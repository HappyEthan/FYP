import csv
import json

import pytest

from brushbot.experiments.calibration import summarize_scan, validate_calibration


def _table():
    return {
        "version": 1,
        "feature": "dBxy_norm_uT",
        "source": "measured",
        "installation_id": "fixture-a",
        "sensor_mount_id": "mount-a",
        "filter": {"kind": "ema", "alpha": 0.3},
        "speed_range_mm_s": [4.0, 6.0],
        "directions": ["x_positive"],
        "depth_mm": [0.0, 1.0, 2.0],
        "amplitude_uT": [0.0, 50.0, 110.0],
        "approved": True,
    }


def _context():
    return {
        "installation_id": "fixture-a",
        "sensor_mount_id": "mount-a",
        "filter": {"kind": "ema", "alpha": 0.3},
        "speed_mm_s": 5.0,
        "direction": "x_positive",
        "target_uT": 80.0,
    }


def test_measured_monotonic_approved_table_is_accepted():
    assert validate_calibration(_table(), _context())["amplitude_uT"][-1] == 110


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source", "simulation", "source"),
        ("approved", False, "approved"),
        ("feature", "dB_norm_uT", "feature"),
        ("depth_mm", [0, 2, 1], "depth_mm"),
        ("amplitude_uT", [0, 50, 40], "amplitude_uT"),
    ],
)
def test_unusable_calibration_is_rejected_without_sorting(field, value, message):
    table = _table()
    table[field] = value
    with pytest.raises(ValueError, match=message):
        validate_calibration(table, _context())


def test_context_mismatch_and_extrapolation_are_rejected():
    with pytest.raises(ValueError, match="installation_id"):
        validate_calibration(_table(), {**_context(), "installation_id": "other"})
    with pytest.raises(ValueError, match="direction"):
        validate_calibration(_table(), {**_context(), "direction": "y_positive"})
    with pytest.raises(ValueError, match="speed"):
        validate_calibration(_table(), {**_context(), "speed_mm_s": 10})
    with pytest.raises(ValueError, match="target_uT"):
        validate_calibration(_table(), {**_context(), "target_uT": 120})


def test_scan_summary_is_explicitly_command_based_without_actual_pose(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"run_id": "r1"}))
    with (tmp_path / "sensor.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "seq", "dBx_uT", "dBy_uT", "valid",
        ])
        writer.writeheader()
        writer.writerow({"seq": 1, "dBx_uT": 3, "dBy_uT": 4, "valid": "true"})
    (tmp_path / "control.jsonl").write_text(json.dumps({
        "sample_seq": 1,
        "phase": "cruise",
        "depth_ff_m": 0.001,
        "depth_fb_m": 0.001,
        "actual_pose_available": False,
        "actual_pose_m_rad": None,
    }) + "\n")
    summary = summarize_scan(str(tmp_path))
    assert summary["position_basis"] == "command_based"
    assert summary["approved"] is False
    assert summary["pairs"] == [{
        "sample_seq": 1,
        "depth_mm": 2.0,
        "amplitude_uT": 5.0,
        "phase": "cruise",
    }]
