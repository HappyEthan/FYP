"""Pure trajectory compilation and return-route geometry; never moves hardware."""

from __future__ import annotations

import copy
import math
from typing import Iterable

import numpy as np

from brushbot.experiments.config import validate_experiment
from brushbot.strokeplan import Stroke, StrokePlan


def tcp_z_m(contact_z_mm: float, depth_mm: float) -> float:
    """Convert positive-down brush depth to the root-TCP world Z coordinate."""
    contact = float(contact_z_mm)
    depth = float(depth_mm)
    if not math.isfinite(contact) or not math.isfinite(depth):
        raise ValueError("contact_z_mm and depth_mm must be finite")
    return (contact - depth) / 1000.0


def _positive(value, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a positive finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a positive finite number") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{field} must be a positive finite number")
    return number


def time_law(length_mm: float, speed_mm_s: float, accel_mm_s2: float,
             dt_s: float) -> dict:
    """Sample a symmetric triangular/trapezoidal distance profile."""
    length = _positive(length_mm, "length_mm")
    speed = _positive(speed_mm_s, "speed_mm_s")
    accel = _positive(accel_mm_s2, "accel_mm_s2")
    dt = _positive(dt_s, "dt_s")

    t_acc = min(speed / accel, math.sqrt(length / accel))
    v_peak = accel * t_acc
    d_acc = 0.5 * accel * t_acc * t_acc
    remaining = max(length - 2.0 * d_acc, 0.0)
    t_cruise = remaining / v_peak
    duration = 2.0 * t_acc + t_cruise

    t = np.arange(0.0, duration, dt, dtype=float)
    if len(t) == 0 or not math.isclose(float(t[-1]), duration, abs_tol=1e-12):
        t = np.append(t, duration)
    distance = np.empty_like(t)
    phases = np.empty(len(t), dtype="U9")
    triangular = t_cruise <= 1e-12
    for index, instant in enumerate(t):
        if instant < t_acc or (triangular and instant <= t_acc):
            distance[index] = 0.5 * accel * instant * instant
            phases[index] = "ramp_up"
        elif not triangular and instant <= t_acc + t_cruise:
            distance[index] = d_acc + v_peak * (instant - t_acc)
            phases[index] = "cruise"
        else:
            remaining_t = duration - instant
            distance[index] = length - 0.5 * accel * remaining_t * remaining_t
            phases[index] = "ramp_down"
    distance[0] = 0.0
    distance[-1] = length
    return {
        "t_s": t,
        "distance_mm": distance,
        "s": distance / length,
        "phase": phases,
        "duration_s": float(duration),
        "t_acc_s": float(t_acc),
        "t_cruise_s": float(t_cruise),
        "v_peak_mm_s": float(v_peak),
        "accel_mm_s2": float(accel),
    }


def _required_setup(setup: dict, fields: Iterable[str]) -> None:
    missing = [field for field in fields if setup.get(field) is None]
    if missing:
        raise ValueError("missing setup fields: " + ", ".join(missing))


def _workspace_check(points_mm: np.ndarray, setup: dict) -> None:
    lower = np.asarray(setup["workspace_min_mm"], dtype=float)
    upper = np.asarray(setup["workspace_max_mm"], dtype=float)
    if (lower.shape != (3,) or upper.shape != (3,)
            or not np.isfinite(np.vstack([lower, upper])).all()):
        raise ValueError("workspace bounds must be finite three-vectors")
    if np.any(lower >= upper) or np.any(points_mm < lower) or np.any(points_mm > upper):
        raise ValueError("trajectory or route is outside workspace")


_LADDER_AXES = {
    "+x": (1.0, 0.0), "-x": (-1.0, 0.0),
    "+y": (0.0, 1.0), "-y": (0.0, -1.0),
}


def _ladder_depths(path: dict) -> list[float]:
    """Expand a depth ladder into the visited sequence (down then up)."""
    steps = int(path["steps"])
    low = float(path["depth_from_mm"])
    high = float(path["depth_to_mm"])
    down = [low + (high - low) * index / (steps - 1) for index in range(steps)]
    return down + list(reversed(down))


