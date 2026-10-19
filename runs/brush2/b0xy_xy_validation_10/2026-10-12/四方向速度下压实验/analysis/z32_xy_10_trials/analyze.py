"""Plot the ten completed Z32 trials, highlighting the four new +Y trials."""
from pathlib import Path
import csv
import importlib.util
import json

import numpy as np

HERE = Path(__file__).resolve().parent
HELPER = HERE.parent / "z32_xy" / "analyze.py"
spec = importlib.util.spec_from_file_location("z32_six_trial_loader", HELPER)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
plt = helper.plt
OLD_SCOPE = json.loads((HELPER.parent / "scope.json").read_text())
NEW_NAMES = [
    "18-45-32_定高_up_Z32到32_速度10_第4次",
    "18-46-35_定高_up_Z32到32_速度10_第5次",
    "18-47-11_定高_up_Z32到32_速度10_第6次",
    "18-47-47_定高_up_Z32到32_速度10_第7次",
]


def main():
    names = OLD_SCOPE["runs"] + NEW_NAMES
    runs = [helper.load(name) for name in names]
    rows = [run["metric"] for run in runs]
    assert len(rows) == 10 and all(r["command_z_mm"] == 32 for r in rows)
    assert len({r["setup_sha256"] for r in rows}) == 1
    assert all({k: v for k, v in r["profile"].items() if k != "direction"} ==
               {k: v for k, v in rows[0]["profile"].items() if k != "direction"} for r in rows)
    subsets = {axis: [run for run in runs if run["metric"]["axis"] == axis] for axis in "XY"}
    assert len(subsets["X"]) == 3 and len(subsets["Y"]) == 7
    groups = {axis: helper.stats([run["metric"]["middle_mean_uT"] for run in subset])
              for axis, subset in subsets.items()}
    correlations = {}
    for axis, subset in subsets.items():
        x = [run["metric"]["B0xy_uT"] for run in subset]
        y = [run["metric"]["middle_mean_uT"] for run in subset]
        correlations[axis] = {"n": len(x), "pearson_r": float(np.corrcoef(x, y)[0, 1]),
                              "spearman_rho": float(np.corrcoef(helper.rank(x), helper.rank(y))[0, 1])}
    new_rows = rows[-4:]
    new_stats = helper.stats([r["middle_mean_uT"] for r in new_rows])
    new_r = float(np.corrcoef([r["B0xy_uT"] for r in new_rows],
                             [r["middle_mean_uT"] for r in new_rows])[0, 1])
    summary = {
        "run_count": 10, "new_run_names": NEW_NAMES, "runs": rows,
        "group_middle_statistics": groups, "B0xy_response_correlations": correlations,
        "new_four_Y_statistics": new_stats, "new_four_Y_pearson_r": new_r,
        "method": "Same validated loader as previous six-trial analysis: active direction baseline id=1, B0xy=norm(mean baseline XY vector), response=mean(norm_xy(EMA(B-B0))) with alpha 0.3 over direction-projected command path 10–40mm, 151 controls per trial. Baselines and EMA replay verified against original sensor.csv; all recorded source snapshot hashes checked.",
        "helper_path": str(HELPER), "helper_sha256": helper.sha(HELPER),
        "operator_context_previous_six": OLD_SCOPE["operator_context"],
        "operator_context_new_four": "Not separately confirmed; no assumption about paper, water or hand adjustment.",
        "limitations": ["Unbalanced directions: X n=3, Y n=7.",
                        "Four new Y trials form a later batch after an approximately 46-minute gap; pooled correlation can reflect batch differences.",
                        "Correlations are descriptive and cannot establish cause or diagnose board faults."],
    }
    (HERE / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    columns = ["axis", "repeat", "time", "B0xy_uT", "middle_mean_uT", "middle_sample_std_uT", "reboot_duration_s", "actual_middle_z_mean_mm", "actual_middle_z_range_mm", "raw_folder"]
    with (HERE / "per_run_metrics.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    fig, axes = plt.subplots(2, 3, figsize=(16, 9.5))
    fig.subplots_adjust(left=.06, right=.985, bottom=.1, top=.85, wspace=.32, hspace=.38)
    palettes = {"X": helper.COLORS, "Y": list(plt.get_cmap("tab10").colors[:7])}
    ymax = max(float(run["response"].max()) for run in runs) * 1.14
    for j, axis in enumerate("XY"):
        subset = subsets[axis]
        for run, color in zip(subset, palettes[axis]):
            row = run["metric"]
            new = row["run_name"] in NEW_NAMES
            axes[0, j].plot(run["distance"], run["response"], color=color,
                            lw=1.7 if new else 1.2, ls="-" if new or axis == "X" else "--",
                            alpha=1 if new or axis == "X" else .65,
                            label=f'{axis}{row["repeat"]}{" 新增" if new else ""}：{row["middle_mean_uT"]:.1f}')
        axes[0, j].axvspan(10, 40, color="#94a3b8", alpha=.1)
        axes[0, j].set(title=f'{"AB"[j]} +{axis} 响应曲线（{len(subset)}笔）', xlim=(0, 50), ylim=(0, ymax),
                       xlabel="沿本方向的命令行程（mm）", ylabel="响应幅值（µT）")
        axes[0, j].legend(loc="lower right", fontsize=8.5, ncol=2 if axis == "Y" else 1)
        helper.frame(axes[0, j])
        scatter = axes[1, j]
        x = [run["metric"]["B0xy_uT"] for run in subset]
        y = [run["metric"]["middle_mean_uT"] for run in subset]
        for run, bx, response, color in zip(subset, x, y, palettes[axis]):
            row = run["metric"]
            new = row["run_name"] in NEW_NAMES
            scatter.scatter(bx, response, color=color, marker="*" if new else "o",
                            s=140 if new else 60, zorder=3)
            scatter.annotate(f'{axis}{row["repeat"]}', (bx, response), xytext=(6, 5),
                             textcoords="offset points", color=color, fontsize=9)
        fit_x = np.linspace(min(x), max(x), 100)
        scatter.plot(fit_x, np.polyval(np.polyfit(x, y, 1), fit_x), color="#64748b", ls="--", lw=1)
        scatter.set(title=f'{"DE"[j]} +{axis}：B0xy 与响应均值', xlabel="空载方向基线 B0xy（µT）",
                    ylabel="中段响应均值（µT）", ylim=(0, ymax))
        scatter.margins(x=.17)
        scatter.text(.04, .97, f'n={len(x)}；Pearson r={correlations[axis]["pearson_r"]:+.3f}',
                     transform=scatter.transAxes, va="top", fontsize=10,
                     bbox={"facecolor": "white", "edgecolor": "#e2e8f0", "alpha": .9, "pad": 4})
        helper.frame(scatter)

    labels = [f'{r["axis"]}{r["repeat"]}' for r in rows]
    values = [r["middle_mean_uT"] for r in rows]
    bar = axes[0, 2]
    colors = ["#cbd5e1"] * 6 + palettes["Y"][3:]
    bar.bar(range(10), values, color=colors, width=.7)
    bar.axvline(2.5, color="#94a3b8", lw=1)
    bar.axvline(5.5, color="#64748b", lw=1, ls="--")
    for i, value in enumerate(values):
        bar.text(i, value + ymax*.025, f'{value:.1f}', ha="center", rotation=90, fontsize=8.5)
    bar.set_xticks(range(10), labels, rotation=35)
    bar.set(title="C 十笔中段均值：彩色为新增4笔", ylabel="响应均值（µT）", ylim=(0, ymax*1.07))
    helper.frame(bar)
    table_ax = axes[1, 2]
    table_ax.axis("off")
    table_ax.set_title("F 新增4笔（均为 +Y）")
    table = table_ax.table(cellText=[[f'Y{r["repeat"]}', r["time"], f'{r["B0xy_uT"]:.2f}', f'{r["middle_mean_uT"]:.2f}'] for r in new_rows],
                          colLabels=["实验", "时间", "B0xy", "响应均值"], cellLoc="center", bbox=[0, .31, 1, .6])
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor("#e2e8f0")
        if row == 0:
            cell.set_facecolor("#f1f5f9")
    table_ax.text(.01, .19, f'新增4笔：均值 {new_stats["mean"]:.2f} µT；CV {new_stats["cv_pct"]:.1f}%\n'
                  f'仅新增4笔：B0xy—响应 r={new_r:+.3f}', transform=table_ax.transAxes, fontsize=10, va="top")
    table_ax.text(.01, .04, f'全部X：CV {groups["X"]["cv_pct"]:.1f}%\n全部Y：CV {groups["Y"]["cv_pct"]:.1f}%',
                  transform=table_ax.transAxes, fontsize=10, va="top")
    fig.suptitle("Z32 实验更新｜共10笔：+X 3笔，+Y 7笔", fontsize=22, y=.976)
    fig.text(.5, .91, "新增18:45–18:47的Y4–Y7；星号为新增点；均值统一取10–40 mm；10 mm/s，50 mm", ha="center", fontsize=12, color="#475569")
    fig.text(.5, .035, "响应 = ‖EMA(B − B0)xy‖，α=0.3，单位µT。X/Y分别统计；前后批次相隔约46分钟，相关系数只作描述。", ha="center", fontsize=10, color="#475569")
    fig.savefig(HERE / "z32_10_trials_overview.png", dpi=180, facecolor="white")
    plt.close(fig)
    print(json.dumps({"new_trials": [{"label": f'Y{r["repeat"]}', "B0xy_uT": r["B0xy_uT"], "response_uT": r["middle_mean_uT"]} for r in new_rows],
                      "correlations": correlations, "new_four_CV_pct": new_stats["cv_pct"], "new_four_r": new_r,
                      "group_CV_pct": {axis: val["cv_pct"] for axis, val in groups.items()},
                      "all_reboots_successful": True, "output": str(HERE / "z32_10_trials_overview.png")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
