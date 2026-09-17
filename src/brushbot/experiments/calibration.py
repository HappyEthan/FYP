"""Validation and offline summaries for measured 2-D magnetic calibration."""

from __future__ import annotations

import copy
import csv
import json
import math
from pathlib import Path

import numpy as np


_FIELDS = {
    "version", "feature", "source", "installation_id", "sensor_mount_id",
    "filter", "speed_range_mm_s", "directions", "depth_mm",
    "amplitude_uT", "approved",
}


def validate_calibration(table: dict, context: dict) -> dict:
    """Accept only an approved, strictly monotonic measured branch in context."""
    if not isinstance(table, dict) or not isinstance(context, dict):
        raise ValueError("calibration table and context must be objects")
    missing = sorted(_FIELDS - set(table))
    unknown = sorted(set(table) - _FIELDS)
    errors = [f"missing {field}" for field in missing]
    errors.extend(f"unknown field {field}" for field in unknown)
    if table.get("version") != 1:
        errors.append("version must be 1")
    if table.get("feature") != "dBxy_norm_uT":
        errors.append("feature must be dBxy_norm_uT")
    if table.get("source") != "measured":
        errors.append("source must be measured")
    if table.get("approved") is not True:
        errors.append("approved must be true")

    for field in ("installation_id", "sensor_mount_id"):
        if table.get(field) != context.get(field):
            errors.append(f"{field} does not match execution context")
    if table.get("filter") != context.get("filter"):
        errors.append("filter does not match execution context")

    try:
        speeds = np.asarray(table["speed_range_mm_s"], dtype=float)
        if (speeds.shape != (2,) or not np.isfinite(speeds).all()
                or speeds[0] <= 0 or speeds[0] > speeds[1]):
            errors.append("speed_range_mm_s must be a positive ordered pair")
        else:
            speed = float(context["speed_mm_s"])
            if not math.isfinite(speed) or not speeds[0] <= speed <= speeds[1]:
                errors.append("speed_mm_s is outside calibration speed range")
    except (KeyError, TypeError, ValueError):
        errors.append("speed_range_mm_s or context speed is invalid")

    directions = table.get("directions")
    if (not isinstance(directions, list) or not directions
            or not all(isinstance(item, str) and item for item in directions)):
        errors.append("directions must be a non-empty string list")
    elif context.get("direction") not in directions:
        errors.append("direction is outside calibration applicability")

    try:
        depth = np.asarray(table["depth_mm"], dtype=float)
        amplitude = np.asarray(table["amplitude_uT"], dtype=float)
        if (depth.ndim != 1 or amplitude.ndim != 1 or len(depth) != len(amplitude)
                or len(depth) < 2 or not np.isfinite(depth).all()
                or np.any(depth < 0) or np.any(np.diff(depth) <= 0)):
            errors.append("depth_mm must be finite and strictly increasing")
        if (amplitude.ndim != 1 or not np.isfinite(amplitude).all()
                or np.any(amplitude < 0) or np.any(np.diff(amplitude) <= 0)):
            errors.append("amplitude_uT must be finite and strictly increasing")
        target = float(context["target_uT"])
        if (not math.isfinite(target) or amplitude.ndim != 1 or len(amplitude) == 0
                or target < amplitude[0] or target > amplitude[-1]):
            errors.append("target_uT is outside calibration range")
    except (KeyError, TypeError, ValueError, IndexError):
        errors.append("depth_mm/amplitude_uT/target_uT are invalid")

    if errors:
        raise ValueError("invalid calibration: " + "; ".join(dict.fromkeys(errors)))
    return copy.deepcopy(table)


def summarize_scan(run_dir: str) -> dict:
    """Join cruise control rows to valid magnetic samples by sample sequence."""
    folder = Path(run_dir)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    sensors = {}
    with (folder / "sensor.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("valid", "")).lower() not in {"1", "true"}:
                continue
            try:
                seq = int(row["seq"])
                dx, dy = float(row["dBx_uT"]), float(row["dBy_uT"])
            except (KeyError, TypeError, ValueError):
                continue
            if math.isfinite(dx) and math.isfinite(dy):
                sensors[seq] = float(math.hypot(dx, dy))

    setup_path = folder / "setup.json"
    setup = json.loads(setup_path.read_text(encoding="utf-8")) if setup_path.exists() else {}
    pairs = []
    all_actual = True
    with (folder / "control.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("phase") != "cruise" or row.get("sample_seq") not in sensors:
                continue
            seq = int(row["sample_seq"])
            actual = row.get("actual_pose_m_rad")
            if row.get("actual_pose_available") and actual is not None and setup.get("contact_z_mm") is not None:
                depth_mm = float(setup["contact_z_mm"]) - float(actual[2]) * 1000.0
            else:
                all_actual = False
                depth_mm = 1000.0 * (float(row.get("depth_ff_m", 0.0))
                                     + float(row.get("depth_fb_m", 0.0)))
            pairs.append({
                "sample_seq": seq,
                "depth_mm": float(depth_mm),
                "amplitude_uT": sensors[seq],
                "phase": "cruise",
            })
    return {
        "run_id": manifest.get("run_id", folder.name),
        "feature": "dBxy_norm_uT",
        "source": "measured",
        "position_basis": "actual_pose" if pairs and all_actual else "command_based",
        "approved": False,
        "pairs": pairs,
    }
