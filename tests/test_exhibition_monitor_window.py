"""Offscreen smoke tests for the manual exhibition monitor shell."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PyQt5")
from PyQt5 import QtWidgets

from brushbot.exhibition_monitor.window import ExhibitionWindow


class FakeGateway:
    def close(self):
        self.closed = True


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
    window = ExhibitionWindow(gateway=FakeGateway())
    qtbot.addWidget(window)
    window.show()
    QtWidgets.QApplication.processEvents()
    assert window.is_monitor_page()
    assert window.minimumWidth() >= 1100
    assert window.findChild(QtWidgets.QPushButton, "connect-sensor") is not None


def test_monitor_controls_fit_1366_layout(qtbot):
    window = ExhibitionWindow(gateway=FakeGateway())
    qtbot.addWidget(window)
    window.resize(1366, 768)
    window.show()
    QtWidgets.QApplication.processEvents()
    for object_name in ("xy-plot", "serial-port", "connect-sensor", "capture-baseline"):
        widget = window.findChild(QtWidgets.QWidget, object_name)
        assert widget is not None and widget.isVisible(), object_name
        assert window.rect().contains(widget.geometry().center())
