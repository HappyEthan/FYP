#!/usr/bin/env python3
"""合成示范生成器: 产出带真值的示范 CSV (+truth npz), 供管线开发与 E2E 验收.

用法 (单行):
    python scripts/synth_demo.py --out /tmp/demo.csv --truth /tmp/truth.npz
    python scripts/synth_demo.py --uniform-speed --seed 7 --out /tmp/demo_uni.csv --truth /tmp/truth_uni.npz
"""
import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from brushbot.demo_pipeline import DEMO_COLS          # noqa: E402
from brushbot.sim_loop import V0NoiseSource           # noqa: E402

FS = 100.0
DIRECTION = np.array([1.0, 0.3, 0.1]) / np.linalg.norm([1.0, 0.3, 0.1])


def g_true_s(s, base=125.0, depth=60.0):
    """真值 g(s): 边缘 10% ramp + 2 周期正弦提按 (量程内, 峰值 185 µT)."""
    g = base + depth * np.sin(2.0 * np.pi * 2.0 * s)
    return g * np.clip(np.minimum(s, 1.0 - s) / 0.1, 0.0, 1.0)


def stroke_path(k, m):
    """第 k 笔 XY (米): 直线与半圆弧交替, 逐笔 y 下移 1cm."""
    t = np.linspace(0.0, 1.0, m)
    y0 = 0.01 * k
    if k % 2 == 0:
        return np.column_stack([0.04 * t, np.full(m, y0)])
    ang = np.pi * t
    return np.column_stack([0.02 - 0.02 * np.cos(ang), y0 + 0.012 * np.sin(ang)])


def true_s_on_path(xy, k):
    """恢复样本 XY -> 几何真值 s (E2E 对齐用; 与管线边界内缩配套, 不假设支撑一致).

    直线笔画 (偶 k) 用 x/0.04; 半椭圆弧 (奇 k) 用参数角反解."""
    xy = np.asarray(xy, float)
    if k % 2 == 0:
        return np.clip(xy[:, 0] / 0.04, 0.0, 1.0)
    y0 = 0.01 * k
    ang = np.arctan2((xy[:, 1] - y0) / 0.012, (0.02 - xy[:, 0]) / 0.02)
    return np.clip(ang / np.pi, 0.0, 1.0)


def make_demo(n_strokes=3, stroke_s=3.0, gap_s=0.8, speed_mod=0.5, seed=42,
              noise=None):
    """(rows (N,7), truth). speed_mod: 变速幅度 (0=匀速; 0.5 → 速度在 0.5~1.5x 摆动)."""
    assert 0.0 <= speed_mod < 1.0, "speed_mod ∈ [0,1) 否则 s_of_t 非单调"
    n, ngap = int(stroke_s * FS), int(gap_s * FS)
    tn = np.linspace(0.0, 1.0, n)
    s_of_t = tn + speed_mod * np.sin(2.0 * np.pi * tn) / (2.0 * np.pi)
    s_of_t = (s_of_t - s_of_t[0]) / (s_of_t[-1] - s_of_t[0])
    s_grid = np.linspace(0.0, 1.0, 400)
    truth = {"s_grid": s_grid}
    # 悬空段 XY 线性平移到下笔起点 (与 Task 5 _make_demo 同一修正: 手不会瞬移,
    # 瞬移会在切分边界伪造大步弧长)
    paths = [stroke_path(k, 400) for k in range(n_strokes)]
    frac = np.linspace(0.0, 1.0, ngap)[:, None]
    g_parts = [np.zeros(ngap)]
    xy_parts = [np.tile(paths[0][0], (ngap, 1))]        # 初始悬空: 停在首笔起点
    for k in range(n_strokes):
        path = paths[k]
        g_parts.append(np.interp(s_of_t, s_grid, g_true_s(s_grid)))
        xy_parts.append(np.column_stack([np.interp(s_of_t, s_grid, path[:, 0]),
                                         np.interp(s_of_t, s_grid, path[:, 1])]))
        truth["g%d" % k] = g_true_s(s_grid)
        nxt = paths[k + 1][0] if k + 1 < n_strokes else path[-1]
        g_parts.append(np.zeros(ngap))
        xy_parts.append(path[-1][None, :] * (1.0 - frac) + nxt[None, :] * frac)
    g = np.concatenate(g_parts)
    xy = np.vstack(xy_parts)
    if noise is not None:
        nz = noise.sample(len(g))
    else:
        nz = np.random.default_rng(seed).normal(0.0, 2.0, (len(g), 3))
    dB = DIRECTION[None, :] * g[:, None] + nz
    t_s = np.arange(len(g)) / FS
    rows = np.column_stack([t_s * 1e6, t_s, dB, xy])
    return rows, truth


def write_demo_csv(path, rows):
    header = ",".join(DEMO_COLS)
    np.savetxt(path, rows, delimiter=",", header=header, comments="",
               fmt="%.9g")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--strokes", type=int, default=3)
    ap.add_argument("--uniform-speed", action="store_true")
    ap.add_argument("--csv-dir", default=str(ROOT / "delta_b_v0_20260724"),
                    help="V0 idle CSV 目录 (存在则用真噪声, 否则白噪声)")
    args = ap.parse_args(argv)

    idle = sorted(p for p in Path(args.csv_dir).glob("*.csv") if "idle" in p.stem)
    noise = V0NoiseSource(idle, seed=args.seed) if idle else None
    rows, truth = make_demo(n_strokes=args.strokes,
                            speed_mod=0.0 if args.uniform_speed else 0.5,
                            seed=args.seed, noise=noise)
    write_demo_csv(args.out, rows)
    np.savez(args.truth, **truth)
    print("示范 CSV: %s (%d 拍, 噪声=%s)  真值: %s"
          % (args.out, len(rows), "V0" if noise else "white", args.truth))


if __name__ == "__main__":
    main()
