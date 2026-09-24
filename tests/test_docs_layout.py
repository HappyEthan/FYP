"""文档布局检查器的行为测试。"""

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER = REPO_ROOT / "scripts" / "check_docs_layout.py"


def _run_checker(repo_root):
    return subprocess.run(
        [sys.executable, str(CHECKER), "--root", str(repo_root)],
        capture_output=True,
        text=True,
        check=False,
    )


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _frontmatter(project, status="draft"):
    return (
        "---\n"
        f"project: {project}\n"
        f"status: {status}\n"
        "---\n\n"
        "# 测试文档\n"
    )


def test_accepts_new_local_document_with_matching_metadata(tmp_path):
    _write(
        tmp_path / "docs" / "01-monitor-filter" / "design" / "new-design.md",
        _frontmatter("01-monitor-filter"),
    )

    result = _run_checker(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "文档布局检查通过" in result.stdout


def test_rejects_new_document_without_metadata(tmp_path):
    _write(
        tmp_path / "docs" / "02-strokeplan" / "generation" / "new-plan.md",
        "# 没有元信息\n",
    )

    result = _run_checker(tmp_path)

    assert result.returncode == 1
    assert "缺少 YAML 元信息" in result.stdout


def test_rejects_project_metadata_that_disagrees_with_folder(tmp_path):
    _write(
        tmp_path / "docs" / "04-robot-control" / "wrong.md",
        _frontmatter("03-transformer"),
    )

    result = _run_checker(tmp_path)

    assert result.returncode == 1
    assert "project 应为 04-robot-control" in result.stdout


def test_rejects_obsolete_sync_directory(tmp_path):
    _write(
        tmp_path / "docs" / "同步" / "02-strokeplan" / "contract.md",
        _frontmatter("02-strokeplan", status="stable"),
    )

    result = _run_checker(tmp_path)

    assert result.returncode == 1
    assert "不允许的 docs 顶层目录" in result.stdout


def test_rejects_obsolete_sync_metadata(tmp_path):
    _write(
        tmp_path / "docs" / "05-data-acquisition" / "protocol" / "capture.md",
        _frontmatter("05-data-acquisition").replace("status: draft\n", "status: draft\nsync: local\n"),
    )

    result = _run_checker(tmp_path)

    assert result.returncode == 1
    assert "已废弃 sync 元信息" in result.stdout


def test_rejects_loose_document_at_docs_root(tmp_path):
    _write(tmp_path / "docs" / "new-note.md", _frontmatter("shared"))

    result = _run_checker(tmp_path)

    assert result.returncode == 1
    assert "docs 顶层不允许" in result.stdout


def test_rejects_legacy_archive_directory(tmp_path):
    _write(
        tmp_path / "docs" / "archive" / "old.md",
        _frontmatter("shared", status="archived"),
    )

    result = _run_checker(tmp_path)

    assert result.returncode == 1
    assert "不允许的 docs 顶层目录" in result.stdout


def test_grandfathers_existing_document_from_allowlist(tmp_path):
    legacy_doc = tmp_path / "docs" / "03-transformer" / "design" / "legacy.md"
    _write(legacy_doc, "# 历史文档没有元信息\n")
    _write(
        tmp_path / "docs" / "其他" / "history" / "legacy-document-allowlist.txt",
        "docs/03-transformer/design/legacy.md\n",
    )

    result = _run_checker(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr


def test_rejects_unknown_status_value(tmp_path):
    _write(
        tmp_path / "docs" / "06-mujoco-simulation-platform" / "models" / "model.md",
        _frontmatter("06-mujoco-simulation-platform", status="finished"),
    )

    result = _run_checker(tmp_path)

    assert result.returncode == 1
    assert "status 值无效" in result.stdout


def test_rejects_markdown_inside_assets(tmp_path):
    _write(tmp_path / "docs" / "assets" / "misplaced.md", "# 放错位置\n")

    result = _run_checker(tmp_path)

    assert result.returncode == 1
    assert "assets 目录不能存放 Markdown 文档" in result.stdout


def test_accepts_image_to_strokeplan_baseline_document(tmp_path):
    _write(
        tmp_path
        / "docs"
        / "07-image-to-strokeplan-baseline"
        / "template-migration"
        / "baseline.md",
        _frontmatter("07-image-to-strokeplan-baseline"),
    )

    result = _run_checker(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr


def test_accepts_system_evaluation_document(tmp_path):
    _write(
        tmp_path
        / "docs"
        / "08-system-evaluation"
        / "ablations"
        / "open-vs-closed-loop.md",
        _frontmatter("08-system-evaluation"),
    )

    result = _run_checker(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr


def test_accepts_other_document_with_other_metadata(tmp_path):
    _write(
        tmp_path / "docs" / "其他" / "architecture" / "system-map.md",
        _frontmatter("other"),
    )

    result = _run_checker(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr


def test_rejects_other_document_with_project_owner(tmp_path):
    _write(
        tmp_path / "docs" / "其他" / "references" / "misclassified.md",
        _frontmatter("01-monitor-filter"),
    )

    result = _run_checker(tmp_path)

    assert result.returncode == 1
    assert "project 应为 other" in result.stdout


def test_rejects_any_file_left_in_tmp(tmp_path):
    _write(tmp_path / "docs" / "tmp" / "incoming" / "figure.png", "not-an-image")

    result = _run_checker(tmp_path)

    assert result.returncode == 1
    assert "tmp 临时目录必须为空" in result.stdout


def test_rejects_shared_directory(tmp_path):
    _write(
        tmp_path / "docs" / "shared" / "architecture" / "old-policy.md",
        _frontmatter("shared"),
    )

    result = _run_checker(tmp_path)

    assert result.returncode == 1
    assert "不允许的 docs 顶层目录" in result.stdout


def test_rejects_file_at_assets_root(tmp_path):
    _write(tmp_path / "docs" / "assets" / "loose.png", "not-an-image")

    result = _run_checker(tmp_path)

    assert result.returncode == 1
    assert "assets 根目录不能直接存放文件" in result.stdout


def test_rejects_unknown_asset_owner_directory(tmp_path):
    _write(tmp_path / "docs" / "assets" / "misc" / "figure.png", "not-an-image")

    result = _run_checker(tmp_path)

    assert result.returncode == 1
    assert "assets 所有者目录无效：misc" in result.stdout


def test_accepts_resource_under_project_asset_directory(tmp_path):
    _write(
        tmp_path / "docs" / "assets" / "04-robot-control" / "figure.png",
        "not-an-image",
    )

    result = _run_checker(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr


def test_accepts_resource_under_other_asset_directory(tmp_path):
    _write(tmp_path / "docs" / "assets" / "other" / "reference.pdf", "not-a-pdf")

    result = _run_checker(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr


def test_rejects_markdown_nested_inside_assets(tmp_path):
    _write(
        tmp_path
        / "docs"
        / "assets"
        / "02-strokeplan"
        / "generated"
        / "notes.md",
        _frontmatter("02-strokeplan"),
    )

    result = _run_checker(tmp_path)

    assert result.returncode == 1
    assert "assets 目录不能存放 Markdown 文档" in result.stdout
