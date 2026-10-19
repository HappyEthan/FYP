#!/usr/bin/env python3
"""Reproducible offline direction-calibration benchmark. Never opens hardware.

Run with python3 <this file>. Raw records and robot configuration are read only.
The reader is pinned to the previous multiheight audit, with all raw hashes checked.
"""
import csv
import hashlib
import html
import importlib.util
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/fyp-matplotlib")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).resolve().parent
BASE = OUT.parent.parent
READER_PATH = OUT.parent / "stage3_review/analyze.py"
CUTOFF = "20261005T074054.304822Z-1014ac"
FIRST_NEW = "20261005T072249.453530Z-6a8c3a"
DIRECTIONS = ("right", "up", "left", "down")
NAMES = dict(right="+X", up="+Y", left="−X", down="−Y")
HEIGHTS = (35, 30, 27)
MODEL_NAMES = dict(M0="M0：统一使用 X 曲线", M1="M1：增益＋偏置", M2="M2：四方向分段曲线")
SUITE_NAMES = {
    "T3_old_X30": "旧批次 X/Z30",
    "T3_speed_7": "速度迁移：7 mm/s",
    "T3_speed_15": "速度迁移：15 mm/s",
    "T3_sweep_10": "半程下压：10 mm/s",
    "T3_sweep_15": "半程下压：15 mm/s",
}
WINDOWS = ((30, 120), (50, 100))
NOISE = 20.


class Curve:
    def __init__(self, depths, values):
        self.depths = np.asarray(depths, dtype=float)
        self.values = np.asarray(values, dtype=float)
        if (self.depths.ndim != 1 or self.values.shape != self.depths.shape
                or len(self.depths) < 2 or not np.isfinite(self.depths).all()
                or not np.isfinite(self.values).all()
                or not (np.diff(self.depths) > 0).all()
                or not (np.diff(self.values) > 0).all()):
            raise ValueError("strictly increasing finite depth and response nodes required")

    def forward(self, depth):
        if not np.isfinite(depth) or depth < self.depths[0] or depth > self.depths[-1]:
            return None
        return float(np.interp(depth, self.depths, self.values))

    def inverse(self, value):
        if not np.isfinite(value):
            return None, "invalid_measurement"
        if value < self.values[0]:
            return None, "below_range"
        if value > self.values[-1]:
            return None, "above_range"
        return float(np.interp(value, self.values, self.depths)), "ok"

    def slope(self, depth):
        i = int(np.clip(np.searchsorted(self.depths, depth, side="right") - 1,
                        0, len(self.depths) - 2))
        return float(np.diff(self.values)[i] / np.diff(self.depths)[i])

    def noise_depth_scale(self, depth):
        return NOISE / self.slope(depth)

    def to_dict(self):
        return dict(depth_nodes_mm=self.depths.tolist(), response_nodes_uT=self.values.tolist(),
                    sensitivity_uT_per_mm=(np.diff(self.values)/np.diff(self.depths)).tolist(),
                    user_20uT_depth_scale_mm=(NOISE*np.diff(self.depths)/np.diff(self.values)).tolist(),
                    exceeds_tentative_1mm_noise_scale=(NOISE*np.diff(self.depths)/np.diff(self.values)>1).tolist())


def affine_curve(x, y):
    # The X identity must preserve exact support endpoints, including roundoff.
    if np.array_equal(x.depths, y.depths) and np.array_equal(x.values, y.values):
        return Curve(x.depths, x.values), 1., 0.
    x_at_y = np.array([x.forward(d) for d in y.depths])
    k, b = np.linalg.lstsq(np.column_stack([x_at_y, np.ones(len(x_at_y))]),
                          y.values, rcond=None)[0]
    if k <= 0:
        raise ValueError("nonpositive fitted gain")
    return Curve(x.depths, k*x.values+b), float(k), float(b)


def ensure_disjoint(train_ids, test_ids):
    assert not set(train_ids) & set(test_ids), "training / test run_id overlap"


