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
DIRECTION_FOLDERS = {"+x": "正X方向", "+y": "正Y方向",
                     "-x": "负X方向", "-y": "负Y方向"}


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
            matches = [path for path in run_root.glob("*/manifest.json")
                       if json.loads(path.read_text(encoding="utf-8"))["run_id"].endswith("-" + run_id)]
            if len(matches) != 1:
                raise ValueError(f"expected one run with ID {run_id}: {matches}")
            run = _read_run(matches[0].parent)
            if run["status"] != "completed":
                raise ValueError(f"run is not completed: {matches[0]}")
            setup = json.loads((matches[0].parent / "setup.json").read_text(encoding="utf-8"))
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
            [run["folder"] for run in pair], output_dir.parent / DIRECTION_FOLDERS[direction],
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
    steady_ax, average_ax, depth10_ax, depth13_ax = axes.flat
    direction_stats = []
    direction_means = []
    figure_visits = range(7)  # Z=24 mm / depth 16 mm is under review.
    for direction, pair, color in run_groups:
        z_values = np.array([z_by_visit[visit] for visit in range(8)])
        depth = 40.0 - z_values
        medians = np.vstack([
            [next(item["steady_median_uT"] for item in rows
                  if item["direction"] == direction and item["run_id"] == run["id"]
                  and item["visit"] == visit) for visit in range(8)]
            for run in pair])
        mean_median = medians.mean(axis=0)
        direction_means.append(mean_median)
        for run_medians in medians:
            steady_ax.plot(depth[list(figure_visits)], run_medians[list(figure_visits)],
                           color=color, alpha=0.35, lw=1.2)
        steady_ax.plot(depth[list(figure_visits)], mean_median[list(figure_visits)], color=color, lw=2.5,
                       marker="o", markersize=4, label=direction)
        direction_stats.append({
            "direction": direction,
            "orientation": ORIENTATION_LABELS[direction],
            "run_ids": [run["id"] for run in pair],
            "depth_mm": depth.tolist(),
            "mean_steady_median_uT": mean_median.tolist(),
            "repeat_abs_gap_uT": np.abs(medians[0] - medians[1]).tolist(),
            "mean_across_depths_uT": float(mean_median.mean()),
            "mean_across_plotted_depths_uT": float(mean_median[list(figure_visits)].mean()),
        })
        for target_depth, axis in ((10.0, depth10_ax), (13.0, depth13_ax)):
            lower_visit = next(visit for visit in range(7)
                               if depth[visit] <= target_depth <= depth[visit + 1])
            fraction = ((target_depth - depth[lower_visit]) /
                        (depth[lower_visit + 1] - depth[lower_visit]))
            pair_curves = np.vstack([
                (1 - fraction) * curves[(direction, run["id"], lower_visit)]
                + fraction * curves[(direction, run["id"], lower_visit + 1)]
                for run in pair
            ])
            mean_curve = pair_curves.mean(axis=0)
            axis.fill_between(grid, pair_curves.min(axis=0), pair_curves.max(axis=0),
                              color=color, alpha=0.12, linewidth=0)
            axis.plot(grid, mean_curve, color=color, lw=2, label=direction)

    pooled_mean = np.mean(np.vstack(direction_means), axis=0)
    plotted_depth = depth[list(figure_visits)]
    average_ax.plot(plotted_depth, pooled_mean[list(figure_visits)],
                    color="#303642", lw=2.6, marker="o", markersize=5)
    for x, y in zip(plotted_depth, pooled_mean[list(figure_visits)]):
        average_ax.annotate(f"{y:.1f}", (x, y), xytext=(0, 8),
                            textcoords="offset points", ha="center", fontsize=8)
    steady_ax.set_title("Steady response vs commanded depth (depth 16 mm excluded)")
    steady_ax.set_ylabel(r"Median filtered $|\Delta B_{xy}|$ ($\mu$T)")
    steady_ax.legend(loc="upper left", fontsize=8)
    steady_ax.text(0.02, 0.72, "thin: each run   thick: two-run mean",
                   transform=steady_ax.transAxes, fontsize=8, color="0.35")
    average_ax.set_title("Mean of four direction means (equal weight)")
    average_ax.set_ylabel(r"Four-direction mean $|\Delta B_{xy}|$ ($\mu$T)")
    for ax in (steady_ax, average_ax):
        ax.set_xlabel("Commanded depth = 40 - Z (mm)")
        ax.set_xlim(3.7, 14.6)
        ax.grid(alpha=0.22)
    for target_depth, lower_visit, ax in ((10.0, 3, depth10_ax), (13.0, 5, depth13_ax)):
        ax.set_title(
            f"Along +X at interpolated depth {target_depth:g} mm "
            f"(measured {depth[lower_visit]:.3f}–{depth[lower_visit + 1]:.3f} mm)")
        ax.set_xlabel("Travel along +X (mm)")
        ax.set_ylabel(r"Interpolated smoothed $|\Delta B_{xy}|$ ($\mu$T)")
        ax.set_xlim(0, float(signature[1]))
        ax.grid(alpha=0.22)
    depth10_ax.text(0.02, 0.95, "line: two-run mean   band: repeat range",
                    transform=depth10_ax.transAxes, va="top", fontsize=8, color="0.35")
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
        "figure_excluded_depth_mm": [16.0],
        "figure_exclusion_reason": "operator suspects Z=24 mm data; raw data and CSV retained for audit",
        "four_direction_mean_depth_mm": plotted_depth.tolist(),
        "four_direction_mean_uT": pooled_mean[list(figure_visits)].tolist(),
        "interpolated_plot_depth_mm": [10.0, 13.0],
        "interpolation_method": "Within each run and direction, linear interpolation of smoothed |dBxy| curves between neighboring measured command depths; then equal-weight mean of two runs. These curves are not observations at the target depths.",
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
                        default=Path("runs/brush2/2026-09-23/01_四方向阶梯实验/raw"))
    parser.add_argument("--output", type=Path,
                        default=Path("runs/brush2/2026-09-23/01_四方向阶梯实验/analysis/四方向汇总"))
    args = parser.parse_args()
    result = build_comparison(args.run_root, args.output)
    print(result["plot"])
