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
            "pause_every_passes": 4,
            "pause_z_mm": 100.0,
        },
        "motion": {"speed_mm_s": 10.0, "accel_mm_s2": None},
        "control": {"enabled": False},
    }
    spec.update(overrides)
    return spec


def wetting_block(**overrides):
    wetting = {
        "every_paths": 1,
        "x_mm": -300.0,
        "y_mm": 500.0,
        "cup_rim_z_mm": 100.0,
        "safe_z_mm": 120.0,
        "dip_z_mm": 50.0,
        "dwell_s": 1.0,
        "settle_s": 0.5,
    }
    wetting.update(overrides)
    return wetting


def wetting_ladder_spec(**overrides):
    spec = ladder_spec()
    spec["path"].pop("pause_every_passes")
    spec["path"].pop("pause_z_mm")
    spec["path"]["wetting"] = wetting_block(**overrides)
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


@pytest.mark.parametrize("value", [0, -1, 1.5, True])
def test_ladder_rejects_invalid_pause_interval(value):
    spec = ladder_spec()
    spec["path"]["pause_every_passes"] = value
    with pytest.raises(ValueError, match="pause_every_passes must be a positive integer"):
        validate_experiment(spec)


def test_ladder_accepts_automatic_wetting_block():
    spec = wetting_ladder_spec()

    checked = validate_experiment(spec)

    assert checked["path"]["wetting"] == wetting_block()


def test_ladder_rejects_unknown_automatic_wetting_field():
    spec = wetting_ladder_spec(radius_mm=20.0)

    with pytest.raises(ValueError, match="unknown field path.wetting.radius_mm"):
        validate_experiment(spec)


@pytest.mark.parametrize("value", [0, -1, 1.5, True])
def test_ladder_rejects_invalid_automatic_wetting_interval(value):
    spec = wetting_ladder_spec(every_paths=value)

    with pytest.raises(ValueError, match="wetting.every_paths must be a positive integer"):
        validate_experiment(spec)


@pytest.mark.parametrize(
    "field", ["x_mm", "y_mm", "cup_rim_z_mm", "safe_z_mm", "dip_z_mm"])
def test_ladder_rejects_non_finite_automatic_wetting_coordinates(field):
    spec = wetting_ladder_spec(**{field: float("nan")})

    with pytest.raises(ValueError, match=f"wetting.{field} must be finite"):
        validate_experiment(spec)


@pytest.mark.parametrize("field", ["dwell_s", "settle_s"])
def test_ladder_rejects_negative_automatic_wetting_durations(field):
    spec = wetting_ladder_spec(**{field: -0.1})

    with pytest.raises(ValueError, match=f"wetting.{field} must be >= 0"):
        validate_experiment(spec)


def test_ladder_requires_automatic_wetting_safe_z_above_dip_z():
    spec = wetting_ladder_spec(safe_z_mm=50.0, dip_z_mm=50.0)

    with pytest.raises(
            ValueError,
            match="path.wetting.safe_z_mm must be above path.wetting.dip_z_mm"):
        validate_experiment(spec)


def test_ladder_requires_automatic_wetting_safe_z_above_cup_rim():
    spec = wetting_ladder_spec(safe_z_mm=100.0, cup_rim_z_mm=100.0)

    with pytest.raises(
            ValueError,
            match="path.wetting.safe_z_mm must be above path.wetting.cup_rim_z_mm"):
        validate_experiment(spec)


def test_ladder_requires_automatic_wetting_dip_z_below_cup_rim():
    spec = wetting_ladder_spec(dip_z_mm=100.0, cup_rim_z_mm=100.0)

    with pytest.raises(
            ValueError,
            match="path.wetting.dip_z_mm must be below path.wetting.cup_rim_z_mm"):
        validate_experiment(spec)


def test_ladder_rejects_combining_manual_pause_and_automatic_wetting():
    spec = ladder_spec()
    spec["path"]["wetting"] = wetting_block()

    with pytest.raises(ValueError, match="wetting cannot be combined with manual pause"):
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


