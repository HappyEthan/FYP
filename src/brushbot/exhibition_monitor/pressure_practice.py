"""Deterministic, GUI-independent pressure practice state machine."""

from dataclasses import dataclass
import math
from typing import Mapping, Sequence


@dataclass(frozen=True)
class PracticeConfig:
    threshold_uT: float = 100.0
    down_threshold_uT: float = 110.0
    up_threshold_uT: float = 90.0
    debounce_s: float = 0.08
    inter_letter_pause_s: float = 1.0
    fast_pressure_uT: float = 300.0
    min_speed: float = 0.05
    max_speed: float = 0.80


@dataclass(frozen=True)
class PracticeState:
    status: str
    active_letter: str | None
    progress: float
    pen_down: bool
    pressure_bxy_uT: float | None
    pause_remaining_s: float


class PressurePracticeEngine:
    """Integrate pressure-controlled progress through an S then Z template."""

    def __init__(
        self,
        template: Mapping[str, Sequence[tuple[float, float]]],
        config: PracticeConfig | None = None,
    ) -> None:
        if "S" not in template or "Z" not in template:
            raise ValueError("template must contain S and Z")
        self.template = template
        self.config = config or PracticeConfig()
        self.reset()

    def reset(self) -> None:
        self._status = "idle_wait_s_down"
        self._active_letter: str | None = "S"
        self._progress = 0.0
        self._stable_down = False
        self._candidate_down: bool | None = None
        self._candidate_since: float | None = None
        self._last_update_s: float | None = None
        self._pause_until_s: float | None = None
        self._pressure: float | None = None

    @property
    def state(self) -> PracticeState:
        now = self._last_update_s
        remaining = 0.0
        if self._pause_until_s is not None and now is not None:
            remaining = max(0.0, self._pause_until_s - now)
        return PracticeState(
            status=self._status,
            active_letter=self._active_letter,
            progress=self._progress,
            pen_down=self._stable_down,
            pressure_bxy_uT=self._pressure,
            pause_remaining_s=remaining,
        )

    def update(self, pressure_bxy_uT: float | None, now_s: float) -> PracticeState:
        valid = pressure_bxy_uT is not None and math.isfinite(pressure_bxy_uT)
        self._pressure = pressure_bxy_uT if valid else None
        if not valid:
            return self.state

        previous = self._last_update_s
        self._last_update_s = now_s
        dt = 0.0 if previous is None else min(0.2, max(0.0, now_s - previous))

        self._update_pen_state(float(pressure_bxy_uT), now_s)

        if self._status == "s_finished_pause":
            if self._pause_until_s is not None and now_s >= self._pause_until_s:
                self._status = "wait_z_down" if not self._stable_down else "wait_z_up"
                self._active_letter = "Z"
                self._progress = 0.0
                self._pause_until_s = None
            return self.state

        if self._status == "idle_wait_s_down":
            if self._stable_down:
                self._status = "s_writing"
            return self.state
        if self._status == "s_paused":
            if self._stable_down:
                self._status = "s_writing"
            return self.state
        if self._status == "wait_z_up":
            if not self._stable_down:
                self._status = "wait_z_down"
            return self.state
        if self._status == "wait_z_down":
            if self._stable_down:
                self._status = "z_writing"
            return self.state
        if self._status == "z_paused":
            if self._stable_down:
                self._status = "z_writing"
            return self.state
        if self._status not in ("s_writing", "z_writing"):
            return self.state

        if not self._stable_down:
            self._status = "s_paused" if self._active_letter == "S" else "z_paused"
            return self.state

        pressure = float(pressure_bxy_uT)
        normalized = max(0.0, min(1.0, (pressure - self.config.threshold_uT) / (
            self.config.fast_pressure_uT - self.config.threshold_uT
        )))
        speed = self.config.min_speed + normalized * (self.config.max_speed - self.config.min_speed)
        self._progress = min(1.0, self._progress + speed * dt)
        if self._progress >= 1.0:
            if self._active_letter == "S":
                self._status = "s_finished_pause"
                self._active_letter = "S"
                self._pause_until_s = now_s + self.config.inter_letter_pause_s
            else:
                self._status = "done"
                self._active_letter = "Z"
                self._pause_until_s = None
        return self.state

    def _update_pen_state(self, pressure: float, now_s: float) -> None:
        if pressure >= self.config.down_threshold_uT:
            candidate = True
        elif pressure <= self.config.up_threshold_uT:
            candidate = False
        else:
            return
        if candidate == self._stable_down:
            self._candidate_down = None
            self._candidate_since = None
            return
        if candidate != self._candidate_down:
            self._candidate_down = candidate
            self._candidate_since = now_s
        elif self._candidate_since is not None and now_s - self._candidate_since >= self.config.debounce_s:
            self._stable_down = candidate
            self._candidate_down = None
            self._candidate_since = None
