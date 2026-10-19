#!/usr/bin/env python3
"""Audit the first 30 runs, including the second Z30 round, without changing raw data."""
import csv
import hashlib
import html
import importlib.util
import json
import os
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/fyp-matplotlib")
OUT = Path(__file__).resolve().parent
BASE = OUT.parent.parent
HELPER = OUT.parent / "stage1_review" / "analyze.py"
spec = importlib.util.spec_from_file_location("stage1_reader", HELPER)
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)
np = reader.np
plt = reader.plt
NAMES = reader.NAMES
DIRECTIONS = tuple(reader.UNITS)
SPEEDS = (7, 10, 15)
CUTOFF = "20261005T070101.617743Z-155869"
SECOND_ROUND_START = "20261005T065033.031523Z-cb61c7"
DISTANCE_EDGES = np.arange(30, 120.001, 5)
DISTANCE_CENTERS = (DISTANCE_EDGES[:-1] + DISTANCE_EDGES[1:]) / 2


def save_csv(name, rows):
    with (OUT / name).open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def distance_bins(run):
    values = [run["g"][(run["distance"] >= lo) & (run["distance"] < hi)]
              for lo, hi in zip(DISTANCE_EDGES[:-1], DISTANCE_EDGES[1:])]
    assert min(map(len, values)) >= 10
    return np.array([np.median(v) for v in values])


def table(headers, rows):
    return "<table><thead><tr>" + "".join(f"<th>{html.escape(str(v))}</th>" for v in headers) + "</tr></thead><tbody>" + "".join("<tr>" + "".join(f"<td>{html.escape(str(v))}</td>" for v in row) + "</tr>" for row in rows) + "</tbody></table>"


