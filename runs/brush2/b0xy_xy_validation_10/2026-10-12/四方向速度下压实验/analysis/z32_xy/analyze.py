"""Analyze the six listed Z32 trials offline; preserve original experiment records."""
from pathlib import Path
import csv
import hashlib
import json
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.ticker import FormatStrFormatter, ScalarFormatter
import numpy as np

HERE = Path(__file__).resolve().parent
RAW = HERE.parents[1] / "raw"
COLORS = ["#2563eb", "#d97706", "#059669"]
UNITS = {"right": np.array([1., 0.]), "up": np.array([0., 1.])}
AXES = {"right": "X", "up": "Y"}
font_path = Path("/usr/local/share/fonts/msyh.ttf")
if font_path.exists():
    font_manager.fontManager.addfont(str(font_path))
plt.rcParams.update({"font.family": "Microsoft YaHei", "axes.unicode_minus": False,
                     "font.size": 11, "axes.titlesize": 13, "legend.fontsize": 9})


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stats(values):
    values = np.asarray(values, dtype=float)
    assert len(values) >= 2 and np.isfinite(values).all()
    return dict(n=len(values), mean=float(values.mean()), sample_std=float(values.std(ddof=1)),
                cv_pct=float(values.std(ddof=1) / values.mean() * 100),
                minimum=float(values.min()), maximum=float(values.max()),
                range=float(np.ptp(values)), range_relative_to_mean_pct=float(np.ptp(values) / values.mean() * 100))


def rank(values):
    values = np.asarray(values)
    return np.array([np.sum(values < x) + (np.sum(values == x) - 1) / 2 + 1 for x in values])


def association(rows):
    x = np.array([r["B0xy_uT"] for r in rows])
    y = np.array([r["middle_mean_uT"] for r in rows])
    return dict(n=len(rows), pearson_r=float(np.corrcoef(x, y)[0, 1]),
                spearman_rho=float(np.corrcoef(rank(x), rank(y))[0, 1]),
                confidence_interval=None,
                interpretation="Only three trials per direction; descriptive correlation. A reliable confidence interval is not claimed.")


