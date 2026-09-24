"""Two-page manual exhibition monitor with one shared sensor connection."""

from copy import deepcopy
import math
import time

from PyQt5 import QtCore, QtWidgets

from .gateway import ExhibitionGateway
from .monitor_page import MonitorPage
from .navigation import NavigationRail
from .pressure_practice import PressurePracticeEngine
from .state_store import ExhibitionStateStore
from .sz_template import load_sz_template
from .theme import stylesheet
from .writing_page import WritingPage


class ExhibitionWindow(QtWidgets.QMainWindow):
    """Own one gateway/store and switch between monitor and writing pages."""

    def __init__(
        self,
        gateway=None,
        *,
        backend_url="http://127.0.0.1:8765",
        offline=False,
        clock=None,
    ):
        super().__init__()
        self.gateway = gateway if gateway is not None else ExhibitionGateway(backend_url)
        self.backend_url = backend_url
        self.offline = offline
        self._clock = clock or time.monotonic
        self.store = ExhibitionStateStore(self)
        self.template = load_sz_template()
        self.engine = PressurePracticeEngine(self.template)
        self.engine.set_page_active(False, self._practice_now())
        self._monitor_page = None
        self._writing_page = None
        self._writing_visible = False
        self._stream_started = False
        self._closed = False
        self.setWindowTitle("智能毛笔系统")
        self.setMinimumSize(1180, 720)
        self.resize(1366, 768)
        self.setStyleSheet(stylesheet())
        self._build_shell()
        self.show_monitor()
        self._start_stream()

    def _build_shell(self):
        shell = QtWidgets.QWidget(objectName="monitor-shell")
        root = QtWidgets.QVBoxLayout(shell)
        root.setContentsMargins(24, 18, 24, 20)
        root.setSpacing(12)

        heading = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("智能毛笔系统")
        title.setObjectName("title")
        heading.addWidget(title)
        heading.addStretch()
        self.heading_status = QtWidgets.QLabel("离线空数据框架" if self.offline else "等待连接")
        self.heading_status.setObjectName("status")
        heading.addWidget(self.heading_status)
        root.addLayout(heading)

        body = QtWidgets.QHBoxLayout()
        body.setSpacing(14)
        self.navigation = NavigationRail()
        self.navigation.setMinimumWidth(150)
        self.navigation.page_requested.connect(self._show_page)
        body.addWidget(self.navigation)

        self.page_stack = QtWidgets.QStackedWidget()
        self.monitor_page = MonitorPage(self.store, self.gateway)
        self.writing_page = WritingPage(self.store)
        self.monitor_page.setMinimumSize(900, 580)
        self.writing_page.setMinimumSize(900, 580)
        self.page_stack.addWidget(self.monitor_page)
        self.page_stack.addWidget(self.writing_page)
        body.addWidget(self.page_stack, 1)
        root.addLayout(body, 1)
        self.setCentralWidget(shell)

        # Compatibility aliases keep embedding/tests independent of the page split.
        self._monitor_page = self.monitor_page
        self._writing_page = self.writing_page
        self.xy_plot = self.monitor_page.xy_plot
        self.x_plot = self.monitor_page.x_plot
        self.y_plot = self.monitor_page.y_plot
        self.connection_panel = self.monitor_page.connection_panel
        self.sz_canvas = self.writing_page.sz_canvas
        self.practice_panel = self.writing_page.practice_panel
        self.practice_panel.start_button.clicked.connect(self._start_practice)
        self.practice_panel.reset_button.clicked.connect(self._reset_practice)
        self.timer = QtCore.QTimer(self)
        self.store.changed.connect(self._refresh_sensor_views)
        self._refresh_sensor_views()

    def _start_stream(self) -> None:
        if self.offline or self._stream_started:
            return
        start_stream = getattr(self.gateway, "start_stream", None)
        if callable(start_stream):
            start_stream(self._on_snapshot)
            self._stream_started = True

    def _on_snapshot(self, snapshot: dict) -> None:
        if self._closed or not isinstance(snapshot, dict):
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

    def _show_page(self, page: str) -> None:
        page = "writing" if str(page).lower() == "writing" else "monitor"
        if page == ("writing" if self._writing_visible else "monitor"):
            self.navigation.set_current(page)
            return
        if page == "writing":
            self._writing_visible = True
            self.engine.set_page_active(True, self._practice_now())
            self.page_stack.setCurrentWidget(self.writing_page)
            self.writing_page.on_page_entered()
        else:
            self._writing_visible = False
            self.engine.set_page_active(False, self._practice_now())
            self.page_stack.setCurrentWidget(self.monitor_page)
            self.writing_page.on_page_left()
        self.navigation.set_current(page)
        self._refresh_sensor_views()

    def _practice_now(self) -> float:
        try:
            return float(self._clock())
        except Exception:
            return time.monotonic()

    def _start_practice(self):
        if not self._writing_visible:
            self._show_page("writing")
        self.template = load_sz_template()
        self.engine.template = self.template
        self.engine.start_session(self._practice_now())
        self.writing_page.sz_canvas.set_template(self.template)
        self.writing_page.sz_canvas.begin_session()
        self.writing_page.sz_canvas.set_practice_state(self.engine.state)
        self.practice_panel.apply_state(self.engine.state)

    def _reset_practice(self):
        self.engine.reset()
        self.writing_page.sz_canvas.reset()
        self.practice_panel.apply_state(self.engine.state)

    @staticmethod
    def _pressure_from_sensor(sensor: dict):
        if "pressure_bxy_uT" in sensor:
            value = sensor.get("pressure_bxy_uT")
        else:
            xy = sensor.get("xy")
            try:
                value = math.hypot(float(xy["x"]), float(xy["y"]))
            except (AttributeError, KeyError, TypeError, ValueError):
                return None
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        return value if math.isfinite(value) else None

    @staticmethod
    def _xy_from_sensor(sensor: dict):
        xy = sensor.get("xy") if isinstance(sensor, dict) else None
        try:
            x, y = float(xy["x"]), float(xy["y"])
        except (AttributeError, KeyError, TypeError, ValueError):
            return None
        return (x, y) if math.isfinite(x) and math.isfinite(y) else None

    def _refresh_sensor_views(self):
        if self._closed:
            return
        snapshot = self.store.snapshot() or {}
        sensor = snapshot.get("sensor") if isinstance(snapshot, dict) else None
        if not isinstance(sensor, dict) and isinstance(snapshot, dict) and "connected" in snapshot:
            sensor = snapshot
        if sensor is None:
            sensor = {}
        connected = bool(sensor.get("connected"))
        self.heading_status.setText(
            "已连接" if connected else ("连接失败" if sensor.get("error") else ("离线空数据框架" if self.offline else "等待连接"))
        )
        self.heading_status.setStyleSheet("color: #b56b2f; font-weight: 700;" if sensor.get("error") else "")
        self.navigation.set_sensor(sensor)
        self.xy_plot.set_sensor_snapshot(sensor)
        series = sensor.get("series", {}) if isinstance(sensor, dict) else {}
        if not isinstance(series, dict):
            series = {}
        times = series.get("t", [])
        xs = series.get("x", [])
        ys = series.get("y", [])
        bxy = series.get("bxy")
        if not isinstance(bxy, list) or len(bxy) != len(times):
            bxy = []
            for x, y in zip(xs, ys):
                try:
                    bxy.append(math.hypot(float(x), float(y)))
                except (TypeError, ValueError):
                    bxy.append(float("nan"))
        self.x_plot.set_series(times, xs)
        self.y_plot.set_series(times, ys)
        self.writing_page.set_pressure_series(times, bxy)
        xy = self._xy_from_sensor(sensor)
        self.writing_page.set_sensor_xy(*(xy if xy is not None else (None, None)))

        if not self.engine.state.session_started:
            self.practice_panel.apply_state(self.engine.state)
            return
        now_s = self._practice_now()
        pressure = self._pressure_from_sensor(sensor)
        valid = connected and bool(sensor.get("baseline_ready")) and not sensor.get("error") and pressure is not None
        if valid:
            state = self.engine.update(pressure, now_s)
            self.writing_page.sz_canvas.set_practice_state(state)
            self.practice_panel.apply_state(state)
            return

        self.engine.invalidate_clock(now_s)
        if sensor.get("error"):
            self.practice_panel.set_hold_status(f"练习暂停：{sensor.get('error')}")
        elif not connected:
            self.practice_panel.set_hold_status("练习暂停：未连接")
        elif not sensor.get("baseline_ready"):
            self.practice_panel.set_hold_status("练习暂停：等待基线")
        else:
            self.practice_panel.set_hold_status("练习暂停：等待有效压力")

    def show_monitor(self) -> None:
        self._show_page("monitor")

    def show_writing(self) -> None:
        self._show_page("writing")

    def is_monitor_page(self) -> bool:
        return self.page_stack.currentWidget() is self.monitor_page

    def is_writing_page(self) -> bool:
        return self.page_stack.currentWidget() is self.writing_page

    def closeEvent(self, event):
        if self._closed:
            event.accept()
            return
        self._closed = True
        if self.timer.isActive():
            self.timer.stop()
        if self.connection_panel is not None:
            self.connection_panel.close()
        gateway = self.gateway
        if gateway is not None:
            close = getattr(gateway, "close", None)
            if callable(close):
                close()
        self.gateway = None
        super().closeEvent(event)
