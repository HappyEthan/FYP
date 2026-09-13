"""Stable normalized S/Z writing templates and arc-length helpers."""

from __future__ import annotations

import math
from collections.abc import Sequence

Point = tuple[float, float]


_TEMPLATE: dict[str, tuple[Point, ...]] = {
    # Both paths are ordered in the direction a brush would naturally write.
    "S": (
        (0.78, 0.14), (0.62, 0.06), (0.38, 0.06), (0.20, 0.16),
        (0.18, 0.30), (0.30, 0.40), (0.52, 0.46), (0.72, 0.54),
        (0.82, 0.66), (0.76, 0.82), (0.58, 0.94), (0.34, 0.94),
        (0.16, 0.84),
    ),
    "Z": (
        (0.18, 0.12), (0.82, 0.12), (0.18, 0.88), (0.82, 0.88),
    ),
}


def load_sz_template() -> dict[str, tuple[Point, ...]]:
    """Return a fresh, normalized S-then-Z template mapping."""
    return {letter: tuple(points) for letter, points in _TEMPLATE.items()}


def polyline_at_progress(
    points: Sequence[Point], progress: float
) -> tuple[tuple[Point, ...], tuple[Point, ...]]:
    """Split *points* at normalized cumulative arc-length progress.

    The interpolated point is shared by the completed and active portions so
    that painting either portion remains visually continuous.  At zero the
    active portion retains the original starting point; at one the completed
    portion is the complete source polyline.
    """
    source = tuple((float(x), float(y)) for x, y in points)
    if not source:
        return (), ()
    if len(source) == 1:
        return ((), source) if progress <= 0 else (source, ())
    try:
        fraction = float(progress)
    except (TypeError, ValueError):
        fraction = 0.0
    if not math.isfinite(fraction):
        fraction = 0.0 if fraction < 0 else 1.0
    fraction = max(0.0, min(1.0, fraction))
    lengths = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(source, source[1:])]
    total = sum(lengths)
    if total <= 0.0:
        return (source, ()) if fraction >= 1.0 else ((), source)
    if fraction <= 0.0:
        return (), source
    if fraction >= 1.0:
        return source, ()
    target = total * fraction
    travelled = 0.0
    for index, length in enumerate(lengths):
        if travelled + length >= target:
            start, end = source[index], source[index + 1]
            ratio = 0.0 if length == 0.0 else (target - travelled) / length
            current = (start[0] + ratio * (end[0] - start[0]), start[1] + ratio * (end[1] - start[1]))
            return source[: index + 1] + (current,), (current,) + source[index + 1 :]
        travelled += length
    return source, ()
