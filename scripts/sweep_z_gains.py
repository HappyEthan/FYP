#!/usr/bin/env python3
"""层1: {滤波} × {kp, ki} 增益扫描 → 稳定边界 + 工作点 + 报告.

用法 (单行):
    python scripts/sweep_z_gains.py
    python scripts/sweep_z_gains.py --quick
    python scripts/sweep_z_gains.py --csv-dir delta_b_v0_20260724 --out docs/z-phase1-sweep.md

回答 spec §1 的 Q1 (滤波收益) 与 Q2 (稳定边界+裕度).
"""
import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from brushbot.filter import ButterworthFilter, OneEuroFilter  # noqa: E402
from brushbot.monitor.core import EMA                          # noqa: E402
from brushbot.sim_loop import (FS, Plant, V0NoiseSource, diverged, osc_index,  # noqa: E402
                               rms_pct, run_loop, synth_press)
from brushbot.z_control import ZController                     # noqa: E402
from compare_filters import ema_freq_response                  # noqa: E402  (同目录)

CALIB_Z = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
CALIB_DB = np.array([0.0, 50.0, 100.0, 150.0, 200.0, 250.0])
FILTERS = [
    ("none", None, None),
    ("EMA a=0.3", lambda: EMA(0.3), lambda f: ema_freq_response(0.3, f)),
    ("Butter fc=8", lambda: ButterworthFilter(8.0), ButterworthFilter(8.0).freq_response),
    ("OneEuro mc=0.5 b=0.03", lambda: OneEuroFilter(0.5, 0.03), None),  # 非线性: 无频域数
]
OSC_MAX = 0.05     # 稳定判定: osc_index ≤ 5% (spec §3.3 暂定值)
SEED = 42
TAU, N_DELAY = 0.05, 2


def run_cell(make_filter, kp, ki, sigma_f, g_d, csvs, tau=TAU, n_delay=N_DELAY):
    noise = V0NoiseSource(csvs, seed=SEED)
    plant = Plant(CALIB_Z, CALIB_DB, tau=tau, n_delay=n_delay, noise=noise)
    ctrl = ZController(CALIB_Z, CALIB_DB, kp=kp, ki=ki, noise_std=sigma_f)
    res = run_loop(ctrl, make_filter() if make_filter else None, g_d, plant)
    stable = (not diverged(res, ctrl.z_surface, CALIB_Z[-1] / 1000.0)
              and osc_index(res) <= OSC_MAX)
    return rms_pct(res, sigma_f), stable


def sweep(make_filter, kp_grid, ki_grid, sigma_f, g_d, csvs):
    rms = np.empty((len(kp_grid), len(ki_grid)))
    stable = np.empty_like(rms, dtype=bool)
    for i, kp in enumerate(kp_grid):
        for j, ki in enumerate(ki_grid):
            rms[i, j], stable[i, j] = run_cell(make_filter, kp, ki, sigma_f, g_d, csvs)
    return rms, stable


def working_point(rms, stable, kp_grid, ki_grid):
    """稳定且 +2 网格步 (≈2.5×kp / ≈3.7×ki, 保守 ≥2×裕度) 仍稳定者中取 RMS 最小.

    ki=0 行只查 kp 裕度. 返回 (i, j) 或 None."""
    best = None
    for i in range(len(kp_grid)):
        for j in range(len(ki_grid)):
            if not stable[i, j]:
                continue
            i2, j2 = i + 2, (j + 2 if ki_grid[j] > 0 else j)
            if i2 >= len(kp_grid) or j2 >= len(ki_grid) or not stable[i2, j2]:
                continue
            if best is None or rms[i, j] < rms[best]:
                best = (i, j)
    return best


def phase_margin_deg(kp, ki, freq_fn, tau=TAU, delay_s=(N_DELAY + 1) / FS):
    """线性臂解析相位裕度. L = (kp + ki/s)·执行器·延迟·滤波器 (S_cal 与 plant
    斜率互逆, calib_scale=1 时消掉). OneEuro 不适用 (spec 坑3)."""
    f = np.geomspace(0.01, 49.0, 4000)
    w = 2 * np.pi * f
    L = (kp + ki / (1j * w)) * np.exp(-1j * w * delay_s) / (1 + 1j * w * tau)
    if freq_fn is not None:
        L = L * freq_fn(f)
    idx = np.nonzero(np.abs(L) >= 1.0)[0]
    if len(idx) == 0:
        return float("inf")
    return float(180.0 + np.degrees(np.angle(L[idx[-1]])))


