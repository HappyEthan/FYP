"""离线目标曲线管线: 示范 CSV (ΔB+XY 同步) -> StrokePlan.

纪律 (与实时链路相反): 离线数据必须干净 -- 坏数据当场报错, 不透传.
见 docs/superpowers/specs/2026-07-31-offline-target-pipeline-design.md
"""
import numpy as np

from brushbot import config
from brushbot.sim_loop import fft_lowpass
from brushbot.strokeplan import Stroke, StrokePlan
from brushbot.z_control import calib_lookup_z

FS = config.FS   # 采样主频: config 为唯一定义 (R12)
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
    t = np.atleast_1d(d["t_s"])
    if len(t) < 2:
        raise ValueError("示范太短")
    dt_med = float(np.median(np.diff(t)))
    if abs(dt_med - 1.0 / FS) > 0.1 / FS:
        raise ValueError(
            "示范采样率 %.1f Hz ≠ 管线假定的 %g Hz (σ 窗口/切分/边界内缩的时间常数都会静默失真): %s"
            % (1.0 / dt_med, FS, csv_path))
    return {"t": t,
            "xy": np.column_stack([np.atleast_1d(d["x_m"]), np.atleast_1d(d["y_m"])]),
            "dB": np.column_stack([np.atleast_1d(d["dBx_uT"]),
                                   np.atleast_1d(d["dBy_uT"]),
                                   np.atleast_1d(d["dBz_uT"])]),
            "source": str(csv_path)}


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
            "或给 build_plan 显式传 sigma; 或整段无书写内容(全程安静的录音同样触发本判据)"
            % (head_s, sigma))
    return sigma


def segment_strokes(g_clean, sigma, fs=FS, min_len_s=0.3, merge_gap_s=0.15,
                    rel_peak=0.05):
    """接触段切分: g >= T 的连续区间 [(start, end)). 返回 (segs, n_dropped).

    (2026-07-31 三次修订, Task 5 评审驱动, 收敛版) 阈值 T = max(3σ, rel_peak ·
    p99(g_clean)): 零相位砖墙滤波的旁瓣振铃随**信号**幅度缩放 (实测 185µT 笔画
    在悬空段留下 4-7µT ≈ 2-4% 峰值的旁瓣), 任何纯噪声口径的阈值/幅度门都挡不住
    它 —— 阈值必须同时随信号规模缩放, 旁瓣 (≤4%) 天然落在 5% 线下. 间隙 <
    merge_gap_s 的相邻 run 合并 (桥接笔画中途短暂低压中断); 合并后短于
    min_len_s 的计入 n_dropped."""
    thresh = max(3.0 * sigma, rel_peak * float(np.percentile(g_clean, 99)))
    mask = np.concatenate([[False], g_clean >= thresh, [False]])
    d = np.diff(mask.astype(int))
    merge_gap = int(merge_gap_s * fs)
    merged = []
    for a, b in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)):
        if merged and int(a) - merged[-1][1] < merge_gap:
            merged[-1] = (merged[-1][0], int(b))
        else:
            merged.append((int(a), int(b)))
    min_len = int(min_len_s * fs)
    segs = [tuple(r) for r in merged if r[1] - r[0] >= min_len]
    return segs, int(len(merged) - len(segs))


def reparam_arclength(xy_seg, g_seg, M=200):
    """时域笔段 -> 均匀弧长域 (s, xy_s, g_s). 总弧长 < 1mm 抛 ValueError.

    XY 停顿产生的 s 平台是合法输入 (非降序列, np.interp 安全)."""
    ds = np.hypot(*np.diff(np.asarray(xy_seg, float), axis=0).T)
    s = np.concatenate([[0.0], np.cumsum(ds)])
    if s[-1] < 1e-3:
        raise ValueError("笔画弧长 %.3g m < 1mm (原地按压不算笔画)" % s[-1])
    s = s / s[-1]
    s_grid = np.linspace(0.0, 1.0, M)
    xy_s = np.column_stack([np.interp(s_grid, s, xy_seg[:, 0]),
                            np.interp(s_grid, s, xy_seg[:, 1])])
    return s_grid, xy_s, np.interp(s_grid, s, np.asarray(g_seg, float))


def build_plan(demo, calib_z_mm, calib_abs_dB, fc=3.0, M=200, sigma=None):
    """编排整条管线: 整段零相位滤波 -> norm -> σ -> 切分 -> 逐笔重参数化 -> 反查.

    铁律: 先滤 (N,3) 向量再取 norm. 整段滤波后再切分 (避免短笔段 FFT 边缘伪影)."""
    g_clean = np.linalg.norm(fft_lowpass(demo["dB"], fc), axis=1)
    if sigma is None:
        sigma = estimate_sigma(g_clean)
    segs, n_dropped_short = segment_strokes(g_clean, sigma)
    # 边界内缩: 零相位砖墙低通把接触边界抹开 ~0.5/fc, 段边缘裹进的"悬空但在移动"
    # 样本会伪造弧长 (实测 40mm 笔画被污染 17-21%); 收缩后段内每拍 XY 都真实在纸上.
    trim = int(round(0.5 * FS / fc))
    cal_max = float(np.max(calib_abs_dB))
    strokes, durations, n_dropped_arc, n_sat, n_tot = [], [], 0, 0, 0
    for a, b in segs:
        a, b = a + trim, b - trim
        if b - a < int(0.1 * FS):              # 裁后过短 → 并入过短丢弃计数
            n_dropped_short += 1
            continue
        try:
            s, xy_s, g_s = reparam_arclength(demo["xy"][a:b], g_clean[a:b], M)
        except ValueError:
            n_dropped_arc += 1
            continue
        n_sat += int((g_s > cal_max).sum())
        n_tot += len(g_s)
        strokes.append(Stroke(s=s, xy=xy_s, g_press=g_s,
                              z_ff=np.asarray(calib_lookup_z(
                                  g_s, calib_z_mm, calib_abs_dB), float)))
        durations.append((b - a) / FS)         # 裁后净接触时长 (spec §8.5 落点)
    sat_frac = n_sat / max(n_tot, 1)
    meta = {"fc": float(fc), "M": int(M), "sigma": float(sigma),
            "edge_trim_s": trim / FS,
            "stroke_durations_s": durations,
            "n_dropped_short": int(n_dropped_short),
            "n_dropped_arc": int(n_dropped_arc), "sat_frac": float(sat_frac),
            "calib_fingerprint": [float(np.min(calib_z_mm)), float(np.max(calib_z_mm)),
                                  float(np.min(calib_abs_dB)), cal_max],
            "source": demo.get("source", "")}
    if sat_frac > 0.05:
        print("警告: %.1f%% 样本超标定范围被饱和 -- 示范力度超出标定表, 建议重标"
              % (100.0 * sat_frac))
    if n_dropped_short or n_dropped_arc:
        print("提示: 丢弃过短笔画 %d 段 / 短弧长 %d 段" % (n_dropped_short, n_dropped_arc))
    return StrokePlan(strokes=strokes, meta=meta)
