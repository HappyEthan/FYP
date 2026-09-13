"""Single-page manual monitor window with an injectable gateway seam."""

from PyQt5 import QtCore, QtWidgets
from copy import deepcopy

from .connection_panel import ConnectionPanel
from .gateway import ExhibitionGateway
from .sensor_panels import SignalPlot, XYPlot
from .state_store import ExhibitionStateStore
from .theme import stylesheet


class ExhibitionWindow(QtWidgets.QMainWindow):
    """The only exhibition client page; hardware transport is injected later."""

    def __init__(self, gateway=None, *, backend_url="http://127.0.0.1:8765", offline=False):
        super().__init__()
        self.gateway = gateway if gateway is not None else ExhibitionGateway(backend_url)
        self.backend_url = backend_url
        self.offline = offline
        self.store = ExhibitionStateStore(self)
        self._monitor_page = None
        self._stream_started = False
        self._closed = False
        self.setWindowTitle("Brushbot · 人工监控")
        self.setMinimumSize(1100, 680)
        self.resize(1366, 768)
        self.setStyleSheet(stylesheet())
        self._build_monitor_page()
        self.show_monitor()
        self._start_stream()

    def _start_stream(self) -> None:
        """Start the single gateway stream owned by this window."""
        if self.offline or self._stream_started:
            return
        start_stream = getattr(self.gateway, "start_stream", None)
        if callable(start_stream):
            start_stream(self._on_snapshot)
            self._stream_started = True

    def _on_snapshot(self, snapshot: dict) -> None:
        """Publish a gateway snapshot while retaining history on errors."""
        if not isinstance(snapshot, dict):
            return
        latest = self.store.snapshot() or {}
        incoming_sensor = snapshot.get("sensor") if isinstance(snapshot.get("sensor"), dict) else snapshot
        previous_sensor = latest.get("sensor") if isinstance(latest, dict) else None
        if isinstance(previous_sensor, dict) and isinstance(incoming_sensor, dict):
            sensor = deepcopy(previous_sensor)
            sensor.update(deepcopy(incoming_sensor))
            incoming_series = incoming_sensor.get("series")
            if (
                "series" not in incoming_sensor
                or not isinstance(incoming_series, dict)
                or not incoming_series
            ) and "series" in previous_sensor:
                sensor["series"] = deepcopy(previous_sensor["series"])
            if "sensor" in snapshot:
                snapshot = dict(snapshot)
                snapshot["sensor"] = sensor
            else:
                snapshot = sensor
        self.store.update_snapshot(snapshot)

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
        self.heading_status = QtWidgets.QLabel("离线空数据框架" if self.offline else "等待连接")
        self.heading_status.setObjectName("status")
        heading.addWidget(self.heading_status)
        root.addLayout(heading)

        body = QtWidgets.QHBoxLayout()
        body.setSpacing(14)
        plots = QtWidgets.QWidget()
        plots_layout = QtWidgets.QVBoxLayout(plots)
        plots_layout.setContentsMargins(0, 0, 0, 0)
        plots_layout.setSpacing(10)
        self.xy_plot = XYPlot()
        self.xy_plot.setMinimumSize(620, 330)
        plots_layout.addWidget(self.xy_plot, 3)
        signal_row = QtWidgets.QHBoxLayout()
        signal_row.setSpacing(10)
        self.x_plot = SignalPlot("x")
        self.y_plot = SignalPlot("y")
        signal_row.addWidget(self.x_plot)
        signal_row.addWidget(self.y_plot)
        plots_layout.addLayout(signal_row, 1)
        body.addWidget(plots, 3)

        self.connection_panel = ConnectionPanel(self.store, self.gateway)
        body.addWidget(self.connection_panel, 1)
        root.addLayout(body, 1)
        self.setCentralWidget(page)
        self._monitor_page = page
        self.timer = QtCore.QTimer(self)
        self.store.changed.connect(self._refresh_sensor_views)
        self._refresh_sensor_views()

    def _refresh_sensor_views(self):
        snapshot = self.store.snapshot() or {}
        sensor = snapshot.get("sensor") if isinstance(snapshot, dict) else None
        if not isinstance(sensor, dict) and isinstance(snapshot, dict) and "connected" in snapshot:
            sensor = snapshot
        if sensor is None:
            self.heading_status.setText("离线空数据框架" if self.offline else "等待连接")
        elif sensor.get("connected"):
            self.heading_status.setText("已连接")
        elif sensor.get("error"):
            self.heading_status.setText("连接失败")
        else:
            self.heading_status.setText("未连接")
        self.heading_status.setStyleSheet(
            "color: #b56b2f; font-weight: 700;" if isinstance(sensor, dict) and sensor.get("error")
            else ""
        )
        self.xy_plot.set_sensor_snapshot(sensor)
        sensor = sensor or {}
        series = sensor.get("series", {}) if isinstance(sensor, dict) else {}
        self.x_plot.set_series(series.get("t", []), series.get("x", []))
        self.y_plot.set_series(series.get("t", []), series.get("y", []))

    def show_monitor(self) -> None:
        """Display the sole manual monitor page."""
        if self.centralWidget() is not self._monitor_page:
            self.setCentralWidget(self._monitor_page)
        self._monitor_page.show()

    def is_monitor_page(self) -> bool:
        return self.centralWidget() is self._monitor_page and self._monitor_page is not None

    def closeEvent(self, event):
        if self._closed:
            event.accept()
            return
        self._closed = True
        if self.timer.isActive():
            self.timer.stop()
        gateway = self.gateway
        if gateway is not None:
            close = getattr(gateway, "close", None)
            if callable(close):
                close()
        self.gateway = None
        super().closeEvent(event)
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.quit()
