import importlib.util
import json
import pathlib
import re

import numpy as np
import pytest

from brushbot.monitor.recorder import Recorder


def _load_analyze_module():
    path = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "analyze_deltab.py"
    spec = importlib.util.spec_from_file_location("analyze_deltab", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_simple_recorder_has_unique_name_and_no_action_metadata(tmp_path):
    rec = Recorder(str(tmp_path), np.zeros(3), {"name": "serial"})
    rec.add(10.0, [1.0, 2.0, 3.0])
    csv_path, json_path = map(pathlib.Path, rec.finish())
    meta = json.loads(json_path.read_text(encoding="utf-8"))
    assert csv_path.stem == json_path.stem
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_\d{6}",
        csv_path.stem,
    )
    assert meta["sample_count"] == 1
    for key in (
        "action", "repetition", "action_window_s",
        "action_start_t_us", "action_end_t_us",
    ):
        assert key not in meta


def test_two_simple_recordings_never_overwrite(tmp_path):
    paths = []
    for value in (1.0, 2.0):
        rec = Recorder(str(tmp_path), np.zeros(3), {"name": "serial"})
        rec.add(0.0, [value, 0.0, 0.0])
        paths.append(rec.finish()[0])
    assert paths[0] != paths[1]


def test_recorder_roundtrip_readable_by_analyzer(tmp_path):
    b0 = np.array([10.0, 20.0, 30.0])
    d_b = np.array([
        [1.0, 2.0, 3.0], [4.0, 5.0, 6.0],
        [7.0, 8.0, 9.0], [0.0, 0.0, 0.0],
    ])
    rec = Recorder(str(tmp_path), b0, {"name": "serial", "port": "/dev/fake"})
    for index, row in enumerate(d_b):
        rec.add(index / 100.0, row)
    csv_path, json_path = rec.finish()

    got = _load_analyze_module().load(str(tmp_path))[0]
    assert got["action"] == pathlib.Path(csv_path).stem
    assert got["win"] is None
    np.testing.assert_allclose(got["B"], d_b)
    np.testing.assert_allclose(got["B0"], b0)
    meta = json.loads(pathlib.Path(json_path).read_text(encoding="utf-8"))
    assert meta["delta_definition"] == "dB = B - B0"
    assert meta["recording_mode"] == "manual_start_stop"


def test_recorder_marks_bad_frame_without_replacing_raw_value(tmp_path):
    b0 = np.array([30.0, -1030.0, -4200.0])
    rec = Recorder(str(tmp_path), b0, {"name": "serial"})
    rows = np.array([
        [0.0, 0.0, 0.0], [46.65, 1029.85, 4199.758], [1.0, 2.0, 3.0],
    ])
    for index, row in enumerate(rows):
        rec.add(index * .003, row)
    csv_path, json_path = rec.finish()
    data = np.genfromtxt(csv_path, delimiter=",", names=True)
    assert np.atleast_1d(data["sample_valid"]).tolist() == [1.0, 0.0, 1.0]
    np.testing.assert_allclose(
        [data["dBx_uT"][1], data["dBy_uT"][1], data["dBz_uT"][1]], rows[1])
    meta = json.loads(pathlib.Path(json_path).read_text(encoding="utf-8"))
    assert meta["invalid_sample_count"] == 1


def test_recorder_verify_returns_true_for_own_output(tmp_path):
    rec = Recorder(str(tmp_path), np.zeros(3), {"name": "array"})
    rec.add(0.0, [1.0, 2.0, 3.0])
    csv_path, _ = rec.finish()
    assert rec.verify(csv_path) is True


def test_recorder_invalid_run_is_skipped_by_analyzer(tmp_path):
    rec = Recorder(str(tmp_path), np.zeros(3), {"name": "serial"})
    rec.add(0.0, [1.0, 1.0, 1.0])
    rec.finish(valid=False, note="串口断开")
    assert _load_analyze_module().load(str(tmp_path)) == []


def test_recorder_refuses_empty(tmp_path):
    rec = Recorder(str(tmp_path), np.zeros(3), {"name": "array"})
    with pytest.raises(ValueError):
        rec.finish()
