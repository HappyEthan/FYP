import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from brushbot.experiments.recording import RunRecorder
from brushbot.strokeplan import Stroke, StrokePlan


def test_abort_keeps_rows_and_snapshots(tmp_path):
    recorder = RunRecorder(str(tmp_path), {"experiment": {"version": 1}})
    recorder.write("event", {"phase": "baseline", "host_ns": 10})
    folder = Path(recorder.finish("aborted", "operator_stop"))
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "aborted"
    assert manifest["reason"] == "operator_stop"
    assert (folder / "events.jsonl").read_text(encoding="utf-8").strip()
    assert json.loads((folder / "resolved.json").read_text())["version"] == 1


def test_input_bytes_are_exact_and_snapshot_hashes_are_recorded(tmp_path):
    raw = b'{\n  "version": 1,\n  "name": "unchanged"\n}\n'
    recorder = RunRecorder(str(tmp_path), {
        "input_bytes": raw,
        "experiment": {"version": 1, "name": "unchanged"},
        "setup": {"installation_id": "test"},
        "filter": {"kind": "ema", "alpha": 0.3},
        "adapter": {"path": "/opt/adapter", "version": "abc"},
    })
    folder = Path(recorder.finish("completed"))
    assert (folder / "input.json").read_bytes() == raw
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["sha256"]["input.json"] == hashlib.sha256(raw).hexdigest()
    assert manifest["filter"] == {"kind": "ema", "alpha": 0.3}
    assert manifest["adapter"]["version"] == "abc"


def test_compiled_plan_and_timeline_are_saved(tmp_path):
    stroke = Stroke(
        s=np.array([0.0, 1.0]),
        xy=np.array([[0.1, 0.2], [0.2, 0.2]]),
        g_press=np.array([np.nan, np.nan]),
        z_ff=np.array([0.0, 0.001]),
    )
    compiled = {
        "plan": StrokePlan([stroke], {"control_mode": "off"}),
        "t_s": np.array([0.0, 1.0]),
        "s": np.array([0.0, 1.0]),
        "phase": np.array(["ramp_up", "ramp_down"]),
        "pose_m_rad": np.zeros((2, 6)),
        "g_ref_uT": np.array([np.nan, np.nan]),
        "depth_ff_m": np.array([0.0, 0.001]),
    }
    recorder = RunRecorder(str(tmp_path), {
        "experiment": {"version": 1}, "compiled": compiled,
    })
    folder = Path(recorder.finish("completed"))
    assert StrokePlan.load(folder / "compiled_plan.npz").meta["control_mode"] == "off"
    with np.load(folder / "timeline.npz", allow_pickle=False) as timeline:
        np.testing.assert_array_equal(timeline["phase"], ["ramp_up", "ramp_down"])
        assert np.isnan(timeline["g_ref_uT"]).all()


def test_sensor_stream_is_csv_and_preserves_empty_prebaseline_delta(tmp_path):
    recorder = RunRecorder(str(tmp_path), {"experiment": {"version": 1}})
    recorder.write("sensor", {
        "seq": 1, "sensor_t_us": 12, "host_rx_ns": 34,
        "Bx_uT": 1.0, "By_uT": 2.0, "Bz_uT": 3.0,
        "dBx_uT": None, "dBy_uT": None, "dBz_uT": None,
        "valid": True, "invalid_reason": "",
    })
    folder = Path(recorder.finish("completed"))
    with (folder / "sensor.csv").open(newline="", encoding="utf-8") as handle:
        row = next(csv.DictReader(handle))
    assert row["sensor_t_us"] == "12"
    assert row["dBx_uT"] == ""
    assert row["valid"] == "true"


def test_baseline_metadata_records_first_applicable_sample(tmp_path):
    recorder = RunRecorder(str(tmp_path), {"experiment": {"version": 1}})
    recorder.record_baseline({
        "B0_uT": [10.0, 20.0, 30.0],
        "std_uT": [0.1, 0.1, 0.1],
        "first_seq": 1,
        "last_seq": 100,
    })
    folder = Path(recorder.finish("completed"))
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["baseline"]["B0_uT"] == [10.0, 20.0, 30.0]
    assert manifest["baseline"]["applies_after_seq"] == 100


def test_multiple_baselines_are_kept_in_order_with_effective_visit(tmp_path):
    recorder = RunRecorder(str(tmp_path), {"experiment": {"version": 1}})
    recorder.record_baseline({
        "baseline_id": 0, "B0_uT": [10.0, 20.0, 30.0],
        "first_seq": 1, "last_seq": 3, "effective_visit": 0,
    })
    recorder.record_baseline({
        "baseline_id": 1, "B0_uT": [11.0, 21.0, 31.0],
        "first_seq": 50, "last_seq": 52, "effective_visit": 4,
    })
    folder = Path(recorder.finish("completed"))
    manifest = json.loads((folder / "manifest.json").read_text())

    assert [item["baseline_id"] for item in manifest["baselines"]] == [0, 1]
    assert manifest["baselines"][1]["effective_visit"] == 4
    assert manifest["baselines"][1]["applies_after_seq"] == 52
    assert manifest["baseline"] == manifest["baselines"][0]


