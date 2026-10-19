#!/usr/bin/env python3
"""Offline multi-height calibration audit. Raw data and robot settings are unchanged."""
import csv
import hashlib
import html
import json
import os
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/fyp-matplotlib")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).resolve().parent
BASE = OUT.parent.parent
FIRST_NEW = "20261005T072249.453530Z-6a8c3a"
CUTOFF = "20261005T074054.304822Z-1014ac"
UNITS = {"right": (1, 0), "up": (0, 1), "left": (-1, 0), "down": (0, -1)}
NAMES = {"right": "+X", "up": "+Y", "left": "-X", "down": "-Y"}
LEVELS = (35, 30, 27)
NOISE = 20.0  # User-specified scale, not an estimated SD or confidence bound.
EDGES = np.arange(30, 120.001, 5)
CENTERS = (EDGES[:-1]+EDGES[1:])/2


def read_json(path):
    return json.loads(path.read_text())


def read_run(folder):
    manifest = read_json(folder/"manifest.json")
    p = read_json(folder/"identification.json")
    setup = read_json(folder/"settings.json")
    resolved = read_json(folder/"resolved.json")
    assert manifest["status"] == "completed" and manifest["execution_environment"] == "hardware"
    for name, digest in manifest["sha256"].items():
        assert hashlib.sha256((folder/name).read_bytes()).hexdigest() == digest
    control = [json.loads(line) for line in (folder/"control.jsonl").read_text().splitlines()]
    with (folder/"sensor.csv").open() as stream:
        sensor = list(csv.DictReader(stream))
    lookup = {int(r["seq"]): r for r in sensor}
    with (folder/"actual_tcp.csv").open() as stream:
        tcp = list(csv.DictReader(stream))
    meta = read_json(folder/"actual_tcp_meta.json")
    hold = p["mode"] == "four-direction-hold"
    line = [r for r in control if r["phase"] == ("straight_hold" if hold else "sweep_down")]
    g = np.array([r["a_control_uT"] for r in line])
    z = np.array([r["z_cmd_m"]*1000 for r in line])
    xy = np.array([[r["x_cmd_m"]*1000, r["y_cmd_m"]*1000] for r in line])
    origin = np.array([setup["origin_x_mm"], setup["origin_y_mm"]])
    unit = np.array(UNITS[p["direction"]])
    distance = (xy-origin)@unit
    assert np.isfinite(g).all()
    assert p["travel_mm"] == 150 and p["entry_contact_z_mm"] == 36
    assert p["entry_tilt_deg"] == 30 and p["writing_tilt_deg"] == 15
    assert setup["filter"] == {"kind": "ema", "alpha": .3} and setup["wait_z_mm"] == 70
    baseline = manifest["baselines"][-1]
    assert baseline["quality_axes"] == [0, 1]
    assert {int(lookup[r["sample_seq"]]["baseline_id"]) for r in line} == {baseline["baseline_id"]}
    selected = [r for r in tcp if r["valid"] == "true" and line[0]["host_ns"] <=
                (int(r["request_start_ns"])+int(r["request_end_ns"]))/2 <= line[-1]["host_ns"]]
    xyz = np.array([[float(r[k])*1000 for k in ("x_m", "y_m", "z_m")] for r in selected])
    td = (xyz[:, :2]-origin)@unit
    if hold:
        assert p["start_z_mm"] == p["end_z_mm"] and np.allclose(z, p["start_z_mm"])
        expected = np.full(len(xyz), p["start_z_mm"])
    else:
        q = np.clip(2*td/150-1, 0, 1)
        expected = 36-11*(10*q**3-15*q**4+6*q**5)
    stat = dict(run_id=manifest["run_id"], folder=folder.name, batch_id=resolved["batch_id"],
                stage="new_multiheight" if manifest["run_id"] >= FIRST_NEW else "previous",
                mode=p["mode"], direction=p["direction"], speed_mm_s=p["speed_mm_s"],
                command_z_mm=p["start_z_mm"] if hold else None,
                sensor_frames=len(sensor), sensor_invalid=sum(r["valid"] != "true" for r in sensor),
                tcp_samples=meta["samples"], tcp_invalid=meta["invalid_samples"],
                tcp_worker_stopped=meta["worker_stopped"],
                max_measure_sensor_age_ms=max(r["sample_age_s"] for r in line)*1000,
                tcp_z_path_max_abs_mm=float(abs(xyz[:, 2]-expected).max()),
                baseline_bx_uT=baseline["B0_uT"][0], baseline_by_uT=baseline["B0_uT"][1],
                baseline_std_bx_uT=baseline["std_uT"][0], baseline_std_by_uT=baseline["std_uT"][1],
                primary_median_uT=None, early_median_uT=None, late_median_uT=None,
                late_minus_early_uT=None, tail_max_uT=None,
                full_peak_uT=float(g.max()), peak_distance_mm=float(distance[g.argmax()]),
                above_500_last_distance_mm=float(distance[g > 500].max()) if np.any(g > 500) else None)
    bins = None
    if hold:
        samples = [g[(distance >= lo)&(distance < hi)] for lo, hi in zip(EDGES[:-1], EDGES[1:])]
        assert min(map(len, samples)) >= 10
        bins = np.array([np.median(a) for a in samples])
        early = float(np.median(g[(distance >= 30)&(distance < 60)]))
        late = float(np.median(g[(distance >= 90)&(distance < 120)]))
        stat.update(primary_median_uT=float(np.median(g[(distance >= 30)&(distance <= 120)])),
                    early_median_uT=early, late_median_uT=late, late_minus_early_uT=late-early,
                    tail_max_uT=float(g[distance >= 120].max()))
    return dict(stat=stat, folder=folder, profile=p, distance=distance, g=g, bins=bins)


