"""Small, deterministic Qt sensor visualisations for the exhibition page.

These widgets deliberately consume already-decoded snapshots.  They do not
know about serial devices or the network gateway; that boundary keeps the
manual display easy to exercise off-line.
"""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
import math

import pyqtgraph as pg
from PyQt5 import QtCore, QtGui, QtWidgets

from .theme import COLORS


class XYPlot(QtWidgets.QWidget):
    """Draw an XY field plot with a fixed circular display geometry."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("xy-plot")
        self.setMinimumSize(420, 300)
        self.setAttribute(QtCore.Qt.WA_OpaquePaintEvent, False)
        self.sensor_snapshot: dict | None = None
        # These public flags make the empty frame explicit and are useful to
        # embedding code that wants to describe what is visible before data.
        self.has_circle = True
        self.has_axes = True

    def set_sensor_snapshot(self, sensor: dict | None) -> None:
        self.sensor_snapshot = deepcopy(sensor) if sensor is not None else None
        self.update()

    @staticmethod
    def _radius_u_t(sensor: dict | None) -> float:
        try:
            radius = float((sensor or {}).get("display", {}).get("xy_radius_uT", 400))
        except (AttributeError, TypeError, ValueError):
            radius = 400.0
        return radius if math.isfinite(radius) and radius > 0 else 400.0

    def _plot_rect(self) -> QtCore.QRectF:
        # Leave room for unit labels while using the same scale in both axes.
        return QtCore.QRectF(self.rect()).adjusted(42.0, 26.0, -28.0, -38.0)

    def display_geometry(self):
        """Return ``(center, pixel_radius, current_point)`` for the frame.

        Coordinates are clamped only for display.  ``sensor_snapshot`` remains
        an untouched copy of the incoming data so callers can inspect values
        outside the visible radius.
        """

        rect = self._plot_rect()
        center = rect.center()
        radius = max(1.0, min(rect.width(), rect.height()) / 2.0)
        xy = (self.sensor_snapshot or {}).get("xy", {})
        try:
            x = float(xy.get("x", 0.0))
            y = float(xy.get("y", 0.0))
        except (AttributeError, TypeError, ValueError):
            x, y = 0.0, 0.0
        limit = self._radius_u_t(self.sensor_snapshot)
        magnitude = math.hypot(x, y)
        if magnitude > limit:
            factor = limit / magnitude
            x, y = x * factor, y * factor
        point = QtCore.QPointF(
            center.x() + radius * x / limit,
            center.y() - radius * y / limit,
        )
        return center, radius, point

    # Descriptive aliases keep the geometry straightforward for embedding and
    # tests without exposing the paint implementation.
    def current_point_position(self):
        return self.display_geometry()[2]

    def display_point(self):
        return self.current_point_position()

    def _clamped_series(self):
        sensor = self.sensor_snapshot or {}
        series = sensor.get("series", {}) if isinstance(sensor, dict) else {}
        try:
            xs = list(series.get("x", []))
            ys = list(series.get("y", []))
        except AttributeError:
            return []
        limit = self._radius_u_t(sensor)
        points = []
        for x, y in zip(xs, ys):
            try:
                x, y = float(x), float(y)
            except (TypeError, ValueError):
                continue
            magnitude = math.hypot(x, y)
            if magnitude > limit:
                factor = limit / magnitude
                x, y = x * factor, y * factor
            points.append((x, y))
        return points

    def paintEvent(self, event):  # noqa: N802 - Qt API name
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor(COLORS["surface"]))
        rect = self._plot_rect()
        center, radius, point = self.display_geometry()

        axis_pen = QtGui.QPen(QtGui.QColor("#c6d4cc"), 1)
        painter.setPen(axis_pen)
        painter.drawLine(QtCore.QPointF(center.x(), rect.top()), QtCore.QPointF(center.x(), rect.bottom()))
        painter.drawLine(QtCore.QPointF(rect.left(), center.y()), QtCore.QPointF(rect.right(), center.y()))

        circle_pen = QtGui.QPen(QtGui.QColor(COLORS["secondary"]), 1.5, QtCore.Qt.DashLine)
        painter.setPen(circle_pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawEllipse(center, radius, radius)

        painter.setPen(QtGui.QColor("#638077"))
        painter.drawText(QtCore.QPointF(rect.right() - 58, center.y() - 8),
                         f"+{self._radius_u_t(self.sensor_snapshot):g} µT")
        painter.drawText(QtCore.QPointF(rect.left(), center.y() - 8),
                         f"−{self._radius_u_t(self.sensor_snapshot):g} µT")
        painter.drawText(QtCore.QPointF(rect.right() - 72, rect.top() - 7), "ΔBy (µT)")
        painter.drawText(QtCore.QPointF(rect.right() - 82, rect.bottom() + 25), "ΔBx (µT)")
        painter.drawText(QtCore.QPointF(center.x() + 7, center.y() - 8), "0")

        trail = self._clamped_series()
        if len(trail) > 1:
            path = QtGui.QPainterPath()
            for index, (x, y) in enumerate(trail):
                mapped = QtCore.QPointF(
                    center.x() + radius * x / self._radius_u_t(self.sensor_snapshot),
                    center.y() - radius * y / self._radius_u_t(self.sensor_snapshot),
                )
                path.moveTo(mapped) if index == 0 else path.lineTo(mapped)
            trail_pen = QtGui.QPen(QtGui.QColor(COLORS["secondary"]), 2)
            trail_pen.setCapStyle(QtCore.Qt.RoundCap)
            painter.setPen(trail_pen)
            painter.drawPath(path)

        connected = bool((self.sensor_snapshot or {}).get("connected"))
        series = (self.sensor_snapshot or {}).get("series", {})
        has_data = bool(series.get("x")) if isinstance(series, dict) else False
        status = "已连接" if connected and has_data else ("等待采样" if connected else "未连接")
        painter.setPen(QtGui.QColor(COLORS["primary"] if connected and has_data else COLORS["accent"]))
        painter.drawText(QtCore.QPointF(rect.left(), rect.top() - 8), status)

        if self.sensor_snapshot and self.sensor_snapshot.get("contact"):
            glow = QtGui.QPen(QtGui.QColor(88, 185, 161, 90), 10)
            painter.setPen(glow)
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawEllipse(point, 17, 17)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor(COLORS["primary"]))
        painter.drawEllipse(point, 6, 6)


class SignalPlot(pg.PlotWidget):
    """Independent pyqtgraph plot for one ΔB channel."""

    _CHANNELS = {
        "x": "ΔBx (µT)",
        "y": "ΔBy (µT)",
    }

    def __init__(self, channel: str, parent=None):
        super().__init__(parent=parent)
        channel = str(channel).lower()
        if channel not in self._CHANNELS:
            raise ValueError("channel must be 'x' or 'y'")
        self.channel = channel
        self.setObjectName(f"signal-{channel}")
        self.setBackground(COLORS["surface"])
        self.hideButtons()
        self.setMenuEnabled(False)
        self.showGrid(x=True, y=True, alpha=0.12)
        self.plotItem.setTitle(self._CHANNELS[channel], color=COLORS["ink"], size="12pt")
        self.plotItem.getAxis("bottom").setLabel("t (s)", color=COLORS["ink"])
        self.plotItem.getAxis("left").setLabel("µT", color=COLORS["ink"])
        self.zero_line = pg.InfiniteLine(pos=0.0, angle=0, pen=pg.mkPen(COLORS["accent"], width=1))
        self.plotItem.addItem(self.zero_line)
        self.curve = self.plot(pen=pg.mkPen(COLORS["primary"], width=2))
        self.waiting_label = pg.TextItem("等待采样", color=COLORS["accent"], anchor=(0.5, 0.5))
        self.plotItem.addItem(self.waiting_label)
        self.latest_value_label = QtWidgets.QLabel("— µT", self)
        self.latest_value_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignTop)
        self.latest_value_label.setStyleSheet(f"color: {COLORS['ink']}; font-weight: 600;")
        self.latest_value_label.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.latest_value_label.move(0, 4)
        self.latest_value_label.resize(self.width() - 10, 24)
        self._times: list[float] = []
        self._values: list[float] = []

    def resizeEvent(self, event):  # noqa: N802 - Qt API name
        super().resizeEvent(event)
        if hasattr(self, "latest_value_label"):
            self.latest_value_label.resize(max(1, self.width() - 10), 24)

    def set_series(self, times: Sequence[float], values: Sequence[float]) -> None:
        pairs = []
        for time_value, value in zip(times, values):
            try:
                time_value, value = float(time_value), float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(time_value) and math.isfinite(value):
                pairs.append((time_value, value))
        self._times = [pair[0] for pair in pairs]
        self._values = [pair[1] for pair in pairs]
        self.curve.setData(self._times, self._values)
        if not self._values:
            self.latest_value_label.setText("— µT")
            self.waiting_label.setVisible(True)
            self.plotItem.setXRange(-1.0, 0.0, padding=0.0)
            self.plotItem.setYRange(-1.0, 1.0, padding=0.0)
            self.waiting_label.setPos(-0.5, 0.0)
            return

        self.waiting_label.setVisible(False)
        latest = self._values[-1]
        shown = Decimal(str(latest)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        self.latest_value_label.setText(f"{shown:.1f} µT")
        minimum, maximum = min(self._values), max(self._values)
        limit = max(1.0, abs(minimum), abs(maximum)) * 1.15
        self.plotItem.setYRange(-limit, limit, padding=0.0)
        if len(self._times) == 1 or self._times[0] == self._times[-1]:
            end = self._times[-1]
            self.plotItem.setXRange(end - 1.0, end, padding=0.0)
        else:
            self.plotItem.setXRange(self._times[0], self._times[-1], padding=0.02)