def summarize(rows):
    by_run = defaultdict(list)
    for row in rows:
        by_run[row["run_id"]].append(row)
    valid = [r for r in rows if r["inverse_status"] == "ok"]
    per_run_valid = [[r for r in group if r["inverse_status"] == "ok"]
                     for group in by_run.values()]
    per_run_valid = [group for group in per_run_valid if group]
    def equal_run_metric(field, squared=False, valid_only=False):
        means = []
        for group in by_run.values():
            values = [r[field] for r in group if r.get(field) is not None
                      and (not valid_only or r["inverse_status"] == "ok")]
            if values:
                values = np.asarray(values, dtype=float)
                means.append(float(np.mean(values**2 if squared else abs(values))))
        if not means:
            return None
        value = float(np.mean(means))
        return float(np.sqrt(value)) if squared else value
    return dict(total_runs=len(by_run), valid_runs=len(per_run_valid),
                total_predictions=len(rows), valid_predictions=len(valid),
                run_balanced_coverage=float(np.mean([
                    sum(r["inverse_status"] == "ok" for r in group)/len(group)
                    for group in by_run.values()])) if by_run else 0.,
                statuses=dict(Counter(r["inverse_status"] for r in rows)),
                forward_mae_uT=equal_run_metric("forward_error_uT"),
                forward_rmse_uT=equal_run_metric("forward_error_uT", squared=True),
                z_mae_mm_valid_only=equal_run_metric("z_error_mm", valid_only=True),
                z_rmse_mm_valid_only=equal_run_metric("z_error_mm", squared=True, valid_only=True),
                z_max_abs_mm_valid_only=max([abs(r["z_error_mm"]) for r in valid], default=None),
                x_equivalent_rmse_uT_valid_only=equal_run_metric("x_equivalent_error_uT", squared=True, valid_only=True),
                predictions_within_1mm=sum(abs(r["z_error_mm"]) <= 1 for r in valid),
                forward_predictions_within_user_20uT=sum(abs(r["forward_error_uT"]) <= NOISE
                                                       for r in rows if r.get("forward_error_uT") is not None))


def save_csv(name, rows):
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with (OUT/name).open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def read_runs():
    spec = importlib.util.spec_from_file_location("multiheight_audit_reader", READER_PATH)
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    folders = [p.parent for p in (BASE/"raw").glob("*/manifest.json")
               if json.loads(p.read_text())["run_id"] <= CUTOFF]
    runs = sorted([reader.read_run(p) for p in folders], key=lambda r: r["stat"]["run_id"])
    assert len(runs) == 48
    for run in runs:
        hold = run["profile"]["mode"] == "four-direction-hold"
        phase = "straight_hold" if hold else "sweep_down"
        records = [json.loads(line) for line in (run["folder"]/"control.jsonl").read_text().splitlines()]
        run["z"] = np.array([r["z_cmd_m"]*1000 for r in records if r["phase"] == phase])
        assert len(run["z"]) == len(run["g"]) == len(run["distance"])
    return runs


def split_inventory(runs):
    groups, old_x, speeds, sweeps = defaultdict(list), [], [], []
    for run in runs:
        s = run["stat"]
        if s["mode"] != "four-direction-hold":
            sweeps.append(run)
        elif s["speed_mm_s"] != 10:
            speeds.append(run)
        elif s["direction"] == "right" and s["command_z_mm"] == 30 and s["run_id"] < FIRST_NEW:
            old_x.append(run)
        else:
            groups[s["direction"], s["command_z_mm"]].append(run)
    assert set(groups) == {(d, z) for d in DIRECTIONS for z in HEIGHTS}
    assert all(len(pair) == 2 for pair in groups.values())
    assert (len(old_x), len(speeds), len(sweeps)) == (2, 16, 6)
    assert len({r["stat"]["run_id"] for pair in groups.values() for r in pair}) == 24
    return groups, old_x, speeds, sweeps


def mask_for(run, window):
    return (run["distance"] >= window[0]) & (run["distance"] <= window[1])


def run_median(run, window):
    selected = run["g"][mask_for(run, window)]
    assert len(selected) > 0
    return float(np.median(selected))


def fit_direction(runs, window):
    by_depth = defaultdict(list)
    for run in runs:
        by_depth[40-run["stat"]["command_z_mm"]].append(run_median(run, window))
    depths = sorted(by_depth)
    return Curve(depths, [float(np.mean(by_depth[d])) for d in depths])


def fit_models(x, target):
    affine, k, b = affine_curve(x, target)
    return dict(M0=x, M1=affine, M2=target), dict(gain=k, offset_uT=b)


def measurements(run, window, sweep=False):
    selected = mask_for(run, window)
    if sweep:
        selected &= (run["z"] >= 27) & (run["z"] <= 35)
        # Keep actual commanded depth per control-linked sample on a moving Z path.
        # All samples in a run together receive one stroke's weight in metrics.
        return [dict(grain="frame", distance_mm=float(run["distance"][i]),
                     measured_g_uT=float(run["g"][i]), command_z_mm=float(run["z"][i]))
                for i in np.flatnonzero(selected)]
    items = [dict(grain="median", distance_mm=None, measured_g_uT=run_median(run, window),
                  command_z_mm=run["stat"]["command_z_mm"])]
    for lo in np.arange(window[0], window[1], 5):
        mask = (run["distance"] >= lo) & (run["distance"] < lo+5)
        assert mask.sum() >= 10
        items.append(dict(grain="bin", distance_mm=float(lo+2.5),
                          measured_g_uT=float(np.median(run["g"][mask])),
                          command_z_mm=run["stat"]["command_z_mm"]))
    return items


