import numpy as np
import pytest

from brushbot.demo_pipeline import (DEMO_COLS, estimate_sigma, load_demo,
                                    segment_strokes, build_plan, reparam_arclength)
from brushbot.strokeplan import StrokePlan

FS = 100.0


def _write_csv(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        f.write(",".join(DEMO_COLS) + "\n")
        for r in rows:
            f.write(",".join("%.9g" % v for v in r) + "\n")


def _rows(n=100, dB=(1.0, 2.0, 3.0)):
    return [(i * 1e4, i * 0.01, *dB, 0.001 * i, 0.0) for i in range(n)]


def test_load_demo_ok(tmp_path):
    p = tmp_path / "demo.csv"
    _write_csv(p, _rows())
    d = load_demo(p)
    assert d["xy"].shape == (100, 2) and d["dB"].shape == (100, 3)
    assert d["dB"][0, 2] == pytest.approx(3.0)


def test_load_demo_missing_xy_columns(tmp_path):
    p = tmp_path / "v0_style.csv"
    with open(p, "w", encoding="utf-8") as f:
        f.write("t_us,t_s,dBx_uT,dBy_uT,dBz_uT\n0,0,1,2,3\n1,0.01,1,2,3\n")
    with pytest.raises(ValueError, match="x_m"):
        load_demo(p)


def test_load_demo_wrong_sample_rate_rejected(tmp_path):
    p = tmp_path / "demo_50hz.csv"
    rows = [(i * 2e4, i * 0.02, 1.0, 2.0, 3.0, 0.001 * i, 0.0) for i in range(100)]
    _write_csv(p, rows)
    with pytest.raises(ValueError, match="采样率"):
        load_demo(p)


def test_load_demo_nan_reports_row(tmp_path):
    p = tmp_path / "bad.csv"
    rows = _rows()
    rows[7] = (7e4, 0.07, float("nan"), 2.0, 3.0, 0.007, 0.0)
    _write_csv(p, rows)
    with pytest.raises(ValueError, match="9"):        # 表头 1 行 + 0 始下标 7 → 第 9 行
        load_demo(p)


def test_estimate_sigma_from_quiet_head():
    rng = np.random.default_rng(0)
    g = np.concatenate([np.abs(rng.normal(0, 2.0, 60)),
                        150.0 + rng.normal(0, 2.0, 400)])
    assert estimate_sigma(g, fs=FS, head_s=0.5) == pytest.approx(
        g[:50].std(), rel=1e-9)


def test_estimate_sigma_rejects_loud_head():
    rng = np.random.default_rng(1)
    g = np.abs(rng.normal(100.0, 40.0, 400))          # 一上来就在写
    with pytest.raises(ValueError, match="悬空"):
        estimate_sigma(g, fs=FS)


def test_segment_strokes_finds_runs_and_drops_short():
    sigma = 2.0                                        # 3σ = 6
    g = np.zeros(1000)
    g[100:400] = 100.0                                 # 笔 1: 3.0s
    g[500:520] = 100.0                                 # 过短 (0.2s < 0.3s) → 丢
    g[600:950] = 100.0                                 # 笔 2: 3.5s
    segs, dropped = segment_strokes(g, sigma, fs=FS, min_len_s=0.3)
    assert segs == [(100, 400), (600, 950)]
    assert dropped == 1


def test_segment_strokes_merges_chatter_and_scales_threshold():
    """(2026-07-31 三次修订) 阈值随信号规模缩放: 滤波旁瓣量级的游走不成 run;
    强信号的边界抖动并入主段."""
    sigma = 2.0                        # 3σ=6; p99≈200 → T=max(6, 10)=10
    g = np.zeros(1000)
    g[100:400] = 200.0
    g[404:412] = 200.0                 # 边界抖动: 间隙 4 拍 < merge_gap → 并入主段
    g[600:625] = 8.0                   # 旁瓣量级 (4% 峰值): 低于 T=10 → 不成 run
    segs, dropped = segment_strokes(g, sigma, fs=FS)
    assert segs == [(100, 412)]
    assert dropped == 0


_CAL_Z = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
_CAL_DB = np.array([0.0, 50.0, 100.0, 150.0, 250.0, 200.0])  # 故意乱序尾: 反查须容忍


def _g_true_s(s):
    """真值 g(s): 边缘 10% ramp + 中段正弦提按, 峰值 185 µT."""
    g = 125.0 + 60.0 * np.sin(2.0 * np.pi * 2.0 * s)
    return g * np.clip(np.minimum(s, 1.0 - s) / 0.1, 0.0, 1.0)


def _make_demo(speed_mod=0.5, seed=3, noise_std=2.0, n_strokes=2,
               stroke_s=3.0, gap_s=0.8):
    """合成示范 dict (带白噪声, 变速): 返回 (demo, s_grid, g_true(s_grid)).

    变速: s(t) = t + speed_mod·sin(2πt)/(2π), 单调; speed_mod=0 → 匀速."""
    rng = np.random.default_rng(seed)
    n, ngap = int(stroke_s * FS), int(gap_s * FS)
    tn = np.linspace(0.0, 1.0, n)
    s_of_t = tn + speed_mod * np.sin(2.0 * np.pi * tn) / (2.0 * np.pi)
    s_of_t = (s_of_t - s_of_t[0]) / (s_of_t[-1] - s_of_t[0])
    s_grid = np.linspace(0.0, 1.0, 400)
    # (2026-07-31 修正) 悬空段 XY 必须从上笔终点线性平移到下笔起点, 不许原地停住后瞬移:
    # 真实的手不会瞬移; 零相位滤波会把接触边界抹进悬空段一两拍, 切分段若裹进瞬移点,
    # 一步假弧长会吃掉大块 s 轴 (实测笔 1 恢复 RMS 98 µT 的根因).
    starts = [np.array([0.0, 0.01 * k]) for k in range(n_strokes)]
    ends = [np.array([0.04, 0.01 * k]) for k in range(n_strokes)]
    frac = np.linspace(0.0, 1.0, ngap)[:, None]
    g_parts = [np.zeros(ngap)]
    xy_parts = [np.tile(starts[0], (ngap, 1))]          # 初始悬空: 停在首笔起点
    for k in range(n_strokes):
        g_parts.append(np.interp(s_of_t, s_grid, _g_true_s(s_grid)))
        x = 0.04 * s_of_t
        y = np.full(n, 0.01 * k)
        xy_parts.append(np.column_stack([x, y]))
        nxt = starts[k + 1] if k + 1 < n_strokes else ends[k]
        g_parts.append(np.zeros(ngap))
        xy_parts.append(ends[k][None, :] * (1.0 - frac) + nxt[None, :] * frac)
    g = np.concatenate(g_parts)
    xy = np.vstack(xy_parts)
    direction = np.array([1.0, 0.3, 0.1]) / np.linalg.norm([1.0, 0.3, 0.1])
    dB = direction[None, :] * g[:, None] + rng.normal(0.0, noise_std, (len(g), 3))
    t = np.arange(len(g)) / FS
    return {"t": t, "xy": xy, "dB": dB}, s_grid, _g_true_s(s_grid)


def _true_s(st):
    """几何真值 s: _make_demo 的笔画是 x=0.04·s 的直线, 故 x/0.04 精确给出每个
    恢复样本的真实 s —— 不依赖"恢复段支撑 == 真值支撑"假设 (边界内缩后两者必然不同)."""
    return np.clip(st.xy[:, 0] / 0.04, 0.0, 1.0)


def _geom_rms(st, lo=0.1, hi=0.9):
    """恢复 g_press vs 几何对齐真值的内部区间 RMS."""
    ts = _true_s(st)
    m = (ts >= lo) & (ts <= hi)
    return float(np.sqrt(np.mean((st.g_press[m] - _g_true_s(ts[m])) ** 2)))


def _on_true_grid(st, grid):
    """恢复 g_press 重采样到几何真值 s 网格. argsort 是单调性防御: 强滤波
    (如 fc=3) 下段边界残留的悬空移动样本会使 ts 折返, 乱序结点让 np.interp 出
    垃圾; 本测试的 fc=10 下 ts 本就单调, 排序为 no-op. 残留样本的影响由
    边界内缩 (build_plan trim) 和网格裁剪共同控制, 排序本身不构成排除机制."""
    ts = _true_s(st)
    idx = np.argsort(ts)
    return np.interp(grid, ts[idx], st.g_press[idx])


def test_reparam_arclength_uniform_grid_and_short_arc():
    n = 100
    xy = np.column_stack([np.linspace(0.0, 0.04, n), np.zeros(n)])
    s, xy_s, g_s = reparam_arclength(xy, np.linspace(0.0, 1.0, n), M=50)
    np.testing.assert_allclose(s, np.linspace(0.0, 1.0, 50))
    np.testing.assert_allclose(xy_s[:, 0], 0.04 * s, atol=1e-12)
    with pytest.raises(ValueError, match="1mm"):
        reparam_arclength(np.zeros((50, 2)), np.ones(50), M=10)


def test_build_plan_segments_and_recovers_truth():
    """恢复精度 (spec Q1 单测版): 带噪变速示范 → 逐笔几何对齐 RMS ≤ 3 µT."""
    demo, s_grid, g_true = _make_demo(speed_mod=0.5)
    plan = build_plan(demo, _CAL_Z, _CAL_DB)
    assert len(plan.strokes) == 2
    assert plan.meta["edge_trim_s"] == pytest.approx(0.17)
    for st in plan.strokes:
        assert _geom_rms(st) <= 3.0
        assert (st.z_ff >= 0.0).all() and (st.z_ff <= 0.005).all()
    # (2026-07-31 恢复) 噪声毛刺由 segment_strokes 的合并+幅度门吸收, 不再污染丢弃计数
    assert plan.meta["n_dropped_short"] == 0 and plan.meta["sat_frac"] == 0.0


def test_speed_invariance():
    """速度解耦 (spec Q2 单测版): 匀速 vs 变速恢复互差 ≤ 1 µT (几何网格上比).

    用 fc=10 弱滤波隔离"时域滤波×速度"耦合 (fc=3 下写快的段被滤得更狠, 互差
    ~2.4 µT——那是全管线固有属性而非重参数化缺陷, 由 E2E 如实报告, spec §8.5).
    本测试只考弧长重参数化本身."""
    d_uni, _, _ = _make_demo(speed_mod=0.0, seed=5, noise_std=0.5)
    d_var, _, _ = _make_demo(speed_mod=0.5, seed=5, noise_std=0.5)
    p_uni = build_plan(d_uni, _CAL_Z, _CAL_DB, fc=10.0)
    p_var = build_plan(d_var, _CAL_Z, _CAL_DB, fc=10.0)
    grid = np.linspace(0.1, 0.9, 200)
    for a, b in zip(p_uni.strokes, p_var.strokes):
        diff = _on_true_grid(a, grid) - _on_true_grid(b, grid)
        assert float(np.sqrt(np.mean(diff ** 2))) <= 1.0


def test_build_plan_saturation_counted():
    demo, _, _ = _make_demo(noise_std=0.5)
    small_cal = np.array([0.0, 50.0, 100.0])            # 上界 100 < 峰值 185
    plan = build_plan(demo, np.array([0.0, 1.0, 2.0]), small_cal)
    assert plan.meta["sat_frac"] > 0.05
    for st in plan.strokes:
        assert st.z_ff.max() <= 0.002 + 1e-12           # 饱和到最大压深


def test_build_plan_meta_stroke_durations():
    """R15: build_plan 把逐笔实际接触时长 (边界内缩后) 写进 meta —
    spec §8.5 "示范速度≈执行速度" 硬要求的落点, 回放不再靠调用方硬编码."""
    demo, _, _ = _make_demo(speed_mod=0.5)
    plan = build_plan(demo, _CAL_Z, _CAL_DB)
    durs = plan.meta["stroke_durations_s"]
    assert len(durs) == len(plan.strokes) == 2
    trim = plan.meta["edge_trim_s"]
    for d in durs:
        assert 0.3 <= d <= 5.0            # 合成示范笔画量级, 且为裁剪后净时长
    # 与 to_gd_series(None) 打通: 不传时长即按示范速度回放
    g_d, _ = plan.to_gd_series(None)
    assert len(g_d) == sum(int(round(d * 100.0)) + 50 for d in durs)
