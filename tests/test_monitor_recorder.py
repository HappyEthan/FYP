import importlib.util
import json
import pathlib
import numpy as np
import pytest
from brushbot.monitor.recorder import Recorder, next_repetition


def _load_analyze_module():
    """按路径加载 scripts/analyze_deltab.py(它不是包的一部分)."""
    p = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "analyze_deltab.py"
    spec = importlib.util.spec_from_file_location("analyze_deltab", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_next_repetition_increments(tmp_path):
    assert next_repetition(str(tmp_path), "line_lr") == 1
    (tmp_path / "20260724_120000_line_lr_r01.csv").write_text("x")
    (tmp_path / "20260724_120000_line_lr_r03.csv").write_text("x")
    (tmp_path / "20260724_120000_other_r09.csv").write_text("x")
    assert next_repetition(str(tmp_path), "line_lr") == 4


def test_recorder_roundtrip_readable_by_analyzer(tmp_path):
    """★ 最关键: 录出来的文件必须能被现有分析脚本原样读回."""
    b0 = np.array([10.0, 20.0, 30.0])
    dB = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0], [0.0, 0.0, 0.0]])
    rec = Recorder(str(tmp_path), "line_lr", b0, {"name": "serial", "port": "/dev/ttyUSB0"})
    for i, row in enumerate(dB):
        rec.add(i / 100.0, row)
    rec.mark_start(0.01)
    rec.mark_stop(0.02)
    csv_path, json_path = rec.finish()

    analyze = _load_analyze_module()
    recs = analyze.load(str(tmp_path))
    assert len(recs) == 1
    got = recs[0]
    assert got["action"] == "line_lr"
    assert np.allclose(got["B"], dB)                 # ΔB 逐点一致
    assert np.allclose(got["B0"], b0)                # 基线一致
    assert got["win"] == {"start": 0.01, "end": 0.02}
    meta = json.load(open(json_path, encoding="utf-8"))
    assert meta["sample_count"] == 4
    assert meta["delta_definition"] == "dB = B - B0"
    assert meta["valid"] is True


def test_recorder_verify_returns_true_for_own_output(tmp_path):
    rec = Recorder(str(tmp_path), "t", np.zeros(3), {"name": "array"})
    rec.add(0.0, [1.0, 2.0, 3.0])
    csv_path, _ = rec.finish()
    assert rec.verify(csv_path) is True


def test_recorder_invalid_run_is_skipped_by_analyzer(tmp_path):
    """断线收尾: valid=false 的记录不应被分析脚本当成有效数据."""
    rec = Recorder(str(tmp_path), "broken", np.zeros(3), {"name": "serial"})
    rec.add(0.0, [1.0, 1.0, 1.0])
    rec.finish(valid=False, note="串口断开")
    analyze = _load_analyze_module()
    assert analyze.load(str(tmp_path)) == []


def test_recorder_refuses_empty(tmp_path):
    rec = Recorder(str(tmp_path), "empty", np.zeros(3), {"name": "array"})
    with pytest.raises(ValueError):
        rec.finish()
