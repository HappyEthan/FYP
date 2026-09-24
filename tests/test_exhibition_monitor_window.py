"""Offscreen smoke tests for the manual exhibition monitor shell."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PyQt5")
from PyQt5 import QtWidgets

from brushbot.exhibition_monitor.pressure_practice import PracticeConfig
from brushbot.exhibition_monitor.window import ExhibitionWindow


class FakeGateway:
    def __init__(self):
        self.start_calls = []
        self.close_calls = 0

    def start_stream(self, callback):
        self.start_calls.append(callback)

    def close(self):
        self.close_calls += 1


def _sensor(pressure, *, connected=True, baseline_ready=True, error=None):
    payload = {
        "connected": connected,
        "baseline_ready": baseline_ready,
        "pressure_bxy_uT": pressure,
        "xy": {"x": pressure, "y": 0.0},
        "series": {"t": [], "x": [], "y": []},
    }
    payload["error"] = error
    return {"sensor": payload}


@pytest.fixture
def qtbot():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    class Bot:
        def addWidget(self, widget):
            self.widget = widget

    bot = Bot()
    bot.app = app
    yield bot
    if hasattr(bot, "widget"):
        bot.widget.close()
        app.processEvents()


def test_app_starts_directly_on_manual_monitor(qtbot):
    gateway = FakeGateway()
    window = ExhibitionWindow(gateway=gateway)
    qtbot.addWidget(window)
    window.show()
    QtWidgets.QApplication.processEvents()
    assert window.is_monitor_page()
    assert window.minimumWidth() >= 1100
    assert window.findChild(QtWidgets.QPushButton, "connect-sensor") is not None
    assert len(gateway.start_calls) == 1


def test_monitor_controls_fit_1366_layout(qtbot):
    window = ExhibitionWindow(gateway=FakeGateway())
    qtbot.addWidget(window)
    window.resize(1366, 768)
    window.show()
    QtWidgets.QApplication.processEvents()
    for object_name in ("xy-plot", "serial-port", "connect-sensor", "baseline"):
        widget = window.findChild(QtWidgets.QWidget, object_name)
        assert widget is not None and widget.isVisible(), object_name
        assert window.rect().contains(widget.geometry().center())


def test_stream_snapshot_refreshes_all_views_and_close_is_idempotent(qtbot):
    gateway = FakeGateway()
    window = ExhibitionWindow(gateway=gateway)
    qtbot.addWidget(window)
    snapshot = {"sensor": {"connected": True, "series": {"t": [1], "x": [2], "y": [3]}}}
    gateway.start_calls[0](snapshot)
    QtWidgets.QApplication.processEvents()
    assert window.xy_plot.sensor_snapshot == snapshot["sensor"]
    assert window.x_plot._times == [1.0]
    assert window.y_plot._values == [3]
    window.close()
    window.close()
    assert gateway.close_calls == 1


def test_error_snapshot_keeps_last_series_and_sets_orange_status(qtbot):
    gateway = FakeGateway()
    window = ExhibitionWindow(gateway=gateway)
    qtbot.addWidget(window)
    gateway.start_calls[0]({"sensor": {"connected": True, "series": {"t": [1], "x": [2], "y": [3]}}})
    gateway.start_calls[0]({"sensor": {"connected": False, "error": "stream lost", "series": None}})
    QtWidgets.QApplication.processEvents()
    assert window.x_plot._times == [1.0]
    assert window.x_plot._values == [2.0]
    assert window.y_plot._values == [3.0]
    assert window.heading_status.text() == "连接失败"
    assert "#b56b2f" in window.heading_status.styleSheet()
    gateway.start_calls[0]({"sensor": {"error": "still lost", "series": {}}})
    QtWidgets.QApplication.processEvents()
    assert window.x_plot._values == [2.0]


def test_none_series_snapshot_does_not_crash_refresh(qtbot):
    gateway = FakeGateway()
    window = ExhibitionWindow(gateway=gateway)
    qtbot.addWidget(window)
    gateway.start_calls[0]({"sensor": {"connected": True, "series": None}})
    QtWidgets.QApplication.processEvents()
    assert window.x_plot._values == []


def test_monitor_imports_do_not_pull_serial_or_robot_modules():
    import ast
    from pathlib import Path

    source = Path(__file__).parents[1] / "src/brushbot/exhibition_monitor/window.py"
    tree = ast.parse(source.read_text())
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any("serial" in name.lower() or "cps" in name.lower() or "robot" in name.lower() for name in imports)


def test_window_contains_sz_canvas_and_generate_reset_controls(qtbot):
    window = ExhibitionWindow(gateway=FakeGateway())
    qtbot.addWidget(window)
    assert window.sz_canvas is not None
    assert window.practice_panel.start_button.text() == "开始写字"
    assert window.practice_panel.reset_button.text() == "重新开始"


def test_sensor_snapshot_drives_s_progress_and_pressure_label(qtbot):
    gateway = FakeGateway()
    now = [0.0]
    window = ExhibitionWindow(gateway=gateway, clock=lambda: now[0])
    qtbot.addWidget(window)
    window.practice_panel.generate_button.click()
    callback = gateway.start_calls[0]
    callback(_sensor(250.0))
    now[0] = 0.12
    callback(_sensor(250.0))
    now[0] = 0.28
    callback(_sensor(300.0))
    QtWidgets.QApplication.processEvents()
    assert window.practice_panel.pressure_label.text().startswith("当前压力：")
    assert window.engine.state.status == "s_writing"
    assert window.engine.state.progress > 0.0
    assert window.sz_canvas.practice_state == window.engine.state


def test_s_completion_waits_one_second_before_accepting_new_z_down(qtbot):
    gateway = FakeGateway()
    now = [0.0]
    window = ExhibitionWindow(gateway=gateway, clock=lambda: now[0])
    qtbot.addWidget(window)
    window.engine.config = PracticeConfig(min_speed=1.0, max_speed=1.0, debounce_s=0.08, smoothing_window=1, smoothing_alpha=1.0)
    window.practice_panel.generate_button.click()
    callback = gateway.start_calls[0]
    for timestamp, pressure in ((0.0, 250.0), (0.08, 250.0), (0.28, 300.0), (0.48, 300.0), (0.68, 300.0), (0.88, 300.0), (1.08, 300.0)):
        now[0] = timestamp
        callback(_sensor(pressure))
    assert window.engine.state.status == "s_finished_pause"
    now[0] = 1.98
    callback(_sensor(0.0))
    assert window.engine.state.status == "s_finished_pause"
    now[0] = 2.08
    callback(_sensor(0.0))
    assert window.engine.state.status == "wait_z_down"
    now[0] = 2.16
    callback(_sensor(250.0))
    now[0] = 2.24
    callback(_sensor(250.0))
    assert window.engine.state.status == "z_writing"


def test_sensor_disconnect_freezes_sz_progress(qtbot):
    gateway = FakeGateway()
    now = [0.0]
    window = ExhibitionWindow(gateway=gateway, clock=lambda: now[0])
    qtbot.addWidget(window)
    window.practice_panel.generate_button.click()
    callback = gateway.start_calls[0]
    callback(_sensor(250.0))
    now[0] = 0.08
    callback(_sensor(250.0))
    now[0] = 0.28
    callback(_sensor(300.0))
    progress = window.engine.state.progress
    now[0] = 20.0
    callback(_sensor(None, connected=False, baseline_ready=False, error="stream lost"))
    assert window.engine.state.progress == pytest.approx(progress)
    assert "暂停" in window.practice_panel.status_label.text()


def test_sensor_disconnect_gap_does_not_consume_practice_clock(qtbot):
    gateway = FakeGateway()
    now = [0.0]
    window = ExhibitionWindow(gateway=gateway, clock=lambda: now[0])
    qtbot.addWidget(window)
    window.engine.config = PracticeConfig(
        min_speed=0.8,
        max_speed=0.8,
        debounce_s=0.08,
        smoothing_window=1,
        smoothing_alpha=1.0,
    )
    window.practice_panel.generate_button.click()
    callback = gateway.start_calls[0]
    callback(_sensor(250.0))
    now[0] = 0.08
    callback(_sensor(250.0))
    now[0] = 0.28
    callback(_sensor(300.0))
    before = window.engine.state.progress
    now[0] = 10.0
    callback(_sensor(None, connected=False, baseline_ready=False, error="stream lost"))
    now[0] = 10.1
    callback(_sensor(300.0))
    assert window.engine.state.progress == pytest.approx(before + 0.08)


def test_sensor_error_with_valid_pressure_freezes_sz_progress(qtbot):
    gateway = FakeGateway()
    now = [0.0]
    window = ExhibitionWindow(gateway=gateway, clock=lambda: now[0])
    qtbot.addWidget(window)
    window.engine.config = PracticeConfig(
        min_speed=0.8,
        max_speed=0.8,
        debounce_s=0.08,
        smoothing_window=1,
        smoothing_alpha=1.0,
    )
    window.practice_panel.generate_button.click()
    callback = gateway.start_calls[0]
    callback(_sensor(250.0))
    now[0] = 0.08
    callback(_sensor(250.0))
    now[0] = 0.28
    callback(_sensor(300.0))
    progress = window.engine.state.progress
    now[0] = 1.0
    callback(_sensor(300.0, error="frame error"))
    assert window.engine.state.progress == pytest.approx(progress)
    assert "暂停" in window.practice_panel.status_label.text()


def test_post_close_snapshot_callback_cannot_mutate_practice_state(qtbot):
    gateway = FakeGateway()
    now = [0.0]
    window = ExhibitionWindow(gateway=gateway, clock=lambda: now[0])
    qtbot.addWidget(window)
    window.practice_panel.generate_button.click()
    callback = gateway.start_calls[0]
    callback(_sensor(250.0))
    now[0] = 0.08
    callback(_sensor(250.0))
    before = window.engine.state
    window.close()
    now[0] = 20.0
    callback(_sensor(300.0))
    assert window.engine.state == before
