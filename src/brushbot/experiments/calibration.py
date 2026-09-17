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


def _read_sensor_amplitudes(folder: Path) -> dict:
    """Map each valid sample seq to hypot(dBx, dBy)."""
    amplitudes = {}
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
                amplitudes[seq] = float(math.hypot(dx, dy))
    return amplitudes


def summarize_scan(run_dir: str) -> dict:
    """Join cruise control rows to valid magnetic samples by sample sequence."""
    folder = Path(run_dir)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    sensors = _read_sensor_amplitudes(folder)

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


def _read_measure_rows(folder: Path, amplitudes: dict, contact_z_mm):
    samples = []
    all_actual = True
    with (folder / "control.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            phase = str(row.get("phase", ""))
            if not phase.startswith("measure_"):
                continue
            try:
                visit = int(phase.split("_", 1)[1])
                seq = int(row["sample_seq"])
            except (IndexError, KeyError, TypeError, ValueError):
                continue
            if seq not in amplitudes:
                continue
            commanded = 1000.0 * float(row.get("depth_ff_m", 0.0))
            actual = row.get("actual_pose_m_rad")
            if (row.get("actual_pose_available") and actual is not None
                    and contact_z_mm is not None):
                measured = float(contact_z_mm) - float(actual[2]) * 1000.0
            else:
                all_actual = False
                measured = commanded
            samples.append({
                "visit": visit, "depth_cmd_mm": commanded,
                "depth_meas_mm": float(measured),
                "amplitude_uT": amplitudes[seq],
                "host_ns": int(row.get("host_ns", 0)),
            })
    return samples, all_actual


def summarize_ladder(run_dir: str) -> dict:
    """Join ladder measure legs to valid magnetic samples and group them by rung."""
    folder = Path(run_dir)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    setup_path = folder / "setup.json"
    setup = json.loads(setup_path.read_text(encoding="utf-8")) if setup_path.exists() else {}
    contact_z_mm = setup.get("contact_z_mm")
    amplitudes = _read_sensor_amplitudes(folder)
    samples, all_actual = _read_measure_rows(folder, amplitudes, contact_z_mm)

    by_visit: dict[int, list] = {}
    for sample in samples:
        by_visit.setdefault(sample["visit"], []).append(sample)
    visits = sorted(by_visit)
    # 档数由最大档号推出，而不是由"实际出现的档数"推出。若某一趟一个有效样本都没有，
    # len(visits)//2 会让降程/升程的分界左移，把不同深度的档配到一起并静默少报档数；
    # 用最大档号则缺失的档会得到空 rung（幅值 NaN、monotonic 判 False），坏数据自己暴露。
    half = (max(visits) + 1) // 2 if visits else 0

    def _reduce(visit_list, field, reducer):
        values = [s[field] for visit in visit_list if visit in by_visit
                  for s in by_visit[visit]]
        return float(reducer(values)) if values else float("nan")

    rungs = []
    # 按档号配对而非 zip：升程的档序与降程相反，第 index 档的升程是第 (2*half-1-index) 趟。
    # 用 zip 会在任一趟缺失时静默截断，把档位错配。
    for index in range(half):
        down_visit = index
        up_visit = 2 * half - 1 - index
        pool = [visit for visit in (down_visit, up_visit) if visit in by_visit]
        down_amp = _reduce([down_visit], "amplitude_uT", np.mean)
        up_amp = _reduce([up_visit], "amplitude_uT", np.mean)
        rungs.append({
            "index": index,
            "depth_cmd_mm": _reduce(pool, "depth_cmd_mm", np.median),
            "depth_actual_median_mm": (
                _reduce(pool, "depth_meas_mm", np.median) if all_actual else None),
            "amplitude_down_uT": down_amp,
            "amplitude_up_uT": up_amp,
            "amplitude_uT": float(np.mean([down_amp, up_amp])),
            "n": sum(len(by_visit[visit]) for visit in pool),
            "hysteresis_uT": float(up_amp - down_amp),
        })

    if samples:
        first, last = samples[0], samples[-1]
        span_s = (last["host_ns"] - first["host_ns"]) / 1e9
        total = last["amplitude_uT"] - first["amplitude_uT"]
        per_minute = (total / span_s * 60.0) if span_s > 0 else 0.0
    else:
        total, per_minute = 0.0, 0.0

    amplitudes_in_order = [rung["amplitude_uT"] for rung in rungs]
    monotonic = all(
        later > earlier
        for earlier, later in zip(amplitudes_in_order, amplitudes_in_order[1:])
    )
    notes = []
    if not monotonic:
        notes.append("monotonic: rung amplitudes are not strictly increasing")
    origin_ok = None
    if rungs:
        origin_ok = abs(rungs[0]["amplitude_uT"]) < 100.0
        if not origin_ok:
            notes.append("origin: depth-0 amplitude is far above the static floor")

    return {
        "run_id": manifest.get("run_id", folder.name),
        "feature": "dBxy_norm_uT",
        "source": "measured",
        "position_basis": "actual_pose" if samples and all_actual else "command_based",
        "approved": False,
        "steps": len(rungs),
        "rungs": rungs,
        "drift": {"total_uT": float(total), "per_minute_uT": float(per_minute)},
        "quality": {"monotonic": monotonic, "origin_ok": origin_ok, "notes": notes},
    }