def save_csv(name, rows):
    with (OUT/name).open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def fit_model(x, y, kind):
    if kind == "gain_only":
        return float(x@y/(x@x)), 0.0
    slope, offset = np.linalg.lstsq(np.column_stack([x, np.ones(len(x))]), y, rcond=None)[0]
    assert slope > 0
    return float(slope), float(offset)


def table(headers, rows):
    esc = lambda value: html.escape(str(value))
    return "<table><thead><tr>"+"".join(f"<th>{esc(v)}</th>" for v in headers)+"</tr></thead><tbody>"+"".join("<tr>"+"".join(f"<td>{esc(v)}</td>" for v in row)+"</tr>" for row in rows)+"</tbody></table>"


def main():
    folders = [p.parent for p in sorted((BASE/"raw").glob("*/manifest.json"))
               if read_json(p)["run_id"] <= CUTOFF]
    runs = sorted([read_run(p) for p in folders], key=lambda r: r["stat"]["run_id"])
    new = [r for r in runs if r["stat"]["stage"] == "new_multiheight"]
    assert len(runs) == 48 and len(new) == 18
    assert all(r["profile"]["mode"] == "four-direction-hold" and r["profile"]["speed_mm_s"] == 10 for r in new)
    groups = defaultdict(list)
    old_x30 = []
    for run in runs:
        s = run["stat"]
        if s["mode"] != "four-direction-hold" or s["speed_mm_s"] != 10:
            continue
        if s["direction"] == "right" and s["command_z_mm"] == 30 and s["stage"] == "previous":
            old_x30.append(run)
        else:
            groups[s["direction"], s["command_z_mm"]].append(run)
    assert len(old_x30) == 2
    assert set(groups) == {(d, z) for d in UNITS for z in LEVELS}
    assert all(len(pair) == 2 for pair in groups.values())
    assert all(r["stat"]["stage"] == "new_multiheight" for d in UNITS for z in (35, 27) for r in groups[d, z])
    assert all(r["stat"]["stage"] == "previous" for d in ("up", "left", "down") for r in groups[d, 30])
    repeat = []
    for d in UNITS:
        for z in LEVELS:
            pair = groups[d, z]
            a, b = [r["stat"]["primary_median_uT"] for r in pair]
            delta = pair[1]["bins"]-pair[0]["bins"]
            repeat.append(dict(direction=d, command_z_mm=z,
                               source_stage=pair[0]["stat"]["stage"],
                               run1_id=pair[0]["stat"]["run_id"], run2_id=pair[1]["stat"]["run_id"],
                               run1_median_uT=a, run2_median_uT=b,
                               median_difference_uT=b-a, mean_of_two_medians_uT=(a+b)/2,
                               matched_bin_mae_uT=float(abs(delta).mean()),
                               matched_bin_mean_shift_uT=float(delta.mean()),
                               rmse_after_constant_shift_uT=float(np.std(delta))))
    X = np.array([[r["stat"]["primary_median_uT"] for r in groups["right", z]] for z in LEVELS])
    model_rows, cv_rows, mean_checks = [], [], []
    endpoints = [0, 2]
    for d in ("up", "left", "down"):
        Y = np.array([[r["stat"]["primary_median_uT"] for r in groups[d, z]] for z in LEVELS])
        xm, ym = X.mean(axis=1), Y.mean(axis=1)
        for kind in ("gain_only", "gain_offset"):
            k, b = fit_model(xm[endpoints], ym[endpoints], kind)
            middle_error = (ym[1]-b)/k-xm[1]
            model_rows.append(dict(direction=d, model=kind, speed_mm_s=10,
                                   gain=k, offset_uT=b, fit_levels_mm="35,27",
                                   fit_grain="mean of two independent stroke medians per height",
                                   z30_mean_check_x_equivalent_error_uT=float(middle_error),
                                   z30_direction_data_are_historical=True,
                                   status="candidate_not_installed"))
            for i, z in enumerate(LEVELS):
                mean_checks.append(dict(direction=d, model=kind, command_z_mm=z,
                                        mean_x_uT=float(xm[i]), mean_direction_uT=float(ym[i]),
                                        x_equivalent_error_uT=float((ym[i]-b)/k-xm[i]),
                                        used_for_fit=z in (35, 27)))
            for train_index in (0, 1):
                test_index = 1-train_index
                kt, bt = fit_model(X[endpoints, train_index], Y[endpoints, train_index], kind)
                for i in endpoints:
                    error = (Y[i, test_index]-bt)/kt-X[i, test_index]
                    cv_rows.append(dict(direction=d, model=kind,
                                        train_repeat=train_index+1, heldout_repeat=test_index+1,
                                        command_z_mm=LEVELS[i], fitted_gain=kt, fitted_offset_uT=bt,
                                        heldout_source_run=groups[d, LEVELS[i]][test_index]["stat"]["run_id"],
                                        heldout_reference_run=groups["right", LEVELS[i]][test_index]["stat"]["run_id"],
                                        actual_direction_uT=float(Y[i, test_index]),
                                        actual_x_reference_uT=float(X[i, test_index]),
                                        corrected_x_uT=float((Y[i, test_index]-bt)/kt),
                                        x_equivalent_error_uT=float(error),
                                        within_user_20uT_scale=bool(abs(error) <= NOISE)))
    cv_summary = []
    for d in ("up", "left", "down"):
        for kind in ("gain_only", "gain_offset"):
            rows = [r for r in cv_rows if r["direction"] == d and r["model"] == kind]
            errors = np.array([r["x_equivalent_error_uT"] for r in rows])
            cv_summary.append(dict(direction=d, model=kind, heldout_conditions=len(rows),
                                   x_equivalent_mae_uT=float(abs(errors).mean()),
                                   x_equivalent_rmse_uT=float(np.sqrt(np.mean(errors**2))),
                                   max_abs_x_equivalent_error_uT=float(abs(errors).max()),
                                   conditions_within_user_20uT_scale=sum(abs(errors) <= NOISE).item()))
    old_mean = float(np.mean([r["stat"]["primary_median_uT"] for r in old_x30]))
    new_mean = float(X[1].mean())
    baseline_shift = dict(old_x30_medians_uT=[r["stat"]["primary_median_uT"] for r in old_x30],
                          new_x30_medians_uT=X[1].tolist(), mean_change_uT=new_mean-old_mean)

    def quality(subset):
        return dict(runs=len(subset), sensor_frames=sum(r["stat"]["sensor_frames"] for r in subset),
                    sensor_invalid=sum(r["stat"]["sensor_invalid"] for r in subset),
                    tcp_samples=sum(r["stat"]["tcp_samples"] for r in subset),
                    tcp_invalid=sum(r["stat"]["tcp_invalid"] for r in subset),
                    max_hold_tcp_z_deviation_mm=max(r["stat"]["tcp_z_path_max_abs_mm"] for r in subset if r["bins"] is not None),
                    max_sensor_age_ms=max(r["stat"]["max_measure_sensor_age_ms"] for r in subset))

    conclusions = [
        "新增18笔全部齐全：Z35/Z27各四方向×两笔，另有两笔+X/Z30参照。累计10月5日48笔，不含9月27日记录。",
        "沿用用户设定的约20 uT噪声量级，忽略水的影响，不安排空载背景实验。20 uT只是比较尺度，不是本批估计的标准差或统计置信限。",
        "增益+偏置能很好描述高度均值：由新增Z35/Z27的两笔均值拟合，+Y/-X/-Y候选k约2.023/1.439/2.920，b约-69.59/-37.94/-129.54 uT。Z30的均值换算误差约-5.24/+0.21/+0.94 uT。均值一致尚未证明单笔校准稳定。",
        "独立笔次验证失败集中在Y方向：用第一笔的Z35/Z27拟合、预测第二笔，再交换训练与验证，+Y/-X/-Y换算到X的RMSE分别约35.0/16.2/34.4 uT，最大误差约36.6/22.7/37.9 uT。-X可作初步试验，其余方向仍不能称为20 uT量级内的稳定统一校准。",
        "浅压Z35重复性不足：+X/-X两笔中段中位数分别下降45.48/55.38 uT，+Y/-Y也下降24.40/22.93 uT。Z27的+X下降35.69 uT，而+Y/-X/-Y变化约+1.74/-19.89/-14.06 uT。",
        "X参照发生明显批次变化：旧Z30两笔263.83/213.97 uT，新增参照153.54/158.21 uT，均值下降约83.02 uT。新增两笔Z30彼此很近，不能因此把旧X表与所有新高度直接合并。",
        "X第二笔从Z30到Z27只增加约10.35 uT，低于用户指定的20 uT噪声量级。这支笔在该记录下对两种高度的磁区分度不足，三点插值不能自动解决。",
        "Z27/-Y两笔起笔峰值约1070/945 uT，分别出现在沿程约2.00/0.64 mm；中段约422/408 uT。当前模型仅描述30-120 mm中段，不覆盖这些起笔瞬态。"]
    limitations = [
        "方向与倾斜姿态、路径位置同时变化；结果是该装配和该路径下的方向响应校准，不是纯方向因果分解，也不是法向力标定。",
        "主窗口仍为沿程30-120 mm。逐笔中位数是拟合的观测单位；5 mm分箱只用于曲线重复对照，不当成独立实验样本。全程峰值另行保留。",
        "主模型只由本轮新增的Z35/Z27拟合。Z30的+X使用新增参照，其他三个方向仍是之前采集的两笔，非同期；中间高度的均值检查是诊断，不能视为完整同期验证。",
        "独立验证按每条件时间先后两笔分组，第一组与第二组反转了方向/高度顺序；X与其他方向来自不同笔次，不是同步测量。该验证包含参照重复误差，正是实际使用时会遇到的限制。",
        "每次验证只有两个高度、每高度一个训练笔；两参数仿射模型在训练点精确通过是构造结果。两笔均值拟合的训练误差不得替代另一笔验证。",
        "仅四个轴向方向和10 mm/s；未验证对角线、连续角度或7/15 mm/s。没有把任何候选系数写入机器人控制配置。"]
    next_steps = [
        "暂不扩大到更多速度或对角线。先固定10 mm/s，保持装配、纸面高度和进笔方式一致，检验浅压参考与加载历史的重复性。",
        "先做+X的顺序对照，共4笔：第一组Z35→Z27，第二组Z27→Z35，每个顺序条件一组；这样两个高度各两笔，保留实际TCP及进笔/加载阶段。用这些记录检查Z35在深压之后是否系统降低。",
        "若顺序影响达到当前噪声量级以上，先统一每笔之间的恢复/等待和加载协议，再按统一协议建立多高度参考。若顺序对照稳定，补同期Z30四方向各两笔（8笔），与稳定的Z35/Z27进行完整验证。",
        "-X可先用候选k,b作离线试验，但仍报告独立验证最大误差约23 uT；+Y/-Y候选系数暂不作为正式校准。"]
    summary = dict(status="multiheight_candidate_validation", calibration_approved=False,
                   cutoff_run_id=CUTOFF, all_run_count=48, new_run_count=18, speed_mm_s=10,
                   command_z_levels_mm=list(LEVELS), primary_window_mm=[30, 120],
                   user_assumptions=dict(noise_scale_uT=NOISE, noise_is_not_estimated_sd=True,
                                         ignore_water=True, no_air_background_experiments=True),
                   new_run_quality=quality(new), all_run_quality=quality(runs),
                   height_repeatability=repeat, candidate_models=model_rows,
                   validation_summary=cv_summary, mean_height_checks=mean_checks,
                   x_reference_shift=baseline_shift, conclusions=conclusions,
                   limitations=limitations, next_experiments=next_steps,
                   input_sha256={str(p.relative_to(BASE)): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for r in runs for p in sorted(r["folder"].iterdir()) if p.is_file()},
                   generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    save_csv("run_quality.csv", [r["stat"] for r in runs])
    save_csv("height_repeatability.csv", repeat)
    save_csv("candidate_models.csv", model_rows)
    save_csv("heldout_predictions.csv", cv_rows)
    save_csv("validation_summary.csv", cv_summary)
    save_csv("mean_height_checks.csv", mean_checks)
    (OUT/"summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    colors = ("#2474b5", "#df7836")
    fig, axes = plt.subplots(4, 3, figsize=(15, 13), sharex=True, sharey="row", constrained_layout=True)
    for i, d in enumerate(UNITS):
        for j, z in enumerate(LEVELS):
            ax = axes[i, j]
            for number, run in enumerate(groups[d, z]):
                mask = (run["distance"] >= 30)&(run["distance"] <= 120)
                ax.plot(run["distance"][mask], run["g"][mask], color=colors[number],
                        label=f"Stroke {number+1}: {run['stat']['primary_median_uT']:.1f} uT")
            ax.set(title=f"{NAMES[d]}, Z{z}"+(" (earlier runs)" if z == 30 and d != "right" else ""), xlim=(30, 120))
            ax.grid(alpha=.2)
            ax.legend(fontsize=8)
            if j == 0:
                ax.set_ylabel("EMA |delta Bxy| / uT")
            if i == 3:
                ax.set_xlabel("Command travel / mm")
    fig.suptitle("10 mm/s: unchanged calibration window 30-120 mm\nZ35/Z27 and +X/Z30 are new; other Z30 runs precede this batch", fontsize=14)
    fig.savefig(OUT/"01_height_curves.png", dpi=150)
    plt.close(fig)
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), constrained_layout=True)
    for ax, d in zip(axes, ("up", "left", "down")):
        Y = np.array([[r["stat"]["primary_median_uT"] for r in groups[d, z]] for z in LEVELS])
        for number in (0, 1):
            ax.plot(X[:, number], Y[:, number], "o", color=colors[number], label=f"Stroke {number+1}")
        ax.plot(X.mean(axis=1), Y.mean(axis=1), "kD", label="Height means")
        xx = np.linspace(40, 230, 100)
        for kind, style in (("gain_only", ":"), ("gain_offset", "-")):
            model = next(r for r in model_rows if r["direction"] == d and r["model"] == kind)
            ax.plot(xx, model["gain"]*xx+model["offset_uT"], style, color="#21845f", label=kind)
        for z, x, y in zip(LEVELS, X.mean(axis=1), Y.mean(axis=1)):
            ax.annotate(f"Z{z}", (x, y), xytext=(4, 5), textcoords="offset points")
        ax.set(title=NAMES[d], xlabel="+X stroke median / uT", ylabel="Direction stroke median / uT")
        ax.grid(alpha=.2)
        ax.legend(fontsize=8)
    fig.suptitle("Candidate gain and offset: fits use Z35/Z27 height means\nIndividual strokes and independent validation must also agree")
    fig.savefig(OUT/"02_candidate_models.png", dpi=150)
    plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), constrained_layout=True)
    xrefs = sorted(old_x30+groups["right", 30], key=lambda r:r["stat"]["run_id"])
    for number, run in enumerate(xrefs):
        axes[0].plot(run["distance"], run["g"], label=f"{run['folder'].name[:8]}: {run['stat']['primary_median_uT']:.1f} uT")
    axes[0].axvspan(30, 120, color="grey", alpha=.08)
    axes[0].set(title="+X, Z30: old and new reference strokes", xlabel="Travel / mm", ylabel="EMA |delta Bxy| / uT", xlim=(0, 150))
    axes[0].legend(fontsize=8)
    cases = [r for r in cv_rows if r["model"] == "gain_offset"]
    axes[1].axhspan(-NOISE, NOISE, color="#21845f", alpha=.12, label="User noise scale +/-20 uT")
    axes[1].scatter(range(len(cases)), [r["x_equivalent_error_uT"] for r in cases], color="#2474b5")
    axes[1].set_xticks(range(len(cases)), [f"{NAMES[r['direction']]}\nZ{r['command_z_mm']}\ntrain{r['train_repeat']}" for r in cases], fontsize=8)
    axes[1].axhline(0, color="grey", linewidth=.7)
    axes[1].set(title="Independent stroke predictions: gain + offset", ylabel="Corrected value - measured +X / uT")
    axes[1].legend(fontsize=8)
    for ax in axes:
        ax.grid(alpha=.2)
    fig.savefig(OUT/"03_reference_and_validation.png", dpi=150)
    plt.close(fig)
    fig, axes = plt.subplots(1, 4, figsize=(16, 4), constrained_layout=True)
    for ax, d in zip(axes, UNITS):
        for number, run in enumerate(groups[d, 27]):
            ax.plot(run["distance"], run["g"], color=colors[number], label=f"Stroke {number+1}")
        ax.axvspan(30, 120, color="grey", alpha=.08)
        ax.set(title=f"{NAMES[d]}, Z27", xlabel="Travel / mm", ylabel="EMA |delta Bxy| / uT", xlim=(0, 150))
        ax.grid(alpha=.2)
        ax.legend(fontsize=8)
    fig.suptitle("Full Z27 traces: entry peaks retained; calibration describes the shaded window")
    fig.savefig(OUT/"04_full_z27_traces.png", dpi=150)
    plt.close(fig)

    page = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>多高度方向校准验证</title><style>body{max-width:1200px;margin:auto;padding:24px;font:17px/1.7 sans-serif;color:#20354a}img{width:100%;height:auto}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left}table{border-collapse:collapse;width:100%}a{color:#2474b5}</style><h1>10月5日多高度分析：新增18笔，累计48笔</h1>'
    page += "".join("<p>"+html.escape(text)+"</p>" for text in conclusions)
    page += '<h2>两笔中段中位数（uT）</h2><p>沿程30–120 mm。Z35/Z27全部新增；Z30只有+X为新增，其他方向为前批记录。</p>'
    page += table(["方向", "Z35 两笔", "Z30 两笔", "Z27 两笔"], [[NAMES[d]]+[" / ".join(f"{r['stat']['primary_median_uT']:.1f}" for r in groups[d, z]) for z in LEVELS] for d in UNITS])
    page += '<h2>新增数据质量</h2>' + table(["传感器帧数", "invalid传感器", "TCP样本", "invalid TCP", "最大TCP Z偏差/mm"], [[summary["new_run_quality"][k] for k in ("sensor_frames", "sensor_invalid", "tcp_samples", "tcp_invalid", "max_hold_tcp_z_deviation_mm")]])
    page += '<h2>候选公式</h2><p>g方向 = k × gX + b；校正值 gX = (g方向 − b)/k。参数仅供离线分析，未写入控制配置。拟合使用新Z35/Z27的高度均值。</p>'
    page += table(["方向", "k", "b/uT", "Z30均值换算误差/uT"], [[NAMES[r["direction"]], f"{r['gain']:.4f}", f"{r['offset_uT']:.2f}", f"{r['z30_mean_check_x_equivalent_error_uT']:.2f}"] for r in model_rows if r["model"] == "gain_offset"])
    page += '<h2>独立笔次验证</h2><p>用一组笔次拟合两个新高度，另一组验证，再交换。下表误差已换算到X尺度；20 uT仅为用户给定比较量级。</p>'
    page += table(["方向", "模型", "RMSE/uT", "最大绝对误差/uT", "20 uT内条件数/4"], [[NAMES[r["direction"]], r["model"], f"{r['x_equivalent_rmse_uT']:.2f}", f"{r['max_abs_x_equivalent_error_uT']:.2f}", r["conditions_within_user_20uT_scale"]] for r in cv_summary])
    for filename, title in (("01_height_curves.png", "各高度主窗口曲线"), ("02_candidate_models.png", "方向映射候选"), ("03_reference_and_validation.png", "X参照变化及独立验证"), ("04_full_z27_traces.png", "Z27完整曲线与起笔峰值")):
        page += f'<h2>{title}</h2><img src="{filename}">'
    page += '<h2>下一步</h2>' + "".join("<p>"+html.escape(text)+"</p>" for text in next_steps)
    page += '<h2>适用边界</h2>' + "".join("<p>"+html.escape(text)+"</p>" for text in limitations)
    page += '<p>' + " · ".join(f'<a href="{name}">{label}</a>' for name,label in (("summary.json", "完整统计与原始输入哈希"), ("height_repeatability.csv", "各高度重复性"), ("heldout_predictions.csv", "独立笔次预测"), ("run_quality.csv", "逐笔质量"), ("candidate_models.csv", "候选参数"))) + '</p></html>'
    (OUT/"index.html").write_text(page)
    print(json.dumps({k:summary[k] for k in ("new_run_count", "new_run_quality", "all_run_quality", "validation_summary", "x_reference_shift")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
