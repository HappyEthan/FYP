import numpy as np
import pytest
from brushbot.z_control import ZController


# Shared calibration: 0–5 mm press → 0–250 µT |ΔB| (monotonic, linear-ish)
_CALIB_Z = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0], dtype=float)
_CALIB_DB = np.array([0.0, 50.0, 100.0, 150.0, 200.0, 250.0], dtype=float)


Z_SURFACE = 0.20  # must match ZController default


def _plant(z_cmd, calib_z, calib_dB):
    """Synthetic plant: z_cmd (world m) → |ΔB| (µT). Same curve as calibration.

    Converts world-frame z_cmd to z_offset by subtracting Z_SURFACE,
    then interpolates on the calibration curve.
    """
    z_off_mm = (z_cmd - Z_SURFACE) * 1000.0
    return float(np.interp(z_off_mm, calib_z, calib_dB, left=0.0, right=calib_dB[-1]))


def test_z_ff_interpolation():
    """前饋插值在標定範圍內連續，超出範圍時飽和保護。"""
    ctrl = ZController(_CALIB_Z, _CALIB_DB, dt=0.01)
    # Inside range
    z = ctrl._z_ff_lookup(100.0)
    assert 0.001 < z < 0.005, f"z_ff(100) = {z}, expected ~0.002"
    # Outside → clamp to bounds
    z_low = ctrl._z_ff_lookup(-10.0)
    assert z_low == 0.0, f"z_ff(-10) = {z_low}, expected 0.0"
    z_high = ctrl._z_ff_lookup(1e6)
    assert z_high > 0.004, f"z_ff(1e6) = {z_high}, expected ~0.005"
    # z_ff output is in meters
    assert ctrl._z_ff_lookup(150.0) == pytest.approx(0.003, rel=0.01)


def test_s_cal_from_calib():
    """S_cal = z 跨度 / |ΔB| 跨度 (m/µT)。"""
    ctrl = ZController(_CALIB_Z, _CALIB_DB, dt=0.01)
    assert ctrl.s_cal == pytest.approx(0.005 / 250.0)


def test_kp_dimensionless_semantics():
    """kp=0.5 表示每拍修正误差的 50%: 比例项 = kp·S_cal·e。"""
    ctrl = ZController(_CALIB_Z, _CALIB_DB, dt=0.01, kp=0.5, ki=0.0)
    z_cmd = ctrl.step(np.array([100.0, 0.0, 0.0]), 150.0)  # e = 50, 未 freeze
    expected = 0.20 + 0.003 + 0.5 * ctrl.s_cal * 50.0      # surface + z_ff(150) + Kp 项
    assert z_cmd == pytest.approx(expected)


def test_reset_clears_integrator():
    """reset 後反饋項歸零。"""
    ctrl = ZController(_CALIB_Z, _CALIB_DB, dt=0.01, ki=5.0)
    # Run a few steps to build up integrator
    for _ in range(50):
        ctrl.step(np.array([0.0, 0.0, 50.0]), 150.0)  # g_d=150 but meas only 50
    assert ctrl.z_fb > 0.001, "z_fb should have built up"
    ctrl.reset()
    assert ctrl.z_fb == 0.0
    assert ctrl.z_fb == pytest.approx(0.0)


def test_z_fb_clamping():
    """反饋超出 DZ_MARGIN 時被限幅，退飽和啟動。"""
    ctrl = ZController(_CALIB_Z, _CALIB_DB, dt=0.01, ki=5.0, dz_margin=1e-3,
                       noise_std=1.0)  # lower noise_std so dB_meas stays above 3σ
    # Large persistent error should saturate the integrator
    for _ in range(200):
        ctrl.step(np.array([0.0, 0.0, 30.0]), 200.0)  # abs_meas=30 > 3σ=3 → not frozen
    assert abs(ctrl.z_fb) <= 1e-3 + 1e-9, f"z_fb={ctrl.z_fb} exceeded margin"


def test_lift_freezes_integrator():
    """目標 |ΔB| < 閾值時積分凍結（筆擡起時誤差無意義）。"""
    ctrl = ZController(_CALIB_Z, _CALIB_DB, dt=0.01, ki=1.0)
    # Build up some integrator
    for _ in range(50):
        ctrl.step(np.array([0.0, 0.0, 80.0]), 150.0)
    z_before = ctrl.z_fb
    # Now simulate lift: g_d near zero
    for _ in range(50):
        ctrl.step(np.array([0.0, 0.0, 5.0]), 5.0)
    assert ctrl.z_fb == pytest.approx(z_before, abs=1e-9), "z_fb changed during lift"
    assert ctrl.frozen


def test_air_freezes_integrator():
    """測量 |ΔB| < 3σ 時積分凍結（筆懸空時無接觸信號）。"""
    noise_std = 7.0  # µT
    ctrl = ZController(_CALIB_Z, _CALIB_DB, dt=0.01, ki=1.0, noise_std=noise_std)
    # Build up some integrator
    for _ in range(50):
        ctrl.step(np.array([0.0, 0.0, 80.0]), 150.0)
    z_before = ctrl.z_fb
    # Now dB_meas is tiny → no contact
    for _ in range(50):
        ctrl.step(np.array([0.0, 0.0, noise_std]), 150.0)
    assert ctrl.z_fb == pytest.approx(z_before, abs=1e-9), "z_fb changed during air"


def test_step_tracks_constant():
    """固定目標下閉環用默認無量綱增益收斂到 ±5%。"""
    ctrl = ZController(_CALIB_Z, _CALIB_DB, dt=0.01)
    g_d = 120.0
    dB_meas = np.zeros(3)
    for _ in range(300):
        z_cmd = ctrl.step(dB_meas, g_d)
        abs_meas = _plant(z_cmd, _CALIB_Z, _CALIB_DB)
        dB_meas = np.array([abs_meas, 0.0, 0.0])
    error = abs(g_d - np.linalg.norm(dB_meas)) / g_d
    assert error < 0.05, f"steady-state error {error:.3f} > 0.05"