def test_one_way_ladder_compiles_safe_wetting_before_every_path():
    spec = wetting_ladder_spec()
    spec["path"].update({
        "travel_mm": 200.0,
        "steps": 5,
        "order": "one_way",
        "transit_z_mm": 50.0,
    })
    setup = ladder_setup(
        origin_x_mm=-200.0,
        origin_y_mm=500.0,
        wait_z_mm=130.0,
        workspace_min_mm=[-400.0, 400.0, 0.0],
        workspace_max_mm=[100.0, 600.0, 150.0],
        max_z_speed_mm_s=13.0,
        approach_speed_mm_s=13.0,
        return_speed_mm_s=13.0,
    )

    compiled = compile_experiment(spec, setup)
    phases = compiled["phase"]
    poses_mm = compiled["pose_m_rad"][:, :3] * 1000.0

    assert compiled["automatic_rebaseline_next_visits"] == [0, 1, 2, 3, 4]
    assert len(compiled["automatic_rebaseline_after_indices"]) == 5
    for visit in range(5):
        suffix = f"{visit:02d}"
        for prefix in (
                "wet_rise_", "wet_transfer_out_", "wet_dip_", "wet_dwell_",
                "wet_lift_", "wet_transfer_back_", "wet_settle_", "wet_lower_"):
            assert f"{prefix}{suffix}" in phases
        measure = poses_mm[phases == f"measure_{suffix}"]
        assert measure[0] == pytest.approx(
            [-200.0, 500.0, measure[0, 2]], abs=0.05)
        assert measure[-1] == pytest.approx([0.0, 500.0, measure[-1, 2]])
        for prefix in ("wet_transfer_out_", "wet_transfer_back_"):
            transfer = poses_mm[phases == f"{prefix}{suffix}"]
            assert transfer[:, 2] == pytest.approx(120.0)
        dip = poses_mm[phases == f"wet_dip_{suffix}"]
        assert dip[:, 0] == pytest.approx(-300.0)
        assert dip[:, 1] == pytest.approx(500.0)
        assert dip[-1, 2] == pytest.approx(50.0)
        dwell = poses_mm[phases == f"wet_dwell_{suffix}"]
        assert np.allclose(dwell, [-300.0, 500.0, 50.0])
        settle = poses_mm[phases == f"wet_settle_{suffix}"]
        assert np.allclose(settle, [-200.0, 500.0, 120.0])
    assert not any(str(phase).endswith("_05") for phase in phases)


def test_automatic_wetting_allows_zero_dwell_and_settle_times():
    spec = wetting_ladder_spec(
        x_mm=0.0, y_mm=200.0, cup_rim_z_mm=80.0,
        safe_z_mm=100.0, dip_z_mm=50.0,
        dwell_s=0.0, settle_s=0.0)
    spec["path"]["order"] = "one_way"

    compiled = compile_experiment(spec, ladder_setup())

    assert len(compiled["automatic_rebaseline_after_indices"]) == 8
    assert not any(str(phase).startswith("wet_dwell_") for phase in compiled["phase"])
    assert not any(str(phase).startswith("wet_settle_") for phase in compiled["phase"])


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


def test_one_way_ladder_visits_each_configured_depth_once():
    path = ladder_spec()["path"]
    path["order"] = "one_way"

    assert _ladder_depths(path) == pytest.approx(
        [0.0, 20.0 / 7, 40.0 / 7, 60.0 / 7, 80.0 / 7,
         100.0 / 7, 120.0 / 7, 20.0])

    compiled = compile_experiment(ladder_spec(path=path), ladder_setup(), dt_s=0.02)
    assert sorted({phase for phase in compiled["phase"] if phase.startswith("measure_")}) == [
        f"measure_{visit:02d}" for visit in range(8)
    ]


def test_ladder_compiles_sixteen_visits_and_four_phases_each():
    compiled = compile_experiment(ladder_spec(), ladder_setup(), dt_s=0.02)
    phases = set(compiled["phase"])
    for visit in range(16):
        for prefix in ("approach", "measure", "lift", "transit"):
            assert f"{prefix}_{visit:02d}" in phases


