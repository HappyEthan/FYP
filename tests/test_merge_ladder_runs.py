import csv
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_script():
    path = ROOT / "scripts" / "merge_ladder_runs.py"
    spec = importlib.util.spec_from_file_location("merge_ladder_runs", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_completed_run(folder, run_id, label, offset):
    folder.mkdir()
    (folder / "manifest.json").write_text(json.dumps({
        "run_id": run_id, "status": "completed",
    }), encoding="utf-8")
    (folder / "resolved.json").write_text(json.dumps({
        "run_label": label,
        "path": {"axis": "+x", "travel_mm": 200.0, "order": "one_way"},
        "motion": {"speed_mm_s": 10.0},
    }), encoding="utf-8")
    sensors = []
    controls = []
    for visit, z_mm in enumerate((27.0, 25.0, 23.0)):
        for point, x_mm in enumerate((0.0, 100.0, 200.0)):
            seq = visit * 3 + point + 1
            sensors.append({
                "seq": seq, "dBx_uT": offset + visit * 10 + point,
                "dBy_uT": 0.0, "baseline_id": visit // 2, "valid": "true",
            })
            controls.append({
                "phase": f"measure_{visit:02d}", "sample_seq": seq,
                "x_cmd_m": (-300.0 + x_mm) / 1000.0,
                "y_cmd_m": 0.5, "z_cmd_m": z_mm / 1000.0,
            })
    with (folder / "sensor.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(sensors[0]))
        writer.writeheader()
        writer.writerows(sensors)
    with (folder / "control.jsonl").open("w", encoding="utf-8") as handle:
        for row in controls:
            handle.write(json.dumps(row) + "\n")
    return folder


def test_merge_preserves_run_identity_and_combines_matching_repeats(tmp_path):
    script = _load_script()
    run_a = _write_completed_run(tmp_path / "run-a", "run-a", "repeat_01", 0.0)
    run_b = _write_completed_run(tmp_path / "run-b", "run-b", "repeat_02", 2.0)

    result = script.merge_ladder_runs([run_a, run_b], tmp_path / "combined")

    assert result["rows"] == 18
    assert result["z_mm"] == pytest.approx([23.0, 25.0, 27.0])
    with Path(result["csv"]).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["source_run_id"] for row in rows} == {"run-a", "run-b"}
    assert {row["run_label"] for row in rows} == {"repeat_01", "repeat_02"}
    assert {float(row["travel_mm"]) for row in rows} == {0.0, 100.0, 200.0}
    assert Path(result["plot"]).is_file()


def test_merge_rejects_incomplete_or_incompatible_runs(tmp_path):
    script = _load_script()
    run_a = _write_completed_run(tmp_path / "run-a", "run-a", "repeat_01", 0.0)
    run_b = _write_completed_run(tmp_path / "run-b", "run-b", "repeat_02", 2.0)
    manifest = json.loads((run_b / "manifest.json").read_text(encoding="utf-8"))
    manifest["status"] = "aborted"
    (run_b / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="completed"):
        script.merge_ladder_runs([run_a, run_b], tmp_path / "combined")

    manifest["status"] = "completed"
    (run_b / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    resolved = json.loads((run_b / "resolved.json").read_text(encoding="utf-8"))
    resolved["path"]["travel_mm"] = 150.0
    (run_b / "resolved.json").write_text(json.dumps(resolved), encoding="utf-8")
    with pytest.raises(ValueError, match="incompatible"):
        script.merge_ladder_runs([run_a, run_b], tmp_path / "combined")


def test_stitch_accepts_fault_run_and_keeps_only_complete_measure_paths(tmp_path):
    script = _load_script()
    run_a = _write_completed_run(tmp_path / "run-a", "run-a", "part1", 0.0)
    run_b = _write_completed_run(tmp_path / "run-b", "run-b", "part2", 2.0)

    manifest = json.loads((run_a / "manifest.json").read_text(encoding="utf-8"))
    manifest["status"] = "fault"
    (run_a / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    controls = [json.loads(line) for line in
                (run_a / "control.jsonl").read_text(encoding="utf-8").splitlines()]
    controls = [row for row in controls
                if not (row["phase"] == "measure_02" and row["x_cmd_m"] > -0.2)]
    (run_a / "control.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in controls), encoding="utf-8")

    for row in [json.loads(line) for line in
                (run_b / "control.jsonl").read_text(encoding="utf-8").splitlines()]:
        row["z_cmd_m"] -= 0.0015
        row.setdefault("_rewritten", True)
        with (run_b / "rewritten.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
    (run_b / "control.jsonl").write_text(
        (run_b / "rewritten.jsonl").read_text(encoding="utf-8"), encoding="utf-8")

    result = script.stitch_ladder_runs([run_a, run_b], tmp_path / "stitched")

    assert result["rows"] == 15
    assert result["included_paths"] == 5
    assert result["excluded_incomplete_paths"] == [{
        "source_run_id": "run-a", "run_label": "part1", "visit": 2,
        "z_mm": pytest.approx(23.0), "max_travel_mm": pytest.approx(100.0),
    }]
    assert result["z_mm"] == pytest.approx([21.5, 23.5, 25.0, 25.5, 27.0])
    assert Path(result["csv"]).is_file()
    assert Path(result["plot"]).is_file()


def test_compare_repeats_builds_one_panel_per_z_and_summary(tmp_path):
    script = _load_script()
    runs = [
        _write_completed_run(
            tmp_path / f"run-{index}", f"run-{index}",
            f"repeat_02_part{index}", float(index))
        for index in (2, 3, 4)
    ]

    result = script.compare_ladder_repeats(runs, tmp_path / "comparison")

    assert result["mode"] == "repeat_comparison"
    assert result["repeat_labels"] == [
        "repeat_02_part2", "repeat_02_part3", "repeat_02_part4"]
    assert result["z_mm"] == pytest.approx([23.0, 25.0, 27.0])
    assert result["rows"] == 27
    assert Path(result["csv"]).is_file()
    assert Path(result["plot"]).is_file()