def _leg_samples(xy0, xy1, z0, z1, speed_mm_s: float, accel_mm_s2: float,
                 dt_s: float):
    """Sample one leg with a symmetric trapezoidal profile.

    Reuses ``time_law`` so every leg is dt-spaced and acceleration-limited,
    exactly like the line and circle experiments. Without the ramps the leg
    boundaries would be instantaneous velocity steps, which shake the arm.
    """
    start_xy = np.asarray(xy0, dtype=float)
    end_xy = np.asarray(xy1, dtype=float)
    span = max(float(np.linalg.norm(end_xy - start_xy)), abs(float(z1) - float(z0)))
    if span <= 0:
        return start_xy[None, :].copy(), np.array([float(z0)]), np.array([0.0])
    law = time_law(span, speed_mm_s, accel_mm_s2, dt_s)
    fraction = law["s"]
    xy = start_xy[None, :] + (end_xy - start_xy)[None, :] * fraction[:, None]
    z = float(z0) + (float(z1) - float(z0)) * fraction
    return xy, z, law["t_s"]


def _compile_ladder(checked: dict, setup: dict, dt_s: float, accel_budget: float) -> dict:
    """Compile a ladder experiment into one timed multi-pass plan."""
    _required_setup(setup, ("approach_speed_mm_s", "return_speed_mm_s"))
    path = checked["path"]
    travel = _positive(path["travel_mm"], "travel_mm")
    transit_z = float(path["transit_z_mm"])
    measure_speed = _positive(checked["motion"]["speed_mm_s"], "speed_mm_s")
    approach_speed = _positive(setup["approach_speed_mm_s"], "approach_speed_mm_s")
    return_speed = _positive(setup["return_speed_mm_s"], "return_speed_mm_s")
    contact_z = float(setup["contact_z_mm"])
    max_depth = _positive(setup["max_depth_mm"], "max_depth_mm")
    max_z_speed = _positive(setup["max_z_speed_mm_s"], "max_z_speed_mm_s")
    max_xy_speed = _positive(setup["max_xy_speed_mm_s"], "max_xy_speed_mm_s")
    # 回程段在 XY 平面运动、接近/抬笔段在 Z 轴运动，都不能越过 installation 声明的速度上限；
    # 上限由 compile_experiment 的 _required_setup 保证存在。编译期直接拒绝而非静默收敛，
    # 防止产出"比声明的上限跑得更快"的轨迹。
    if return_speed > max_xy_speed:
        raise ValueError("return_speed_mm_s exceeds max_xy_speed_mm_s")
    if approach_speed > max_z_speed:
        raise ValueError("approach_speed_mm_s exceeds max_z_speed_mm_s")
    direction = np.asarray(_LADDER_AXES[path["axis"]], dtype=float)
    origin = np.asarray([setup["origin_x_mm"], setup["origin_y_mm"]], dtype=float)
    orientation = np.asarray(setup["vertical_rpy_rad"], dtype=float)
    if orientation.shape != (3,) or not np.isfinite(orientation).all():
        raise ValueError("vertical_rpy_rad must be three finite radians")

    depths = _ladder_depths(path)
    if max(depths) > max_depth + 1e-9:
        raise ValueError("ladder depth exceeds max_depth_mm")
    for depth in depths:
        if contact_z - depth > transit_z + 1e-9:
            raise ValueError("transit_z_mm must be above every ladder depth")

    start_xy = origin.copy()
    end_xy = origin + direction * travel
    xy_parts: list[np.ndarray] = []
    z_parts: list[np.ndarray] = []
    t_parts: list[np.ndarray] = []
    phase_parts: list[np.ndarray] = []
    elapsed = 0.0
    for visit, depth in enumerate(depths):
        work_z = contact_z - depth
        legs = (
            (f"approach_{visit:02d}", start_xy, start_xy, transit_z, work_z, approach_speed),
            (f"measure_{visit:02d}", start_xy, end_xy, work_z, work_z, measure_speed),
            (f"lift_{visit:02d}", end_xy, end_xy, work_z, transit_z, approach_speed),
            (f"transit_{visit:02d}", end_xy, start_xy, transit_z, transit_z, return_speed),
        )
        for name, xy0, xy1, z0, z1, speed in legs:
            leg_xy, leg_z, leg_t = _leg_samples(
                xy0, xy1, z0, z1, speed, accel_budget, dt_s)
            if t_parts:
                leg_xy, leg_z, leg_t = leg_xy[1:], leg_z[1:], leg_t[1:]
            xy_parts.append(leg_xy)
            z_parts.append(leg_z)
            t_parts.append(leg_t + elapsed)
            phase_parts.append(np.full(len(leg_t), name, dtype="U12"))
            elapsed += float(leg_t[-1])

    xy_mm = np.vstack(xy_parts)
    tcp_z_mm = np.concatenate(z_parts)
    t_s = np.concatenate(t_parts)
    phase = np.concatenate(phase_parts)
    depth_mm = np.clip(contact_z - tcp_z_mm, 0.0, max_depth)

    poses = np.column_stack([
        xy_mm / 1000.0,
        tcp_z_mm / 1000.0,
        np.repeat(orientation[None, :], len(t_s), axis=0),
    ])
    _workspace_check(poses[:, :3] * 1000.0, setup)
    steps_mm = np.linalg.norm(np.diff(poses[:, :3], axis=0), axis=1) * 1000.0
    if len(steps_mm) and np.max(steps_mm) > _positive(setup["max_step_mm"], "max_step_mm") + 1e-9:
        raise ValueError("trajectory exceeds max_step_mm")
    z_rates = np.abs(np.diff(tcp_z_mm)) / np.maximum(np.diff(t_s), 1e-12)
    if len(z_rates) and np.max(z_rates) > max_z_speed + 1e-9:
        raise ValueError("trajectory exceeds max_z_speed_mm_s")

    distance = np.linalg.norm(np.diff(xy_mm, axis=0), axis=1)
    travelled = np.concatenate([[0.0], np.cumsum(distance)])
    total = float(travelled[-1])
    s = travelled / total if total > 0 else np.zeros(len(t_s))

    if checked["control"]["enabled"]:
        g_ref = np.full(len(t_s), float(checked["control"]["target_uT"]))
        control_mode = "dBxy_magnitude"
    else:
        g_ref = np.full(len(t_s), np.nan)
        control_mode = "off"
    depth_m = depth_mm / 1000.0
    stroke = Stroke(s=s.copy(), xy=poses[:, :2].copy(),
                    g_press=g_ref.copy(), z_ff=depth_m.copy())
    plan = StrokePlan(
        strokes=[stroke],
        meta={
            "control_mode": control_mode,
            "stroke_durations_s": [float(t_s[-1])],
            "time_law": "ladder_constant_depth_passes",
        },
    )
    return {
        "plan": plan,
        "t_s": t_s,
        "s": s,
        "phase": phase,
        "pose_m_rad": poses,
        "g_ref_uT": g_ref,
        "depth_ff_m": depth_m,
        "spec_snapshot": copy.deepcopy(checked),
        "setup_snapshot": copy.deepcopy(setup),
    }


