import numpy as np
import pytest
from brushbot.monitor.core import RingBuffer, Baseline, derive


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
