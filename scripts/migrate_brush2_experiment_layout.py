#!/usr/bin/env python3
"""One-time, offline migration from date/combined to date/experiment/{raw,analysis}.

Dry-run by default. --apply renames only existing directories/files and refuses
collisions. Original run file bytes are never edited.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRUSH = ROOT / "runs/brush2"
GROUPS = {
    "ff": "01_四目标纯前馈",
    "p": "02_P反馈与增益扫描",
    "limits": "03_P2修正上限",
    "ladder": "01_四方向阶梯实验",
}
TARGETS = {
    "01_gradual_press": "渐进压笔",
    "02_single_arch": "单拱",
    "03_double_wave": "双波",
    "04_smooth_levels_wide_transitions": "宽过渡",
}
ORIENTATIONS = {
    "brush2_full_ry15": "姿态Ry正15",
    "brush2_full_rx15_rz90": "姿态Rx正15_Rz90",
    "brush2_full_ry-15_rz180": "姿态Ry负15_Rz180",
    "brush2_full_rx-15_rz270": "姿态Rx负15_Rz270",
}


def number(value: float) -> str:
    return f"{float(value):g}".replace(".", "p")


def run_info(folder: Path) -> dict:
    manifest = json.loads((folder / "manifest.json").read_text())
    resolved = json.loads((folder / "resolved.json").read_text())
    if manifest["status"] != "completed":
        raise ValueError(f"unexpected non-completed run: {folder}")
    for name, digest in manifest["sha256"].items():
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"snapshot mismatch: {folder / name}")
    return {"folder": folder, "manifest": manifest, "resolved": resolved}


def target_name(label: str) -> tuple[str, str]:
    for stem, display in TARGETS.items():
        if label.endswith(stem):
            return stem, display
    raise ValueError(f"unknown target: {label}")


def build_run_moves() -> tuple[list[tuple[Path, Path]], dict[str, dict]]:
    moves = []
    by_short_id = {}
    for day in ("2026-09-23", "2026-09-24"):
        folders = sorted(p for p in (BRUSH / day).iterdir()
                         if p.is_dir() and (p / "manifest.json").exists())
        seen = Counter()
        for folder in folders:
            info = run_info(folder)
            resolved = info["resolved"]
            control = resolved["control"]
            label = resolved["run_label"]
            time = folder.name[:8]
            short_id = folder.name.rsplit("__", 1)[-1]
            if day == "2026-09-23":
                if label not in ORIENTATIONS:
                    raise ValueError(f"unknown ladder orientation: {folder}")
                group = "ladder"
                key = label
                seen[key] += 1
                name = f"{time}_{ORIENTATIONS[label]}_第{seen[key]}次"
                target = None
            else:
                target, display = target_name(label)
                if not control["enabled"]:
                    group = "ff"
                    key = (group, target)
                    seen[key] += 1
                    name = f"{time}_{display}_第{seen[key]}次"
                elif (control["kp"] == 2
                      and (control["max_correction_mm"],
                           control["max_correction_speed_mm_s"],
                           control["max_correction_accel_mm_s2"]) != (.2, 2., 40.)):
                    group = "limits"
                    profile = (control["max_correction_mm"],
                               control["max_correction_speed_mm_s"],
                               control["max_correction_accel_mm_s2"])
                    key = (group, profile)
                    seen[key] += 1
                    suffix = f"_第{seen[key]}次"
                    name = (f"{time}_{display}_P2_修正{number(profile[0])}mm_"
                            f"速度{number(profile[1])}_加速度{number(profile[2])}{suffix}")
                else:
                    group = "p"
                    key = (group, target, control["kp"])
                    seen[key] += 1
                    suffix = f"_第{seen[key]}次"
                    name = f"{time}_{display}_P{number(control['kp'])}{suffix}"
            destination = BRUSH / day / GROUPS[group] / "raw" / name
            moves.append((folder, destination))
            by_short_id[short_id] = {"source": folder, "destination": destination,
                                     "day": day, "group": group, "target": target,
                                     "time": time}
    if len(moves) != 35 or len(by_short_id) != 35:
        raise ValueError(f"expected 35 raw runs, got {len(moves)}")
    return moves, by_short_id


def build_analysis_moves() -> list[tuple[Path, Path]]:
    old24 = BRUSH / "combined/2026-09-24"
    new24 = BRUSH / "2026-09-24"
    old23 = BRUSH / "combined/2026-09-23"
    new23 = BRUSH / "2026-09-23" / GROUPS["ladder"] / "analysis"
    mapping = {
        "strokeplan_tracking_8": ("ff", "四目标跟随"),
        # Historical migration map. The two intermediate copies were pruned
        # afterward; v3 was renamed to P反馈命令边界回放.
        "strokeplan_feedback_shadow_8_v1": ("ff", "反馈影子回放_版本1"),
        "strokeplan_feedback_shadow_8_v2": ("ff", "反馈影子回放_版本2"),
        "strokeplan_feedback_shadow_8_v3": ("ff", "反馈影子回放_版本3"),
        "strokeplan_p_tracking_8": ("p", "四目标P跟随"),
        "strokeplan_p_gain_selected_04": ("p", "P增益扫描"),
        "strokeplan_p_limits_04": ("limits", "历史限幅对比"),
        "strokeplan_p_limits_selected_04": ("limits", "修正上限精选"),
    }
    moves = [(old24 / name, new24 / GROUPS[group] / "analysis" / dest)
             for name, (group, dest) in mapping.items()]
    moves += [(old24 / name, new24 / GROUPS["limits"] / "analysis" / dest)
              for name, dest in (
                  ("cleanup_proposal_1542_1730.json", "清理记录.json"),
                  ("data_inventory_1542_1730.csv", "清理前逐笔索引.csv"),
                  ("retired_run_10f17a_summary.json", "已清理实验摘要.json"),
              )]
    moves += [(old23 / name, new23 / dest)
              for name, dest in (
                  ("+x", "正X方向"), ("+y", "正Y方向"),
                  ("-x", "负X方向"), ("-y", "负Y方向"),
                  ("four_directions", "四方向汇总"),
              )]
    moves.append((BRUSH / "combined/2026-09-25/tracking_diagnosis_v1/diagnosis.json",
                  new24 / "跨实验跟随诊断_2026-09-25.json"))
    return moves


def add_file_renames(analysis_moves: list[tuple[Path, Path]],
                     runs: dict[str, dict]) -> list[tuple[Path, Path]]:
    changes = []
    for source, destination in analysis_moves:
        if source.name in ("strokeplan_tracking_8", "strokeplan_p_tracking_8"):
            for png in source.glob("*__repeat_*__*.png"):
                stem, repeat, short_id = png.stem.split("__")
                if short_id not in runs:
                    raise ValueError(f"unknown chart run: {png}")
                display = TARGETS[stem]
                changes.append((destination / png.name,
                                destination / f"{display}_第{repeat.split('_')[-1]}次.png"))
        elif source.name.startswith("strokeplan_feedback_shadow_8_v"):
            for csv_path in source.glob("*.csv"):
                short_id = csv_path.stem.rsplit("__", 1)[-1]
                changes.append((destination / csv_path.name,
                                destination / (runs[short_id]["destination"].name + ".csv")))
        elif source.name == "strokeplan_p_limits_04":
            changes.extend([
                (destination / "10f17a-repeat-142be8.png",
                 destination / "修正0p30_两次高响应对比.png"),
                (destination / "68defd_vs_69395a_actual_tcp.png",
                 destination / "修正0p40_首次与实际TCP复验.png"),
            ])
    return changes


def check_moves(moves: list[tuple[Path, Path]]) -> None:
    sources = [source for source, _ in moves]
    destinations = [destination for _, destination in moves]
    if len(set(sources)) != len(sources) or len(set(destinations)) != len(destinations):
        raise ValueError("duplicate source or destination")
    for source, destination in moves:
        if not source.exists():
            raise ValueError(f"missing source: {source}")
        if destination.exists():
            raise ValueError(f"destination already exists: {destination}")


def check_analysis_coverage(moves: list[tuple[Path, Path]],
                            renames: list[tuple[Path, Path]]) -> None:
    combined = BRUSH / "combined"
    source_dirs = [source for source, _ in moves if source.is_dir() and combined in source.parents]
    source_files = [source for source, _ in moves if source.is_file() and combined in source.parents]
    uncovered = [path for path in combined.rglob("*") if path.is_file()
                 and path not in source_files
                 and not any(folder in path.parents for folder in source_dirs)]
    if uncovered:
        raise ValueError(f"unplanned combined files: {uncovered}")
    destinations = [new for _, new in renames]
    if len(destinations) != len(set(destinations)):
        raise ValueError("duplicate chart/csv destination")


def replace_paths(moves: list[tuple[Path, Path]]) -> None:
    """Rewrite paths in derived text only, after all moves are complete."""
    replacements = []
    for old, new in moves:
        replacements.append((str(old.resolve()), str(new.resolve())))
        replacements.append((str(old.relative_to(ROOT)), str(new.relative_to(ROOT))))
    replacements.sort(key=lambda pair: len(pair[0]), reverse=True)
    analysis_files = []
    for day in ("2026-09-23", "2026-09-24"):
        for path in (BRUSH / day).rglob("*"):
            if path.is_file() and "analysis" in path.parts and path.suffix in {".json", ".csv", ".md", ".py"}:
                analysis_files.append(path)
    analysis_files.append(BRUSH / "2026-09-24/跨实验跟随诊断_2026-09-25.json")
    analysis_files.extend((ROOT / "docs/04-robot-control").rglob("*.md"))
    for path in analysis_files:
        original = path.read_text(encoding="utf-8")
        changed = original
        for old, new in replacements:
            changed = changed.replace(old, new)
        if changed != original:
            path.write_text(changed, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="perform verified moves")
    args = parser.parse_args()
    run_moves, runs = build_run_moves()
    analysis_moves = build_analysis_moves()
    check_moves(run_moves + analysis_moves)
    renames = add_file_renames(analysis_moves, runs)
    check_analysis_coverage(analysis_moves, renames)
    print(f"raw runs: {len(run_moves)}; analysis entries: {len(analysis_moves)}; chart/csv renames: {len(renames)}")
    for old, new in run_moves + analysis_moves:
        print(f"{old.relative_to(ROOT)} -> {new.relative_to(ROOT)}")
    if not args.apply:
        return
    audit = [{"old": str(old.relative_to(ROOT)), "new": str(new.relative_to(ROOT))}
             for old, new in run_moves + analysis_moves + renames]
    for source, destination in run_moves + analysis_moves:
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
    for source, destination in renames:
        if not source.exists() or destination.exists():
            raise ValueError(f"unsafe chart rename: {source} -> {destination}")
        source.rename(destination)
    replace_paths(run_moves + analysis_moves + renames)
    (BRUSH / "2026-09-24/.migration_paths.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    for path in (BRUSH / "combined/2026-09-25/tracking_diagnosis_v1",
                 BRUSH / "combined/2026-09-25", BRUSH / "combined/2026-09-24",
                 BRUSH / "combined/2026-09-23", BRUSH / "combined"):
        path.rmdir()
    print("migration completed")


if __name__ == "__main__":
    main()
