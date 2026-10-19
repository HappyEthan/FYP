"""Pair each accepted directional baseline with the same stroke window; no hardware I/O."""
from pathlib import Path
import csv
import hashlib
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.ticker import ScalarFormatter
import numpy as np

HERE = Path(__file__).resolve().parent
BASELINES = HERE.parent / "2026-10-10_2026-10-12_all_baselines/summary.json"
FONT = Path("/usr/local/share/fonts/msyh.ttf")
if FONT.exists():
    font_manager.fontManager.addfont(str(FONT))
plt.rcParams.update({"font.family": "Microsoft YaHei", "axes.unicode_minus": False,
                     "font.size": 11, "axes.titlesize": 13, "legend.fontsize": 9})
GROUPS = [
    ("contact_1010", "10日接触参数测试（7笔）", "#94a3b8", "s", 1, 7),
    ("fixed_1010", "10日定高（6笔）", "#2563eb", "o", 8, 13),
    ("fixed_1012_before", "12日前三笔（操作有变化）", "#d97706", "^", 14, 16),
    ("fixed_1012_reboot", "12日每笔软复位（3笔）", "#9333ea", "D", 17, 19),
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rank(values):
    values = np.asarray(values)
    return np.array([np.sum(values < x) + (np.sum(values == x) - 1) / 2 + 1
                     for x in values], dtype=float)


def correlation(x, y):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    assert len(x) == len(y) >= 3 and np.isfinite(x).all() and np.isfinite(y).all()
    return {"n": len(x), "pearson_r": float(np.corrcoef(x, y)[0, 1]),
            "spearman_rho": float(np.corrcoef(rank(x), rank(y))[0, 1])}


def load(info, baseline):
    folder = Path(info["run_dir"])
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["status"] == "completed"
    assert digest(folder / "manifest.json") == info["manifest_sha256"]
    assert digest(folder / "sensor.csv") == info["sensor_sha256"]
    for name, expected in manifest["sha256"].items():
        assert digest(folder / name) == expected, (folder.name, name)
    setup_path = folder / ("setup.json" if (folder / "setup.json").exists() else "settings.json")
    setup = json.loads(setup_path.read_text())
    alpha = setup["filter"]["alpha"]
    assert alpha == .3
    b0 = np.array([baseline[f"B0{axis}_uT"] for axis in "xyz"])
    active = next(b for b in manifest["baselines"] if b["baseline_id"] == 1)
    assert np.max(np.abs(b0 - active["B0_uT"])) < 1e-8
    with (folder / "sensor.csv").open() as stream:
        sensors = list(csv.DictReader(stream))
    assert all(row["valid"] == "true" for row in sensors)
    accepted = [row for row in sensors if active["first_seq"] <= int(row["seq"]) <= active["last_seq"]]
    baseline_raw = np.array([[float(row[f"B{axis}_uT"]) for axis in "xyz"] for row in accepted])
    assert np.max(np.abs(baseline_raw.mean(axis=0) - b0)) < 1e-8
    assert np.max(np.abs(baseline_raw.std(axis=0) - active["std_uT"])) < 1e-8
    filtered, vectors, raw = None, {}, {}
    for row in sensors:
        if row["baseline_id"] != "1":
            continue
        value = np.array([float(row[f"dB{axis}_uT"]) for axis in "xyz"])
        original = np.array([float(row[f"B{axis}_uT"]) for axis in "xyz"])
        assert np.max(np.abs(original - b0 - value)) < 1e-8
        filtered = value if filtered is None else alpha * value + (1 - alpha) * filtered
        vectors[int(row["seq"])] = filtered.copy()
        raw[int(row["seq"])] = original
    controls = [json.loads(line) for line in (folder / "control.jsonl").read_text().splitlines()]
    straight = [row for row in controls if row["phase"] == "straight_hold"]
    distance = np.array([row.get("distance_mm", row["y_cmd_m"] * 1000 - setup["origin_y_mm"])
                         for row in straight])
    middle = (distance >= 10 - 1e-8) & (distance <= 40 + 1e-8)
    signal = np.array([row["a_control_uT"] for row in straight])
    components = np.array([vectors[row["sample_seq"]] for row in straight])
    source_values = np.array([raw[row["sample_seq"]] for row in straight])
    error = float(np.max(np.abs(np.linalg.norm(components[:, :2], axis=1) - signal)))
    assert error < 1e-8 and int(middle.sum()) == 151
    if "bx_filtered_uT" in straight[0]:
        logged = np.array([[row[f"b{axis}_filtered_uT"] for axis in "xyz"] for row in straight])
        assert np.max(np.abs(logged - components)) < 1e-8
    row = dict(info, baseline_id=1, middle_points=int(middle.sum()),
               window_start_mm=10., window_end_mm=40., filter_alpha=alpha,
               middle_response_mean_uT=float(signal[middle].mean()),
               middle_response_sample_std_uT=float(signal[middle].std(ddof=1)),
               full_straight_response_mean_uT=float(signal.mean()),
               ema_replay_max_error_uT=error,
               control_sha256=digest(folder / "control.jsonl"))
    for axis, j in zip("xyz", range(3)):
        row[f"baseline_B{axis}_uT"] = float(b0[j])
        row[f"baseline_std_B{axis}_uT"] = baseline[f"std_B{axis}_uT"]
        row[f"middle_filtered_delta_B{axis}_mean_uT"] = float(components[middle, j].mean())
        row[f"middle_filtered_loaded_B{axis}_mean_uT"] = float(components[middle, j].mean() + b0[j])
        row[f"middle_unfiltered_loaded_B{axis}_mean_uT"] = float(source_values[middle, j].mean())
    row["group"] = next(key for key, _, _, _, lo, hi in GROUPS if lo <= info["run_order"] <= hi)
    return row


def frame(ax):
    ax.grid(alpha=.18)
    ax.spines[["top", "right"]].set_visible(False)
    ax.xaxis.set_major_formatter(ScalarFormatter(useOffset=False))


def scatter(ax, rows, axis, title, correlations):
    for key, label, color, marker, lo, hi in GROUPS:
        subset = [row for row in rows if row["group"] == key]
        ax.scatter([r[f"baseline_B{axis}_uT"] for r in subset],
                   [r["middle_response_mean_uT"] for r in subset], s=64, marker=marker,
                   c=color, edgecolor="white", linewidth=.6, zorder=3)
    for row in rows[-3:]:
        ax.annotate(f'12日#{row["repeat"]}',
                    (row[f"baseline_B{axis}_uT"], row["middle_response_mean_uT"]),
                    xytext=(5, 7), textcoords="offset points", fontsize=9, color="#7e22ce")
    stats = correlations["all_19"][axis]
    same = correlations["fixed_12"][axis]
    latest = correlations["latest_soft_reboot_3"][axis]
    text = (f'全部19笔 r = {stats["pearson_r"]:+.3f}\n'
            f'定高12笔 r = {same["pearson_r"]:+.3f}\n'
            f'最新3笔 r = {latest["pearson_r"]:+.3f}')
    ax.text(.03, .96, text, transform=ax.transAxes, va="top", fontsize=10,
            bbox={"facecolor": "white", "alpha": .9, "edgecolor": "#e2e8f0", "pad": 5})
    if axis == "x":
        latest_rows = rows[-3:]
        x = np.array([r["baseline_Bx_uT"] for r in latest_rows])
        y = np.array([r["middle_response_mean_uT"] for r in latest_rows])
        xfit = np.linspace(x.min(), x.max(), 60)
        ax.plot(xfit, np.polyval(np.polyfit(x, y, 1), xfit), ls="--", lw=1,
                color="#9333ea", alpha=.65)
    ax.set(title=title, xlabel=f"方向空载基线 B0{axis}（µT）",
           ylabel="中段磁响应均值（µT）", ylim=(170, 405))
    ax.margins(x=.15)
    frame(ax)


def plot(rows, correlations):
    fig = plt.figure(figsize=(16, 10.6))
    grid = fig.add_gridspec(2, 3, height_ratios=[1, 1.15],
                            left=.065, right=.95, bottom=.15, top=.83,
                            wspace=.3, hspace=.49)
    history = fig.add_subplot(grid[0, :2])
    response = history.twinx()
    order = [r["run_order"] for r in rows]
    history.plot(order, [r["baseline_Bx_uT"] for r in rows], "o-", color="#2563eb", lw=1.6, ms=4)
    response.plot(order, [r["middle_response_mean_uT"] for r in rows], "s-", color="#ea580c", lw=1.6, ms=4)
    for _, label, color, _, lo, hi in GROUPS:
        history.axvspan(lo - .5, hi + .5, color=color, alpha=.055)
        history.text((lo + hi) / 2, 1.04,
                     label.replace("（7笔）", "").replace("（6笔）", "").replace("（操作有变化）", "").replace("（3笔）", ""),
                     transform=history.get_xaxis_transform(), ha="center", fontsize=9)
    for x in (7.5, 13.5, 16.5):
        history.axvline(x, color="#cbd5e1", lw=1)
    history.set(xlabel="两天实验顺序编号（1–19）",
                ylabel="B0x 基线（µT，左轴）", xlim=(.5, 19.5), ylim=(2030, 2245))
    history.set_title("A 每笔基线与实验均值（按时间排序）", y=1.16)
    response.set(ylabel="中段响应均值（µT，右轴）", ylim=(150, 410))
    history.tick_params(axis="y", colors="#2563eb")
    response.tick_params(axis="y", colors="#ea580c")
    history.yaxis.label.set_color("#2563eb")
    response.yaxis.label.set_color("#ea580c")
    history.set_xticks(order)
    history.legend(handles=[Line2D([0], [0], color="#2563eb", marker="o", label="B0x 基线（左轴）"),
                            Line2D([0], [0], color="#ea580c", marker="s", label="响应均值（右轴）")],
                   loc="lower left", ncol=2, fontsize=9)
    frame(history)
    response.spines["top"].set_visible(False)

    decomposition = fig.add_subplot(grid[0, 2])
    latest = rows[-3:]
    repeats = [r["repeat"] for r in latest]
    base = [r["baseline_Bx_uT"] for r in latest]
    loaded = [r["middle_filtered_loaded_Bx_mean_uT"] for r in latest]
    means = [r["middle_response_mean_uT"] for r in latest]
    decomposition.set_title("B 最新三笔数值拆分（单位：µT）", y=1.16)
    decomposition.axis("off")
    table = decomposition.table(
        cellText=[["空载基线 B0x", *[f"{v:.1f}" for v in base]],
                  ["接触 Bx 原值", *[f"{v:.1f}" for v in loaded]],
                  ["响应均值", *[f"{v:.1f}" for v in means]]],
        colLabels=["", *[f"12日第{x}次" for x in repeats]],
        colWidths=[.36, .22, .22, .22], cellLoc="center", bbox=[0, .45, 1, .58])
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor("#e2e8f0")
        if row == 0:
            cell.set_facecolor("#f1f5f9")
        else:
            cell.get_text().set_color(["#2563eb", "#059669", "#ea580c"][row - 1])
    change_base, change_loaded = base[1] - base[0], loaded[1] - loaded[0]
    change_dx = change_loaded - change_base
    decomposition.text(0, .35,
                       f"空载 B0x 极差 {np.ptp(base):.1f}；接触 Bx 原值极差 {np.ptp(loaded):.1f}\n\n"
                       f"第5次相对第4次：\n接触原值 {change_loaded:+.1f}，基线 {change_base:+.1f}\n"
                       f"平均 ΔBx 因此增加 {change_dx:.1f}\n响应均值增加 {means[1] - means[0]:.1f}（幅值还含 ΔBy）\n\n"
                       "接触 Bx 原值为中段 EMA 滤波磁场均值。",
                       transform=decomposition.transAxes, va="top", fontsize=10, linespacing=1.25)

    for axis, column, title in zip("xyz", range(3),
                                   ("C B0x 与实验均值", "D B0y 与实验均值", "E B0z 与实验均值（Bz 未参与幅值）")):
        scatter(fig.add_subplot(grid[1, column]), rows, axis, title, correlations)
    handles = [Line2D([0], [0], marker=marker, color="none", markerfacecolor=color,
                      markeredgecolor="white", markersize=8, label=label)
               for _, label, color, marker, _, _ in GROUPS]
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(.5, .077), ncol=4, frameon=False)
    fig.suptitle("空载基线与行笔磁响应均值的关系｜10月10日 + 10月12日，19笔", fontsize=19, y=.982)
    fig.text(.5, .936,
             "每笔使用实际生效的方向基线1；实验均值统一取直线行笔10–40 mm（151个控制点）",
             ha="center", fontsize=12, color="#475569")
    fig.text(.5, .047,
             "响应 = ‖EMA(B − B0)xy‖，α = 0.3；各点为一笔实验均值。r 为 Pearson 相关系数，最新3笔的 r 仅作描述。",
             ha="center", fontsize=10, color="#475569")
    fig.text(.5, .021,
             "全部19笔含不同接触参数；12笔定高运动参数一致，但准备操作、纸面历史及复位状态不同。基线参与减法，相关性不能单独证明板子故障。",
             ha="center", fontsize=10, color="#475569")
    fig.savefig(HERE / "baseline_response_relation.png", dpi=180, facecolor="white")
    plt.close(fig)


