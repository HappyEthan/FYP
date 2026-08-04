"""离线目标曲线管线: 示范 CSV (ΔB+XY 同步) -> StrokePlan.

纪律 (与实时链路相反): 离线数据必须干净 -- 坏数据当场报错, 不透传.
见 docs/superpowers/specs/2026-07-31-offline-target-pipeline-design.md
"""
import numpy as np

FS = 100.0
DEMO_COLS = ("t_us", "t_s", "dBx_uT", "dBy_uT", "dBz_uT", "x_m", "y_m")


def load_demo(csv_path):
    """示范 CSV -> {"t": (N,), "xy": (N,2), "dB": (N,3)}. 缺列/非有限值当场报错."""
    d = np.genfromtxt(csv_path, delimiter=",", names=True)
    names = d.dtype.names or ()
    missing = [c for c in DEMO_COLS if c not in names]
    if missing:
        raise ValueError(
            "示范 CSV 缺列 %s (V0 监控格式没有 x_m/y_m; 示范录制格式见 "
            "spec 2026-07-31-offline-target-pipeline §2): %s" % (missing, csv_path))
    cols = np.column_stack([np.atleast_1d(d[c]) for c in DEMO_COLS])
    bad = ~np.isfinite(cols)
    if bad.any():
        row = int(np.flatnonzero(bad.any(axis=1))[0]) + 2   # +1 表头, +1 改 1 始计数
        raise ValueError("示范 CSV 含非有限值, 首个坏行为第 %d 行: %s" % (row, csv_path))
    return {"t": np.atleast_1d(d["t_s"]),
            "xy": np.column_stack([np.atleast_1d(d["x_m"]), np.atleast_1d(d["y_m"])]),
            "dB": np.column_stack([np.atleast_1d(d["dBx_uT"]),
                                   np.atleast_1d(d["dBy_uT"]),
                                   np.atleast_1d(d["dBz_uT"])])}


def estimate_sigma(g_clean, fs=FS, head_s=0.5):
    """滤波后 σ 估计: 取首段悬空 (录制协议规定首尾悬空 >=0.5s) 的 std.

    首段不安静 (std 超全段 std 的一半) -> 报错; 可在 build_plan 显式传 sigma 绕过."""
    head = g_clean[:int(head_s * fs)]
    if len(head) < int(0.2 * fs):
        raise ValueError("录音太短 (%d 拍), 无法从首段估计 σ" % len(g_clean))
    sigma = float(head.std())
    if sigma > 0.5 * float(np.std(g_clean)):
        raise ValueError(
            "首段 %.1fs 不像悬空段 (std=%.2f µT), 录制需首尾悬空 >=0.5s; "
            "或给 build_plan 显式传 sigma" % (head_s, sigma))
    return sigma


def segment_strokes(g_clean, sigma, fs=FS, min_len_s=0.3):
    """接触段切分: g >= 3σ 的连续区间 [(start, end)), 过短段丢弃并计数.

    返回 (segs, n_dropped)."""
    mask = np.concatenate([[False], g_clean >= 3.0 * sigma, [False]])
    d = np.diff(mask.astype(int))
    starts = np.flatnonzero(d == 1)
    ends = np.flatnonzero(d == -1)
    min_len = int(min_len_s * fs)
    segs = [(int(a), int(b)) for a, b in zip(starts, ends) if b - a >= min_len]
    return segs, int(len(starts) - len(segs))
