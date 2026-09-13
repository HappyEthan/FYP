"""Deterministic, GUI-independent pressure practice state machine."""

from dataclasses import dataclass
import math
from typing import Mapping, Sequence

from .pressure_smoothing import PressureSmoother


@dataclass(frozen=True)
class PracticeConfig:
    threshold_uT: float = 200.0
    down_threshold_uT: float = 210.0
    up_threshold_uT: float = 180.0
    debounce_s: float = 0.12
    inter_letter_pause_s: float = 1.0
    fast_pressure_uT: float = 400.0
    min_speed: float = 0.02
    max_speed: float = 0.30
    smoothing_window: int = 3
    smoothing_alpha: float = 0.20

    def __post_init__(self):
        thresholds = (self.threshold_uT, self.down_threshold_uT, self.up_threshold_uT)
        if not all(math.isfinite(float(value)) for value in thresholds):
            raise ValueError("pressure thresholds must be finite")
        if self.up_threshold_uT >= self.threshold_uT or self.threshold_uT >= self.down_threshold_uT:
            raise ValueError("thresholds must satisfy up < threshold < down")
        if not math.isfinite(float(self.fast_pressure_uT)) or self.fast_pressure_uT <= self.threshold_uT:
            raise ValueError("fast_pressure_uT must exceed threshold_uT")
        if not math.isfinite(float(self.min_speed)) or not math.isfinite(float(self.max_speed)):
            raise ValueError("speeds must be finite")
        if self.min_speed < 0.0 or self.max_speed < self.min_speed:
            raise ValueError("speeds must satisfy max_speed >= min_speed >= 0")
        if (
            not math.isfinite(float(self.debounce_s))
            or not math.isfinite(float(self.inter_letter_pause_s))
            or self.debounce_s < 0.0
            or self.inter_letter_pause_s < 0.0
        ):
            raise ValueError("timings must be finite and non-negative")
        if self.smoothing_window < 1 or self.smoothing_window % 2 == 0:
            raise ValueError("smoothing_window must be a positive odd integer")
        if not math.isfinite(float(self.smoothing_alpha)) or not 0.0 < self.smoothing_alpha <= 1.0:
            raise ValueError("smoothing_alpha must be finite and in (0, 1]")


@dataclass(frozen=True)
class PracticeState:
    status: str
    active_letter: str | None
    progress: float
    pen_down: bool
    pressure_bxy_uT: float | None
    pause_remaining_s: float
    session_started: bool = False
    page_active: bool = True


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
        self._status = "idle_wait_start"
        self._active_letter: str | None = "S"
        self._progress = 0.0
        self._session_started = False
        self._page_active = True
        self._stable_down = False
        self._candidate_down: bool | None = None
        self._candidate_since: float | None = None
        self._last_update_s: float | None = None
        self._pause_until_s: float | None = None
        self._pressure: float | None = None
        self._smoother = PressureSmoother(
            window=self.config.smoothing_window,
            alpha=self.config.smoothing_alpha,
        )

    def start_session(self, now_s: float) -> PracticeState:
        """Arm a fresh S/Z session; pressure must still trigger the first stroke."""
        self._status = "ready_wait_s_down"
        self._active_letter = "S"
        self._progress = 0.0
        self._session_started = True
        self._stable_down = False
        self._candidate_down = None
        self._candidate_since = None
        self._last_update_s = float(now_s)
        self._pause_until_s = None
        self._pressure = None
        self._smoother = PressureSmoother(
            window=self.config.smoothing_window,
            alpha=self.config.smoothing_alpha,
        )
        return self.state

    def set_page_active(self, active: bool, now_s: float | None = None) -> PracticeState:
        """Pause path-time integration while the writing page is hidden."""
        self._page_active = bool(active)
        if now_s is not None:
            self._last_update_s = float(now_s)
        elif not self._page_active and self._last_update_s is None:
            self._last_update_s = 0.0
        return self.state

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
            session_started=self._session_started,
            page_active=self._page_active,
        )

    def update(self, pressure_bxy_uT: float | None, now_s: float) -> PracticeState:
        valid = pressure_bxy_uT is not None
        try:
            raw_pressure = float(pressure_bxy_uT)
        except (TypeError, ValueError):
            valid = False
            raw_pressure = None
        if valid and not math.isfinite(raw_pressure):
            valid = False
        self._pressure = self._smoother.update(raw_pressure) if valid else None
        valid = self._pressure is not None
        if not valid:
            self._last_update_s = now_s
            return self.state

        previous = self._last_update_s
        self._last_update_s = now_s
        dt = 0.0 if previous is None else min(0.2, max(0.0, now_s - previous))

        self._update_pen_state(float(self._pressure), now_s)

        if not self._page_active:
            return self.state

        if self._status == "s_finished_pause":
            if self._pause_until_s is not None and now_s >= self._pause_until_s:
                self._status = "wait_z_down" if not self._stable_down else "wait_z_up"
                self._active_letter = "Z"
                self._progress = 0.0
                self._pause_until_s = None
            return self.state

        if self._status in ("idle_wait_start", "ready_wait_s_down"):
            if self._status == "idle_wait_start":
                return self.state
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

        pressure = float(self._pressure)
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

    def invalidate_clock(self, now_s: float) -> None:
        """Drop elapsed integration time without changing visible practice progress."""
        self._last_update_s = float(now_s)

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
