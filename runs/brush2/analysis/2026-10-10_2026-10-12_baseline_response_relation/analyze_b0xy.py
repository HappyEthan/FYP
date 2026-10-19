"""Compare the magnitude of the active XY baseline with the stroke response."""
from pathlib import Path
import csv
import json

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np

from analyze import BASELINES, GROUPS, correlation, digest, frame, load

HERE = Path(__file__).resolve().parent


def draw_points(ax, rows):
    for key, label, color, marker, _, _ in GROUPS:
        group = [r for r in rows if r["group"] == key]
        ax.scatter([r["B0xy_uT"] for r in group],
                   [r["middle_response_mean_uT"] for r in group],
                   color=color, marker=marker, s=65, edgecolor="white", linewidth=.6, zorder=3)
    latest = [r for r in rows if r["group"] == "fixed_1012_reboot"]
    for r in latest:
        ax.annotate(f'12日#{r["repeat"]}', (r["B0xy_uT"], r["middle_response_mean_uT"]),
                    xytext=(6, 8), textcoords="offset points", color="#7e22ce", fontsize=10)
    x = np.array([r["B0xy_uT"] for r in latest])
    y = np.array([r["middle_response_mean_uT"] for r in latest])
    xfit = np.linspace(x.min(), x.max(), 80)
    ax.plot(xfit, np.polyval(np.polyfit(x, y, 1), xfit), color="#9333ea", ls="--", lw=1.1,
            alpha=.7)
    ax.set(xlabel="方向空载基线幅值 B0xy（µT）", ylabel="中段响应均值（µT）", ylim=(170, 405))
    ax.margins(x=.12)
    frame(ax)


