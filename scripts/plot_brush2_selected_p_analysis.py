#!/usr/bin/env python3
"""Build selected brush2 P-gain and correction-limit analysis artifacts.

Recorded magnetic traces are observations. One-factor replays reuse one recorded
trace to compare controller commands and do not predict magnetic outcomes.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from brushbot.experiments.strokeplan_feedback import StrokePlanPFeedback


ROOT = Path(__file__).resolve().parents[1]
DAY = ROOT / "runs/brush2/archive/2026-09-24"
GAIN_OUT = DAY / "02_P反馈与增益扫描/analysis/P增益扫描"
LIMIT_OUT = DAY / "03_P2修正上限/analysis/修正上限精选"
GAIN_IDS = ("36c368", "d0a5c2", "0f2f88", "63dee4", "f4a10d",
            "c61f9e", "9527cc", "bb27fb")
LIMIT_IDS = ("bb27fb", "a8a59a", "68defd", "58bce8")
EXCLUDED_LIMIT_IDS = {
    "10f17a": "operator-flagged high-response episode; raw run retired on 2026-09-25, compact summary retained",
    "142be8": "repeat of the high-response episode; no actual TCP stream",
    "69395a": "large mid-path excess response; no actual TCP stream",
}
PROFILE_KEYS = ("kp", "ki", "max_correction_mm", "max_correction_speed_mm_s",
                "max_correction_accel_mm_s2", "taper_ticks")
SNAPSHOTS = ("strokeplan.npz", "feedforward.json", "settings.json",
             "resolved.json", "compiled_plan.npz", "timeline.npz", "setup.json",
             "calibration.json")
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9,
                     "axes.spines.top": False, "axes.spines.right": False})


def load(short_id: str) -> dict:
    matches = [path.parent for path in DAY.glob("*/raw/*/manifest.json")
               if json.loads(path.read_text())["run_id"].endswith("-" + short_id)]
    if len(matches) != 1:
        raise ValueError(f"expected one run for {short_id}, got {len(matches)}")
    folder = matches[0]
    manifest = json.loads((folder / "manifest.json").read_text())
    resolved = json.loads((folder / "resolved.json").read_text())
    if manifest.get("status") != "completed" or manifest.get("execution_environment") != "hardware":
        raise ValueError(f"incomplete or non-hardware run: {short_id}")
    for name in SNAPSHOTS:
        actual = hashlib.sha256((folder / name).read_bytes()).hexdigest()
        if actual != manifest["sha256"][name]:
            raise ValueError(f"snapshot hash mismatch: {short_id}/{name}")
    control = resolved["control"]
    if not control["enabled"] or control["mode"] != "p" or control["ki"] != 0:
        raise ValueError(f"not a P-only run: {short_id}")
    with (folder / "control.jsonl").open() as stream:
        all_rows = [json.loads(line) for line in stream]
    measure = [row for row in all_rows if row["phase"] == "measure_00"]
    if len(measure) != 1011:
        raise ValueError(f"incomplete measure phase: {short_id}")
    x = 1000 * (np.array([r["x_cmd_m"] for r in measure]) - measure[0]["x_cmd_m"])
    target = np.array([r["a_ref_uT"] for r in measure])
    observed = np.array([r["a_control_uT"] for r in measure])
    correction = 1000 * np.array([r["depth_fb_m"] for r in measure])
    if (not np.isfinite(np.r_[x, target, observed, correction]).all()
            or abs(x[-1] - 200) > .1 or np.any(np.diff(x) < -1e-8)):
        raise ValueError(f"invalid trajectory or signal: {short_id}")
    error = observed - target
    mid = (x >= 100) & (x < 150)
    metrics = {
        "run_id": short_id, "kp": control["kp"],
        "amplitude_mm": control["max_correction_mm"],
        "speed_mm_s": control["max_correction_speed_mm_s"],
        "acceleration_mm_s2": control["max_correction_accel_mm_s2"],
        "measure_ticks": len(measure),
        "full_mae_uT": float(np.mean(np.abs(error))),
        "full_signed_mean_uT": float(np.mean(error)),
        "mid_100_150_mae_uT": float(np.mean(np.abs(error[mid]))),
        "mid_100_150_signed_mean_uT": float(np.mean(error[mid])),
        "first_measured_uT": float(observed[0]),
        "first_target_uT": float(target[0]),
        "mid_100_150_mean_correction_mm": float(np.mean(correction[mid])),
        "mid_100_150_negative_cap_ticks": int(np.count_nonzero(
            np.isclose(correction[mid], -control["max_correction_mm"], atol=1e-8))),
        "actual_tcp_valid_rows": 0,
    }
    meta_path = folder / "actual_tcp_meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        metrics["actual_tcp_valid_rows"] = meta["valid_samples"]
        if meta["invalid_samples"] or meta["worker_error"]:
            raise ValueError(f"invalid actual TCP stream: {short_id}")
    return {"id": short_id, "display": folder.name[:8],
            "folder": folder, "manifest": manifest,
            "resolved": resolved, "all_rows": all_rows, "measure": measure,
            "x": x, "target": target, "observed": observed,
            "correction": correction, "metrics": metrics}


def write_csv(path: Path, records: list[dict]) -> None:
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def frame(ax, *, correction=False):
    ax.axvspan(100, 150, color="#eed8ac", alpha=.35, zorder=0)
    ax.set_xlim(0, 200)
    ax.grid(alpha=.18)
    if correction:
        ax.axhline(0, color=".4", lw=.7)


def small_multiples(runs: list[dict], output: Path, *, mode: str, title: str):
    fig, axes = plt.subplots(2, 4, figsize=(16, 7.5), sharex=True, sharey=True,
                             layout="constrained")
    for ax, run in zip(axes.flat, runs):
        x = run["x"]
        if mode == "magnetic":
            ax.plot(x, run["target"], color=".28", ls="--", lw=1.1)
            ax.plot(x, run["observed"], color="#2377ad", lw=1.35)
            ax.set_ylim(0, 260)
            subtitle = f"MAE {run['metrics']['full_mae_uT']:.1f} uT"
        elif mode == "error":
            ax.plot(x, run["observed"] - run["target"], color="#7655a8", lw=1.3)
            ax.set_ylim(-140, 140)
            subtitle = f"MAE {run['metrics']['full_mae_uT']:.1f} uT"
        else:
            ax.plot(x, run["correction"], color="#b65a34", lw=1.3)
            ax.set_ylim(-.45, .45)
            subtitle = (f"limit +/-{run['metrics']['amplitude_mm']:g} mm")
        frame(ax, correction=mode != "magnetic")
        ax.set_title(f"P={run['metrics']['kp']:g}  {run['display']} | {subtitle}", fontsize=10)
    for ax in axes.flat[len(runs):]:
        ax.axis("off")
    for ax in axes[-1]:
        ax.set_xlabel("Command path X (mm)")
    for ax in axes[:, 0]:
        ax.set_ylabel("Magnetic field (uT)" if mode == "magnetic"
                      else "Measured - target (uT)" if mode == "error"
                      else "Command correction (mm, +down)")
    fig.suptitle(title, fontsize=15)
    fig.savefig(output, dpi=170)
    plt.close(fig)


def limit_multiples(runs: list[dict], output: Path, *, mode: str):
    fig, axes = plt.subplots(2, 2, figsize=(12.5, 8), sharex=True, sharey=True,
                             layout="constrained")
    for ax, run in zip(axes.flat, runs):
        m = run["metrics"]
        label = f"{m['amplitude_mm']:g} mm / {m['speed_mm_s']:g} mm/s / {m['acceleration_mm_s2']:g} mm/s2"
        if mode == "magnetic":
            ax.plot(run["x"], run["target"], color=".28", ls="--", lw=1.2,
                    label="target")
            ax.plot(run["x"], run["observed"], color="#2377ad", lw=1.4,
                    label="observed")
            ax.set_ylim(0, 270)
        else:
            ax.plot(run["x"], run["correction"], color="#b65a34", lw=1.35)
            ax.set_ylim(-.45, .45)
        frame(ax, correction=mode != "magnetic")
        ax.set_title(f"{run['display']} | {label} | MAE {m['full_mae_uT']:.1f} uT",
                     fontsize=10)
        ax.set_xlabel("Command path X (mm)")
        ax.set_ylabel("Magnetic field (uT)" if mode == "magnetic"
                      else "Command correction (mm, +down)")
    if mode == "magnetic":
        axes[0, 0].legend(fontsize=8)
    fig.suptitle("Selected measured runs, P=2 | " + mode, fontsize=15)
    fig.savefig(output, dpi=170)
    plt.close(fig)


def metrics_plot(runs: list[dict], output: Path, *, by_gain: bool):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.3), sharey=True, layout="constrained")
    if by_gain:
        categories = ["0.05", "0.1", "0.2", "0.3", "0.4", "1", "2"]
        keys = [f"{r['metrics']['kp']:g}" for r in runs]
        title = "P gain sweep | fixed limits 0.2 / 2 / 40"
    else:
        categories = ["0.2/2/40", "0.25/2/50", "0.4/5/70"]
        keys = [f"{r['metrics']['amplitude_mm']:g}/{r['metrics']['speed_mm_s']:g}/{r['metrics']['acceleration_mm_s2']:g}" for r in runs]
        title = "Selected limit profiles | P=2; repeated 0.4/5/70 shown separately"
    for ax, key, ylabel in zip(axes,
                               ("full_mae_uT", "mid_100_150_mae_uT"),
                               ("Full path MAE (uT)", "X=100-150 mm MAE (uT)")):
        for i, run in enumerate(runs):
            idx = categories.index(keys[i])
            repeat = sum(keys[j] == keys[i] for j in range(i))
            xx = idx + (-.08 if repeat == 0 and keys.count(keys[i]) > 1 else
                        .08 if repeat == 1 else 0)
            ax.scatter(xx, run["metrics"][key], s=70, color="#2377ad", zorder=3)
            offset = ((-5, 10) if repeat == 0 else (5, -15)) if keys.count(keys[i]) > 1 else (0, 7)
            align = ("right" if repeat == 0 else "left") if keys.count(keys[i]) > 1 else "center"
            ax.annotate(run["display"], (xx, run["metrics"][key]), xytext=offset,
                        textcoords="offset points", ha=align, fontsize=7.5)
        ax.set_xticks(range(len(categories)), categories)
        ax.set_xlim(-.5, len(categories)-.5)
        ax.set_ylabel(ylabel)
        ax.grid(axis="y", alpha=.2)
    fig.suptitle(title, fontsize=13)
    fig.savefig(output, dpi=170)
    plt.close(fig)


def actual_tcp_summary(run: dict) -> dict:
    result = {"run_id": run["id"], "valid_tcp_samples": 0,
              "measure_tcp_samples": 0, "mid_tcp_samples": 0,
              "mid_actual_minus_cmd_z_mean_mm": None,
              "mid_actual_z_mean_mm": None, "mid_paired_cmd_z_mean_mm": None}
    path = run["folder"] / "actual_tcp.csv"
    if not path.exists():
        return result
    rows = run["all_rows"]
    times = [r["host_ns"] for r in rows]
    paired = []
    with path.open() as stream:
        for pose in csv.DictReader(stream):
            if pose["valid"] != "true":
                continue
            result["valid_tcp_samples"] += 1
            mid_ns = (int(pose["request_start_ns"]) + int(pose["request_end_ns"])) // 2
            index = bisect.bisect_right(times, mid_ns) - 1
            if index < 0 or rows[index]["phase"] != "measure_00":
                continue
            result["measure_tcp_samples"] += 1
            command = rows[index]
            path_mm = 1000 * (command["x_cmd_m"] - run["measure"][0]["x_cmd_m"])
            if 100 <= path_mm < 150:
                paired.append((float(pose["z_m"])*1000, command["z_cmd_m"]*1000))
    if paired:
        result["mid_tcp_samples"] = len(paired)
        result["mid_actual_minus_cmd_z_mean_mm"] = sum(a-c for a, c in paired)/len(paired)
        result["mid_actual_z_mean_mm"] = sum(a for a, _ in paired)/len(paired)
        result["mid_paired_cmd_z_mean_mm"] = sum(c for _, c in paired)/len(paired)
    return result


def replay(source: dict, overrides: dict) -> np.ndarray:
    folder = source["folder"]
    with np.load(folder / "timeline.npz", allow_pickle=False) as timeline:
        pose = timeline["pose_m_rad"]
        phase = timeline["phase"]
        depth = timeline["depth_ff_m"]
        target = timeline["g_ref_uT"]
    rows = source["all_rows"]
    if len(rows) != len(pose) or any(abs(rows[i]["t_s"]-i*.02) > 1e-8
                                      for i in range(len(rows))):
        raise ValueError("source observations are not one per timeline tick")
    control = source["resolved"]["control"]
    profile = {k: control[k] for k in PROFILE_KEYS}
    profile.update(overrides)
    feedback = StrokePlanPFeedback(json.loads((folder / "feedforward.json").read_text()),
                                   json.loads((folder / "settings.json").read_text()),
                                   .02, measure_ticks=len(source["measure"]), profile=profile)
    feedback.reset(pose[0])
    measure_tick = 0
    corrections = []
    for i, row in enumerate(rows):
        active = phase[i] == "measure_00"
        ref = float(target[i]) if active else None
        if active and (not math.isclose(row["a_ref_uT"], ref, abs_tol=1e-9)
                       or not math.isclose(row["depth_ff_m"], depth[i], abs_tol=1e-9)):
            raise ValueError(f"source target or feedforward mismatch at tick {i}")
        _, correction, _ = feedback.command(
            measure_tick if active else -1, pose[i], depth_ff_m=float(depth[i]),
            a_ref_uT=ref, a_control_uT=float(row["a_control_uT"]))
        if active:
            measure_tick += 1
            corrections.append(correction*1000)
    if len(corrections) != len(source["measure"]):
        raise ValueError("replay did not cover full measure phase")
    return np.asarray(corrections)


def build_replay(source: dict, folder: Path) -> list[dict]:
    baseline = replay(source, {})
    if not np.allclose(baseline, source["correction"], atol=1e-9, rtol=0):
        raise ValueError("baseline replay differs from recorded correction")
    cases = [
        ("amplitude_mm", "max_correction_mm", (.2, .25, .3, .4)),
        ("speed_mm_s", "max_correction_speed_mm_s", (2, 4, 5)),
        ("acceleration_mm_s2", "max_correction_accel_mm_s2", (40, 50, 60, 70)),
    ]
    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True, layout="constrained")
    metrics = []
    for ax, (label, key, values) in zip(axes, cases):
        for value in values:
            result = replay(source, {key: value})
            difference = result - baseline
            metrics.append({"source_run_id": source["id"], "varied_parameter": label,
                            "value": value, "baseline_value": source["resolved"]["control"][key],
                            "max_abs_command_difference_mm": float(np.max(np.abs(difference))),
                            "mean_abs_command_difference_mm": float(np.mean(np.abs(difference))),
                            "changed_measure_ticks": int(np.count_nonzero(np.abs(difference) > 1e-9))})
            ax.plot(source["x"], result, lw=1.4, label=f"{value:g}")
        frame(ax, correction=True)
        ax.set_ylabel("Command correction (mm)")
        ax.set_title(f"Vary only {label}; reference profile 0.4 / 5 / 70", loc="left")
        ax.legend(title=label, ncol=len(values), fontsize=8, title_fontsize=8,
                  frameon=False, loc="upper right")
    axes[-1].set_xlabel("Command path X (mm)")
    fig.suptitle(f"One-factor command replay | recorded {source['display']} magnetic signal held fixed",
                 fontsize=14)
    fig.savefig(folder / "one_factor_command_replay.png", dpi=170)
    plt.close(fig)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gain-output", type=Path, default=GAIN_OUT)
    parser.add_argument("--limit-output", type=Path, default=LIMIT_OUT)
    args = parser.parse_args()
    ids = dict.fromkeys((*GAIN_IDS, *LIMIT_IDS))
    all_runs = {short_id: load(short_id) for short_id in ids}
    reference = all_runs[GAIN_IDS[0]]
    for run in all_runs.values():
        for name in ("strokeplan.npz", "feedforward.json", "settings.json"):
            if run["manifest"]["sha256"][name] != reference["manifest"]["sha256"][name]:
                raise ValueError(f"different input snapshot: {run['id']} {name}")
        if not np.allclose(run["x"], reference["x"], atol=1e-8, rtol=0) or not np.allclose(
                run["target"], reference["target"], atol=1e-8, rtol=0):
            raise ValueError(f"different command path or target: {run['id']}")
    gain = [all_runs[key] for key in GAIN_IDS]
    limits = [all_runs[key] for key in LIMIT_IDS]
    for run in gain:
        m = run["metrics"]
        if (m["amplitude_mm"], m["speed_mm_s"], m["acceleration_mm_s2"]) != (.2, 2., 40.):
            raise ValueError(f"gain scan changed limits: {run['id']}")
    for run in limits:
        if run["metrics"]["kp"] != 2:
            raise ValueError(f"limit scan changed P: {run['id']}")
    expected_profiles = ((.2, 2., 40.), (.25, 2., 50.), (.4, 5., 70.), (.4, 5., 70.))
    for run, expected in zip(limits, expected_profiles):
        m = run["metrics"]
        if (m["amplitude_mm"], m["speed_mm_s"], m["acceleration_mm_s2"]) != expected:
            raise ValueError(f"unexpected limit profile: {run['id']}")
    gain_dir = args.gain_output
    limit_dir = args.limit_output
    gain_dir.mkdir(parents=True, exist_ok=True)
    limit_dir.mkdir(parents=True, exist_ok=True)
    write_csv(gain_dir / "metrics.csv", [run["metrics"] for run in gain])
    write_csv(limit_dir / "metrics.csv", [run["metrics"] for run in limits])
    write_csv(limit_dir / "actual_tcp_check.csv", [actual_tcp_summary(run) for run in limits])
    small_multiples(gain, gain_dir / "magnetic_tracking_by_p.png", mode="magnetic",
                    title="P gain sweep | same inputs and limits 0.2 / 2 / 40")
    small_multiples(gain, gain_dir / "signed_error_by_p.png", mode="error",
                    title="Signed magnetic tracking error | P gain sweep")
    small_multiples(gain, gain_dir / "feedback_by_p.png", mode="correction",
                    title="Logged feedback correction | P gain sweep")
    metrics_plot(gain, gain_dir / "p_metrics.png", by_gain=True)
    limit_multiples(limits, limit_dir / "magnetic_tracking_by_limits.png", mode="magnetic")
    limit_multiples(limits, limit_dir / "feedback_by_limits.png", mode="correction")
    metrics_plot(limits, limit_dir / "limits_metrics.png", by_gain=False)
    replay_metrics = build_replay(all_runs["68defd"], limit_dir)
    write_csv(limit_dir / "replay_metrics.csv", replay_metrics)
    common = {name: reference["manifest"]["sha256"][name]
              for name in ("strokeplan.npz", "feedforward.json", "settings.json")}
    (gain_dir / "selection.json").write_text(json.dumps({
        "analysis": "P size at fixed correction limits",
        "run_ids": list(GAIN_IDS), "input_sha256": common,
        "signal": "measure_00 a_control_uT (EMA 0.3); error=measured-target; no shifting or trimming",
        "x_axis": "logged command path, not actual TCP X",
        "limits_mm_mm_s_mm_s2": [.2, 2, 40],
        "interpretation": "Descriptive run-level comparison; one repeat except P=0.05. "
                          "Do not infer an optimal gain from these observations alone.",
        "excluded": "Other P runs changed correction limits and are not part of the gain sweep.",
    }, indent=2) + "\n")
    (limit_dir / "selection.json").write_text(json.dumps({
        "analysis": "Selected measured limit profiles at P=2, plus one-factor command replay",
        "run_ids": list(LIMIT_IDS), "input_sha256": common,
        "signal": "measure_00 a_control_uT (EMA 0.3); error=measured-target; no shifting or trimming",
        "x_axis": "logged command path, not actual TCP X",
        "excluded_from_main_figures": EXCLUDED_LIMIT_IDS,
        "exclusion_caveat": "Excluded as previously suspect comparisons, not proven invalid runs. "
                            "High error alone does not establish procedural failure.",
        "measured_interpretation": "Profiles change multiple limits together; repeat variation "
                                   "is visible. Do not attribute magnetic differences to one limit.",
        "replay_source_run_id": "68defd",
        "replay_validation": "Baseline command replay matches all 1011 logged measure corrections.",
        "replay_interpretation": "Recorded magnetic signal is held fixed. One limit changes at a time; "
                                 "this compares software commands only, not counterfactual "
                                 "magnetic tracking or actual TCP movement.",
    }, indent=2) + "\n")
    print(f"gain: {gain_dir} ({len(gain)} runs)")
    print(f"limits: {limit_dir} ({len(limits)} measured runs, {len(replay_metrics)} replays)")


if __name__ == "__main__":
    main()
