import json
from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "organize_runs.py"


def _write_json(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def test_apply_groups_run_by_shanghai_date_with_readable_name(tmp_path):
    runs = tmp_path / "runs"
    source = runs / "20260921T121727.485489Z-9f6fd2"
    source.mkdir(parents=True)
    _write_json(source / "manifest.json", {
        "run_id": source.name,
        "started_at": "2026-09-21T12:17:27.485584+00:00",
        "status": "fault",
    })
    _write_json(source / "resolved.json", {
        "name": "z_batch_29p5_to_20",
        "run_label": "repeat_02_part5_rx15_rz90",
    })
    payload = b"original sensor bytes\n"
    (source / "sensor.csv").write_bytes(payload)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(runs), "--apply",
         "--ensure-date", "2026-09-22"],
        text=True, capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    target = (runs / "2026-09-21" /
              "20-17-27__repeat_02_part5_rx15_rz90__9f6fd2")
    assert target.is_dir()
    assert not source.exists()
    assert (target / "sensor.csv").read_bytes() == payload
    assert (runs / "2026-09-22").is_dir()


def test_apply_groups_combined_output_and_repairs_summary_paths(tmp_path):
    runs = tmp_path / "runs"
    run_id = "20260921T121727.485489Z-9f6fd2"
    source_run = runs / run_id
    source_run.mkdir(parents=True)
    _write_json(source_run / "manifest.json", {
        "run_id": run_id,
        "started_at": "2026-09-21T12:17:27.485584+00:00",
        "status": "fault",
    })
    _write_json(source_run / "resolved.json", {"run_label": "part5"})

    combined = runs / "combined" / "20260921_part5_comparison"
    combined.mkdir(parents=True)
    csv_path = combined / "comparison_measurements.csv"
    plot_path = combined / "repeat_comparison_by_z.png"
    csv_path.write_text("source_run_id\n" + run_id + "\n", encoding="utf-8")
    plot_path.write_bytes(b"png bytes")
    _write_json(combined / "summary.json", {
        "source_runs": [f"runs/{run_id}"],
        "csv": str(csv_path.resolve()),
        "plot": str(plot_path.resolve()),
    })
    stamp = datetime(2026, 9, 21, 18, 50, 3,
                     tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
    os.utime(combined, (stamp, stamp))

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(runs), "--apply",
         "--include-combined"],
        text=True, capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    moved_run = runs / "2026-09-21" / "20-17-27__part5__9f6fd2"
    moved_combined = (runs / "combined" / "2026-09-21" /
                      "18-50-03__part5_comparison")
    assert moved_run.is_dir()
    assert moved_combined.is_dir()
    summary = json.loads(
        (moved_combined / "summary.json").read_text(encoding="utf-8"))
    assert summary["source_runs"] == [
        "runs/2026-09-21/20-17-27__part5__9f6fd2"]
    assert summary["csv"] == str(
        (moved_combined / "comparison_measurements.csv").resolve())
    assert summary["plot"] == str(
        (moved_combined / "repeat_comparison_by_z.png").resolve())
