#!/usr/bin/env python3
"""按上海本地日期和可读标签整理实验 run；默认只预览，不移动。"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
from zoneinfo import ZoneInfo


RUN_ID_RE = re.compile(
    r"^(?P<stamp>\d{8}T\d{6}\.\d{6}Z)-(?P<short>[0-9a-f]{6})$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SHANGHAI = ZoneInfo("Asia/Shanghai")


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _safe_brief(value: object) -> str:
    text = str(value or "run").strip()
    text = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "-", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-._")
    return text[:80] or "run"


def _fingerprint(folder: Path) -> dict[str, tuple[int, str]]:
    result = {}
    for path in sorted(item for item in folder.rglob("*") if item.is_file()):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        result[str(path.relative_to(folder))] = (path.stat().st_size, digest)
    return result


def _run_destination(root: Path, source: Path) -> Path:
    match = RUN_ID_RE.fullmatch(source.name)
    if match is None:
        raise ValueError(f"not a run id: {source.name}")
    manifest = _read_json(source / "manifest.json")
    if manifest.get("status") == "running":
        raise ValueError(f"refusing to move running run: {source.name}")
    started_at = datetime.fromisoformat(str(manifest["started_at"]))
    if started_at.tzinfo is None:
        raise ValueError(f"started_at lacks timezone: {source.name}")
    local = started_at.astimezone(SHANGHAI)
    resolved_path = source / "resolved.json"
    resolved = _read_json(resolved_path) if resolved_path.exists() else {}
    brief = _safe_brief(resolved.get("run_label") or resolved.get("name"))
    name = f"{local:%H-%M-%S}__{brief}__{match.group('short')}"
    return root / f"{local:%Y-%m-%d}" / name


def _plan_run_moves(root: Path, selected_dates: set[str]) -> list[tuple[Path, Path]]:
    moves = []
    for source in sorted(root.iterdir()):
        if not source.is_dir() or RUN_ID_RE.fullmatch(source.name) is None:
            continue
        target = _run_destination(root, source)
        if selected_dates and target.parent.name not in selected_dates:
            continue
        moves.append((source, target))
    targets = [target for _, target in moves]
    if len(targets) != len(set(targets)):
        raise ValueError("multiple runs resolve to the same destination")
    conflicts = [target for target in targets if target.exists()]
    if conflicts:
        raise FileExistsError("destination already exists: " + str(conflicts[0]))
    return moves


def _plan_combined_moves(
        root: Path, selected_dates: set[str]) -> list[tuple[Path, Path]]:
    combined_root = root / "combined"
    if not combined_root.is_dir():
        return []
    moves = []
    for source in sorted(combined_root.iterdir()):
        if not source.is_dir() or DATE_RE.fullmatch(source.name):
            continue
        local = datetime.fromtimestamp(source.stat().st_mtime, SHANGHAI)
        if selected_dates and f"{local:%Y-%m-%d}" not in selected_dates:
            continue
        brief = re.sub(r"^\d{8}_", "", source.name)
        target = (combined_root / f"{local:%Y-%m-%d}" /
                  f"{local:%H-%M-%S}__{_safe_brief(brief)}")
        moves.append((source, target))
    targets = [target for _, target in moves]
    if len(targets) != len(set(targets)):
        raise ValueError("multiple combined outputs resolve to the same destination")
    conflicts = [target for target in targets if target.exists()]
    if conflicts:
        raise FileExistsError("destination already exists: " + str(conflicts[0]))
    return moves


def _move_verified(source: Path, target: Path) -> None:
    before = _fingerprint(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    after = _fingerprint(target)
    if after != before:
        if not source.exists():
            shutil.move(str(target), str(source))
        raise RuntimeError(f"verification failed after moving {source.name}")


def _repair_combined_summary(
        root: Path, target: Path, run_moves: list[tuple[Path, Path]]) -> None:
    summary_path = target / "summary.json"
    if not summary_path.exists():
        return
    summary = _read_json(summary_path)
    by_run_id = {source.name: destination for source, destination in run_moves}
    repaired_sources = []
    for value in summary.get("source_runs", []):
        run_id = Path(str(value)).name
        destination = by_run_id.get(run_id)
        if destination is None:
            repaired_sources.append(value)
        else:
            repaired_sources.append(
                str(Path(root.name) / destination.relative_to(root)))
    if "source_runs" in summary:
        summary["source_runs"] = repaired_sources
    for key in ("csv", "plot"):
        if key in summary:
            summary[key] = str((target / Path(str(summary[key])).name).resolve())
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="按上海本地日期整理 run；默认 dry-run，传 --apply 才移动")
    parser.add_argument("root", nargs="?", default="runs", help="runs 根目录")
    parser.add_argument("--date", action="append", default=[],
                        help="只整理指定本地日期 YYYY-MM-DD；可重复")
    parser.add_argument("--ensure-date", action="append", default=[],
                        help="确保日期目录存在；可重复")
    parser.add_argument("--include-combined", action="store_true",
                        help="同时整理 runs/combined 下的输出并修复 summary 路径")
    parser.add_argument("--apply", action="store_true", help="实际执行移动")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    selected_dates = set(args.date)
    requested_dates = selected_dates | set(args.ensure_date)
    invalid = sorted(date for date in requested_dates if DATE_RE.fullmatch(date) is None)
    if invalid:
        parser.error("invalid date: " + invalid[0])

    try:
        moves = _plan_run_moves(root, selected_dates)
        combined_moves = (
            _plan_combined_moves(root, selected_dates)
            if args.include_combined else [])
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"无法整理: {exc}", file=sys.stderr)
        return 2

    mode = "MOVE" if args.apply else "DRY-RUN"
    for source, target in moves:
        print(f"{mode}: {source.name} -> {target.relative_to(root)}")
    for source, target in combined_moves:
        print(f"{mode}: combined/{source.name} -> {target.relative_to(root)}")
    for date in sorted(requested_dates):
        print(f"{mode}: ensure {date}/")

    if not args.apply:
        print("预览完成：{} 个 run，{} 个合并输出；未修改文件。".format(
            len(moves), len(combined_moves)))
        return 0

    try:
        for date in sorted(requested_dates):
            (root / date).mkdir(parents=True, exist_ok=True)
        for source, target in moves:
            _move_verified(source, target)
        for source, target in combined_moves:
            _move_verified(source, target)
            _repair_combined_summary(root, target, moves)
    except OSError as exc:
        print(f"整理失败: {exc}", file=sys.stderr)
        return 2
    print("整理完成：{} 个 run，{} 个合并输出。".format(
        len(moves), len(combined_moves)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
