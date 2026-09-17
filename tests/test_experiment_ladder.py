import pytest

from brushbot.experiments.config import validate_experiment


def ladder_spec(**overrides):
    spec = {
        "version": 1,
        "name": "z_ladder_x",
        "path": {
            "kind": "ladder",
            "axis": "+x",
            "travel_mm": 100.0,
            "depth_from_mm": 0.0,
            "depth_to_mm": 20.0,
            "steps": 8,
            "order": "down_then_up",
            "transit_z_mm": 50.0,
        },
        "motion": {"speed_mm_s": 10.0, "accel_mm_s2": None},
        "control": {"enabled": False},
    }
    spec.update(overrides)
    return spec


def test_ladder_spec_without_z_block_is_valid():
    checked = validate_experiment(ladder_spec())
    assert checked["path"]["kind"] == "ladder"
    assert checked["path"]["steps"] == 8


def test_ladder_spec_rejects_z_block():
    spec = ladder_spec()
    spec["z"] = {"start_tcp_z_mm": 40.0, "end_tcp_z_mm": 20.0}
    with pytest.raises(ValueError, match="unknown field z"):
        validate_experiment(spec)


def test_line_spec_still_requires_z_block():
    spec = ladder_spec()
    spec["path"] = {"kind": "line", "delta_xy_mm": [10.0, 0.0]}
    with pytest.raises(ValueError, match="missing z"):
        validate_experiment(spec)


@pytest.mark.parametrize("axis", ["+x", "-x", "+y", "-y"])
def test_ladder_accepts_four_axes(axis):
    spec = ladder_spec()
    spec["path"]["axis"] = axis
    assert validate_experiment(spec)["path"]["axis"] == axis


def test_ladder_rejects_non_string_axis():
    spec = ladder_spec()
    spec["path"]["axis"] = ["+x"]
    with pytest.raises(ValueError, match="axis must be one of"):
        validate_experiment(spec)


def test_ladder_rejects_unknown_axis():
    spec = ladder_spec()
    spec["path"]["axis"] = "diagonal"
    with pytest.raises(ValueError, match="axis must be one of"):
        validate_experiment(spec)


def test_ladder_rejects_depth_from_above_depth_to():
    spec = ladder_spec()
    spec["path"]["depth_from_mm"] = 20.0
    spec["path"]["depth_to_mm"] = 0.0
    with pytest.raises(ValueError, match="depth_from_mm must be below depth_to_mm"):
        validate_experiment(spec)


def test_ladder_rejects_single_step():
    spec = ladder_spec()
    spec["path"]["steps"] = 1
    with pytest.raises(ValueError, match="steps must be an integer >= 2"):
        validate_experiment(spec)


def test_ladder_rejects_unknown_order():
    spec = ladder_spec()
    spec["path"]["order"] = "up_then_down"
    with pytest.raises(ValueError, match="order must be down_then_up"):
        validate_experiment(spec)


def test_ladder_rejects_negative_depth():
    spec = ladder_spec()
    spec["path"]["depth_from_mm"] = -1.0
    with pytest.raises(ValueError, match="depth_from_mm must be >= 0"):
        validate_experiment(spec)


def test_ladder_rejects_unknown_path_field():
    spec = ladder_spec()
    spec["path"]["radius_mm"] = 5.0
    with pytest.raises(ValueError, match="unknown field path.radius_mm"):
        validate_experiment(spec)


import numpy as np

from brushbot.experiments.trajectory import (
    _ladder_depths,
    compile_experiment,
)


def ladder_setup(**overrides):
    setup = {
        "origin_x_mm": 100.0,
        "origin_y_mm": 200.0,
        "wait_z_mm": 60.0,
        "contact_z_mm": 40.0,
        "vertical_rpy_rad": [0.0, 0.0, 0.0],
        "orientation_tolerance_rad": 0.01,
        "workspace_min_mm": [0.0, 0.0, 0.0],
        "workspace_max_mm": [300.0, 400.0, 100.0],
        "max_depth_mm": 25.0,
        "max_xy_speed_mm_s": 30.0,
        "max_z_speed_mm_s": 10.0,
        "max_accel_mm_s2": 50.0,
        "max_step_mm": 2.0,
        "approach_speed_mm_s": 2.0,
        "return_speed_mm_s": 30.0,
    }
    setup.update(overrides)
    return setup


def test_ladder_depths_goes_down_then_up():
    path = ladder_spec()["path"]
    depths = _ladder_depths(path)
    assert len(depths) == 16
    assert depths[0] == pytest.approx(0.0)
    assert depths[7] == pytest.approx(20.0)
    assert depths[8] == pytest.approx(20.0)
    assert depths[-1] == pytest.approx(0.0)
    for depth in (0.0, 20.0):
        assert depths.count(depth) == 2


def test_ladder_compiles_sixteen_visits_and_four_phases_each():
    compiled = compile_experiment(ladder_spec(), ladder_setup(), dt_s=0.02)
    phases = set(compiled["phase"])
    for visit in range(16):
        for prefix in ("approach", "measure", "lift", "transit"):
            assert f"{prefix}_{visit:02d}" in phases


def test_ladder_phase_dtype_keeps_full_names():
    compiled = compile_experiment(ladder_spec(), ladder_setup(), dt_s=0.02)
    assert compiled["phase"].dtype.itemsize >= 11 * 4
    assert "approach_00" in set(compiled["phase"])
    assert "transit_15" in set(compiled["phase"])


