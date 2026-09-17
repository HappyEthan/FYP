import copy
import json
import sys
from pathlib import Path

import pytest

from brushbot.experiments.config import (
    load_experiment,
    validate_experiment,
    validate_installation,
)


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "configs" / "experiments"


def _open_scan():
    return {
        "version": 1,
        "name": "x_press_scan",
        "_comment": "其他候选 X 速度：10、20 mm/s；不是自动批次",
        "path": {"kind": "line", "delta_xy_mm": [400, 0]},
        "motion": {"speed_mm_s": 5, "accel_mm_s2": None},
        "z": {"start_tcp_z_mm": 40, "end_tcp_z_mm": 20},
        "control": {"enabled": False},
    }


def _hardware_setup():
    return {
        "installation_id": "fixture-a",
        "verified": True,
        "tcp_name": "brush-root",
        "ucs_name": "paper",
        "tool_coord_si": [0, 0, 0, 0, 0, 0],
        "user_coord_si": [0, 0, 0, 0, 0, 0],
        "vertical_rpy_rad": [3.141592653589793, 0, 0],
        "sensor_mount_id": "mount-a",
        "origin_x_mm": 100,
        "origin_y_mm": 200,
        "wait_z_mm": 60,
        "contact_z_mm": 40,
        "workspace_min_mm": [0, 0, 0],
        "workspace_max_mm": [500, 500, 200],
        "max_depth_mm": 25,
        "max_xy_speed_mm_s": 25,
        "max_z_speed_mm_s": 10,
        "max_accel_mm_s2": 50,
        "max_step_mm": 2,
        "approach_speed_mm_s": 2,
        "return_speed_mm_s": 10,
        "pose_tolerance_mm": 1,
        "orientation_tolerance_rad": 0.02,
        "baseline_window_s": 1,
        "baseline_timeout_s": 5,
        "baseline_min_samples": 50,
        "baseline_max_std_uT": [2, 2, 2],
        "baseline_max_drift_uT_s": 1,
        "sensor_max_age_s": 0.05,
        "max_tick_lateness_s": 0.01,
        "stop_timeout_s": 1,
        "gripper_width_mm": 10,
        "gripper_speed": 30,
        "gripper_force": 30,
        "filter": {"kind": "ema", "alpha": 0.3},
    }


def test_open_scan_has_no_magnetic_target():
    data = _open_scan()
    assert validate_experiment(data)["control"] == {"enabled": False}
    data["motion"]["speed_mm_s"] = -1
    with pytest.raises(ValueError, match="speed_mm_s"):
        validate_experiment(data)


@pytest.mark.parametrize(
    ("mutate", "field"),
    [
        (lambda d: d["path"].update(delta_xy_mm=[400]), "delta_xy_mm"),
        (lambda d: d["z"].update(start_tcp_z_mm=float("nan")), "start_tcp_z_mm"),
        (lambda d: d["motion"].update(accel_mm_s2=0), "accel_mm_s2"),
        (lambda d: d.update(version=2), "version"),
    ],
)
def test_experiment_rejects_invalid_units_and_non_finite_values(mutate, field):
    data = _open_scan()
    mutate(data)
    with pytest.raises(ValueError, match=field):
        validate_experiment(data)


def test_closed_loop_null_fields_are_preview_only():
    data = _open_scan()
    data["control"] = {
        "enabled": True,
        "target_uT": None,
        "deadband_uT": 0,
        "kp": None,
        "ki": None,
        "calibration_file": None,
    }
    preview = validate_experiment(data)
    assert preview["control"]["target_uT"] is None
    with pytest.raises(ValueError, match="target_uT.*kp.*ki.*calibration_file"):
        validate_experiment(data, executable=True)


def test_closed_loop_requires_all_control_keys_even_for_preview():
    data = _open_scan()
    data["control"] = {"enabled": True, "target_uT": None}
    with pytest.raises(ValueError, match="deadband_uT"):
        validate_experiment(data)


def test_hardware_installation_reports_all_missing_or_unverified_fields():
    with pytest.raises(ValueError) as exc:
        validate_installation({"verified": False}, hardware=True)
    message = str(exc.value)
    assert "verified" in message
    assert "contact_z_mm" in message
    assert "workspace_min_mm" in message
    assert "vertical_rpy_rad" in message


def test_hardware_installation_does_not_fill_candidate_values():
    setup = _hardware_setup()
    checked = validate_installation(setup, hardware=True)
    assert checked == setup
    incomplete = copy.deepcopy(setup)
    incomplete["contact_z_mm"] = None
    with pytest.raises(ValueError, match="contact_z_mm"):
        validate_installation(incomplete, hardware=True)


def test_loading_templates_is_standard_json_and_has_no_hardware_import():
    before = set(sys.modules)
    names = {
        "x_press_scan.json",
        "horizontal_hold.json",
        "vertical_hold.json",
        "circle_hold.json",
        "z_ladder_x.json",
    }
    assert {p.name for p in TEMPLATES.glob("*.json")} == names
    for name in names:
        path = TEMPLATES / name
        parsed = json.loads(path.read_text(encoding="utf-8"))
        assert load_experiment(path) == validate_experiment(parsed)
    imported = set(sys.modules) - before
    assert not any(name == "huayan_robot" or name.startswith("huayan_robot.") for name in imported)


def test_json_nan_constant_is_rejected(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"version": 1, "value": NaN}', encoding="utf-8")
    with pytest.raises(ValueError, match="NaN"):
        load_experiment(path)
