#!/usr/bin/env python3
"""Offline-only: combine completed one-way Z batches without losing provenance."""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np


FIELDS = (
    "source_run_id", "run_label", "visit", "z_mm", "travel_mm",
    "Bxy_uT", "baseline_id",
)


def _load_run(folder: Path, *, require_completed=True):
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if require_completed and manifest.get("status") != "completed":
        raise ValueError("run {} is not completed".format(folder))
    resolved = json.loads((folder / "resolved.json").read_text(encoding="utf-8"))
    if resolved.get("path", {}).get("order") != "one_way":
        raise ValueError("run {} is not a one_way batch".format(folder))
    label = resolved.get("run_label")
    if not isinstance(label, str) or not label.strip():
        raise ValueError("run {} has no run_label".format(folder))

    sensors = {}
    with (folder / "sensor.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("valid", "")).lower() not in {"1", "true"}:
                continue
            try:
                seq = int(row["seq"])
                dx, dy = float(row["dBx_uT"]), float(row["dBy_uT"])
            except (KeyError, TypeError, ValueError):
                continue
            if math.isfinite(dx) and math.isfinite(dy):
                sensors[seq] = (math.hypot(dx, dy), row.get("baseline_id", ""))

    by_visit = {}
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
                seq = int(row["sample_seq"])
                x_mm = float(row["x_cmd_m"]) * 1000.0
                y_mm = float(row["y_cmd_m"]) * 1000.0
                z_mm = float(row["z_cmd_m"]) * 1000.0
                amplitude, baseline_id = sensors[seq]
            except (KeyError, TypeError, ValueError):
                continue
            by_visit.setdefault(visit, []).append(
                (x_mm, y_mm, z_mm, amplitude, baseline_id))

    output = []
    for visit, rows in sorted(by_visit.items()):
        x0, y0 = rows[0][0], rows[0][1]
        for x_mm, y_mm, z_mm, amplitude, baseline_id in rows:
            output.append({
                "source_run_id": manifest.get("run_id", folder.name),
                "run_label": label,
                "visit": visit,
                "z_mm": z_mm,
                "travel_mm": math.hypot(x_mm - x0, y_mm - y0),
                "Bxy_uT": amplitude,
                "baseline_id": baseline_id,
            })
    signature = (
        resolved["path"].get("axis"), float(resolved["path"].get("travel_mm")),
        float(resolved["motion"].get("speed_mm_s")),
        tuple(round(float(z), 6) for z in sorted({row["z_mm"] for row in output})),
    )
    return output, signature


def _smooth_on_grid(rows, grid):
    x = np.asarray([row["travel_mm"] for row in rows], dtype=float)
    y = np.asarray([row["Bxy_uT"] for row in rows], dtype=float)
    order = np.argsort(x)
    x, y = x[order], y[order]
    interp = np.interp(grid, x, y)
    window = min(21, len(interp) if len(interp) % 2 else len(interp) - 1)
    if window < 5:
        return interp
    weights = np.hanning(window)
    weights /= weights.sum()
    pad = window // 2
    return np.convolve(np.pad(interp, pad, mode="edge"), weights, mode="valid")


def _write_plot(rows, target):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    z_values = sorted({round(float(row["z_mm"]), 6) for row in rows}, reverse=True)
    labels = sorted({row["run_label"] for row in rows})
    colors = plt.cm.viridis(np.linspace(0.05, 0.95, len(z_values)))
    fig, ax = plt.subplots(figsize=(12, 7), dpi=150)
    for color, z_mm in zip(colors, z_values):
        curves = []
        max_common = min(
            max(row["travel_mm"] for row in rows
                if round(float(row["z_mm"]), 6) == z_mm and row["run_label"] == label)
            for label in labels)
        grid = np.arange(0.0, max_common + 1e-9, 0.5)
        for label in labels:
            subset = [row for row in rows
                      if round(float(row["z_mm"]), 6) == z_mm
                      and row["run_label"] == label]
            curve = _smooth_on_grid(subset, grid)
            curves.append(curve)
            ax.plot(grid, curve, color=color, alpha=0.35, linewidth=1.0)
        mean = np.mean(np.vstack(curves), axis=0)
        ax.plot(grid, mean, color=color, linewidth=2.5, label="Z={:.2f} mm".format(z_mm))
    ax.set_xlabel("Travel distance (mm)")
    ax.set_ylabel(r"$|\Delta B_{xy}|$ ($\mu$T)")
    ax.set_title("Combined one-way Z batches: thin=repeats, thick=mean")
    ax.grid(True, alpha=0.22)
    ax.legend(ncol=2, fontsize=8)
    fig.tight_layout()
    fig.savefig(target, bbox_inches="tight")
    plt.close(fig)


def _path_groups(rows):
    groups = {}
    for row in rows:
        key = (row["source_run_id"], row["run_label"], int(row["visit"]))
        groups.setdefault(key, []).append(row)
    return groups


def _write_stitched_plot(rows, target):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    groups = _path_groups(rows)
    z_values = sorted({round(float(group[0]["z_mm"]), 6)
                       for group in groups.values()}, reverse=True)
    colors = {
        z_mm: color for z_mm, color in zip(
            z_values, plt.cm.viridis(np.linspace(0.05, 0.95, len(z_values))))
    }
    labels = sorted({key[1] for key in groups})
    line_styles = {
        label: ("-" if index == 0 else "--")
        for index, label in enumerate(labels)
    }

    fig, (ax, summary_ax) = plt.subplots(
        1, 2, figsize=(14, 8), dpi=150,
        gridspec_kw={"width_ratios": [3.0, 1.05], "wspace": 0.27})
    summary_by_label = {}
    duplicate_counts = {
        z_mm: sum(1 for group in groups.values()
                  if round(float(group[0]["z_mm"]), 6) == z_mm)
        for z_mm in z_values
    }
    duplicate_seen = {z_mm: 0 for z_mm in z_values}

    ordered = sorted(
        groups.items(), key=lambda item: (-float(item[1][0]["z_mm"]), item[0]))
    for (run_id, label, visit), group in ordered:
        z_mm = round(float(group[0]["z_mm"]), 6)
        baseline_ids = sorted({str(row["baseline_id"]) for row in group})
        grid = np.arange(0.0, max(row["travel_mm"] for row in group) + 1e-9, 0.5)
        smooth = _smooth_on_grid(group, grid)
        raw_x = np.asarray([row["travel_mm"] for row in group], dtype=float)
        raw_y = np.asarray([row["Bxy_uT"] for row in group], dtype=float)
        color = colors[z_mm]
        style = line_styles[label]
        legend = "Z={:g} mm ({}; baseline {})".format(
            z_mm, label, "/".join(baseline_ids))
        ax.plot(raw_x, raw_y, color=color, alpha=0.10, linewidth=0.7,
                linestyle=style)
        ax.plot(grid, smooth, color=color, linewidth=2.2,
                linestyle=style, label=legend)

        values = np.asarray([row["Bxy_uT"] for row in group], dtype=float)
        median = float(np.median(values))
        low, high = np.percentile(values, [10, 90])
        count = duplicate_counts[z_mm]
        seen = duplicate_seen[z_mm]
        duplicate_seen[z_mm] += 1
        offset = 0.0 if count == 1 else (seen - (count - 1) / 2.0) * 0.22
        plot_z = z_mm + offset
        marker = "o" if label == labels[0] else "s"
        summary_ax.errorbar(
            plot_z, median, yerr=[[median - low], [high - median]],
            fmt=marker, color=color, markeredgecolor="white",
            markeredgewidth=0.7, capsize=4, linewidth=1.5, markersize=7,
            linestyle="none")
        summary_by_label.setdefault(label, []).append((plot_z, median))

    for label, points in summary_by_label.items():
        points.sort(reverse=True)
        summary_ax.plot(
            [point[0] for point in points], [point[1] for point in points],
            color="0.6", linewidth=1.1, linestyle=line_styles[label], zorder=0)

    ax.set_xlabel("Travel distance along +X (mm)")
    ax.set_ylabel(r"$|\Delta B_{xy}|=\sqrt{\Delta B_x^2+\Delta B_y^2}$ ($\mu$T)")
    ax.set_title("Magnetic response along each completed measurement path")
    ax.grid(True, alpha=0.22)
    ax.legend(fontsize=7.5, loc="best")
    ax.text(
        0.01, 0.015,
        "thin: raw matched samples   thick: 0.5 mm grid + 10.5 mm Hann smoothing",
        transform=ax.transAxes, fontsize=8.5, color="0.35")

    summary_ax.set_xlabel("Commanded Z (mm)")
    summary_ax.set_ylabel(r"$|\Delta B_{xy}|$ ($\mu$T)")
    summary_ax.set_title("Spatial distribution summary")
    summary_ax.grid(True, alpha=0.22)
    summary_ax.invert_xaxis()
    summary_ax.text(
        0.5, 0.02,
        "point: median\nbar: 10th–90th percentile\ndashed/square: continuation run",
        transform=summary_ax.transAxes, ha="center", va="bottom",
        fontsize=8.5, color="0.35")
    fig.suptitle(
        "Stitched Z ladder | {} | 10 mm/s | completed measure phases only".format(
            " + ".join(labels)), fontsize=15)
    fig.savefig(target, bbox_inches="tight")
    plt.close(fig)


def _write_repeat_comparison_plot(rows, target):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    groups = _path_groups(rows)
    z_values = sorted({round(float(group[0]["z_mm"]), 6)
                       for group in groups.values()}, reverse=True)
    labels = sorted({key[1] for key in groups})
    colors = {
        label: color for label, color in zip(
            labels, plt.cm.tab10(np.linspace(0.0, 0.4, len(labels))))
    }
    columns = 3
    rows_count = int(math.ceil((len(z_values) + 1) / columns))
    fig, axes = plt.subplots(
        rows_count, columns, figsize=(15, 4.8 * rows_count), dpi=150,
        squeeze=False)
    flat_axes = list(axes.flat)
    summary_ax = flat_axes[len(z_values)]
    summary = {label: [] for label in labels}

    for axis, z_mm in zip(flat_axes, z_values):
        for label in labels:
            matching = [
                group for key, group in groups.items()
                if key[1] == label
                and round(float(group[0]["z_mm"]), 6) == z_mm
            ]
            if len(matching) != 1:
                raise ValueError(
                    "expected exactly one path for {} at Z={}".format(label, z_mm))
            group = matching[0]
            raw_x = np.asarray([row["travel_mm"] for row in group], dtype=float)
            raw_y = np.asarray([row["Bxy_uT"] for row in group], dtype=float)
            grid = np.arange(0.0, raw_x.max() + 1e-9, 0.5)
            smooth = _smooth_on_grid(group, grid)
            axis.plot(raw_x, raw_y, color=colors[label], alpha=0.08, linewidth=0.6)
            axis.plot(grid, smooth, color=colors[label], linewidth=2.0, label=label)
            median = float(np.median(raw_y))
            low, high = np.percentile(raw_y, [10, 90])
            summary[label].append((z_mm, median, float(low), float(high)))
        axis.set_title("Z={:g} mm".format(z_mm))
        axis.set_xlim(0.0, 200.0)
        axis.set_xlabel("Travel along +X (mm)")
        axis.set_ylabel(r"$|\Delta B_{xy}|$ ($\mu$T)")
        axis.grid(True, alpha=0.22)

    for label in labels:
        points = sorted(summary[label], reverse=True)
        z = np.asarray([point[0] for point in points])
        median = np.asarray([point[1] for point in points])
        low = np.asarray([point[2] for point in points])
        high = np.asarray([point[3] for point in points])
        summary_ax.errorbar(
            z, median, yerr=np.vstack((median - low, high - median)),
            color=colors[label], marker="o", linewidth=1.7, capsize=3,
            markersize=5, label=label)
    summary_ax.set_title("Spatial distribution summary")
    summary_ax.set_xlabel("Commanded Z (mm)")
    summary_ax.set_ylabel(r"$|\Delta B_{xy}|$ median ($\mu$T)")
    summary_ax.invert_xaxis()
    summary_ax.grid(True, alpha=0.22)
    summary_ax.legend(fontsize=8)
    summary_ax.text(
        0.5, 0.02, "point: median   bar: 10th–90th percentile",
        transform=summary_ax.transAxes, ha="center", va="bottom",
        fontsize=8, color="0.35")

    for axis in flat_axes[len(z_values) + 1:]:
        axis.set_visible(False)
    handles, legend_labels = flat_axes[0].get_legend_handles_labels()
    fig.legend(
        handles, legend_labels, loc="upper center", ncol=len(labels),
        bbox_to_anchor=(0.5, 0.955), frameon=True)
    fig.suptitle(
        "Repeat comparison | 10 mm/s | raw samples + 10.5 mm Hann smoothing",
        fontsize=15, y=0.995)
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.93))
    fig.savefig(target, bbox_inches="tight")
    plt.close(fig)


