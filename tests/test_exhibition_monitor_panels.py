"""Behavior tests for the manual exhibition sensor panels."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PyQt5")

from PyQt5 import QtCore, QtWidgets

from brushbot.exhibition_monitor.connection_panel import ConnectionPanel
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


def test_connection_panel_uses_gateway_and_applies_sensor_state(app):
    store = ExhibitionStateStore()
    gateway = FakeGateway()
    panel = ConnectionPanel(store, gateway)
    panel.findChild(QtWidgets.QLineEdit, "serial-port").setText("/dev/test")
    panel.findChild(QtWidgets.QComboBox, "serial-baud").setCurrentText("9600")
    panel.findChild(QtWidgets.QPushButton, "connect-sensor").click()
    panel.findChild(QtWidgets.QPushButton, "baseline").click()
    panel.findChild(QtWidgets.QPushButton, "disconnect-sensor").click()

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