def compile_experiment(spec: dict, setup: dict, dt_s: float = 0.02) -> dict:
    """Compile one validated JSON experiment into one timed StrokePlan."""
    checked = validate_experiment(spec, executable=True)
    _required_setup(
        setup,
        ("origin_x_mm", "origin_y_mm", "contact_z_mm", "vertical_rpy_rad",
         "workspace_min_mm", "workspace_max_mm", "max_depth_mm",
         "max_xy_speed_mm_s", "max_z_speed_mm_s", "max_accel_mm_s2",
         "max_step_mm"),
    )
    speed = _positive(checked["motion"]["speed_mm_s"], "speed_mm_s")
    max_xy_speed = _positive(setup["max_xy_speed_mm_s"], "max_xy_speed_mm_s")
    if speed > max_xy_speed:
        raise ValueError("speed_mm_s exceeds max_xy_speed_mm_s")
    max_accel = _positive(setup["max_accel_mm_s2"], "max_accel_mm_s2")
    requested_accel = checked["motion"]["accel_mm_s2"]
    accel_budget = max_accel if requested_accel is None else _positive(requested_accel, "accel_mm_s2")
    if accel_budget > max_accel:
        raise ValueError("accel_mm_s2 exceeds max_accel_mm_s2")

    path = checked["path"]
    if path["kind"] == "ladder":
        return _compile_ladder(checked, setup, dt_s, accel_budget)
    if path["kind"] == "line":
        delta = np.asarray(path["delta_xy_mm"], dtype=float)
        length = float(np.linalg.norm(delta))
        tangential_accel = accel_budget
    else:
        radius = float(path["radius_mm"])
        length = 2.0 * math.pi * radius
        centripetal = speed * speed / radius
        if centripetal >= accel_budget:
            raise ValueError("requested circle speed exceeds centripetal acceleration budget")
        tangential_accel = math.sqrt(accel_budget * accel_budget - centripetal * centripetal)

    law = time_law(length, speed, tangential_accel, dt_s)
    s = law["s"]
    if path["kind"] == "line":
        local_xy_mm = s[:, None] * delta[None, :]
    else:
        theta = 2.0 * math.pi * s
        sign = -1.0 if path["clockwise"] else 1.0
        local_xy_mm = np.column_stack([
            radius - radius * np.cos(theta),
            sign * radius * np.sin(theta),
        ])
        local_xy_mm[-1] = 0.0

    start_z = float(checked["z"]["start_tcp_z_mm"])
    end_z = float(checked["z"]["end_tcp_z_mm"])
    tcp_z_mm = (1.0 - s) * start_z + s * end_z
    contact_z = float(setup["contact_z_mm"])
    depth_mm = contact_z - tcp_z_mm
    max_depth = _positive(setup["max_depth_mm"], "max_depth_mm")
    if np.any(depth_mm < -1e-9) or np.any(depth_mm > max_depth + 1e-9):
        raise ValueError("TCP Z implies depth outside max_depth_mm")
    depth_mm = np.clip(depth_mm, 0.0, max_depth)
    z_speed = abs(end_z - start_z) / length * law["v_peak_mm_s"]
    if z_speed > _positive(setup["max_z_speed_mm_s"], "max_z_speed_mm_s") + 1e-12:
        raise ValueError("trajectory exceeds max_z_speed_mm_s")

    origin = np.asarray([setup["origin_x_mm"], setup["origin_y_mm"]], dtype=float)
    xy_mm = local_xy_mm + origin
    orientation = np.asarray(setup["vertical_rpy_rad"], dtype=float)
    if orientation.shape != (3,) or not np.isfinite(orientation).all():
        raise ValueError("vertical_rpy_rad must be three finite radians")
    poses = np.column_stack([
        xy_mm / 1000.0,
        tcp_z_mm / 1000.0,
        np.repeat(orientation[None, :], len(s), axis=0),
    ])
    _workspace_check(poses[:, :3] * 1000.0, setup)
    steps_mm = np.linalg.norm(np.diff(poses[:, :3], axis=0), axis=1) * 1000.0
    if len(steps_mm) and np.max(steps_mm) > _positive(setup["max_step_mm"], "max_step_mm") + 1e-9:
        raise ValueError("trajectory exceeds max_step_mm")

    if checked["control"]["enabled"]:
        g_ref = np.full(len(s), float(checked["control"]["target_uT"]))
        control_mode = "dBxy_magnitude"
    else:
        g_ref = np.full(len(s), np.nan)
        control_mode = "off"
    depth_m = depth_mm / 1000.0
    stroke = Stroke(s=s.copy(), xy=poses[:, :2].copy(),
                    g_press=g_ref.copy(), z_ff=depth_m.copy())
    plan = StrokePlan(
        strokes=[stroke],
        meta={
            "control_mode": control_mode,
            "stroke_durations_s": [float(law["duration_s"])],
            "time_law": "symmetric_trapezoid_or_triangle",
        },
    )
    return {
        "plan": plan,
        "t_s": law["t_s"].copy(),
        "s": s.copy(),
        "phase": law["phase"].copy(),
        "pose_m_rad": poses,
        "g_ref_uT": g_ref,
        "depth_ff_m": depth_m,
        "spec_snapshot": copy.deepcopy(checked),
        "setup_snapshot": copy.deepcopy(setup),
    }
