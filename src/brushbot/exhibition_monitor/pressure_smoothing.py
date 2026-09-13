"""Shared pressure smoothing for the writer and its graph."""

from __future__ import annotations

from collections import deque
import math
from statistics import median


class PressureSmoother:
    """Remove short spikes, then apply a causal EMA low-pass filter."""

    def __init__(self, *, window: int = 5, alpha: float = 0.2):
        window = int(window)
        if window < 1 or window % 2 == 0:
            raise ValueError("window must be a positive odd integer")
        alpha = float(alpha)
        if not math.isfinite(alpha) or not 0.0 < alpha <= 1.0:
            raise ValueError("alpha must be finite and in (0, 1]")
        self.window = window
        self.alpha = alpha
        self._recent: deque[float] = deque(maxlen=window)
        self._smooth: float | None = None

    @property
    def value(self) -> float | None:
        return self._smooth

    def reset(self) -> None:
        self._recent.clear()
        self._smooth = None

    def update(self, value: float | None) -> float | None:
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value):
            return None
        self._recent.append(value)
        filtered = float(median(self._recent))
        if self._smooth is None:
            self._smooth = filtered
        else:
            self._smooth = self.alpha * filtered + (1.0 - self.alpha) * self._smooth
        return self._smooth


def smooth_pressure_series(
    times, values, *, window: int = 5, alpha: float = 0.2
) -> list[tuple[float, float]]:
    """Return finite, time-aligned `(time, smoothed_pressure)` pairs."""
    smoother = PressureSmoother(window=window, alpha=alpha)
    result = []
    for time_value, value in zip(times or [], values or []):
        try:
            time_value = float(time_value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(time_value):
            continue
        smoothed = smoother.update(value)
        if smoothed is not None:
            result.append((time_value, smoothed))
    return result
