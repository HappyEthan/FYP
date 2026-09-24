"""Stable normalized two-stroke writing templates and arc-length helpers."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

Point = tuple[float, float]


_TEMPLATE: dict[str, tuple[Point, ...]] = {
    # Compatibility keys remain S/Z, while the visible practice is now two
    # simple strokes: first horizontal, then vertical.
    "S": ((0.08, 0.50), (0.92, 0.50)),
    "Z": ((0.50, 0.08), (0.50, 0.92)),
}


def load_sz_template() -> dict[str, tuple[Point, ...]]:
    """Return a fresh, normalized horizontal-then-vertical template mapping."""
    return {letter: tuple(points) for letter, points in _TEMPLATE.items()}


def layout_sz(
    template: Mapping[str, Sequence[Point]],
    canvas_rect: tuple[float, float, float, float],
    gutter: float = 48.0,
) -> dict[str, tuple[float, float, float, float]]:
    """Return separate left/right letter boxes inside ``canvas_rect``."""
    if "S" not in template or "Z" not in template:
        raise ValueError("template must contain S and Z")
    left, top, right, bottom = (float(value) for value in canvas_rect)
    width = max(0.0, right - left)
    height = max(0.0, bottom - top)
    gutter = max(0.0, float(gutter))
    box_width = max(0.0, (width - gutter) / 2.0)
    return {
        "S": (left, top, left + box_width, bottom),
        "Z": (left + box_width + gutter, top, right, bottom),
    }


def jittered_point(
    center: Point,
    xy: Point | None,
    *,
    jitter_gain: float,
    max_offset: float,
) -> Point:
    """Apply XYPlot's right/up orientation and clamp the offset radius."""
    cx, cy = float(center[0]), float(center[1])
    try:
        if xy is None:
            raise TypeError
        x, y = float(xy[0]), float(xy[1])
    except (TypeError, ValueError, IndexError):
        x, y = 0.0, 0.0
    try:
        gain = max(0.0, float(jitter_gain))
        limit = max(0.0, float(max_offset))
    except (TypeError, ValueError):
        gain, limit = 0.0, 0.0
    dx, dy = x * gain, -y * gain
    magnitude = math.hypot(dx, dy)
    if magnitude > limit > 0.0:
        scale = limit / magnitude
        dx, dy = dx * scale, dy * scale
    elif limit <= 0.0:
        dx, dy = 0.0, 0.0
    return cx + dx, cy + dy


def stamp_brush(previous: Point, current: Point, brush_width: float) -> tuple[Point, ...]:
    """Return interpolated brush centers so a thick stroke has no gaps."""
    start = (float(previous[0]), float(previous[1]))
    end = (float(current[0]), float(current[1]))
    spacing = max(1.0, float(brush_width) * 0.45)
    distance = math.hypot(end[0] - start[0], end[1] - start[1])
    count = max(1, int(math.ceil(distance / spacing)))
    return tuple(
        (
            start[0] + (end[0] - start[0]) * index / count,
            start[1] + (end[1] - start[1]) * index / count,
        )
        for index in range(count + 1)
    )


def calligraphic_outline(
    points: Sequence[Point], width: float, *, stroke: str = "horizontal"
) -> tuple[Point, ...]:
    """Build a sampled, asymmetrical brush outline around a centerline.

    The profiles are traced from a regular-script long horizontal and hanging-
    needle vertical: the entry has a small pressed shoulder, the shaft settles
    into a stable body, and the exit progressively lifts to a sharp tip.  The
    two sides intentionally use slightly different widths/forward offsets so
    the result is not a mathematically symmetric capsule.
    """
    source = tuple((float(x), float(y)) for x, y in points)
    if not source:
        return ()
    if len(source) == 1:
        half = max(0.0, float(width)) / 2.0
        x, y = source[0]
        return ((x - half, y), (x, y - half), (x + half, y), (x, y + half))
    if stroke == "horizontal":
        profile = (
            (0.00, 0.62, 0.48, -0.10, -0.03),
            (0.04, 0.92, 0.80, -0.04, -0.01),
            (0.10, 1.00, 0.96, -0.01, 0.00),
            (0.18, 0.96, 0.94, 0.00, 0.00),
            (0.30, 0.90, 0.88, 0.00, 0.00),
            (0.45, 0.88, 0.86, 0.00, 0.00),
            (0.60, 0.90, 0.90, 0.00, 0.00),
            (0.74, 0.86, 0.82, 0.01, 0.02),
            (0.86, 0.68, 0.56, 0.02, 0.04),
            (0.94, 0.32, 0.25, 0.04, 0.06),
            (1.00, 0.02, 0.02, 0.06, 0.08),
        )
    else:
        profile = (
            (0.00, 0.66, 0.52, -0.04, -0.02),
            (0.04, 0.92, 0.80, -0.02, 0.00),
            (0.10, 1.00, 0.94, 0.00, 0.00),
            (0.18, 0.96, 0.92, 0.00, 0.00),
            (0.32, 0.90, 0.88, 0.00, 0.00),
            (0.48, 0.88, 0.86, 0.00, 0.00),
            (0.64, 0.88, 0.86, 0.00, 0.00),
            (0.76, 0.82, 0.78, 0.01, 0.02),
            (0.86, 0.60, 0.50, 0.03, 0.04),
            (0.94, 0.24, 0.18, 0.06, 0.07),
            (1.00, 0.015, 0.015, 0.09, 0.10),
        )
    lengths = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(source, source[1:])]
    total = sum(lengths)
    if total <= 0.0:
        return calligraphic_outline((source[0],), width)

    def at_fraction(fraction: float) -> tuple[Point, Point]:
        target = total * max(0.0, min(1.0, fraction))
        travelled = 0.0
        for index, length in enumerate(lengths):
            if travelled + length >= target or index == len(lengths) - 1:
                start, end = source[index], source[index + 1]
                ratio = 0.0 if length == 0.0 else (target - travelled) / length
                point = (start[0] + ratio * (end[0] - start[0]), start[1] + ratio * (end[1] - start[1]))
                tangent = (end[0] - start[0], end[1] - start[1])
                magnitude = math.hypot(*tangent) or 1.0
                return point, (tangent[0] / magnitude, tangent[1] / magnitude)
            travelled += length
        return source[-1], (0.0, 1.0)

    left, right = [], []
    for fraction, left_factor, right_factor, left_lead, right_lead in profile:
        point, tangent = at_fraction(fraction)
        normal = (-tangent[1], tangent[0])
        brush_width = max(0.0, float(width))
        left_radius = brush_width * left_factor / 2.0
        right_radius = brush_width * right_factor / 2.0
        left.append(
            (
                point[0] + tangent[0] * brush_width * left_lead + normal[0] * left_radius,
                point[1] + tangent[1] * brush_width * left_lead + normal[1] * left_radius,
            )
        )
        right.append(
            (
                point[0] + tangent[0] * brush_width * right_lead - normal[0] * right_radius,
                point[1] + tangent[1] * brush_width * right_lead - normal[1] * right_radius,
            )
        )
    return tuple(left + list(reversed(right)))


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
