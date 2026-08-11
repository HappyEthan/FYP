from pathlib import Path

import numpy as np
import pytest

from brushbot.filter import OneEuroFilter
from brushbot.monitor.core import EMA
from brushbot.sim_loop import (FS, Plant, V0NoiseSource, diverged, freeze_jump,
                               load_deltab_csv, osc_index, press_from_v0, rms_pct,
                               run_loop, synth_press)
from brushbot.z_control import ZController

ROOT = Path(__file__).resolve().parents[1]
IDLE_CSVS = sorted(p for p in (ROOT / "delta_b_v0_20260724").glob("*.csv")
                   if "idle" in p.stem)

needs_v0 = pytest.mark.skipif(not IDLE_CSVS, reason="V0 idle data not present")


@needs_v0
def test_noise_source_sigma_matches_pool():
    """回放样本的 |σ| 与样本池一致 (它就是池子的切片)。"""
    src = V0NoiseSource(IDLE_CSVS, seed=0)
    pool = np.vstack([load_deltab_csv(p) for p in IDLE_CSVS])
    pool = pool - pool.mean(axis=0)
    sigma_pool = float(np.linalg.norm(pool.std(axis=0)))
    assert src.filtered_sigma(None) == pytest.approx(sigma_pool, rel=1e-9)


@needs_v0
def test_noise_source_seed_reproducible():
    a = V0NoiseSource(IDLE_CSVS, seed=7).sample(500)
    b = V0NoiseSource(IDLE_CSVS, seed=7).sample(500)
    np.testing.assert_array_equal(a, b)
    c = V0NoiseSource(IDLE_CSVS, seed=8).sample(500)
    assert not np.array_equal(a, c)


@needs_v0
def test_noise_source_contiguous_and_wraps():
    """跨调用连续 (1/f 谱保真的前提); 超池长时镜像延拓不报错。"""
    src = V0NoiseSource(IDLE_CSVS, seed=1)
    a = np.vstack([src.sample(100), src.sample(100)])
    src2 = V0NoiseSource(IDLE_CSVS, seed=1)
    b = src2.sample(200)
    np.testing.assert_array_equal(a, b)
    pool_len = len(np.vstack([load_deltab_csv(p) for p in IDLE_CSVS]))
    big = V0NoiseSource(IDLE_CSVS, seed=2).sample(pool_len * 2 + 17)
    assert big.shape == (pool_len * 2 + 17, 3) and np.isfinite(big).all()


@needs_v0
def test_noise_source_low_freq_dominates():
    """idle 噪声是 1/f 形: 低频段功率 > 高频段 (回放保真粗检)。"""
    x = V0NoiseSource(IDLE_CSVS, seed=3).sample(4000)[:, 2]
    P = np.abs(np.fft.rfft(x - x.mean())) ** 2
    f = np.fft.rfftfreq(len(x), d=1.0 / FS)
    assert P[(f > 0) & (f < 5)].sum() > P[f > 40].sum()


@needs_v0
def test_filtered_sigma_reduced_by_filter():
    src = V0NoiseSource(IDLE_CSVS, seed=0)
    assert src.filtered_sigma(lambda: EMA(0.3)) < src.filtered_sigma(None)


_CAL_Z = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
_CAL_DB = np.array([0.0, 50.0, 100.0, 150.0, 200.0, 250.0])
Z_SURF = 0.20


def _settle(plant, z_cmd, n=200):
    for _ in range(n):
        out = plant.step(z_cmd)
    return out


def test_plant_steady_state_matches_calib():
    plant = Plant(_CAL_Z, _CAL_DB)
    _settle(plant, Z_SURF + 2.0e-3)
    assert plant.abs_true == pytest.approx(100.0, rel=1e-3)


def test_plant_calib_scale():
    plant = Plant(_CAL_Z, _CAL_DB, calib_scale=1.2)
    _settle(plant, Z_SURF + 2.0e-3)
    assert plant.abs_true == pytest.approx(120.0, rel=1e-3)


def test_plant_paper_step_shifts_depth():
    plant = Plant(_CAL_Z, _CAL_DB, paper_step=(1.0, +0.5e-3))
    _settle(plant, Z_SURF + 2.0e-3, n=90)      # t<1s: 未触发
    assert plant.abs_true == pytest.approx(100.0, rel=1e-2)
    _settle(plant, Z_SURF + 2.0e-3, n=200)     # t>1s: 深 0.5mm
    assert plant.abs_true == pytest.approx(125.0, rel=1e-3)


def test_plant_drift_ramp():
    plant = Plant(_CAL_Z, _CAL_DB, drift_rate=2.0)
    out = _settle(plant, Z_SURF, n=100)        # 悬空 1s, 漂移 ~2 µT
    assert np.linalg.norm(out) == pytest.approx(2.0, abs=0.1)


def test_plant_delay_and_tau_timing():
    plant = Plant(_CAL_Z, _CAL_DB, tau=0.05, n_delay=2)
    for _ in range(2):                          # FIFO 排空前不动
        plant.step(Z_SURF + 2.0e-3)
        assert plant.z_act == pytest.approx(Z_SURF)
    for _ in range(5):                          # τ=50ms → 5拍≈1τ → ~63%
        plant.step(Z_SURF + 2.0e-3)
    frac = (plant.z_act - Z_SURF) / 2.0e-3
    assert 0.55 < frac < 0.72