def test_ladder_pause_boundaries_follow_completed_high_returns_and_skip_final_pass():
    compiled = compile_experiment(ladder_spec(), ladder_setup(), dt_s=0.02)
    indices = compiled["pause_after_indices"]

    assert [compiled["phase"][index] for index in indices] == [
        "pause_lift_03", "pause_lift_07", "pause_lift_11",
    ]
    assert compiled["pause_next_visits"] == [4, 8, 12]
    for index in indices:
        pose_mm = compiled["pose_m_rad"][index, :3] * 1000.0
        assert pose_mm == pytest.approx([100.0, 200.0, 100.0])


def test_ladder_resumes_from_pause_height_with_a_smooth_vertical_lower():
    compiled = compile_experiment(ladder_spec(), ladder_setup(), dt_s=0.02)
    phase = compiled["phase"]
    pose_mm = compiled["pose_m_rad"][:, :3] * 1000.0

    lower = pose_mm[phase == "pause_lower_03"]

    assert lower[0, :2] == pytest.approx([100.0, 200.0])
    assert 99.0 < lower[0, 2] < 100.0
    assert lower[-1] == pytest.approx([100.0, 200.0, 50.0])
    assert np.all(np.diff(lower[:, 2]) <= 1e-9)


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
    assert z_mm.max() == pytest.approx(100.0)


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
    assert checked["path"]["steps"] == 5
    assert checked["path"]["travel_mm"] == pytest.approx(200.0)
    assert checked["path"]["pause_every_passes"] == 4
    assert checked["path"]["depth_from_mm"] == pytest.approx(9.0)
    assert checked["path"]["depth_to_mm"] == pytest.approx(13.0)
    assert checked["path"]["order"] == "one_way"
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


from brushbot.experiments.calibration import summarize_ladder
from brushbot.experiments.fake import make_ladder_rig


def test_ladder_rig_completes_and_summarizes(tmp_path):
    rig = make_ladder_rig(recorder_root=str(tmp_path))
    rig.engine.start()
    rig.advance_until("END_WAIT", max_steps=4000)
    assert rig.saved_status == "completed"
    summary = summarize_ladder(rig.engine.snapshot()["run_dir"])
    assert summary["position_basis"] == "actual_pose"
    assert summary["quality"]["monotonic"] is True
    assert summary["quality"]["origin_ok"] is True
    assert len(summary["rungs"]) == 2


def test_ladder_rig_amplitudes_grow_with_depth(tmp_path):
    rig = make_ladder_rig(recorder_root=str(tmp_path))
    rig.engine.start()
    rig.advance_until("END_WAIT", max_steps=4000)
    summary = summarize_ladder(rig.engine.snapshot()["run_dir"])
    amplitudes = [rung["amplitude_uT"] for rung in summary["rungs"]]
    assert amplitudes[0] < amplitudes[1]


def test_ladder_timeline_never_lets_the_engine_skip_more_than_one_tick():
    # 引擎按 elapsed = k*dt 对时间轴做 searchsorted 取索引。时间轴的采样时刻与引擎的 elapsed
    # 各自带浮点误差，两者网格对不齐时某一拍可能同时跨过两个样本——引擎的 deadline_miss 判据
    # 正是按"最多 2 个样本"来容忍这个伪影的。这条测试直接模拟引擎的取索引过程。
    # 只断言"最大间隔 <= dt"抓不到这个 bug：梯子有 0.02 的均匀网格时同样会让一拍跨过两个样本
    # （实测 228 次），而最大间隔始终是 0.02。
    compiled = compile_experiment(ladder_spec(), ladder_setup(), dt_s=0.02)
    t_s = compiled["t_s"]
    dt_s = 0.02
    last = 0
    for tick in range(1, int(t_s[-1] / dt_s) + 3):
        index = min(int(np.searchsorted(t_s, tick * dt_s, side="right") - 1), len(t_s) - 1)
        index = max(index, 0)
        assert float(t_s[index]) - float(t_s[last]) <= 2.5 * dt_s
        last = index
