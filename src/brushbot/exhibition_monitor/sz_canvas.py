"""QPainter canvas for a separated, jittered S/Z writing surface."""

from __future__ import annotations

from collections.abc import Mapping

from PyQt5 import QtCore, QtGui, QtWidgets

from .sz_template import (
    jittered_point,
    layout_sz,
    load_sz_template,
    polyline_at_progress,
    stamp_brush,
)
from .theme import COLORS


class SZCanvas(QtWidgets.QWidget):
    """Render the plan band, pressure-driven ink and one jittered brush point."""

    PLAN_WIDTH = 28.0
    INK_WIDTH = 18.0
    BRUSH_WIDTH = 20.0
    JITTER_GAIN = 0.08

    def __init__(self, parent=None):
        super().__init__(parent)
        self.template = load_sz_template()
        self.practice_state = None
        self.sensor_xy = (0.0, 0.0)
        self._ink_paths: dict[str, list[tuple[float, float]]] = {"S": [], "Z": []}
        self._last_brush_point: tuple[float, float] | None = None
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
        self._last_brush_point = None

    def reset(self) -> None:
        self.practice_state = None
        self.reset_ink()
        self.update()

    def _plot_rect(self) -> QtCore.QRectF:
        return QtCore.QRectF(self.rect()).adjusted(24.0, 42.0, -24.0, -24.0)

    def _boxes(self) -> dict[str, tuple[float, float, float, float]]:
        rect = self._plot_rect()
        return layout_sz(
            self.template,
            (rect.left(), rect.top(), rect.right(), rect.bottom()),
            gutter=max(24.0, rect.width() * 0.08),
        )

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

    def _capture_brush_sample(self, state) -> None:
        if state is None or not getattr(state, "session_started", False):
            return
        letter = getattr(state, "active_letter", None)
        if letter not in self.template or getattr(state, "status", "") not in {"s_writing", "z_writing"}:
            return
        boxes = self._boxes()
        center = self._center_for_state(state, boxes)
        if center is None:
            return
        max_offset = max(0.0, self.PLAN_WIDTH / 2.0 - self.BRUSH_WIDTH / 2.0)
        point = jittered_point(center, self.sensor_xy, jitter_gain=self.JITTER_GAIN, max_offset=max_offset)
        previous = self._last_brush_point
        if previous is None or previous != point:
            self._ink_paths.setdefault(letter, []).extend(stamp_brush(previous or point, point, self.BRUSH_WIDTH))
        self._last_brush_point = point

    def visible_geometry(self) -> dict:
        state = self.practice_state
        active_letter = getattr(state, "active_letter", None) if state is not None else "S"
        progress = float(getattr(state, "progress", 0.0) or 0.0) if state is not None else 0.0
        status = self._status_text(getattr(state, "status", None) if state is not None else None)
        boxes = self._boxes()
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
        completed_mapped = self._mapped_paths(completed, boxes)
        active_mapped = self._mapped_paths(active, boxes)
        point = self._last_brush_point
        if state is not None and getattr(state, "session_started", False):
            if getattr(state, "status", "") in {"s_writing", "z_writing"} or point is None:
                point = self._center_for_state(state, boxes)
                if point is not None:
                    max_offset = max(0.0, self.PLAN_WIDTH / 2.0 - self.BRUSH_WIDTH / 2.0)
                    point = jittered_point(point, self.sensor_xy, jitter_gain=self.JITTER_GAIN, max_offset=max_offset)
        return {
            "frame": True,
            "template": dict(self.template),
            "planned": self._mapped_paths(self.template, boxes),
            "boxes": boxes,
            "completed": completed_mapped or {},
            "active": active_mapped or {},
            "ink": {letter: tuple(points) for letter, points in self._ink_paths.items() if points},
            "point": point,
            "active_letter": active_letter,
            "progress": max(0.0, min(1.0, progress)),
            "status": status,
            "pause_remaining_s": float(getattr(state, "pause_remaining_s", 0.0) or 0.0) if state is not None else 0.0,
            "plan_width": self.PLAN_WIDTH,
            "ink_width": self.INK_WIDTH,
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
        self._draw_paths(painter, geometry["planned"], COLORS["template_gray"], geometry["plan_width"])
        self._draw_paths(painter, geometry["ink"], COLORS["completed_ink"], geometry["ink_width"])
        self._draw_paths(painter, geometry["completed"], COLORS["completed_ink"], geometry["ink_width"])
        self._draw_paths(painter, geometry["active"], COLORS["current_ink"], geometry["ink_width"])
        point = geometry["point"]
        if point is not None:
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor(COLORS["current_ink"]))
            painter.drawEllipse(QtCore.QPointF(*point), self.BRUSH_WIDTH / 2.0, self.BRUSH_WIDTH / 2.0)
        painter.setPen(QtGui.QColor(COLORS["ink"]))
        painter.drawText(QtCore.QPointF(rect.left(), 26), f"SZ  {geometry['status']}")
        painter.drawText(QtCore.QPointF(rect.right() - 80, 26), f"{geometry['progress']:.0%}")

    def _draw_paths(self, painter, paths, color, width):
        pen = QtGui.QPen(QtGui.QColor(color), float(width), QtCore.Qt.SolidLine,
                         QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin)
        painter.setPen(pen)
        for points in paths.values():
            if not points:
                continue
            path = QtGui.QPainterPath(QtCore.QPointF(*points[0]))
            for point in points[1:]:
                path.lineTo(QtCore.QPointF(*point))
            painter.drawPath(path)
