#!/usr/bin/env python3
"""Compare recorded StrokePlan magnetic responses with their logged targets."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


PROFILES = (
    ("01_gradual_press", "01 Gradual press"),
    ("02_single_arch", "02 Single arch"),
    ("03_double_wave", "03 Double wave"),
    ("04_smooth_levels_wide_transitions", "04 Wide transitions"),
)


def _load_run(folder: Path, profile: str, control_mode: str) -> dict:
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "completed" or manifest.get("execution_environment") != "hardware":
        raise ValueError(f"expected completed hardware run: {folder}")
    label = f"strokeplan_p_{profile}" if control_mode == "p" else f"strokeplan_{profile}"
    if f"__{label}__" not in folder.name:
        raise ValueError(f"unexpected run label: {folder}")
    for name in ("strokeplan.npz", "feedforward.json", "settings.json", "resolved.json"):
        digest = hashlib.sha256((folder / name).read_bytes()).hexdigest()
        if digest != manifest["sha256"][name]:
            raise ValueError(f"snapshot hash mismatch: {folder / name}")
    control = json.loads((folder / "resolved.json").read_text(encoding="utf-8"))["control"]
    if control_mode == "p":
        if not control.get("enabled") or control.get("mode") != "p":
            raise ValueError(f"expected P feedback run: {folder}")
    elif control.get("enabled"):
        raise ValueError(f"expected pure feedforward run: {folder}")
    with np.load(folder / "strokeplan.npz", allow_pickle=False) as plan:
        if int(plan["format_version"]) != 3 or int(plan["n_strokes"]) != 1:
            raise ValueError(f"expected single-stroke V3 plan: {folder}")
        expected_target = np.asarray(plan["s0_g"], dtype=float)

    with (folder / "control.jsonl").open(encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    measure = [row for row in rows if row.get("phase") == "measure_00"]
    if len(measure) != len(expected_target) or len(measure) < 2:
        raise ValueError(f"incomplete measurement timeline: {folder}")
    target = np.asarray([row["a_ref_uT"] for row in measure], dtype=float)
    observed = np.asarray([row["a_control_uT"] for row in measure], dtype=float)
    x_mm = 1000 * (np.asarray([row["x_cmd_m"] for row in measure], dtype=float)
                   - float(measure[0]["x_cmd_m"]))
    if (not np.isfinite(np.r_[target, observed, x_mm]).all()
            or np.any(np.diff(x_mm) < -1e-8)
            or abs(x_mm[-1] - 200) > 0.1
            or not np.allclose(target, expected_target, atol=1e-6, rtol=0)):
        raise ValueError(f"target or trajectory mismatch: {folder}")
    error = observed - target
    return {
        "folder": folder,
        "run_id": manifest["run_id"],
        "short_id": folder.name.rsplit("__", 1)[-1],
        "x_mm": x_mm,
        "target": target,
        "observed": observed,
        "error": error,
        "control": control,
        "baseline": manifest.get("baseline", {}),
        "metrics": {
            "samples": len(measure),
            "mae_uT": float(np.mean(np.abs(error))),
            "median_abs_error_uT": float(np.median(np.abs(error))),
            "p90_abs_error_uT": float(np.percentile(np.abs(error), 90)),
            "mean_signed_error_uT": float(np.mean(error)),
            "correlation": float(np.corrcoef(target, observed)[0, 1]),
            "observed_min_uT": float(observed.min()),
            "observed_max_uT": float(observed.max()),
        },
    }


def _plot_overview(grouped: list[list[dict]], output: Path, control_mode: str) -> None:
    colors = plt.cm.viridis(np.linspace(0.12, 0.85, len(PROFILES)))
    fig, axes = plt.subplots(4, 2, figsize=(17, 15), dpi=150, sharex=True, sharey=True)
    for i, ((_, title), runs) in enumerate(zip(PROFILES, grouped)):
        for j, run in enumerate(runs):
            ax = axes[i, j]
            ax.plot(run["x_mm"], run["target"], color="0.25", ls="--", lw=1.6,
                    label="StrokePlan target")
            ax.plot(run["x_mm"], run["observed"], color=colors[i], lw=1.9,
                    label="Recorded filtered response")
            metrics = run["metrics"]
            ax.set_title(f"{title} | repeat {j+1} · {run['short_id']}", loc="left", fontsize=11)
            ax.text(0.02, 0.95,
                    f"MAE {metrics['mae_uT']:.1f}  ·  median |error| {metrics['median_abs_error_uT']:.1f}"
                    f"  ·  P90 {metrics['p90_abs_error_uT']:.1f} µT",
                    transform=ax.transAxes, va="top", fontsize=8.5,
                    bbox={"facecolor": "white", "alpha": 0.85, "edgecolor": "none"})
            ax.set_xlim(0, 200)
            ax.set_ylim(0, 380)
            ax.grid(True, alpha=0.22)
            if j == 0:
                ax.set_ylabel("Magnetic response (µT)")
            if i == 3:
                ax.set_xlabel("Travel along +X (mm)")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=2, bbox_to_anchor=(0.5, 0.972))
    mode = "FF + P · " if control_mode == "p" else ""
    fig.suptitle(f"StrokePlan tracking | {mode}brush2 · Ry+15° · +X 200 mm · 10 mm/s",
                 fontsize=16)
    fig.text(0.5, 0.011,
             "Recorded line is a_control_uT (EMA α=0.3); metrics use all 1,011 writing samples."
             " Completed run ≠ tracking validated.",
             ha="center", fontsize=9, color="0.35")
    fig.tight_layout(rect=(0.02, 0.025, 0.99, 0.946), h_pad=2.0)
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)


def _plot_errors(grouped: list[list[dict]], output: Path, control_mode: str) -> None:
    colors = plt.cm.viridis(np.linspace(0.12, 0.85, len(PROFILES)))
    fig, axes = plt.subplots(4, 2, figsize=(17, 14), dpi=150, sharex=True, sharey=True)
    for i, ((_, title), runs) in enumerate(zip(PROFILES, grouped)):
        for j, run in enumerate(runs):
            ax = axes[i, j]
            ax.axhline(0, color="0.25", ls="--", lw=1)
            ax.plot(run["x_mm"], run["error"], color=colors[i], lw=1.5)
            ax.set_title(f"{title} | repeat {j+1} · {run['short_id']}", loc="left", fontsize=11)
            ax.text(0.02, 0.95, f"Mean signed error {run['metrics']['mean_signed_error_uT']:+.1f} µT",
                    transform=ax.transAxes, va="top", fontsize=8.5,
                    bbox={"facecolor": "white", "alpha": 0.85, "edgecolor": "none"})
            ax.set_xlim(0, 200)
            ax.set_ylim(-100, 180)
            ax.grid(True, alpha=0.22)
            if j == 0:
                ax.set_ylabel("Measured − target (µT)")
            if i == 3:
                ax.set_xlabel("Travel along +X (mm)")
    mode = "FF + P | " if control_mode == "p" else ""
    fig.suptitle(f"StrokePlan signed tracking error | {mode}positive = stronger than target",
                 fontsize=16)
    fig.tight_layout(rect=(0.02, 0.02, 0.99, 0.965), h_pad=2.0)
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)


def _plot_detail(run: dict, title: str, repeat: int, color, output: Path) -> None:
    fig, (ax, err_ax) = plt.subplots(2, 1, figsize=(12, 7.5), dpi=150, sharex=True,
                                     gridspec_kw={"height_ratios": [2.1, 1], "hspace": 0.12})
    ax.plot(run["x_mm"], run["target"], color="0.25", ls="--", lw=1.8,
            label="StrokePlan target a_ref_uT")
    ax.plot(run["x_mm"], run["observed"], color=color, lw=2,
            label="Recorded filtered response a_control_uT")
    ax.set_ylabel("Magnetic response (µT)")
    ax.set_ylim(0, 380)
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.22)
    err_ax.axhline(0, color="0.25", ls="--", lw=1)
    err_ax.plot(run["x_mm"], run["error"], color=color, lw=1.4)
    err_ax.set_ylabel("Measured − target (µT)")
    err_ax.set_xlabel("Travel along +X (mm)")
    err_ax.set_xlim(0, 200)
    err_ax.set_ylim(-100, 180)
    err_ax.grid(True, alpha=0.22)
    m = run["metrics"]
    fig.suptitle(f"{title} | repeat {repeat} · {run['short_id']} | MAE {m['mae_uT']:.1f} µT · "
                 f"median |error| {m['median_abs_error_uT']:.1f} µT · P90 {m['p90_abs_error_uT']:.1f} µT",
                 fontsize=13)
    fig.subplots_adjust(top=0.89, bottom=0.09, left=0.10, right=0.98, hspace=0.15)
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=Path("runs/brush2/2026-09-24"))
    parser.add_argument("--control-mode", choices=("feedforward", "p"),
                        default="feedforward")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output is None:
        name = "strokeplan_p_tracking_8" if args.control_mode == "p" else "strokeplan_tracking_8"
        args.output = args.run_dir.parent / "combined" / args.run_dir.name / name

    grouped = []
    for profile, _ in PROFILES:
        label = f"strokeplan_p_{profile}" if args.control_mode == "p" else f"strokeplan_{profile}"
        folders = sorted(args.run_dir.glob(f"*__{label}__*/manifest.json"))
        if len(folders) != 2:
            raise ValueError(f"expected two runs for {profile}, found {len(folders)}")
        grouped.append([_load_run(folder.parent, profile, args.control_mode)
                        for folder in folders])
    if args.control_mode == "p":
        controls = [run["control"] for runs in grouped for run in runs]
        if any(control != controls[0] for control in controls[1:]):
            raise ValueError("P run profiles differ; do not combine as one condition")
    args.output.mkdir(parents=True, exist_ok=args.control_mode == "feedforward")
    _plot_overview(grouped, args.output / "target_vs_measured_overview.png", args.control_mode)
    _plot_errors(grouped, args.output / "signed_error_overview.png", args.control_mode)
    colors = plt.cm.viridis(np.linspace(0.12, 0.85, len(PROFILES)))
    summary = []
    for i, ((profile, title), runs) in enumerate(zip(PROFILES, grouped)):
        for j, run in enumerate(runs, 1):
            filename = f"{profile}__repeat_{j}__{run['short_id']}.png"
            shown_title = f"FF + P | {title}" if args.control_mode == "p" else title
            _plot_detail(run, shown_title, j, colors[i], args.output / filename)
            summary.append({"profile": profile, "repeat": j, "run_id": run["run_id"],
                            "run_directory": str(run["folder"].resolve()), **run["metrics"]})
    with (args.output / "tracking_summary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)
    (args.output / "source_and_method.json").write_text(json.dumps({
        "source_runs": [row["run_directory"] for row in summary],
        "control_mode": args.control_mode,
        "feedback_profile": grouped[0][0]["control"] if args.control_mode == "p" else None,
        "measure_phase": "measure_00",
        "target_field": "a_ref_uT",
        "measured_field": "a_control_uT",
        "error_definition": "a_control_uT - a_ref_uT at the same logged control tick",
        "metrics": "All writing samples; no further smoothing or time shifting; no pass/fail threshold",
        "notes": "V3 input, feedforward/settings and resolved snapshots checked against manifest hashes."
                 " Commanded X is the distance axis; actual TCP pose is unavailable.",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote 10 PNGs and 2 data files to {args.output}")


if __name__ == "__main__":
    main()
