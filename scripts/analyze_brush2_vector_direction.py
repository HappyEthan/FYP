#!/usr/bin/env python3
"""Analyze signed horizontal magnetic changes in the 2026-09-23 brush2 ladder runs.

All four pose groups commanded +X travel. Directions below refer to the
baseline-subtracted sensor Bx/By plane, not a calibrated world-frame vector.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DAY = ROOT / "runs/brush2/2026-09-23/01_四方向阶梯实验"
OUT = DAY / "analysis/磁向量方向"
GROUPS = (
    ("+x", "姿态Ry正15", "Ry+15°, Rz0°", 0),
    ("+y", "姿态Rx正15_Rz90", "Rx+15°, Rz90°", 90),
    ("-x", "姿态Ry负15_Rz180", "Ry−15°, Rz180°", 180),
    ("-y", "姿态Rx负15_Rz270", "Rx−15°, Rz270°", 270),
)
DEPTHS = np.linspace(4.0, 16.0, 8)
plt.rcParams.update({"font.family": "Noto Sans CJK SC", "font.size": 10,
                     "axes.spines.top": False, "axes.spines.right": False})


def wrap_deg(angle: float) -> float:
    return (angle + 180.0) % 360.0 - 180.0


def write_csv(path: Path, records: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def load_run(folder: Path) -> dict:
    manifest = json.loads((folder / "manifest.json").read_text())
    if (manifest["status"] != "completed"
            or manifest["execution_environment"] != "hardware"):
        raise ValueError(f"expected completed hardware run: {folder}")
    for filename, digest in manifest["sha256"].items():
        if hashlib.sha256((folder / filename).read_bytes()).hexdigest() != digest:
            raise ValueError(f"snapshot hash mismatch: {folder / filename}")
    setup = json.loads((folder / "setup.json").read_text())
    origin_x_mm = float(setup["origin_x_mm"])
    sensor = {}
    with (folder / "sensor.csv").open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row["valid"] == "true" and row["dBx_uT"] and row["dBy_uT"]:
                sensor[int(row["seq"])] = (
                    float(row["dBx_uT"]), float(row["dBy_uT"]), row["baseline_id"])
    by_visit = {visit: [] for visit in range(8)}
    with (folder / "control.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if not row["phase"].startswith("measure_"):
                continue
            visit = int(row["phase"].split("_", 1)[1])
            x_mm = 1000 * float(row["x_cmd_m"]) - origin_x_mm
            if not 30 <= x_mm <= 170:
                continue
            dx, dy, baseline_id = sensor[int(row["sample_seq"])]
            if baseline_id != str(visit + 1):
                raise ValueError(f"unexpected path baseline: {folder} visit {visit}")
            by_visit[visit].append((x_mm, dx, dy, int(row["sample_seq"])))
    arrays = {}
    for visit, values in by_visit.items():
        data = np.asarray(values, dtype=float)
        if len(data) != 700 or len(set(data[:, 3])) != 700:
            raise ValueError(f"expected 700 distinct samples: {folder} visit {visit}")
        arrays[visit] = data[:, :3]
    return {"folder": folder, "run_id": manifest["run_id"], "visits": arrays}


def summarize(groups: dict) -> tuple[list[dict], list[dict]]:
    angle_rows, spatial_rows = [], []
    for label, _, posture, rz_deg in GROUPS:
        runs = groups[label]
        reference_deg = wrap_deg(90 + rz_deg)
        for visit, depth in enumerate(DEPTHS):
            medians = np.asarray([np.median(run["visits"][visit][:, 1:], axis=0)
                                  for run in runs])
            mean = medians.mean(axis=0)
            angle = math.degrees(math.atan2(mean[1], mean[0]))
            each_bias = [wrap_deg(math.degrees(math.atan2(v[1], v[0])) - reference_deg)
                         for v in medians]
            angle_rows.append({
                "group": label, "posture": posture, "command_depth_mm": float(depth),
                "command_z_mm": float(40 - depth), "reference_angle_deg": reference_deg,
                "repeat_1_dBx_uT": medians[0, 0], "repeat_1_dBy_uT": medians[0, 1],
                "repeat_1_bias_deg": each_bias[0],
                "repeat_2_dBx_uT": medians[1, 0], "repeat_2_dBy_uT": medians[1, 1],
                "repeat_2_bias_deg": each_bias[1],
                "equal_run_mean_dBx_uT": mean[0], "equal_run_mean_dBy_uT": mean[1],
                "angle_from_positive_Bx_deg": angle,
                "bias_from_Rz_rotated_positive_By_deg": wrap_deg(angle-reference_deg),
            })
        # Representative middle depth: 9.143 mm. Each 10 mm bin contains
        # 50 control-linked samples per run; summarize each run first.
        visit = 3
        for left in range(30, 170, 10):
            medians = []
            for run in runs:
                data = run["visits"][visit]
                selected = data[(data[:, 0] >= left) & (data[:, 0] < left + 10), 1:]
                if len(selected) != 50:
                    raise ValueError(f"incomplete spatial bin: {run['folder']} {left}")
                medians.append(np.median(selected, axis=0))
            mean = np.mean(medians, axis=0)
            spatial_rows.append({"group": label, "command_depth_mm": DEPTHS[visit],
                                 "command_x_mid_mm": left + 5,
                                 "repeat_1_dBx_uT": medians[0][0],
                                 "repeat_1_dBy_uT": medians[0][1],
                                 "repeat_2_dBx_uT": medians[1][0],
                                 "repeat_2_dBy_uT": medians[1][1],
                                 "equal_run_mean_dBx_uT": mean[0],
                                 "equal_run_mean_dBy_uT": mean[1]})
    return angle_rows, spatial_rows


def plot_components(rows: list[dict], output: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(12.5, 8), sharex=True, sharey=True,
                             layout="constrained")
    for ax, (label, _, posture, _) in zip(axes.flat, GROUPS):
        group = [row for row in rows if row["group"] == label]
        x = [row["command_x_mid_mm"] for row in group]
        for component, color in (("dBx", "#2864a0"), ("dBy", "#dc7528")):
            for repeat in (1, 2):
                ax.plot(x, [row[f"repeat_{repeat}_{component}_uT"] for row in group],
                        color=color, alpha=.30, linewidth=1)
            ax.plot(x, [row[f"equal_run_mean_{component}_uT"] for row in group],
                    color=color, linewidth=2.2, label="ΔBx" if component == "dBx" else "ΔBy")
        ax.axhline(0, color="0.35", linewidth=.8)
        ax.set_title(f"{label} 姿态 · {posture}", loc="left")
        ax.set_xlim(30, 170)
        ax.set_ylim(-230, 230)
        ax.grid(alpha=.2)
    for ax in axes[-1]:
        ax.set_xlabel("命令 +X 行程 (mm)")
    for ax in axes[:, 0]:
        ax.set_ylabel("相对本档基线的磁场变化 (µT)")
    axes[0, 0].legend(loc="upper right", ncol=2, frameon=False)
    fig.suptitle("沿 +X 行进时的 ΔBx 与 ΔBy · 命令压深 9.143 mm", fontsize=15)
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_angles(rows: list[dict], output: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 6), layout="constrained")
    colors = ("#2864a0", "#dc7528", "#7450a2", "#178578")
    for (label, _, _, _), color in zip(GROUPS, colors):
        group = [row for row in rows if row["group"] == label]
        depths = [row["command_depth_mm"] for row in group]
        for repeat in (1, 2):
            ax.plot(depths, [row[f"repeat_{repeat}_bias_deg"] for row in group],
                    color=color, alpha=.35, linewidth=1)
        ax.plot(depths, [row["bias_from_Rz_rotated_positive_By_deg"] for row in group],
                color=color, marker="o", linewidth=2.4, label=label)
    ax.axhline(0, color="0.25", linewidth=1)
    ax.set(xlabel="命令压深 (mm)", ylabel="相对旋转后 +By 参考方向的偏角 (°)",
           xlim=(3.5, 16.5), ylim=(-45, 45))
    ax.grid(alpha=.2)
    ax.legend(title="姿态标签", ncol=4, frameon=False, loc="upper left")
    fig.suptitle("四种姿态的磁向量偏角 · 细线为两次重复，粗线为等权结果", fontsize=15)
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    groups = {}
    source = {}
    for label, stem, _, _ in GROUPS:
        folders = sorted((DAY / "raw").glob(f"*_{stem}_第*次"))
        if len(folders) != 2:
            raise ValueError(f"expected two runs for {label}, got {len(folders)}")
        groups[label] = [load_run(folder) for folder in folders]
        source[label] = [{"folder": str(run["folder"]), "run_id": run["run_id"]}
                         for run in groups[label]]
    angle_rows, spatial_rows = summarize(groups)
    OUT.mkdir(parents=True, exist_ok=True)
    write_csv(OUT / "逐档磁向量偏角.csv", angle_rows)
    write_csv(OUT / "中档沿X分量.csv", spatial_rows)
    plot_components(spatial_rows, OUT / "中档沿X_Bx_By.png")
    plot_angles(angle_rows, OUT / "逐档偏角.png")
    (OUT / "source_and_method.json").write_text(json.dumps({
        "source_runs": source,
        "raw_fields": ["sensor.csv:dBx_uT", "sensor.csv:dBy_uT"],
        "join": "control.jsonl sample_seq to valid sensor.csv sample; 700 distinct samples per run/pass in command X=30–170 mm",
        "angle": "atan2(mean of two run-level median dBy, mean of two run-level median dBx), degrees from sensor +Bx",
        "reference": "Empirical +x group dominant +By direction (90 degrees) rotated by the commanded Rz category: 0/90/180/270 degrees",
        "bias": "wrapped angle minus reference, positive counterclockwise in recorded Bx/By plane",
        "position_limit": "X and Z are commands; no synchronized actual TCP for these runs",
        "coordinate_limit": "No independent sensor-to-TCP/world orientation calibration; angular bias is not a robot heading error",
        "interpretation_limit": "Two repeats; changing brush contact, wetting and sensor mounting may affect components; no causal attribution",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Analyzed 8 completed runs / 64 paths; wrote {OUT}")


if __name__ == "__main__":
    main()