def test_json_streams_convert_non_finite_values_to_null(tmp_path):
    recorder = RunRecorder(str(tmp_path), {"experiment": {"version": 1}})
    recorder.write("control", {
        "host_ns": 1,
        "a_raw_uT": float("nan"),
        "actual_pose_available": False,
        "actual_pose_m_rad": None,
    })
    folder = Path(recorder.finish("fault", "sensor_stale"))
    row = json.loads((folder / "control.jsonl").read_text())
    assert row["a_raw_uT"] is None
    assert row["actual_pose_m_rad"] is None


def test_same_second_runs_never_overwrite(tmp_path):
    first = RunRecorder(str(tmp_path), {"experiment": {"version": 1}})
    second = RunRecorder(str(tmp_path), {"experiment": {"version": 1}})
    first_folder = Path(first.finish("completed"))
    second_folder = Path(second.finish("completed"))
    assert first_folder != second_folder
    assert first_folder.exists() and second_folder.exists()


@pytest.mark.parametrize("status", ["completed", "aborted", "fault"])
def test_every_terminal_status_keeps_partial_data(tmp_path, status):
    recorder = RunRecorder(str(tmp_path), {"experiment": {"version": 1}})
    recorder.write("event", {"host_ns": 1, "phase": "test"})
    folder = Path(recorder.finish(status, "reason" if status != "completed" else ""))
    assert folder.exists()
    assert (folder / "events.jsonl").stat().st_size > 0


def test_invalid_stream_or_status_is_rejected(tmp_path):
    recorder = RunRecorder(str(tmp_path), {"experiment": {"version": 1}})
    with pytest.raises(ValueError, match="stream"):
        recorder.write("other", {})
    with pytest.raises(ValueError, match="status"):
        recorder.finish("interrupted")
    recorder.finish("aborted", "test_cleanup")


def test_recording_queue_must_be_bounded(tmp_path):
    with pytest.raises(ValueError, match="queue_size"):
        RunRecorder(str(tmp_path), {"experiment": {"version": 1}}, queue_size=0)


def test_writer_failure_is_reported_as_logger_fault_and_data_is_retained(tmp_path):
    recorder = RunRecorder(str(tmp_path), {"experiment": {"version": 1}})

    def fail_write(_stream, _row):
        raise OSError("disk unavailable")

    recorder._write_item = fail_write
    recorder.write("event", {"host_ns": 1})
    with pytest.raises(RuntimeError, match="logger_fault.*disk unavailable"):
        recorder.finish("completed")
    manifest = json.loads((recorder.run_dir / "manifest.json").read_text())
    assert manifest["status"] == "fault"
    assert recorder.run_dir.exists()


def test_new_recorder_marks_orphaned_running_manifest_interrupted(tmp_path):
    orphan = tmp_path / "old-run"
    orphan.mkdir()
    (orphan / "manifest.json").write_text(json.dumps({
        "run_id": "old-run", "status": "running", "reason": "",
    }))
    recorder = RunRecorder(str(tmp_path), {"experiment": {"version": 1}})
    recovered = json.loads((orphan / "manifest.json").read_text())
    assert recovered["status"] == "interrupted"
    assert recovered["reason"] == "recovered_after_unclean_shutdown"
    recorder.finish("aborted", "test_cleanup")


def test_writer_failure_is_reported_and_manifest_becomes_fault(tmp_path):
    recorder = RunRecorder(str(tmp_path), {"experiment": {"version": 1}})

    def fail(_stream, _row):
        raise OSError("disk full")

    recorder._write_item = fail
    recorder.write("event", {"host_ns": 1})
    with pytest.raises(RuntimeError, match="logger_fault"):
        recorder.finish("completed")
    manifest = json.loads((recorder.run_dir / "manifest.json").read_text())
    assert manifest["status"] == "fault"
    assert "disk full" in manifest["reason"]


def test_new_recorder_marks_stale_running_manifest_interrupted(tmp_path):
    stale = tmp_path / "stale-run"
    stale.mkdir()
    (stale / "manifest.json").write_text(json.dumps({"status": "running"}))
    recorder = RunRecorder(str(tmp_path), {"experiment": {"version": 1}})
    recorder.finish("completed")
    recovered = json.loads((stale / "manifest.json").read_text())
    assert recovered["status"] == "interrupted"
    assert recovered["reason"] == "recovered_after_unclean_shutdown"
