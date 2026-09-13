"""Offscreen smoke tests for the manual exhibition monitor shell."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PyQt5")
from PyQt5 import QtWidgets

from brushbot.exhibition_monitor.window import ExhibitionWindow


class FakeGateway:
    def __init__(self):
        self.start_calls = []
        self.close_calls = 0

    def start_stream(self, callback):
        self.start_calls.append(callback)

    def close(self):
        self.close_calls += 1


@pytest.fixture
def qtbot():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    class Bot:
        def addWidget(self, widget):
            self.widget = widget

    bot = Bot()
    bot.app = app
    return bot


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