def predict(run, window, suite, fold, models, x, reference=None, sweep=False):
    s = run["stat"]
    items = measurements(run, window, sweep)
    refs = measurements(reference, window) if reference is not None else None
    rows = []
    for i, item in enumerate(items):
        depth = 40-item["command_z_mm"]
        for name, model in models.items():
            predicted_g = model.forward(depth)
            depth_est, status = model.inverse(item["measured_g_uT"])
            z_est = None if depth_est is None else 40-depth_est
            x_eq = None if depth_est is None else x.forward(depth_est)
            ref_value = None if refs is None else refs[i]["measured_g_uT"]
            rows.append(dict(suite=suite, window_mm=f"{window[0]}-{window[1]}", fold=fold,
                             model=name, run_id=s["run_id"], folder=s["folder"],
                             direction=s["direction"], speed_mm_s=s["speed_mm_s"],
                             source_stage=s["stage"], **item, predicted_g_uT=predicted_g,
                             forward_error_uT=None if predicted_g is None else predicted_g-item["measured_g_uT"],
                             inverse_status=status, estimated_z_mm=z_est,
                             z_error_mm=None if z_est is None else z_est-item["command_z_mm"],
                             raw_distance_outside_range_uT=max(model.values[0]-item["measured_g_uT"],
                                                               item["measured_g_uT"]-model.values[-1], 0.),
                             x_equivalent_uT=x_eq, heldout_x_reference_uT=ref_value,
                             x_equivalent_error_uT=None if x_eq is None or ref_value is None else x_eq-ref_value,
                             noise_depth_scale_at_command_mm=model.noise_depth_scale(depth),
                             noise_depth_scale_at_estimate_mm=None if depth_est is None else model.noise_depth_scale(depth_est)))
    return rows


def metric_rows(predictions):
    groups = defaultdict(list)
    for row in predictions:
        for direction, z in (("all", "all"), (row["direction"], "all"),
                             (row["direction"], row["command_z_mm"] if row["grain"] != "frame" else "path")):
            key = (row["suite"], row["window_mm"], row["grain"], row["model"], direction, z)
            groups[key].append(row)
    return [dict(suite=k[0], window_mm=k[1], grain=k[2], model=k[3], direction=k[4],
                 command_z_mm=k[5], **summarize(rows)) for k, rows in groups.items()]


def paired_comparisons(rows):
    by_point = defaultdict(dict)
    for r in rows:
        key = (r["suite"], r["window_mm"], r["grain"], r["run_id"], r["distance_mm"])
        by_point[key][r["model"]] = r
    pairs = defaultdict(lambda: ([], []))
    for point in by_point.values():
        for a, b in (("M0", "M2"), ("M1", "M2")):
            if point[a]["inverse_status"] == point[b]["inverse_status"] == "ok":
                r = point[a]
                for direction in ("all", r["direction"]):
                    key = (r["suite"], r["window_mm"], r["grain"], direction, a, b)
                    pairs[key][0].append(point[a])
                    pairs[key][1].append(point[b])
    return [dict(suite=k[0], window_mm=k[1], grain=k[2], direction=k[3],
                 model_a=k[4], model_b=k[5], common_predictions=len(a),
                 common_runs=len({r["run_id"] for r in a}),
                 rmse_a_mm=summarize(a)["z_rmse_mm_valid_only"],
                 rmse_b_mm=summarize(b)["z_rmse_mm_valid_only"])
            for k, (a, b) in pairs.items()]


