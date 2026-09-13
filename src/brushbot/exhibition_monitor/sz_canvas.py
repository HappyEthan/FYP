"""QPainter widget for the normalized S/Z pressure-practice templates."""

from __future__ import annotations

from collections.abc import Mapping

from PyQt5 import QtCore, QtGui, QtWidgets

from .sz_template import load_sz_template, polyline_at_progress
from .theme import COLORS


class SZCanvas(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.template = load_sz_template()
        self.practice_state = None
        self.setMinimumSize(420, 300)

    def set_template(self, template: Mapping[str, tuple[tuple[float, float], ...]]) -> None:
        if "S" not in template or "Z" not in template:
            raise ValueError("template must contain S and Z")
        self.template = {letter: tuple((float(x), float(y)) for x, y in template[letter]) for letter in ("S", "Z")}
        self.update()

    def set_practice_state(self, state) -> None:
        self.practice_state = state
        self.update()

    def reset(self) -> None:
        self.practice_state = None
        self.update()

    def visible_geometry(self) -> dict:
        state = self.practice_state
        active_letter = getattr(state, "active_letter", None) if state is not None else "S"
        progress = float(getattr(state, "progress", 0.0) or 0.0) if state is not None else 0.0
        status = getattr(state, "status", None) if state is not None else None
        status = self._status_text(status)
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
        elif state is not None and status == "已完成":
            completed = dict(self.template)
        return {
            "frame": True,
            "template": dict(self.template),
            "completed": completed,
            "active": active,
            "active_letter": active_letter,
            "progress": max(0.0, min(1.0, progress)),
            "status": status,
            "pause_remaining_s": float(getattr(state, "pause_remaining_s", 0.0) or 0.0) if state is not None else 0.0,
            "colors": {"template": COLORS["template_gray"], "completed": COLORS["completed_ink"], "current": COLORS["current_ink"], "pause": COLORS["pause_hint"]},
        }

    @staticmethod
    def _status_text(status):
        return {None: "等待开始", "done": "已完成", "s_finished_pause": "停顿后继续", "s_paused": "已停顿", "z_paused": "已停顿"}.get(status, status or "等待开始")

    def _plot_rect(self):
        return QtCore.QRectF(self.rect()).adjusted(24.0, 34.0, -24.0, -42.0)

    def _map(self, point, rect):
        scale = min(rect.width(), rect.height())
        ox = rect.left() + (rect.width() - scale) / 2
        oy = rect.top() + (rect.height() - scale) / 2
        return QtCore.QPointF(ox + point[0] * scale, oy + point[1] * scale)

    def paintEvent(self, event):  # noqa: N802
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
        self._draw_paths(painter, geometry["template"], COLORS["template_gray"], rect, 4)
        self._draw_paths(painter, geometry["completed"], COLORS["completed_ink"], rect, 6)
        self._draw_paths(painter, geometry["active"], COLORS["current_ink"], rect, 6)
        painter.setPen(QtGui.QColor(COLORS["ink"]))
        painter.drawText(QtCore.QPointF(rect.left(), 22), f"{geometry['active_letter'] or '—'}  {geometry['status']}")
        painter.drawText(QtCore.QPointF(rect.right() - 80, 22), f"{geometry['progress']:.0%}")

    def _draw_paths(self, painter, paths, color, rect, width):
        pen = QtGui.QPen(QtGui.QColor(color), width, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin)
        painter.setPen(pen)
        for points in paths.values():
            if not points:
                continue
            path = QtGui.QPainterPath(self._map(points[0], rect))
            for point in points[1:]:
                path.lineTo(self._map(point, rect))
            painter.drawPath(path)
