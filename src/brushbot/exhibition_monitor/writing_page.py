"""Pressure-driven SZ writing page."""

from PyQt5 import QtCore, QtWidgets

from .pressure_plot import PressurePlot
from .practice_panel import PracticePanel
from .sz_canvas import SZCanvas


class WritingPage(QtWidgets.QWidget):
    start_requested = QtCore.pyqtSignal()
    reset_requested = QtCore.pyqtSignal()

    def __init__(self, store=None, parent=None):
        super().__init__(parent)
        self.setObjectName("writing-page")
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        self.sz_canvas = SZCanvas()
        root.addWidget(self.sz_canvas, 5)
        self.pressure_plot = PressurePlot()
        self.pressure_plot.setMinimumHeight(150)
        root.addWidget(self.pressure_plot, 2)
        self.practice_panel = PracticePanel()
        self.start_button = self.practice_panel.start_button
        self.reset_button = self.practice_panel.reset_button
        self.practice_panel.start_button.clicked.connect(self.start_requested)
        self.practice_panel.reset_button.clicked.connect(self.reset_requested)
        root.addWidget(self.practice_panel, 1)

    def on_page_entered(self):
        self.show()

    def on_page_left(self):
        self.hide()

    def set_sensor_xy(self, x, y):
        self.sz_canvas.set_sensor_xy(x, y)

    def set_pressure_series(self, times, values):
        self.pressure_plot.set_series(times, values)
