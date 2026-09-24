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
    """Expand a depth ladder into its configured one-way or round-trip visits."""
    steps = int(path["steps"])
    low = float(path["depth_from_mm"])
    high = float(path["depth_to_mm"])
    down = [low + (high - low) * index / (steps - 1) for index in range(steps)]
    if path["order"] == "one_way":
        return down
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


def _hold_samples(xy, z, duration_s: float, dt_s: float):
    """Sample a stationary dwell without introducing a zero-duration motion leg."""
    duration = float(duration_s)
    if duration <= 0:
        return np.asarray(xy, dtype=float)[None, :], np.array([float(z)]), np.array([0.0])
    t = np.arange(0.0, duration, float(dt_s), dtype=float)
    if len(t) == 0 or not math.isclose(float(t[-1]), duration, abs_tol=1e-12):
        t = np.append(t, duration)
    points = np.repeat(np.asarray(xy, dtype=float)[None, :], len(t), axis=0)
    return points, np.full(len(t), float(z)), t


def _compile_ladder(checked: dict, setup: dict, dt_s: float, accel_budget: float) -> dict:
    """Compile a ladder experiment into one timed multi-pass plan."""
    _required_setup(setup, ("approach_speed_mm_s", "return_speed_mm_s"))
    path = checked["path"]
    travel = _positive(path["travel_mm"], "travel_mm")
    transit_z = float(path["transit_z_mm"])
    pause_z = float(path.get("pause_z_mm", transit_z))
    wetting = path.get("wetting")
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
    if pause_z < transit_z - 1e-9:
        raise ValueError("pause_z_mm must be at or above transit_z_mm")

    wet_visits = []
    if wetting is not None:
        wet_safe_z = float(wetting["safe_z_mm"])
        wet_dip_z = float(wetting["dip_z_mm"])
        if wet_safe_z < transit_z - 1e-9:
            raise ValueError("wetting.safe_z_mm must be at or above transit_z_mm")
        wet_visits = list(range(0, len(depths), int(wetting["every_paths"])))
        wet_xy = np.asarray([wetting["x_mm"], wetting["y_mm"]], dtype=float)
        wet_dwell_s = float(wetting["dwell_s"])
        wet_settle_s = float(wetting["settle_s"])

    pause_every = path.get("pause_every_passes")
    pause_next_visits = (
        list(range(int(pause_every), len(depths), int(pause_every)))
        if pause_every is not None else [])
    pause_completed_visits = {next_visit - 1 for next_visit in pause_next_visits}

    start_xy = origin.copy()
    end_xy = origin + direction * travel
    xy_parts: list[np.ndarray] = []
    z_parts: list[np.ndarray] = []
    t_parts: list[np.ndarray] = []
    phase_parts: list[np.ndarray] = []
    elapsed = 0.0
    for visit, depth in enumerate(depths):
        work_z = contact_z - depth
        legs = []
        if visit in wet_visits:
            wet_start_z = wet_safe_z if visit == 0 else transit_z
            legs.extend([
                (f"wet_rise_{visit:02d}", start_xy, start_xy,
                 wet_start_z, wet_safe_z, approach_speed, None),
                (f"wet_transfer_out_{visit:02d}", start_xy, wet_xy,
                 wet_safe_z, wet_safe_z, return_speed, None),
                (f"wet_dip_{visit:02d}", wet_xy, wet_xy,
                 wet_safe_z, wet_dip_z, approach_speed, None),
                (f"wet_dwell_{visit:02d}", wet_xy, wet_xy,
                 wet_dip_z, wet_dip_z, 0.0, wet_dwell_s),
                (f"wet_lift_{visit:02d}", wet_xy, wet_xy,
                 wet_dip_z, wet_safe_z, approach_speed, None),
                (f"wet_transfer_back_{visit:02d}", wet_xy, start_xy,
                 wet_safe_z, wet_safe_z, return_speed, None),
                (f"wet_settle_{visit:02d}", start_xy, start_xy,
                 wet_safe_z, wet_safe_z, 0.0, wet_settle_s),
                (f"wet_lower_{visit:02d}", start_xy, start_xy,
                 wet_safe_z, transit_z, approach_speed, None),
            ])
        legs.extend([
            (f"approach_{visit:02d}", start_xy, start_xy,
             transit_z, work_z, approach_speed, None),
            (f"measure_{visit:02d}", start_xy, end_xy,
             work_z, work_z, measure_speed, None),
            (f"lift_{visit:02d}", end_xy, end_xy,
             work_z, transit_z, approach_speed, None),
            (f"transit_{visit:02d}", end_xy, start_xy,
             transit_z, transit_z, return_speed, None),
        ])
        if visit in pause_completed_visits and pause_z > transit_z:
            legs.extend([
                (f"pause_lift_{visit:02d}", start_xy, start_xy,
                 transit_z, pause_z, approach_speed, None),
                (f"pause_lower_{visit:02d}", start_xy, start_xy,
                 pause_z, transit_z, approach_speed, None),
            ])
        for name, xy0, xy1, z0, z1, speed, hold_s in legs:
            if hold_s is not None and hold_s <= 0:
                continue
            if hold_s is None:
                leg_xy, leg_z, leg_t = _leg_samples(
                    xy0, xy1, z0, z1, speed, accel_budget, dt_s)
            else:
                leg_xy, leg_z, leg_t = _hold_samples(xy0, z0, hold_s, dt_s)
            if t_parts:
                leg_xy, leg_z, leg_t = leg_xy[1:], leg_z[1:], leg_t[1:]
            xy_parts.append(leg_xy)
            z_parts.append(leg_z)
            t_parts.append(leg_t + elapsed)
            phase_parts.append(np.full(len(leg_t), name, dtype="U32"))
            elapsed += float(leg_t[-1])

    xy_mm = np.vstack(xy_parts)
    tcp_z_mm = np.concatenate(z_parts)
    t_s = np.concatenate(t_parts)
    phase = np.concatenate(phase_parts)
    pause_after_indices: list[int] = []
    for next_visit in pause_next_visits:
        completed_visit = next_visit - 1
        pause_phase = (f"pause_lift_{completed_visit:02d}"
                       if pause_z > transit_z else f"transit_{completed_visit:02d}")
        matches = np.flatnonzero(phase == pause_phase)
        if len(matches):
            pause_after_indices.append(int(matches[-1]))
    automatic_rebaseline_after_indices: list[int] = []
    for visit in wet_visits:
        marker_phase = (f"wet_settle_{visit:02d}" if wet_settle_s > 0
                        else f"wet_transfer_back_{visit:02d}")
        matches = np.flatnonzero(phase == marker_phase)
        if len(matches):
            automatic_rebaseline_after_indices.append(int(matches[-1]))
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
        "pause_after_indices": pause_after_indices,
        "pause_next_visits": pause_next_visits,
        "automatic_rebaseline_after_indices": automatic_rebaseline_after_indices,
        "automatic_rebaseline_next_visits": wet_visits,
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
