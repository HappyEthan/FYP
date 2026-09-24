"""QPainter canvas for a separated, jittered S/Z writing surface."""

from __future__ import annotations

from collections.abc import Mapping

from PyQt5 import QtCore, QtGui, QtWidgets

from .sz_template import (
    calligraphic_outline,
    jittered_point,
    load_sz_template,
    polyline_at_progress,
    stamp_brush,
)
from .theme import COLORS


class SZCanvas(QtWidgets.QWidget):
    """Render the plan band, pressure-driven ink and one jittered brush point."""

    PLAN_WIDTH = 5.0
    OUTLINE_WIDTH = 42.0
    INK_WIDTH = 26.0
    BRUSH_WIDTH = 26.0
    MIN_BRUSH_WIDTH = 16.0
    MAX_BRUSH_WIDTH = 42.0
    JITTER_LIMIT_FRACTION = 0.0
    XY_DISPLAY_RADIUS = 400.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.template = load_sz_template()
        self.practice_state = None
        self.sensor_xy = (0.0, 0.0)
        self._ink_paths: dict[str, list[tuple[float, float]]] = {"S": [], "Z": []}
        self._ink_pressures: dict[str, list[float]] = {"S": [], "Z": []}
        self._ink_widths: dict[str, list[float]] = {"S": [], "Z": []}
        self._last_brush_point: tuple[float, float] | None = None
        self._last_brush_letter: str | None = None
        self.setMinimumSize(620, 330)
        self.setObjectName("sz-canvas")

    def set_template(self, template: Mapping[str, tuple[tuple[float, float], ...]]) -> None:
        if "S" not in template or "Z" not in template:
            raise ValueError("template must contain S and Z")
        self.template = {
            letter: tuple((float(x), float(y)) for x, y in template[letter])
            for letter in ("S", "Z")
        }
        self.reset_ink()
        self.update()

    def set_sensor_xy(self, x: float | None, y: float | None) -> None:
        try:
            self.sensor_xy = (float(x), float(y))
        except (TypeError, ValueError):
            return
        self.update()

    def set_practice_state(self, state) -> None:
        self.practice_state = state
        self._capture_brush_sample(state)
        self.update()

    def begin_session(self) -> None:
        self.reset_ink()
        self.update()

    def reset_ink(self) -> None:
        self._ink_paths = {"S": [], "Z": []}
        self._ink_pressures = {"S": [], "Z": []}
        self._ink_widths = {"S": [], "Z": []}
        self._last_brush_point = None
        self._last_brush_letter = None

    @staticmethod
    def _mix_color(start: str, end: str, amount: float) -> str:
        amount = max(0.0, min(1.0, float(amount)))
        start_rgb = tuple(int(start[index:index + 2], 16) for index in (1, 3, 5))
        end_rgb = tuple(int(end[index:index + 2], 16) for index in (1, 3, 5))
        rgb = tuple(round(left + (right - left) * amount) for left, right in zip(start_rgb, end_rgb))
        return "#%02x%02x%02x" % rgb

    @classmethod
    def pressure_color(cls, pressure: float | None) -> str:
        """Map raw Bxy pressure to the calm exhibition palette."""
        try:
            value = float(pressure)
        except (TypeError, ValueError):
            value = 0.0
        if value <= 200.0:
            return "#74b8a7"
        if value <= 300.0:
            return cls._mix_color("#74b8a7", "#54a58f", (value - 200.0) / 100.0)
        if value <= 400.0:
            return cls._mix_color("#54a58f", "#3e927d", (value - 300.0) / 100.0)
        if value <= 500.0:
            return cls._mix_color("#3e927d", "#2d7d6b", (value - 400.0) / 100.0)
        if value <= 600.0:
            return cls._mix_color("#2d7d6b", "#6f7650", (value - 500.0) / 100.0)
        if value <= 700.0:
            return cls._mix_color("#6f7650", "#b56b2f", (value - 600.0) / 100.0)
        if value <= 1000.0:
            return cls._mix_color("#b56b2f", "#8e4329", (value - 700.0) / 300.0)
        return "#8e4329"

    @classmethod
    def brush_width_for_pressure(cls, pressure: float | None) -> float:
        """Map raw Bxy to a bounded calligraphic brush width."""
        try:
            value = float(pressure)
        except (TypeError, ValueError):
            value = 0.0
        if value <= 200.0:
            return cls.MIN_BRUSH_WIDTH
        if value >= 1000.0:
            return cls.MAX_BRUSH_WIDTH
        ratio = (value - 200.0) / 800.0
        return cls.MIN_BRUSH_WIDTH + ratio * (cls.MAX_BRUSH_WIDTH - cls.MIN_BRUSH_WIDTH)

    def reset(self) -> None:
        self.practice_state = None
        self.reset_ink()
        self.update()

    def _plot_rect(self) -> QtCore.QRectF:
        return QtCore.QRectF(self.rect()).adjusted(24.0, 42.0, -24.0, -24.0)

    def _boxes(self) -> dict[str, tuple[float, float, float, float]]:
        rect = self._plot_rect()
        gutter = max(24.0, rect.width() * 0.06)
        side = min((rect.width() - gutter) / 2.0, rect.height())
        total_width = side * 2.0 + gutter
        left = rect.left() + max(0.0, (rect.width() - total_width) / 2.0)
        top = rect.top() + max(0.0, (rect.height() - side) / 2.0)
        return {
            "S": (left, top, left + side, top + side),
            "Z": (left + side + gutter, top, left + side * 2.0 + gutter, top + side),
        }

    @staticmethod
    def _grid_geometry(boxes):
        grids = {}
        for letter, box in boxes.items():
            left, top, right, bottom = box
            mid_x = (left + right) / 2.0
            mid_y = (top + bottom) / 2.0
            grids[letter] = {
                "box": box,
                "lines": (
                    ((mid_x, top), (mid_x, bottom)),
                    ((left, mid_y), (right, mid_y)),
                ),
            }
        return grids

    @staticmethod
    def _map(point, box):
        left, top, right, bottom = box
        scale = min(right - left, bottom - top)
        ox = left + (right - left - scale) / 2.0
        oy = top + (bottom - top - scale) / 2.0
        return (ox + float(point[0]) * scale, oy + float(point[1]) * scale)

    def _mapped_paths(self, paths, boxes):
        return {
            letter: tuple(self._map(point, boxes[letter]) for point in points)
            for letter, points in paths.items()
            if points
        }

    def _center_for_state(self, state, boxes):
        letter = getattr(state, "active_letter", None)
        if letter not in self.template:
            return None
        progress = float(getattr(state, "progress", 0.0) or 0.0)
        _done, current = polyline_at_progress(self.template[letter], progress)
        point = current[0] if current else self.template[letter][-1]
        return self._map(point, boxes[letter])

    def _jittered_for_state(self, state, boxes, brush_width=None):
        letter = getattr(state, "active_letter", None)
        center = self._center_for_state(state, boxes)
        if center is None or letter not in boxes:
            return None, 0.0
        box = boxes[letter]
        span = min(box[2] - box[0], box[3] - box[1])
        limit = max(0.0, span * self.JITTER_LIMIT_FRACTION)
        point = center
        half_brush = (self.BRUSH_WIDTH if brush_width is None else float(brush_width)) / 2.0
        point = (
            min(max(point[0], box[0] + half_brush), box[2] - half_brush),
            min(max(point[1], box[1] + half_brush), box[3] - half_brush),
        )
        return point, limit

    def _mapped_outlines(self, boxes):
        outlines = {}
        for letter, points in self.template.items():
            box = boxes[letter]
            scale = min(box[2] - box[0], box[3] - box[1])
            stroke = "horizontal" if letter == "S" else "vertical"
            outline = calligraphic_outline(points, self.OUTLINE_WIDTH / scale, stroke=stroke)
            outlines[letter] = tuple(self._map(point, box) for point in outline)
        return outlines

    def _capture_brush_sample(self, state) -> None:
        if state is None or not getattr(state, "session_started", False):
            return
        letter = getattr(state, "active_letter", None)
        if letter not in self.template or getattr(state, "status", "") not in {"s_writing", "z_writing"}:
            return
        boxes = self._boxes()
        try:
            pressure = float(getattr(state, "pressure_bxy_uT", 0.0) or 0.0)
        except (TypeError, ValueError):
            pressure = 0.0
        brush_width = self.brush_width_for_pressure(pressure)
        point, _limit = self._jittered_for_state(state, boxes, brush_width)
        if point is None:
            return
        previous = self._last_brush_point if self._last_brush_letter == letter else None
        if previous is None or previous != point:
            stamped = stamp_brush(previous or point, point, brush_width)
            self._ink_paths.setdefault(letter, []).extend(stamped)
            self._ink_pressures.setdefault(letter, []).extend([pressure] * len(stamped))
            self._ink_widths.setdefault(letter, []).extend([brush_width] * len(stamped))
        self._last_brush_point = point
        self._last_brush_letter = letter

    def visible_geometry(self) -> dict:
        state = self.practice_state
        active_letter = getattr(state, "active_letter", None) if state is not None else "S"
        progress = float(getattr(state, "progress", 0.0) or 0.0) if state is not None else 0.0
        status = self._status_text(getattr(state, "status", None) if state is not None else None)
        boxes = self._boxes()
        grid = self._grid_geometry(boxes)
        default_span = min(boxes["S"][2] - boxes["S"][0], boxes["S"][3] - boxes["S"][1])
        jitter_limit = default_span * self.JITTER_LIMIT_FRACTION
        completed: dict[str, tuple] = {}
        active: dict[str, tuple] = {}
        if state is not None and active_letter in self.template:
            if active_letter == "Z":
                completed["S"] = self.template["S"]
            done, current = polyline_at_progress(self.template[active_letter], progress)
            if done:
                completed[active_letter] = done
            if current:
                active[active_letter] = current
        planned_mapped = self._mapped_paths(self.template, boxes)
        outline_mapped = self._mapped_outlines(boxes)
        completed_mapped = self._mapped_paths(completed, boxes)
        active_mapped = self._mapped_paths(active, boxes)
        point = self._last_brush_point
        point_width = self.brush_width_for_pressure(
            getattr(state, "pressure_bxy_uT", 0.0) if state is not None else 0.0
        )
        if state is not None and getattr(state, "session_started", False):
            if getattr(state, "status", "") in {"s_writing", "z_writing"} or point is None:
                point, jitter_limit = self._jittered_for_state(state, boxes, point_width)
            else:
                _current, jitter_limit = self._jittered_for_state(state, boxes, point_width)
        return {
            "frame": True,
            "template": dict(self.template),
            "planned": planned_mapped,
            "outline": outline_mapped,
            "path_visible": True,
            "boxes": boxes,
            "grid": grid,
            "completed": completed_mapped or {},
            "active": active_mapped or {},
            "ink": {letter: tuple(points) for letter, points in self._ink_paths.items() if points},
            "ink_pressure": {
                letter: tuple(values)
                for letter, values in self._ink_pressures.items()
                if values
            },
            "ink_widths": {
                letter: tuple(values)
                for letter, values in self._ink_widths.items()
                if values
            },
            "point": point,
            "point_color": self.pressure_color(
                getattr(state, "pressure_bxy_uT", 0.0) if state is not None else 0.0
            ),
            "point_width": point_width,
            "active_letter": active_letter,
            "progress": max(0.0, min(1.0, progress)),
            "status": status,
            "pause_remaining_s": float(getattr(state, "pause_remaining_s", 0.0) or 0.0) if state is not None else 0.0,
            "plan_width": self.PLAN_WIDTH,
            "ink_width": self.INK_WIDTH,
            "diffusion_width": self.INK_WIDTH + 8.0,
            "outline_width": self.OUTLINE_WIDTH,
            "jitter_limit": jitter_limit,
            "colors": {
                "template": COLORS["template_gray"],
                "completed": COLORS["completed_ink"],
                "current": COLORS["current_ink"],
                "pause": COLORS["pause_hint"],
            },
        }

    @staticmethod
    def _status_text(status):
        return {
            None: "等待开始",
            "idle_wait_start": "等待开始",
            "ready_wait_s_down": "等待 S 落笔",
            "idle_wait_s_down": "等待 S 落笔",
            "s_finished_pause": "S 完成，停顿",
            "s_paused": "S 已暂停",
            "z_paused": "Z 已暂停",
            "wait_z_up": "等待 Z 抬笔",
            "wait_z_down": "等待 Z 落笔",
            "done": "已完成",
        }.get(status, status or "等待开始")

    def paintEvent(self, event):  # noqa: N802 - Qt API name
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor(COLORS["surface"]))
        geometry = self.visible_geometry()
        rect = self._plot_rect()
        frame_pen = QtGui.QPen(QtGui.QColor(COLORS["secondary"]), 1)
        painter.setPen(frame_pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRect(rect)
        self._draw_grids(painter, geometry["grid"])
        self._draw_outlines(
            painter,
            geometry["outline"],
            COLORS["template_gray"],
            geometry["outline_width"],
        )
        self._draw_paths(
            painter,
            geometry["planned"],
            COLORS["template_gray"],
            geometry["plan_width"],
            alpha=190,
        )
        self._draw_pressure_paths(
            painter,
            geometry["ink"],
            geometry["ink_pressure"],
            geometry["ink_widths"],
            geometry["ink_width"],
        )
        point = geometry["point"]
        if point is not None:
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor(geometry["point_color"]))
            point_width = geometry["point_width"]
            painter.drawEllipse(QtCore.QPointF(*point), point_width / 2.0, point_width / 2.0)
        painter.setPen(QtGui.QColor(COLORS["ink"]))
        painter.drawText(QtCore.QPointF(rect.right() - 80, 26), f"{geometry['progress']:.0%}")

    def _draw_grids(self, painter, grids):
        border = QtGui.QColor(COLORS["secondary"])
        border.setAlpha(170)
        center = QtGui.QColor(COLORS["template_gray"])
        center.setAlpha(115)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.setPen(QtGui.QPen(border, 1.2, QtCore.Qt.SolidLine))
        for grid in grids.values():
            left, top, right, bottom = grid["box"]
            painter.drawRect(QtCore.QRectF(left, top, right - left, bottom - top))
            pen = QtGui.QPen(center, 1.0, QtCore.Qt.DashLine)
            pen.setDashPattern([5.0, 5.0])
            painter.setPen(pen)
            for start, end in grid["lines"]:
                painter.drawLine(QtCore.QPointF(*start), QtCore.QPointF(*end))
            painter.setPen(QtGui.QPen(border, 1.2, QtCore.Qt.SolidLine))

    def _draw_paths(self, painter, paths, color, width, *, alpha=255):
        qcolor = QtGui.QColor(color)
        qcolor.setAlpha(int(alpha))
        pen = QtGui.QPen(qcolor, float(width), QtCore.Qt.SolidLine,
                         QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin)
        painter.setPen(pen)
        for points in paths.values():
            if not points:
                continue
            path = QtGui.QPainterPath(QtCore.QPointF(*points[0]))
            for point in points[1:]:
                path.lineTo(QtCore.QPointF(*point))
            painter.drawPath(path)

    def _draw_outlines(self, painter, outlines, color, width):
        fill = QtGui.QColor(color)
        fill.setAlpha(65)
        edge = QtGui.QColor(color)
        edge.setAlpha(120)
        painter.setPen(QtGui.QPen(edge, 1.0, QtCore.Qt.SolidLine,
                                  QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin))
        painter.setBrush(fill)
        for points in outlines.values():
            if len(points) < 3:
                continue
            path = QtGui.QPainterPath(QtCore.QPointF(*points[0]))
            for point in points[1:]:
                path.lineTo(QtCore.QPointF(*point))
            path.closeSubpath()
            painter.drawPath(path)
        painter.setBrush(QtCore.Qt.NoBrush)

    def _draw_pressure_paths(self, painter, paths, pressures, widths, width):
        for letter, points in paths.items():
            if not points:
                continue
            samples = pressures.get(letter, ())
            width_samples = widths.get(letter, ())
            first_pressure = samples[0] if samples else 0.0
            first_width = width_samples[0] if width_samples else width
            diffusion = QtGui.QColor(self.pressure_color(first_pressure))
            diffusion.setAlpha(24)
            painter.setPen(QtGui.QPen(diffusion, float(first_width + 8.0), QtCore.Qt.SolidLine,
                                      QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin))
            painter.drawPoint(QtCore.QPointF(*points[0]))
            for index, point in enumerate(points[1:], start=1):
                pressure = samples[min(index, len(samples) - 1)] if samples else first_pressure
                stroke_width = width_samples[min(index, len(width_samples) - 1)] if width_samples else width
                color = QtGui.QColor(self.pressure_color(pressure))
                diffusion = QtGui.QColor(color)
                diffusion.setAlpha(24)
                painter.setPen(QtGui.QPen(diffusion, float(stroke_width + 8.0), QtCore.Qt.SolidLine,
                                          QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin))
                segment = QtGui.QPainterPath(QtCore.QPointF(*points[index - 1]))
                segment.lineTo(QtCore.QPointF(*point))
                painter.drawPath(segment)
                color.setAlpha(225)
                painter.setPen(QtGui.QPen(
                    color,
                    float(stroke_width),
                    QtCore.Qt.SolidLine,
                    QtCore.Qt.RoundCap,
                    QtCore.Qt.RoundJoin,
                ))
                painter.drawPath(segment)