def benchmark(runs):
    groups, old_x, speeds, sweeps = split_inventory(runs)
    predictions, assignments, fits, candidates = [], [], [], {}
    for window in WINDOWS:
        for fold in (0, 1):
            train = [pair[fold] for pair in groups.values()]
            test = [pair[1-fold] for pair in groups.values()]
            train_ids = [r["stat"]["run_id"] for r in train]
            test_ids = [r["stat"]["run_id"] for r in test]
            ensure_disjoint(train_ids, test_ids)
            assert len(train_ids) == len(test_ids) == 12
            if window == WINDOWS[0]:
                assignments += [dict(suite="T1_repeat_holdout", fold=fold+1,
                                     role=role, run_id=r["stat"]["run_id"],
                                     direction=r["stat"]["direction"],
                                     command_z_mm=r["stat"]["command_z_mm"],
                                     source_stage=r["stat"]["stage"])
                                for role, subset in (("train", train), ("test", test)) for r in subset]
            curves = {d: fit_direction([groups[d, z][fold] for z in HEIGHTS], window) for d in DIRECTIONS}
            x = curves["right"]
            for d in DIRECTIONS:
                models, affine = fit_models(x, curves[d])
                fits.append(dict(suite="T1_repeat_holdout", window_mm=f"{window[0]}-{window[1]}",
                                 fold=fold+1, direction=d, train_run_ids=train_ids,
                                 test_run_ids=[groups[d, z][1-fold]["stat"]["run_id"] for z in HEIGHTS],
                                 curves={name: model.to_dict() for name, model in models.items()}, affine=affine))
                for z in HEIGHTS:
                    predictions += predict(groups[d, z][1-fold], window, "T1_repeat_holdout", fold+1,
                                           models, x, reference=groups["right", z][1-fold])
                endpoints = [groups[d, z][fold] for z in (35, 27)]
                endpoint_curve = fit_direction(endpoints, window)
                ref_x = fit_direction([groups["right", z][fold] for z in (35, 27)], window) if d == "right" else x
                models_mid, affine_mid = fit_models(ref_x, endpoint_curve)
                mid = groups[d, 30][1-fold]
                used = endpoints + ([groups["right", z][fold] for z in HEIGHTS] if d != "right" else [])
                ids = sorted({r["stat"]["run_id"] for r in used})
                ensure_disjoint(ids, [mid["stat"]["run_id"]])
                assert not any(r["stat"]["direction"] == d and r["stat"]["command_z_mm"] == 30 for r in used)
                fits.append(dict(suite="T2_middle_height_holdout", window_mm=f"{window[0]}-{window[1]}",
                                 fold=fold+1, direction=d, train_run_ids=ids,
                                 test_run_ids=[mid["stat"]["run_id"]],
                                 curves={name: model.to_dict() for name, model in models_mid.items()}, affine=affine_mid))
                predictions += predict(mid, window, "T2_middle_height_holdout", fold+1,
                                       models_mid, ref_x, reference=groups["right", 30][1-fold])
        full = {d: fit_direction([r for z in HEIGHTS for r in groups[d, z]], window) for d in DIRECTIONS}
        core_ids = sorted(r["stat"]["run_id"] for pair in groups.values() for r in pair)
        if window == WINDOWS[0]:
            candidates = dict(status="offline_candidate_not_installed", approved_for_hardware=False,
                              scope=dict(directions=list(DIRECTIONS), speed_mm_s=10, writing_tilt_deg=15,
                                         command_z_mm=[27, 35], travel_mm=150, window_mm=list(window)),
                              signal="control.jsonl:a_control_uT = norm of EMA baseline-subtracted Bxy, alpha 0.3",
                              depth="nominal command depth in mm = 40 - Zcmd; not force or bristle indentation",
                              noise_scale_uT=NOISE, noise_is_not_estimated_sd=True,
                              ignore_water=True, mixed_epoch=True, train_run_ids=core_ids,
                              source_runs={d: [dict(run_id=r["stat"]["run_id"], command_z_mm=z,
                                                    source_stage=r["stat"]["stage"],
                                                    median_uT=run_median(r, window))
                                               for z in HEIGHTS for r in groups[d, z]] for d in DIRECTIONS},
                              direction_curves={d: curve.to_dict() for d, curve in full.items()},
                              inference="strict inverse within response endpoints; no clipping/extrapolation; steady phase only")
        for d in DIRECTIONS:
            models, affine = fit_models(full["right"], full[d])
            migrations = [(r, "T3_old_X30") for r in old_x if r["stat"]["direction"] == d]
            migrations += [(r, f'T3_speed_{r["stat"]["speed_mm_s"]:g}') for r in speeds if r["stat"]["direction"] == d]
            migrations += [(r, f'T3_sweep_{r["stat"]["speed_mm_s"]:g}') for r in sweeps if r["stat"]["direction"] == d]
            for run, suite in migrations:
                ensure_disjoint(core_ids, [run["stat"]["run_id"]])
                predictions += predict(run, window, suite, 0, models, full["right"],
                                       sweep=run["stat"]["mode"] != "four-direction-hold")
            fits.append(dict(suite="T3_frozen_full_core", window_mm=f"{window[0]}-{window[1]}",
                             fold=0, direction=d, train_run_ids=core_ids,
                             test_run_ids=[r["stat"]["run_id"] for r, _ in migrations],
                             curves={name: model.to_dict() for name, model in models.items()}, affine=affine))
    assert len(assignments) == 48
    return predictions, assignments, fits, candidates


