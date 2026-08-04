import numpy as np
import pytest

from brushbot.demo_pipeline import (DEMO_COLS, estimate_sigma, load_demo,
                                    segment_strokes)

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
