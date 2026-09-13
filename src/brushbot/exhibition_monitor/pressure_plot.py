"""Lightweight QPainter pressure-history plot for the SZ writing page."""

from __future__ import annotations

from PyQt5 import QtCore, QtGui, QtWidgets

from .theme import COLORS
from .pressure_smoothing import smooth_pressure_series


class PressurePlot(QtWidgets.QWidget):
    """Render a unit-free rolling pressure trend without another plot engine."""

    Y_MIN = 0.0
    Y_MAX = 800.0
    PRESSURE_THRESHOLD = 200.0

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
        return "压力变化 0 200 800 时间"

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

        # Keep the scale readable: the user can immediately see that 200 is
        # the pressure boundary, while samples above it remain in the plot.
        threshold_ratio = (self.PRESSURE_THRESHOLD - self.Y_MIN) / (self.Y_MAX - self.Y_MIN)
        threshold_y = rect.bottom() - rect.height() * threshold_ratio
        pressure_region = QtCore.QRectF(
            rect.left(), rect.top(), rect.width(), max(0.0, threshold_y - rect.top())
        )
        painter.fillRect(pressure_region, QtGui.QColor(181, 107, 47, 22))
        threshold_pen = QtGui.QPen(QtGui.QColor(COLORS["accent"]), 1, QtCore.Qt.DashLine)
        painter.setPen(threshold_pen)
        painter.drawLine(QtCore.QPointF(rect.left(), threshold_y), QtCore.QPointF(rect.right(), threshold_y))
        painter.setPen(QtGui.QColor(COLORS["ink"]))
        painter.drawText(QtCore.QPointF(rect.left(), 20.0), self.title_text)
        painter.drawText(QtCore.QPointF(rect.left(), rect.bottom() + 20.0), "时间")
        painter.drawText(QtCore.QPointF(8.0, rect.top() + 5.0), "800")
        painter.drawText(QtCore.QPointF(8.0, threshold_y + 5.0), "200")
        painter.drawText(QtCore.QPointF(8.0, rect.bottom()), "0")
        painter.setPen(QtGui.QColor(COLORS["accent"]))
        painter.drawText(QtCore.QPointF(rect.right() - 54.0, rect.top() + 18.0), "有压力")
        painter.setPen(QtGui.QColor(COLORS["secondary"]))
        painter.drawText(QtCore.QPointF(rect.right() - 54.0, rect.bottom() - 6.0), "无压力")
        if len(self._values) < 1:
            painter.setPen(QtGui.QColor(COLORS["accent"]))
            painter.drawText(rect.center(), "等待采样")
            return
        start = self._times[0]
        end = self._times[-1] if self._times[-1] != start else start + 1.0
        path = QtGui.QPainterPath()
        for index, (time_value, value) in enumerate(zip(self._times, self._values)):
            x = rect.left() + rect.width() * (time_value - start) / (end - start)
            bounded = max(self.Y_MIN, min(self.Y_MAX, value))
            y = rect.bottom() - rect.height() * (bounded - self.Y_MIN) / (self.Y_MAX - self.Y_MIN)
            point = QtCore.QPointF(x, y)
            if index == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
        painter.setPen(QtGui.QPen(QtGui.QColor(COLORS["primary"]), 2, QtCore.Qt.SolidLine,
                                  QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin))
        painter.drawPath(path)
