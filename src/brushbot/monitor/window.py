"""PyQtGraph 监控窗口. 唯一允许 import GUI 库的模块.

布局: 上=归一化 XY 单位圆 + 接触指示; 下=ΔBx/ΔBy/|ΔBxy|/ΔBz 时序
采集在定时器里 poll 信号源, 重绘固定 ~50 FPS, 与采样率解耦。
"""
import os
import time
import numpy as np
import pyqtgraph as pg
from PyQt5 import QtCore, QtGui, QtWidgets

from brushbot.monitor.core import RingBuffer, Baseline, EMA, derive
from brushbot.monitor.recorder import Recorder
from brushbot.monitor import sources as S

BUF_SECONDS = 60
RATE_HZ = 100
WINDOWS_S = [2, 5, 10, 20]
RATE_TOLERANCE = 0.02


class MonitorWindow(QtWidgets.QMainWindow):
    def __init__(self, out_dir="recordings"):
        super().__init__()
        self.setWindowTitle("ΔB 实时监控")
        self.resize(1200, 780)
        self.out_dir = out_dir
        self.src = None
        self.rb = RingBuffer(BUF_SECONDS * RATE_HZ)
        self.bl = Baseline()
        self.ema = EMA(alpha=0.3)
        self._src_mode = "回放"
        self._norm_radius = 0.0
        self._xy_alpha = 0.06
        self._prev_norm = None
        self._paused = False
        self._pause_t0 = None
        self.rec = None
        self._rec_started_wall = None
        self._auto_baseline_s = None
        self._auto_baseline_ref_t = None

        self._build_ui()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(20)

    # ---------- UI ----------
    def _build_ui(self):
        bar = self.addToolBar("main")
        self.btn_src_serial = QtWidgets.QPushButton("串口"); self.btn_src_serial.setCheckable(True)
        self.btn_src_replay = QtWidgets.QPushButton("回放"); self.btn_src_replay.setCheckable(True)
        self.btn_src_synth = QtWidgets.QPushButton("合成"); self.btn_src_synth.setCheckable(True)
        for b in (self.btn_src_serial, self.btn_src_replay, self.btn_src_synth):
            b.setFixedWidth(52); bar.addWidget(b)
        self.btn_src_replay.setChecked(True)
        self.ed_port = QtWidgets.QLineEdit("/dev/ttyUSB0"); self.ed_port.setFixedWidth(140)
        bar.addWidget(self.ed_port)
        self.btn_conn = QtWidgets.QPushButton("连接"); bar.addWidget(self.btn_conn)
        self.btn_restart = QtWidgets.QPushButton("⟳ 重放"); self.btn_restart.setEnabled(False)
        bar.addWidget(self.btn_restart)
        self.btn_base = QtWidgets.QPushButton("取基线(B)"); bar.addWidget(self.btn_base)
        self.btn_rec = QtWidgets.QPushButton("● 录制(R)"); bar.addWidget(self.btn_rec)
        self.btn_mark = QtWidgets.QPushButton("标记(M)"); bar.addWidget(self.btn_mark)
        self.btn_pause = QtWidgets.QPushButton("⏸ 暂停"); self.btn_pause.setCheckable(True)
        bar.addWidget(self.btn_pause)
        bar.addWidget(QtWidgets.QLabel(" 动作 "))
        self.ed_action = QtWidgets.QLineEdit("line_lr"); self.ed_action.setFixedWidth(90)
        bar.addWidget(self.ed_action)
        bar.addWidget(QtWidgets.QLabel(" 时窗 "))
        self.cb_win = QtWidgets.QComboBox()
        self.cb_win.addItems(["%ds" % w for w in WINDOWS_S]); self.cb_win.setCurrentIndex(1)
        bar.addWidget(self.cb_win)
        bar.addWidget(QtWidgets.QLabel(" 滤波α "))
        self.cb_alpha = QtWidgets.QComboBox()
        self.cb_alpha.addItems(["0.05","0.10","0.20","0.30","0.50","0.70","1.00"])
        self.cb_alpha.setCurrentIndex(3); self.cb_alpha.setFixedWidth(70)
        bar.addWidget(self.cb_alpha)
        bar.addWidget(QtWidgets.QLabel(" XYα "))
        self.cb_xy_alpha = QtWidgets.QComboBox()
        self.cb_xy_alpha.addItems(["0.03","0.06","0.12","0.20","0.35","0.55","0.80"])
        self.cb_xy_alpha.setCurrentIndex(1); self.cb_xy_alpha.setFixedWidth(70)  # 0.06
        bar.addWidget(self.cb_xy_alpha)
        bar.addWidget(QtWidgets.QLabel(" 倍速 "))
        self.cb_speed = QtWidgets.QComboBox()
        self.cb_speed.addItems(["0.25x","0.5x","1x","2x","4x","8x"])
        self.cb_speed.setCurrentIndex(2); self.cb_speed.setFixedWidth(70)
        bar.addWidget(self.cb_speed)

        self.btn_conn.clicked.connect(self._toggle_connect)
        self.btn_restart.clicked.connect(self._restart)
        self.btn_base.clicked.connect(lambda: self._take_baseline())
        self.btn_rec.clicked.connect(self._toggle_record)
        self.btn_mark.clicked.connect(self._toggle_mark)
        self.btn_pause.toggled.connect(self._set_pause)
        self.btn_src_serial.clicked.connect(lambda: self._set_src_mode("串口"))
        self.btn_src_replay.clicked.connect(lambda: self._set_src_mode("回放"))
        self.btn_src_synth.clicked.connect(lambda: self._set_src_mode("合成"))
        self.cb_alpha.currentTextChanged.connect(self._set_alpha)
        self.cb_xy_alpha.currentTextChanged.connect(self._set_xy_alpha)
        self.cb_speed.currentTextChanged.connect(self._set_speed)

        pg.setConfigOptions(antialias=True, background="#0e1116", foreground="#c9d1d9")

        # ===== 上半: 归一化 XY 圆(左) + 空隙(右) =====
        h_top = QtWidgets.QSplitter(); h_top.setOrientation(QtCore.Qt.Horizontal)

        self.p_xy = pg.PlotWidget(title="形变方向（归一化）")
        self.p_xy.setAspectLocked(True); self.p_xy.showGrid(x=True, y=True, alpha=0.2)
        self.p_xy.setLabel("bottom", "ΔBx / max"); self.p_xy.setLabel("left", "ΔBy / max")
        theta = np.linspace(0, 2*np.pi, 200)
        self.c_circle = self.p_xy.plot(np.cos(theta), np.sin(theta),
                                        pen=pg.mkPen("#484f58", width=1, style=QtCore.Qt.DashLine))
        self.c_vec = self.p_xy.plot(pen=pg.mkPen("#ff4d6d", width=2))
        self.c_pt = self.p_xy.plot(pen=None, symbol="o", symbolSize=12,
                                    symbolBrush="#ff4d6d", symbolPen=None)
        self.p_xy.disableAutoRange()
        self.p_xy.setXRange(-1.1, 1.1, padding=0); self.p_xy.setYRange(-1.1, 1.1, padding=0)
        self.p_xy.getViewBox().setMouseEnabled(x=False, y=False)  # 禁止鼠标拖拽/滚轮缩放
        # 接触指示: 小圆叠在单位圆左上
        self.contact_dot = pg.ScatterPlotItem(size=16)
        self.contact_dot.setData([0.92], [0.92])
        self.p_xy.addItem(self.contact_dot)
        h_top.addWidget(self.p_xy)

        # 右侧空白占位(保持单位圆不会太扁)
        spacer = QtWidgets.QWidget(); h_top.addWidget(spacer)
        h_top.setSizes([500, 200])

        # ===== 下半: ΔBx / ΔBy / |ΔBxy| / ΔBz =====
        bot = QtWidgets.QWidget(); vb = QtWidgets.QVBoxLayout(bot)
        vb.setContentsMargins(0, 0, 0, 0)
        self.p_x = pg.PlotWidget(title="ΔBx"); self.p_y = pg.PlotWidget(title="ΔBy")
        self.p_mag = pg.PlotWidget(title="|ΔBxy| 幅度"); self.p_z = pg.PlotWidget(title="ΔBz")
        self.cur_x = self.p_x.plot(pen=pg.mkPen("#4aa3ff", width=1))
        self.cur_y = self.p_y.plot(pen=pg.mkPen("#ffa64a", width=1))
        self.cur_mag = self.p_mag.plot(pen=pg.mkPen("#3fb950", width=1.5))
        self.cur_z = self.p_z.plot(pen=pg.mkPen("#b6bfcc", width=1))
        for p in (self.p_x, self.p_y, self.p_mag, self.p_z):
            p.showGrid(x=True, y=True, alpha=0.3); p.setLabel("left", "uT")
            p.getViewBox().setAutoVisible(y=True)
        self.p_x.disableAutoRange(axis='x')
        self.p_y.setXLink(self.p_x); self.p_mag.setXLink(self.p_x); self.p_z.setXLink(self.p_x)
        self.chk_mag = QtWidgets.QCheckBox("显示 |ΔBxy| 幅度"); self.chk_mag.setChecked(False)
        self.chk_mag.toggled.connect(self.p_mag.setVisible); self.p_mag.setVisible(False)
        self.chk_z = QtWidgets.QCheckBox("显示 ΔBz"); self.chk_z.setChecked(False)
        self.chk_z.toggled.connect(self.p_z.setVisible); self.p_z.setVisible(False)
        vb.addWidget(self.p_x); vb.addWidget(self.p_y)
        vb.addWidget(self.chk_mag); vb.addWidget(self.p_mag)
        vb.addWidget(self.chk_z); vb.addWidget(self.p_z)

        v_split = QtWidgets.QSplitter(); v_split.setOrientation(QtCore.Qt.Vertical)
        v_split.addWidget(h_top); v_split.addWidget(bot)
        v_split.setSizes([360, 420])
        self.setCentralWidget(v_split)

        self.lbl_read = QtWidgets.QLabel("—")
        self.statusBar().addPermanentWidget(self.lbl_read, 1)
        self.lbl_contact = QtWidgets.QLabel(" 悬空 ")
        self.lbl_contact.setStyleSheet("background:#30363d;color:#8b949e;padding:2px 8px;border-radius:3px;")
        self.statusBar().addPermanentWidget(self.lbl_contact)
        self.lbl_health = QtWidgets.QLabel("未连接")
        self.statusBar().addPermanentWidget(self.lbl_health)
        self._sync_controls()

    # ---- 键盘快捷键 ----
    def keyPressEvent(self, ev: QtGui.QKeyEvent):
        k = ev.key()
        if k == QtCore.Qt.Key_Space:
            self.btn_pause.toggle()
        elif k == QtCore.Qt.Key_B:
            self._take_baseline()
        elif k == QtCore.Qt.Key_R:
            self._toggle_record()
        elif k == QtCore.Qt.Key_M:
            self._toggle_mark()
        elif QtCore.Qt.Key_1 <= k <= QtCore.Qt.Key_4:
            self.cb_win.setCurrentIndex(k - QtCore.Qt.Key_1)
        else:
            super().keyPressEvent(ev)

    def _set_pause(self, paused: bool):
        self._paused = paused
        if paused:
            self._pause_t0 = time.monotonic()
            self.btn_pause.setText("▶ 继续")
        else:
            self._pause_t0 = None
            self.btn_pause.setText("⏸ 暂停")

    # ---- 源模式 / 控制同步 ----
    def _sync_controls(self):
        mode = self._src_mode
        self.ed_port.setEnabled(mode == "串口")
        if self.src is not None:
            is_replay = isinstance(self.src, S.ReplaySource)
        else:
            is_replay = (mode == "回放")
        self.btn_rec.setEnabled(not is_replay)
        self.cb_speed.setEnabled(mode != "串口")
        for b, m in [(self.btn_src_serial, "串口"), (self.btn_src_replay, "回放"),
                     (self.btn_src_synth, "合成")]:
            b.setChecked(m == mode)
            b.setEnabled(self.src is None)

    def _set_src_mode(self, mode: str):
        if self.src is not None:
            return
        self._src_mode = mode
        self._sync_controls()

    def _restart(self):
        if self.src is not None and hasattr(self.src, "seek"):
            self.src.seek(0)
            self._norm_radius = 0.0
            self._prev_norm = None
            self._paused = False; self.btn_pause.setChecked(False)
            # 立即清空 XY 图, 避免重放间歇残留上一个回放的最后位置
            self.c_pt.setData([], [])
            self.c_vec.setData([], [])
            self.statusBar().showMessage("已重放", 2000)

    def _set_alpha(self, text: str):
        self.ema = EMA(alpha=float(text))

    def _set_xy_alpha(self, text: str):
        self._xy_alpha = float(text)

    def _set_speed(self, text: str):
        mult = float(text.replace("x", ""))
        if self.src is not None and hasattr(self.src, "set_rate"):
            self.src.set_rate(mult)
            self.statusBar().showMessage("倍速 %.2gx" % mult, 2000)

    # ---------- 源 ----------
    def _toggle_connect(self):
        if self.src is not None:
            self._disconnect(); return
        mode = self._src_mode
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
        self.rb = RingBuffer(BUF_SECONDS * RATE_HZ)
        self.bl = Baseline()
        self.ema = EMA(alpha=float(self.cb_alpha.currentText()))
        if isinstance(self.src, S.ReplaySource):
            self.bl.b0 = self.src.b0
        self.btn_conn.setText("断开")
        self.btn_restart.setEnabled(hasattr(self.src, "seek"))
        self._norm_radius = 0.0
        self._prev_norm = None
        self._paused = False; self.btn_pause.setChecked(False)
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
        self.btn_restart.setEnabled(False)
        self._paused = False; self.btn_pause.setChecked(False)
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
            self.btn_rec.setText("■ 停止(R)")
            self.btn_base.setEnabled(False)
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
        self.rec = None; self._rec_started_wall = None
        self.btn_rec.setText("● 录制(R)"); self.btn_mark.setText("标记(M)")
        self.btn_base.setEnabled(True)

    def _toggle_mark(self):
        if self.rec is None:
            return
        t, _ = self.rb.latest(1)
        if not len(t):
            return
        if self.btn_mark.text().startswith("标记(M)"):
            self.rec.mark_start(float(t[-1])); self.btn_mark.setText("标记 STOP(M)")
        else:
            self.rec.mark_stop(float(t[-1])); self.btn_mark.setText("标记(M)")

    # ---------- 主循环 ----------
    def _tick(self):
        if self.src is not None and not self._paused:
            try:
                for (t_s, bx, by, bz) in self.src.read():
                    self.rb.append(t_s, (bx, by, bz))
                    if self.rec is not None and self.bl.ready:
                        self.rec.add(t_s, self.bl.apply(np.array([[bx, by, bz]]))[0])
            except Exception as e:
                self.statusBar().showMessage("采集中断: %s" % e, 8000)
                self._disconnect(note=str(e))
            if self._auto_baseline_s is not None and self.rec is None and self.rb.n_total > 0:
                t_latest, _ = self.rb.latest(1)
                now_t = float(t_latest[-1])
                if self._auto_baseline_ref_t is None:
                    self._auto_baseline_ref_t = now_t
                elif now_t - self._auto_baseline_ref_t >= self._auto_baseline_s:
                    self._auto_baseline_s = None
                    self._take_baseline(update_b0=not isinstance(self.src, S.ReplaySource))
        # 暂停时 read() 不调用, _t0 自动对轨, 恢复时无缝继续
        self._redraw()
        self._update_health()

    def _redraw(self):
        win_s = WINDOWS_S[self.cb_win.currentIndex()]
        t, B = self.rb.latest(win_s * RATE_HZ)
        if len(t) == 0:
            return
        dB = self.bl.apply(B)
        # EMA 平滑时间序列
        self.ema.reset()
        dB_smooth = self.ema.update(dB)
        mag_xy = np.hypot(dB_smooth[:, 0], dB_smooth[:, 1])

        self.cur_x.setData(t, dB_smooth[:, 0])
        self.cur_y.setData(t, dB_smooth[:, 1])
        if self.p_mag.isVisible():
            self.cur_mag.setData(t, mag_xy)
        if self.p_z.isVisible():
            self.cur_z.setData(t, dB_smooth[:, 2])

        gate = 3.0 * self.bl.sigma_norm if self.bl.ready else float("inf")
        last = dB[-1]
        d = derive(last, gate)
        # 归一化半径
        mag_xy_raw = np.hypot(dB[:, 0], dB[:, 1])
        if len(mag_xy_raw):
            self._norm_radius = max(self._norm_radius, float(mag_xy_raw.max()))

        # —— 归一化 XY 圆 ——
        if self._norm_radius > 1e-9:
            nx, ny = last[0] / self._norm_radius, last[1] / self._norm_radius
            if self._prev_norm is None:
                self._prev_norm = (nx, ny)
            a = self._xy_alpha
            sx = a * nx + (1 - a) * self._prev_norm[0]
            sy = a * ny + (1 - a) * self._prev_norm[1]
            self._prev_norm = (sx, sy)
            self.c_pt.setData([sx], [sy])
            self.c_vec.setData([0.0, sx], [0.0, sy])
        else:
            self.c_pt.setData([], [])
            self.c_vec.setData([], [])

        # 接触指示
        in_contact = d["mag_xy"] >= gate if np.isfinite(gate) else False
        if in_contact:
            self.contact_dot.setBrush(pg.mkBrush("#3fb950"))
            self.lbl_contact.setText(" 接触 ")
            self.lbl_contact.setStyleSheet(
                "background:#1a3a1a;color:#3fb950;font-weight:bold;padding:2px 8px;border-radius:3px;")
        else:
            self.contact_dot.setBrush(pg.mkBrush("#484f58"))
            self.lbl_contact.setText(" 悬空 ")
            self.lbl_contact.setStyleSheet(
                "background:#30363d;color:#8b949e;padding:2px 8px;border-radius:3px;")

        self.lbl_read.setText(
            "|ΔB| %.0f  |ΔBxy| %.0f  φ %s°  θ %s°  半径 %.0f µT  门控 %.0f µT  %s"
            % (d["mag"], d["mag_xy"],
               "—" if d["phi_deg"] is None else "%.1f" % d["phi_deg"],
               "—" if d["theta_deg"] is None else "%.1f" % d["theta_deg"],
               self._norm_radius, gate if np.isfinite(gate) else 0.0,
               "⏸" if self._paused else ""))
        # X 轴滚动
        if len(t) >= 2:
            self.p_x.setXRange(float(t[-1]) - win_s, float(t[-1]), padding=0)
        # Y 轴对称自适应
        Y_FLOOR = 50.0
        channels = [(dB_smooth[:, 0], self.p_x), (dB_smooth[:, 1], self.p_y)]
        if self.p_mag.isVisible():
            channels.append((mag_xy, self.p_mag))
        if self.p_z.isVisible():
            channels.append((dB_smooth[:, 2], self.p_z))
        for ch_v, cur in channels:
            if len(ch_v):
                mx = max(float(np.abs(ch_v).max()), Y_FLOOR)
                cur.getViewBox().setYRange(-mx, mx, padding=0)

    def measured_rate_hz(self):
        t, _ = self.rb.latest(2 * RATE_HZ)
        if len(t) < 2:
            return None
        span = float(t[-1] - t[0])
        return (len(t) - 1) / span if span > 1e-9 else None

    def _update_health(self):
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
        bad = getattr(self.src, "bad_lines", None)
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
