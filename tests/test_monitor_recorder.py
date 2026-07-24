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


def test_action_window_is_rebased_to_csv_time_origin(tmp_path):
    """标记(mark_start/mark_stop)必须用与样本相同的时间原点重新基准化.

    若首个样本不在 t_s=0(操作员先接源、观察一阵再按录制), CSV 里的
    t_s 会被重新基准化到从 0 开始, 但标记若不跟着重新基准化,
    action_window_s 就不再对应 CSV 里的任何东西。
    """
    b0 = np.zeros(3)
    rec = Recorder(str(tmp_path), "line_lr", b0, {"name": "array"})
    for i, t in enumerate([100.0, 100.01, 100.02]):
        rec.add(t, [float(i), float(i), float(i)])
    rec.mark_start(100.005)
    rec.mark_stop(100.015)
    csv_path, json_path = rec.finish()

    d = np.genfromtxt(csv_path, delimiter=",", names=True)
    assert d["t_s"][0] == pytest.approx(0.0)

    meta = json.load(open(json_path, encoding="utf-8"))
    win = meta["action_window_s"]
    assert win["start"] == pytest.approx(0.005)
    assert win["end"] == pytest.approx(0.015)


def test_next_repetition_does_not_match_action_name_suffix(tmp_path):
    """action 名是既有 action 的后缀时不应误命中(必须锚定完整文件名)."""
    (tmp_path / "20260724_120000_line_lr_r01.csv").write_text("x")
    (tmp_path / "20260724_120000_line_lr_r05.csv").write_text("x")
    assert next_repetition(str(tmp_path), "lr") == 1


def test_action_start_stop_t_us_present_and_consistent(tmp_path):
    """JSON 必须包含微秒级的 action_start_t_us/action_end_t_us,
    与 action_window_s(秒)在同一重新基准化的时间原点上一致。"""
    b0 = np.zeros(3)
    rec = Recorder(str(tmp_path), "line_lr", b0, {"name": "array"})
    for i, t in enumerate([100.0, 100.01, 100.02]):
        rec.add(t, [float(i), float(i), float(i)])
    rec.mark_start(100.005)
    rec.mark_stop(100.015)
    _, json_path = rec.finish()

    meta = json.load(open(json_path, encoding="utf-8"))
    assert isinstance(meta["action_start_t_us"], int)
    assert isinstance(meta["action_end_t_us"], int)
    assert meta["action_start_t_us"] == pytest.approx(meta["action_window_s"]["start"] * 1e6, abs=1)
    assert meta["action_end_t_us"] == pytest.approx(meta["action_window_s"]["end"] * 1e6, abs=1)