def plot(rows, correlations):
    fig = plt.figure(figsize=(14.5, 10))
    grid = fig.add_gridspec(2, 2, left=.07, right=.945, bottom=.16, top=.815,
                            wspace=.29, hspace=.48, height_ratios=[1, 1.08])
    history = fig.add_subplot(grid[0, 0])
    response = history.twinx()
    order = [r["run_order"] for r in rows]
    history.plot(order, [r["B0xy_uT"] for r in rows], "o-", color="#2563eb", ms=4, lw=1.5)
    response.plot(order, [r["middle_response_mean_uT"] for r in rows], "s-", color="#ea580c", ms=4, lw=1.5)
    for group, short in zip(GROUPS, ("10日接触", "10日定高", "12日前3笔", "12日复位3笔")):
        _, _, color, _, lo, hi = group
        history.axvspan(lo - .5, hi + .5, color=color, alpha=.06)
        history.text((lo + hi) / 2, 1.04, short, transform=history.get_xaxis_transform(),
                     ha="center", fontsize=9)
    for x in (7.5, 13.5, 16.5):
        history.axvline(x, color="#cbd5e1", lw=1)
    history.set_title("A B0xy 与响应均值：逐笔对照", y=1.17)
    history.set(xlabel="两天实验顺序编号（1–19）", ylabel="B0xy（µT，左轴）",
                xlim=(.5, 19.5), ylim=(3500, 3720))
    response.set(ylabel="响应均值（µT，右轴）", ylim=(150, 410))
    history.set_xticks(order)
    history.tick_params(axis="y", colors="#2563eb")
    history.tick_params(axis="x", labelsize=9)
    response.tick_params(axis="y", colors="#ea580c")
    history.yaxis.label.set_color("#2563eb")
    response.yaxis.label.set_color("#ea580c")
    history.legend(handles=[Line2D([0], [0], color="#2563eb", marker="o", label="B0xy（左轴）"),
                            Line2D([0], [0], color="#ea580c", marker="s", label="响应（右轴）")],
                   loc="lower left", fontsize=8, ncol=2)
    frame(history)
    response.spines["top"].set_visible(False)

    all_scatter = fig.add_subplot(grid[0, 1])
    draw_points(all_scatter, rows)
    all_scatter.set_title("B 全部19笔：总体关系较弱", y=1.17)
    all_scatter.text(.03, .96,
                     f'全部19笔 r = {correlations["all_19"]["pearson_r"]:+.3f}\n'
                     f'定高12笔 r = {correlations["fixed_12"]["pearson_r"]:+.3f}',
                     transform=all_scatter.transAxes, va="top", fontsize=10,
                     bbox={"facecolor": "white", "edgecolor": "#e2e8f0", "alpha": .9, "pad": 5})

    fixed_scatter = fig.add_subplot(grid[1, 0])
    draw_points(fixed_scatter, rows[7:])
    fixed_scatter.set(title="C 相同运动参数的12笔：分组关系不同", ylim=(170, 375))
    fixed_scatter.text(.03, .96,
                       f'10日6笔 r = {correlations["fixed_1010_6"]["pearson_r"]:+.3f}\n'
                       f'12日6笔 r = {correlations["fixed_1012_6"]["pearson_r"]:+.3f}\n'
                       f'最新3笔 r = {correlations["latest_soft_reboot_3"]["pearson_r"]:+.3f}',
                       transform=fixed_scatter.transAxes, va="top", fontsize=10,
                       bbox={"facecolor": "white", "edgecolor": "#e2e8f0", "alpha": .9, "pad": 5})

    details = fig.add_subplot(grid[1, 1])
    details.axis("off")
    details.set_title("D 最新三笔：B0xy 越低，响应越高")
    latest = rows[-3:]
    table = details.table(
        cellText=[["B0xy", *[f'{r["B0xy_uT"]:.1f}' for r in latest]],
                  ["响应均值", *[f'{r["middle_response_mean_uT"]:.1f}' for r in latest]]],
        colLabels=["单位：µT", *[f'12日第{r["repeat"]}次' for r in latest]],
        colWidths=[.28, .24, .24, .24], cellLoc="center", bbox=[0, .58, 1, .36])
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    for (row, _), cell in table.get_celld().items():
        cell.set_edgecolor("#e2e8f0")
        if row == 0:
            cell.set_facecolor("#f1f5f9")
        else:
            cell.get_text().set_color("#2563eb" if row == 1 else "#ea580c")
    bxyrange = np.ptp([r["B0xy_uT"] for r in latest])
    response_range = np.ptp([r["middle_response_mean_uT"] for r in latest])
    details.text(0, .49,
                 f"B0xy 极差 {bxyrange:.1f} µT；响应均值极差 {response_range:.1f} µT\n\n"
                 "B0xy = √(B0x² + B0y²)\n"
                 "每帧响应 = ‖EMA(B − B0)xy‖，α = 0.3\n\n"
                 "响应先按分量减基线，再求 XY 幅值。\n"
                 "它不等于接触 Bxy 幅值减去 B0xy；方向变化也有影响。\n"
                 "最新只有3笔，强相关还不能推广或用于判定板子故障。",
                 transform=details.transAxes, va="top", fontsize=10.5, linespacing=1.35)

    fig.suptitle("空载基线幅值 B0xy 与行笔响应均值的关系", y=.974, fontsize=21)
    fig.text(.5, .925,
             "10月10日 + 10月12日，共19笔；使用每笔实际生效的方向基线1；响应均值取行笔中段10–40 mm",
             ha="center", fontsize=11, color="#475569")
    handles = [Line2D([0], [0], color="none", marker=marker, markerfacecolor=color,
                      markeredgecolor="white", markersize=8, label=label)
               for _, label, color, marker, _, _ in GROUPS]
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(.5, .071), ncol=4,
               frameon=False, fontsize=9)
    fig.text(.5, .044,
             "r 为 Pearson 相关系数；一个点代表一笔实验。紫色虚线只拟合最新3筆，用于展示这组三个数值的趋势。".replace("筆", "笔"),
             ha="center", fontsize=10, color="#475569")
    fig.text(.5, .018,
             "前7笔接触参数不同；其余12笔运动参数一致，但手调磁毛、纸面历史和复位状态有变化。相关性不等于因果关系。",
             ha="center", fontsize=10, color="#475569")
    fig.savefig(HERE / "b0xy_response_relation.png", dpi=180, facecolor="white")
    plt.close(fig)


