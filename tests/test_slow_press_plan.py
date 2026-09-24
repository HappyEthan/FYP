import csv
from pathlib import Path

import numpy as np
import pytest

from brushbot.strokeplan import StrokePlan
from scripts.generate_slow_press_plan import build_slow_press_plan


def test_build_slow_press_plan_uses_experiment_signal_and_geometry(tmp_path):
    data = tmp_path / "slow_press.csv"
    with data.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("t_s", "dBx_uT", "dBy_uT", "sample_valid"))
        for index in range(2301):
            t = index / 100.0
            amplitude = 10.0 + 50.0 * min(max((t - 8.0) / 14.0, 0.0), 1.0)
            writer.writerow((t, amplitude, 0.0, 1))
    out = tmp_path / "slow.npz"
    plan = build_slow_press_plan(data, output=out, n_points=101,
                                 max_depth_mm=3.0, speed_mm_s=5.0)
    assert out.exists()
    loaded = StrokePlan.load(out)
    st = loaded.strokes[0]
    assert len(st.s) == len(st.xy) == len(st.g_press) == len(st.z_ff) == 101
    np.testing.assert_allclose(st.xy[0], [-0.299025, 0.500067])
    np.testing.assert_allclose(st.xy[-1], [0.000975, 0.500067])
    assert st.z_ff[0] == 0.0
    assert st.z_ff[-1] == pytest.approx(0.003)
    assert np.all(np.diff(st.s) > 0)
    assert np.all(np.diff(st.z_ff) >= -1e-12)
    assert np.max(st.g_press) > np.min(st.g_press) + 20.0
    assert loaded.meta["source_csv"].endswith(data.name)
    assert loaded.meta["generation"] == "monotone_slow_press_from_dBxy"


def test_generator_rejects_missing_or_short_recording(tmp_path):
    missing = tmp_path / "missing.csv"
    try:
        build_slow_press_plan(missing, output=tmp_path / "x.npz")
    except ValueError as exc:
        assert "cannot read" in str(exc)
    else:
        raise AssertionError("missing input must fail")
