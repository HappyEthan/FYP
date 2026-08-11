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
    plan = _plan2()
    wps = plan.to_waypoints(z_surface=0.20, lift=0.015)
    m = len(plan.strokes[0].s)
    assert len(wps) == 2 * (m + 2)                      # 每笔: 进入 + M + 抬笔
    x0, y0 = plan.strokes[0].xy[0]
    assert wps[0] == pytest.approx((x0, y0, 0.215))     # 悬空进入点
    assert wps[1][2] == pytest.approx(0.20 + plan.strokes[0].z_ff[0])
    assert wps[m + 1][2] == pytest.approx(0.215)        # 抬笔点
    zs = np.array([w[2] for w in wps])
    assert (zs >= 0.20 - 1e-12).all() and (zs <= 0.215 + 1e-12).all()


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
    """B1 兼容 (spec Q4): OpenLoopController 原样消费 to_waypoints."""
    from brushbot.controller import OpenLoopController
    from brushbot.types import State
    ctrl = OpenLoopController(_plan2().to_waypoints(), speed=0.02,
                              fixed_ori=(0.0, 0.0, 0.0))
    for i in range(50):
        cmd = ctrl.step(State(tcp_pose=(0, 0, 0, 0, 0, 0), g_meas=0.0, t=i * 0.01))
        x, y, z = cmd.tcp_pose[:3]
        assert np.isfinite([x, y, z]).all() and 0.19 <= z <= 0.22
