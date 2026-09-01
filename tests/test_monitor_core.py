import numpy as np
import pytest
from brushbot.monitor.core import (EMA, RingBuffer, Baseline, derive,
                                   normalize_symmetric, fit_whitening, filter_bad_frames)


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


# ---------------------------------------------------------------- 每轴归一化


def test_normalize_symmetric_zero_at_center():
    """对称 ±R: ΔB=0(零点/基线) 必须落在圆心 0."""
    R = 100.0
    got = normalize_symmetric(np.array([0.0, 0.0]), [R, R])
    np.testing.assert_allclose(got, [0.0, 0.0])


def test_normalize_symmetric_map_full_to_edge():
    """对称 ±R: 满压 ±R 各到 ±1 边缘, 超出被截断."""
    R = np.array([100.0, 50.0])
    got = normalize_symmetric(np.array([[100.0, 50.0], [-100.0, -50.0], [1000.0, 1000.0]]), R)
    np.testing.assert_allclose(got[0], [1.0, 1.0])
    np.testing.assert_allclose(got[1], [-1.0, -1.0])
    np.testing.assert_allclose(got[2], [1.0, 1.0])  # 超界截断


def test_normalize_symmetric_per_axis_radius():
    """每轴对称半径独立: x 半径大, y 半径小."""
    R = np.array([200.0, 50.0])          # 不对称半径
    dB = np.array([[-100.0, 25.0]])       # ΔBx=-0.5R, ΔBy=+0.5R
    got = normalize_symmetric(dB, R)
    np.testing.assert_allclose(got, [[-0.5, 0.5]])


def test_normalize_symmetric_zero_radius():
    """R<=0 → 全 0, 无除零."""
    got = normalize_symmetric(np.array([5.0, -5.0]), [0.0, 0.0])
    np.testing.assert_allclose(got, [0.0, 0.0])


def test_baseline_normalize_xy_symmetric():
    bl = Baseline()
    dB = np.array([[0.0, 0.0, 0.0], [20.0, -10.0, 0.0]])  # 零点 + 满压
    bl.set_norm_radius([40.0, 20.0])
    assert bl.norm_ready is True
    n = bl.normalize_xy(dB)
    np.testing.assert_allclose(n[0], [0.0, 0.0])     # 零点 → 圆心
    np.testing.assert_allclose(n[1], [0.5, -0.5])    # 满压 → 半径一半


def test_baseline_normalize_xy_zero_point_is_center_even_asym():
    """正负满压不对称时, 用较大半径, 零点仍在圆心(核心需求)."""
    bl = Baseline()
    # +X 满压 ΔBx=+100, −X 满压 ΔBx=−140 → 半径取 140
    bl.set_norm_radius([max(100, 140), max(80, 50)])   # R=(140, 80)
    dB = np.array([[0.0, 0.0, 0.0], [100.0, 80.0, 0.0], [-140.0, -50.0, 0.0]])
    n = bl.normalize_xy(dB)
    np.testing.assert_allclose(n[0], [0.0, 0.0])              # 零点圆心
    np.testing.assert_allclose(n[1], [100/140, 80/80])        # +X 压 → 不到边缘
    np.testing.assert_allclose(n[2], [-1.0, -50/80])          # −X 满压 → 恰好左边缘


def test_baseline_normalize_xy_overall_radius():
    """单一整体半径(每轴同值 R): 物理转圈最远端(幅= R)落到圆边缘, 与轴向无关."""
    bl = Baseline()
    R = 100.0
    bl.set_norm_radius([R, R])                    # 整体半径
    # 任意方向, 只要 |ΔBxy| = R 就到圆边缘
    dB = np.array([[60.0, 80.0, 0.0]])             # hypot = 100 = R
    n = bl.normalize_xy(dB)
    assert np.allclose(n[0], [0.6, 0.8])
    assert np.hypot(*n[0]) == pytest.approx(1.0)   # 幅值=1 → 恰好圆边缘
    # 对角方向也验证
    d2 = np.array([[-70.71, -70.71, 0.0]])         # hypot ≈ 100
    n2 = bl.normalize_xy(d2)
    assert np.hypot(*n2[0]) == pytest.approx(1.0, abs=1e-3)


def test_baseline_normalize_xy_fallback_legacy():
    bl = Baseline()
    dB = np.array([[50.0, -40.0, 0.0]])
    n = bl.normalize_xy(dB, fallback_radius=100.0)
    np.testing.assert_allclose(n[0], [0.5, -0.4])
    # 无半径 → 全 0
    n0 = bl.normalize_xy(dB)
    np.testing.assert_allclose(n0, [[0.0, 0.0]])


