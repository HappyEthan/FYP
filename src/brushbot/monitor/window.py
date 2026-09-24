"""PyQtGraph 监控窗口. 唯一允许 import GUI 库的模块.

布局: 左=实验操作; 中=XY 方向/幅值; 右=联动磁场时序。
采集在定时器里 poll 信号源, 重绘固定 ~50 FPS, 与采样率解耦。
"""
import os
import argparse
import time
import numpy as np
import pyqtgraph as pg
from PyQt5 import QtCore, QtGui, QtWidgets

from brushbot.monitor.core import (RingBuffer, Baseline, EMA, derive,
                                   frame_quality_mask, robust_symmetric_limit)
from brushbot.monitor.recorder import Recorder
from brushbot.monitor import sources as S
from brushbot.monitor.experiment_panel import ExperimentPanel
from brushbot.monitor.cartesian_return_panel import CartesianReturnPanel
from brushbot.monitor.control import MonitorControlServer

BUF_SECONDS = 60
RATE_HZ = 100
MAX_EXPECTED_RATE_HZ = 500
WINDOWS_S = [2, 5, 10, 20]
RATE_TOLERANCE = 0.02


class MonitorWindow(QtWidgets.QMainWindow):
    def __init__(self, out_dir="recordings", config_dir="configs", *,
                 experiment_service=None, experiment_setup=None,
                 control_socket="/tmp/brushbot-monitor.sock"):
        super().__init__()
        self.setWindowTitle("ΔB 实时监控")
        self.resize(1200, 780)
        self.out_dir = out_dir
        self.config_dir = config_dir
        self.experiment_service = experiment_service
        self.experiment_setup = experiment_setup or {}
        self.src = None
        self.rb = RingBuffer(BUF_SECONDS * MAX_EXPECTED_RATE_HZ)
        self.bl = Baseline()
        self.ema = EMA(alpha=1.0)
        self._src_mode = "回放"
        self._circle_radius = 400.0
        self._paused = False
        self._pause_t0 = None
        self.rec = None
        self._rec_started_wall = None
        self._auto_baseline_s = None
        self._auto_baseline_ref_t = None
        self._display_bad_frames = 0
        self._latest_frame_valid = True
        self.control_server = MonitorControlServer(control_socket)

        self._build_ui()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(20)
        try:
            self.control_server.start()
        except OSError:
            # A restricted/offline test environment may disallow local sockets.
            self.control_server = None

    # ---------- UI ----------
    def _build_ui(self):
        self.setWindowTitle("Brushbot · 磁触觉实验工作台")
        self.resize(1360, 860)
        self.setMinimumSize(1000, 680)
        self.setStyleSheet("""
            QMainWindow, QWidget#workspace { background: #101820; color: #dce6f0; }
            QWidget { color: #dce6f0; font-size: 13px; }
            QDockWidget { font-weight: bold; }
            QDockWidget::title { background: #18232e; padding: 10px; }
            QGroupBox { background: #18232e; border: 1px solid #2a3948;
                        border-radius: 8px; margin-top: 16px; padding: 14px 10px 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
            QLabel { background: transparent; }
            QLabel#muted { color: #94a8ba; }
            QLabel#heading { font-size: 19px; font-weight: bold; }
            QPushButton, QToolButton { background: #243443; border: 1px solid #3a4d60;
                        border-radius: 5px; padding: 7px 10px; }
            QPushButton:hover, QToolButton:hover { background: #30475b; }
            QPushButton:checked, QToolButton:checked { background: #225a59;
                        border-color: #42b7aa; color: #cefff4; }
            QPushButton:disabled, QToolButton:disabled { color: #728292;
                        background: #1a2732; border-color: #2b3947; }
            QPushButton#primary { background: #20796d; border-color: #42b7aa; }
            QPushButton#primary:disabled { background: #1a3538; color: #748f91; }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { background: #101b25;
                        border: 1px solid #3a4d60; border-radius: 4px; padding: 6px; }
            QLineEdit:disabled, QComboBox:disabled { color: #728292; }
            QComboBox QAbstractItemView { background: #18232e; selection-background-color: #225a59; }
            QCheckBox { spacing: 6px; }
            QScrollArea { border: none; background: #101820; }
            QScrollBar:vertical { background: #101820; width: 10px; margin: 0; }
            QScrollBar::handle:vertical { background: #3a4d60; min-height: 24px; border-radius: 4px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: #101820; }
            QStatusBar { background: #18232e; color: #94a8ba; }
            QStatusBar::item { border: none; }
            QSplitter::handle { background: #2a3948; }
            QToolTip { background: #e4edf5; color: #17212c; border: none; }
        """)

        def hint(text):
            label = QtWidgets.QLabel(text)
            label.setObjectName("muted")
            label.setWordWrap(True)
            return label

        workspace = QtWidgets.QWidget()
        workspace.setObjectName("workspace")
        root = QtWidgets.QVBoxLayout(workspace)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(12)
        self.setCentralWidget(workspace)

        heading = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("磁触觉实验工作台")
        title.setObjectName("heading")
        heading.addWidget(title)
        heading.addStretch()
        self.btn_panel = QtWidgets.QToolButton()
        heading.addWidget(self.btn_panel)
        root.addLayout(heading)

        source = QtWidgets.QGroupBox("数据源")
        source_row = QtWidgets.QHBoxLayout(source)
        self.btn_src_serial = QtWidgets.QPushButton("串口")
        self.btn_src_replay = QtWidgets.QPushButton("回放")
        for button in (self.btn_src_serial, self.btn_src_replay):
            button.setCheckable(True)
            source_row.addWidget(button)
        self.ed_port = QtWidgets.QLineEdit("/dev/ttyACM0")
        self.ed_port.setPlaceholderText("串口设备路径")
        self.ed_port.setMaximumWidth(190)
        self.ed_port.setToolTip("输入传感器串口路径，例如 /dev/ttyACM0")
        source_row.addWidget(self.ed_port)
        self.lbl_source = hint("打开 CSV 与配套 JSON 开始回放")
        self.lbl_source.setMinimumWidth(0)
        self.lbl_source.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        source_row.addWidget(self.lbl_source, 1)
        self.btn_conn = QtWidgets.QPushButton("打开回放…")
        self.btn_conn.setObjectName("primary")
        source_row.addWidget(self.btn_conn)
        root.addWidget(source)

        # 操作侧栏独立于数据源。
        self.operations = QtWidgets.QDockWidget("实验操作", self)
        self.operations.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea)
        self.operations.setFeatures(QtWidgets.QDockWidget.DockWidgetClosable)
        self.operations.setMinimumWidth(240)
        self.operations.setMaximumWidth(300)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        sidebar = QtWidgets.QWidget()
        sidebar.setObjectName("workspace")
        side = QtWidgets.QVBoxLayout(sidebar)
        side.setContentsMargins(10, 10, 10, 10)
        side.setSpacing(14)
        scroll.setWidget(sidebar)
        self.operations.setWidget(scroll)
        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self.operations)
        action = self.operations.toggleViewAction()
        action.setText("实验操作")
        self.btn_panel.setDefaultAction(action)

        baseline = QtWidgets.QGroupBox("01  基线")
        base_layout = QtWidgets.QVBoxLayout(baseline)
        self.lbl_baseline = hint("连接数据源后取空载基线")
        base_layout.addWidget(self.lbl_baseline)
        self.btn_base = QtWidgets.QPushButton("取基线  B")
        base_layout.addWidget(self.btn_base)
        side.addWidget(baseline)

        recording = QtWidgets.QGroupBox("02  录制")
        rec_layout = QtWidgets.QVBoxLayout(recording)
        self.btn_rec = QtWidgets.QPushButton("开始录制")
        self.btn_rec.setObjectName("primary")
        rec_layout.addWidget(self.btn_rec)
        self.lbl_recording = hint("先连接数据源并取基线")
        rec_layout.addWidget(self.lbl_recording)
        rec_layout.addWidget(hint("保存位置：" + os.path.abspath(self.out_dir)))
        side.addWidget(recording)

        self.experiment_panel = ExperimentPanel(
            self.experiment_service, self.experiment_setup, self)
        side.addWidget(self.experiment_panel)
        initial_return_pose = self.experiment_setup.get("return_pose_mm_deg")
        if initial_return_pose is None:
            orientation = self.experiment_setup.get("vertical_rpy_rad", [0.0, 0.0, 0.0])
            initial_return_pose = [
                self.experiment_setup.get("origin_x_mm", 0.0),
                self.experiment_setup.get("origin_y_mm", 0.0),
                self.experiment_setup.get("wait_z_mm", 0.0),
                *np.degrees(np.asarray(orientation, dtype=float)).tolist(),
            ]
        self.cartesian_return_panel = CartesianReturnPanel(
            self.experiment_service, initial_return_pose, self)
        side.addWidget(self.cartesian_return_panel)

        # 播放 / 采集暂停使用同一入口，但清楚标注原有暂停语义。
        transport = QtWidgets.QHBoxLayout()
        self.btn_pause = QtWidgets.QPushButton("暂停")
        self.btn_pause.setCheckable(True)
        transport.addWidget(self.btn_pause)
        self._group_replay = QtWidgets.QWidget()
        playback = QtWidgets.QHBoxLayout(self._group_replay)
        playback.setContentsMargins(0, 0, 0, 0)
        self.btn_restart = QtWidgets.QPushButton("从头播放")
        playback.addWidget(self.btn_restart)
        playback.addWidget(QtWidgets.QLabel("倍速"))
        self.cb_speed = QtWidgets.QComboBox()
        self.cb_speed.addItems(["0.25x", "0.5x", "1x", "2x", "4x", "8x"])
        self.cb_speed.setCurrentIndex(2)
        playback.addWidget(self.cb_speed)
        transport.addWidget(self._group_replay)
        transport.addStretch()
        root.addLayout(transport)

        pg.setConfigOptions(antialias=True, background="#101820", foreground="#c9d8e6")
        plots = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        plots.setChildrenCollapsible(False)
        plots.setHandleWidth(6)
        root.addWidget(plots, 1)

        xy = QtWidgets.QGroupBox("XY 方向与幅值")
        xy.setMinimumWidth(280)
        xy_layout = QtWidgets.QVBoxLayout(xy)
        xy_form = QtWidgets.QFormLayout()
        self.sp_radius = QtWidgets.QSpinBox()
        self.sp_radius.setRange(50, 20000)
        self.sp_radius.setSingleStep(50)
        self.sp_radius.setValue(400)
        self.sp_radius.setSuffix(" µT")
        xy_form.addRow("显示圆半径", self.sp_radius)
        xy_layout.addLayout(xy_form)
        side.addStretch()
        side.addWidget(hint("快捷键\n空格 暂停 / 继续 · B 基线\nR 录制 · 1–4 时窗"))

        self.p_xy = pg.PlotWidget()
        self.p_xy.setAspectLocked(True)
        self.p_xy.showGrid(x=True, y=True, alpha=0.2)
        self.p_xy.setLabel("bottom", "ΔBx (µT)")
        self.p_xy.setLabel("left", "ΔBy (µT)")
        theta = np.linspace(0, 2*np.pi, 200)
        self.c_circle = self.p_xy.plot(self._circle_radius*np.cos(theta),
                                      self._circle_radius*np.sin(theta),
                                      pen=pg.mkPen("#516679", width=1, style=QtCore.Qt.DashLine))
        self.c_vec = self.p_xy.plot(pen=pg.mkPen("#42d7ba", width=2))
        self.c_pt = self.p_xy.plot(pen=None, symbol="o", symbolSize=11,
                                  symbolBrush="#42d7ba", symbolPen=None)
        self.p_xy.disableAutoRange()
        pad = self._circle_radius * 1.15
        self.p_xy.setXRange(-pad, pad, padding=0)
        self.p_xy.setYRange(-pad, pad, padding=0)
        self.p_xy.getViewBox().setMouseEnabled(x=False, y=False)
        self.contact_dot = pg.ScatterPlotItem(size=12)
        self.contact_dot.setData([self._circle_radius*.92], [self._circle_radius*.92])
        self.p_xy.addItem(self.contact_dot)
        xy_layout.addWidget(self.p_xy, 1)
        self.lbl_contact = QtWidgets.QLabel("阈值状态：待基线")
        self.lbl_contact.setToolTip("沿用现有磁幅值阈值判定，不等同于独立验证的物理接触")
        xy_layout.addWidget(self.lbl_contact)
        self.lbl_read = hint("等待数据：幅值、方向与门控阈值将在此显示")
        xy_layout.addWidget(self.lbl_read)
        plots.addWidget(xy)

        timeseries = QtWidgets.QGroupBox("磁场时序")
        timeseries.setMinimumWidth(330)
        series_layout = QtWidgets.QVBoxLayout(timeseries)
        options = QtWidgets.QGridLayout()
        self.cb_win = QtWidgets.QComboBox()
        self.cb_win.addItems(["%ds" % w for w in WINDOWS_S])
        self.cb_win.setCurrentIndex(1)
        self.cb_alpha = QtWidgets.QComboBox()
        self.cb_alpha.addItems(["原始", "0.05", "0.10", "0.20", "0.30", "0.50", "0.70", "1.00"])
        self.cb_alpha.setCurrentIndex(0)
        self.cb_alpha.setToolTip("EMA 显示平滑；数值越小平滑越强，原始录制不受影响")
        options.addWidget(QtWidgets.QLabel("时窗"), 0, 0)
        options.addWidget(self.cb_win, 0, 1)
        options.addWidget(QtWidgets.QLabel("时序平滑 α"), 1, 0)
        options.addWidget(self.cb_alpha, 1, 1)
        series_layout.addLayout(options)
        channels = QtWidgets.QHBoxLayout()
        channels.addWidget(hint("附加通道"))
        self.chk_mag = QtWidgets.QCheckBox("|ΔBxy|")
        self.chk_z = QtWidgets.QCheckBox("ΔBz")
        channels.addWidget(self.chk_mag)
        channels.addWidget(self.chk_z)
        channels.addStretch()
        series_layout.addLayout(channels)
        self.p_x = pg.PlotWidget(title="ΔBx")
        self.p_y = pg.PlotWidget(title="ΔBy")
        self.p_mag = pg.PlotWidget(title="|ΔBxy|")
        self.p_z = pg.PlotWidget(title="ΔBz")
        self.cur_x = self.p_x.plot(pen=pg.mkPen("#65b5ff", width=1))
        self.cur_y = self.p_y.plot(pen=pg.mkPen("#ffb45e", width=1))
        self.cur_mag = self.p_mag.plot(pen=pg.mkPen("#42d7ba", width=1.5))
        self.cur_z = self.p_z.plot(pen=pg.mkPen("#bc9fff", width=1))
        graph_scroll = QtWidgets.QScrollArea()
        graph_scroll.setWidgetResizable(True)
        graph_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        graph_body = QtWidgets.QWidget()
        graph_body.setObjectName("workspace")
        graph_layout = QtWidgets.QVBoxLayout(graph_body)
        graph_layout.setContentsMargins(0, 0, 0, 0)
        graph_scroll.setWidget(graph_body)
        series_layout.addWidget(graph_scroll, 1)
        tick_font = QtGui.QFont()
        tick_font.setPixelSize(12)
        for plot in (self.p_x, self.p_y, self.p_mag, self.p_z):
            plot.showGrid(x=True, y=True, alpha=0.2)
            plot.setLabel("left", "µT")
            plot.getViewBox().setAutoVisible(y=True)
            plot.setMinimumHeight(150)
            graph_layout.addWidget(plot, 1)
        for plot in (self.p_xy, self.p_x, self.p_y, self.p_mag, self.p_z):
            for axis in ("left", "bottom"):
                plot.getAxis(axis).setTickFont(tick_font)
        self.p_x.disableAutoRange(axis="x")
        for plot in (self.p_y, self.p_mag, self.p_z):
            plot.setXLink(self.p_x)
        self.chk_mag.toggled.connect(self.p_mag.setVisible)
        self.chk_z.toggled.connect(self.p_z.setVisible)
        self.p_mag.setVisible(False)
        self.p_z.setVisible(False)
        plots.addWidget(timeseries)
        plots.setSizes([420, 580])

        self.lbl_health = QtWidgets.QLabel("未连接")
        self.statusBar().addPermanentWidget(self.lbl_health)
        self.statusBar().showMessage("选择数据源开始实验")
        self.btn_conn.clicked.connect(self._toggle_connect)
        self.btn_restart.clicked.connect(self._restart)
        self.btn_base.clicked.connect(lambda: self._take_baseline())
        self.btn_rec.clicked.connect(self._toggle_record)
        self.btn_pause.toggled.connect(self._set_pause)
        self.btn_src_serial.clicked.connect(lambda: self._set_src_mode("串口"))
        self.btn_src_replay.clicked.connect(lambda: self._set_src_mode("回放"))
        self.cb_alpha.currentTextChanged.connect(self._set_alpha)
        self.sp_radius.valueChanged.connect(self._on_radius_changed)
        self.cb_speed.currentTextChanged.connect(self._set_speed)
        self._sync_controls()
    # ---- 键盘快捷键 ----
    def keyPressEvent(self, ev: QtGui.QKeyEvent):
        k = ev.key()
        if k == QtCore.Qt.Key_Space:
            self.btn_pause.click()
        elif k == QtCore.Qt.Key_B:
            self.btn_base.click()
        elif k == QtCore.Qt.Key_R:
            self.btn_rec.click()
        elif QtCore.Qt.Key_1 <= k <= QtCore.Qt.Key_4:
            self.cb_win.setCurrentIndex(k - QtCore.Qt.Key_1)
        else:
            super().keyPressEvent(ev)

    def _set_pause(self, paused: bool):
        self._paused = paused
        if paused:
            self._pause_t0 = time.monotonic()
        else:
            self._pause_t0 = None
        self._sync_controls()

    # ---- 源模式 / 控制同步 ----
    def _sync_controls(self):
        mode = self._src_mode
        connected = self.src is not None
        recording = self.rec is not None
        is_replay = isinstance(self.src, S.ReplaySource) if connected else mode == "回放"
        self.ed_port.setVisible(mode == "串口")
        self.ed_port.setEnabled(not connected)
        self._group_replay.setVisible(mode != "串口")
        self.btn_conn.setText("断开" if connected else
                              {"串口": "连接传感器", "回放": "打开回放…"}[mode])
        self.btn_conn.setEnabled(self.experiment_service is None)
        if connected:
            name = self.src.info.get("name", mode)
            self.lbl_source.setText(name)
            self.lbl_source.setToolTip(name)
        else:
            self.lbl_source.setText({"串口": "115200 baud · 原始磁场采集",
                                    "回放": "打开 CSV 与配套 JSON"}[mode])
            self.lbl_source.setToolTip(self.lbl_source.text())

        def available(widget, enabled, reason, usage):
            widget.setEnabled(enabled)
            widget.setToolTip(usage if enabled else reason)

        available(self.btn_base, connected and not recording,
                  "先连接数据源；录制期间不可重取基线", "取最近一段空载静止数据作为基线（B）")
        available(self.btn_rec, connected and not is_replay and self.bl.ready,
                  "回放期间不可录制；需要先连接并取基线", "开始或停止录制原始 ΔB（R）")
        available(self.btn_pause, connected, "连接数据源后可暂停",
                  "暂停读取数据源（包括录制取样），不是仅冻结视图；空格继续")
        self.btn_pause.setText(("继续" if self._paused else "暂停") +
                               ("采集" if mode == "串口" else "播放"))
        self.btn_restart.setEnabled(connected and hasattr(self.src, "seek") and not recording)
        self.btn_restart.setToolTip("从头播放；录制期间不可跳转")
        self.cb_speed.setEnabled(connected and mode != "串口")
        self.btn_rec.setText("停止录制" if recording else "开始录制")
        self.lbl_recording.setText("录制中" if recording else
                                  "回放模式不生成新录制" if is_replay else
                                  "就绪 · 可以开始录制" if connected and self.bl.ready else
                                  "先连接数据源并取基线")
        self.lbl_baseline.setText(
            "B₀ = (%.1f, %.1f, %.1f) µT\n门控 %.1f µT" % (*self.bl.b0, 3 * self.bl.sigma_norm)
            if connected and self.bl.ready else "请保持空载静止；连接约 1 秒后自动取基线")
        for b, m in [(self.btn_src_serial, "串口"), (self.btn_src_replay, "回放")]:
            b.setChecked(m == mode)
            b.setEnabled(self.src is None and self.experiment_service is None)

    def closeEvent(self, event):
        if self.control_server is not None:
            self.control_server.close()
        if self.experiment_service is not None:
            try:
                self.experiment_service.close()
            except RuntimeError as exc:
                self.statusBar().showMessage(str(exc), 8000)
                event.ignore()
                return
        super().closeEvent(event)

    def _set_src_mode(self, mode: str):
        if self.src is not None:
            return
        self._src_mode = mode
        self._sync_controls()

    def _restart(self):
        if self.src is not None and hasattr(self.src, "seek"):
            self.src.seek(0)
            self._paused = False; self.btn_pause.setChecked(False)
            # 立即清空 XY 图, 避免重放间歇残留上一个回放的最后位置
            self.c_pt.setData([], [])
            self.c_vec.setData([], [])
            self.statusBar().showMessage("已重放", 2000)
            self._sync_controls()

    @staticmethod
    def _make_ema(text: str) -> EMA:
        """由下拉文本构造 EMA 滤波器; "原始" → α=1.0(直通, 去滤波)."""
        if text == "原始":
            return EMA(alpha=1.0)
        return EMA(alpha=float(text))

    def _set_alpha(self, text: str):
        self.ema = self._make_ema(text)

    def _on_radius_changed(self, value: int):
        """圆半径调整: 重画边界圆 + 更新 view 范围 (留 15% 边距)."""
        self._circle_radius = float(value)
        theta = np.linspace(0, 2*np.pi, 200)
        self.c_circle.setData(self._circle_radius*np.cos(theta),
                              self._circle_radius*np.sin(theta))
        pad = self._circle_radius * 1.15
        self.p_xy.setXRange(-pad, pad, padding=0)
        self.p_xy.setYRange(-pad, pad, padding=0)
        self.contact_dot.setData([self._circle_radius*0.92]*1,
                                 [self._circle_radius*0.92])

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
            else:
                path, _ = QtWidgets.QFileDialog.getOpenFileName(
                    self, "选择录制的 CSV", "", "CSV (*.csv)")
                if not path:
                    return
                self.src = S.ReplaySource(path)
            self.src.start()
            if hasattr(self.src, "set_rate"):
                self.src.set_rate(float(self.cb_speed.currentText().replace("x", "")))
        except Exception as e:
            self.src = None
            self.statusBar().showMessage("打不开信号源: %s" % e, 8000)
            return
        self.rb = RingBuffer(BUF_SECONDS * MAX_EXPECTED_RATE_HZ)
        self.bl = Baseline()
        self.ema = self._make_ema(self.cb_alpha.currentText())
        if isinstance(self.src, S.ReplaySource):
            self.bl.b0 = self.src.b0
        self.btn_conn.setText("断开")
        self.btn_restart.setEnabled(hasattr(self.src, "seek"))
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
        t, B = self.rb.latest_seconds(seconds)
        quality = frame_quality_mask(B)
        clean = B[quality]
        if len(clean) < 10:
            self.statusBar().showMessage("样本不足, 无法取基线", 4000); return
        self.bl.take(clean, update_b0=update_b0)
        self._sync_controls()
        self.statusBar().showMessage(
            "已取基线 B0=(%.1f, %.1f, %.1f) µT, 门控=%.1f µT%s"
            % (*self.bl.b0, 3 * self.bl.sigma_norm,
               "，剔除 %d 个异常帧" % int((~quality).sum()) if (~quality).any() else ""), 6000)

    # ---------- 录制 ----------
    def _toggle_record(self):
        if self.rec is None:
            if self.src is None:
                self.statusBar().showMessage("请先连接信号源", 4000); return
            if not self.bl.ready:
                self.statusBar().showMessage("请先取基线", 4000); return
            self.rec = Recorder(self.out_dir, self.bl.b0, self.src.info)
            self._rec_started_wall = time.monotonic()
            self._sync_controls()
        else:
            self._stop_record()

    def _handle_control(self, request):
        action = request.get("action") if isinstance(request, dict) else None
        if action == "start_record":
            if self.src is None:
                return {"status": "rejected", "error": "Monitor source is not connected"}
            if not self.bl.ready:
                return {"status": "rejected", "error": "Monitor baseline is not ready"}
            if self.rec is None:
                self._toggle_record()
            return {"status": "recording" if self.rec is not None else "rejected"}
        if action == "stop_record":
            if self.rec is not None:
                self._stop_record()
            return {"status": "stopped"}
        return {"status": "rejected", "error": "unknown Monitor action"}

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
        self._sync_controls()

    # ---------- 主循环 ----------
    def _tick(self):
        if self.control_server is not None:
            self.control_server.drain(self._handle_control)
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
        t, B = self.rb.latest_seconds(win_s)
        if len(t) == 0:
            return
        dB = self.bl.apply(B)
        quality = frame_quality_mask(B)
        self._display_bad_frames = int((~quality).sum())
        self._latest_frame_valid = bool(quality[-1])
        dB_display = dB.copy()
        dB_display[~quality] = np.nan
        # EMA 平滑时间序列
        self.ema.reset()
        dB_smooth = self.ema.update(dB_display)
        mag_xy = np.hypot(dB_smooth[:, 0], dB_smooth[:, 1])

        self.cur_x.setData(t, dB_smooth[:, 0])
        self.cur_y.setData(t, dB_smooth[:, 1])
        if self.p_mag.isVisible():
            self.cur_mag.setData(t, mag_xy)
        if self.p_z.isVisible():
            self.cur_z.setData(t, dB_smooth[:, 2])

        gate = 3.0 * self.bl.sigma_norm if self.bl.ready else float("inf")
        valid_i = np.flatnonzero(quality)
        if not len(valid_i):
            return
        last = dB_smooth[int(valid_i[-1])]
        d = derive(last, gate)
        # XY 平面直接使用与时序相同的物理 ΔB 数据流。
        if np.all(np.isfinite(last)):
            sx, sy = float(last[0]), float(last[1])
            # 真实坐标钳位到边界圆内: 超出 r 的点贴住圆周(保持方向)
            r = max(self._circle_radius, 1e-9)
            mag = float(np.hypot(sx, sy))
            if mag > r:
                sx = sx * r / mag
                sy = sy * r / mag
            self.c_pt.setData([sx], [sy])
            self.c_vec.setData([0.0, sx], [0.0, sy])
            radius_display = float(np.hypot(sx, sy))
        else:
            self.c_pt.setData([], [])
            self.c_vec.setData([], [])
            radius_display = 0.0

        # 接触指示
        in_contact = d["mag_xy"] >= gate if np.isfinite(gate) else False
        if in_contact:
            self.contact_dot.setBrush(pg.mkBrush("#3fb950"))
            self.lbl_contact.setText("磁响应：超过接触判定阈值")
            self.lbl_contact.setStyleSheet(
                "background:#1a3a1a;color:#3fb950;font-weight:bold;padding:2px 8px;border-radius:3px;")
        else:
            self.contact_dot.setBrush(pg.mkBrush("#484f58"))
            self.lbl_contact.setText("磁响应：低于阈值" if self.bl.ready else "阈值状态：待基线")
            self.lbl_contact.setStyleSheet(
                "background:#30363d;color:#8b949e;padding:2px 8px;border-radius:3px;")

        self.lbl_read.setText(
            "|ΔB| %.0f  |ΔBxy| %.0f  φ %s°  θ %s°  半径 %.0f µT  门控 %.0f µT  %s"
            % (d["mag"], d["mag_xy"],
               "—" if d["phi_deg"] is None else "%.1f" % d["phi_deg"],
               "—" if d["theta_deg"] is None else "%.1f" % d["theta_deg"],
               radius_display, gate if np.isfinite(gate) else 0.0,
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
                mx = robust_symmetric_limit(ch_v, floor=Y_FLOOR) * 1.05
                cur.getViewBox().setYRange(-mx, mx, padding=0)

    def measured_rate_hz(self):
        t, _ = self.rb.latest_seconds(2.0)
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
        if self._display_bad_frames:
            parts.append("异常帧 %d" % self._display_bad_frames)
        if self.rec is not None and self._rec_started_wall is not None:
            parts.append("录制中 %.1fs" % (time.monotonic() - self._rec_started_wall))
        self.lbl_health.setText("  ·  ".join(parts))
        self.lbl_health.setStyleSheet("color: #d29922;" if off_nominal else "")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--control-socket", default="/tmp/brushbot-monitor.sock")
    qt_argv = argv or []
    args, _ = parser.parse_known_args(qt_argv[1:] if qt_argv else None)
    app = QtWidgets.QApplication(qt_argv)
    w = MonitorWindow(control_socket=args.control_socket)
    w.show()
    return app.exec_()
