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
    """固定目標下閉環機制驗證：顯式温和增益 kp=0.3/ki=0.03 在理想瞬時 plant
    （零延遲、零執行器滯後）上收斂到 ±5%。

    本測試考的是"閉環機制本身能收斂"，不考默認增益政策——Phase 1 回填後的默認值
    (kp=1.2077/ki=0.134) 是在假設執行器滯後 (n_delay=2 拍、tau=0.05s) 的前提下由
    層 1/層 2 掃描得出的工作點，套到本測試零滯後的理想瞬時 plant 上會單拍過衝出整
    個標定量程觸發飽和式極限環，不收斂（不是機制壞了，是工作點的前提條件不滿足）。
    默認增益在其設計前提（有延遲/滯後的真實 plant）下的收斂性由
    `tests/test_sim_loop.py::test_run_loop_closed_loop_converges_constant`
    （用 `sim_loop.Plant`，含 n_delay=2 拍傳輸延遲 + tau=0.05s 一階執行器）驗證。
    （2026-07-30 Task 9 修訂）
    """
    ctrl = ZController(_CALIB_Z, _CALIB_DB, dt=0.01, kp=0.3, ki=0.03)
    g_d = 120.0
    dB_meas = np.zeros(3)
    for _ in range(300):
        z_cmd = ctrl.step(dB_meas, g_d)
        abs_meas = _plant(z_cmd, _CALIB_Z, _CALIB_DB)
        dB_meas = np.array([abs_meas, 0.0, 0.0])
    error = abs(g_d - np.linalg.norm(dB_meas)) / g_d
    assert error < 0.05, f"steady-state error {error:.3f} > 0.05"


# ---------------------------------------------------------------- 输出钳位
# z_cmd 离开控制器前的两层安全钳（2026-08-10 审计 R1）：
# 绝对位置钳 = 物理不变量（笔尖最深/最高），速率钳 = 动力学不变量（单拍跳变）。
# 正常书写时两钳都不应咬合；只在异常（断线补零/数据污染/freeze 切换毛刺）时介入。


def test_abs_clamp_bounds_depth_on_sensor_stuck_zero():
    """传感器卡 0 + 目标满量程：压深被钳在 z_press_max（默认 = 标定量程+积分权限+1mm）。

    无钳位时该场景 kp 项 + z_ff 会算出 ~11mm（标定量程仅 5mm）。"""
    ctrl = ZController(_CALIB_Z, _CALIB_DB, dt=0.01)
    assert ctrl.z_press_max == pytest.approx(0.005 + 3e-3 + 1e-3)  # 默认推导
    for _ in range(100):
        z_cmd = ctrl.step(np.zeros(3), 250.0)
        assert z_cmd - Z_SURFACE <= ctrl.z_press_max + 1e-12


def test_abs_clamp_bounds_depth_on_garbage_target():
    """上游污染 g_d=1e4（无钳位时 ~246mm）：仍被钳在 z_press_max。"""
    ctrl = ZController(_CALIB_Z, _CALIB_DB, dt=0.01)
    z_cmd = ctrl.step(np.zeros(3), 1e4)
    assert z_cmd - Z_SURFACE <= ctrl.z_press_max + 1e-12


def test_abs_clamp_bounds_lift():
    """反向大误差（测量异常大、目标 0）：抬笔不超过 z_lift_max。"""
    ctrl = ZController(_CALIB_Z, _CALIB_DB, dt=0.01)
    z_cmd = ctrl.step(np.array([2000.0, 0.0, 0.0]), 0.0)
    assert z_cmd >= Z_SURFACE - ctrl.z_lift_max - 1e-12


