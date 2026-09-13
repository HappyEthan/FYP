"""Single-page manual monitor window with an injectable gateway seam."""

from PyQt5 import QtCore, QtWidgets

from .theme import stylesheet


class ExhibitionWindow(QtWidgets.QMainWindow):
    """The only exhibition client page; hardware transport is injected later."""

    def __init__(self, gateway=None, *, backend_url="http://127.0.0.1:8765", offline=False):
        super().__init__()
        self.gateway = gateway
        self.backend_url = backend_url
        self.offline = offline
        self._monitor_page = None
        self.setWindowTitle("Brushbot · 人工监控")
        self.setMinimumSize(1100, 680)
        self.resize(1366, 768)
        self.setStyleSheet(stylesheet())
        self._build_monitor_page()
        self.show_monitor()

    def _build_monitor_page(self):
        page = QtWidgets.QWidget(objectName="monitor-page")
        root = QtWidgets.QVBoxLayout(page)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        heading = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("磁触觉人工监控")
        title.setObjectName("title")
        heading.addWidget(title)
        heading.addStretch()
        status = QtWidgets.QLabel("离线空数据框架" if self.offline else "等待连接")
        status.setObjectName("status")
        heading.addWidget(status)
        root.addLayout(heading)

        body = QtWidgets.QHBoxLayout()
        body.setSpacing(14)
        plot = QtWidgets.QFrame(objectName="xy-plot")
        plot.setMinimumSize(620, 420)
        plot.setFrameShape(QtWidgets.QFrame.StyledPanel)
        plot_layout = QtWidgets.QVBoxLayout(plot)
        plot_layout.addWidget(QtWidgets.QLabel("XY 触觉轨迹"))
        plot_layout.addStretch()
        plot_hint = QtWidgets.QLabel("暂无采样数据")
        plot_hint.setAlignment(QtCore.Qt.AlignCenter)
        plot_layout.addWidget(plot_hint)
        plot_layout.addStretch()
        body.addWidget(plot, 3)

        controls = QtWidgets.QGroupBox("串口与基线")
        controls_layout = QtWidgets.QVBoxLayout(controls)
        port = QtWidgets.QLineEdit("/dev/ttyUSB0", objectName="serial-port")
        port.setPlaceholderText("串口设备")
        controls_layout.addWidget(port)
        connect = QtWidgets.QPushButton("连接传感器", objectName="connect-sensor")
        controls_layout.addWidget(connect)
        baseline = QtWidgets.QPushButton("获取基线", objectName="capture-baseline")
        controls_layout.addWidget(baseline)
        controls_layout.addStretch()
        body.addWidget(controls, 1)
        root.addLayout(body, 1)
        self.setCentralWidget(page)
        self._monitor_page = page
        self.timer = QtCore.QTimer(self)

    def show_monitor(self) -> None:
        """Display the sole manual monitor page."""
        if self.centralWidget() is not self._monitor_page:
            self.setCentralWidget(self._monitor_page)
        self._monitor_page.show()

    def is_monitor_page(self) -> bool:
        return self.centralWidget() is self._monitor_page and self._monitor_page is not None

    def closeEvent(self, event):
        if self.timer.isActive():
            self.timer.stop()
        gateway = self.gateway
        if gateway is not None:
            close = getattr(gateway, "close", None)
            if callable(close):
                close()
        self.gateway = None
        super().closeEvent(event)
