"""跨模块契约测试: 无 GUI 依赖 + 串口成帧 + 录制→分析脚本 端到端.

这些测的是逐模块单测结构上看不到的"接缝", 也是最终评审里三个 Critical 的来源。
全部不需要显示器。
"""
import importlib.util
import json
import pathlib
import subprocess
import sys

import numpy as np
import pytest

from brushbot.monitor.recorder import Recorder
from brushbot.monitor.sources import ArraySource, SerialSource

REPO = pathlib.Path(__file__).resolve().parents[1]


def _load_analyzer():
    """按路径加载 scripts/analyze_deltab.py(它不是包的一部分)."""
    p = REPO / "scripts" / "analyze_deltab.py"
    spec = importlib.util.spec_from_file_location("analyze_deltab", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ---------- 契约 1: 核心三模块不得拖进 GUI ----------

def test_core_modules_do_not_import_gui():
    """core/sources/recorder 必须无 GUI 依赖.

    用子进程跑, 否则同一次 pytest 里别的测试 import 过 window 就会污染 sys.modules。
    """
    code = ("import sys, brushbot.monitor.core, brushbot.monitor.sources, "
            "brushbot.monitor.recorder; "
            "print([m for m in sys.modules if m.startswith(('PyQt5', 'pyqtgraph'))])")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=REPO, check=True)
    assert out.stdout.strip() == "[]", "核心模块把 GUI 库拖进来了: %s" % out.stdout


# ---------- 契约 2: 串口成帧(唯一的真硬件通路, 之前完全没测) ----------

class _FakeSerial:
    """最小替身: 按预设分块吐字节, 模拟 pyserial 的非阻塞 read(n)."""

    def __init__(self, chunks):
        self._chunks = list(chunks)

    def read(self, n):
        return self._chunks.pop(0) if self._chunks else b""

    def close(self):
        pass


def _serial_with(chunks):
    src = SerialSource("/dev/null")
    src._ser = _FakeSerial(chunks)
    src._buf = b""
    src._t0_us = None
    src.bad_lines = 0
    return src


def test_serial_source_joins_line_split_across_chunks():
    """一行被拆到两个数据包里时必须拼回来, 而不是当成两条坏行丢掉."""
    src = _serial_with([b"1000000,1.5,2.5,", b"3.5\n"])
    assert src.read() == []                      # 半行: 先不出数
    got = src.read()
    assert len(got) == 1
    assert got[0] == (0.0, 1.5, 2.5, 3.5)        # 首样本 → 相对时间 0
    assert src.bad_lines == 0


def test_serial_source_skips_header_and_counts_bad_lines():
    src = _serial_with([b"# t_us,Bx_uT,By_uT,Bz_uT\n"
                        b"oops not a sample\n"
                        b"2000000,1.0,2.0,3.0\n"])
    got = src.read()
    assert len(got) == 1                         # 表头跳过, 坏行跳过, 好行留下
    assert src.bad_lines == 1                    # 表头不计坏行, 乱码计
    assert got[0][1:] == (1.0, 2.0, 3.0)


def test_serial_source_times_are_relative_to_first_sample():
    src = _serial_with([b"5000000,0,0,0\n5500000,1,1,1\n"])
    got = src.read()
    assert [g[0] for g in got] == pytest.approx([0.0, 0.5])


# ---------- 契约 3: 录制出来的东西必须能被分析脚本真正跑通 ----------

def _record_array(tmp_path, n=120):
    """Use a deterministic offline array; no monitor synthetic source is involved."""
    t = np.arange(n, dtype=float) / 100.0
    delta = np.column_stack([
        100.0 * np.sin(2 * np.pi * t),
        80.0 * np.cos(2 * np.pi * t),
        20.0 * np.sin(4 * np.pi * t),
    ])
    b0 = np.array([270.0, 710.0, -5500.0])
    src = ArraySource(t, delta + b0, rate_hz=100.0, name="offline-array")
    rec = Recorder(str(tmp_path), b0, src.info)
    for k in range(n):
        rec.add(t[k], src._B[k] - b0)
    return rec.finish()


def test_new_recording_is_consumable_without_fabricated_action_window(tmp_path):
    csv_path, _ = _record_array(tmp_path)
    analyze = _load_analyzer()
    recs = analyze.load(str(tmp_path))
    assert recs[0]["action"] == pathlib.Path(csv_path).stem
    assert recs[0]["win"] is None


def test_legacy_action_and_window_are_preserved(tmp_path):
    csv_path, json_path = _record_array(tmp_path)
    meta = json.loads(pathlib.Path(json_path).read_text(encoding="utf-8"))
    meta["action"] = "line_lr"
    meta["action_window_s"] = {"start": 0.2, "end": 0.8}
    pathlib.Path(json_path).write_text(json.dumps(meta), encoding="utf-8")

    rec = _load_analyzer().load(str(tmp_path))[0]
    assert pathlib.Path(csv_path).exists()
    assert rec["action"] == "line_lr"
    assert rec["win"] == {"start": 0.2, "end": 0.8}
