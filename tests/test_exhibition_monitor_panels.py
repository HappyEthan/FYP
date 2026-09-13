"""Behavior tests for the manual exhibition sensor panels."""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PyQt5")

from PyQt5 import QtCore, QtWidgets

from brushbot.exhibition_monitor.connection_panel import ConnectionPanel
from brushbot.exhibition_monitor.practice_panel import PracticePanel
from brushbot.exhibition_monitor.pressure_practice import PracticeState
from brushbot.exhibition_monitor.sensor_panels import SignalPlot, XYPlot
from brushbot.exhibition_monitor.state_store import ExhibitionStateStore


@pytest.fixture
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_xy_plot_clamps_current_point_to_circle_and_keeps_empty_frame(app):
    plot = XYPlot()
    plot.resize(420, 320)
    plot.set_sensor_snapshot(
        {
            "connected": True,
            "xy": {"x": 800, "y": 0},
            "display": {"xy_radius_uT": 400},
            "series": {"x": [], "y": []},
        }
    )
    center, radius, point = plot.display_geometry()
    assert point.x() == pytest.approx(center.x() + radius)
    assert point.y() == pytest.approx(center.y())

    plot.set_sensor_snapshot(None)
    assert plot.has_circle
    assert plot.has_axes


def test_signal_plots_have_independent_channel_labels_zero_line_and_latest_value(app):
    x_plot = SignalPlot("x")
    y_plot = SignalPlot("y")
    for plot, title in ((x_plot, "ΔBx (µT)"), (y_plot, "ΔBy (µT)")):
        plot.set_series([0.0, 0.5, 1.0], [1.0, -2.0, 3.25])
        assert title in plot.plotItem.titleLabel.text
        assert plot.getAxis("bottom").labelText == "t (s)"
        assert plot.zero_line in plot.plotItem.items
        assert plot.latest_value_label.text() == "3.3 µT"


class FakeGateway:
    def __init__(self):
        self.calls = []

    def connect_sensor(self, port, baud):
        self.calls.append(("connect", port, baud))
        return 200, {"connected": True, "port": port, "baud": baud}

    def disconnect_sensor(self):
        self.calls.append(("disconnect",))
        return 200, {"connected": False}

    def take_baseline(self):
        self.calls.append(("baseline",))
        return 202, {"connected": True, "baseline_running": True}


class SlowBaselineGateway(FakeGateway):
    def take_baseline(self):
        self.calls.append(("baseline-start",))
        time.sleep(0.15)
        self.calls.append(("baseline-done",))
        return 202, {"connected": True, "baseline_running": True}


def test_connection_panel_uses_gateway_and_applies_sensor_state(app):
    store = ExhibitionStateStore()
    gateway = FakeGateway()
    panel = ConnectionPanel(store, gateway)
    panel.findChild(QtWidgets.QLineEdit, "serial-port").setText("/dev/test")
    panel.findChild(QtWidgets.QComboBox, "serial-baud").setCurrentText("9600")
    panel.findChild(QtWidgets.QPushButton, "connect-sensor").click()
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and len(gateway.calls) < 1:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    panel.findChild(QtWidgets.QPushButton, "baseline").click()
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and len(gateway.calls) < 2:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    panel.findChild(QtWidgets.QPushButton, "disconnect-sensor").click()

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and len(gateway.calls) < 3:
        app.processEvents()
        time.sleep(0.005)

    assert gateway.calls == [
        ("connect", "/dev/test", 9600),
        ("baseline",),
        ("disconnect",),
    ]
    panel.apply_sensor(
        {
            "connected": True,
            "port": "/dev/test",
            "sample_rate_hz": 100.0,
            "bad_lines": 2,
            "baseline_running": True,
            "error": "bad frame",
        }
    )
    assert panel.status_label.text() == "已连接"
    assert panel.detail_label.text() == "/dev/test · 100.0 Hz · 坏帧 2"
    assert panel.error_label.text() == "bad frame"
    assert panel.findChild(QtWidgets.QPushButton, "baseline").isEnabled() is False
    panel.apply_sensor({"connected": True, "contact": True})
    assert panel.contact_label.text() == "接触"
    panel.apply_sensor({"connected": True, "contact": False})
    assert panel.contact_label.text() == "离开"


def test_baseline_request_does_not_block_gui_and_preserves_latest_series(app):
    store = ExhibitionStateStore()
    gateway = SlowBaselineGateway()
    panel = ConnectionPanel(store, gateway)
    store.update_snapshot(
        {
            "sensor": {
                "connected": True,
                "series": {"t": [0.0, 1.0], "x": [2.0, 3.0], "y": [4.0, 5.0]},
                "xy": {"x": 3.0, "y": 5.0},
            }
        }
    )
    started = time.monotonic()
    panel.findChild(QtWidgets.QPushButton, "baseline").click()
    elapsed = time.monotonic() - started
    assert elapsed < 0.08

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and ("baseline-start",) not in gateway.calls:
        app.processEvents()
        time.sleep(0.005)
    assert gateway.calls == [("baseline-start",)]
    while time.monotonic() < deadline and ("baseline-done",) not in gateway.calls:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert ("baseline-done",) in gateway.calls
    assert store.snapshot()["sensor"]["series"] == {
        "t": [0.0, 1.0], "x": [2.0, 3.0], "y": [4.0, 5.0]
    }


def test_empty_signal_plot_places_waiting_text_inside_frame(app):
    plot = SignalPlot("x")
    plot.resize(320, 180)
    plot.set_series([], [])
    app.processEvents()
    x, y = plot.waiting_label.pos().x(), plot.waiting_label.pos().y()
    xmin, xmax = plot.plotItem.viewRange()[0]
    ymin, ymax = plot.plotItem.viewRange()[1]
    assert xmin <= x <= xmax
    assert ymin <= y <= ymax
    assert plot.waiting_label.isVisible()


def test_connection_panel_defaults_to_acm0(app):
    panel = ConnectionPanel(ExhibitionStateStore(), FakeGateway())
    assert panel.port_edit.text() == "/dev/ttyACM0"


def test_practice_panel_shows_pressure_and_state(app):
    panel = PracticePanel()
    panel.apply_state(PracticeState("s_writing", "S", 0.25, True, 180.0, 0.0))
    assert "书写 S" in panel.status_label.text()
    assert "180.0" in panel.pressure_label.text()
    assert "25%" in panel.progress_label.text()