def merge_ladder_runs(run_dirs, output_dir):
    folders = [Path(path) for path in run_dirs]
    if len(folders) < 2:
        raise ValueError("at least two completed runs are required")
    combined = []
    expected = None
    for folder in folders:
        rows, signature = _load_run(folder)
        if expected is None:
            expected = signature
        elif signature != expected:
            raise ValueError("runs have incompatible axis/travel/speed/Z values")
        combined.extend(rows)

    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    csv_path = target / "combined_measurements.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(combined)
    plot_path = target / "combined_bxy_by_z.png"
    _write_plot(combined, plot_path)
    summary = {
        "source_runs": [str(folder) for folder in folders],
        "rows": len(combined),
        "z_mm": sorted({float(row["z_mm"]) for row in combined}),
        "csv": str(csv_path.resolve()),
        "plot": str(plot_path.resolve()),
    }
    (target / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def stitch_ladder_runs(run_dirs, output_dir, *, min_completion_ratio=0.99):
    """Combine complete measurement paths across continuation or faulted runs."""
    folders = [Path(path) for path in run_dirs]
    if len(folders) < 2:
        raise ValueError("at least two runs are required")
    included = []
    excluded = []
    expected_motion = None
    for folder in folders:
        rows, signature = _load_run(folder, require_completed=False)
        motion_signature = signature[:3]
        if expected_motion is None:
            expected_motion = motion_signature
        elif motion_signature != expected_motion:
            raise ValueError("runs have incompatible axis/travel/speed values")
        expected_travel = float(signature[1])
        for (run_id, label, visit), group in sorted(_path_groups(rows).items()):
            max_travel = max(float(row["travel_mm"]) for row in group)
            if max_travel + 1e-9 < expected_travel * float(min_completion_ratio):
                excluded.append({
                    "source_run_id": run_id,
                    "run_label": label,
                    "visit": visit,
                    "z_mm": float(np.median([row["z_mm"] for row in group])),
                    "max_travel_mm": max_travel,
                })
                continue
            included.extend(group)
    if not included:
        raise ValueError("no complete measurement paths found")

    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    csv_path = target / "combined_measurements.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(included)
    plot_path = target / "combined_bxy_by_z.png"
    _write_stitched_plot(included, plot_path)
    summary = {
        "mode": "stitched_complete_paths",
        "source_runs": [str(folder) for folder in folders],
        "rows": len(included),
        "included_paths": len(_path_groups(included)),
        "excluded_incomplete_paths": excluded,
        "z_mm": sorted({float(row["z_mm"]) for row in included}),
        "csv": str(csv_path.resolve()),
        "plot": str(plot_path.resolve()),
    }
    (target / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def compare_ladder_repeats(run_dirs, output_dir):
    """Compare completed, compatible repeat runs in one panel per Z level."""
    folders = [Path(path) for path in run_dirs]
    if len(folders) < 2:
        raise ValueError("at least two completed repeat runs are required")
    combined = []
    expected = None
    labels = []
    for folder in folders:
        rows, signature = _load_run(folder)
        if expected is None:
            expected = signature
        elif signature != expected:
            raise ValueError("runs have incompatible axis/travel/speed/Z values")
        label = rows[0]["run_label"] if rows else ""
        if label in labels:
            raise ValueError("repeat run labels must be unique")
        labels.append(label)
        combined.extend(rows)

    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    csv_path = target / "comparison_measurements.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(combined)
    plot_path = target / "repeat_comparison_by_z.png"
    _write_repeat_comparison_plot(combined, plot_path)
    summary = {
        "mode": "repeat_comparison",
        "source_runs": [str(folder) for folder in folders],
        "repeat_labels": sorted(labels),
        "rows": len(combined),
        "z_mm": sorted({float(row["z_mm"]) for row in combined}),
        "csv": str(csv_path.resolve()),
        "plot": str(plot_path.resolve()),
    }
    (target / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="合并两个或更多已完成的单向 Z 批次")
    parser.add_argument("run_dirs", nargs="+", help="要合并的 run 目录")
    parser.add_argument("--output", help="输出目录；默认写入 runs/combined/<timestamp>")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--stitch-partial", action="store_true",
        help="续测拼接：允许 fault/aborted run，只保留行程完成度至少 99%% 的测量路径")
    mode.add_argument(
        "--compare-repeats", action="store_true",
        help="重复实验对比：每个 Z 一个子图，最后一个子图汇总中位数与 10–90%% 区间")
    args = parser.parse_args(argv)
    if len(args.run_dirs) < 2:
        parser.error("至少提供两个 run 目录")
    output = (Path(args.output) if args.output else
              Path(args.run_dirs[0]).resolve().parent / "combined" /
              datetime.now().strftime("%Y%m%dT%H%M%S"))
    if args.compare_repeats:
        result = compare_ladder_repeats(args.run_dirs, output)
    elif args.stitch_partial:
        result = stitch_ladder_runs(args.run_dirs, output)
    else:
        result = merge_ladder_runs(args.run_dirs, output)
    print("合并完成: {}".format(output))
    print("CSV: {}".format(result["csv"]))
    print("图: {}".format(result["plot"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
