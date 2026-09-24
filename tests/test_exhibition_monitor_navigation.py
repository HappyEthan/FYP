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
            widget.show()
            app.processEvents()

    return Bot()


def test_navigation_switches_pages_without_restarting_gateway(qtbot):
    gateway = FakeGateway()
    window = ExhibitionWindow(gateway=gateway)
    qtbot.addWidget(window)
    assert window.is_monitor_page()
    assert window.navigation.monitor_button.isChecked()
    assert not window.navigation.writing_button.isChecked()
    assert window.findChild(QtWidgets.QLabel, "title").text() == "智能毛笔系统"
    assert window.navigation.monitor_button.text() == "监控模式"
    assert window.navigation.writing_button.text() == "写字模式"
    window.navigation.writing_button.click()
    assert window.is_writing_page()
    assert window.navigation.writing_button.isChecked()
    assert not window.navigation.monitor_button.isChecked()
    window.navigation.monitor_button.click()
    assert window.is_monitor_page()
    assert window.navigation.monitor_button.isChecked()
    assert len(gateway.start_calls) == 1
    assert gateway.close_calls == 0


def test_writing_page_requires_start_and_resumes_after_navigation(qtbot):
    gateway = FakeGateway()
    now = [0.0]
    window = ExhibitionWindow(gateway=gateway, clock=lambda: now[0])
    qtbot.addWidget(window)
    window.navigation.writing_button.click()
    callback = gateway.start_calls[0]
    assert window.engine.state.status == "idle_wait_start"
    callback({"sensor": {"connected": True, "baseline_ready": True, "pressure_bxy_uT": 300.0, "xy": {"x": 3.0, "y": 4.0}, "series": {"t": [], "x": [], "y": [], "bxy": []}}})
    assert window.engine.state.progress == 0.0
    window.writing_page.start_button.click()
    callback({"sensor": {"connected": True, "baseline_ready": True, "pressure_bxy_uT": 250.0, "xy": {"x": 3.0, "y": 4.0}, "series": {"t": [], "x": [], "y": [], "bxy": []}}})
    now[0] = 0.12
    callback({"sensor": {"connected": True, "baseline_ready": True, "pressure_bxy_uT": 250.0, "xy": {"x": 3.0, "y": 4.0}, "series": {"t": [], "x": [], "y": [], "bxy": []}}})
    now[0] = 0.28
    callback({"sensor": {"connected": True, "baseline_ready": True, "pressure_bxy_uT": 300.0, "xy": {"x": 3.0, "y": 4.0}, "series": {"t": [], "x": [], "y": [], "bxy": []}}})
    before = window.engine.state.progress
    window.navigation.monitor_button.click()
    now[0] = 10.0
    callback({"sensor": {"connected": True, "baseline_ready": True, "pressure_bxy_uT": 300.0, "xy": {"x": 3.0, "y": 4.0}, "series": {"t": [], "x": [], "y": [], "bxy": []}}})
    assert window.engine.state.progress == pytest.approx(before)
    window.navigation.writing_button.click()
    now[0] = 10.1
    callback({"sensor": {"connected": True, "baseline_ready": True, "pressure_bxy_uT": 300.0, "xy": {"x": 3.0, "y": 4.0}, "series": {"t": [], "x": [], "y": [], "bxy": []}}})
    assert window.engine.state.progress > before