def test_baseline_clear_norm():
    bl = Baseline()
    bl.set_norm_matrix(np.eye(2), 40.0)
    bl.clear_norm()
    assert bl.norm_ready is False
    n = bl.normalize_xy(np.array([[10.0, 10.0, 0.0]]), fallback_radius=20.0)
    np.testing.assert_allclose(n, [[0.5, 0.5]])


# ---------------------------------------------------------------- 椭圆白化(各向同性化)


def test_fit_whitening_circle_identity():
    """输入已是圆(各向同性) → 白化后方差应各向同性(cov≈I)."""
    rng = np.random.default_rng(0)
    th = rng.uniform(0, 2 * np.pi, 4000)
    d = np.column_stack([np.cos(th), np.sin(th)]) * 300.0   # 正圆 R=300
    W, R = fit_whitening(d)
    # 白化后应各向同性: cov≈I, R 为白化后基准幅度(>0)
    assert R > 0
    # 白化后应接近各向同性: cov ≈ I
    whitened = d @ W.T
    Cw = np.cov(whitened.T)
    ev = np.linalg.eigh(Cw)[0]
    assert ev[0] > 0
    ratio = np.sqrt(ev[1] / ev[0])
    assert ratio < 1.5, f"圆输入被错误放大各向异性: 比 {ratio:.2f}"


def test_fit_whitening_ellipse_isotropizes():
    """椭圆输入(各向异性) → 白化后方差各向同性(长短比≈1)."""
    rng = np.random.default_rng(1)
    th = rng.uniform(0, 2 * np.pi, 8000)
    # 构造各向异性: x 轴放大 2 倍 → 椭圆长短比≈2
    d = np.column_stack([2.0 * np.cos(th), 1.0 * np.sin(th)]) * 200.0
    W, R = fit_whitening(d)
    # 白化后样本应该是圆(各向同性)
    whitened = d @ W.T
    Cw = np.cov(whitened.T)
    ev = np.linalg.eigh(Cw)[0]
    ratio = np.sqrt(ev[1] / max(ev[0], 1e-12))
    assert ratio < 1.2, f"白化后仍各向异性: 长短比 {ratio:.2f}"
    # 点应落在单位圆内(R 内), 且 R≈各向同性半径
    assert R > 0


def test_baseline_normalize_xy_whitened():
    """Baseline.set_norm_matrix(W,R) → normalize_xy 用白化矩阵."""
    rng = np.random.default_rng(2)
    th = rng.uniform(0, 2 * np.pi, 6000)
    d = np.column_stack([2.0 * np.cos(th), 1.0 * np.sin(th)]) * 200.0
    bl = Baseline()
    W, R = fit_whitening(d)
    bl.set_norm_matrix(W, R)
    assert bl.norm_ready is True
    # 等幅物理形变(沿各方向) → 归一化后点到圆心距离应近似恒定(圆)
    test_th = np.linspace(0, 2 * np.pi, 64)
    ring = np.column_stack([2.0 * np.cos(test_th), 1.0 * np.sin(test_th)]) * 200.0
    n = bl.normalize_xy(np.column_stack([ring, np.zeros(len(ring))]))
    dist = np.hypot(n[:, 0], n[:, 1])
    # 各方向距离应该较一致(变异系数小), 大部分≈1(p99半径, 允许个别略超)
    assert dist.max() < 1.05
    cv = dist.std() / max(dist.mean(), 1e-9)
    assert cv < 0.3, f"各向异性未矫正, 距离变异系数 {cv:.2f}"


def test_filter_bad_frames_removes_spikes():
    """坏帧滤波: 个别爆表毛刺被剔除, 正常样本保留."""
    good = np.array([[300.0, 100.0], [-200.0, 300.0], [150.0, -150.0]])
    spike = np.array([[695250.0, 500.0]])      # 离群毛刺
    sample = np.vstack([good, spike])
    clean, mask = filter_bad_frames(sample)
    assert len(clean) == len(good)
    assert mask.tolist() == [True, True, True, False]
    np.testing.assert_allclose(clean, good)


def test_filter_bad_frames_keeps_clean():
    d = np.array([[10.0, 20.0], [30.0, 40.0], [15.0, 25.0]])
    clean, mask = filter_bad_frames(d)
    assert mask.all()


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