def test_ladder_measure_legs_hold_constant_depth():
    compiled = compile_experiment(ladder_spec(), ladder_setup(), dt_s=0.02)
    phase = compiled["phase"]
    z_mm = compiled["pose_m_rad"][:, 2] * 1000.0
    for visit in range(16):
        mask = phase == f"measure_{visit:02d}"
        assert mask.sum() > 1
        assert np.ptp(z_mm[mask]) < 1e-9


def test_ladder_measure_legs_step_down_then_up():
    compiled = compile_experiment(ladder_spec(), ladder_setup(), dt_s=0.02)
    phase = compiled["phase"]
    z_mm = compiled["pose_m_rad"][:, 2] * 1000.0
    depths = [
        ladder_setup()["contact_z_mm"] - float(z_mm[phase == f"measure_{v:02d}"].mean())
        for v in range(16)
    ]
    assert depths[:8] == pytest.approx(np.linspace(0.0, 20.0, 8))
    assert depths[8:] == pytest.approx(np.linspace(20.0, 0.0, 8))


def test_ladder_xy_is_constant_during_approach_and_lift():
    compiled = compile_experiment(ladder_spec(), ladder_setup(), dt_s=0.02)
    phase = compiled["phase"]
    xy_mm = compiled["pose_m_rad"][:, :2] * 1000.0
    for visit in range(16):
        for prefix in ("approach", "lift"):
            mask = phase == f"{prefix}_{visit:02d}"
            assert np.ptp(xy_mm[mask], axis=0).max() < 1e-9


def test_ladder_never_goes_below_deepest_depth():
    compiled = compile_experiment(ladder_spec(), ladder_setup(), dt_s=0.02)
    z_mm = compiled["pose_m_rad"][:, 2] * 1000.0
    assert z_mm.min() == pytest.approx(20.0)
    assert z_mm.max() == pytest.approx(50.0)


def test_ladder_rejects_depth_beyond_max_depth():
    spec = ladder_spec()
    spec["path"]["depth_to_mm"] = 30.0
    with pytest.raises(ValueError, match="exceeds max_depth_mm"):
        compile_experiment(spec, ladder_setup(), dt_s=0.02)


def test_ladder_rejects_transit_below_a_depth():
    spec = ladder_spec()
    spec["path"]["transit_z_mm"] = 30.0
    with pytest.raises(ValueError, match="transit_z_mm must be above"):
        compile_experiment(spec, ladder_setup(), dt_s=0.02)


def test_ladder_rejects_workspace_violation():
    spec = ladder_spec()
    spec["path"]["travel_mm"] = 500.0
    with pytest.raises(ValueError, match="outside workspace"):
        compile_experiment(spec, ladder_setup(), dt_s=0.02)


def test_ladder_rejects_step_above_max_step():
    setup = ladder_setup(max_step_mm=0.1)
    with pytest.raises(ValueError, match="exceeds max_step_mm"):
        compile_experiment(ladder_spec(), setup, dt_s=0.02)


def test_ladder_rejects_return_speed_above_max_xy():
    setup = ladder_setup(max_xy_speed_mm_s=20.0)
    with pytest.raises(ValueError, match="return_speed_mm_s exceeds max_xy_speed_mm_s"):
        compile_experiment(ladder_spec(), setup, dt_s=0.02)


def test_ladder_rejects_approach_speed_above_max_z():
    setup = ladder_setup(max_z_speed_mm_s=1.0)
    with pytest.raises(ValueError, match="approach_speed_mm_s exceeds max_z_speed_mm_s"):
        compile_experiment(ladder_spec(), setup, dt_s=0.02)


def test_ladder_depth_ff_is_zero_above_contact():
    compiled = compile_experiment(ladder_spec(), ladder_setup(), dt_s=0.02)
    phase = compiled["phase"]
    transit = np.char.startswith(phase.astype(str), "transit")
    assert np.all(compiled["depth_ff_m"][transit] == 0.0)


def test_ladder_timeline_starts_at_zero_is_strictly_increasing_and_dt_bounded():
    # 引擎按时间轴推进：索引不得跨拍前进（engine.py 的 deadline_miss），
    # 因此 t_s 必须从 0 开始、严格递增、且最大步长不超过 dt_s。
    compiled = compile_experiment(ladder_spec(), ladder_setup(), dt_s=0.02)
    t_s = compiled["t_s"]
    assert len(t_s) > 2
    assert t_s[0] == pytest.approx(0.0)
    step = np.diff(t_s)
    assert np.all(step > 0.0)
    assert np.max(step) <= 0.02 + 1e-9


from pathlib import Path

from brushbot.experiments.config import load_experiment, validate_installation

REPO = Path(__file__).resolve().parents[1]


def test_shipped_ladder_experiment_is_valid():
    checked = load_experiment(REPO / "configs/experiments/z_ladder_x.json")
    assert checked["path"]["kind"] == "ladder"
    assert checked["path"]["steps"] == 8
    assert checked["path"]["depth_to_mm"] == pytest.approx(20.0)
    assert checked["path"]["transit_z_mm"] == pytest.approx(50.0)
    assert checked["control"]["enabled"] is False


def test_installation_template_is_not_executable():
    import json
    template = json.loads(
        (REPO / "configs/installations/template.json").read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="verified must be true"):
        validate_installation(template, hardware=True)


def test_installation_template_preview_is_accepted():
    import json
    template = json.loads(
        (REPO / "configs/installations/template.json").read_text(encoding="utf-8"))
    assert validate_installation(template, hardware=False)["verified"] is False
