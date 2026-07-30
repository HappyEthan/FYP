from pathlib import Path

import numpy as np
import pytest

from brushbot.monitor.core import EMA
from brushbot.sim_loop import FS, Plant, V0NoiseSource, load_deltab_csv

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
