import numpy as np
import pytest

from brushbot.strokeplan import FS, Stroke, StrokePlan


def _stroke(m=50, seed=0):
    rng = np.random.default_rng(seed)
    s = np.linspace(0.0, 1.0, m)
    return Stroke(s=s, xy=rng.normal(0.02, 0.01, (m, 2)),
                  g_press=rng.uniform(0.0, 200.0, m),
                  z_ff=rng.uniform(0.0, 0.005, m))


def _plan2():
    return StrokePlan(strokes=[_stroke(seed=1), _stroke(seed=2)],
                      meta={"fc": 3.0, "M": 50, "sigma": 2.5})


def test_npz_roundtrip(tmp_path):
    plan = _plan2()
    p = tmp_path / "plan.npz"
    plan.save(p)
    back = StrokePlan.load(p)
    assert len(back.strokes) == 2
    for a, b in zip(plan.strokes, back.strokes):
        np.testing.assert_array_equal(a.s, b.s)
        np.testing.assert_array_equal(a.xy, b.xy)
        np.testing.assert_array_equal(a.g_press, b.g_press)
        np.testing.assert_array_equal(a.z_ff, b.z_ff)
    assert back.meta == plan.meta


def test_empty_plan_roundtrip(tmp_path):
    p = tmp_path / "empty.npz"
    StrokePlan(strokes=[], meta={}).save(p)
    assert StrokePlan.load(p).strokes == []


def test_waypoints_structure():
    """B1/物理世界帧 (审计 R3 修正): 压笔 = 纸面下 (z_surface − z_ff), 抬笔 = 纸面上."""
    plan = _plan2()
    wps = plan.to_waypoints(z_surface=0.20, lift=0.015, origin=None)
    m = len(plan.strokes[0].s)
    assert len(wps) == 2 * (m + 2)                      # 每笔: 进入 + M + 抬笔
    x0, y0 = plan.strokes[0].xy[0]
    assert wps[0] == pytest.approx((x0, y0, 0.215))     # 悬空进入点 (纸面上)
    assert wps[1][2] == pytest.approx(0.20 - plan.strokes[0].z_ff[0])  # 压 = 纸面下
    assert wps[m + 1][2] == pytest.approx(0.215)        # 抬笔点
    zs = np.array([w[2] for w in wps])
    assert (zs >= 0.20 - 0.005 - 1e-12).all() and (zs <= 0.215 + 1e-12).all()
    press = np.array([w[2] for w in wps[1:m + 1]])
    assert (press <= 0.20 + 1e-12).all(), "压笔点必须不高于纸面 (旧 z 符号 bug: 全在纸面上)"


def test_waypoints_origin_translation():
    """origin 帧变换 (审计 R3): 示范原始坐标平移到书写平面可达中心."""
    from brushbot import config
    plan = _plan2()
    xy = np.array([(x, y) for x, y, _ in plan.to_waypoints(origin=(0.45, 0.0))])
    center = (xy.min(axis=0) + xy.max(axis=0)) / 2.0
    np.testing.assert_allclose(center, (0.45, 0.0), atol=1e-9)
    # 默认 origin = config.CHAR_ORIGIN (臂可达); origin=None 保留示范原始坐标
    xy_default = np.array([(x, y) for x, y, _ in plan.to_waypoints()])
    center_default = (xy_default.min(axis=0) + xy_default.max(axis=0)) / 2.0
    np.testing.assert_allclose(center_default, config.CHAR_ORIGIN, atol=1e-9)
    xy_raw = np.array([(x, y) for x, y, _ in plan.to_waypoints(origin=None)])
    center_raw = (xy_raw.min(axis=0) + xy_raw.max(axis=0)) / 2.0
    assert np.abs(center_raw - np.asarray(config.CHAR_ORIGIN)).max() > 0.1


def test_gd_series_uses_stored_durations():
    """R15: meta 存逐笔时长后 to_gd_series(None) 默认按存储时长回放 (spec §8.5 硬要求落点)."""
    plan = _plan2()
    plan.meta["stroke_durations_s"] = [1.0, 2.0]
    g_d, xy = plan.to_gd_series(None, fs=100.0, gap_s=0.5)
    assert len(g_d) == len(xy) == (100 + 50) + (200 + 50)
    g2, _ = plan.to_gd_series(2.0, fs=100.0, gap_s=0.5)   # 显式标量覆盖存储值
    assert len(g2) == 2 * 250
    with pytest.raises(ValueError, match="stroke_durations_s"):
        _plan2().to_gd_series(None)                        # 无存储时长 + 不传 → fail loud


