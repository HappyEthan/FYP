import time

import numpy as np
import pytest
from brushbot.monitor.sources import parse_serial_line, ArraySource


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


from brushbot.monitor.sources import synth_writing_B
from brushbot.monitor import sources as S


def test_synth_writing_B_produces_streamable_source():
    src = synth_writing_B(n=200, rate_hz=100.0)
    assert src.info["n_samples"] == 200
    src.start()
    got = []
    for _ in range(2000):
        got.extend(src.read())
        if src.done:
            break
        time.sleep(0.001)
    src.stop()
    assert len(got) == 200
    B = np.array([[g[1], g[2], g[3]] for g in got])
    assert np.isfinite(B).all()
    # 应当围绕标称 B0 波动, 且确实有变化(不是常数)
    assert B.std(axis=0).max() > 0.0


def test_progress_and_duration():
    t = np.arange(100) / 100.0
    src = S.ArraySource(t, np.zeros((100, 3)), rate_hz=100.0)
    assert src.progress == 0.0
    assert src.duration_s == pytest.approx(0.99)
    src.start()
    src.seek(0.5)
    assert src.progress == pytest.approx(0.5, abs=0.02)
    src.seek(1.0)
    assert src.progress == 1.0
    assert src.done


def test_progress_empty_array():
    src = S.ArraySource([], np.zeros((0, 3)))
    assert src.progress == 1.0
    assert src.duration_s == 0.0