def main():
    folders = [p.parent for p in sorted((BASE / "raw").glob("*/manifest.json"))
               if reader.read_json(p)["run_id"] <= CUTOFF]
    runs = sorted([reader.read_run(p) for p in folders], key=lambda r: r["stat"]["run_id"])
    holds = [r for r in runs if r["bins"] is None]
    new = [r for r in holds if r["stat"]["run_id"] >= SECOND_ROUND_START]
    assert len(runs) == 30 and len(holds) == 24 and len(new) == 12
    groups = defaultdict(list)
    for run in holds:
        groups[run["stat"]["direction"], run["stat"]["speed_mm_s"]].append(run)
    assert set(groups) == {(d, v) for d in DIRECTIONS for v in SPEEDS}
    assert all(len(pair) == 2 for pair in groups.values())
    assert len({r["stat"]["batch_id"] for r in holds if r not in new}) == 1
    assert len({r["stat"]["batch_id"] for r in new}) == 3
    repeat, bins_rows = [], []
    for direction in DIRECTIONS:
        for speed in SPEEDS:
            pair = groups[direction, speed]
            s, t = (r["stat"] for r in pair)
            values = [distance_bins(r) for r in pair]
            delta = values[1] - values[0]
            repeat.append(dict(
                direction=direction, speed_mm_s=speed,
                run1_id=s["run_id"], run2_id=t["run_id"],
                round1_median_uT=s["hold_median_uT"], round2_median_uT=t["hold_median_uT"],
                median_delta_uT=t["hold_median_uT"]-s["hold_median_uT"],
                median_change_pct=(t["hold_median_uT"]/s["hold_median_uT"]-1)*100,
                matched_5mm_bin_mae_uT=float(abs(delta).mean()),
                matched_5mm_bin_rmse_uT=float(np.sqrt(np.mean(delta**2))),
                mean_signed_bin_shift_uT=float(delta.mean()),
                rmse_after_removing_constant_shift_uT=float(np.std(delta)),
                matched_bin_correlation=float(np.corrcoef(*values)[0, 1]),
                round1_late_minus_early_uT=s["hold_late_minus_early_uT"],
                round2_late_minus_early_uT=t["hold_late_minus_early_uT"],
                round1_tail_max_uT=s["hold_tail_120_150_max_uT"],
                round2_tail_max_uT=t["hold_tail_120_150_max_uT"],
                round1_end_air_uT=s["post_air_ema_median_uT"],
                round2_end_air_uT=t["post_air_ema_median_uT"]))
            for number, run in enumerate(pair, 1):
                bins_rows += [dict(run_id=run["stat"]["run_id"], round=number,
                                   direction=direction, speed_mm_s=speed,
                                   distance_center_mm=float(x), median_uT=float(y))
                              for x, y in zip(DISTANCE_CENTERS, values[number-1])]
    speed_rows = []
    for direction in DIRECTIONS:
        for speed in (7, 15):
            reference = [r["stat"]["hold_median_uT"] for r in groups[direction, 10]]
            contrast = [r["stat"]["hold_median_uT"] for r in groups[direction, speed]]
            differences = np.array(contrast)-reference
            speed_rows.append(dict(direction=direction, compare_speed_mm_s=speed,
                                   reference_speed_mm_s=10,
                                   round1_delta_uT=float(differences[0]),
                                   round2_delta_uT=float(differences[1]),
                                   round1_delta_pct=float(differences[0]/reference[0]*100),
                                   round2_delta_pct=float(differences[1]/reference[1]*100),
                                   same_sign_in_two_rounds=bool(np.prod(differences) > 0)))
    ratio_rows = []
    for direction in DIRECTIONS[1:]:
        for speed in SPEEDS:
            x = [r["stat"]["hold_median_uT"] for r in groups["right", speed]]
            other = [r["stat"]["hold_median_uT"] for r in groups[direction, speed]]
            ratio_rows.append(dict(direction=direction, speed_mm_s=speed,
                                   round1_ratio_to_x=other[0]/x[0], round2_ratio_to_x=other[1]/x[1],
                                   ratio_change_pct=(other[1]/x[1]/(other[0]/x[0])-1)*100))

    def quality(subset):
        return dict(runs=len(subset), sensor_frames=sum(r["stat"]["sensor_frames"] for r in subset),
                    invalid_sensor_frames=sum(r["stat"]["sensor_invalid"] for r in subset),
                    tcp_samples=sum(r["stat"]["tcp_samples"] for r in subset),
                    tcp_invalid=sum(r["stat"]["tcp_invalid"] for r in subset),
                    max_measure_sensor_age_ms=max(r["stat"]["max_measure_age_ms"] for r in subset),
                    max_hold_tcp_z_deviation_mm=max(r["stat"]["tcp_z_path_max_abs_mm"] for r in subset if r["bins"] is None),
                    end_air_residual_range_uT=[min(r["stat"]["post_air_ema_median_uT"] for r in subset),
                                               max(r["stat"]["post_air_ema_median_uT"] for r in subset)])

    conclusions = [
        "30笔已齐：6笔扫描，24笔Z30定高；四方向×三速度各有两笔独立记录。新增12笔与全批均无记录为invalid的传感器或TCP样本。",
        "方向/姿态组合的差异可重复：两轮每个速度均为-Y最大；例如10 mm/s的-Y比-X高158.09和125.47 uT。方向、倾斜姿态、路径位置及固定执行顺序同时变化，尚不能归因于纯方向。",
        "-X中段跨笔相差2.2%-4.0%，+Y相差2.7%-6.8%；+X的10/15 mm/s相差-18.9%/+20.9%，-Y的15 mm/s相差+25.9%。不能把所有条件的两笔平均后当作稳定标定值。",
        "+X10、+X15及-Y15的重复差主要是整条曲线偏移：等距离分箱平均偏移分别为-51.03、+52.70、+74.04 uT；去除该单一偏移后的残差RMSE仅1.38、2.40、2.10 uT。这是重复差的描述，不是已验证的校正方法。",
        "速度差异部分可重复：-X两轮均7>15>10 mm/s；7相对10高32.01/36.69 uT，15相对10高17.37/20.58 uT。+X和-Y的15相对10差异反号，不能采用统一的随速度单调变化公式。",
        "-X首轮10/15 mm/s的408/501 uT后段峰值，第二轮未重现（全程峰值234/251 uT）；但六笔-X在中段末30 mm比前30 mm均高约36-43 uT，沿程变化仍可重复。保留首轮峰值，不作选择性删除。",
        "按用户提供的实验背景，本轮不考虑水的影响，以触角装配偏向一侧及背景磁场为主要校准对象。采集脚本已在每个方向15度姿态、起点Z70单独归零，因此已有方向姿态的起点参考；沿程背景和加载后的状态变化仍需对照。",
        "新增笔抬至Z70后的末段残差仍为16.79-88.43 uT；其起点与终点XY不同，且经历过接触。优先空载往返诊断，再扩展高度。",
        "暂不发布方向增益或新前馈表。Z30单一高度不能同时辨识方向增益和偏置，旧9/25换笔前的X表也不能直接作为这支笔的参照。"]
    limitations = [
        "主统计窗口沿用第一阶段预先规定的30-120 mm；完整0-150 mm轨迹和后段峰值均保留。5 mm分箱用于同位置对照，不算独立重复；每条件仅两笔，未作显著性或置信区间声明。",
        "round1/round2按同条件记录的时间先后定义。第一轮速度顺序10→15→7，第二轮7→15→10；方向始终+X→+Y→-X→-Y。首轮为一个批次，第二轮为三个批次，因此不是完全随机且批次一致的因果设计。",
        "两轮相同方向的起点、终点、命令Z30和倾斜轨迹一致；异步TCP几何诊断发现最大Z偏差约0.211 mm。这不能验证法向力、笔毫实际压入量，也不能排除小高度变化的影响。",
        "抬笔后的空载残差不能直接从接触幅值中相减；XY、Z和受载历史不同。即使后续取得相同条件的空载参考，也应先处理三轴矢量而非直接相减两个模长。",
        "用户补充：水的影响不大，本轮不考虑；触角偏向一侧，方向差异主要按装配不对称和背景磁场处理。装配状况是用户提供的信息；单靠这批接触数据还不能定量分解装配与背景场各自的贡献。",
        "校正候选仅限后续可辨识模型：固定v=10时g_theta(Z)=k_theta*f_X(Z)+b_theta，换算g_X=(g_theta-b_theta)/k_theta。f_X需由同一支笔、同一加载协议的新高度数据建立。三个高度可初步检查仿射关系；四个轴向方向的拟合不能证明对任意角度有效。"]
    next_steps = [
        dict(priority=1, new_runs=8, description="四方向空载往返，各两次：10 mm/s、Z70，同方向15度姿态，原路径150 mm往返，起点/终点/回到起点各停10 s。检查位置依赖和回零漂移；优先+X/-X的4次，再+Y/-Y的4次。相比上一阶段只建议X方向4次，现在按用户明确的背景场校准目标覆盖全部四方向。当前采集入口没有空载模式，不使用--hold-z-mm 70。Z70对照用于诊断，不能直接当作Z30接触数据的可扣除零点。"),
        dict(priority=2, new_runs=18, description="空载/状态偏移可解释后，先固定10 mm/s，补Z35、Z27，四方向各两笔（16笔）；每轮另插入一笔+X/Z30参照（共2笔），检查参照跨笔偏移，总18笔。保持装配不变并使用新纸带；两轮交换高度顺序，并反转方向顺序。若空载显示明显位置影响并导致采集参考协议改变，应按新协议重新采对应Z30，避免把旧Z30与新协议强行合并。"),
        dict(priority=3, new_runs=None, description="用同一支笔的Z35/Z30/Z27定高数据比较仅增益与增益+偏置模型，按整笔验证。通过后增加45°、135°、225°、315°作为未参与拟合方向的验证，再决定是否补7/15 mm/s多高度数据。")]

    summary = dict(status="descriptive_stage2_review", calibration_approved=False,
                   cutoff_run_id=CUTOFF, observed_runs=30, hold_runs=24, sweep_runs=6,
                   independent_runs_per_hold_condition=2, primary_distance_window_mm=[30, 120],
                   user_context=dict(ignore_water_effect=True,
                                     asymmetric_assembly_reported=True,
                                     background_field_is_calibration_target=True),
                   diagnostic_distance_bin_width_mm=5, new_round_quality=quality(new),
                   all_runs_quality=quality(runs), hold_repeatability=repeat,
                   speed_contrasts=speed_rows, descriptive_ratios_to_x=ratio_rows,
                   conclusions=conclusions, limitations=limitations, next_experiments=next_steps,
                   input_sha256={str(p.relative_to(BASE)): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for r in runs for p in sorted(r["folder"].iterdir()) if p.is_file()},
                   generator_sha256={str(p.relative_to(BASE)): hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in (Path(__file__).resolve(), HELPER)})
    save_csv("run_quality.csv", [dict(round=1 if r["stat"]["run_id"] < SECOND_ROUND_START else 2,
                                       **r["stat"]) for r in runs])
    save_csv("hold_repeatability.csv", repeat)
    save_csv("hold_distance_bins.csv", bins_rows)
    save_csv("speed_contrasts.csv", speed_rows)
    save_csv("direction_ratios.csv", ratio_rows)
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))

    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    colors = ("#2474b5", "#df7836")
    fig, axes = plt.subplots(4, 3, figsize=(15, 14), sharex=True, sharey=True, constrained_layout=True)
    for i, direction in enumerate(DIRECTIONS):
        for j, speed in enumerate(SPEEDS):
            ax = axes[i, j]
            for rep, run in enumerate(groups[direction, speed]):
                ax.plot(run["distance"], run["g"], color=colors[rep], linewidth=1.1,
                        label=f"Round {rep+1}: {run['stat']['hold_median_uT']:.1f} uT")
            ax.axvspan(30, 120, color="grey", alpha=.10)
            ax.set(title=f"{NAMES[direction]}, {speed} mm/s", xlim=(0, 150), ylim=(0, 530))
            ax.grid(alpha=.18)
            ax.legend(loc="upper left", fontsize=8)
            if j == 0:
                ax.set_ylabel("EMA |delta Bxy| / uT")
            if i == 3:
                ax.set_xlabel("Command travel / mm")
    fig.suptitle("Z30: two independent strokes per condition, full traces retained\nShaded: unchanged primary window 30-120 mm; legend: within-window median", fontsize=15)
    fig.savefig(OUT / "01_hold_rounds.png", dpi=150)
    plt.close(fig)
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), sharex=True, constrained_layout=True)
    for ax, direction in zip(axes.flat, DIRECTIONS):
        for rep in range(2):
            values = [groups[direction, v][rep]["stat"]["hold_median_uT"] for v in SPEEDS]
            ax.plot(SPEEDS, values, "o-", color=colors[rep], label=f"Round {rep+1}")
        ax.set(title=NAMES[direction], ylabel="30-120 mm median / uT", xlabel="Speed / mm/s", xticks=SPEEDS)
        ax.grid(alpha=.2)
        ax.legend()
    fig.suptitle("Speed comparisons: descriptive only, two strokes per condition\nLines connect measured levels; they are not fitted speed laws")
    fig.savefig(OUT / "02_speed_comparison.png", dpi=150)
    plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(14, 5), constrained_layout=True)
    labels = [f"{NAMES[row['direction']]} {row['speed_mm_s']}" for row in repeat]
    axes[0].bar(range(12), [row["mean_signed_bin_shift_uT"] for row in repeat], color="#2474b5")
    axes[0].axhline(0, color="black", linewidth=.7)
    axes[0].set(ylabel="Round 2 - round 1 / uT", title="Mean shift in matched 5 mm bins")
    for rep in range(2):
        axes[1].bar(np.arange(12)+(rep-.5)*.35,
                    [row[f"round{rep+1}_end_air_uT"] for row in repeat], width=.35,
                    color=colors[rep], label=f"Round {rep+1}")
    axes[1].set(ylabel="End-air residual / uT", title="Z70: last 0.5 s of post-lift hold")
    axes[1].legend()
    for ax in axes:
        ax.set_xticks(range(12), labels, rotation=45, ha="right")
        ax.grid(axis="y", alpha=.2)
    fig.suptitle("Offsets and airborne residuals are diagnostics, not validated corrections")
    fig.savefig(OUT / "03_offsets_and_air.png", dpi=150)
    plt.close(fig)

    page = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>10月5日第二轮分析</title><style>body{max-width:1200px;margin:auto;padding:24px;font:17px/1.7 sans-serif;color:#20354a}img{width:100%;height:auto}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left}table{border-collapse:collapse;width:100%}a{color:#2474b5}</style><h1>新增12笔分析：Z30两轮，累计30笔</h1>'
    page += "".join("<p>"+html.escape(v)+"</p>" for v in conclusions)
    page += '<h2>Z30主窗口中位数：第一轮 → 第二轮（uT）</h2><p>每格两笔独立记录；统计窗口沿程30–120 mm，不包含起笔和120–150 mm末段。</p>'
    rows = []
    for d in DIRECTIONS:
        rows.append([NAMES[d]]+[" → ".join(f"{r['stat']['hold_median_uT']:.1f}" for r in groups[d, v]) for v in SPEEDS])
    page += table(["方向", "7 mm/s", "10 mm/s", "15 mm/s"], rows)
    page += '<h2>数据质量</h2>' + table(["范围", "传感器帧数", "invalid帧", "TCP样本", "invalid TCP", "最大定高TCP Z偏差/mm"],
        [[label, q["sensor_frames"], q["invalid_sensor_frames"], q["tcp_samples"], q["tcp_invalid"], f"{q['max_hold_tcp_z_deviation_mm']:.3f}"]
         for label, q in (("新增12笔", summary["new_round_quality"]), ("累计30笔", summary["all_runs_quality"]))])
    for name, title in (("01_hold_rounds.png", "逐条件完整曲线"), ("02_speed_comparison.png", "两轮速度对照"), ("03_offsets_and_air.png", "整段偏移与抬笔残差")):
        page += f'<h2>{title}</h2><img src="{name}">'
    page += '<h2>下一步</h2>' + "".join(f"<p>{v['priority']}. {html.escape(v['description'])}" + (f" 新增{v['new_runs']}笔。" if v['new_runs'] is not None else "") + "</p>" for v in next_steps)
    page += '<h2>适用边界与候选公式</h2>' + "".join("<p>"+html.escape(v)+"</p>" for v in limitations)
    page += '<p>此页独立保存第二轮结论，第一阶段报告未覆盖。分析脚本固定截止记录，后续添加原始数据不会改变本批范围。</p><p>'
    page += " · ".join(f'<a href="{name}">{label}</a>' for name, label in (("summary.json", "完整统计与输入哈希"), ("hold_repeatability.csv", "两笔重复差"), ("run_quality.csv", "逐笔质量"), ("speed_contrasts.csv", "速度对照"), ("direction_ratios.csv", "未标定方向比例"), ("analyze.py", "重现分析脚本")))
    page += "</p></html>"
    (OUT / "index.html").write_text(page)
    print(json.dumps({k: summary[k] for k in ("observed_runs", "hold_runs", "new_round_quality", "all_runs_quality")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
