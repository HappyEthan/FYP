"""版本化实验 JSON 与安装配置的纯校验。"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any


_INSTALLATION_FIELDS = (
    "installation_id", "verified", "tcp_name", "ucs_name", "tool_coord_si",
    "user_coord_si", "vertical_rpy_rad", "sensor_mount_id", "origin_x_mm",
    "origin_y_mm", "wait_z_mm", "contact_z_mm", "workspace_min_mm",
    "workspace_max_mm", "max_depth_mm", "max_xy_speed_mm_s",
    "max_z_speed_mm_s", "max_accel_mm_s2", "max_step_mm",
    "approach_speed_mm_s", "return_speed_mm_s", "pose_tolerance_mm",
    "orientation_tolerance_rad", "baseline_window_s", "baseline_timeout_s",
    "baseline_min_samples", "baseline_max_std_uT", "baseline_max_drift_uT_s",
    "sensor_max_age_s", "max_tick_lateness_s", "stop_timeout_s",
    "gripper_width_mm", "gripper_speed", "gripper_force", "filter",
)


def _finite_number(value: Any, field: str, errors: list[str], *, positive=False,
                   nonnegative=False) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(f"{field} must be a finite number")
        return None
    number = float(value)
    if not math.isfinite(number):
        errors.append(f"{field} must be finite")
    elif positive and number <= 0:
        errors.append(f"{field} must be > 0")
    elif nonnegative and number < 0:
        errors.append(f"{field} must be >= 0")
    return number


def _number_vector(value: Any, size: int, field: str, errors: list[str]) -> None:
    if not isinstance(value, (list, tuple)) or len(value) != size:
        errors.append(f"{field} must contain {size} finite numbers")
        return
    for index, item in enumerate(value):
        _finite_number(item, f"{field}[{index}]", errors)


def _mapping(value: Any, field: str, errors: list[str]) -> dict:
    if not isinstance(value, dict):
        errors.append(f"{field} must be an object")
        return {}
    return value


def _require_keys(data: dict, fields: tuple[str, ...], prefix: str,
                  errors: list[str]) -> None:
    for field in fields:
        if field not in data:
            errors.append(f"missing {prefix}{field}")


def _reject_unknown(data: dict, allowed: set[str], prefix: str,
                    errors: list[str]) -> None:
    for field in sorted(set(data) - allowed):
        errors.append(f"unknown field {prefix}{field}")


def validate_experiment(data: dict, *, executable: bool = False) -> dict:
    """Validate a version-1 experiment without resolving installation values.

    Closed-loop ``null`` values remain valid for preview.  Passing
    ``executable=True`` requires all measured control values to be populated.
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        raise ValueError("experiment must be a JSON object")
    path = _mapping(data.get("path"), "path", errors)
    is_ladder = path.get("kind") == "ladder"
    required = ["version", "name", "path", "motion", "control"]
    allowed = {
        "version", "name", "_comment", "run_label", "path", "motion", "control",
    }
    if not is_ladder:
        required.append("z")
        allowed.add("z")
    _require_keys(data, tuple(required), "", errors)
    _reject_unknown(data, allowed, "", errors)

    if data.get("version") != 1:
        errors.append("version must be 1")
    if not isinstance(data.get("name"), str) or not data.get("name", "").strip():
        errors.append("name must be a non-empty string")
    if "_comment" in data and not isinstance(data["_comment"], str):
        errors.append("_comment must be a string")
    if ("run_label" in data
            and (not isinstance(data["run_label"], str)
                 or not data["run_label"].strip())):
        errors.append("run_label must be a non-empty string")

    kind = path.get("kind")
    if kind == "line":
        _require_keys(path, ("kind", "delta_xy_mm"), "path.", errors)
        _reject_unknown(path, {"kind", "delta_xy_mm"}, "path.", errors)
        _number_vector(path.get("delta_xy_mm"), 2, "delta_xy_mm", errors)
        if isinstance(path.get("delta_xy_mm"), (list, tuple)) and len(path["delta_xy_mm"]) == 2:
            try:
                if math.hypot(float(path["delta_xy_mm"][0]), float(path["delta_xy_mm"][1])) <= 0:
                    errors.append("delta_xy_mm must have positive length")
            except (TypeError, ValueError):
                pass
    elif kind == "circle":
        _require_keys(path, ("kind", "radius_mm", "clockwise"), "path.", errors)
        _reject_unknown(path, {"kind", "radius_mm", "clockwise"}, "path.", errors)
        _finite_number(path.get("radius_mm"), "radius_mm", errors, positive=True)
        if not isinstance(path.get("clockwise"), bool):
            errors.append("clockwise must be boolean")
    elif kind == "ladder":
        required_fields = ("kind", "axis", "travel_mm", "depth_from_mm",
                           "depth_to_mm", "steps", "order", "transit_z_mm")
        allowed_fields = {
            *required_fields, "pause_every_passes", "pause_z_mm", "wetting",
        }
        _require_keys(path, required_fields, "path.", errors)
        _reject_unknown(path, allowed_fields, "path.", errors)
        axis = path.get("axis")
        if not isinstance(axis, str) or axis not in {"+x", "-x", "+y", "-y"}:
            errors.append("path.axis must be one of +x, -x, +y, -y")
        _finite_number(path.get("travel_mm"), "travel_mm", errors, positive=True)
        _finite_number(path.get("depth_from_mm"), "depth_from_mm", errors, nonnegative=True)
        _finite_number(path.get("depth_to_mm"), "depth_to_mm", errors, nonnegative=True)
        _finite_number(path.get("transit_z_mm"), "transit_z_mm", errors, positive=True)
        if path.get("pause_z_mm") is not None:
            _finite_number(path.get("pause_z_mm"), "pause_z_mm", errors, positive=True)
        steps = path.get("steps")
        if isinstance(steps, bool) or not isinstance(steps, int) or steps < 2:
            errors.append("path.steps must be an integer >= 2")
        pause_every = path.get("pause_every_passes")
        if (pause_every is not None
                and (isinstance(pause_every, bool)
                     or not isinstance(pause_every, int)
                     or pause_every < 1)):
            errors.append("path.pause_every_passes must be a positive integer")
        if path.get("pause_z_mm") is not None and pause_every is None:
            errors.append("path.pause_z_mm requires pause_every_passes")
        if path.get("wetting") is not None:
            wetting = _mapping(path.get("wetting"), "path.wetting", errors)
            wetting_fields = {
                "every_paths", "x_mm", "y_mm", "cup_rim_z_mm",
                "safe_z_mm", "dip_z_mm", "dwell_s", "settle_s",
            }
            _require_keys(wetting, tuple(sorted(wetting_fields)), "path.wetting.", errors)
            _reject_unknown(wetting, wetting_fields, "path.wetting.", errors)
            wet_every = wetting.get("every_paths")
            if (isinstance(wet_every, bool) or not isinstance(wet_every, int)
                    or wet_every < 1):
                errors.append("path.wetting.every_paths must be a positive integer")
            for field in (
                    "x_mm", "y_mm", "cup_rim_z_mm", "safe_z_mm", "dip_z_mm"):
                _finite_number(wetting.get(field), f"path.wetting.{field}", errors)
            for field in ("dwell_s", "settle_s"):
                _finite_number(
                    wetting.get(field), f"path.wetting.{field}", errors,
                    nonnegative=True)
            safe_z = wetting.get("safe_z_mm")
            dip_z = wetting.get("dip_z_mm")
            if (isinstance(safe_z, (int, float)) and not isinstance(safe_z, bool)
                    and isinstance(dip_z, (int, float)) and not isinstance(dip_z, bool)
                    and math.isfinite(float(safe_z)) and math.isfinite(float(dip_z))
                    and float(safe_z) <= float(dip_z)):
                errors.append(
                    "path.wetting.safe_z_mm must be above path.wetting.dip_z_mm")
            cup_rim_z = wetting.get("cup_rim_z_mm")
            if (isinstance(safe_z, (int, float)) and not isinstance(safe_z, bool)
                    and isinstance(cup_rim_z, (int, float))
                    and not isinstance(cup_rim_z, bool)
                    and math.isfinite(float(safe_z))
                    and math.isfinite(float(cup_rim_z))
                    and float(safe_z) <= float(cup_rim_z)):
                errors.append(
                    "path.wetting.safe_z_mm must be above "
                    "path.wetting.cup_rim_z_mm")
            if (isinstance(dip_z, (int, float)) and not isinstance(dip_z, bool)
                    and isinstance(cup_rim_z, (int, float))
                    and not isinstance(cup_rim_z, bool)
                    and math.isfinite(float(dip_z))
                    and math.isfinite(float(cup_rim_z))
                    and float(dip_z) >= float(cup_rim_z)):
                errors.append(
                    "path.wetting.dip_z_mm must be below "
                    "path.wetting.cup_rim_z_mm")
            if pause_every is not None or path.get("pause_z_mm") is not None:
                errors.append(
                    "path.wetting cannot be combined with manual pause fields")
        if path.get("order") not in {"down_then_up", "one_way"}:
            errors.append("path.order must be down_then_up or one_way")
        pair = (path.get("depth_from_mm"), path.get("depth_to_mm"))
        if all(isinstance(value, (int, float)) and not isinstance(value, bool)
               for value in pair) and float(pair[0]) >= float(pair[1]):
            errors.append("depth_from_mm must be below depth_to_mm")
    else:
        errors.append("path.kind must be line, circle or ladder")

    motion = _mapping(data.get("motion"), "motion", errors)
    _require_keys(motion, ("speed_mm_s", "accel_mm_s2"), "motion.", errors)
    _reject_unknown(motion, {"speed_mm_s", "accel_mm_s2"}, "motion.", errors)
    _finite_number(motion.get("speed_mm_s"), "speed_mm_s", errors, positive=True)
    if motion.get("accel_mm_s2") is not None:
        _finite_number(motion.get("accel_mm_s2"), "accel_mm_s2", errors, positive=True)

    if not is_ladder:
        z = _mapping(data.get("z"), "z", errors)
        _require_keys(z, ("start_tcp_z_mm", "end_tcp_z_mm"), "z.", errors)
        _reject_unknown(z, {"start_tcp_z_mm", "end_tcp_z_mm"}, "z.", errors)
        _finite_number(z.get("start_tcp_z_mm"), "start_tcp_z_mm", errors)
        _finite_number(z.get("end_tcp_z_mm"), "end_tcp_z_mm", errors)

    control = _mapping(data.get("control"), "control", errors)
    if not isinstance(control.get("enabled"), bool):
        errors.append("control.enabled must be boolean")
    elif control["enabled"]:
        fields = ("target_uT", "deadband_uT", "kp", "ki", "calibration_file")
        _require_keys(control, fields, "control.", errors)
        _reject_unknown(control, {"enabled", *fields}, "control.", errors)
        for field in ("target_uT", "kp", "ki"):
            value = control.get(field)
            if value is None:
                if executable:
                    errors.append(f"{field} is required for execution")
            else:
                _finite_number(value, field, errors, nonnegative=True)
        _finite_number(control.get("deadband_uT"), "deadband_uT", errors, nonnegative=True)
        calibration = control.get("calibration_file")
        if calibration is None:
            if executable:
                errors.append("calibration_file is required for execution")
        elif not isinstance(calibration, str) or not calibration.strip():
            errors.append("calibration_file must be a non-empty string or null")
    else:
        _reject_unknown(control, {"enabled"}, "control.", errors)

    if errors:
        raise ValueError("invalid experiment: " + "; ".join(errors))
    return copy.deepcopy(data)


