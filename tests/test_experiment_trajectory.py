import numpy as np
import pytest

from brushbot.experiments.trajectory import (
    compile_experiment,
    tcp_z_m,
    time_law,
)


def _spec(*, speed=5.0, accel=50.0):
    return {
        "version": 1,
        "name": "line",
        "path": {"kind": "line", "delta_xy_mm": [400, 0]},
        "motion": {"speed_mm_s": speed, "accel_mm_s2": accel},
        "z": {"start_tcp_z_mm": 40, "end_tcp_z_mm": 20},
        "control": {"enabled": False},
    }


def _setup():
    return {
        "origin_x_mm": 100,
        "origin_y_mm": 200,
        "wait_z_mm": 60,
        "contact_z_mm": 40,
        "vertical_rpy_rad": [1.0, 2.0, 3.0],
        "orientation_tolerance_rad": 0.01,
        "workspace_min_mm": [0, 0, 0],
        "workspace_max_mm": [600, 400, 100],
        "max_depth_mm": 25,
        "max_xy_speed_mm_s": 25,
        "max_z_speed_mm_s": 10,
        "max_accel_mm_s2": 50,
        "max_step_mm": 2,
    }


def test_root_tcp_depth_sign():
    assert tcp_z_m(40, 0) == pytest.approx(0.040)
    assert tcp_z_m(40, 20) == pytest.approx(0.020)


@pytest.mark.parametrize(("speed", "ideal"), [(5, 80), (10, 40), (20, 20)])
def test_time_law_includes_acceleration_and_exact_endpoint(speed, ideal):
    law = time_law(400, speed, 50, 0.02)
    assert law["t_s"][0] == 0
    assert law["distance_mm"][0] == 0
    assert law["distance_mm"][-1] == pytest.approx(400)
    assert law["s"][-1] == 1
    assert law["t_s"][-1] > ideal
    assert {"ramp_up", "cruise", "ramp_down"}.issubset(set(law["phase"]))
    assert np.all(np.diff(law["distance_mm"]) >= 0)


def test_short_move_uses_triangular_profile():
    law = time_law(1, 100, 10, 0.02)
    assert "cruise" not in set(law["phase"])
    assert law["v_peak_mm_s"] == pytest.approx(np.sqrt(10))


def test_compile_line_uses_monitor_origin_and_preserves_open_loop_nan():
    result = compile_experiment(_spec(), _setup())
    assert set(result) == {
        "plan", "t_s", "s", "phase", "pose_m_rad", "g_ref_uT",
        "depth_ff_m", "spec_snapshot", "setup_snapshot",
    }
    np.testing.assert_allclose(result["pose_m_rad"][0], [0.1, 0.2, 0.04, 1, 2, 3])
    np.testing.assert_allclose(result["pose_m_rad"][-1], [0.5, 0.2, 0.02, 1, 2, 3])
    assert np.isnan(result["g_ref_uT"]).all()
    assert result["plan"].meta["control_mode"] == "off"
    assert result["depth_ff_m"][-1] == pytest.approx(0.02)


def test_circle_starts_at_local_zero_and_clockwise_moves_negative_y():
    spec = _spec()
    spec["path"] = {"kind": "circle", "radius_mm": 20, "clockwise": True}
    spec["z"] = {"start_tcp_z_mm": 40, "end_tcp_z_mm": 40}
    result = compile_experiment(spec, _setup())
    np.testing.assert_allclose(result["pose_m_rad"][0, :2], [0.1, 0.2])
    assert result["pose_m_rad"][1, 1] < 0.2
    np.testing.assert_allclose(result["pose_m_rad"][-1, :2], [0.1, 0.2], atol=1e-12)


def test_compile_resolves_null_acceleration_only_from_setup_limit():
    spec = _spec(accel=None)
    assert compile_experiment(spec, _setup())["t_s"][-1] > 80
    setup = _setup()
    setup["max_accel_mm_s2"] = None
    with pytest.raises(ValueError, match="max_accel_mm_s2"):
        compile_experiment(spec, setup)


def test_compile_checks_z_speed_and_single_step_not_only_x_speed():
    spec = _spec(speed=20, accel=50)
    setup = _setup()
    setup["max_z_speed_mm_s"] = 0.5
    with pytest.raises(ValueError, match="max_z_speed_mm_s"):
        compile_experiment(spec, setup)
    setup = _setup()
    setup["max_step_mm"] = 0.01
    with pytest.raises(ValueError, match="max_step_mm"):
        compile_experiment(spec, setup)


def test_circle_rejects_speed_whose_centripetal_acceleration_exceeds_limit():
    spec = _spec(speed=20, accel=1)
    spec["path"] = {"kind": "circle", "radius_mm": 20, "clockwise": False}
    with pytest.raises(ValueError, match="centripetal"):
        compile_experiment(spec, _setup())


def test_closed_loop_null_target_cannot_compile():
    spec = _spec()
    spec["control"] = {
        "enabled": True,
        "target_uT": None,
        "deadband_uT": 0,
        "kp": None,
        "ki": None,
        "calibration_file": None,
    }
    with pytest.raises(ValueError, match="target_uT"):
        compile_experiment(spec, _setup())