def load(name):
    folder = RAW / name
    manifest = json.loads((folder / "manifest.json").read_text())
    profile = json.loads((folder / "identification.json").read_text())
    setup = json.loads((folder / "settings.json").read_text())
    resolved = json.loads((folder / "resolved.json").read_text())
    assert manifest["status"] == "completed"
    for filename, expected in manifest["sha256"].items():
        assert sha(folder / filename) == expected, (name, filename)
    direction = profile["direction"]
    unit = UNITS[direction]
    origin = np.array([setup["origin_x_mm"], setup["origin_y_mm"]])
    assert np.array_equal(origin, [-150, 450])
    assert profile["mode"] == "four-direction-hold"
    assert profile["start_z_mm"] == profile["end_z_mm"] == profile["entry_contact_z_mm"]
    assert profile["travel_mm"] == 50 and profile["speed_mm_s"] == 10
    assert profile["entry_tilt_deg"] == 30 and profile["writing_tilt_deg"] == 15
    assert profile["rotate_s"] == 2 and profile["entry_reverse_mm"] == 5
    assert setup["filter"] == {"alpha": .3, "kind": "ema"}
    controls = [json.loads(line) for line in (folder / "control.jsonl").read_text().splitlines()]
    assert "load_start" not in {r["phase"] for r in controls}
    straight = [r for r in controls if r["phase"] == "straight_hold"]
    rotation = [r for r in controls if r["phase"] == "rotate_contact"]
    xy = np.array([[r["x_cmd_m"], r["y_cmd_m"]] for r in straight]) * 1000
    distance = (xy - origin) @ unit
    assert np.isclose(distance[-1], 50) and np.all(np.diff(distance) > 0)
    assert np.allclose([r["z_cmd_m"] * 1000 for r in straight + rotation], profile["start_z_mm"])
    mid = (distance >= 10 - 1e-8) & (distance <= 40 + 1e-8)
    tail = distance >= 40 - 1e-8
    assert int(mid.sum()) == 151
    with (folder / "sensor.csv").open() as stream:
        sensors = list(csv.DictReader(stream))
    invalid = [r for r in sensors if r["valid"] != "true"]
    assert not invalid
    source = {int(r["seq"]): r for r in sensors}
    assert {source[r["sample_seq"]]["baseline_id"] for r in straight + rotation} == {"1"}
    assert len(manifest["baselines"]) == 2
    baseline_metrics = []
    for base in manifest["baselines"]:
        accepted = [r for r in sensors if base["first_seq"] <= int(r["seq"]) <= base["last_seq"]]
        original = np.array([[float(r[f"B{axis}_uT"]) for axis in "xyz"] for r in accepted])
        host = np.array([int(r["host_rx_ns"]) for r in accepted], dtype=np.int64)
        seconds = (host - host[0]) / 1e9
        slopes = np.array([np.polyfit(seconds, original[:, j], 1)[0] for j in range(3)])
        assert np.max(np.abs(original.mean(axis=0) - base["B0_uT"])) < 1e-8
        assert np.max(np.abs(original.std(axis=0) - base["std_uT"])) < 1e-8
        assert np.max(np.abs(slopes - base["drift_uT_s"])) < 1e-7
        baseline_metrics.append(dict(baseline_id=base["baseline_id"], samples=len(accepted),
                                     duration_s=float(seconds[-1]), mean_uT=base["B0_uT"],
                                     std_uT=base["std_uT"], drift_uT_s=base["drift_uT_s"],
                                     raw_xy_norm_std_uT=float(np.hypot(original[:, 0], original[:, 1]).std())))
    active = next(b for b in manifest["baselines"] if b["baseline_id"] == 1)
    b0 = np.array(active["B0_uT"])
    filtered = None
    vectors = {}
    for r in sensors:
        if r["baseline_id"] != "1":
            continue
        value = np.array([float(r[f"dB{axis}_uT"]) for axis in "xyz"])
        original = np.array([float(r[f"B{axis}_uT"]) for axis in "xyz"])
        assert np.max(np.abs(original - b0 - value)) < 1e-8
        filtered = value if filtered is None else .3 * value + .7 * filtered
        vectors[int(r["seq"])] = filtered.copy()
    components = np.array([vectors[r["sample_seq"]] for r in straight])
    amplitude = np.array([r["a_control_uT"] for r in straight])
    replay_error = max(abs(np.hypot(*vectors[r["sample_seq"]][:2]) - r["a_control_uT"])
                       for r in straight + rotation)
    assert replay_error < 1e-8
    raw_selected = np.array([[float(source[r["sample_seq"]][f"B{axis}_uT"])
                              for axis in "xyz"] for r in straight])
    with (folder / "actual_tcp.csv").open() as stream:
        actual_all = list(csv.DictReader(stream))
    assert all(r["valid"] == "true" for r in actual_all)
    actual = [r for r in actual_all if r["valid"] == "true"
              and straight[0]["host_ns"] <= int(r["request_end_ns"]) <= straight[-1]["host_ns"]]
    actual_xy = np.array([[float(r["x_m"]), float(r["y_m"])] for r in actual]) * 1000
    actual_distance = (actual_xy - origin) @ unit
    actual_z = np.array([float(r["z_m"]) * 1000 for r in actual])
    actual_mid = (actual_distance >= 10) & (actual_distance <= 40)
    assert int(actual_mid.sum()) >= 20
    reboot = resolved["sensor_reboot"]
    assert reboot["status"] == "completed" and reboot["ack_host_ns"] < reboot["ready_host_ns"] < reboot["completed_host_ns"]
    end_rotation = [r["a_control_uT"] for r in rotation if r["t_s"] >= rotation[-1]["t_s"] - .3 - 1e-9]
    repeat = int(re.search(r"第(\d+)次", name).group(1))
    metric = dict(run_name=name, raw_folder=str(folder), date="2026-10-12", time=name[:8].replace("-", ":"),
                  direction=direction, axis=AXES[direction], repeat=repeat,
                  command_z_mm=profile["start_z_mm"], speed_mm_s=10., travel_mm=50.,
                  active_baseline_id=1, baseline_count=2, B0xy_uT=float(np.hypot(*b0[:2])),
                  baseline_Bxyz_uT=b0.tolist(), baseline_std_Bxyz_uT=active["std_uT"],
                  baselines=baseline_metrics, middle_points=int(mid.sum()),
                  middle_mean_uT=float(amplitude[mid].mean()),
                  middle_sample_std_uT=float(amplitude[mid].std(ddof=1)),
                  middle_median_uT=float(np.median(amplitude[mid])),
                  middle_signal_slope_uT_per_mm=float(np.polyfit(distance[mid], amplitude[mid], 1)[0]),
                  rotation_end_mean_uT=float(np.mean(end_rotation)), tail_mean_uT=float(amplitude[tail].mean()),
                  full_straight_mean_uT=float(amplitude.mean()),
                  middle_filtered_delta_Bxyz_mean_uT=components[mid].mean(axis=0).tolist(),
                  middle_filtered_loaded_Bxyz_mean_uT=(components[mid].mean(axis=0) + b0).tolist(),
                  middle_unfiltered_loaded_Bxyz_mean_uT=raw_selected[mid].mean(axis=0).tolist(),
                  middle_filtered_loaded_Bxy_norm_mean_uT=float(np.linalg.norm(components[mid, :2] + b0[:2], axis=1).mean()),
                  actual_middle_points=int(actual_mid.sum()),
                  actual_middle_z_mean_mm=float(actual_z[actual_mid].mean()),
                  actual_middle_z_min_mm=float(actual_z[actual_mid].min()),
                  actual_middle_z_max_mm=float(actual_z[actual_mid].max()),
                  actual_middle_z_range_mm=float(np.ptp(actual_z[actual_mid])),
                  actual_middle_z_slope_mm_per_mm=float(np.polyfit(actual_distance[actual_mid], actual_z[actual_mid], 1)[0]),
                  sensor_samples=len(sensors), invalid_sensor_samples=len(invalid),
                  actual_samples=len(actual_all), invalid_actual_samples=sum(r["valid"] != "true" for r in actual_all),
                  median_sensor_interval_us=float(np.median(np.diff([int(r["sensor_t_us"]) for r in sensors]))),
                  reboot_duration_s=(reboot["completed_host_ns"] - reboot["requested_host_ns"]) / 1e9,
                  reboot_ack_latency_s=(reboot["ack_host_ns"] - reboot["requested_host_ns"]) / 1e9,
                  reboot_reconnect_count=reboot["reconnect_count"],
                  sensor_first_uptime_s=int(sensors[0]["sensor_t_us"]) / 1e6,
                  max_lateness_ms=max(r["lateness_s"] for r in controls) * 1000,
                  ema_replay_max_error_uT=float(replay_error),
                  profile=profile, setup_sha256=manifest["sha256"]["settings.json"],
                  sources={filename: sha(folder / filename) for filename in
                           ("manifest.json", "sensor.csv", "control.jsonl", "actual_tcp.csv")},
                  sensor_hash_recorded_in_manifest="sensor.csv" in manifest["sha256"])
    return dict(metric=metric, distance=distance, response=amplitude, components=components,
                actual_distance=actual_distance, actual_z=actual_z,
                rotation_t=np.array([r["t_s"] for r in rotation]) - rotation[0]["t_s"],
                rotation_response=np.array([r["a_control_uT"] for r in rotation]))


