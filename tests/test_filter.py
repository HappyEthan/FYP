"""ButterworthFilter / OneEuroFilter 单测. 见 spec §6."""
import numpy as np
import pytest

from brushbot.filter import ButterworthFilter


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
