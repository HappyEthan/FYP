from pathlib import Path

import numpy as np
import pytest

from brushbot.monitor.core import EMA
from brushbot.sim_loop import FS, V0NoiseSource, load_deltab_csv

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