def fmt(value, digits=2):
    return "—" if value is None else f"{value:.{digits}f}"


def html_table(headers, rows):
    esc = lambda v: html.escape(str(v))
    return '<table><thead><tr>'+''.join(f'<th>{esc(h)}</th>' for h in headers)+'</tr></thead><tbody>'+''.join(
        '<tr>'+''.join(f'<td>{esc(v)}</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table>'


def draw_plots(predictions, metrics, fits):
    plt.rcParams.update({"font.family": "Noto Sans CJK SC", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False})
    colors = dict(M0="#8591a2", M1="#db8630", M2="#238774")
    main = [r for r in metrics if r["suite"] == "T1_repeat_holdout" and r["window_mm"] == "30-120"
            and r["grain"] == "median" and r["command_z_mm"] == "all" and r["direction"] != "all"]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8), layout="constrained")
    for j, model in enumerate(MODEL_NAMES):
        selected = [next(r for r in main if r["direction"] == d and r["model"] == model) for d in DIRECTIONS]
        xs = np.arange(4)+(j-1)*.24
        axes[0].bar(xs, [r["forward_rmse_uT"] for r in selected], width=.23, color=colors[model], label=MODEL_NAMES[model])
        axes[1].bar(xs, [r["z_rmse_mm_valid_only"] or 0 for r in selected], width=.23, color=colors[model], label=MODEL_NAMES[model])
        axes[2].bar(xs, [r["run_balanced_coverage"]*100 for r in selected], width=.23, color=colors[model], label=MODEL_NAMES[model])
        for xloc, r in zip(xs, selected):
            if r["z_rmse_mm_valid_only"] is None:
                axes[1].text(xloc, .05, "无有效估计", rotation=90, ha="center", fontsize=8)
    axes[0].set(title="全部独立测试笔：磁响应预测误差", ylabel="原始磁响应均方根误差（µT）")
    axes[1].set(title="仅成功反查记录：Z 估计误差", ylabel="命令 Z 均方根误差（mm）")
    axes[2].set(title="反查覆盖率：保留越界记录", ylabel="可反查笔数占全部测试笔的比例（%）", ylim=(0, 105))
    axes[0].axhline(NOISE, ls=":", color="grey", label="用户给定的 20 µT 比较量级")
    axes[1].axhline(1, ls=":", color="grey")
    for ax in axes:
        ax.set_xticks(np.arange(4), [NAMES[d] for d in DIRECTIONS])
        ax.grid(axis="y", alpha=.2)
    axes[0].legend(fontsize=9)
    fig.savefig(OUT/"01_models_and_coverage.png", dpi=155)
    plt.close(fig)
    fig, axes = plt.subplots(2, 2, figsize=(12, 8.5), sharex=True, sharey=True, layout="constrained")
    for ax, d in zip(axes.flat, DIRECTIONS):
        for model in MODEL_NAMES:
            rows = [r for r in predictions if r["suite"] == "T1_repeat_holdout" and r["window_mm"] == "30-120"
                    and r["grain"] == "median" and r["direction"] == d and r["model"] == model]
            valid = [r for r in rows if r["inverse_status"] == "ok"]
            ax.scatter([r["command_z_mm"]+.12*(list(MODEL_NAMES).index(model)-1) for r in valid],
                       [r["estimated_z_mm"] for r in valid], color=colors[model], marker={"M0":"s", "M1":"^", "M2":"o"}[model],
                       label=f'{MODEL_NAMES[model]}\n可反查：{len(valid)}/{len(rows)} 笔', alpha=.85)
        ax.plot([27, 35], [27, 35], "k--", lw=1)
        ax.set(title=f'{NAMES[d]} 方向', xlabel="独立测试笔的命令 Z（mm）", ylabel="磁反馈反查的 Z（mm）", xlim=(26.5, 35.5), ylim=(26.5, 35.5))
        ax.grid(alpha=.2)
        ax.legend(fontsize=8)
    fig.suptitle("独立笔次的 Z 反查：未显示的点为幅值越界记录", fontsize=13)
    fig.savefig(OUT/"02_heldout_z.png", dpi=155)
    plt.close(fig)
    fig, axes = plt.subplots(4, 3, figsize=(15, 12), layout="constrained", sharex=True)
    for i, d in enumerate(DIRECTIONS):
        for j, z in enumerate(HEIGHTS):
            ax = axes[i, j]
            rows = [r for r in predictions if r["suite"] == "T1_repeat_holdout" and r["window_mm"] == "30-120"
                    and r["grain"] == "bin" and r["model"] == "M2" and r["direction"] == d and r["command_z_mm"] == z]
            for fold, color in ((1, "#2474b5"), (2, "#d47c2c")):
                points = sorted([r for r in rows if r["fold"] == fold], key=lambda r:r["distance_mm"])
                ax.plot([r["distance_mm"] for r in points], [r["estimated_z_mm"] if r["estimated_z_mm"] is not None else np.nan for r in points],
                        "o-", markersize=2, color=color,
                        label=f'第 {fold} 折：{sum(r["inverse_status"] == "ok" for r in points)}/{len(points)} 个分箱有效')
            ax.axhline(z, color="grey", ls="--")
            ax.set(title=f'{NAMES[d]} 方向，命令 Z{z}', ylim=(26, 36), xlim=(30, 120))
            ax.grid(alpha=.2)
            ax.legend(fontsize=7)
            if j == 0:
                ax.set_ylabel("反查 Z（mm）")
            if i == 3:
                ax.set_xlabel("沿程距离（mm）")
    fig.suptitle("四方向分段曲线的笔内回放：每 5 mm 分箱，笔次等权评分", fontsize=13)
    fig.savefig(OUT/"03_m2_bin_replay.png", dpi=145)
    plt.close(fig)


