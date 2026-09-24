#!/usr/bin/env python3
"""Generate a monotone, data-derived slow-press StrokePlan offline."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import numpy as np

from brushbot.strokeplan import Stroke, StrokePlan


DEFAULT_CSV = Path("recordings/2026-09-10_18-18-48_367374.csv")
DEFAULT_START_MM = (-299.025, 500.067)
DEFAULT_DELTA_MM = (300.0, 0.0)


def _read_signal(path: Path) -> tuple[np.ndarray, np.ndarray]:
    if not path.exists():
        raise ValueError(f"cannot read recording: {path}")
    rows = []
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row.get("sample_valid") != "1":
                    continue
                try:
                    t, bx, by = (float(row[key]) for key in ("t_s", "dBx_uT", "dBy_uT"))
                except (TypeError, ValueError):
                    continue
                if all(math.isfinite(value) for value in (t, bx, by)):
                    rows.append((t, math.hypot(bx, by)))
    except OSError as exc:
        raise ValueError(f"cannot read recording: {path}") from exc
    if len(rows) < 100:
        raise ValueError(f"recording is too short after cleaning: {len(rows)} samples")
    data = np.asarray(rows, dtype=float)
    if np.any(np.diff(data[:, 0]) <= 0):
        raise ValueError("recording timestamps must be strictly increasing")
    return data[:, 0], data[:, 1]


def _moving_median(values: np.ndarray, window: int = 167) -> np.ndarray:
    window = max(3, int(window) | 1)
    pad = window // 2
    padded = np.pad(values, (pad, pad), mode="edge")
    return np.asarray([np.median(padded[i:i + window])
                       for i in range(len(values))], dtype=float)


def build_slow_press_plan(csv_path=DEFAULT_CSV, *, output=None, n_points=301,
                          max_depth_mm=3.0, speed_mm_s=5.0,
                          start_xy_mm=DEFAULT_START_MM,
                          delta_xy_mm=DEFAULT_DELTA_MM,
                          orientation_rpy_deg=(0.0, 5.0, 0.0),
                          baseline_start_s=1.0, baseline_end_s=8.0,
                          response_start_s=8.0, response_end_s=22.0):
    path = Path(csv_path)
    t, amplitude = _read_signal(path)
    if n_points < 3 or max_depth_mm <= 0 or speed_mm_s <= 0:
        raise ValueError("n_points >= 3, max_depth_mm and speed_mm_s must be positive")
    baseline_mask = (t >= baseline_start_s) & (t < baseline_end_s)
    response_mask = (t >= response_start_s) & (t <= response_end_s)
    if baseline_mask.sum() < 10 or response_mask.sum() < 10:
        raise ValueError("recording lacks the requested baseline or response window")
    smooth = _moving_median(amplitude)
    baseline = float(np.median(smooth[baseline_mask]))
    response = smooth[response_mask]
    # A slow press must not retract as the measured signal fluctuates.
    monotone = np.maximum.accumulate(response)
    lo = float(np.percentile(monotone, 5))
    hi = float(np.percentile(monotone, 95))
    if hi <= lo + 1e-9:
        raise ValueError("response signal has insufficient dynamic range")
    u = np.clip((monotone - lo) / (hi - lo), 0.0, 1.0)
    sample_s = np.linspace(0.0, 1.0, len(u))
    s = np.linspace(0.0, 1.0, int(n_points))
    g = np.interp(s, sample_s, response)
    g = np.maximum.accumulate(g)
    g[0] = max(0.0, baseline)
    depth = np.interp(s, sample_s, u) * float(max_depth_mm) / 1000.0
    start = np.asarray(start_xy_mm, dtype=float)
    delta = np.asarray(delta_xy_mm, dtype=float)
    if start.shape != (2,) or delta.shape != (2,) or not np.isfinite(np.r_[start, delta]).all():
        raise ValueError("start_xy_mm and delta_xy_mm must be finite 2-vectors")
    if np.linalg.norm(delta) <= 0:
        raise ValueError("delta_xy_mm must have positive length")
    xy = (start[None, :] + s[:, None] * delta[None, :]) / 1000.0
    orientation = np.deg2rad(np.asarray(orientation_rpy_deg, dtype=float))
    if orientation.shape != (3,) or not np.isfinite(orientation).all():
        raise ValueError("orientation_rpy_deg must be a finite 3-vector")
    duration = float(np.linalg.norm(delta) / speed_mm_s)
    plan = StrokePlan(
        [Stroke(s=s, xy=xy, g_press=g, z_ff=depth)],
        meta={
            "generation": "monotone_slow_press_from_dBxy",
            "source_csv": str(path),
            "cleaning": "sample_valid=1, finite, monotone timestamps; monotone envelope",
            "baseline_window_s": [baseline_start_s, baseline_end_s],
            "response_window_s": [response_start_s, response_end_s],
            "baseline_dBxy_uT": baseline,
            "max_depth_mm": float(max_depth_mm),
            "speed_mm_s": float(speed_mm_s),
            "orientation_rpy_rad": orientation.tolist(),
            "stroke_durations_s": [duration],
        },
    )
    if output is not None:
        plan.save(output)
    return plan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default=str(DEFAULT_CSV))
    parser.add_argument("--output", default="slow_press_from_experiment2.npz")
    parser.add_argument("--n-points", type=int, default=301)
    parser.add_argument("--max-depth-mm", type=float, default=3.0)
    parser.add_argument("--speed-mm-s", type=float, default=5.0)
    args = parser.parse_args(argv)
    plan = build_slow_press_plan(args.csv, output=args.output,
                                 n_points=args.n_points,
                                 max_depth_mm=args.max_depth_mm,
                                 speed_mm_s=args.speed_mm_s)
    print(f"saved {args.output} ({len(plan.strokes[0].s)} points)")


if __name__ == "__main__":
    main()
