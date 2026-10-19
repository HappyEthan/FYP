#!/usr/bin/env python3
"""Offline audit of this day's first-stage runs; raw inputs are never changed."""
import csv
import hashlib
import html
import json
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).resolve().parent
BASE = OUT.parent.parent
UNITS = {"right": (1, 0), "up": (0, 1), "left": (-1, 0), "down": (0, -1)}
NAMES = {"right": "+X", "up": "+Y", "left": "-X", "down": "-Y"}
EDGES = np.arange(25.5, 35.50001, .25)
CENTERS = (EDGES[:-1] + EDGES[1:]) / 2


def read_json(path):
    return json.loads(path.read_text())


def save_csv(name, rows):
    if not rows:
        return
    with (OUT / name).open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def read_run(folder):
    manifest = read_json(folder / "manifest.json")
    profile = read_json(folder / "identification.json")
    setup = read_json(folder / "settings.json")
    resolved = read_json(folder / "resolved.json")
    assert manifest["status"] == "completed"
    assert manifest["execution_environment"] == "hardware"
    for name, digest in manifest["sha256"].items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest
    rows = [json.loads(line) for line in (folder / "control.jsonl").read_text().splitlines()]
    sensor = list(csv.DictReader((folder / "sensor.csv").open()))
    lookup = {int(row["seq"]): row for row in sensor}
    tcp = list(csv.DictReader((folder / "actual_tcp.csv").open()))
    tcp_meta = read_json(folder / "actual_tcp_meta.json")
    is_hold = profile["mode"] == "four-direction-hold"
    phase = "straight_hold" if is_hold else "sweep_down"
    measure = [row for row in rows if row["phase"] == phase]
    g = np.array([row["a_control_uT"] for row in measure])
    z = np.array([row["z_cmd_m"] * 1000 for row in measure])
    xy = np.array([[row["x_cmd_m"] * 1000, row["y_cmd_m"] * 1000] for row in measure])
    origin = np.array([setup["origin_x_mm"], setup["origin_y_mm"]])
    unit = np.array(UNITS[profile["direction"]])
    distance = (xy - origin) @ unit
    assert np.isfinite(g).all()
    baseline = manifest["baselines"][-1]
    ids = {int(lookup[row["sample_seq"]]["baseline_id"]) for row in measure}
    assert ids == {baseline["baseline_id"]}
    assert baseline["quality_axes"] == [0, 1]
    assert profile["travel_mm"] == 150 and profile["entry_contact_z_mm"] == 36
    assert profile["entry_tilt_deg"] == 30 and profile["writing_tilt_deg"] == 15
    assert setup["filter"] == {"kind": "ema", "alpha": .3}
    assert setup["wait_z_mm"] == 70
    post = [row for row in rows if row["phase"] == "post_lift_hold"]
    post_tail = [row for row in post if row["t_s"] >= post[-1]["t_s"] - .5]
    post_delta = np.array([[float(lookup[row["sample_seq"]][key])
                            for key in ("dBx_uT", "dBy_uT", "dBz_uT")]
                           for row in post_tail])
    selected_tcp = [row for row in tcp if row["valid"] == "true"
                    and measure[0]["host_ns"] <= (int(row["request_start_ns"])
                    + int(row["request_end_ns"])) / 2 <= measure[-1]["host_ns"]]
    xyz = np.array([[float(row[key]) * 1000 for key in ("x_m", "y_m", "z_m")]
                   for row in selected_tcp])
    td = (xyz[:, :2] - origin) @ unit
    if is_hold:
        expected_z = np.full(len(xyz), profile["start_z_mm"])
    else:
        q = np.clip(2 * td / 150 - 1, 0, 1)
        expected_z = 36 - 11 * (10*q**3 - 15*q**4 + 6*q**5)
    stat = dict(run_id=manifest["run_id"], folder=folder.name,
                batch_id=resolved["batch_id"], trial_index=resolved["trial_index"],
                mode=profile["mode"], direction=profile["direction"],
                speed_mm_s=profile["speed_mm_s"], command_z_start_mm=profile["start_z_mm"],
                command_z_end_mm=profile["end_z_mm"], control_measure_samples=len(measure),
                sensor_frames=len(sensor), sensor_invalid=sum(row["valid"] != "true" for row in sensor),
                max_measure_age_ms=max(row["sample_age_s"] for row in measure)*1000,
                tcp_samples=tcp_meta["samples"], tcp_invalid=tcp_meta["invalid_samples"],
                tcp_worker_stopped=tcp_meta["worker_stopped"],
                tcp_z_path_max_abs_mm=float(abs(xyz[:, 2] - expected_z).max()),
                baseline_bx_uT=baseline["B0_uT"][0], baseline_by_uT=baseline["B0_uT"][1],
                baseline_std_bx_uT=baseline["std_uT"][0], baseline_std_by_uT=baseline["std_uT"][1],
                post_air_ema_median_uT=float(np.median([row["a_control_uT"] for row in post_tail])),
                post_air_mean_dbx_uT=float(post_delta[:, 0].mean()),
                post_air_mean_dby_uT=float(post_delta[:, 1].mean()),
                hold_median_uT=None, hold_cv_pct=None, hold_early_uT=None,
                hold_middle_uT=None, hold_late_uT=None, hold_late_minus_early_uT=None,
                hold_tail_120_150_median_uT=None, hold_tail_120_150_max_uT=None,
                full_measure_peak_uT=float(g.max()), peak_distance_mm=float(distance[g.argmax()]),
                sweep_z30_uT=None, max_bin_drop_uT=None)
    bins = None
    if is_hold:
        assert np.allclose(z, 30)
        core = g[(distance >= 30) & (distance <= 120)]
        windows = [float(np.median(g[(distance >= lo) & (distance < lo+30)]))
                   for lo in (30, 60, 90)]
        stat.update(hold_median_uT=float(np.median(core)),
                    hold_cv_pct=float(np.std(core) / np.mean(core) * 100),
                    hold_early_uT=windows[0], hold_middle_uT=windows[1], hold_late_uT=windows[2],
                    hold_late_minus_early_uT=windows[2]-windows[0],
                    hold_tail_120_150_median_uT=float(np.median(g[distance >= 120])),
                    hold_tail_120_150_max_uT=float(g[distance >= 120].max()))
    else:
        assert np.all(np.diff(z) <= 1e-8) and abs(z[-1]-25) < 1e-6
        samples = [g[(z >= lo) & (z < hi)] for lo, hi in zip(EDGES[:-1], EDGES[1:])]
        assert min(map(len, samples)) >= 3
        bins = np.array([np.median(values) for values in samples])
        stat.update(sweep_z30_uT=float(np.interp(30, CENTERS, bins)),
                    max_bin_drop_uT=float(max(0, -np.diff(bins[::-1]).min())))
    return dict(stat=stat, folder=folder, profile=profile, measure=measure,
                distance=distance, g=g, z=z, bins=bins)


