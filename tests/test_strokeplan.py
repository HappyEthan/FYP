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
