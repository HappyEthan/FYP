#!/usr/bin/env python3
"""Compare the four completed brush2 orientation pairs from 2026-09-23."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from merge_ladder_runs import _smooth_on_grid
from plot_combined_ladders import _read_run, plot_combined


RUN_GROUPS = (
    ("+x", "df7649", "c575e5", "#1f77b4"),
    ("+y", "7d1a59", "486bc3", "#d95f02"),
    ("-x", "9666d5", "2f3488", "#7b3294"),
    ("-y", "43a39c", "3b670b", "#1b9e77"),
)
ORIENTATION_LABELS = {
    "+x": "Ry+15°, Rz0°",
    "+y": "Rx+15°, Rz90°",
    "-x": "Ry-15°, Rz180°",
    "-y": "Rx-15°, Rz270°",
}


def build_comparison(run_root: Path, output_dir: Path):
    run_root = Path(run_root)
    output_dir = Path(output_dir)
    run_groups = []
    signature = None
    z_by_visit = {}
    rows = []
    curves = {}
    for direction, first_id, second_id, color in RUN_GROUPS:
        pair = []
        for run_id in (first_id, second_id):
            matches = list(run_root.glob(f"*__{run_id}"))
            if len(matches) != 1:
                raise ValueError(f"expected one run with ID {run_id}: {matches}")
            run = _read_run(matches[0])
            if run["status"] != "completed":
                raise ValueError(f"run is not completed: {matches[0]}")
            setup = json.loads((matches[0] / "setup.json").read_text(encoding="utf-8"))
            if (float(setup["contact_z_mm"]), float(setup["origin_x_mm"]),
                    float(setup["origin_y_mm"])) != (40.0, -200.0, 500.0):
                raise ValueError(f"incompatible contact/origin: {matches[0]}")
            if signature is None:
                signature = run["signature"]
            elif run["signature"] != signature:
                raise ValueError(f"incompatible trajectory: {matches[0]}")
            if set(run["groups"]) != set(range(8)):
                raise ValueError(f"run has incomplete measurement paths: {matches[0]}")
            pair.append(run)
        run_groups.append((direction, pair, color))

    for direction, pair, _ in run_groups:
        result = plot_combined(
            [run["folder"] for run in pair], output_dir.parent / direction,
            stem=direction, title=f"{direction} | {ORIENTATION_LABELS[direction]}",
            run_labels=("Repeat 1", "Repeat 2"), simple_names=True)
        if result["included_visits"] != list(range(8)):
            raise ValueError(f"incomplete repeat comparison for {direction}")

    grid = np.arange(0.0, float(signature[1]) + 1e-9, 0.5)
    for direction, pair, color in run_groups:
        for run in pair:
            for visit in range(8):
                group = run["groups"][visit]
                travel = np.asarray([float(item["travel_mm"]) for item in group])
                if travel.min() > 1.0 or travel.max() < float(signature[1]) * 0.995:
                    raise ValueError(f"incomplete path: {run['folder']} visit {visit}")
                steady = np.asarray(run["steady"].get(visit, []), dtype=float)
                if len(steady) < 500 or not np.isfinite(steady).all():
                    raise ValueError(f"insufficient steady samples: {run['folder']} visit {visit}")
                z_mm = float(group[0]["z_mm"])
                if visit in z_by_visit and abs(z_by_visit[visit] - z_mm) > 1e-5:
                    raise ValueError(f"mismatched Z at visit {visit}")
                z_by_visit[visit] = z_mm
                rows.append({
                    "direction": direction, "run_id": run["id"],
                    "visit": visit, "z_mm": z_mm, "depth_mm": 40.0 - z_mm,
                    "matched_raw_samples": len(group),
                    "steady_samples": len(steady),
                    "steady_median_uT": float(np.median(steady)),
                    "steady_p10_uT": float(np.percentile(steady, 10)),
                    "steady_p90_uT": float(np.percentile(steady, 90)),
                })
                curves[(direction, run["id"], visit)] = _smooth_on_grid(group, grid)

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = "four_directions"
    summary_csv = output_dir / f"{stem}_pass_summary.csv"
    with summary_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    curve_csv = output_dir / f"{stem}_spatial_curves.csv"
    with curve_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("direction", "visit", "z_mm", "travel_mm",
                         "mean_smoothed_uT", "repeat_min_uT", "repeat_max_uT"))
        for direction, pair, _ in run_groups:
            for visit in range(8):
                pair_curves = np.vstack([curves[(direction, run["id"], visit)] for run in pair])
                for x, mean, low, high in zip(grid, pair_curves.mean(axis=0),
                                              pair_curves.min(axis=0), pair_curves.max(axis=0)):
                    writer.writerow((direction, visit, z_by_visit[visit], x, mean, low, high))

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(17, 10), dpi=150)
    steady_ax, gap_ax, shallow_ax, deep_ax = axes.flat
    direction_stats = []
    for direction, pair, color in run_groups:
        z_values = np.array([z_by_visit[visit] for visit in range(8)])
        depth = 40.0 - z_values
        medians = np.vstack([
            [next(item["steady_median_uT"] for item in rows
                  if item["direction"] == direction and item["run_id"] == run["id"]
                  and item["visit"] == visit) for visit in range(8)]
            for run in pair])
        mean_median = medians.mean(axis=0)
        for run_medians in medians:
            steady_ax.plot(depth, run_medians, color=color, alpha=0.35, lw=1.2)
        steady_ax.plot(depth, mean_median, color=color, lw=2.5,
                       marker="o", markersize=4, label=direction)
        gap_ax.plot(depth, np.abs(medians[0] - medians[1]), color=color,
                    lw=2, marker="o", markersize=4)
        direction_stats.append({
            "direction": direction,
            "orientation": ORIENTATION_LABELS[direction],
            "run_ids": [run["id"] for run in pair],
            "depth_mm": depth.tolist(),
            "mean_steady_median_uT": mean_median.tolist(),
            "repeat_abs_gap_uT": np.abs(medians[0] - medians[1]).tolist(),
            "mean_across_depths_uT": float(mean_median.mean()),
        })
        for visit, axis in ((0, shallow_ax), (7, deep_ax)):
            pair_curves = np.vstack([curves[(direction, run["id"], visit)] for run in pair])
            mean_curve = pair_curves.mean(axis=0)
            axis.fill_between(grid, pair_curves.min(axis=0), pair_curves.max(axis=0),
                              color=color, alpha=0.12, linewidth=0)
            axis.plot(grid, mean_curve, color=color, lw=2, label=direction)

    steady_ax.set_title("Steady response vs commanded depth")
    steady_ax.set_ylabel(r"Median filtered $|\Delta B_{xy}|$ ($\mu$T)")
    steady_ax.legend(loc="upper left", fontsize=8)
    steady_ax.text(0.02, 0.72, "thin: each run   thick: two-run mean",
                   transform=steady_ax.transAxes, fontsize=8, color="0.35")
    gap_ax.set_title("Difference between the two runs")
    gap_ax.set_ylabel(r"Absolute gap in steady median ($\mu$T)")
    for ax in (steady_ax, gap_ax):
        ax.set_xlabel("Commanded depth = 40 - Z (mm)")
        ax.set_xlim(4, 16)
        ax.grid(alpha=0.22)
    for visit, ax in ((0, shallow_ax), (7, deep_ax)):
        ax.set_title(f"Along +X at Z={z_by_visit[visit]:g} mm (depth {40-z_by_visit[visit]:g} mm)")
        ax.set_xlabel("Travel along +X (mm)")
        ax.set_ylabel(r"Smoothed raw $|\Delta B_{xy}|$ ($\mu$T)")
        ax.set_xlim(0, float(signature[1]))
        ax.grid(alpha=0.22)
    shallow_ax.text(0.02, 0.95, "line: two-run mean   band: repeat range",
                    transform=shallow_ax.transAxes, va="top", fontsize=8, color="0.35")
    fig.suptitle("Brush 2 | Four orientation directions | 2026-09-23 | 8 completed runs | commanded +X travel",
                 fontsize=15)
    fig.tight_layout(rect=(0, 0, 1, 0.955))
    plot_path = output_dir / f"{stem}_comparison.png"
    fig.savefig(plot_path, bbox_inches="tight")
    plt.close(fig)

    metadata = {
        "source_runs": [str(run["folder"].resolve()) for _, pair, _ in run_groups for run in pair],
        "excluded_fault_runs": ["901492", "4c8ffa"],
        "direction_labels": ORIENTATION_LABELS,
        "direction_meaning": "brush/sensor orientation category; all robot measurement paths command +X travel",
        "z_mm": [z_by_visit[visit] for visit in range(8)],
        "contact_z_mm": 40.0,
        "steady_window_travel_mm": [30.0, 170.0],
        "steady_statistic": "median of control a_control_uT",
        "spatial_smoothing": "raw sqrt(dBx_uT^2 + dBy_uT^2), 0.5 mm grid, 21-point Hann",
        "directions": direction_stats,
        "plot": str(plot_path.resolve()),
        "pass_summary_csv": str(summary_csv.resolve()),
        "spatial_curves_csv": str(curve_csv.resolve()),
    }
    metadata_path = output_dir / f"{stem}_metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    return metadata


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path,
                        default=Path("runs/brush2/2026-09-23"))
    parser.add_argument("--output", type=Path,
                        default=Path("runs/brush2/combined/2026-09-23/four_directions"))
    args = parser.parse_args()
    result = build_comparison(args.run_root, args.output)
    print(result["plot"])