def main():
    runs = [read_run(path.parent) for path in sorted((BASE / "raw").glob("*/manifest.json"))]
    holds = [run for run in runs if run["bins"] is None]
    sweeps = [run for run in runs if run["bins"] is not None]
    assert len(runs) == 18 and len(holds) == 12 and len(sweeps) == 6
    groups = defaultdict(list)
    for run in sweeps:
        groups[run["stat"]["direction"], run["stat"]["speed_mm_s"]].append(run)
    repeat = []
    for (direction, speed), pair in groups.items():
        assert len(pair) == 2
        delta = pair[1]["bins"] - pair[0]["bins"]
        repeat.append(dict(direction=direction, speed_mm_s=speed,
                           run1=pair[0]["stat"]["run_id"], run2=pair[1]["stat"]["run_id"],
                           mae_uT=float(np.mean(abs(delta))),
                           rmse_uT=float(np.sqrt(np.mean(delta**2))),
                           max_abs_uT=float(abs(delta).max()),
                           mean_signed_shift_uT=float(delta.mean()),
                           centered_difference_rmse_uT=float(np.std(delta)),
                           correlation=float(np.corrcoef(pair[0]["bins"], pair[1]["bins"])[0, 1]),
                           run1_z30_uT=pair[0]["stat"]["sweep_z30_uT"],
                           run2_z30_uT=pair[1]["stat"]["sweep_z30_uT"]))
    history = []
    for hold in holds:
        key = (hold["stat"]["direction"], hold["stat"]["speed_mm_s"])
        for sweep in groups.get(key, []):
            d_at30 = float(np.interp(30, sweep["z"][::-1], sweep["distance"][::-1]))
            near = hold["g"][abs(hold["distance"]-d_at30) <= 5]
            h = float(np.median(near))
            history.append(dict(direction=key[0], speed_mm_s=key[1],
                                hold_run_id=hold["stat"]["run_id"], sweep_run_id=sweep["stat"]["run_id"],
                                sweep_distance_at_z30_mm=d_at30, hold_window_half_width_mm=5,
                                hold_same_position_median_uT=h, sweep_z30_uT=sweep["stat"]["sweep_z30_uT"],
                                hold_minus_sweep_uT=h-sweep["stat"]["sweep_z30_uT"]))
    save_csv("run_quality.csv", [run["stat"] for run in runs])
    save_csv("sweep_repeatability.csv", repeat)
    save_csv("hold_vs_sweep_z30.csv", history)
    save_csv("sweep_bins.csv", [dict(run_id=run["stat"]["run_id"], direction=run["stat"]["direction"],
                                     speed_mm_s=run["stat"]["speed_mm_s"], command_z_mm=float(z),
                                     median_uT=float(g)) for run in sweeps for z, g in zip(CENTERS, run["bins"])])
    plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False})
    colors = {7: "#21845f", 10: "#2474b5", 15: "#dd8433"}
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    for ax, direction in zip(axes.flat, UNITS):
        for run in holds:
            if run["stat"]["direction"] == direction:
                speed = run["stat"]["speed_mm_s"]
                ax.plot(run["distance"], run["g"], color=colors[speed], label=f"{speed:g} mm/s")
        ax.axvspan(30, 120, color="grey", alpha=.08)
        ax.set(title=NAMES[direction], xlabel="Travel / mm", ylabel="EMA |delta Bxy| / uT", xlim=(0, 150))
        ax.grid(alpha=.2)
        ax.legend()
    fig.suptitle("Z30 hold: 12 runs, ONE independent run per direction/speed\nPrimary window: 30-120 mm; no between-run repeatability estimate")
    fig.savefig(OUT / "01_hold_curves.png", dpi=160)
    plt.close(fig)
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), constrained_layout=True)
    for ax, (key, pair) in zip(axes, groups.items()):
        for index, run in enumerate(pair, 1):
            ax.plot(CENTERS, run["bins"], label=f"repeat {index}")
        ax.set(title=f"{NAMES[key[0]]}, {key[1]:g} mm/s", xlabel="Command Z / mm",
               ylabel="EMA |delta Bxy| / uT", xlim=(35.5, 25.5))
        ax.grid(alpha=.2)
        ax.legend()
    fig.suptitle("Sweep repeatability: identical command-Z bins, 25.5-35.5 mm\nCorrelated shapes do not establish absolute agreement")
    fig.savefig(OUT / "02_sweep_repeats.png", dpi=160)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(12, 5), constrained_layout=True)
    ax.bar(range(len(runs)), [run["stat"]["post_air_ema_median_uT"] for run in runs], color="#b36b46")
    ax.set_xticks(range(len(runs)), [f"{NAMES[run['stat']['direction']]} {run['stat']['speed_mm_s']:g}\n{'hold' if run['bins'] is None else 'sweep'}" for run in runs], fontsize=8)
    ax.set(ylabel="End-air residual relative to start baseline / uT",
           title="Z70 after lift: last 0.5 s of the 2 s airborne hold\nDifferent XY positions and preceding contact history; not a correction estimate")
    ax.grid(axis="y", alpha=.2)
    fig.savefig(OUT / "03_end_air_residual.png", dpi=160)
    plt.close(fig)
    missing = [dict(mode="hold", direction=direction, speed_mm_s=speed, command_z_mm=30,
                    available_independent_runs=1, additional_runs_for_two=1)
               for direction in UNITS for speed in (7, 10, 15)]
    summary = dict(status="descriptive_stage1_review", calibration_approved=False,
                   observed_runs=18, completed_runs=18, hold_runs=12, sweep_runs=6,
                   hold_primary_window_mm=[30, 120], sweep_z_bin_range_mm=[25.5, 35.5],
                   sweep_z_bin_width_mm=.25, missing_for_original_30=missing,
                   sensor_frames=sum(run["stat"]["sensor_frames"] for run in runs),
                   invalid_sensor_frames=sum(run["stat"]["sensor_invalid"] for run in runs),
                   tcp_samples=sum(run["stat"]["tcp_samples"] for run in runs),
                   tcp_invalid=sum(run["stat"]["tcp_invalid"] for run in runs),
                   max_measure_sensor_age_ms=max(run["stat"]["max_measure_age_ms"] for run in runs),
                   end_air_residual_range_uT=[min(run["stat"]["post_air_ema_median_uT"] for run in runs),
                                              max(run["stat"]["post_air_ema_median_uT"] for run in runs)],
                   sweep_repeatability=repeat, hold_vs_sweep_same_position=history,
                   conclusions=["Z30每个方向/速度仅一笔，不能估计跨笔重复性或作方向/速度因果结论。",
                                "+X两次扫描形状高度相关，但绝对响应相差约71 uT，尚不能平均成已验证前馈表。",
                                "本次四笔-X扫描未重现9/27的大幅局部回落，但不能解释旧异常原因。",
                                "完整Z30定高曲线仍有后段异常：-X的10/15 mm/s在约120-150 mm明显增大，15 mm/s峰值约500 uT；该段保留展示，不纳入预先规定的30-120 mm主统计窗口。",
                                "Z70末段仍有40-89 uT空载残差，需要空载往返区分位置磁场与卸载/漂移影响。",
                                "暂停直接扩展Z35/Z27的48笔；优先空载对照及补齐Z30第二轮。"],
                   limitations=["所有统计以命令高度为口径，不是法向力或笔毫实际压入量。",
                                "TCP按请求起止中点筛阶段，只作异步几何诊断，不作逐点同步真值。",
                                "方向与倾斜姿态同时变化；速度与固定顺序、补水、时间可能混杂。",
                                "空载末端残差不是可直接扣除的接触信号偏置。",
                                "曲线分箱不是独立实验重复；未选择性排除局部异常。"],
                   next_experiments=[
                       dict(priority=1, description="补齐Z30第二轮：四方向，各速度再采一笔；速度顺序7→15→10 mm/s。每笔统一补水、控滴、等待，使用新纸带，记录补水和纸面编号。", new_runs=12),
                       dict(priority=2, description="+X、-X空载往返对照：10 mm/s，Z70，沿原150 mm路径往返，各2次。始终保持本方向15度姿态，起点、终点、返回起点各停10 s，全程无接触。记录原始三轴及TCP。当前入口没有空载模式，不能把hold高度直接改成70。", new_runs=4),
                       dict(priority=3, description="只有定高重复与空载零点影响可解释后，先补10 mm/s下Z35、Z27，四方向各2笔。", new_runs=16),
                       dict(priority=4, description="确认速度差异可重复后，再补Z35、Z27下7和15 mm/s，四方向各2笔。", new_runs=32)],
                   input_sha256={str(path.relative_to(BASE)): hashlib.sha256(path.read_bytes()).hexdigest()
                                 for run in runs for path in run["folder"].iterdir() if path.is_file()})
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))
    page = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>10月5日第一阶段分析</title><style>body{max-width:1200px;margin:auto;padding:24px;font:17px/1.7 sans-serif;color:#20354a}img{width:100%}td,th{padding:8px;border-bottom:1px solid #ddd}table{border-collapse:collapse}</style><h1>10月5日第一阶段分析：18笔</h1>'
    page += "".join("<p>" + html.escape(text) + "</p>" for text in summary["conclusions"])
    page += '<h2>Z30定高中段中位数（uT）</h2><p>沿程30-120 mm；每格仅一笔。</p><table><tr><th>方向</th><th>7 mm/s</th><th>10 mm/s</th><th>15 mm/s</th></tr>'
    for direction in UNITS:
        page += '<tr><td>' + NAMES[direction] + '</td>'
        for speed in (7, 10, 15):
            run = next(run for run in holds if run["stat"]["direction"] == direction and run["stat"]["speed_mm_s"] == speed)
            page += f'<td>{run["stat"]["hold_median_uT"]:.2f}</td>'
        page += '</tr>'
    page += '</table>'
    for filename, title in (("01_hold_curves.png", "定高沿程曲线"), ("02_sweep_repeats.png", "扫描两笔对照"), ("03_end_air_residual.png", "抬笔末段空载残差")):
        page += f'<h2>{title}</h2><img src="{filename}">'
    page += '<h2>适用边界</h2>' + ''.join('<p>' + html.escape(text) + '</p>' for text in summary["limitations"])
    page += '<h2>下一轮采集顺序</h2>' + ''.join(f'<p>{item["priority"]}. {html.escape(item["description"])} 新增{item["new_runs"]}笔。</p>' for item in summary["next_experiments"])
    page += '<p><a href="summary.json">完整统计与输入哈希</a> · <a href="run_quality.csv">逐笔质量与定高变化</a> · <a href="sweep_repeatability.csv">扫描重复差</a> · <a href="hold_vs_sweep_z30.csv">同高度、同位置附近的加载路径对照</a></p></html>'
    (OUT / "index.html").write_text(page)
    print(json.dumps({key: summary[key] for key in ("observed_runs", "hold_runs", "sweep_runs", "sensor_frames", "invalid_sensor_frames", "tcp_samples", "tcp_invalid", "max_measure_sensor_age_ms", "end_air_residual_range_uT", "sweep_repeatability", "hold_vs_sweep_same_position")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
