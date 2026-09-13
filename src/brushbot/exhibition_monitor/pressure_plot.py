"""Lightweight QPainter pressure-history plot for the SZ writing page."""

from __future__ import annotations

from PyQt5 import QtCore, QtGui, QtWidgets

from .theme import COLORS
from .pressure_smoothing import smooth_pressure_series


class PressurePlot(QtWidgets.QWidget):
    """Render a unit-free rolling pressure trend without another plot engine."""

    def __init__(self, *, window_s: float = 8.0, smoothing_window: int = 3,
                 smoothing_alpha: float = 0.20, parent=None):
        super().__init__(parent)
        self.window_s = max(0.5, float(window_s))
        self.smoothing_window = int(smoothing_window)
        self.smoothing_alpha = float(smoothing_alpha)
        self.setObjectName("pressure-plot")
        self.setMinimumSize(420, 130)
        self.title_text = "压力变化"
        self._times: list[float] = []
        self._values: list[float] = []

    def visible_text(self) -> str:
        return "压力变化 时间"

    def set_series(self, times, values) -> None:
        pairs = smooth_pressure_series(
            times,
            values,
            window=self.smoothing_window,
            alpha=self.smoothing_alpha,
        )
        if pairs:
            latest = pairs[-1][0]
            pairs = [pair for pair in pairs if pair[0] >= latest - self.window_s]
        self._times = [pair[0] for pair in pairs]
        self._values = [pair[1] for pair in pairs]
        self.update()

    def _plot_rect(self):
        return QtCore.QRectF(self.rect()).adjusted(52.0, 30.0, -22.0, -28.0)

    def paintEvent(self, event):  # noqa: N802 - Qt API name
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor(COLORS["surface"]))
        rect = self._plot_rect()
        painter.setPen(QtGui.QPen(QtGui.QColor(COLORS["secondary"]), 1))
        painter.drawRect(rect)
        painter.setPen(QtGui.QColor(COLORS["ink"]))
        painter.drawText(QtCore.QPointF(rect.left(), 20.0), self.title_text)
        painter.drawText(QtCore.QPointF(rect.left(), rect.bottom() + 20.0), "时间")
        if len(self._values) < 1:
            painter.setPen(QtGui.QColor(COLORS["accent"]))
            painter.drawText(rect.center(), "等待采样")
            return
        minimum, maximum = min(self._values), max(self._values)
        span = max(1.0, maximum - minimum)
        start = self._times[0]
        end = self._times[-1] if self._times[-1] != start else start + 1.0
        path = QtGui.QPainterPath()
        for index, (time_value, value) in enumerate(zip(self._times, self._values)):
            x = rect.left() + rect.width() * (time_value - start) / (end - start)
            y = rect.bottom() - rect.height() * (value - (minimum - span * 0.15)) / (span * 1.3)
            point = QtCore.QPointF(x, y)
            if index == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
        painter.setPen(QtGui.QPen(QtGui.QColor(COLORS["primary"]), 2, QtCore.Qt.SolidLine,
                                  QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin))
        painter.drawPath(path)
