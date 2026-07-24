"""PyQtGraph 监控窗口. 唯一允许 import GUI 库的模块.

布局: 左=ΔBx–ΔBy 相图; 右=ΔBx / ΔBy / ΔBz(可折叠) 三个独立时序图。
采集在定时器里 poll 信号源, 重绘固定 ~50 FPS, 与采样率解耦。
"""
import os
import time
import numpy as np
import pyqtgraph as pg
from PyQt5 import QtCore, QtWidgets

from brushbot.monitor.core import RingBuffer, Baseline, derive
from brushbot.monitor.recorder import Recorder
from brushbot.monitor import sources as S

BUF_SECONDS = 60
RATE_HZ = 100
WINDOWS_S = [5, 10, 30, 60]
RATE_TOLERANCE = 0.02     # 测得速率偏离标称值超过这个比例 → 状态栏变黄示警


class MonitorWindow(QtWidgets.QMainWindow):
    def __init__(self, out_dir="recordings"):
        super().__init__()
        self.setWindowTitle("ΔB 实时监控 — 形变量与形变方向")
        self.resize(1400, 820)
        self.out_dir = out_dir
        self.src = None
        self.rb = RingBuffer(BUF_SECONDS * RATE_HZ)
        self.bl = Baseline()
        self.rec = None
        self._rec_started_wall = None     # 本次录制开始的墙钟时间(用于状态栏"已录制"计时)
        # 连上后自动取一次基线, 用"样本自己的时间戳"(而非墙钟, 也不是样本计数)
        # 走够这么多秒就触发——样本计数在慢于 100Hz 的源上要等好几秒才触发,
        # 早就晚于操作员手动取基线+开始录制的时间窗口了。
        self._auto_baseline_s = None          # 还差多少"源自己的秒"触发自动取基线; None=已完成/未安排
        self._auto_baseline_ref_t = None      # 本次连接第一份样本的时间戳(源自己的时钟), 用作 0 点

        self._build_ui()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(20)              # 50 FPS

    # ---------- UI ----------
    def _build_ui(self):
        bar = self.addToolBar("main")
        self.cb_src = QtWidgets.QComboBox()
        self.cb_src.addItems(["串口", "回放", "合成"])
        bar.addWidget(QtWidgets.QLabel(" 源 ")); bar.addWidget(self.cb_src)
        self.ed_port = QtWidgets.QLineEdit("/dev/ttyUSB0"); self.ed_port.setFixedWidth(140)
        bar.addWidget(self.ed_port)
        self.btn_conn = QtWidgets.QPushButton("连接"); bar.addWidget(self.btn_conn)
        self.btn_base = QtWidgets.QPushButton("取基线"); bar.addWidget(self.btn_base)
        self.btn_rec = QtWidgets.QPushButton("● 录制"); bar.addWidget(self.btn_rec)
        self.btn_mark = QtWidgets.QPushButton("标记 START"); bar.addWidget(self.btn_mark)
        bar.addWidget(QtWidgets.QLabel(" 动作名 "))
        self.ed_action = QtWidgets.QLineEdit("line_lr"); self.ed_action.setFixedWidth(110)
        bar.addWidget(self.ed_action)
        bar.addWidget(QtWidgets.QLabel(" 时窗 "))
        self.cb_win = QtWidgets.QComboBox()
        self.cb_win.addItems(["%ds" % w for w in WINDOWS_S]); self.cb_win.setCurrentIndex(1)
        bar.addWidget(self.cb_win)

        self.btn_conn.clicked.connect(self._toggle_connect)
        self.btn_base.clicked.connect(lambda: self._take_baseline())
        self.btn_rec.clicked.connect(self._toggle_record)
        self.btn_mark.clicked.connect(self._toggle_mark)
        self.cb_src.currentIndexChanged.connect(self._sync_controls)

        pg.setConfigOptions(antialias=True, background="#0e1116", foreground="#c9d1d9")
        split = QtWidgets.QSplitter()
        self.p_xy = pg.PlotWidget(title="XY 相图  ΔBx – ΔBy")
        self.p_xy.setAspectLocked(True); self.p_xy.showGrid(x=True, y=True, alpha=0.3)
        self.p_xy.setLabel("bottom", "ΔBx (uT)"); self.p_xy.setLabel("left", "ΔBy (uT)")
        self.c_trail = self.p_xy.plot(pen=pg.mkPen("#3fb950", width=1))
        self.c_vec = self.p_xy.plot(pen=pg.mkPen("#ff4d6d", width=2))
        self.c_pt = self.p_xy.plot(pen=None, symbol="o", symbolSize=9,
                                   symbolBrush="#ff4d6d", symbolPen=None)
        split.addWidget(self.p_xy)

        right = QtWidgets.QWidget(); vb = QtWidgets.QVBoxLayout(right)
        vb.setContentsMargins(0, 0, 0, 0)
        self.p_x = pg.PlotWidget(title="ΔBx"); self.p_y = pg.PlotWidget(title="ΔBy")
        self.p_z = pg.PlotWidget(title="ΔBz")
        self.cur_x = self.p_x.plot(pen=pg.mkPen("#4aa3ff", width=1))
        self.cur_y = self.p_y.plot(pen=pg.mkPen("#ffa64a", width=1))
        self.cur_z = self.p_z.plot(pen=pg.mkPen("#b6bfcc", width=1))
        for p in (self.p_x, self.p_y, self.p_z):
            p.showGrid(x=True, y=True, alpha=0.3); p.setLabel("left", "uT")
        self.p_y.setXLink(self.p_x); self.p_z.setXLink(self.p_x)
        self.chk_z = QtWidgets.QCheckBox("显示 ΔBz"); self.chk_z.setChecked(False)
        self.chk_z.toggled.connect(self.p_z.setVisible); self.p_z.setVisible(False)
        vb.addWidget(self.p_x); vb.addWidget(self.p_y)
        vb.addWidget(self.chk_z); vb.addWidget(self.p_z)
        split.addWidget(right); split.setSizes([560, 840])
        self.setCentralWidget(split)

        self.lbl_read = QtWidgets.QLabel("—")
        self.statusBar().addPermanentWidget(self.lbl_read, 1)
        # 健康信号: 连接状态 / 测得采样率(偏离标称>2%变黄) / 坏行数 / 录制计时——
        # 光看曲线看不出采样率掉了或者串口在丢帧, 这几个数必须常驻在状态栏上。
        self.lbl_health = QtWidgets.QLabel("未连接")
        self.statusBar().addPermanentWidget(self.lbl_health)
        self._sync_controls()

    def _sync_controls(self):
        mode = self.cb_src.currentText()
        self.ed_port.setEnabled(mode == "串口")
        # 录制是否可用取决于**实际已连接的源**, 而非下拉框当前选项——
        # 否则连上回放源后再切下拉框会在不断开的情况下把回放样本录进去。
        # 未连接时才退回用下拉框选项预判。
        if self.src is not None:
            is_replay = isinstance(self.src, S.ReplaySource)
        else:
            is_replay = (mode == "回放")
        self.btn_rec.setEnabled(not is_replay)      # 回放不产生新数据

    # ---------- 源 ----------
    def _toggle_connect(self):
        if self.src is not None:
            self._disconnect(); return
        mode = self.cb_src.currentText()
        try:
            if mode == "串口":
                self.src = S.SerialSource(self.ed_port.text().strip())
            elif mode == "合成":
                self.src = S.synth_writing_B()
            else:
                path, _ = QtWidgets.QFileDialog.getOpenFileName(
                    self, "选择录制的 CSV", "", "CSV (*.csv)")
                if not path:
                    return
                self.src = S.ReplaySource(path)
            self.src.start()
        except Exception as e:
            self.src = None
            self.statusBar().showMessage("打不开信号源: %s" % e, 8000)
            return
        # 基线属于"这一次连接", 不属于窗口本身: 换源时必须整体换掉, 否则会残留
        # 上一个源标定出的 ready/sigma(甚至 b0), 导致门控用错误的 σ 放行方向,
        # 或 ΔB 用错误的 b0 计算。
        self.rb = RingBuffer(BUF_SECONDS * RATE_HZ)
        self.bl = Baseline()
        if isinstance(self.src, S.ReplaySource):
            # 只借用记录自带的 b0 (apply() 不看 ready, 从第一帧起 ΔB 就正确)。
            # 不把 ready 置 True: 若沿用上一个源的旧 sigma (可能为 0), 门控会
            # 失效而放行方向线; 保持 ready=False 让 _redraw 用 gate=inf 抑制方向,
            # 直到 1 秒后的自动重取基线 (_pending_baseline) 产生真实 sigma 为止。
            self.bl.b0 = self.src.b0
        self.btn_conn.setText("断开")
        # 所有源都在采到 1 秒后自动重取基线 —— 回放也要, 否则 sigma 为 0 会让门控失效
        # (记录开头通常是静止段, 重取得到的 b0 与记录自带的基本一致, 但额外拿到 sigma;
        # 回放源的自动取基线用 update_b0=False, 保留记录自带的 b0, 只刷新 sigma)
        self._auto_baseline_s = 1.0
        self._auto_baseline_ref_t = None
        self.statusBar().showMessage("已连接: %s" % self.src.info.get("name"), 4000)
        self._sync_controls()

    def _disconnect(self, note=""):
        if self.rec is not None:
            self._stop_record(valid=False, note=note or "断开连接")
        try:
            self.src.stop()
        except Exception:
            pass
        self.src = None
        self.btn_conn.setText("连接")
        self._sync_controls()

    # ---------- 基线 ----------
    def _take_baseline(self, seconds=1.0, update_b0=True):
        t, B = self.rb.latest(int(seconds * RATE_HZ))
        if len(B) < 10:
            self.statusBar().showMessage("样本不足, 无法取基线", 4000); return
        self.bl.take(B, update_b0=update_b0)
        self.statusBar().showMessage(
            "已取基线 B0=(%.1f, %.1f, %.1f) µT, 门控=%.1f µT"
            % (*self.bl.b0, 3 * self.bl.sigma_norm), 6000)

    # ---------- 录制 ----------
    def _toggle_record(self):
        if self.rec is None:
            if self.src is None:
                self.statusBar().showMessage("请先连接信号源", 4000); return
            if not self.bl.ready:
                self.statusBar().showMessage("请先取基线", 4000); return
            self.rec = Recorder(self.out_dir, self.ed_action.text().strip() or "unnamed",
                                self.bl.b0, self.src.info)
            self._rec_started_wall = time.monotonic()
            self.btn_rec.setText("■ 停止")
            self.btn_base.setEnabled(False)   # 录制中不可重取基线, 否则 JSON 里冻结的
                                               # b0 与后续 CSV 行实际用的 b0 就对不上了
        else:
            self._stop_record()

    def _stop_record(self, valid=True, note=""):
        try:
            csv_path, _ = self.rec.finish(valid=valid, note=note)
            ok = self.rec.verify(csv_path)
            self.statusBar().showMessage(
                ("已保存 %s" % os.path.basename(csv_path)) if ok
                else ("⚠️ 写出的文件自检失败: %s" % csv_path), 8000)
        except Exception as e:
            self.statusBar().showMessage("录制收尾失败: %s" % e, 8000)
        self.rec = None
        self._rec_started_wall = None
        self.btn_rec.setText("● 录制"); self.btn_mark.setText("标记 START")
        self.btn_base.setEnabled(True)

    def _toggle_mark(self):
        if self.rec is None:
            return
        t, _ = self.rb.latest(1)
        if not len(t):
            return
        if self.btn_mark.text().endswith("START"):
            self.rec.mark_start(float(t[-1])); self.btn_mark.setText("标记 STOP")
        else:
            self.rec.mark_stop(float(t[-1])); self.btn_mark.setText("标记 START")

    # ---------- 主循环 ----------
    def _tick(self):
        if self.src is not None:
            try:
                for (t_s, bx, by, bz) in self.src.read():
                    self.rb.append(t_s, (bx, by, bz))
                    if self.rec is not None and self.bl.ready:
                        self.rec.add(t_s, self.bl.apply(np.array([[bx, by, bz]]))[0])
            except Exception as e:
                self.statusBar().showMessage("采集中断: %s" % e, 8000)
                self._disconnect(note=str(e))
            # 待定的自动取基线: 录制中绝不能触发(会让 JSON 冻结的 b0 与录制中途
            # 实际使用的 b0 对不上, 且 verify() 看不出这种损坏), 因此录制期间整体
            # 跳过——包括参考时间点的采集, 计时在录制结束后从当前样本重新起算。
            # 触发条件用"源自己时间戳"的已过秒数, 而不是样本计数: 按样本数算的话,
            # 任何慢于 100Hz 的源都要等好几秒才触发, 早就晚于操作员手动取基线+
            # 开始录制的时间窗口了。
            if self._auto_baseline_s is not None and self.rec is None and self.rb.n_total > 0:
                t_latest, _ = self.rb.latest(1)
                now_t = float(t_latest[-1])
                if self._auto_baseline_ref_t is None:
                    self._auto_baseline_ref_t = now_t
                elif now_t - self._auto_baseline_ref_t >= self._auto_baseline_s:
                    self._auto_baseline_s = None
                    # 回放源: 保留记录自带的 b0(逐点复现原始 ΔB), 只用这次自动
                    # 取基线刷新一份真实 sigma 用于方向门控(见 core.Baseline.take)。
                    self._take_baseline(update_b0=not isinstance(self.src, S.ReplaySource))
        self._redraw()
        self._update_health()

    def _redraw(self):
        win_s = WINDOWS_S[self.cb_win.currentIndex()]
        t, B = self.rb.latest(win_s * RATE_HZ)
        if len(t) == 0:
            return
        dB = self.bl.apply(B)
        self.cur_x.setData(t, dB[:, 0])
        self.cur_y.setData(t, dB[:, 1])
        if self.p_z.isVisible():
            self.cur_z.setData(t, dB[:, 2])

        n_trail = min(len(dB), 2 * RATE_HZ)
        self.c_trail.setData(dB[-n_trail:, 0], dB[-n_trail:, 1])
        last = dB[-1]
        # 未取基线前 dB 实际是原始 B(apply 减的是全零 b0), 门控必须无穷大以
        # 完全抑制方向线, 否则会把原始 B 的方向当成有效形变画出来。
        gate = 3.0 * self.bl.sigma_norm if self.bl.ready else float("inf")
        d = derive(last, gate)
        self.c_pt.setData([last[0]], [last[1]])
        if d["phi_deg"] is None:
            self.c_vec.setData([], [])
        else:
            self.c_vec.setData([0.0, last[0]], [0.0, last[1]])
        self.lbl_read.setText(
            "|ΔB| %.1f   |ΔBxy| %.1f   φ %s   θ %s   ΔBx %.1f  ΔBy %.1f  ΔBz %.1f   "
            "缓冲 %d   门控 %s"
            % (d["mag"], d["mag_xy"],
               "—" if d["phi_deg"] is None else "%.1f°" % d["phi_deg"],
               "—" if d["theta_deg"] is None else "%.1f°" % d["theta_deg"],
               last[0], last[1], last[2], self.rb.n_total,
               "— µT" if not np.isfinite(gate) else "%.1f µT" % gate))

    def measured_rate_hz(self):
        """由样本自己的时间戳测得的实际采样率; 样本不足时返回 None.

        这是操作员判断"采集是否健康"的唯一实时信号——曲线本身看不出掉速。
        """
        t, _ = self.rb.latest(2 * RATE_HZ)
        if len(t) < 2:
            return None
        span = float(t[-1] - t[0])
        return (len(t) - 1) / span if span > 1e-9 else None

    def _update_health(self):
        """状态栏健康区: 连接状态 / 实测 Hz(偏离标称 >2% 变黄) / 坏行数 / 录制计时."""
        if self.src is None:
            self.lbl_health.setText("未连接")
            self.lbl_health.setStyleSheet("")
            return
        parts = ["● %s" % self.src.info.get("name", "?")]
        nominal = float(self.src.info.get("nominal_rate_hz") or RATE_HZ)
        rate = self.measured_rate_hz()
        off_nominal = False
        if rate is None:
            parts.append("— Hz")
        else:
            parts.append("%.1f Hz" % rate)
            off_nominal = nominal > 0 and abs(rate - nominal) / nominal > RATE_TOLERANCE
        bad = getattr(self.src, "bad_lines", None)      # 只有串口源有这个计数
        if bad is not None:
            parts.append("坏行 %d" % bad)
        if self.rec is not None and self._rec_started_wall is not None:
            parts.append("录制中 %.1fs" % (time.monotonic() - self._rec_started_wall))
        self.lbl_health.setText("  ·  ".join(parts))
        self.lbl_health.setStyleSheet("color: #d29922;" if off_nominal else "")


def main(argv=None) -> int:
    app = QtWidgets.QApplication(argv or [])
    w = MonitorWindow()
    w.show()
    return app.exec_()
