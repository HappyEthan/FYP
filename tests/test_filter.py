"""ButterworthFilter / OneEuroFilter 单测. 见 spec §6."""
import numpy as np
import pytest

from brushbot.filter import ButterworthFilter, OneEuroFilter


def run_scalar(filt, values):
    """标量序列复制成三通道跑滤波, 返回第 0 通道输出序列."""
    x = np.repeat(np.asarray(values, dtype=float)[:, None], 3, axis=1)
    return filt.update(x)[:, 0]


class TestButterworthFilter:
    def test_invalid_fc_raises(self):
        with pytest.raises(ValueError):
            ButterworthFilter(fc=0.0)
        with pytest.raises(ValueError):
            ButterworthFilter(fc=50.0)  # >= Nyquist

    def test_first_sample_no_jump(self):
        y = ButterworthFilter(fc=8.0).update(np.array([3.0, -2.0, 7.0]))
        np.testing.assert_allclose(y, [3.0, -2.0, 7.0])

    def test_dc_gain_unity(self):
        y = run_scalar(ButterworthFilter(fc=8.0), np.full(200, 5.0))
        assert y[-1] == pytest.approx(5.0, rel=1e-9)

    def test_minus3db_at_fc(self):
        h = ButterworthFilter(fc=8.0).freq_response(8.0)
        assert abs(h) == pytest.approx(1.0 / np.sqrt(2.0), abs=1e-6)

    def test_rolloff_12db_per_oct(self):
        f = ButterworthFilter(fc=4.0)
        # 16→32 Hz 一个倍频程, 理想衰减 4x, 双线性预畸变下放宽到 >3x
        assert abs(f.freq_response(16.0)) / abs(f.freq_response(32.0)) > 3.0

    def test_freq_response_matches_simulation(self):
        # 3 Hz 正弦稳态输出 == 解析频响预测 (同时验证 biquad 与 freq_response)
        f = ButterworthFilter(fc=8.0)
        t = np.arange(2000) / 100.0
        y = run_scalar(f, np.sin(2 * np.pi * 3.0 * t))
        h = f.freq_response(3.0)
        y_pred = np.abs(h) * np.sin(2 * np.pi * 3.0 * t + np.angle(h))
        np.testing.assert_allclose(y[1000:], y_pred[1000:], atol=1e-3)

    def test_step_settles_within_5pct(self):
        # 冷启动于 0, 样本 1 处阶跃到 1; fc=8 Hz 应在 100 ms (10 样本) 内进入 ±5%
        y = run_scalar(ButterworthFilter(fc=8.0),
                       np.concatenate([np.zeros(1), np.ones(99)]))
        assert np.all(np.abs(y[11:] - 1.0) <= 0.05)

    def test_batch_matches_single(self):
        rng = np.random.default_rng(0)
        x = rng.normal(size=(50, 3))
        fa, fb = ButterworthFilter(8.0), ButterworthFilter(8.0)
        ya = fa.update(x)
        yb = np.array([fb.update(xi) for xi in x])
        np.testing.assert_array_equal(ya, yb)

    def test_reset_cold_restart(self):
        f = ButterworthFilter(8.0)
        f.update(np.ones((10, 3)))
        f.reset()
        np.testing.assert_allclose(f.update(np.array([2.0, 2.0, 2.0])), 2.0)

    def test_nan_passthrough_state_intact(self):
        f = ButterworthFilter(8.0)
        f.update(np.full((20, 3), 4.0))
        out = f.update(np.array([np.nan, 4.0, 4.0]))
        assert np.isnan(out[0]) and out[1] == 4.0
        y = f.update(np.array([4.0, 4.0, 4.0]))
        np.testing.assert_allclose(y, 4.0, rtol=1e-6)

    def test_bad_shape_raises(self):
        with pytest.raises(ValueError):
            ButterworthFilter(8.0).update(np.zeros((3, 2)))


class TestOneEuroFilter:
    def test_invalid_params_raise(self):
        with pytest.raises(ValueError):
            OneEuroFilter(min_cutoff=0.0)
        with pytest.raises(ValueError):
            OneEuroFilter(min_cutoff=1.0, d_cutoff=0.0)

    def test_first_sample_no_jump(self):
        y = OneEuroFilter(1.0, 0.0).update(np.array([3.0, -2.0, 7.0]))
        np.testing.assert_allclose(y, [3.0, -2.0, 7.0])

    def test_static_noise_reduced(self):
        # 静止段 (min_cutoff=1 Hz, beta=0): 输出方差显著低于输入
        rng = np.random.default_rng(1)
        x = rng.normal(0.0, 1.0, size=(2000, 3))
        y = OneEuroFilter(min_cutoff=1.0, beta=0.0).update(x)
        assert y[500:].std() < 0.5 * x[500:].std()

    def test_adaptive_less_lag_when_fast(self):
        # beta>0 时对 100 µT/s 斜坡的稳态滞后应远小于 beta=0
        ramp = 100.0 * np.arange(300) / 100.0
        lag_fixed = ramp[-1] - run_scalar(OneEuroFilter(1.0, beta=0.0), ramp)[-1]
        lag_adapt = ramp[-1] - run_scalar(OneEuroFilter(1.0, beta=0.05), ramp)[-1]
        assert lag_adapt < 0.5 * lag_fixed

    def test_custom_dt_accepted(self):
        # 同一序列用 2 倍 dt 跑, 等效截止相同时收敛更快 (行为不同即可验证 dt 生效)
        f1, f2 = OneEuroFilter(1.0, 0.0), OneEuroFilter(1.0, 0.0)
        x = np.concatenate([np.zeros(1), np.ones(20)])
        y1 = run_scalar(f1, x)
        x3 = np.repeat(x[:, None], 3, axis=1)
        y2 = np.array([f2.update(xi, dt=0.02) for xi in x3])[:, 0]
        assert y2[10] > y1[10]  # 大 dt → 单步权重更大 → 收敛更快

    def test_batch_matches_single(self):
        rng = np.random.default_rng(2)
        x = rng.normal(size=(50, 3))
        fa, fb = OneEuroFilter(1.0, 0.03), OneEuroFilter(1.0, 0.03)
        ya = fa.update(x)
        yb = np.array([fb.update(xi) for xi in x])
        np.testing.assert_array_equal(ya, yb)

    def test_reset_cold_restart(self):
        f = OneEuroFilter(1.0, 0.03)
        f.update(np.ones((10, 3)))
        f.reset()
        np.testing.assert_allclose(f.update(np.array([2.0, 2.0, 2.0])), 2.0)

    def test_nan_passthrough_state_intact(self):
        f = OneEuroFilter(1.0, 0.0)
        f.update(np.full((20, 3), 4.0))
        out = f.update(np.array([np.nan, 4.0, 4.0]))
        assert np.isnan(out[0]) and out[1] == 4.0
        y = f.update(np.array([4.0, 4.0, 4.0]))
        np.testing.assert_allclose(y, 4.0, rtol=1e-6)

    def test_smoothing_alpha_range(self):
        a = OneEuroFilter.smoothing_alpha(1.0, 0.01)
        assert 0.0 < a < 1.0