def make_report(metrics, comparisons, candidates, quality):
    primary = [r for r in metrics if r["window_mm"] == "30-120" and r["suite"] == "T1_repeat_holdout"
               and r["grain"] == "median" and r["command_z_mm"] == "all"]
    page = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>方向校准离线测试</title><style>body{max-width:1250px;margin:auto;padding:28px;font:16px/1.7 sans-serif;color:#20354a}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:8px;border-bottom:1px solid #ddd;text-align:left}img{width:100%}a{color:#2474b5}.note{background:#f2f6fa;padding:15px}</style><h1>现有数据的方向校准离线测试</h1>'
    page += '<p>48 笔原始记录：核心 24 笔、旧 X/Z30 2 笔、7/15 mm/s 16 笔、半程下压 6 笔。仅离线计算，未连接机器人，未修改控制配置。主窗口 30–120 mm；另以 50–100 mm 检查起笔排除敏感性。</p>'
    page += '<p>指标说明：RMSE 为均方根误差，MAE 为平均绝对误差；TCP 为工具中心点。Z 是机器人命令高度，单位为毫米。</p>'
    page += '<p class="note">M0 所有方向使用当前新 X 曲线；M1 增益＋偏置由训练折三高度等权拟合；M2 各方向独立三节点分段曲线。每条件第一笔训练、第二笔测试，再交换。24 笔各作为测试一次。训练笔次与测试笔次严格分开。原始幅值预测评分包括全部测试笔；Z 反查 RMSE 仅对支持范围内记录计算，因此必须同时看覆盖率。越界不裁切、不外推。</p>'
    overall = {r["model"]:r for r in primary if r["direction"] == "all"}
    m0, m1, m2 = (overall[name] for name in MODEL_NAMES)
    improvement = 100*(1-m2["forward_rmse_uT"]/m0["forward_rmse_uT"])
    page += f'<h2>结果判断</h2><p>方向修正有明显作用：全部测试笔的原始响应 RMSE 从 {fmt(m0["forward_rmse_uT"])} 降到 {fmt(m2["forward_rmse_uT"])} µT，下降约 {improvement:.1f}%。严格支持范围内 M2 的 Z RMSE 为 {fmt(m2["z_rmse_mm_valid_only"])} mm，可反查 {m2["valid_runs"]}/{m2["total_runs"]} 笔。其余笔次保留为越界，不能把成功子集的低误差当作全范围通过。</p>'
    page += '<p>M2 的 +Y 换算优于 M1；−X 的两种方向模型在共同可反查笔上几乎相同；−Y 的 M1 在本批 Z 反查中更好。M2 的全体 Z RMSE 并未显著优于 M1。可把方向模型作为当前装配下的磁目标换算候选，尚不能认定为稳定的全方向 Z 反馈。</p>'
    page += '<p>逐笔中位数不能代替笔内回放：−X/Z30 两笔的中段反查 Z 均从约 31 mm 向约 28 mm 变化，而命令 Z 保持 30 mm。5 mm 分箱测试中，M2 的 +X/−X 误差更大。该发现说明仅用方向和磁幅值反查 Z，仍存在未建模的沿程或接触状态变化；本测试不能识别其物理原因。</p>'
    page += '<h2>跨笔测试：原始响应与命令 Z</h2>'
    page += html_table(["方向", "方法", "原始响应 RMSE/µT（全部）", "Z MAE/mm（有效）", "Z RMSE/mm（有效）", "最大 Z 误差/mm（有效）", "可反查笔数", "全部测试中 ≤1mm"],
                       [[NAMES.get(r["direction"], "总体"), MODEL_NAMES[r["model"]], fmt(r["forward_rmse_uT"]), fmt(r["z_mae_mm_valid_only"]),
                         fmt(r["z_rmse_mm_valid_only"]), fmt(r["z_max_abs_mm_valid_only"]), f'{r["valid_runs"]}/{r["total_runs"]}',
                         f'{r["predictions_within_1mm"]}/{r["total_predictions"]}'] for r in primary])
    page += '<h2>相同可反查记录上的配对比较</h2><p>只比较两算法均支持的同一笔，不能用不同成功子集的 RMSE 判断优劣。此子集也不替代总体覆盖率。</p>'
    paired = [r for r in comparisons if r["suite"] == "T1_repeat_holdout" and r["window_mm"] == "30-120" and r["grain"] == "median"]
    page += html_table(["方向", "比较", "共同笔数", "方法 A 的 Z RMSE/mm", "M2 的 Z RMSE/mm"],
                       [[NAMES.get(r["direction"], "总体"), f'{MODEL_NAMES[r["model_a"]]} 与 M2 分段曲线', r["common_runs"], fmt(r["rmse_a_mm"]), fmt(r["rmse_b_mm"])] for r in paired])
    for filename, label in (("01_models_and_coverage.png", "三种方法的误差与覆盖率"), ("02_heldout_z.png", "逐笔反查 Z"), ("03_m2_bin_replay.png", "中段分箱回放")):
        page += f'<h2>{label}</h2><img src="{filename}">'
    page += '<h2>移除目标方向 Z30 节点：未拟合中间高度</h2><p>只用本轮 Z35/Z27 预测 Z30 的独立笔。+Y/−X/−Y 的 X 参考仍可使用独立新 X/Z30；X 自身则完整留出 Z30。其他方向 Z30 是前一批记录，这项测试同时包含高度插值与时间变化。</p>'
    middle = [r for r in metrics if r["suite"] == "T2_middle_height_holdout" and r["window_mm"] == "30-120" and r["grain"] == "median" and r["command_z_mm"] == "all"]
    page += html_table(["方向", "方法", "响应 RMSE/µT", "Z RMSE/mm（有效）", "可反查笔数"],
                       [[NAMES.get(r["direction"], "总体"), MODEL_NAMES[r["model"]], fmt(r["forward_rmse_uT"]), fmt(r["z_rmse_mm_valid_only"]), f'{r["valid_runs"]}/{r["total_runs"]}'] for r in middle])
    page += '<h2>冻结全量核心模型后的迁移测试</h2><p>速度只在 Z30 检查；速度记录属于更早批次，因此不能把迁移差异单独归因于速度。扫描仅评分沿程主窗口内、Z27–35 的下降段；无校准范围覆盖的轨迹不参与范围内评分。</p>'
    transfer = [r for r in metrics if r["suite"].startswith("T3") and r["window_mm"] == "30-120"
                and r["grain"] in ("median", "frame") and r["command_z_mm"] == "all"]
    page += html_table(["类别", "方向", "方法", "响应 RMSE/µT", "Z RMSE/mm（有效）", "可反查覆盖率", "有效/总点数"],
                       [[SUITE_NAMES[r["suite"]], NAMES.get(r["direction"], "总体"), MODEL_NAMES[r["model"]], fmt(r["forward_rmse_uT"]), fmt(r["z_rmse_mm_valid_only"]),
                         f'{r["run_balanced_coverage"]*100:.1f}%', f'{r["valid_predictions"]}/{r["total_predictions"]}'] for r in transfer])
    page += '<h2>窗口敏感性：相同算法和划分</h2>'
    sensitivity = [r for r in metrics if r["suite"] == "T1_repeat_holdout" and r["grain"] == "median"
                   and r["model"] == "M2" and r["command_z_mm"] == "all"]
    page += html_table(["窗口/mm", "方向", "响应 RMSE/µT", "Z RMSE/mm（有效）", "可反查笔数"],
                       [[r["window_mm"], NAMES.get(r["direction"], "总体"), fmt(r["forward_rmse_uT"]), fmt(r["z_rmse_mm_valid_only"]),
                         f'{r["valid_runs"]}/{r["total_runs"]}'] for r in sensitivity])
    page += '<h2>全核心数据拟合的候选节点（不作为测试成绩）</h2>'
    page += html_table(["方向", "d5/Z35 µT", "d10/Z30 µT", "d13/Z27 µT", "20µT 对应浅段/mm", "20µT 对应深段/mm"],
                       [[NAMES[d]]+[fmt(v) for v in c["response_nodes_uT"]]+[fmt(v) for v in c["user_20uT_depth_scale_mm"]]
                        for d,c in candidates["direction_curves"].items()])
    page += '<h2>解释与边界</h2><p>方向之间原始 µT 不同本身是正常现象。评价的是同方向、同高度跨笔预测，以及校准后估计 Z 是否正确。20 µT 是用户给定的比较量级，不是实测标准差。Z 是命令坐标，不是力或真实笔毫压入量。反查的低误差若伴随大量越界，不能称为稳定校准。</p><p>数据曾用于前期分析，因此这是回顾性验证。每条件只有两笔；不能据此给出可靠的总体置信区间。核心三高度矩阵中，非 X 的 Z30 来自此前批次，属于混合采集批次。只验证四个轴向方向、10 mm/s 稳态，未验证任意角度、转弯、闭环改变 Z 后的动态或笔迹改善。</p>'
    page += '<p>原始数据质量：传感器无效帧 '+str(quality["sensor_invalid"])+', 实际 TCP 无效点 '+str(quality["tcp_invalid"])+', 定高段最大实际 TCP Z 偏差 '+fmt(quality["max_hold_tcp_z_deviation_mm"],3)+' mm。实际 TCP 约 10 Hz，主评分仍使用同步命令 Z。</p>'
    page += '<p>'+" · ".join(f'<a href="{filename}">{label}</a>' for filename,label in (("metrics.json", "指标与方法"), ("metrics.csv", "完整指标表"), ("heldout_predictions.csv", "全部逐笔及分箱预测"), ("migration_predictions.csv", "速度与扫描回放"), ("fold_assignments.csv", "训练测试分配"), ("directional_calibration.json", "候选曲线"), ("analyze.py", "可复现分析程序")))+'</p></html>'
    (OUT/"index.html").write_text(page, encoding="utf-8")


def main():
    runs = read_runs()
    predictions, assignments, fits, candidates = benchmark(runs)
    metrics = metric_rows(predictions)
    comparisons = paired_comparisons(predictions)
    quality = dict(sensor_frames=sum(r["stat"]["sensor_frames"] for r in runs),
                   sensor_invalid=sum(r["stat"]["sensor_invalid"] for r in runs),
                   tcp_invalid=sum(r["stat"]["tcp_invalid"] for r in runs),
                   max_hold_tcp_z_deviation_mm=max(r["stat"]["tcp_z_path_max_abs_mm"] for r in runs if r["bins"] is not None))
    hashes = {str(p.relative_to(BASE)):hashlib.sha256(p.read_bytes()).hexdigest()
              for r in runs for p in sorted(r["folder"].iterdir()) if p.is_file()}
    summary = dict(status="retrospective_offline_benchmark_complete", approved_for_hardware=False,
                   cutoff_run_id=CUTOFF, inventory=dict(core=24, old_x30=2, speed=16, sweep=6),
                   primary_window_mm=[30,120], sensitivity_window_mm=[50,100], user_noise_scale_uT=NOISE,
                   grain_policy="per-stroke median; 5 mm within-stroke bins; sweep frames. Equal weight per stroke.",
                   inverse_policy="strict node-response bounds, no clipping/extrapolation; successful-only Z errors plus coverage",
                   quality=quality, metrics=metrics, paired_comparisons=comparisons, folds_and_models=fits,
                   input_sha256=hashes, reader_sha256=hashlib.sha256(READER_PATH.read_bytes()).hexdigest(),
                   generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    save_csv("fold_assignments.csv", assignments)
    save_csv("heldout_predictions.csv", [r for r in predictions if r["suite"].startswith(("T1", "T2"))])
    save_csv("migration_predictions.csv", [r for r in predictions if r["suite"].startswith("T3")])
    save_csv("metrics.csv", metrics)
    save_csv("paired_comparisons.csv", comparisons)
    for name, value in (("metrics.json", summary), ("directional_calibration.json", candidates)):
        (OUT/name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    draw_plots(predictions, metrics, fits)
    make_report(metrics, comparisons, candidates, quality)
    printed = [r for r in metrics if r["window_mm"] == "30-120" and r["grain"] == "median"
               and r["command_z_mm"] == "all" and r["suite"] in ("T1_repeat_holdout", "T2_middle_height_holdout")]
    print(json.dumps(dict(output=str(OUT), quality=quality, results=printed), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
