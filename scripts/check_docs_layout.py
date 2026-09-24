#!/usr/bin/env python3
"""检查 docs 文档的项目归属、元信息和目录布局。"""

import argparse
from pathlib import Path


PROJECTS = (
    "01-monitor-filter",
    "02-strokeplan",
    "03-transformer",
    "04-robot-control",
    "05-data-acquisition",
    "06-mujoco-simulation-platform",
    "07-image-to-strokeplan-baseline",
    "08-system-evaluation",
)
ASSET_OWNERS = {*PROJECTS, "other"}
ALLOWED_TOP_LEVEL = {*PROJECTS, "README.md", "assets", "其他", "tmp"}
ALLOWED_STATUS = {"draft", "active", "stable", "archived"}
DEFAULT_ALLOWLIST = Path("docs/其他/history/legacy-document-allowlist.txt")


def _load_allowlist(repo_root, allowlist_path):
    path = allowlist_path if allowlist_path.is_absolute() else repo_root / allowlist_path
    if not path.exists():
        return set()
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def _parse_frontmatter(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return None

    metadata = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return metadata
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip("\"'")
    return None


def _metadata_errors(relative_path, metadata, expected_project):
    errors = []
    if metadata is None:
        return [f"{relative_path}: 缺少 YAML 元信息"]

    for field in ("project", "status"):
        if not metadata.get(field):
            errors.append(f"{relative_path}: 元信息缺少 {field}")

    project = metadata.get("project")
    if project and project != expected_project:
        errors.append(f"{relative_path}: project 应为 {expected_project}，实际为 {project}")

    status = metadata.get("status")
    if status and status not in ALLOWED_STATUS:
        allowed = ", ".join(sorted(ALLOWED_STATUS))
        errors.append(f"{relative_path}: status 值无效：{status}；允许值为 {allowed}")
    if "sync" in metadata:
        errors.append(f"{relative_path}: 已废弃 sync 元信息")
    return errors


def validate_repository(repo_root, allowlist_path=DEFAULT_ALLOWLIST):
    repo_root = Path(repo_root).resolve()
    docs_root = repo_root / "docs"
    if not docs_root.is_dir():
        return ["docs: 目录不存在"]

    errors = []
    for child in sorted(docs_root.iterdir(), key=lambda item: item.name):
        if child.name not in ALLOWED_TOP_LEVEL:
            kind = "目录" if child.is_dir() else "文件"
            errors.append(f"docs/{child.name}: 不允许的 docs 顶层{kind}")
        elif child.is_file() and child.name != "README.md":
            errors.append(f"docs/{child.name}: docs 顶层不允许该文件")

    tmp_root = docs_root / "tmp"
    if tmp_root.is_dir():
        for path in sorted(item for item in tmp_root.rglob("*") if item.is_file()):
            relative = path.relative_to(repo_root).as_posix()
            errors.append(f"{relative}: tmp 临时目录必须为空")

    assets_root = docs_root / "assets"
    if assets_root.is_dir():
        for child in sorted(assets_root.iterdir(), key=lambda item: item.name):
            relative = child.relative_to(repo_root).as_posix()
            if not child.is_dir():
                errors.append(f"{relative}: assets 根目录不能直接存放文件")
            elif child.name not in ASSET_OWNERS:
                errors.append(f"{relative}: assets 所有者目录无效：{child.name}")

    legacy_paths = _load_allowlist(repo_root, Path(allowlist_path))
    for path in sorted(docs_root.rglob("*.md")):
        relative = path.relative_to(repo_root).as_posix()
        parts = path.relative_to(docs_root).parts

        if len(parts) == 1:
            if parts[0] != "README.md":
                errors.append(f"{relative}: docs 顶层不允许新增 Markdown 文档")
            continue

        if parts[0] == "assets":
            errors.append(f"{relative}: assets 目录不能存放 Markdown 文档")
            continue
        if parts[0] not in {*PROJECTS, "其他"}:
            continue
        if relative in legacy_paths:
            continue

        if parts[0] == "其他":
            expected_project = "other"
        else:
            expected_project = parts[0]

        errors.extend(
            _metadata_errors(
                relative,
                _parse_frontmatter(path),
                expected_project,
            )
        )
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="仓库根目录；默认自动使用脚本所在仓库",
    )
    parser.add_argument(
        "--legacy-allowlist",
        type=Path,
        default=DEFAULT_ALLOWLIST,
        help="历史文档白名单路径，可为仓库相对路径或绝对路径",
    )
    args = parser.parse_args(argv)

    errors = validate_repository(args.root, args.legacy_allowlist)
    if errors:
        print("文档布局检查失败：")
        for error in errors:
            print(f"- {error}")
        return 1

    print("文档布局检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