def frame(ax):
    ax.grid(alpha=.18)
    ax.spines[["top", "right"]].set_visible(False)
    if isinstance(ax.xaxis.get_major_formatter(), ScalarFormatter):
        ax.xaxis.set_major_formatter(ScalarFormatter(useOffset=False))


def overview(runs, groups, associations):
    fig, axes = plt.subplots(2, 3, figsize=(15, 9.4))
    fig.subplots_adjust(left=.055, right=.98, bottom=.11, top=.85, wspace=.29, hspace=.36)
    subsets = {axis: [r for r in runs if r["metric"]["axis"] == axis] for axis in "XY"}
    for j, axis in enumerate("XY"):
        for run, color in zip(subsets[axis], COLORS):
            row = run["metric"]
            axes[0, j].plot(run["distance"], run["response"], color=color, lw=1.5,
                            label=f'第{row["repeat"]}次；中段{row["middle_mean_uT"]:.1f} µT')
        axes[0, j].axvspan(10, 40, color="#94a3b8", alpha=.12)
        axes[0, j].set(title=f'{"AB"[j]} +{axis} 行笔响应：三笔差异明显',
                       xlabel="沿本方向的命令行程（mm）", ylabel="磁响应幅值（µT）", xlim=(0, 50), ylim=(0, 190))
        axes[0, j].legend(loc="lower right", fontsize=9)
        frame(axes[0, j])
        vals = [r["metric"]["B0xy_uT"] for r in subsets[axis]]
        means = [r["metric"]["middle_mean_uT"] for r in subsets[axis]]
        scatter = axes[1, j]
        scatter.scatter(vals, means, color=COLORS, s=75, edgecolor="white", zorder=3)
        for run, x, y, color in zip(subsets[axis], vals, means, COLORS):
            scatter.annotate(f'#{run["metric"]["repeat"]}', (x, y), xytext=(6, 7),
                             textcoords="offset points", color=color)
        fit_x = np.linspace(min(vals), max(vals), 80)
        scatter.plot(fit_x, np.polyval(np.polyfit(vals, means, 1), fit_x), color="#64748b", lw=1, ls="--")
        scatter.set(title=f'{"DE"[j]} +{axis}：B0xy 与响应均值', xlabel="空载方向基线 B0xy（µT）",
                    ylabel="中段响应均值（µT）", ylim=(60, 172))
        scatter.margins(x=.15)
        scatter.text(.04, .95,
                     f'n=3；Pearson r={associations[axis]["pearson_r"]:+.3f}\n'
                     f'Spearman ρ={associations[axis]["spearman_rho"]:+.2f}',
                     transform=scatter.transAxes, va="top", fontsize=10,
                     bbox={"facecolor": "white", "alpha": .9, "edgecolor": "#e2e8f0", "pad": 5})
        frame(scatter)
    values = [r["metric"]["middle_mean_uT"] for r in runs]
    bars = axes[0, 2]
    bars.bar(range(6), values, color=COLORS * 2, width=.65)
    for i, value in enumerate(values):
        bars.text(i, value + 3, f"{value:.1f}", ha="center", fontsize=10)
    bars.axvline(2.5, color="#cbd5e1")
    bars.set_xticks(range(6), ["X1", "X2", "X3", "Y1", "Y2", "Y3"])
    bars.set(title="C 中段均值与跨笔重复差", ylabel="响应均值（µT）", ylim=(0, 190))
    bars.text(1, 177, f'X：CV {groups["X"]["cv_pct"]:.1f}%', ha="center")
    bars.text(4, 177, f'Y：CV {groups["Y"]["cv_pct"]:.1f}%', ha="center")
    frame(bars)
    vector = axes[1, 2]
    delta = np.array([r["metric"]["middle_filtered_delta_Bxyz_mean_uT"] for r in runs])
    vector.bar(np.arange(6) - .17, delta[:, 0], width=.32, color="#475569", label="平均 ΔBx")
    vector.bar(np.arange(6) + .17, delta[:, 1], width=.32, color="#94a3b8", label="平均 ΔBy")
    vector.axhline(0, color="#cbd5e1", lw=1)
    vector.axvline(2.5, color="#cbd5e1", lw=1)
    vector.set_xticks(range(6), ["X1", "X2", "X3", "Y1", "Y2", "Y3"])
    vector.set(title="F 有符号分量：X主要ΔBy，Y主要ΔBx", ylabel="中段滤波分量均值（µT）")
    vector.legend(loc="best")
    frame(vector)
    fig.suptitle("Z32 定高实验｜+X、+Y各3笔，10 mm/s，50 mm", fontsize=21, y=.976)
    fig.text(.5, .913, "中段均值统一取10–40 mm；顺序XXXYYY；每笔用未写过的纸面、含水准备一致、未手调磁毛", ha="center", fontsize=12, color="#475569")
    fig.text(.5, .035, "响应 = ‖EMA(B − B0)xy‖，α=0.3，单位µT；每笔为一个统计观测。n=3的相关仅作描述，不能证明因果或稳定规律。", ha="center", fontsize=10, color="#475569")
    fig.savefig(HERE / "z32_overview.png", dpi=180, facecolor="white")
    plt.close(fig)