def load_experiment(path: str | Path) -> dict:
    """Load strict standard JSON and validate it for preview only."""
    def reject_constant(token: str):
        raise ValueError(f"non-standard JSON constant {token}")

    try:
        raw = Path(path).read_text(encoding="utf-8")
        data = json.loads(raw, parse_constant=reject_constant)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load experiment JSON: {exc}") from exc
    return validate_experiment(data)


def validate_installation(data: dict, *, hardware: bool) -> dict:
    """Validate installation data, never supplying candidate safety values."""
    errors: list[str] = []
    if not isinstance(data, dict):
        raise ValueError("installation must be a JSON object")
    _reject_unknown(data, set(_INSTALLATION_FIELDS), "", errors)
    if hardware:
        for field in _INSTALLATION_FIELDS:
            if field not in data or data[field] is None:
                errors.append(f"missing hardware field {field}")
        if data.get("verified") is not True:
            errors.append("verified must be true for hardware")
    elif "verified" in data and not isinstance(data["verified"], bool):
        errors.append("verified must be boolean")

    for field in ("installation_id", "tcp_name", "ucs_name", "sensor_mount_id"):
        if field in data and data[field] is not None and (
                not isinstance(data[field], str) or not data[field].strip()):
            errors.append(f"{field} must be a non-empty string")
    for field in ("tool_coord_si", "user_coord_si"):
        if field in data and data[field] is not None:
            _number_vector(data[field], 6, field, errors)
    for field in ("vertical_rpy_rad", "workspace_min_mm", "workspace_max_mm",
                  "baseline_max_std_uT"):
        if field in data and data[field] is not None:
            _number_vector(data[field], 3, field, errors)

    positive = (
        "max_depth_mm", "max_xy_speed_mm_s", "max_z_speed_mm_s",
        "max_accel_mm_s2", "max_step_mm", "approach_speed_mm_s",
        "return_speed_mm_s", "pose_tolerance_mm", "orientation_tolerance_rad",
        "baseline_window_s", "baseline_timeout_s", "baseline_min_samples",
        "baseline_max_drift_uT_s", "sensor_max_age_s", "max_tick_lateness_s",
        "stop_timeout_s", "gripper_width_mm", "gripper_speed", "gripper_force",
    )
    for field in positive:
        if field in data and data[field] is not None:
            _finite_number(data[field], field, errors, positive=True)
    for field in ("origin_x_mm", "origin_y_mm", "wait_z_mm", "contact_z_mm"):
        if field in data and data[field] is not None:
            _finite_number(data[field], field, errors)
    if all(field in data and data[field] is not None
           for field in ("workspace_min_mm", "workspace_max_mm")):
        if any(float(lo) >= float(hi) for lo, hi in zip(
                data["workspace_min_mm"], data["workspace_max_mm"])):
            errors.append("workspace_min_mm must be below workspace_max_mm")
    if "filter" in data and data["filter"] is not None:
        filt = _mapping(data["filter"], "filter", errors)
        if not isinstance(filt.get("kind"), str) or not filt.get("kind", "").strip():
            errors.append("filter.kind must be a non-empty string")

    if errors:
        raise ValueError("invalid installation: " + "; ".join(errors))
    return copy.deepcopy(data)