def test_npz_saves_format_version_and_durations(tmp_path):
    """R15: npz 带格式版本号; 逐笔时长随 meta 无损往返."""
    plan = _plan2()
    plan.meta["stroke_durations_s"] = [1.5, 2.5]
    p = tmp_path / "v2.npz"
    plan.save(p)
    with np.load(p, allow_pickle=False) as d:
        assert int(d["format_version"]) == 2
    assert StrokePlan.load(p).meta["stroke_durations_s"] == [1.5, 2.5]


def test_open_z_series_from_stored_zff():
    """R6: 开环臂 z 序列由存储的 z_ff 字段插值生成 — 两臂共享前馈由数据结构保证.

    z-control 帧 (压深正向): 笔内 z = z_surface + interp(z_ff), 悬空段 = z_surface."""
    plan = _plan2()
    g_d, _ = plan.to_gd_series(2.0)
    z = plan.to_open_z_series(2.0, z_surface=0.20)
    assert len(z) == len(g_d)
    n_st, n_gap = 200, 50
    np.testing.assert_array_equal(z[n_st:n_st + n_gap], 0.20)
    t_norm = np.linspace(0.0, 1.0, n_st)
    expected = 0.20 + np.interp(t_norm, plan.strokes[0].s, plan.strokes[0].z_ff)
    np.testing.assert_allclose(z[:n_st], expected)


def test_open_z_equivalence_lock_linear_calib():
    """等价锁 (审计 R6/R4 联动): 线性标定表下 interp(z_ff) ≡ lookup(interp(g)).

    真实标定表转非线性时本断言必须失败 — 逼出"两臂前馈从哪来"的显式决策,
    而不是让分叉静默混进论文核心数字 (开/闭环差值)."""
    from brushbot.z_control import calib_lookup_z
    cal_z = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    cal_db = np.array([0.0, 50.0, 100.0, 150.0, 200.0, 250.0])
    m = 100
    s = np.linspace(0.0, 1.0, m)
    g = np.linspace(0.0, 240.0, m)
    st = Stroke(s=s, xy=np.column_stack([0.04 * s, np.zeros(m)]), g_press=g,
                z_ff=np.asarray(calib_lookup_z(g, cal_z, cal_db), float))
    plan = StrokePlan(strokes=[st], meta={})
    g_d, _ = plan.to_gd_series(1.5)
    z_field = plan.to_open_z_series(1.5, z_surface=0.20)
    z_lookup = 0.20 + np.asarray(calib_lookup_z(g_d, cal_z, cal_db), float)
    np.testing.assert_allclose(z_field, z_lookup, atol=1e-12)


def test_gd_series_structure():
    plan = _plan2()
    g_d, xy = plan.to_gd_series(stroke_duration_s=2.0, fs=100.0, gap_s=0.5)
    n_st, n_gap = 200, 50
    assert len(g_d) == len(xy) == 2 * (n_st + n_gap)
    assert (g_d >= 0).all()
    np.testing.assert_array_equal(g_d[n_st:n_st + n_gap], 0.0)   # 笔间悬空
    np.testing.assert_array_equal(g_d[-n_gap:], 0.0)             # 尾部悬空
    assert g_d[0] == pytest.approx(plan.strokes[0].g_press[0])


def test_waypoints_drive_openloop_controller():
    """OpenLoopController 可直接消费旧 V2 to_waypoints。"""
    from brushbot.controller import OpenLoopController
    from brushbot.types import State
    ctrl = OpenLoopController(_plan2().to_waypoints(), speed=0.02,
                              fixed_ori=(0.0, 0.0, 0.0))
    for i in range(50):
        cmd = ctrl.step(State(tcp_pose=(0, 0, 0, 0, 0, 0), g_meas=0.0, t=i * 0.01))
        x, y, z = cmd.tcp_pose[:3]
        assert np.isfinite([x, y, z]).all() and 0.18 <= z <= 0.22
