import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PyQt5")
from PyQt5 import QtWidgets

from brushbot.exhibition_monitor.pressure_plot import PressurePlot


@pytest.fixture
def qtbot():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    class Bot:
        def addWidget(self, widget):
            widget.show()
            app.processEvents()

    return Bot()


def test_pressure_plot_empty_state_has_no_unit_label(qtbot):
    plot = PressurePlot()
    qtbot.addWidget(plot)
    assert plot.title_text == "压力变化"
    assert "µT" not in plot.visible_text()
    assert plot._values == []


def test_pressure_plot_filters_invalid_values_and_keeps_recent_window(qtbot):
    plot = PressurePlot(window_s=2.0)
    qtbot.addWidget(plot)
    plot.set_series([0.0, 1.0, 3.0, 4.0], [10.0, float("nan"), 20.0, 30.0])
    assert plot._times == [3.0, 4.0]
    assert plot._values == [20.0, 30.0]
    assert plot._times[0] >= 2.0
    assert "Bxy" not in plot.visible_text()
