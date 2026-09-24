#!/usr/bin/env python3
"""Plot compatible ladder repeats in one spatial chart with a steady summary."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np

from merge_ladder_runs import _load_run, _path_groups, _smooth_on_grid


STEADY_FROM_MM = 30.0
STEADY_TO_MM = 170.0
MIN_COMPLETE_RATIO = 0.995


def _read_run(folder: Path):
    rows, signature = _load_run(folder, require_completed=False)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    setup = json.loads((folder / "setup.json").read_text(encoding="utf-8"))
    resolved = json.loads((folder / "resolved.json").read_text(encoding="utf-8"))
    if signature[0] != "+x":
        raise ValueError(f"only +x ladder runs are supported: {folder}")
    origin_x_mm = float(setup["origin_x_mm"])
    groups = {int(key[2]): group for key, group in _path_groups(rows).items()}
    steady = {}
    with (folder / "control.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            phase = str(row.get("phase", ""))
            if not phase.startswith("measure_"):
                continue
            try:
                visit = int(phase.split("_", 1)[1])
                travel = float(row["x_cmd_m"]) * 1000.0 - origin_x_mm
                amplitude = float(row["a_control_uT"])
            except (KeyError, TypeError, ValueError):
                continue
            if STEADY_FROM_MM <= travel <= STEADY_TO_MM and math.isfinite(amplitude):
                steady.setdefault(visit, []).append(amplitude)
    return {
        "folder": folder,
        "id": folder.name.rsplit("__", 1)[-1],
        "status": manifest.get("status"),
        "expected_visits": set(range(int(resolved["path"]["steps"]))),
        "signature": signature,
        "groups": groups,
        "steady": steady,
    }


def plot_combined(run_dirs: list[Path], output_dir: Path, *,
                  stem: str | None = None, title: str | None = None,
                  run_labels: tuple[str, str] | None = None,
                  simple_names: bool = False):
    if len(run_dirs) != 2:
        raise ValueError("exactly two runs are required")
    runs = [_read_run(Path(folder)) for folder in run_dirs]
    if runs[0]["signature"][:3] != runs[1]["signature"][:3]:
        raise ValueError("runs have incompatible axis, travel, or speed")
    travel_mm = float(runs[0]["signature"][1])
    visits = sorted(set(runs[0]["groups"]) & set(runs[1]["groups"]))
    included = []
    for visit in visits:
        groups = [run["groups"][visit] for run in runs]
        if any(max(float(row["travel_mm"]) for row in group) <
               travel_mm * MIN_COMPLETE_RATIO for group in groups):
            continue
        if any(len(run["steady"].get(visit, [])) < 2 for run in runs):
            continue
        z_values = [float(group[0]["z_mm"]) for group in groups]
        if abs(z_values[0] - z_values[1]) > 1e-5:
            raise ValueError(f"Z mismatch at visit {visit}")
        included.append((visit, z_values[0]))
    if not included:
        raise ValueError("no common complete measurement paths")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    output_dir = Path(output_dir)
    stem = stem or output_dir.name
    if not stem or Path(stem).name != stem:
        raise ValueError("stem must be a nonempty file-name prefix")
    if run_labels is not None and len(run_labels) != 2:
        raise ValueError("run_labels must have two entries")
    display_labels = run_labels or tuple(run["id"] for run in runs)
    output_dir.mkdir(parents=True, exist_ok=True)
    colors = plt.cm.viridis(np.linspace(0.08, 0.88, len(included)))
    fig, (spatial_ax, steady_ax) = plt.subplots(
        1, 2, figsize=(17, 8), dpi=150,
        gridspec_kw={"width_ratios": [3.6, 1.2], "wspace": 0.25})
    summary = []
    grid = np.arange(0.0, travel_mm + 1e-9, 0.5)
    for color, (visit, z_mm) in zip(colors, included):
        for index, run in enumerate(runs):
            group = run["groups"][visit]
            raw_x = np.asarray([row["travel_mm"] for row in group], dtype=float)
            raw_y = np.asarray([row["Bxy_uT"] for row in group], dtype=float)
            style = "-" if index == 0 else "--"
            spatial_ax.plot(raw_x, raw_y, color=color, alpha=0.07,
                            linewidth=0.55, linestyle=style)
            spatial_ax.plot(grid, _smooth_on_grid(group, grid), color=color,
                            linewidth=2.0, linestyle=style)
            values = np.asarray(run["steady"][visit], dtype=float)
            median = float(np.median(values))
            p10, p90 = (float(value) for value in np.percentile(values, [10, 90]))
            steady_ax.errorbar(
                z_mm + (-0.09 if index == 0 else 0.09), median,
                yerr=[[median - p10], [p90 - median]],
                color=color, fmt="o" if index == 0 else "s",
                markersize=5, capsize=2.5, linewidth=1.2)
            summary.append({
                "run_id": run["id"], "status": run["status"],
                "visit": visit, "z_mm": z_mm,
                "matched_raw_samples": len(group),
                "steady_samples": len(values), "steady_median_uT": median,
                "steady_p10_uT": p10, "steady_p90_uT": p90,
            })

    for index, run in enumerate(runs):
        points = sorted(
            (row for row in summary if row["run_id"] == run["id"]),
            key=lambda row: row["z_mm"], reverse=True)
        steady_ax.plot(
            [row["z_mm"] + (-0.09 if index == 0 else 0.09) for row in points],
            [row["steady_median_uT"] for row in points],
            color="0.25" if index == 0 else "0.55",
            linestyle="-" if index == 0 else "--", linewidth=1.5,
            label=display_labels[index], zorder=1)

    spatial_ax.set_xlim(0, travel_mm)
    spatial_ax.set_xlabel("Travel along +X (mm)")
    spatial_ax.set_ylabel(r"$|\Delta B_{xy}|$ ($\mu$T)")
    spatial_ax.set_title("All completed Z paths in one coordinate")
    spatial_ax.grid(True, alpha=0.22)
    steady_ax.set_title("Steady response, X=30–170 mm")
    steady_ax.set_xlabel("Commanded Z (mm)")
    steady_ax.set_ylabel(r"Filtered $|\Delta B_{xy}|$ ($\mu$T)")
    steady_ax.invert_xaxis()
    steady_ax.grid(True, alpha=0.22)
    steady_ax.legend(title="Run / line style", fontsize=8)
    steady_ax.text(0.5, 0.02, "point: median · bar: 10th–90th percentile",
                   transform=steady_ax.transAxes, ha="center", fontsize=8,
                   color="0.35")
    depth_handles = [Line2D([0], [0], color=color, lw=2, label=f"Z={z_mm:.3f} mm")
                     for color, (_, z_mm) in zip(colors, included)]
    run_handles = [Line2D([0], [0], color="0.25", lw=2,
                          ls="-" if index == 0 else "--",
                          marker="o" if index == 0 else "s",
                          label=display_labels[index])
                   for index, run in enumerate(runs)]
    depth_legend = spatial_ax.legend(handles=depth_handles, title="Depth / color",
                                     ncol=2, loc="upper right", fontsize=8)
    spatial_ax.add_artist(depth_legend)
    spatial_ax.legend(handles=run_handles, title="Run / line style",
                      loc="upper left", fontsize=8)
    plot_title = title or "Combined ladder comparison"
    fig.suptitle(f"{plot_title} | {runs[0]['signature'][2]:g} mm/s | 10.5 mm Hann smoothing",
                 fontsize=16, y=0.99)
    fig.subplots_adjust(top=0.89, bottom=0.12, left=0.07, right=0.98)
    plot_path = output_dir / (f"{stem}_comparison.png" if simple_names
                              else f"{stem}__spatial_and_steady.png")
    fig.savefig(plot_path, bbox_inches="tight")
    plt.close(fig)

    summary_csv = output_dir / (f"{stem}_steady_summary.csv" if simple_names
                                 else f"{stem}__steady_summary.csv")
    with summary_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)
    metadata = {
        "source_runs": [str(run["folder"].resolve()) for run in runs],
        "included_visits": [visit for visit, _ in included],
        "excluded_visits": sorted((runs[0]["expected_visits"] | runs[1]["expected_visits"])
                                  - {visit for visit, _ in included}),
        "z_mm": [z for _, z in included],
        "smoothing": "0.5 mm grid, 21-point Hann (10.5 mm)",
        "steady_window_travel_mm": [STEADY_FROM_MM, STEADY_TO_MM],
        "steady_statistic": "median and 10th–90th percentile of control a_control_uT",
        "title": plot_title,
        "display_run_labels": list(display_labels),
        "plot": str(plot_path.resolve()),
        "summary_csv": str(summary_csv.resolve()),
    }
    metadata_path = output_dir / (f"{stem}_metadata.json" if simple_names
                                  else f"{stem}__plot_metadata.json")
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dirs", nargs=2, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--stem", help="descriptive prefix for files in the combined folder")
    parser.add_argument("--title", help="optional figure title")
    parser.add_argument("--run-labels", nargs=2, metavar=("FIRST", "SECOND"))
    parser.add_argument("--simple-names", action="store_true")
    args = parser.parse_args()
    result = plot_combined(args.run_dirs, args.output, stem=args.stem,
                           title=args.title, run_labels=args.run_labels,
                           simple_names=args.simple_names)
    print(result["plot"])


if __name__ == "__main__":
    main()
