"""Side navigation for the two exhibition monitor pages."""

from PyQt5 import QtCore, QtWidgets

from .theme import COLORS


class NavigationRail(QtWidgets.QFrame):
    page_requested = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("navigation-rail")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 18, 12, 18)
        layout.setSpacing(10)
        title = QtWidgets.QLabel("书写监控")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(title)
        self.monitor_button = QtWidgets.QPushButton("磁场监控", objectName="nav-monitor")
        self.writing_button = QtWidgets.QPushButton("写字", objectName="nav-writing")
        layout.addWidget(self.monitor_button)
        layout.addWidget(self.writing_button)
        layout.addStretch()
        self.connection_label = QtWidgets.QLabel("连接状态：等待", objectName="nav-connection")
        self.connection_label.setWordWrap(True)
        layout.addWidget(self.connection_label)
        self.monitor_button.clicked.connect(lambda: self.page_requested.emit("monitor"))
        self.writing_button.clicked.connect(lambda: self.page_requested.emit("writing"))

    def set_current(self, page: str) -> None:
        for button in (self.monitor_button, self.writing_button):
            button.setCheckable(True)
        self.monitor_button.setChecked(page == "monitor")
        self.writing_button.setChecked(page == "writing")
        for button in (self.monitor_button, self.writing_button):
            button.setStyleSheet(
                f"background: {COLORS['accent'] if button.isChecked() else COLORS['primary']};"
            )

    def set_sensor(self, sensor: dict | None) -> None:
        sensor = sensor if isinstance(sensor, dict) else {}
        if sensor.get("connected"):
            text = "连接状态：已连接"
        elif sensor.get("error"):
            text = "连接状态：失败"
        else:
            text = "连接状态：未连接"
        self.connection_label.setText(text)