def test_plant_noise_added():
    src = V0NoiseSource(IDLE_CSVS, seed=0) if IDLE_CSVS else None
    if src is None:
        pytest.skip("V0 idle data not present")
    plant = Plant(_CAL_Z, _CAL_DB, noise=src)
    outs = np.array([np.linalg.norm(plant.step(Z_SURF)) for _ in range(500)])
    assert outs.std() > 1.0                     # 悬空但有噪声起伏


def test_synth_press_structure():
    g = synth_press(cal_max=250.0)
    assert len(g) == int((0.5 + 0.3 + 6.0 + 0.3 + 0.5) * FS)
    assert g[0] == 0.0 and g[-1] == 0.0                    # 首尾悬空
    assert g.max() <= 0.8 * 250.0 + 1e-9                   # base+depth = 0.8·cal_max
    assert g.min() >= 0.0
    press = g[int(0.8 * FS):int(6.8 * FS)]                 # 提按段
    assert press.min() >= 0.2 * 250.0 - 1e-9               # base−depth, 不离纸
    sigma3 = 3 * 2.7                                       # 代表性 3σ 阈值
    assert (g < sigma3).any() and (g > sigma3).any()       # 穿越 freeze 阈值


def test_press_from_v0_zero_phase_norm():
    if not IDLE_CSVS:
        pytest.skip("V0 data not present")
    dyn = sorted(p for p in (ROOT / "delta_b_v0_20260724").glob("*.csv")
                 if "idle" not in p.stem)
    if not dyn:
        pytest.skip("V0 dynamic (non-idle) data not present")
    g = press_from_v0(dyn[0])
    raw = np.linalg.norm(load_deltab_csv(dyn[0]), axis=1)
    assert g.shape == raw.shape and np.isfinite(g).all()
    assert g.std() < raw.std()                             # 滤过更平滑


def _make(kp=0.3, ki=0.03, noise=None, **plant_kw):
    ctrl = ZController(_CAL_Z, _CAL_DB, kp=kp, ki=ki, noise_std=7.0)
    plant = Plant(_CAL_Z, _CAL_DB, noise=noise, **plant_kw)
    return ctrl, plant


def test_run_loop_open_arm_is_pure_feedforward():
    """开环臂 (kp=ki=0): z_fb≡0 且 z_cmd = z_surface + z_ff 逐点成立。

    注: res["z_ff"] 是 ZController.z_ff 属性 = 前馈 offset (m), 不含 z_surface。"""
    ctrl, plant = _make(kp=0.0, ki=0.0)
    g = synth_press(cal_max=250.0)
    res = run_loop(ctrl, None, g, plant)
    np.testing.assert_allclose(res["z_cmd"], 0.20 + res["z_ff"], atol=1e-12)


def test_run_loop_deterministic_same_seed():
    g = synth_press(cal_max=250.0)
    outs = []
    for _ in range(2):
        ctrl, plant = _make(noise=V0NoiseSource(IDLE_CSVS, seed=5)) if IDLE_CSVS \
            else _make()
        outs.append(run_loop(ctrl, OneEuroFilter(0.5, 0.03), g, plant))
    np.testing.assert_array_equal(outs[0]["z_cmd"], outs[1]["z_cmd"])


def test_run_loop_nan_chain_reaches_guard():
    """NaN 从 plant → 滤波透传 → 控制器 freeze 且 z_cmd 有限 (guard 链路)。"""
    class _NaNPlant:
        z_act, abs_true = 0.2, 0.0
        def __init__(self):
            self.k = 0
        def step(self, z_cmd):
            self.k += 1
            return np.full(3, np.nan) if self.k == 50 else np.array([100.0, 0.0, 0.0])
    ctrl = ZController(_CAL_Z, _CAL_DB)
    res = run_loop(ctrl, OneEuroFilter(0.5, 0.03), np.full(100, 150.0), _NaNPlant())
    assert np.isnan(res["abs_f"][49])
    assert np.isfinite(res["z_cmd"]).all()
    assert res["frozen"][49]


def test_run_loop_closed_loop_converges_constant():
    """恒定目标 + 出厂默认增益(真实签名默认, 不显式传) + 现实 plant: 末段误差 <5% —— 默认增益收敛性的唯一属主测试。"""
    ctrl = ZController(_CAL_Z, _CAL_DB, noise_std=7.0)
    plant = Plant(_CAL_Z, _CAL_DB)
    res = run_loop(ctrl, None, np.full(300, 120.0), plant)
    tail = res["abs_true"][-50:]
    assert abs(tail.mean() - 120.0) / 120.0 < 0.05


def test_metrics_contract():
    res = {"g_d": np.array([0.0, 100.0, 100.0, 0.0]),
           "abs_true": np.array([0.0, 90.0, 110.0, 50.0]),
           "z_cmd": np.array([0.2, 0.201, 0.2, 0.201]),
           "frozen": np.array([True, False, False, True])}
    r = rms_pct(res, noise_std=7.0)                       # 接触段 = g_d≥21 的中间两点
    assert r == pytest.approx(np.sqrt((100.0 + 100.0) / 2) / 100.0 * 100.0)
    assert 0.0 <= osc_index(res) <= 1.0
    assert freeze_jump(res) == pytest.approx(1e-3)
    assert not diverged(res, 0.2, 0.005)
    bad = dict(res, z_cmd=np.array([0.2, 0.3, 0.2, 0.2]))
    assert diverged(bad, 0.2, 0.005)                      # 偏 0.1m > 2×5mm
