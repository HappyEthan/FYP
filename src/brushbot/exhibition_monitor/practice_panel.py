"""Controls and status display for pressure-driven S/Z practice."""

from __future__ import annotations

import math

from PyQt5 import QtWidgets

from .theme import COLORS


_STATUS_TEXT = {
    "idle_wait_s_down": "等待 S 下笔",
    "s_writing": "正在书写 S",
    "s_paused": "S 已暂停",
    "s_finished_pause": "S 完成，停顿",
    "wait_z_up": "等待 Z 抬笔",
    "wait_z_down": "等待 Z 下笔",
    "z_writing": "正在书写 Z",
    "z_paused": "Z 已暂停",
    "done": "已完成",
}


class PracticePanel(QtWidgets.QGroupBox):
    """Display practice state; the state machine remains owned by the window."""

    def __init__(self, parent=None):
        super().__init__("SZ 临摹", parent)
        self._build_ui()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(10)

        self.generate_button = QtWidgets.QPushButton("生成 SZ", objectName="generate-sz")
        self.reset_button = QtWidgets.QPushButton("重新开始", objectName="reset-practice")
        layout.addWidget(self.generate_button)
        layout.addWidget(self.reset_button)

        self.status_label = QtWidgets.QLabel("等待开始", objectName="practice-status")
        self.status_label.setStyleSheet(f"color: {COLORS['ink']}; font-weight: 700;")
        layout.addWidget(self.status_label)
        self.pressure_label = QtWidgets.QLabel("压力：— µT", objectName="practice-pressure")
        layout.addWidget(self.pressure_label)
        self.progress_label = QtWidgets.QLabel("进度：0%", objectName="practice-progress")
        layout.addWidget(self.progress_label)
        layout.addStretch()

    def apply_state(self, state) -> None:
        """Render an engine state without making any state-machine decisions."""
        status = getattr(state, "status", None)
        self.status_label.setText(_STATUS_TEXT.get(status, str(status or "等待开始")))
        pressure = getattr(state, "pressure_bxy_uT", None)
        try:
            pressure = float(pressure)
        except (TypeError, ValueError):
            pressure = None
        self.pressure_label.setText(
            f"压力：{pressure:.1f} µT" if pressure is not None and math.isfinite(pressure) else "压力：— µT"
        )
        try:
            progress = max(0.0, min(1.0, float(getattr(state, "progress", 0.0))))
        except (TypeError, ValueError):
            progress = 0.0
        self.progress_label.setText(f"进度：{progress:.0%}")

    def set_hold_status(self, message: str) -> None:
        """Show a transport/baseline hold without mutating the engine state."""
        self.status_label.setText(str(message))