def main():
    evidence = json.loads(BASELINES.read_text())
    baselines = {r["run_order"]: r for r in evidence["all_baselines"] if r["baseline_id"] == 1}
    rows = [load(info, baselines[info["run_order"]]) for info in evidence["run_inventory"]]
    assert len(rows) == 19
    previous = json.loads((HERE / "summary.json").read_text())
    for row, prev in zip(rows, previous["runs"]):
        assert row["run_name"] == prev["run_name"]
        assert abs(row["middle_response_mean_uT"] - prev["middle_response_mean_uT"]) < 1e-8
        row["B0xy_uT"] = float(np.hypot(row["baseline_Bx_uT"], row["baseline_By_uT"]))
    cohorts = {"all_19": rows, "fixed_12": rows[7:], "fixed_1010_6": rows[7:13],
               "fixed_1012_6": rows[13:], "latest_soft_reboot_3": rows[-3:]}
    correlations = {name: correlation([r["B0xy_uT"] for r in group],
                                      [r["middle_response_mean_uT"] for r in group])
                    for name, group in cohorts.items()}
    full_window = {name: correlation([r["B0xy_uT"] for r in group],
                                     [r["full_straight_response_mean_uT"] for r in group])
                   for name, group in cohorts.items()}
    summary = {"run_count": len(rows), "baseline_id": 1,
               "baseline_input": str(BASELINES), "baseline_input_sha256": digest(BASELINES),
               "baseline_definition": "B0xy = hypot(B0x, B0y), where B0x and B0y are the means in the accepted directional baseline window. This is the norm of the baseline vector, not the mean of per-frame baseline norms.",
               "response_definition": "Mean of a_control_uT for straight_hold commanded distance 10–40 mm inclusive, 151 control points per trial. Per-frame response = norm_xy(EMA(B-B0)), alpha 0.3. It is not norm_xy(B)-norm_xy(B0).",
               "verification": previous["verification"],
               "correlations": correlations,
               "full_straight_window_sensitivity_correlations": full_window,
               "limitations": previous["limitations"], "runs": rows}
    (HERE / "b0xy_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    columns = ["run_order", "date", "time", "experiment", "repeat", "group", "B0xy_uT",
               "baseline_Bx_uT", "baseline_By_uT", "middle_response_mean_uT", "middle_points",
               "full_straight_response_mean_uT", "run_dir"]
    with (HERE / "b0xy_paired_metrics.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    lines = ["B0xy基线幅值与实验响应均值关系", "",
             "B0xy = sqrt(B0x^2+B0y^2)，取实际生效的方向基线1。响应均值取行笔中段10–40 mm，单位µT。",
             "响应按向量扣基线后求XY范数；不等于两个XY幅值直接相减。", "",
             "组别 | n | Pearson r | Spearman rho"]
    for name, c in correlations.items():
        lines.append(f'{name} | {c["n"]} | {c["pearson_r"]:+.6f} | {c["spearman_rho"]:+.6f}')
    lines += ["", "最新三笔 | B0xy (µT) | 响应均值 (µT)"]
    for r in rows[-3:]:
        lines.append(f'{r["repeat"]} | {r["B0xy_uT"]:.6f} | {r["middle_response_mean_uT"]:.6f}')
    lines += ["", "最新三笔B0xy与响应呈明显负相关，但只有3笔。全部19笔和运动参数一致的12笔，总体相关均较弱。",
              "不能单由B0xy大小决定响应；基线与接触磁场的方向和相对位置也影响向量差的幅值。",
              "这不单独证明板子故障或基线采集错误；操作变化、纸面历史及复位状态未分离。"]
    (HERE / "b0xy_report.txt").write_text("\n".join(lines) + "\n")
    plot(rows, correlations)
    print(json.dumps({"verified_runs": len(rows), "max_ema_error_uT": max(r["ema_replay_max_error_uT"] for r in rows),
                      "correlations": correlations, "latest": [{k: r[k] for k in ("repeat", "B0xy_uT", "middle_response_mean_uT")} for r in rows[-3:]],
                      "figure": str(HERE / "b0xy_response_relation.png")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