def quality(runs):
    fig, axes = plt.subplots(2, 2, figsize=(13, 8.7))
    fig.subplots_adjust(left=.075, right=.96, bottom=.13, top=.86, wspace=.25, hspace=.42)
    for j, axis in enumerate("XY"):
        for run, color in zip([r for r in runs if r["metric"]["axis"] == axis], COLORS):
            row = run["metric"]
            axes[0, j].plot(run["actual_distance"], run["actual_z"], color=color, lw=1.4,
                            label=f'#{row["repeat"]}；中段起伏{row["actual_middle_z_range_mm"]:.3f} mm')
        axes[0, j].axhline(32, color="#64748b", ls="--", lw=1)
        axes[0, j].axvspan(10, 40, color="#94a3b8", alpha=.1)
        axes[0, j].set(title=f'{"AB"[j]} +{axis} 机器人回读的 TCP 高度', xlabel="沿本方向的实际行程（mm）",
                       ylabel="实际 Z（mm）", xlim=(0, 50), ylim=(31.84, 32.12))
        axes[0, j].yaxis.set_major_formatter(FormatStrFormatter("%.3f"))
        axes[0, j].legend(loc="lower left", fontsize=9)
        frame(axes[0, j])
    rows = [r["metric"] for r in runs]
    labels = [f'{r["axis"]}{r["repeat"]}' for r in rows]
    base = axes[1, 0]
    for component, color, shift in ((0, "#475569", -.17), (1, "#94a3b8", .17)):
        base.bar(np.arange(6) + shift, [r["baseline_std_Bxyz_uT"][component] for r in rows],
                 width=.32, color=color, label=["Bx", "By"][component])
    base.set_xticks(range(6), labels)
    base.set(title="C 方向基线约2秒：短窗噪声接近", ylabel="基线原始磁场标准差（µT）", ylim=(0, 7))
    base.legend()
    frame(base)
    table_ax = axes[1, 1]
    table_ax.axis("off")
    table_ax.set_title("D 六笔基线和响应数值（µT）")
    table = table_ax.table(cellText=[[label, f'{r["B0xy_uT"]:.2f}', f'{r["middle_mean_uT"]:.2f}',
                                     f'{r["reboot_duration_s"]:.3f}'] for label, r in zip(labels, rows)],
                          colLabels=["实验", "B0xy", "响应均值", "复位用时(s)"],
                          cellLoc="center", bbox=[0, .02, 1, .9])
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    for (row, _), cell in table.get_celld().items():
        cell.set_edgecolor("#e2e8f0")
        if row == 0:
            cell.set_facecolor("#f1f5f9")
    fig.suptitle("Z32 数据核对｜实际高度、基线噪声与每笔软复位", fontsize=19, y=.975)
    fig.text(.5, .914, "三笔各自的Z轨迹接近；Y的沿程高度变化较大，可能参与沿程响应变化，但不能单独解释跨笔均值差", ha="center", fontsize=11, color="#475569")
    fig.text(.5, .047, "全部传感器帧及TCP回读有效；两次基线均核对；原始sensor.csv重放EMA与控制记录相符（误差<1e-8 µT）。", ha="center", fontsize=10, color="#475569")
    fig.text(.5, .02, "基线噪声只描述约2秒窗口，不等于排除长时电子漂移；本实验未记录温度或直接测量磁毛形态。", ha="center", fontsize=10, color="#475569")
    fig.savefig(HERE / "z32_quality.png", dpi=180, facecolor="white")
    plt.close(fig)


