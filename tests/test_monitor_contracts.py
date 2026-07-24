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
from brushbot.monitor.sources import SerialSource, synth_writing_B

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

def _record_synth(tmp_path, action, marks=None, n=120):
    """用合成源灌一段进 Recorder 并落盘. marks=(start_s, stop_s) 或 None."""
    src = synth_writing_B(n=n, rate_hz=100.0)
    b0 = np.array([270.0, 710.0, -5500.0])
    rec = Recorder(str(tmp_path), action, b0, src.info)
    for k in range(n):
        t_s = k / 100.0
        raw = src._B[k]                      # 直接取数组, 不必等墙钟
        rec.add(t_s, raw - b0)
    if marks is not None:
        rec.mark_start(marks[0]); rec.mark_stop(marks[1])
    return rec.finish()


def test_synth_recording_is_not_all_zeros(tmp_path):
    """合成 ΔB 必须落在真实量级上.

    曾经的 bug: 触觉模型的任意单位被直接当 µT 用, 峰值 ~1e-4 µT,
    经 '%.3f' 格式化后整份 CSV 全是 0.000 —— 图上却看不出来(自动缩放)。
    """
    csv_path, _ = _record_synth(tmp_path, "synth_scale")
    d = np.genfromtxt(csv_path, delimiter=",", names=True)
    dB = np.c_[d["dBx_uT"], d["dBy_uT"], d["dBz_uT"]]
    peak = float(np.abs(dB).max())
    assert peak > 1.0, "录出来的 ΔB 峰值只有 %g µT, 基本等于全零" % peak
    assert peak <= 400.0 * 1.01


def test_synth_recording_is_labelled_synthetic(tmp_path):
    """合成数据不得冒充真硬件采集 —— 否则数据集里混进假样本且无从分辨."""
    _, json_path = _record_synth(tmp_path, "synth_label")
    meta = json.load(open(json_path, encoding="utf-8"))
    assert meta["sensor"] == "synthetic"
    assert meta["board"] is None


@pytest.mark.parametrize("marks", [None, (0.3, 0.8), (0.8, 0.3), (-5.0, 99.0)])
def test_recording_is_consumable_by_analyzer(tmp_path, marks):
    """★ 端到端: 录制 → analyze() 必须跑通.

    marks 覆盖: 没标记 / 正常 / 顺序颠倒 / 越界。四种都必须产出合法动作窗,
    否则 analyze_deltab.py 会 TypeError(None 不可下标) 或对空数组 .max()。
    """
    _record_synth(tmp_path, "roundtrip", marks=marks)
    analyze = _load_analyzer()
    out_png = tmp_path / "out.png"
    analyze.analyze(str(tmp_path), str(out_png))     # 不抛异常即通过
    recs = analyze.load(str(tmp_path))
    w = recs[0]["win"]
    assert w is not None
    assert 0.0 <= w["start"] < w["end"] <= recs[0]["t"][-1] + 1e-9
