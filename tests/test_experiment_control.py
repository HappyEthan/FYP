import numpy as np
import pytest

from brushbot.z_control import ZController


CAL_Z = np.array([0.0, 1.0, 2.0])
CAL_A = np.array([0.0, 100.0, 200.0])


def test_band_does_not_accumulate_small_error():
    controller = ZController(
        CAL_Z, CAL_A, z_surface=0, kp=1, ki=1, noise_std=0,
        deadband_uT=5, dz_step_max=1,
    )
    depth = controller.step_magnitude(98.0, 100.0, depth_ff_m=0.001)
    assert depth == pytest.approx(0.001)
    assert controller.z_fb == pytest.approx(0)


def test_error_outside_band_uses_nearest_band_edge():
    controller = ZController(
        CAL_Z, CAL_A, z_surface=0, kp=1, ki=0, noise_std=0,
        deadband_uT=5, dz_step_max=1,
    )
    depth = controller.step_magnitude(90.0, 100.0, depth_ff_m=0.001)
    assert depth == pytest.approx(0.001 + controller.s_cal * 5.0)


def test_deadband_choice_never_changes_feedforward_depth():
    exact = ZController(CAL_Z, CAL_A, z_surface=0, kp=0, ki=0,
                        deadband_uT=0, dz_step_max=1)
    band = ZController(CAL_Z, CAL_A, z_surface=0, kp=0, ki=0,
                       deadband_uT=5, dz_step_max=1)
    assert exact.step_magnitude(80, 100, depth_ff_m=0.0017) == pytest.approx(0.0017)
    assert band.step_magnitude(80, 100, depth_ff_m=0.0017) == pytest.approx(0.0017)


def test_step_magnitude_is_independent_of_bz():
    controller = ZController(CAL_Z, CAL_A, z_surface=0, kp=0.3, ki=0,
                             deadband_uT=0, dz_step_max=1)
    dxy = np.array([30.0, 40.0])
    first = controller.step_magnitude(np.hypot(*dxy), 100, depth_ff_m=0.001)
    controller.reset()
    second = controller.step_magnitude(np.hypot(*dxy), 100, depth_ff_m=0.001)
    assert first == second


def test_non_finite_magnitude_is_rejected_before_pressing():
    controller = ZController(CAL_Z, CAL_A, z_surface=0, deadband_uT=0)
    with pytest.raises(ValueError, match="finite"):
        controller.step_magnitude(float("nan"), 100, depth_ff_m=0.001)


def test_saturation_rejects_integral_that_pushes_farther_into_limit():
    controller = ZController(
        CAL_Z, CAL_A, z_surface=0, kp=10, ki=10, noise_std=0,
        deadband_uT=0, z_press_max=0.002, dz_margin=0.001,
        dz_step_max=1,
    )
    controller.step_magnitude(0, 200, depth_ff_m=0.002)
    assert controller.z_fb == pytest.approx(0)
    assert controller.limit_active


def test_reset_starts_each_run_without_integral_history():
    controller = ZController(CAL_Z, CAL_A, z_surface=0, kp=0, ki=1,
                             noise_std=0, deadband_uT=0, dz_step_max=1)
    controller.step_magnitude(50, 100, depth_ff_m=0.001)
    assert controller.z_fb > 0
    controller.reset()
    assert controller.z_fb == 0
    assert controller.limit_active is False
