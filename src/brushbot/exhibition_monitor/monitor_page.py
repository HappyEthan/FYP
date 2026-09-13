"""Sensor-only monitor page extracted from the shared exhibition shell."""

from PyQt5 import QtWidgets

from .connection_panel import ConnectionPanel
from .sensor_panels import SignalPlot, XYPlot


class MonitorPage(QtWidgets.QWidget):
    def __init__(self, store, gateway, parent=None):
        super().__init__(parent)
        self.setObjectName("monitor-page")
        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        plots = QtWidgets.QWidget()
        plots_layout = QtWidgets.QVBoxLayout(plots)
        plots_layout.setContentsMargins(0, 0, 0, 0)
        plots_layout.setSpacing(10)
        self.xy_plot = XYPlot()
        self.xy_plot.setMinimumSize(620, 360)
        plots_layout.addWidget(self.xy_plot, 3)
        signal_row = QtWidgets.QHBoxLayout()
        signal_row.setSpacing(10)
        self.x_plot = SignalPlot("x")
        self.y_plot = SignalPlot("y")
        signal_row.addWidget(self.x_plot)
        signal_row.addWidget(self.y_plot)
        plots_layout.addLayout(signal_row, 1)
        root.addWidget(plots, 3)

        self.connection_panel = ConnectionPanel(store, gateway)
        root.addWidget(self.connection_panel, 1)