def test_rate_clamp_limits_single_step_jump():
    """相邻两拍 z_cmd 之差 ≤ dz_step_max（默认 0.2mm/拍，即 Q4 毛刺判据）。"""
    ctrl = ZController(_CALIB_Z, _CALIB_DB, dt=0.01)
    z_prev = ctrl.step(np.array([120.0, 0.0, 0.0]), 120.0)  # 正常接触拍
    z2 = ctrl.step(np.zeros(3), 250.0)                      # 突发大误差
    assert abs(z2 - z_prev) <= ctrl.dz_step_max + 1e-12
    # 持续大误差：每拍最多爬 dz_step_max，且始终不越绝对钳
    z_last = z2
    for _ in range(100):
        z = ctrl.step(np.zeros(3), 250.0)
        assert abs(z - z_last) <= ctrl.dz_step_max + 1e-12
        assert z - Z_SURFACE <= ctrl.z_press_max + 1e-12
        z_last = z


def test_clamps_inactive_in_nominal_tracking():
    """正常小误差跟踪时输出与无钳位公式逐位一致（钳位对标称行为零影响）。"""
    ctrl = ZController(_CALIB_Z, _CALIB_DB, dt=0.01, kp=0.5, ki=0.0)
    ctrl.step(np.array([148.0, 0.0, 0.0]), 150.0)
    z2 = ctrl.step(np.array([149.0, 0.0, 0.0]), 150.0)
    expected = 0.20 + 0.003 + 0.5 * ctrl.s_cal * 1.0  # surface + z_ff(150) + Kp·e
    assert z2 == pytest.approx(expected)


def test_nan_guard_output_finite_and_rate_clamped():
    """g_d=NaN 走 guard 分支：输出必须有限（回退上一拍指令），且不跳变。

    审计 R2：旧 guard 在 g_d=NaN 时 np.interp(nan) 返回 NaN——"安全 z_cmd" 实为 NaN。"""
    ctrl = ZController(_CALIB_Z, _CALIB_DB, dt=0.01)
    z1 = ctrl.step(np.array([120.0, 0.0, 0.0]), 120.0)
    z2 = ctrl.step(np.array([120.0, 0.0, 0.0]), float("nan"))
    assert np.isfinite(z2)
    assert abs(z2 - z1) <= ctrl.dz_step_max + 1e-12
    assert ctrl.frozen
    # 首拍 g_d 就是 NaN（z_ff 反查得 NaN 且无历史可回退）→ 回退纸面高度
    ctrl2 = ZController(_CALIB_Z, _CALIB_DB, dt=0.01)
    z_first = ctrl2.step(np.array([120.0, 0.0, 0.0]), float("nan"))
    assert np.isfinite(z_first)
    assert z_first == pytest.approx(Z_SURFACE)


def test_reset_clears_rate_clamp_history():
    """reset 后视为新一段运行：首拍不受速率钳约束（允许直接落到目标附近）。"""
    ctrl = ZController(_CALIB_Z, _CALIB_DB, dt=0.01)
    ctrl.step(np.array([10.0, 0.0, 0.0]), 10.0)  # 悬空附近, z ≈ surface
    ctrl.reset()
    z = ctrl.step(np.array([100.0, 0.0, 0.0]), 250.0)
    assert z - Z_SURFACE > 1e-3  # 未被 0.2mm/拍 速率钳拖住
    assert z - Z_SURFACE <= ctrl.z_press_max + 1e-12  # 但绝对钳仍然有效


def test_calib_lookup_z_matches_controller_and_vectorizes():
    from brushbot.z_control import calib_lookup_z
    ctrl = ZController(_CALIB_Z, _CALIB_DB, dt=0.01)
    for g in (-10.0, 0.0, 75.0, 150.0, 999.0):
        assert calib_lookup_z(g, _CALIB_Z, _CALIB_DB) == pytest.approx(
            ctrl._z_ff_lookup(g))
    arr = calib_lookup_z(np.array([0.0, 150.0, 999.0]), _CALIB_Z, _CALIB_DB)
    np.testing.assert_allclose(arr, [0.0, 0.003, 0.005])
    # 非单调标定输入同样正确 (排序在函数内)
    shuffled = np.array([2, 0, 4, 1, 5, 3])
    assert calib_lookup_z(150.0, _CALIB_Z[shuffled], _CALIB_DB[shuffled]) \
        == pytest.approx(0.003)
