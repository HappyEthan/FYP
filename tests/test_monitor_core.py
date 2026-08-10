import numpy as np
import pytest
from brushbot.monitor.core import EMA, RingBuffer, Baseline, derive


def test_ringbuffer_keeps_latest_when_overflowing():
    rb = RingBuffer(capacity=3)
    for i in range(5):
        rb.append(float(i), (i * 1.0, i * 2.0, i * 3.0))
    t, B = rb.latest(3)
    assert rb.n_total == 5
    assert t.tolist() == [2.0, 3.0, 4.0]
    assert B[:, 0].tolist() == [2.0, 3.0, 4.0]
    assert B[-1].tolist() == [4.0, 8.0, 12.0]


def test_ringbuffer_latest_clamps_to_available():
    rb = RingBuffer(capacity=10)
    rb.append(0.0, (1.0, 2.0, 3.0))
    t, B = rb.latest(5)
    assert t.shape == (1,) and B.shape == (1, 3)


def test_baseline_take_and_apply():
    bl = Baseline()
    assert bl.ready is False
    B = np.array([[10.0, 20.0, 30.0], [12.0, 22.0, 34.0]])
    bl.take(B)
    assert bl.ready is True
    assert bl.b0.tolist() == [11.0, 21.0, 32.0]
    out = bl.apply(np.array([[11.0, 21.0, 32.0]]))
    assert out.tolist() == [[0.0, 0.0, 0.0]]


def test_baseline_take_sigma_only_keeps_b0():
    """update_b0=False: 只刷新 sigma, 保留原 b0.

    回放源要的就是这个——记录自带的 b0 必须原样保留(否则回放不再逐点复现
    原始 ΔB), 但方向门控仍需要一份真实测得的 sigma。
    """
    bl = Baseline()
    bl.b0 = np.array([100.0, 200.0, 300.0])          # 记录自带的基线
    bl.take(np.array([[-1.0, -1.0, -1.0], [1.0, 1.0, 1.0]]), update_b0=False)
    assert bl.b0.tolist() == [100.0, 200.0, 300.0]   # 未被覆盖
    assert np.allclose(bl.sigma, [1.0, 1.0, 1.0])    # sigma 已更新
    assert bl.ready is True


def test_baseline_sigma_norm():
    bl = Baseline()
    # 每轴取 [-1, 1] → 总体标准差 = 1.0 每轴 → 模 = sqrt(3)
    B = np.array([[-1.0, -1.0, -1.0], [1.0, 1.0, 1.0]])
    bl.take(B)
    assert np.allclose(bl.sigma, [1.0, 1.0, 1.0])
    assert bl.sigma_norm == pytest.approx(np.sqrt(3.0))


def test_derive_above_gate():
    d = derive(np.array([3.0, 4.0, 0.0]), gate=1.0)
    assert d["mag"] == pytest.approx(5.0)
    assert d["mag_xy"] == pytest.approx(5.0)
    assert d["phi_deg"] == pytest.approx(np.degrees(np.arctan2(4.0, 3.0)))
    assert d["theta_deg"] == pytest.approx(90.0)


def test_derive_below_gate_returns_none_direction():
    d = derive(np.array([0.1, 0.1, 0.1]), gate=100.0)
    assert d["mag"] == pytest.approx(np.sqrt(0.03))
    assert d["phi_deg"] is None
    assert d["theta_deg"] is None


# ---------------------------------------------------------------- EMA NaN 策略
# EMA 是控制环定稿滤波器 (α=0.3), NaN 策略必须与 filter.py 一致:
# 含非有限值的样本原样透传且不更新内部状态 (审计 R2: 旧实现一个 NaN 永久毒化).


def test_ema_nan_passthrough_state_not_poisoned():
    f = EMA(0.3)
    f.update(np.array([10.0, 0.0, 0.0]))
    f.update(np.array([10.0, 0.0, 0.0]))
    y_bad = f.update(np.array([np.nan, 0.0, 0.0]))
    assert np.isnan(y_bad[0]) and y_bad[1] == 0.0  # 原样透传
    y_after = f.update(np.array([10.0, 0.0, 0.0]))
    assert np.all(np.isfinite(y_after)), "NaN 拍后状态被永久毒化"
    # 状态确实未被 NaN 拍更新: 与从未见过 NaN 的参照滤波器逐位一致
    ref = EMA(0.3)
    ref.update(np.array([10.0, 0.0, 0.0]))
    ref.update(np.array([10.0, 0.0, 0.0]))
    y_ref = ref.update(np.array([10.0, 0.0, 0.0]))
    np.testing.assert_allclose(y_after, y_ref)


def test_ema_nan_batch_rows_isolated():
    """(N,3) 批量输入: NaN 行透传, 后续行正常滤波不受污染."""
    f = EMA(0.5)
    batch = np.array([[10.0, 0.0, 0.0],
                      [np.nan, np.nan, np.nan],
                      [20.0, 0.0, 0.0]])
    out = f.update(batch)
    assert np.all(np.isfinite(out[0]))
    assert np.all(np.isnan(out[1]))
    np.testing.assert_allclose(out[2], [15.0, 0.0, 0.0])  # 0.5·20 + 0.5·10