def sensitivity(make_filter, kp, ki, sigma_f, g_d, csvs):
    """工作点在 τ×延迟假设网格下的稳定性抽查 (spec §3.3)."""
    rows = []
    for tau in (0.02, 0.05, 0.1):
        for nd in (1, 2, 4):
            r, s = run_cell(make_filter, kp, ki, sigma_f, g_d, csvs, tau=tau, n_delay=nd)
            rows.append((tau, nd, r, s))
    return rows


def make_heatmap(rms, stable, kp_grid, ki_grid, wp, label, out_png):
    import matplotlib
    matplotlib.use("Agg")
    matplotlib.rcParams["font.sans-serif"] = [
        "Noto Sans CJK SC", "Noto Sans CJK HK", "Noto Sans CJK JP", "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7, 5))
    shown = np.where(stable, rms, np.nan)
    im = ax.imshow(shown, origin="lower", aspect="auto", cmap="viridis")
    ax.set(xticks=range(len(ki_grid)), yticks=range(len(kp_grid)),
           xticklabels=["%g" % k for k in ki_grid],
           yticklabels=["%g" % k for k in kp_grid],
           xlabel="ki (无量纲)", ylabel="kp (无量纲)",
           title="%s: 跟踪 RMS %% (灰=不稳定)" % label)
    ax.set_facecolor("0.8")
    if wp is not None:
        ax.plot(wp[1], wp[0], "r*", ms=16, label="工作点")
        ax.legend()
    fig.colorbar(im, ax=ax, label="RMS %")
    fig.tight_layout()
    fig.savefig(out_png, dpi=120)
    plt.close(fig)


def write_report(results, kp_grid, ki_grid, out_md):
    """生成 markdown 报告: 每滤波臂一节 + 汇总表, 回答 spec §1 Q1/Q2."""
    slugs = {r["label"]: r["label"].replace(" ", "").replace("=", "").replace(".", "")
             for r in results}
    none_rms = next((r["rms"][r["wp"]] for r in results
                      if r["label"] == "none" and r["wp"] is not None), None)

    lines = [
        "# Z 控制层 1 增益扫描报告 (脚本生成)",
        "",
        "> 生成命令: `python scripts/sweep_z_gains.py`",
        "> kp 网格: %s" % ", ".join("%.3g" % k for k in kp_grid),
        "> ki 网格: %s" % ", ".join("%.3g" % k for k in ki_grid),
        "> 回答 spec §1 Q1 (滤波收益) 与 Q2 (稳定边界+裕度).",
        "",
        "## 各滤波臂",
        "",
    ]

    for r in results:
        label = r["label"]
        lines.append("### %s" % label)
        lines.append("")
        lines.append("σ_f (滤波后噪声标准差, µT): **%.2f**" % r["sigma_f"])
        lines.append("")
        if r["wp"] is None:
            lines.append("工作点: **未找到** (全网格内无 +2 网格步仍稳定的格点).")
            lines.append("")
        else:
            i, j = r["wp"]
            kp, ki = kp_grid[i], ki_grid[j]
            rms = r["rms"][i, j]
            lines.append("工作点: kp=**%.4g**, ki=**%.4g**, 跟踪 RMS=**%.2f%%**"
                         % (kp, ki, rms))
            lines.append("")
            if label == "OneEuro mc=0.5 b=0.03":
                lines.append("相位裕度: 非线性滤波器无频域相位裕度 (OneEuro 坑3) — "
                             "时域裕度: 工作点在 kp ×2.48 / ki ×3.73 (+2 网格步) 仍稳定.")
            elif r["pm"] is not None:
                pm = r["pm"]
                pm_str = "∞ (环路增益全频段 <1, 未见穿越)" if not np.isfinite(pm) else "%.1f°" % pm
                lines.append("相位裕度 (解析, 线性臂): **%s**; 时域裕度: +2 网格步 "
                             "(kp ×2.48 / ki ×3.73) 仍稳定." % pm_str)
            else:
                lines.append("相位裕度: 未计算.")
            lines.append("")
            lines.append("敏感性抽查 (τ × n_delay, 工作点增益不变):")
            lines.append("")
            lines.append("| τ (s) \\ n_delay | 1 | 2 | 4 |")
            lines.append("|---|---|---|---|")
            sens = {(t, n): (rr, ss) for t, n, rr, ss in r["sens"]}
            for tau in (0.02, 0.05, 0.1):
                cells = []
                for nd in (1, 2, 4):
                    rr, ss = sens[(tau, nd)]
                    mark = "稳" if ss else "**不稳**"
                    cells.append("%.2f%% (%s)" % (rr, mark))
                lines.append("| %.2f | %s |" % (tau, " | ".join(cells)))
            lines.append("")
        lines.append("![%s 热力图](assets/z-phase1-sweep-%s.png)" % (label, slugs[label]))
        lines.append("")

    lines += [
        "## 汇总表 (Q1: 滤波收益 / Q2: 稳定边界+裕度)",
        "",
        "| 滤波臂 | σ_f µT | 工作点 kp | 工作点 ki | 工作点 RMS % | vs none RMS | 相位裕度 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        label = r["label"]
        if r["wp"] is None:
            lines.append("| %s | %.2f | — | — | — | — | — |" % (label, r["sigma_f"]))
            continue
        i, j = r["wp"]
        kp, ki, rms = kp_grid[i], ki_grid[j], r["rms"][i, j]
        if none_rms is not None and label != "none":
            delta = "%+.1f%%" % (rms - none_rms)
        else:
            delta = "—"
        if label == "OneEuro mc=0.5 b=0.03":
            pm_str = "非线性—时域裕度 2 网格步"
        elif r["pm"] is not None:
            pm_str = "∞" if not np.isfinite(r["pm"]) else "%.1f°" % r["pm"]
        else:
            pm_str = "—"
        lines.append("| %s | %.2f | %.4g | %.4g | %.2f | %s | %s |"
                     % (label, r["sigma_f"], kp, ki, rms, delta, pm_str))

    none_row = next((r for r in results if r["label"] == "none"), None)
    none_kp = kp_grid[none_row["wp"][0]] if none_row and none_row["wp"] is not None else None
    better, worse = [], []
    if none_rms is not None:
        for r in results:
            if r["label"] == "none" or r["wp"] is None:
                continue
            d = r["rms"][r["wp"]] - none_rms
            (better if d < 0 else worse).append((r["label"], d))

    lines += [
        "",
        "**Q1 (滤波收益):** 各滤波臂工作点跟踪 RMS 相对 \"none\" 臂工作点 RMS 的差值见上表 "
        "\"vs none RMS\" 列 (负值 = 优于无滤波); \"none\" 臂即无滤波直接闭环, 作为收益基线.",
        "",
    ]
    if none_rms is not None:
        if worse:
            lines.append(
                "⚠️ **注意:** 并非全部滤波臂都优于 \"none\": " +
                "、".join("%s (%+.1f%%)" % (lb, d) for lb, d in worse) +
                " 在其工作点的跟踪 RMS 反而**高于**无滤波臂。原因: 工作点规则先保证稳定裕度, "
                "滤波器引入的相位滞后压低了可用 kp 上限 (none 臂 kp=%s, 上述臂被迫取更低 kp), "
                "该增益损失抵消乃至反超了噪声降低带来的收益; 这是滤波在闭环中的固有权衡 "
                "(降噪 vs 相位裕度), 不是脚本缺陷, 按判据如实记录、不调整." %
                ("%.3g" % none_kp if none_kp is not None else "N/A"))
        if better:
            lines.append(
                "滤波收益为正的臂: " +
                "、".join("%s (%+.1f%%)" % (lb, d) for lb, d in better) + "。")
        lines.append("")

    lines += [
        "**Q2 (稳定边界+裕度):** 稳定判定 = 未发散 (`diverged`) 且 `osc_index ≤ OSC_MAX`; "
        "工作点规则要求 (kp, ki) 处及 +2 网格步 (kp ×2.48, ki ×3.73, 保守 ≥2× 裕度) 处均稳定, "
        "取满足此条件者中 RMS 最小的格点; 线性滤波臂另附解析相位裕度 (环路含 PI + 一阶执行器 τ + "
        "n_delay 拍延迟 + 滤波器频响); OneEuro 为非线性滤波器, 无法定义频域相位裕度, 只报工作点 "
        "规则本身蕴含的时域增益裕度.",
        "",
        "## 注记",
        "",
        "- 稳定判定阈值 OSC_MAX=%.2f (spec §3.3 暂定值, 未经真机验证)." % OSC_MAX,
        "- \"+2 网格步\" 在本报告的网格间距下等价于 kp ×2.48、ki ×3.73 (几何网格, 全臂通用).",
        "- Plant 的 τ=%.2fs、n_delay=%d 拍为假设值 (真机未标定); 各工作点的敏感性 3×3 表 "
          "(τ∈{0.02,0.05,0.1}s × n_delay∈{1,2,4}) 显示工作点在假设范围内是否仍稳定, "
          "用于评估该假设对结论的影响." % (TAU, N_DELAY),
        "- σ_f 用裸态 (未装配) V0 idle 数据估计, 是乐观下界; 装配态数据到位后须重跑本脚本.",
        "- OneEuro 工作点为层 1 (简化仿真) 下的定稿候选, 非线性特性未在层 1 频域核算中体现, "
          "最终结论待层 2 (`compare_z_arms.py`, Task 8) 用扰动场景确认.",
        "",
    ]
    Path(out_md).write_text("\n".join(lines), encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv-dir", default=str(ROOT / "delta_b_v0_20260724"))
    ap.add_argument("--out", default=str(ROOT / "docs" / "z-phase1-sweep.md"))
    ap.add_argument("--quick", action="store_true", help="缩小网格冒烟")
    args = ap.parse_args(argv)

    csvs = sorted(p for p in Path(args.csv_dir).glob("*.csv") if "idle" in p.stem)
    if not csvs:
        sys.exit("错误: %s 下没有 idle CSV" % args.csv_dir)
    if args.quick:
        kp_grid = np.geomspace(0.1, 1.0, 4)
        ki_grid = np.array([0.0, 0.03, 0.1])
    else:
        kp_grid = np.geomspace(0.05, 3.0, 10)
        ki_grid = np.concatenate([[0.0], np.geomspace(0.005, 0.5, 8)])
    g_d = synth_press(cal_max=CALIB_DB[-1])

    out_md = Path(args.out)
    asset_dir = out_md.parent / "assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for label, mk, freq_fn in FILTERS:
        sigma_f = V0NoiseSource(csvs, seed=SEED).filtered_sigma(mk)
        rms, stable = sweep(mk, kp_grid, ki_grid, sigma_f, g_d, csvs)
        wp = working_point(rms, stable, kp_grid, ki_grid)
        row = {"label": label, "sigma_f": sigma_f, "rms": rms, "stable": stable,
               "wp": wp, "pm": None, "sens": None}
        if wp is not None:
            kp, ki = kp_grid[wp[0]], ki_grid[wp[1]]
            row["pm"] = (phase_margin_deg(kp, ki, freq_fn)
                         if freq_fn is not None or label == "none" else None)
            row["sens"] = sensitivity(mk, kp, ki, sigma_f, g_d, csvs)
        slug = label.replace(" ", "").replace("=", "").replace(".", "")
        make_heatmap(rms, stable, kp_grid, ki_grid, wp, label,
                     asset_dir / ("z-phase1-sweep-%s.png" % slug))
        results.append(row)
        print(label, "wp=", None if wp is None else
              (kp_grid[wp[0]], ki_grid[wp[1]], rms[wp]))
    write_report(results, kp_grid, ki_grid, out_md)
    print("报告:", out_md)


if __name__ == "__main__":
    main()
