#!/usr/bin/env python3
"""E2E 验收 (spec §6): 合成示范 -> 管线 -> 两臂对比.

Q1 恢复精度 / Q2 速度解耦 / Q3 开环 vs 闭环 (calib×0.8). Q4 由
tests/test_strokeplan.py::test_waypoints_drive_openloop_controller 回答.

用法 (单行):
    python scripts/demo_target_pipeline.py
"""
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from brushbot.demo_pipeline import build_plan, load_demo        # noqa: E402
from brushbot.sim_loop import (Plant, V0NoiseSource, rms_pct,   # noqa: E402
                               run_loop)
from brushbot.z_control import ZController, calib_lookup_z      # noqa: E402
from brushbot.monitor.core import EMA                           # noqa: E402
from synth_demo import (g_true_s, make_demo, true_s_on_path,    # noqa: E402
                        write_demo_csv)

FS = 100.0
CALIB_Z = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
CALIB_DB = np.array([0.0, 50.0, 100.0, 150.0, 200.0, 250.0])
SEED = 42
STROKE_DURATION_S = 3.0


def _geom_rms(st, k, lo=0.1, hi=0.9):
    """恢复 g_press vs 几何对齐真值的内部 RMS (对齐经 true_s_on_path, 支撑无关)."""
    ts = true_s_on_path(st.xy, k)
    m = (ts >= lo) & (ts <= hi)
    return float(np.sqrt(np.mean((st.g_press[m] - g_true_s(ts[m])) ** 2)))


def _on_grid(st, k, grid):
    ts = true_s_on_path(st.xy, k)
    idx = np.argsort(ts)              # 边界残留样本可致 ts 非单调, 排序后插值
    return np.interp(grid, ts[idx], st.g_press[idx])


def main():
    csvs = sorted(p for p in (ROOT / "delta_b_v0_20260724").glob("*.csv")
                  if "idle" in p.stem)
    noise = V0NoiseSource(csvs, seed=SEED) if csvs else None
    work = Path(tempfile.mkdtemp(prefix="pipeline-e2e-"))

    # --- 生成两份示范 (同真值, 变速/匀速) 并过管线 ---
    plans, truths = {}, {}
    for name, mod in (("var", 0.5), ("uni", 0.0)):
        rows, truth = make_demo(speed_mod=mod, seed=SEED, noise=noise)
        p = work / ("demo_%s.csv" % name)
        write_demo_csv(p, rows)
        plans[name] = build_plan(load_demo(p), CALIB_Z, CALIB_DB)
        truths[name] = truth
    plan = plans["var"]

    # --- Q1: 恢复精度 (变速+V0 噪声 vs 真值, 逐笔几何对齐 RMS) ---
    q1 = [_geom_rms(st, k) for k, st in enumerate(plan.strokes)]
    print("Q1 恢复精度: 逐笔 RMS = %s µT (判据 ≤3)" %
          ", ".join("%.2f" % v for v in q1))

    # --- Q2: 速度解耦 (几何真值网格上比) ---
    grid = np.linspace(0.1, 0.9, 200)
    q2 = [float(np.sqrt(np.mean((_on_grid(a, k, grid) - _on_grid(b, k, grid)) ** 2)))
          for k, (a, b) in enumerate(zip(plans["uni"].strokes, plans["var"].strokes))]
    print("Q2 速度解耦(全管线 fc=3, 含时域滤波×速度耦合): 互差 RMS = %s µT"
          " (如实报告, sanity ≤3.5; 纯重参数化判据 ≤1 由单测 fc=10 隔离回答)" %
          ", ".join("%.2f" % v for v in q2))

    # --- Q3: 两臂彩排 (calib×0.8) ---
    g_d, _ = plan.to_gd_series(STROKE_DURATION_S)
    sigma_f = (V0NoiseSource(csvs, seed=SEED).filtered_sigma(lambda: EMA(0.3))
               if csvs else 2.0)
    z_open = 0.20 + np.asarray(calib_lookup_z(g_d, CALIB_Z, CALIB_DB), float)
    results = {}
    for arm in ("open", "closed"):
        pl_noise = V0NoiseSource(csvs, seed=SEED) if csvs else None
        plant = Plant(CALIB_Z, CALIB_DB, noise=pl_noise, calib_scale=0.8)
        if arm == "open":
            abs_true = np.empty(len(z_open))
            for i, z in enumerate(z_open):   # 开环: 逐拍执行 z_ff, 不读传感器
                plant.step(z)
                abs_true[i] = plant.abs_true
            res = {"g_d": g_d, "abs_true": abs_true,
                   "z_cmd": z_open, "frozen": g_d < 3.0 * sigma_f}
        else:
            ctrl = ZController(CALIB_Z, CALIB_DB, noise_std=sigma_f)
            res = run_loop(ctrl, EMA(0.3), g_d, plant)
        results[arm] = res
        print("Q3 %s: 接触段 RMS = %.2f%%" % (arm, rms_pct(res, sigma_f)))

    # --- 图: 三面板 (Q1 恢复对比 / Q2 两剖面重叠 / Q3 两臂跟踪) ---
    import matplotlib
    matplotlib.use("Agg")
    matplotlib.rcParams["font.sans-serif"] = [
        "Noto Sans CJK SC", "Noto Sans CJK HK", "Noto Sans CJK JP", "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(3, 1, figsize=(10, 10))
    st = plan.strokes[0]
    tr = truths["var"]
    axes[0].plot(tr["s_grid"], tr["g0"], "k-", lw=2, label="真值 g(s)")
    axes[0].plot(true_s_on_path(st.xy, 0), st.g_press, "--", lw=1.2,
                 label="管线恢复 (几何对齐)")
    axes[0].set(xlabel="s", ylabel="g (µT)", title="Q1: 恢复精度 (笔 0)")
    axes[0].legend(fontsize=8)
    axes[1].plot(true_s_on_path(plans["uni"].strokes[0].xy, 0),
                 plans["uni"].strokes[0].g_press, lw=1.2, label="匀速示范")
    axes[1].plot(true_s_on_path(plans["var"].strokes[0].xy, 0),
                 plans["var"].strokes[0].g_press, "--", lw=1.2,
                 label="±50% 变速示范")
    axes[1].set(xlabel="s", ylabel="g (µT)", title="Q2: 速度解耦")
    axes[1].legend(fontsize=8)
    t_axis = np.arange(len(g_d)) / FS
    axes[2].plot(t_axis, g_d, "k-", lw=1.5, label="目标 g_d")
    for arm, style in (("open", ":"), ("closed", "--")):
        axes[2].plot(t_axis, results[arm]["abs_true"], style, lw=1.2, label=arm)
    axes[2].set(xlabel="t (s)", ylabel="|ΔB| (µT)",
                title="Q3: calib×0.8 下两臂跟踪 (真值口径)")
    axes[2].legend(fontsize=8)
    fig.tight_layout()
    out_png = ROOT / "docs" / "assets" / "target-pipeline-demo.png"
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=120)
    print("图:", out_png)


if __name__ == "__main__":
    main()