def main():
    scope = json.loads((HERE / "scope.json").read_text())
    runs = [load(name) for name in scope["runs"]]
    assert len(runs) == 6 and all(r["metric"]["command_z_mm"] == 32 for r in runs)
    rows = [r["metric"] for r in runs]
    assert len({r["setup_sha256"] for r in rows}) == 1
    profiles = [dict(r["profile"]) for r in rows]
    for profile in profiles:
        profile.pop("direction")
    assert all(p == profiles[0] for p in profiles)
    groups = {axis: stats([r["middle_mean_uT"] for r in rows if r["axis"] == axis]) for axis in "XY"}
    correlations = {axis: association([r for r in rows if r["axis"] == axis]) for axis in "XY"}
    pairwise = []
    grid = np.linspace(10, 40, 301)
    for axis in "XY":
        subset = [run for run in runs if run["metric"]["axis"] == axis]
        curves = [np.interp(grid, run["distance"], run["response"]) for run in subset]
        for i, j in ((0, 1), (0, 2), (1, 2)):
            delta = curves[j] - curves[i]
            pairwise.append(dict(axis=axis, repeats=[i + 1, j + 1],
                                 mean_difference_uT=float(delta.mean()),
                                 rmse_uT=float(np.sqrt(np.mean(delta**2))),
                                 centered_rmse_uT=float(np.sqrt(np.mean((delta - delta.mean())**2)))))
    auxiliary = [load(name)["metric"] for name in scope["auxiliary_z28_x_runs"]]
    x28 = stats([r["middle_mean_uT"] for r in auxiliary])
    comparison = dict(z28_x_two_runs=auxiliary, z28_x_stats=x28,
                      z32_x_mean_relative_change_pct=(groups["X"]["mean"] / x28["mean"] - 1) * 100,
                      interpretation="Descriptive adjacent-batch comparison: X Z28 n=2 versus Z32 n=3, ordered in time. Operator confirmed new paper, consistent water preparation and no manual bristle adjustment for the six Z32 trials; preparation of the two auxiliary Z28 trials was not separately confirmed. Not a matched causal test of height.")
    summary = dict(run_count=len(runs), scope=scope, runs=rows,
                   method="Active direction baseline id=1, B0xy=norm of accepted mean XY vector. Response is mean of per-control-sample norm_xy(EMA(B-B0)) with alpha 0.3 over projected path 10–40mm inclusive (151 points per run). X uses X displacement and Y uses Y displacement. Report sample SD/CV of per-run means. No per-run amplitude normalization. Actual Z uses valid TCP reads in the same stroke and path window. All 12 baseline mean/std/drift values are recomputed and checked. EMA replay matches straight and rotation below 1e-8 uT.",
                   integrity="All manifest-recorded snapshot SHA256 values match. Raw sensor/control/TCP hashes are computed for reproducibility; sensor.csv hashes were not recorded in the original manifests, so acquisition-time raw integrity is not claimed.",
                   group_middle_statistics=groups, B0xy_response_correlations=correlations,
                   pairwise_middle_curves=pairwise, adjacent_z28_x_comparison=comparison,
                   operator_context=scope["operator_context"],
                   limitations=["Only three per direction; correlations are descriptive and no confidence interval is claimed.",
                                "Actual order is XXXYYY rather than interleaving, so between-direction comparisons also involve elapsed time and brush contact history.",
                                "Operator confirmed new paper each trial, consistent water preparation and no manual magnetic bristle adjustment. Water content, paper microgeometry and bristle geometry were not measured.",
                                "B0xy is a scalar norm, while the response subtracts the XY vector before its norm; angles and loaded field state also affect it.",
                                "Near-identical per-direction height paths do not establish identical contact or magnetic bristle geometry.",
                                "Software reboot does not ensure power-cycle cooling; temperature was not recorded."],
                   conclusion="Cross-trial response dispersion remains substantial at Z32: X CV about27.4%, Y about29.6%. X baseline/response correlation is positive, Y negative, neither reproduces a universal inverse relationship. X is dominated by delta By, Y by delta Bx. All six resets succeeded; short-window baseline noise is similar. Common Y path-Z variation may affect along-path response growth but does not explain the whole cross-trial offset.")
    (HERE / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    columns = ["axis", "repeat", "time", "B0xy_uT", "middle_mean_uT", "middle_sample_std_uT",
               "rotation_end_mean_uT", "tail_mean_uT", "actual_middle_z_mean_mm", "actual_middle_z_range_mm",
               "reboot_duration_s", "middle_signal_slope_uT_per_mm", "raw_folder"]
    with (HERE / "per_run_metrics.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    lines = ["2026-10-12 Z32定高XY实验分析（17:55:58–17:59:44）", "",
             "6笔完成：先+X三笔，再+Y三笔。30°→15°转2秒，XY补偿5mm，50mm直线，10mm/s，整个接触转笔和行笔均命令Z32；无转笔后下压。",
             "每笔两次基线均重新采集；实际生效方向基线1，B0xy为其XY均值向量的范数。响应是滤波后磁向量变化XY幅值，单位µT，不是力N。",
             "主统计取沿对应方向10–40mm的151个控制点；一笔才是一个重复观测。", "",
             "操作者确认：六笔每笔使用未写过的纸面，含水准备一致，未手动调整磁毛；含水量未进行定量测量。", "",
             "实验 | B0xy | 转笔末段均值 | 行笔中段均值 | 末段均值 | 实际Z中段均值 | 实际Z中段起伏"]
    for r in rows:
        lines.append(f'{r["axis"]}{r["repeat"]} | {r["B0xy_uT"]:.2f} | {r["rotation_end_mean_uT"]:.2f} | {r["middle_mean_uT"]:.2f} | {r["tail_mean_uT"]:.2f} | {r["actual_middle_z_mean_mm"]:.6f} mm | {r["actual_middle_z_range_mm"]:.3f} mm')
    lines += ["", "跨笔中段均值统计："]
    for axis in "XY":
        group, corr = groups[axis], correlations[axis]
        lines.append(f'{axis}：均值{group["mean"]:.2f} µT，样本SD{group["sample_std"]:.2f} µT，CV{group["cv_pct"]:.2f}%，极差{group["range"]:.2f} µT；B0xy—响应 Pearson r={corr["pearson_r"]:+.6f}，Spearman rho={corr["spearman_rho"]:+.3f}。')
    lines += ["", "主要发现：",
              "1. Z32仍有较大跨笔差异；单笔中段采样波动远小于三笔均值间的变化。同方向两条曲线各自减去中段均值后，成对RMSE约2.77–3.14µT，说明曲线形状接近、差异主要表现为整体响应水平不同；该去均值只用于形状诊断，不改变主统计。",
              "2. X三笔响应逐次降低，但B0xy先上后下；X的Pearson相关为正。Y三笔为负相关，只有3笔，不能据此确认统一的负相关规律。",
              "3. X主要来自ΔBy，Y主要来自ΔBx。B0xy大小本身不能唯一决定响应，还需结合向量方向和接触磁场原值。",
              "4. X实际Z中段起伏约0.02mm；Y约0.17mm，三笔各自的轨迹接近。Y中段随行程Z下降、响应上升，可能存在高度贡献；不能把该贡献与其他接触历史独立分离。",
              "5. 六笔软复位约0.726秒，全成功；传感器帧及实际TCP回读全部有效。方向基线Bx/By噪声约5–6µT，未显示短窗噪声逐笔持续变大。",
              "6. 六笔没有重画旧线，也没有手调磁毛，因此这两个操作不能解释本批差异。仅三次的相关系数不能定位板子故障；软复位成功不等于排除电子漂移。实际XXXYYY顺序未按交错方案执行，仍存在时间和笔毫接触历史影响。", "",
              f'邻近Z28的X两笔均值{auxiliary[0]["middle_mean_uT"]:.2f}、{auxiliary[1]["middle_mean_uT"]:.2f} µT，组均值{x28["mean"]:.2f}；Z32 X组均值低{abs(comparison["z32_x_mean_relative_change_pct"]):.2f}%。这是时间先后不同的描述比较，不能把全部变化归于4mm高度差。',
              "完整数据、分量、曲线成对差和来源哈希见summary.json；逐笔表见per_run_metrics.csv。",
              "图：z32_overview.png（响应、重复差、B0xy关系与分量）；z32_quality.png（实际高度、基线噪声、复位）。"]
    (HERE / "report.txt").write_text("\n".join(lines) + "\n")
    overview(runs, groups, correlations)
    quality(runs)
    print(json.dumps({"runs": len(rows), "group_middle_statistics": groups, "B0xy_response_correlations": correlations,
                      "max_ema_replay_error_uT": max(r["ema_replay_max_error_uT"] for r in rows),
                      "reboot_duration_s": [r["reboot_duration_s"] for r in rows],
                      "pairwise_middle_curves": pairwise,
                      "output": str(HERE)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
