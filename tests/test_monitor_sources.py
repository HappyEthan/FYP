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
