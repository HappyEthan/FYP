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
