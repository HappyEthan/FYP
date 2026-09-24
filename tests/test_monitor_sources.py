import time

import numpy as np
import pytest
from brushbot.monitor.sources import parse_serial_line, ArraySource, SerialSource


def test_monitor_sources_do_not_offer_synthetic_source():
    import brushbot.monitor.sources as sources
    assert not hasattr(sources, "synth_writing_B")


def test_parse_serial_line_good():
    assert parse_serial_line("12345,1.5,-2.25,3.0") == (12345, 1.5, -2.25, 3.0)


@pytest.mark.parametrize("bad", [
    "# t_us,Bx_uT,By_uT,Bz_uT",   # 表头
    "",                            # 空行
    "   ",                         # 空白
    "12345,1.5,-2.25",             # 字段不足
    "12345,1.5,-2.25,3.0,9.9",     # 字段过多
    "abc,1.5,-2.25,3.0",           # 时间戳非数
    "12345,1.5,oops,3.0",          # 磁场非数
    "\x00\xff garbage",            # 乱码
])
def test_parse_serial_line_rejects(bad):
    assert parse_serial_line(bad) is None


def test_array_source_streams_all_samples():
    t = np.arange(5) / 100.0
    B = np.arange(15, dtype=float).reshape(5, 3)
    src = ArraySource(t, B, rate_hz=100.0)
    src.start()
    got = []
    for _ in range(100):            # 反复读直到读完; 模拟 20ms 间隔的 GUI 定时器轮询
        got.extend(src.read())
        if src.done:
            break
        time.sleep(0.001)
    src.stop()
    assert len(got) == 5
    assert got[0] == (0.0, 0.0, 1.0, 2.0)
    assert got[-1] == (0.04, 12.0, 13.0, 14.0)


def test_array_source_read_is_incremental():
    t = np.arange(4) / 100.0
    B = np.zeros((4, 3))
    src = ArraySource(t, B)
    src.start()
    first = src.read()
    second = src.read()
    # 同一个样本不能被读到两次
    assert len(first) + len(second) <= 4
    assert src.info["name"] == "array"


def test_array_source_experiment_frames_are_labelled_and_preserve_time():
    src = ArraySource([0.0], [[1.0, 2.0, 3.0]], name="synthetic:test")
    src.start()
    frames = src.read_frames()
    src.stop()
    assert frames == [{
        "sensor_t_us": 0,
        "B_uT": [1.0, 2.0, 3.0],
        "source_kind": "synthetic",
    }]


def test_serial_read_frames_preserves_raw_sensor_timestamp():
    class FakeSerial:
        def __init__(self):
            self.payload = b"2522423,11,22,33\n"

        def read(self, _size):
            payload, self.payload = self.payload, b""
            return payload

    src = SerialSource()
    src._ser = FakeSerial()
    frame = src.read_frames()[0]
    assert frame["sensor_t_us"] == 2522423
    assert frame["B_uT"] == [11.0, 22.0, 33.0]
    assert frame["source_kind"] == "serial"
    assert isinstance(frame["host_rx_ns"], int)


def test_serial_source_reports_empty_and_malformed_input_counts():
    class FakeSerial:
        def __init__(self):
            self.payloads = [b"", b"header\n", b"123,1,2,3\n"]

        def read(self, _size):
            return self.payloads.pop(0)

    src = SerialSource()
    src._ser = FakeSerial()
    assert src.read_frames() == []
    assert src.read_frames() == []
    assert len(src.read_frames()) == 1
    assert src.diagnostics == {
        "bytes_received": len(b"header\n123,1,2,3\n"),
        "lines_seen": 2,
        "bad_lines": 1,
    }


def test_legacy_and_experiment_modes_use_separate_source_instances():
    legacy = ArraySource([0.0], [[1.0, 2.0, 3.0]])
    experiment = ArraySource([0.0], [[1.0, 2.0, 3.0]])
    legacy.start()
    experiment.start()
    assert legacy.read() == [(0.0, 1.0, 2.0, 3.0)]
    assert experiment.read_frames()[0]["B_uT"] == [1.0, 2.0, 3.0]


def test_array_source_seek():
    t = np.arange(10) / 100.0
    B = np.tile(np.arange(10, dtype=float)[:, None], (1, 3))
    src = ArraySource(t, B)
    src.start()
    src.seek(0.5)
    got = []
    for _ in range(200):
        got.extend(src.read())
        if src.done:
            break
        time.sleep(0.001)
    # 从一半开始 → 拿到的第一个样本索引 >= 5
    assert got[0][1] >= 5.0


import json
from brushbot.monitor.sources import load_v0_record, ReplaySource


def _write_fake_v0(tmp_path, dB, b0=(100.0, 200.0, 300.0)):
    csv = tmp_path / "20260724_120000_test_r01.csv"
    lines = ["t_us,t_s,dBx_uT,dBy_uT,dBz_uT"]
    for i, row in enumerate(dB):
        lines.append("%d,%.6f,%.3f,%.3f,%.3f" % (i * 10000, i / 100.0, *row))
    csv.write_text("\n".join(lines) + "\n")
    (tmp_path / "20260724_120000_test_r01.json").write_text(json.dumps({
        "action": "test", "valid": True,
        "baseline_B0_uT": {"Bx_uT": b0[0], "By_uT": b0[1], "Bz_uT": b0[2]},
        "units": {"dBx_uT": "uT"}, "delta_definition": "dB = B - B0",
    }))
    return str(csv)


def test_load_v0_record_restores_raw_B(tmp_path):
    dB = np.array([[1.0, 2.0, 3.0], [-1.0, -2.0, -3.0]])
    path = _write_fake_v0(tmp_path, dB)
    rec = load_v0_record(path)
    assert rec["b0"].tolist() == [100.0, 200.0, 300.0]
    # 原始 B = ΔB + B0
    assert np.allclose(rec["B_raw"], dB + np.array([100.0, 200.0, 300.0]))
    assert rec["meta"]["action"] == "test"


def test_replay_source_roundtrips_to_original_delta(tmp_path):
    from brushbot.monitor.core import Baseline
    dB = np.array([[1.0, 2.0, 3.0], [-4.0, 5.0, -6.0], [7.0, -8.0, 9.0]])
    path = _write_fake_v0(tmp_path, dB)
    src = ReplaySource(path)
    src.start()
    got = []
    for _ in range(500):
        got.extend(src.read())
        if src.done:
            break
        time.sleep(0.001)
    src.stop()
    assert len(got) == 3
    raw = np.array([[g[1], g[2], g[3]] for g in got])
    bl = Baseline()
    bl.b0 = src.b0                       # 用记录自带的基线扣回去
    assert np.allclose(bl.apply(raw), dB)   # 应与原 CSV 的 ΔB 逐点一致
