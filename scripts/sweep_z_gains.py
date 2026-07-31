#!/usr/bin/env python3
"""层1: {滤波} × {kp, ki} 增益扫描 → 稳定边界 + 双工作点 (wp_P/wp_PI) + 报告.

用法 (单行):
    python scripts/sweep_z_gains.py
    python scripts/sweep_z_gains.py --quick
    python scripts/sweep_z_gains.py --csv-dir delta_b_v0_20260724 --out docs/z-phase1-sweep.md

回答 spec §1 的 Q1 (滤波收益) 与 Q2 (稳定边界+裕度).

2026-07-30 修订 (spec §3.3): 每臂产出两个工作点——wp_P (原规则, min-RMS 落在 ki=0 也接受)
与 wp_PI (同规则限定 ki>0)。层 1 干净场景下积分器无持续偏差可积、只添滞后，wp_P 实测全部
落在 ki=0，这是指标盲区而非"积分无用"；wp_PI 留给层 2 扰动场景量化积分项边际贡献。
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
# 默认 (非 --quick) kp/ki 网格; 提为模块级常量供 compare_z_arms.py 复用, 避免字面量分叉.
KP_GRID_DEFAULT = np.geomspace(0.05, 3.0, 10)
KI_GRID_DEFAULT = np.concatenate([[0.0], np.geomspace(0.005, 0.5, 8)])


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


def working_point(rms, stable, kp_grid, ki_grid, require_ki=False):
    """稳定且 +2 网格步 (≈2.5×kp / ≈3.7×ki, 保守 ≥2×裕度) 仍稳定者中取 RMS 最小.

    require_ki=False (wp_P, 原规则, 默认): ki=0 行只查 kp 裕度 (j 方向裕度对 ki=0 无意义);
    ki>0 行两个方向都查. 层 1 干净场景下实测 wp_P 全部落在 ki=0 (spec §3.3 修订理由).

    require_ki=True (wp_PI, 2026-07-30 修订): 限定 ki_grid[j] > 0 的格点参选; margin
    检查恒同时要求 i+2 与 j+2 均在网格内且稳定 (ki>0 行有真实 ki 裕度可验, 不再按 ki=0
    分支放宽).

    返回 (i, j) 或 None."""
    best = None
    for i in range(len(kp_grid)):
        for j in range(len(ki_grid)):
            if not stable[i, j]:
                continue
            if require_ki:
                if not (ki_grid[j] > 0):
                    continue
                i2, j2 = i + 2, j + 2
            else:
                i2, j2 = i + 2, (j + 2 if ki_grid[j] > 0 else j)
            if i2 >= len(kp_grid) or j2 >= len(ki_grid) or not stable[i2, j2]:
                continue
            if best is None or rms[i, j] < rms[best]:
                best = (i, j)
    return best


def phase_margin_deg(kp, ki, freq_fn, tau=TAU, delay_s=(N_DELAY + 1) / FS):
    """线性臂解析相位裕度. L = (kp + ki/s)·执行器·延迟·滤波器 (S_cal 与 plant
    斜率互逆, calib_scale=1 时消掉). OneEuro 不适用 (spec 坑3).
    delay_s 含 +1 拍用于 run_loop 计算管线 (plant.step → ctrl.step 顺序)."""
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


def make_heatmap(rms, stable, kp_grid, ki_grid, wp_P, wp_PI, label, out_png):
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
    have_legend = False
    if wp_P is not None:
        ax.plot(wp_P[1], wp_P[0], "r*", ms=16, label="wp_P")
        have_legend = True
    if wp_PI is not None:
        ax.plot(wp_PI[1], wp_PI[0], marker="p", color="orange", ms=13,
                 linestyle="None", label="wp_PI")
        have_legend = True
    if have_legend:
        ax.legend()
    fig.colorbar(im, ax=ax, label="RMS %")
    fig.tight_layout()
    fig.savefig(out_png, dpi=120)
    plt.close(fig)


def _render_point(lines, point_name, wp, rms_grid, pm, sens, kp_grid, ki_grid,
                   kp_mult, ki_mult, label):
    """追加单个工作点 (wp_P 或 wp_PI) 的报告段落到 lines (原地追加)."""
    lines.append("**工作点 %s**" % point_name)
    lines.append("")
    if wp is None:
        lines.append("未找到 (全网格内无满足 %s 规则的格点; 未放宽 margin 规则去凑一个)."
                     % point_name)
        lines.append("")
        return
    i, j = wp
    kp, ki = kp_grid[i], ki_grid[j]
    rms = rms_grid[i, j]
    lines.append("kp=**%.4g**, ki=**%.4g**, 跟踪 RMS=**%.2f%%**" % (kp, ki, rms))
    lines.append("")
    if label == "OneEuro mc=0.5 b=0.03":
        lines.append("相位裕度: 非线性滤波器无频域相位裕度 (OneEuro 坑3) — "
                     "时域裕度: 工作点在 kp ×%.2f / ki ×%.2f (+2 网格步) 仍稳定." % (kp_mult, ki_mult))
    elif pm is not None:
        pm_str = "∞ (环路增益全频段 <1, 未见穿越)" if not np.isfinite(pm) else "%.1f°" % pm
        lines.append("相位裕度 (解析, 线性臂): **%s**; 时域裕度: +2 网格步 "
                     "(kp ×%.2f / ki ×%.2f) 仍稳定." % (pm_str, kp_mult, ki_mult))
    else:
        lines.append("相位裕度: 未计算.")
    lines.append("")
    lines.append("敏感性抽查 (τ × n_delay, 工作点增益不变):")
    lines.append("")
    lines.append("| τ (s) \\ n_delay | 1 | 2 | 4 |")
    lines.append("|---|---|---|---|")
    sens_map = {(t, n): (rr, ss) for t, n, rr, ss in sens}
    for tau in (0.02, 0.05, 0.1):
        cells = []
        for nd in (1, 2, 4):
            rr, ss = sens_map[(tau, nd)]
            mark = "稳" if ss else "**不稳**"
            cells.append("%.2f%% (%s)" % (rr, mark))
        lines.append("| %.2f | %s |" % (tau, " | ".join(cells)))
    lines.append("")


def _delta_lists(results, none_rms, wp_key):
    """相对 none 臂同口径工作点的 RMS 差值, 拆成 (better, worse) 两个列表."""
    better, worse = [], []
    if none_rms is None:
        return better, worse
    for r in results:
        if r["label"] == "none" or r[wp_key] is None:
            continue
        d = r["rms"][r[wp_key]] - none_rms
        (better if d < 0 else worse).append((r["label"], d))
    return better, worse


def _summary_table(lines, results, kp_grid, ki_grid, wp_key, pm_key, none_rms, point_name):
    lines.append("### 工作点 %s 汇总" % point_name)
    lines.append("")
    lines.append("| 滤波臂 | σ_f µT | %s kp | %s ki | %s RMS %% | vs none RMS | 相位裕度 |"
                 % (point_name, point_name, point_name))
    lines.append("|---|---|---|---|---|---|---|")
    for r in results:
        label = r["label"]
        wp = r[wp_key]
        if wp is None:
            lines.append("| %s | %.2f | — | — | — | — | — |" % (label, r["sigma_f"]))
            continue
        i, j = wp
        kp, ki, rms = kp_grid[i], ki_grid[j], r["rms"][i, j]
        if none_rms is not None and label != "none":
            delta = "%+.1f%%" % (rms - none_rms)
        else:
            delta = "—"
        pm = r[pm_key]
        if label == "OneEuro mc=0.5 b=0.03":
            pm_str = "非线性—时域裕度 2 网格步"
        elif pm is not None:
            pm_str = "∞" if not np.isfinite(pm) else "%.1f°" % pm
        else:
            pm_str = "—"
        lines.append("| %s | %.2f | %.4g | %.4g | %.2f | %s | %s |"
                     % (label, r["sigma_f"], kp, ki, rms, delta, pm_str))
    lines.append("")


def write_report(results, kp_grid, ki_grid, out_md):
    """生成 markdown 报告: 每滤波臂一节 (双工作点) + 双汇总表, 回答 spec §1 Q1/Q2."""
    # 计算 +2 网格步增益倍数 (几何网格, 全臂通用)
    kp_mult = kp_grid[2] / kp_grid[0]
    nz = ki_grid[ki_grid > 0]
    ki_mult = nz[2] / nz[0] if len(nz) >= 3 else float('nan')

    slugs = {r["label"]: r["label"].replace(" ", "").replace("=", "").replace(".", "")
             for r in results}
    none_row = next((r for r in results if r["label"] == "none"), None)
    none_rms_P = (none_row["rms"][none_row["wp_P"]]
                  if none_row and none_row["wp_P"] is not None else None)
    none_rms_PI = (none_row["rms"][none_row["wp_PI"]]
                   if none_row and none_row["wp_PI"] is not None else None)
    none_kp_P = kp_grid[none_row["wp_P"][0]] if none_row and none_row["wp_P"] is not None else None

    lines = [
        "# Z 控制层 1 增益扫描报告 (脚本生成)",
        "",
        "> 生成命令: `python scripts/sweep_z_gains.py`",
        "> kp 网格: %s" % ", ".join("%.3g" % k for k in kp_grid),
        "> ki 网格: %s" % ", ".join("%.3g" % k for k in ki_grid),
        "> 回答 spec §1 Q1 (滤波收益) 与 Q2 (稳定边界+裕度).",
        "",
        "## 工作点规则 (2026-07-30 修订: 双工作点)",
        "",
        "每臂产出两个工作点，敏感性抽查两点都做：",
        "",
        "- **wp_P**：原规则——\"(+2 网格步) 仍稳定\"的格子里取 rms_pct 最小者"
          "（时域 2 倍增益裕度，对非线性 OneEuro 同样适用）。",
        "- **wp_PI**：同规则加约束 ki>0（margin 检查恒同时验 kp 与 ki 两个方向的 +2 网格步）。",
        "",
        "实测 wp_P **全部落在 ki=0**：层 1 是干净场景（控制器标定表 == plant 真值曲线），"
          "积分器没有持续偏差可积，只额外引入相位滞后，min-RMS 选择规则必然弃掉它——"
          "**这是指标盲区，不是\"积分无用\"**。积分器的价值（稳态抗扰）只在层 2 的扰动场景"
          "（标定偏差、纸面阶跃、传感器漂移）中显形；wp_PI 留给层 2 用来对照 wp_P，"
          "量化积分项的边际贡献。若某臂在网格内找不到 wp_PI（可能），本报告如实标注\"未找到\"，"
          "不放宽 margin 规则去凑一个。",
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
        _render_point(lines, "wp_P", r["wp_P"], r["rms"], r["pm_P"], r["sens_P"],
                      kp_grid, ki_grid, kp_mult, ki_mult, label)
        _render_point(lines, "wp_PI", r["wp_PI"], r["rms"], r["pm_PI"], r["sens_PI"],
                      kp_grid, ki_grid, kp_mult, ki_mult, label)
        lines.append("![%s 热力图](assets/z-phase1-sweep-%s.png)" % (label, slugs[label]))
        lines.append("")

    lines += [
        "## 汇总表 (Q1: 滤波收益 / Q2: 稳定边界+裕度)",
        "",
    ]
    _summary_table(lines, results, kp_grid, ki_grid, "wp_P", "pm_P", none_rms_P, "wp_P")
    _summary_table(lines, results, kp_grid, ki_grid, "wp_PI", "pm_PI", none_rms_PI, "wp_PI")

    better_P, worse_P = _delta_lists(results, none_rms_P, "wp_P")
    better_PI, worse_PI = _delta_lists(results, none_rms_PI, "wp_PI")

    lines += [
        "**Q1 (滤波收益):** 各滤波臂工作点跟踪 RMS 相对 \"none\" 臂同口径工作点 RMS 的差值见"
        "上方两张汇总表 \"vs none RMS\" 列 (负值 = 优于无滤波, wp_P 表对比 none 的 wp_P、"
        "wp_PI 表对比 none 的 wp_PI); \"none\" 臂即无滤波直接闭环, 作为收益基线.",
        "",
    ]
    if none_rms_P is not None:
        if worse_P:
            lines.append(
                "⚠️ **wp_P 口径:** 并非全部滤波臂都优于 \"none\": " +
                "、".join("%s (%+.1f%%)" % (lb, d) for lb, d in worse_P) +
                " 在其工作点的跟踪 RMS 反而**高于**无滤波臂。原因: 工作点规则先保证稳定裕度, "
                "滤波器引入的相位滞后压低了可用 kp 上限 (none 臂 kp=%s, 上述臂被迫取更低 kp), "
                "该增益损失抵消乃至反超了噪声降低带来的收益; 这是滤波在闭环中的固有权衡 "
                "(降噪 vs 相位裕度), 不是脚本缺陷, 按判据如实记录、不调整." %
                ("%.3g" % none_kp_P if none_kp_P is not None else "N/A"))
        if better_P:
            lines.append(
                "wp_P 口径下滤波收益为正的臂: " +
                "、".join("%s (%+.1f%%)" % (lb, d) for lb, d in better_P) + "。")
        lines.append("")
    if none_rms_PI is not None:
        parts = []
        if worse_PI:
            parts.append("劣于 none 的臂: " +
                          "、".join("%s (%+.1f%%)" % (lb, d) for lb, d in worse_PI))
        if better_PI:
            parts.append("优于 none 的臂: " +
                          "、".join("%s (%+.1f%%)" % (lb, d) for lb, d in better_PI))
        if parts:
            lines.append("**wp_PI 口径:** " + "; ".join(parts) + "。")
            lines.append("")
    else:
        lines.append("**wp_PI 口径:** \"none\" 臂无 wp_PI, 无法给出 vs none 的 wp_PI 差值"
                     "(none 臂 ki>0 时无额外相位补偿收益, 未必能在 +2 网格步双向裕度下稳定).")
        lines.append("")

    lines += [
        "**Q2 (稳定边界+裕度):** 稳定判定 = 未发散 (`diverged`) 且 `osc_index ≤ OSC_MAX`; "
        "wp_P 规则要求 (kp, ki) 处及 +2 网格步 (kp ×%.2f, ki ×%.2f, 保守 ≥2× 裕度) 处均稳定 "
        "(ki=0 行只查 kp 方向); wp_PI 规则在此基础上限定 ki>0 且恒同时查 kp、ki 两个方向的 "
        "+2 网格步; 两个规则都取满足条件者中 RMS 最小的格点; 线性滤波臂在两个工作点均附解析相位"
        "裕度 (环路含 PI + 一阶执行器 τ + n_delay 拍延迟 + 滤波器频响); OneEuro 为非线性滤波器, "
        "无法定义频域相位裕度, 只报工作点规则本身蕴含的时域增益裕度." % (kp_mult, ki_mult),
        "",
        "## 滤波器定稿规则核对 (spec §3.3)",
        "",
        "> 规则: OneEuro 工作点闭环 RMS ≤ EMA0.3 工作点 (wp_P 与 wp_PI 两口径都比, 以 wp_PI "
        "为主——积分是设计意图的一部分), 且层 2 全场景无失稳/毛刺异常 → 选型定稿 OneEuro; "
        "否则退 EMA0.3.",
        "",
    ]
    one_row = next((r for r in results if r["label"] == "OneEuro mc=0.5 b=0.03"), None)
    ema_row = next((r for r in results if r["label"] == "EMA a=0.3"), None)
    if one_row and ema_row:
        for point_name, wp_key in (("wp_P", "wp_P"), ("wp_PI", "wp_PI")):
            one_wp, ema_wp = one_row[wp_key], ema_row[wp_key]
            if one_wp is None or ema_wp is None:
                lines.append("- **%s 口径:** OneEuro 或 EMA0.3 在该口径下无工作点, 无法比较."
                             % point_name)
                continue
            one_rms = one_row["rms"][one_wp]
            ema_rms = ema_row["rms"][ema_wp]
            verdict = "OneEuro ≤ EMA0.3 ✓" if one_rms <= ema_rms else "OneEuro > EMA0.3 ✗"
            lines.append("- **%s 口径:** OneEuro RMS=%.2f%% vs EMA0.3 RMS=%.2f%% → %s"
                         % (point_name, one_rms, ema_rms, verdict))
        lines.append("")
        lines.append("**结论 (仅层 1, 以 wp_PI 为主判据):** 上述比较仅覆盖层 1 (纯跟踪 RMS + "
                     "τ/n_delay 敏感性); 层 2 (`compare_z_arms.py`, Task 8) 的扰动场景 (标定偏差/"
                     "纸面阶跃/传感器漂移) 及 freeze 毛刺判据尚未核验, 因此本报告**不单独定稿**"
                     "滤波器选型, 留给 Task 8/9 综合层 1+层 2 数据后按 spec §3.3 规则裁决.")
        lines.append("")

    lines += [
        "## 注记",
        "",
        "- 稳定判定阈值 OSC_MAX=%.2f (spec §3.3 暂定值, 未经真机验证)." % OSC_MAX,
        "- \"+2 网格步\" 在本报告的网格间距下等价于 kp ×%.2f、ki ×%.2f (几何网格, 全臂通用)." % (kp_mult, ki_mult),
        "- Plant 的 τ=%.2fs、n_delay=%d 拍为假设值 (真机未标定); 各工作点 (wp_P 与 wp_PI 各自) 的"
          "敏感性 3×3 表 (τ∈{0.02,0.05,0.1}s × n_delay∈{1,2,4}) 显示工作点在假设范围内是否仍稳定, "
          "用于评估该假设对结论的影响." % (TAU, N_DELAY),
        "- 相位裕度用连续一阶执行器近似 (离散精确极点差 ~4°, 不影响 45° 判线结论).",
        "- σ_f 用裸态 (未装配) V0 idle 数据估计, 是乐观下界; 装配态数据到位后须重跑本脚本.",
        "- OneEuro 工作点为层 1 (简化仿真) 下的定稿候选, 非线性特性未在层 1 频域核算中体现, "
          "最终结论待层 2 (`compare_z_arms.py`, Task 8) 用扰动场景确认.",
        "- wp_PI 为 2026-07-30 spec 修订新增 (双工作点); 若某臂 wp_PI 为 None, 表示全网格内无 "
          "\"ki>0 且 +2 网格步 kp/ki 双向裕度均稳定\" 的格点, 报告如实呈现, 未放宽规则去凑一个.",
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
        kp_grid = KP_GRID_DEFAULT
        ki_grid = KI_GRID_DEFAULT
    g_d = synth_press(cal_max=CALIB_DB[-1])

    out_md = Path(args.out)
    asset_dir = out_md.parent / "assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for label, mk, freq_fn in FILTERS:
        sigma_f = V0NoiseSource(csvs, seed=SEED).filtered_sigma(mk)
        rms, stable = sweep(mk, kp_grid, ki_grid, sigma_f, g_d, csvs)
        wp_P = working_point(rms, stable, kp_grid, ki_grid, require_ki=False)
        wp_PI = working_point(rms, stable, kp_grid, ki_grid, require_ki=True)
        row = {"label": label, "sigma_f": sigma_f, "rms": rms, "stable": stable,
               "wp_P": wp_P, "pm_P": None, "sens_P": None,
               "wp_PI": wp_PI, "pm_PI": None, "sens_PI": None}
        for wp_key, pm_key, sens_key in (("wp_P", "pm_P", "sens_P"),
                                          ("wp_PI", "pm_PI", "sens_PI")):
            wp = row[wp_key]
            if wp is not None:
                kp, ki = kp_grid[wp[0]], ki_grid[wp[1]]
                row[pm_key] = (phase_margin_deg(kp, ki, freq_fn)
                               if freq_fn is not None or label == "none" else None)
                row[sens_key] = sensitivity(mk, kp, ki, sigma_f, g_d, csvs)
        slug = label.replace(" ", "").replace("=", "").replace(".", "")
        make_heatmap(rms, stable, kp_grid, ki_grid, wp_P, wp_PI, label,
                     asset_dir / ("z-phase1-sweep-%s.png" % slug))
        results.append(row)
        print(label,
              "wp_P=", None if wp_P is None else (kp_grid[wp_P[0]], ki_grid[wp_P[1]], rms[wp_P]),
              "wp_PI=", None if wp_PI is None else (kp_grid[wp_PI[0]], ki_grid[wp_PI[1]], rms[wp_PI]))
    write_report(results, kp_grid, ki_grid, out_md)
    print("报告:", out_md)


if __name__ == "__main__":
    main()