def main():
    evidence = json.loads(BASELINES.read_text())
    baselines = {r["run_order"]: r for r in evidence["all_baselines"] if r["baseline_id"] == 1}
    rows = [load(info, baselines[info["run_order"]]) for info in evidence["run_inventory"]]
    assert len(rows) == 19
    # Check the 12 matched-profile means against the previously delivered analyses.
    prior_path = HERE.parents[1] / "2026-10-12/四方向速度下压实验/analysis/z28_soft_reboot_three/summary.json"
    prior = json.loads(prior_path.read_text())
    known = {Path(r["raw_folder"]).name: r["middle_mean_uT"]
             for r in prior["latest"] + prior["previous_same_day"]}
    older_path = prior_path.parents[1] / "z28_repeatability/summary.json"
    older = json.loads(older_path.read_text())
    known.update({Path(r["raw_folder"]).name: r["middle_mean_uT"] for r in older["runs"]})
    for row in rows[7:]:
        assert abs(row["middle_response_mean_uT"] - known[row["run_name"]]) < 1e-8
    cohorts = {"all_19": rows, "fixed_12": rows[7:], "fixed_1010_6": rows[7:13],
               "fixed_1012_6": rows[13:], "latest_soft_reboot_3": rows[-3:]}
    correlations = {name: {axis: correlation([r[f"baseline_B{axis}_uT"] for r in group],
                                           [r["middle_response_mean_uT"] for r in group])
                          for axis in "xyz"} for name, group in cohorts.items()}
    sensitivity_full_straight = {
        name: {axis: correlation([r[f"baseline_B{axis}_uT"] for r in group],
                                  [r["full_straight_response_mean_uT"] for r in group])
               for axis in "xyz"} for name, group in cohorts.items()}
    latest = rows[-3:]
    change = {key: latest[1][key] - latest[0][key]
              for key in ("baseline_Bx_uT", "middle_filtered_loaded_Bx_mean_uT",
                          "middle_filtered_delta_Bx_mean_uT", "middle_response_mean_uT")}
    assert abs(change["middle_filtered_loaded_Bx_mean_uT"] - change["baseline_Bx_uT"]
               - change["middle_filtered_delta_Bx_mean_uT"]) < 1e-8
    summary = {
        "baseline_input": str(BASELINES), "baseline_input_sha256": digest(BASELINES),
        "run_count": len(rows), "baseline_id": 1,
        "method": "Each run is one observation. Primary mean: a_control_uT over commanded straight_hold distance 10–40 mm inclusive, 151 points. Active directional baseline id 1, not initial baseline id 0. EMA alpha 0.3 is replayed from sensor.csv and matches control.jsonl below 1e-8 uT. Mean response is mean of per-sample XY norms, not norm of the mean vector. Loaded filtered field is EMA(delta B)+B0. Correlations are descriptive; no independent replication assumption for repeated paper tracks.",
        "verification": "All 19 sensor/manifest files match hashes of the preceding baseline export; baseline means/std recomputed from raw windows. All manifest-recorded snapshot hashes match. Original manifests do not store sensor.csv hashes; the export hashes establish consistency with that export, not acquisition-time raw-file integrity. Twelve fixed-height response means match previous analyses below 1e-8 uT.",
        "correlations": correlations,
        "full_straight_window_sensitivity_correlations": sensitivity_full_straight,
        "latest_5_minus_4_decomposition_uT": change,
        "limitations": ["First seven trials vary entry tilt, preload height and rotation duration.",
                        "Remaining twelve have the same motion/settings snapshots, but operation history differs. On Oct 12 before trial 2 the operator adjusted magnetic bristles; before trial 3 the board was power cycled. Trials 4–6 use per-trial soft reboot.",
                        "Same paper line was retraced; water preparation was described as consistent. Temperature and bristle geometry were not measured.",
                        "Latest three trials are only n=3. Their near-perfect correlation does not establish a universal relationship or a cause.",
                        "Because the response explicitly subtracts B0, shared variables create mathematical coupling. A constant additive offset shared by unloaded and loaded measurements would cancel; these results do not by themselves locate the changing state in electronics versus the magnetic brush/contact.",
                        "Bz does not enter the XY response. Its latest-three correlation illustrates why a strong small-sample correlation alone does not establish contribution.",
                        "Old and new firmware sample periods differ (about 4 ms versus 3 ms), with the same EMA alpha."],
        "runs": rows,
    }
    (HERE / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    with (HERE / "paired_metrics.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    lines = ["空载基线与实验均值关系：10月10日、10月12日全部19笔", "",
             "方向基线1为实际扣除的B0；不是姿态不同的初始基线0。实验均值取直线行笔10–40 mm，单位µT，不是力N。",
             "每笔151个控制点的范数取均值；一笔只作为一个相关分析观测，不能把控制点当作独立重复。", "",
             "组别 | n | Bx0 Pearson r | By0 Pearson r | Bz0 Pearson r"]
    for name, stats in correlations.items():
        lines.append(f'{name} | {stats["x"]["n"]} | {stats["x"]["pearson_r"]:+.6f} | {stats["y"]["pearson_r"]:+.6f} | {stats["z"]["pearson_r"]:+.6f}')
    lines += ["", "最新三笔：次序 | Bx0 | 中段接触滤波Bx原值 | 平均滤波ΔBx | 中段响应均值"]
    for row in latest:
        lines.append(f'{row["repeat"]} | {row["baseline_Bx_uT"]:.6f} | {row["middle_filtered_loaded_Bx_mean_uT"]:.6f} | {row["middle_filtered_delta_Bx_mean_uT"]:.6f} | {row["middle_response_mean_uT"]:.6f}')
    lines += ["", f'第5次相对第4次：基线Bx变化 {change["baseline_Bx_uT"]:+.3f} µT；接触滤波Bx原值变化 {change["middle_filtered_loaded_Bx_mean_uT"]:+.3f} µT。',
              f'因此平均ΔBx变化为 {change["middle_filtered_delta_Bx_mean_uT"]:+.3f} µT；XY范数的均值变化为 {change["middle_response_mean_uT"]:+.3f} µT。',
              "最新三笔Bx0极差114.512 µT，接触滤波Bx原值极差19.380 µT：这组三次的响应差异与空载参考状态的变化密切关联。",
              "全部19笔Bx0相关较弱；仅看12笔定高也不能认为存在稳定的统一关系。10日和12日各自关系也不同。",
              "基线本来就在B−B0减法中，最新三笔相关很强并不能单独证明板子故障，也不能证明空载基线采集错误。",
              "恒定且同时作用于空载和接触读数的电子零点偏移会被减法抵消；应进一步分离空载/接触状态变化、磁毛几何、接触历史及电子漂移。",
              "原始基线均值/标准差、EMA与已有12笔实验均值均核对一致；原始记录没有修改。", "",
              "逐笔表包含全行笔均值作为窗口敏感性核对，主图和主相关使用10–40 mm中段均值。",
              "完整限制、Pearson/Spearman相关、数据哈希及逐笔指标见summary.json；图为baseline_response_relation.png。"]
    (HERE / "report.txt").write_text("\n".join(lines) + "\n")
    plot(rows, correlations)
    print(json.dumps({"run_count": len(rows), "max_ema_error_uT": max(r["ema_replay_max_error_uT"] for r in rows),
                      "correlations": correlations, "latest_5_minus_4_decomposition_uT": change,
                      "output": str(HERE)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
