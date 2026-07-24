# ΔB 实时监控窗口 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 做一个 PyQtGraph 原生窗口，既能回放已录制的 ΔB 数据集，也能实时监控 Arduino（ESP32+MLX90393，100 Hz）或合成信号，并把实时数据录制成与 `delta_b_v0_20260724/` 完全一致的格式。

**Architecture:** 三层解耦——① 可插拔信号源（一律输出**原始 B**）② 无 GUI 的核心（环形缓冲、基线、派生量、录制器）③ PyQtGraph 界面。采集线程与 ~50 FPS 重绘定时器解耦，中间只隔一个 numpy 环形缓冲。

**Tech Stack:** Python 3.10+、numpy、pyqtgraph、PyQt5、pyserial、pytest。

设计依据：`docs/superpowers/specs/2026-07-24-deltab-monitor-design.md`。

## Global Constraints

- 目标平台仅 Ubuntu（Ethan 本机），conda 环境 `brushbot`，串口 `/dev/ttyUSB0`，波特率 `115200`。
- 磁场单位一律 **µT**；时间 `t_us` 为微秒整数、`t_s` 为相对秒。
- ΔB 定义固定为 `dB = B - B0`。
- 信号源接口**只输出原始 B**，扣基线一律由 `core` 负责。
- `sources.py` / `core.py` / `recorder.py` **禁止 import 任何 GUI 库**（PyQt5、pyqtgraph）；只有 `window.py` 可以。
- GUI 依赖为可选 extra：`pip install -e ".[monitor]"`；未安装 PyQt5 时，现有仿真与分析脚本必须照常可用。
- 录制输出目录默认 `recordings/`（git 忽略）。
- 方向门控阈值 `3·‖σ‖`，`‖σ‖ = sqrt(σx²+σy²+σz²)`，σ 取自取基线那 1 秒。
- 所有终端命令写成单行（用户全局要求，禁止反斜杠续行）。
- 提交信息结尾加：`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

## File Structure

| 文件 | 职责 |
|---|---|
| `src/brushbot/monitor/__init__.py` | 包导出 |
| `src/brushbot/monitor/core.py` | `RingBuffer`（定长 numpy 环形缓冲）、`Baseline`（B0 与 σ）、`derive()`（\|ΔB\|/\|ΔBxy\|/φ/θ + 门控） |
| `src/brushbot/monitor/sources.py` | `Source` 协议、`ArraySource`（内存数组，合成/测试共用）、`SerialSource`、`ReplaySource`、`parse_serial_line()` |
| `src/brushbot/monitor/recorder.py` | `Recorder`：V0 格式 CSV+JSON 写出 + 收尾自检 |
| `src/brushbot/monitor/window.py` | PyQtGraph 界面（唯一 GUI 依赖） |
| `src/brushbot/monitor/__main__.py` | 入口 |
| `tests/test_monitor_core.py` | 环形缓冲、基线、派生量、门控 |
| `tests/test_monitor_sources.py` | 串口行解析、ArraySource、ReplaySource 一致性 |
| `tests/test_monitor_recorder.py` | 录制往返测试（最关键） |
| `pyproject.toml` | 增加 `[project.optional-dependencies] monitor` |
| `.gitignore` | 增加 `recordings/` |

**相对 spec 的两处偏离（均为刻意简化，已同步回 spec）**

1. **`SynthSource` 与测试替身合并为 `ArraySource`**：它吃一段预先算好的 `(N,3)` 原始 B 数组，
   按标称速率流式吐出。合成写字信号由 `synth_writing_B()` 产生数组后交给它。
   这样合成源与测试替身是同一份代码（DRY），且 `ArraySource` 纯函数式、可精确断言。

2. **不起独立采集线程，改为 50 FPS 定时器轮询**：spec §3.2 原写"采集线程 + 重绘定时器"。
   实测量级——100 Hz × 约 30 字节/行 ≈ 3 KB/s，而 OS 串口缓冲通常 ≥4 KB，
   50 FPS 轮询每次只需取走约 2 个样本，`pyserial` 非阻塞读足以覆盖。
   单定时器省掉了环形缓冲的加锁与竞态，简单得多。
   **代价（须知晓）**：若界面被阻塞超过约 1 秒（例如弹出模态文件对话框），
   串口数据可能溢出丢失。串口源在正常监控流程下不会开对话框，故可接受；
   若将来出现丢样，升级路径是把采集移入 `QThread` 并给 `RingBuffer` 加锁。

---

### Task 1: 核心 —— 环形缓冲、基线、派生量

**Files:**
- Create: `src/brushbot/monitor/__init__.py`
- Create: `src/brushbot/monitor/core.py`
- Test: `tests/test_monitor_core.py`

**Interfaces:**
- Consumes: 无（首个任务）
- Produces:
  - `RingBuffer(capacity: int)`，属性 `n_total: int`；方法 `append(t_s: float, b: tuple[float,float,float]) -> None`、`latest(n: int) -> tuple[np.ndarray, np.ndarray]`（返回 `(t (m,), B (m,3))`，按时间升序，m ≤ n）
  - `Baseline`，属性 `b0: np.ndarray (3,)`、`sigma: np.ndarray (3,)`、`sigma_norm: float`、`ready: bool`；方法 `take(B: np.ndarray) -> None`、`apply(B: np.ndarray) -> np.ndarray`
  - `derive(dB: np.ndarray, gate: float) -> dict`，返回 `{"mag": float, "mag_xy": float, "phi_deg": float|None, "theta_deg": float|None}`

- [ ] **Step 1: 建包目录并写失败测试**

创建 `src/brushbot/monitor/__init__.py`，内容仅一行注释：

```python
"""ΔB 实时监控窗口: 可插拔信号源 + 无 GUI 核心 + PyQtGraph 界面."""
```

创建 `tests/test_monitor_core.py`：

```python
import numpy as np
import pytest
from brushbot.monitor.core import RingBuffer, Baseline, derive


def test_ringbuffer_keeps_latest_when_overflowing():
    rb = RingBuffer(capacity=3)
    for i in range(5):
        rb.append(float(i), (i * 1.0, i * 2.0, i * 3.0))
    t, B = rb.latest(3)
    assert rb.n_total == 5
    assert t.tolist() == [2.0, 3.0, 4.0]
    assert B[:, 0].tolist() == [2.0, 3.0, 4.0]
    assert B[-1].tolist() == [4.0, 8.0, 12.0]


def test_ringbuffer_latest_clamps_to_available():
    rb = RingBuffer(capacity=10)
    rb.append(0.0, (1.0, 2.0, 3.0))
    t, B = rb.latest(5)
    assert t.shape == (1,) and B.shape == (1, 3)


def test_baseline_take_and_apply():
    bl = Baseline()
    assert bl.ready is False
    B = np.array([[10.0, 20.0, 30.0], [12.0, 22.0, 34.0]])
    bl.take(B)
    assert bl.ready is True
    assert bl.b0.tolist() == [11.0, 21.0, 32.0]
    out = bl.apply(np.array([[11.0, 21.0, 32.0]]))
    assert out.tolist() == [[0.0, 0.0, 0.0]]


def test_baseline_sigma_norm():
    bl = Baseline()
    # 每轴取 [-1, 1] → 总体标准差 = 1.0 每轴 → 模 = sqrt(3)
    B = np.array([[-1.0, -1.0, -1.0], [1.0, 1.0, 1.0]])
    bl.take(B)
    assert np.allclose(bl.sigma, [1.0, 1.0, 1.0])
    assert bl.sigma_norm == pytest.approx(np.sqrt(3.0))


def test_derive_above_gate():
    d = derive(np.array([3.0, 4.0, 0.0]), gate=1.0)
    assert d["mag"] == pytest.approx(5.0)
    assert d["mag_xy"] == pytest.approx(5.0)
    assert d["phi_deg"] == pytest.approx(np.degrees(np.arctan2(4.0, 3.0)))
    assert d["theta_deg"] == pytest.approx(90.0)


def test_derive_below_gate_returns_none_direction():
    d = derive(np.array([0.1, 0.1, 0.1]), gate=100.0)
    assert d["mag"] == pytest.approx(np.sqrt(0.03))
    assert d["phi_deg"] is None
    assert d["theta_deg"] is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `conda run -n brushbot python -m pytest tests/test_monitor_core.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'brushbot.monitor.core'`

- [ ] **Step 3: 实现 core.py**

创建 `src/brushbot/monitor/core.py`：

```python
"""无 GUI 核心: 环形缓冲 + 基线 + 派生量. 禁止 import 任何 GUI 库."""
import numpy as np


class RingBuffer:
    """定长环形缓冲, O(1) 写入. 存 (t_s, Bx, By, Bz)."""

    def __init__(self, capacity: int):
        if capacity < 1:
            raise ValueError("capacity 必须 >= 1")
        self.capacity = int(capacity)
        self._t = np.zeros(self.capacity, dtype=float)
        self._B = np.zeros((self.capacity, 3), dtype=float)
        self._w = 0          # 下一个写入位置
        self.n_total = 0     # 累计写入总数

    def append(self, t_s: float, b) -> None:
        self._t[self._w] = t_s
        self._B[self._w] = b
        self._w = (self._w + 1) % self.capacity
        self.n_total += 1

    def latest(self, n: int):
        """返回最近 n 个样本 (t, B), 按时间升序; 不足则返回全部."""
        m = min(int(n), self.capacity, self.n_total)
        if m <= 0:
            return np.empty(0), np.empty((0, 3))
        idx = (self._w - m + np.arange(m)) % self.capacity
        return self._t[idx].copy(), self._B[idx].copy()


class Baseline:
    """基线 B0 与噪声 σ. ΔB = B - B0."""

    def __init__(self):
        self.b0 = np.zeros(3)
        self.sigma = np.zeros(3)
        self.ready = False

    def take(self, B: np.ndarray) -> None:
        """用一段静止样本 (N,3) 取基线, 同时算三轴标准差."""
        B = np.asarray(B, dtype=float)
        if B.ndim != 2 or B.shape[1] != 3 or len(B) == 0:
            raise ValueError("take() 需要形如 (N,3) 的非空数组")
        self.b0 = B.mean(axis=0)
        self.sigma = B.std(axis=0)
        self.ready = True

    @property
    def sigma_norm(self) -> float:
        return float(np.linalg.norm(self.sigma))

    def apply(self, B: np.ndarray) -> np.ndarray:
        """原始 B → ΔB."""
        return np.asarray(B, dtype=float) - self.b0


def derive(dB, gate: float) -> dict:
    """单个 ΔB 向量 → 幅值与方向. 幅值低于 gate 时方向置 None(噪声主导, 无意义)."""
    d = np.asarray(dB, dtype=float).reshape(3)
    mag_xy = float(np.hypot(d[0], d[1]))
    mag = float(np.linalg.norm(d))
    if mag < gate:
        return {"mag": mag, "mag_xy": mag_xy, "phi_deg": None, "theta_deg": None}
    return {
        "mag": mag,
        "mag_xy": mag_xy,
        "phi_deg": float(np.degrees(np.arctan2(d[1], d[0]))),
        "theta_deg": float(np.degrees(np.arctan2(mag_xy, d[2]))),
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `conda run -n brushbot python -m pytest tests/test_monitor_core.py -q`
Expected: PASS，6 passed

- [ ] **Step 5: 确认没破坏现有测试**

Run: `conda run -n brushbot python -m pytest -q`
Expected: 全部通过（现有 33 个 + 新增 6 个 = 39 passed）

- [ ] **Step 6: 提交**

```bash
git add src/brushbot/monitor/__init__.py src/brushbot/monitor/core.py tests/test_monitor_core.py && git commit -m "feat(monitor): ring buffer, baseline and derived quantities

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: 信号源 —— 协议、ArraySource、串口行解析

**Files:**
- Create: `src/brushbot/monitor/sources.py`
- Test: `tests/test_monitor_sources.py`

**Interfaces:**
- Consumes: 无（不依赖 Task 1）
- Produces:
  - `parse_serial_line(line: str) -> tuple[int, float, float, float] | None`，返回 `(t_us, Bx, By, Bz)`；表头/空行/坏行返回 `None`
  - `ArraySource(t_s: np.ndarray, B: np.ndarray, name: str = "array", rate_hz: float = 100.0)`，方法 `start()`、`read() -> list[tuple[float,float,float,float]]`、`stop()`、`seek(frac: float)`，属性 `info: dict`、`done: bool`、`rate: float`（可读写的播放倍速）
  - `SerialSource(port: str, baud: int = 115200)`，同样的 `start/read/stop/info`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_monitor_sources.py`：

```python
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
    import time
    t = np.arange(5) / 100.0
    B = np.arange(15, dtype=float).reshape(5, 3)
    src = ArraySource(t, B, rate_hz=100.0)
    src.start()
    got = []
    for _ in range(100):            # 反复读直到读完
        got.extend(src.read())
        if src.done:
            break
        time.sleep(0.001)           # 由调用方推进墙钟(真实场景是 GUI 定时器); read() 必须保持非阻塞
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
    import time
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
        time.sleep(0.001)           # 同上: 墙钟由调用方推进
    # 从一半开始 → 拿到的第一个样本索引 >= 5
    assert got[0][1] >= 5.0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `conda run -n brushbot python -m pytest tests/test_monitor_sources.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'brushbot.monitor.sources'`

- [ ] **Step 3: 实现 sources.py（本步只写 parse + ArraySource + SerialSource）**

创建 `src/brushbot/monitor/sources.py`：

```python
"""可插拔信号源. 一律输出**原始 B**(非 ΔB), 扣基线由 core 负责.

禁止 import 任何 GUI 库。
"""
import time
import numpy as np

Sample = tuple  # (t_s, Bx, By, Bz)


def parse_serial_line(line: str):
    """固件一行 't_us,Bx,By,Bz' → (t_us, Bx, By, Bz); 表头/空行/坏行 → None."""
    if not isinstance(line, str):
        return None
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    parts = s.split(",")
    if len(parts) != 4:
        return None
    try:
        return (int(float(parts[0])), float(parts[1]), float(parts[2]), float(parts[3]))
    except (ValueError, TypeError):
        return None


class ArraySource:
    """内存数组信号源: 按标称速率流式吐出预先算好的原始 B.

    合成信号与单元测试共用此类(合成 = 先算好数组再交给它)。
    """

    def __init__(self, t_s, B, name: str = "array", rate_hz: float = 100.0):
        self._t = np.asarray(t_s, dtype=float).reshape(-1)
        self._B = np.asarray(B, dtype=float).reshape(-1, 3)
        if len(self._t) != len(self._B):
            raise ValueError("t_s 与 B 长度不一致")
        self.name = name
        self.rate_hz = float(rate_hz)
        self.rate = 1.0            # 播放倍速
        self._i = 0
        self._t0 = None

    def start(self) -> None:
        self._t0 = time.monotonic()
        self._i = 0

    def stop(self) -> None:
        self._t0 = None

    def seek(self, frac: float) -> None:
        """跳到总时长的 frac(0~1) 处."""
        frac = min(max(float(frac), 0.0), 1.0)
        self._i = int(frac * len(self._t))
        now = time.monotonic()
        if self._i < len(self._t):
            offset = (self._t[self._i] - self._t[0]) / max(self.rate, 1e-9)
            self._t0 = now - offset
        else:
            self._t0 = now

    @property
    def done(self) -> bool:
        return self._i >= len(self._t)

    @property
    def info(self) -> dict:
        return {"name": self.name, "nominal_rate_hz": self.rate_hz,
                "units": "uT", "n_samples": int(len(self._t))}

    def read(self) -> list:
        """吐出到当前墙钟时刻为止应该发生的样本."""
        if self._t0 is None or self.done:
            return []
        elapsed = (time.monotonic() - self._t0) * self.rate
        out = []
        base = self._t[0]
        while self._i < len(self._t) and (self._t[self._i] - base) <= elapsed:
            out.append((float(self._t[self._i]), float(self._B[self._i, 0]),
                        float(self._B[self._i, 1]), float(self._B[self._i, 2])))
            self._i += 1
        return out


class SerialSource:
    """pyserial 串口源. 固件格式 't_us,Bx,By,Bz' @115200."""

    def __init__(self, port: str = "/dev/ttyUSB0", baud: int = 115200):
        self.port = port
        self.baud = baud
        self._ser = None
        self._buf = b""
        self._t0_us = None
        self.bad_lines = 0

    def start(self) -> None:
        import serial                       # 延迟导入: 没插硬件也能 import 本模块
        self._ser = serial.Serial(self.port, self.baud, timeout=0)
        self._buf = b""
        self._t0_us = None
        self.bad_lines = 0

    def stop(self) -> None:
        if self._ser is not None:
            self._ser.close()
            self._ser = None

    @property
    def info(self) -> dict:
        return {"name": "serial", "nominal_rate_hz": 100.0, "units": "uT",
                "port": self.port, "baud": self.baud}

    def read(self) -> list:
        """非阻塞读, 按行解析; 正确处理跨包截断的半行."""
        if self._ser is None:
            return []
        self._buf += self._ser.read(4096)
        out = []
        while b"\n" in self._buf:
            raw, self._buf = self._buf.split(b"\n", 1)
            rec = parse_serial_line(raw.decode("utf-8", errors="replace"))
            if rec is None:
                if raw.strip() and not raw.strip().startswith(b"#"):
                    self.bad_lines += 1
                continue
            t_us, bx, by, bz = rec
            if self._t0_us is None:
                self._t0_us = t_us
            out.append(((t_us - self._t0_us) / 1e6, bx, by, bz))
        return out
```

- [ ] **Step 4: 运行测试确认通过**

Run: `conda run -n brushbot python -m pytest tests/test_monitor_sources.py -q`
Expected: PASS，12 passed（8 个 parametrize + 4 个）

- [ ] **Step 5: 提交**

```bash
git add src/brushbot/monitor/sources.py tests/test_monitor_sources.py && git commit -m "feat(monitor): pluggable sources — serial line parser, ArraySource, SerialSource

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: 回放源 —— 读 V0 数据集并还原为原始 B

**Files:**
- Modify: `src/brushbot/monitor/sources.py`（追加 `load_v0_record` 与 `ReplaySource`）
- Modify: `tests/test_monitor_sources.py`（追加测试）

**Interfaces:**
- Consumes: `ArraySource`（Task 2）
- Produces:
  - `load_v0_record(csv_path: str) -> dict`，返回 `{"t_s": np.ndarray, "B_raw": np.ndarray (N,3), "b0": np.ndarray (3,), "meta": dict}`
  - `ReplaySource(csv_path: str)`，继承 `ArraySource` 的全部接口，额外属性 `b0: np.ndarray`（该记录的原始基线）

**为什么要"加回 B0"**：数据集 CSV 存的是 ΔB，而信号源接口约定输出原始 B。
`B_raw = ΔB + B0` 还原后，core 再用同一个 B0 扣回去，显示结果与原记录逐点一致；
同时使得"回放时重新取零"成为可能。

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_monitor_sources.py` 末尾：

```python
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
    src.stop()
    assert len(got) == 3
    raw = np.array([[g[1], g[2], g[3]] for g in got])
    bl = Baseline()
    bl.b0 = src.b0                       # 用记录自带的基线扣回去
    assert np.allclose(bl.apply(raw), dB)   # 应与原 CSV 的 ΔB 逐点一致
```

- [ ] **Step 2: 运行测试确认失败**

Run: `conda run -n brushbot python -m pytest tests/test_monitor_sources.py -q -k "v0 or replay"`
Expected: FAIL，`ImportError: cannot import name 'load_v0_record'`

- [ ] **Step 3: 实现**

追加到 `src/brushbot/monitor/sources.py` 末尾：

```python
import json
import os


def load_v0_record(csv_path: str) -> dict:
    """读一对 V0 CSV+JSON. CSV 存的是 ΔB, 这里加回 B0 还原成原始 B."""
    js_path = csv_path[:-4] + ".json" if csv_path.endswith(".csv") else csv_path + ".json"
    if not os.path.exists(js_path):
        raise FileNotFoundError("缺少配套 JSON: %s" % js_path)
    meta = json.load(open(js_path, encoding="utf-8"))
    b0d = meta["baseline_B0_uT"]
    b0 = np.array([b0d["Bx_uT"], b0d["By_uT"], b0d["Bz_uT"]], dtype=float)
    d = np.genfromtxt(csv_path, delimiter=",", names=True)
    dB = np.c_[d["dBx_uT"], d["dBy_uT"], d["dBz_uT"]]
    return {"t_s": np.atleast_1d(d["t_s"]).astype(float),
            "B_raw": dB + b0, "b0": b0, "meta": meta}


class ReplaySource(ArraySource):
    """回放已录制的 V0 数据集(还原成原始 B 后走 ArraySource 的流式逻辑)."""

    def __init__(self, csv_path: str):
        rec = load_v0_record(csv_path)
        super().__init__(rec["t_s"], rec["B_raw"],
                         name="replay:" + os.path.basename(csv_path))
        self.b0 = rec["b0"]
        self.meta = rec["meta"]

    @property
    def info(self) -> dict:
        d = super().info
        d["action"] = self.meta.get("action")
        return d
```

- [ ] **Step 4: 运行测试确认通过**

Run: `conda run -n brushbot python -m pytest tests/test_monitor_sources.py -q`
Expected: PASS，14 passed

- [ ] **Step 5: 用真实数据集做一次冒烟验证**

Run: `conda run -n brushbot python -c "from brushbot.monitor.sources import load_v0_record; r=load_v0_record('delta_b_v0_20260724/20260724_144949_line_rl_r01.csv'); print('样本', len(r['t_s']), 'B0', r['b0'], 'B_raw[0]', r['B_raw'][0])"`
Expected: 打印 `样本 1300`，`B0 [ 278.4 701.8 -5505.2]`，`B_raw[0]` 为三个有限数

- [ ] **Step 6: 提交**

```bash
git add src/brushbot/monitor/sources.py tests/test_monitor_sources.py && git commit -m "feat(monitor): ReplaySource — restore raw B from a V0 record so it can be re-zeroed

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: 录制器 —— V0 格式写出 + 往返自检

**Files:**
- Create: `src/brushbot/monitor/recorder.py`
- Test: `tests/test_monitor_recorder.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: 无
- Produces:
  - `next_repetition(out_dir: str, action: str) -> int`
  - `Recorder(out_dir: str, action: str, b0: np.ndarray, source_info: dict)`；方法
    `add(t_s: float, dB) -> None`、`mark_start(t_s: float) -> None`、`mark_stop(t_s: float) -> None`、
    `finish(valid: bool = True, note: str = "") -> tuple[str, str]`（返回 `(csv_path, json_path)`）、
    `verify(csv_path: str) -> bool`

- [ ] **Step 1: 写失败测试（含最关键的往返测试）**

创建 `tests/test_monitor_recorder.py`：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `conda run -n brushbot python -m pytest tests/test_monitor_recorder.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'brushbot.monitor.recorder'`

- [ ] **Step 3: 实现 recorder.py**

创建 `src/brushbot/monitor/recorder.py`：

```python
"""录制成 V0 数据集格式(CSV + JSON), 与 delta_b_v0_20260724/ 字段一致.

禁止 import 任何 GUI 库。
"""
import glob
import json
import os
import re
from datetime import datetime, timezone

import numpy as np

CSV_HEADER = "t_us,t_s,dBx_uT,dBy_uT,dBz_uT"


def next_repetition(out_dir: str, action: str) -> int:
    """扫描**同 action**的既有文件, 返回最大编号 + 1(从 1 起).

    必须整名 fullmatch: 用 re.search 会让后缀相同的 action 撞车
    (只有 line_lr 文件时, next_repetition(dir,'lr') 会错误地返回 6)。
    """
    best = 0
    for p in glob.glob(os.path.join(out_dir, "*.csv")):
        m = re.fullmatch(r"\d{8}_\d{6}_%s_r(\d+)\.csv" % re.escape(action),
                         os.path.basename(p))
        if m:
            best = max(best, int(m.group(1)))
    return best + 1


class Recorder:
    """累积 ΔB 样本, 结束时写出 CSV+JSON 并自检."""

    def __init__(self, out_dir: str, action: str, b0, source_info: dict):
        self.out_dir = out_dir
        self.action = action
        self.b0 = np.asarray(b0, dtype=float).reshape(3)
        self.source_info = dict(source_info or {})
        self._t = []
        self._dB = []
        self._start = None
        self._stop = None
        os.makedirs(out_dir, exist_ok=True)

    def add(self, t_s: float, dB) -> None:
        self._t.append(float(t_s))
        self._dB.append([float(v) for v in dB])

    def mark_start(self, t_s: float) -> None:
        self._start = float(t_s)

    def mark_stop(self, t_s: float) -> None:
        self._stop = float(t_s)

    def finish(self, valid: bool = True, note: str = ""):
        if not self._t:
            raise ValueError("没有样本, 拒绝写空记录")
        t = np.array(self._t, dtype=float)
        dB = np.array(self._dB, dtype=float)
        t0 = t[0]                                      # ★ 时间原点: 样本与标记必须共用
        t = t - t0                                     # 相对秒
        rep = next_repetition(self.out_dir, self.action)
        stem = "%s_%s_r%02d" % (datetime.now().strftime("%Y%m%d_%H%M%S"), self.action, rep)
        csv_path = os.path.join(self.out_dir, stem + ".csv")
        json_path = os.path.join(self.out_dir, stem + ".json")

        with open(csv_path, "w", encoding="utf-8") as f:
            f.write(CSV_HEADER + "\n")
            for k in range(len(t)):
                f.write("%d,%.6f,%.3f,%.3f,%.3f\n"
                        % (round(t[k] * 1e6), t[k], dB[k, 0], dB[k, 1], dB[k, 2]))

        dt = np.diff(t)
        meta = {
            "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
            "action": self.action,
            "repetition": rep,
            "valid": bool(valid),
            "note": note,
            "sensor": "synthetic" if self.source_info.get("name", "").startswith(("array", "replay"))
                      else "MLX90393",
            "board": "Seeed Studio XIAO ESP32-C3",
            "port": self.source_info.get("port"),
            "baud": self.source_info.get("baud"),
            "units": {"t_us": "us", "t_s": "s",
                      "dBx_uT": "uT", "dBy_uT": "uT", "dBz_uT": "uT"},
            "delta_definition": "dB = B - B0",
            "baseline_B0_uT": {"Bx_uT": float(self.b0[0]),
                               "By_uT": float(self.b0[1]),
                               "Bz_uT": float(self.b0[2])},
            "display_smoothing_applied": False,
            "recording_mode": "manual_markers",
            "sample_count": int(len(t)),
            "measured_duration_s": float(t[-1]),
            "mean_sample_rate_hz": float(1.0 / dt.mean()) if len(dt) else None,
            "max_interval_us": int(dt.max() * 1e6) if len(dt) else None,
            "csv_file": os.path.basename(csv_path),
        }
        if self._start is not None and self._stop is not None:
            # ★ 标记必须减去同一个 t0。否则"连上→看一会儿→按录制"时,
            #   样本被 rebase 到 0 而标记停在几十秒处, action_window_s 直接失效。
            start_s = self._start - t0
            stop_s = self._stop - t0
            meta["action_window_s"] = {"start": start_s, "end": stop_s}
            meta["action_start_t_us"] = int(round(start_s * 1e6))   # 设计文档 §5 要求
            meta["action_end_t_us"] = int(round(stop_s * 1e6))
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return csv_path, json_path

    def verify(self, csv_path: str) -> bool:
        """回读刚写的文件对, 确认格式可被消费; 失败返回 False 而不是抛异常."""
        try:
            js = csv_path[:-4] + ".json"
            meta = json.load(open(js, encoding="utf-8"))
            d = np.genfromtxt(csv_path, delimiter=",", names=True)
            need = {"t_us", "t_s", "dBx_uT", "dBy_uT", "dBz_uT"}
            if not need.issubset(set(d.dtype.names or ())):
                return False
            return int(meta["sample_count"]) == int(np.atleast_1d(d["t_s"]).size)
        except Exception:
            return False
```

- [ ] **Step 4: 运行测试确认通过**

Run: `conda run -n brushbot python -m pytest tests/test_monitor_recorder.py -q`
Expected: PASS，5 passed

- [ ] **Step 5: 忽略录制输出目录**

在 `.gitignore` 末尾追加：

```
# 监控窗口的录制输出
recordings/
```

- [ ] **Step 6: 全量测试**

Run: `conda run -n brushbot python -m pytest -q`
Expected: 全部通过（33 + 6 + 14 + 5 = 58 passed）

- [ ] **Step 7: 提交**

```bash
git add src/brushbot/monitor/recorder.py tests/test_monitor_recorder.py .gitignore && git commit -m "feat(monitor): V0-format recorder with an analyzer round-trip test

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: 合成信号源 —— 由写字合成 ΔB 生成数组

**Files:**
- Modify: `src/brushbot/monitor/sources.py`（追加 `synth_writing_B`）
- Modify: `tests/test_monitor_sources.py`（追加测试）

**Interfaces:**
- Consumes: `ArraySource`（Task 2）、`brushbot.tactile.writing_tactile.tactile_from_trace`
- Produces: `synth_writing_B(n: int = 600, rate_hz: float = 100.0, b0=(270.0, 710.0, -5500.0)) -> ArraySource`

**说明**：不直接调 `write_with_tactile`（它会拉起 PyBullet，慢且依赖字形数据集）。
改为构造一段合成笔尖轨迹交给 `tactile_from_trace`，再叠加标称 B0 得到原始 B。
这样合成源**无外部数据依赖、可在测试中确定性运行**。

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_monitor_sources.py` 末尾：

```python
from brushbot.monitor.sources import synth_writing_B


def test_synth_writing_B_produces_streamable_source():
    src = synth_writing_B(n=200, rate_hz=100.0)
    assert src.info["n_samples"] == 200
    src.start()
    got = []
    for _ in range(2000):
        got.extend(src.read())
        if src.done:
            break
    src.stop()
    assert len(got) == 200
    B = np.array([[g[1], g[2], g[3]] for g in got])
    assert np.isfinite(B).all()
    # 应当围绕标称 B0 波动, 且确实有变化(不是常数)
    assert B.std(axis=0).max() > 0.0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `conda run -n brushbot python -m pytest tests/test_monitor_sources.py -q -k synth`
Expected: FAIL，`ImportError: cannot import name 'synth_writing_B'`

- [ ] **Step 3: 实现**

追加到 `src/brushbot/monitor/sources.py` 末尾：

```python
def synth_writing_B(n: int = 600, rate_hz: float = 100.0,
                    b0=(270.0, 710.0, -5500.0)) -> ArraySource:
    """合成信号源: 构造一段"落笔-横拖-抬笔"轨迹 → 合成 ΔB → 叠加标称 B0 得原始 B.

    不依赖字形数据集与 PyBullet, 确定性可测。
    """
    from brushbot import config
    from brushbot.tactile.writing_tactile import tactile_from_trace

    k = np.arange(n)
    # 前 15% 悬空, 中间落笔并横向匀速拖行, 末 15% 抬笔
    down = (k > 0.15 * n) & (k < 0.85 * n)
    z = np.where(down, config.PAPER_Z - 0.0015, config.PAPER_Z + 0.01)
    x = config.CHAR_ORIGIN[0] + np.linspace(-0.015, 0.015, n)
    y = np.full(n, config.CHAR_ORIGIN[1], dtype=float)
    trace = np.c_[x, y, z]
    dB, _ = tactile_from_trace(trace)
    B_raw = np.asarray(dB, dtype=float) + np.asarray(b0, dtype=float)
    t = k / float(rate_hz)
    return ArraySource(t, B_raw, name="synth:writing", rate_hz=rate_hz)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `conda run -n brushbot python -m pytest tests/test_monitor_sources.py -q`
Expected: PASS，15 passed

- [ ] **Step 5: 提交**

```bash
git add src/brushbot/monitor/sources.py tests/test_monitor_sources.py && git commit -m "feat(monitor): synthetic writing source built on the analytic tactile model

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: 依赖声明 + PyQtGraph 窗口

**Files:**
- Modify: `pyproject.toml`
- Create: `src/brushbot/monitor/window.py`
- Create: `src/brushbot/monitor/__main__.py`

**Interfaces:**
- Consumes: `RingBuffer`/`Baseline`/`derive`（Task 1）、`SerialSource`/`ReplaySource`/`synth_writing_B`（Task 2/3/5）、`Recorder`/`next_repetition`（Task 4）
- Produces: `MonitorWindow`（QMainWindow 子类）、`main(argv=None) -> int`

⚠️ **本任务无自动化测试**：PyQtGraph 窗口无法在无显示环境验证。
测试方式为**手动验收**（Step 6 给出清单）。核心逻辑的正确性已由 Task 1–5 的单测覆盖。

- [ ] **Step 1: 声明可选依赖**

修改 `pyproject.toml`，在 `dependencies` 那一行之后插入：

```toml
[project.optional-dependencies]
monitor = ["pyqtgraph>=0.13", "PyQt5>=5.15", "pyserial>=3.5"]
```

- [ ] **Step 2: 安装监控依赖**

Run: `conda run -n brushbot pip install -e ".[monitor]"`
Expected: 成功安装 pyqtgraph、PyQt5、pyserial

- [ ] **Step 3: 确认核心模块仍然不依赖 GUI**

Run: `conda run -n brushbot python -c "import sys; import brushbot.monitor.core, brushbot.monitor.sources, brushbot.monitor.recorder; bad=[m for m in sys.modules if m.startswith(('PyQt5','pyqtgraph'))]; print('GUI 模块被误引入:', bad); assert not bad, bad; print('✅ 核心三模块无 GUI 依赖')"`
Expected: 打印 `✅ 核心三模块无 GUI 依赖`

- [ ] **Step 4: 实现窗口**

创建 `src/brushbot/monitor/window.py`：

```python
"""PyQtGraph 监控窗口. 唯一允许 import GUI 库的模块.

布局: 左=ΔBx–ΔBy 相图; 右=ΔBx / ΔBy / ΔBz(可折叠) 三个独立时序图。
采集在定时器里 poll 信号源, 重绘固定 ~50 FPS, 与采样率解耦。
"""
import os
import numpy as np
import pyqtgraph as pg
from PyQt5 import QtCore, QtWidgets

from brushbot.monitor.core import RingBuffer, Baseline, derive
from brushbot.monitor.recorder import Recorder
from brushbot.monitor import sources as S

BUF_SECONDS = 60
RATE_HZ = 100
WINDOWS_S = [5, 10, 30, 60]


class MonitorWindow(QtWidgets.QMainWindow):
    def __init__(self, out_dir="recordings"):
        super().__init__()
        self.setWindowTitle("ΔB 实时监控 — 形变量与形变方向")
        self.resize(1400, 820)
        self.out_dir = out_dir
        self.src = None
        self.rb = RingBuffer(BUF_SECONDS * RATE_HZ)
        self.bl = Baseline()
        self.rec = None
        self._pending_baseline = None     # 连上后自动取基线的截止时间

        self._build_ui()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(20)              # 50 FPS

    # ---------- UI ----------
    def _build_ui(self):
        bar = self.addToolBar("main")
        self.cb_src = QtWidgets.QComboBox()
        self.cb_src.addItems(["串口", "回放", "合成"])
        bar.addWidget(QtWidgets.QLabel(" 源 ")); bar.addWidget(self.cb_src)
        self.ed_port = QtWidgets.QLineEdit("/dev/ttyUSB0"); self.ed_port.setFixedWidth(140)
        bar.addWidget(self.ed_port)
        self.btn_conn = QtWidgets.QPushButton("连接"); bar.addWidget(self.btn_conn)
        self.btn_base = QtWidgets.QPushButton("取基线"); bar.addWidget(self.btn_base)
        self.btn_rec = QtWidgets.QPushButton("● 录制"); bar.addWidget(self.btn_rec)
        self.btn_mark = QtWidgets.QPushButton("标记 START"); bar.addWidget(self.btn_mark)
        bar.addWidget(QtWidgets.QLabel(" 动作名 "))
        self.ed_action = QtWidgets.QLineEdit("line_lr"); self.ed_action.setFixedWidth(110)
        bar.addWidget(self.ed_action)
        bar.addWidget(QtWidgets.QLabel(" 时窗 "))
        self.cb_win = QtWidgets.QComboBox()
        self.cb_win.addItems(["%ds" % w for w in WINDOWS_S]); self.cb_win.setCurrentIndex(1)
        bar.addWidget(self.cb_win)

        self.btn_conn.clicked.connect(self._toggle_connect)
        self.btn_base.clicked.connect(lambda: self._take_baseline())
        self.btn_rec.clicked.connect(self._toggle_record)
        self.btn_mark.clicked.connect(self._toggle_mark)
        self.cb_src.currentIndexChanged.connect(self._sync_controls)

        pg.setConfigOptions(antialias=True, background="#0e1116", foreground="#c9d1d9")
        split = QtWidgets.QSplitter()
        self.p_xy = pg.PlotWidget(title="XY 相图  ΔBx – ΔBy")
        self.p_xy.setAspectLocked(True); self.p_xy.showGrid(x=True, y=True, alpha=0.3)
        self.p_xy.setLabel("bottom", "ΔBx (uT)"); self.p_xy.setLabel("left", "ΔBy (uT)")
        self.c_trail = self.p_xy.plot(pen=pg.mkPen("#3fb950", width=1))
        self.c_vec = self.p_xy.plot(pen=pg.mkPen("#ff4d6d", width=2))
        self.c_pt = self.p_xy.plot(pen=None, symbol="o", symbolSize=9,
                                   symbolBrush="#ff4d6d", symbolPen=None)
        split.addWidget(self.p_xy)

        right = QtWidgets.QWidget(); vb = QtWidgets.QVBoxLayout(right)
        vb.setContentsMargins(0, 0, 0, 0)
        self.p_x = pg.PlotWidget(title="ΔBx"); self.p_y = pg.PlotWidget(title="ΔBy")
        self.p_z = pg.PlotWidget(title="ΔBz")
        self.cur_x = self.p_x.plot(pen=pg.mkPen("#4aa3ff", width=1))
        self.cur_y = self.p_y.plot(pen=pg.mkPen("#ffa64a", width=1))
        self.cur_z = self.p_z.plot(pen=pg.mkPen("#b6bfcc", width=1))
        for p in (self.p_x, self.p_y, self.p_z):
            p.showGrid(x=True, y=True, alpha=0.3); p.setLabel("left", "uT")
        self.p_y.setXLink(self.p_x); self.p_z.setXLink(self.p_x)
        self.chk_z = QtWidgets.QCheckBox("显示 ΔBz"); self.chk_z.setChecked(False)
        self.chk_z.toggled.connect(self.p_z.setVisible); self.p_z.setVisible(False)
        vb.addWidget(self.p_x); vb.addWidget(self.p_y)
        vb.addWidget(self.chk_z); vb.addWidget(self.p_z)
        split.addWidget(right); split.setSizes([560, 840])
        self.setCentralWidget(split)

        self.lbl_read = QtWidgets.QLabel("—")
        self.statusBar().addPermanentWidget(self.lbl_read, 1)
        self._sync_controls()

    def _sync_controls(self):
        mode = self.cb_src.currentText()
        self.ed_port.setEnabled(mode == "串口")
        self.btn_rec.setEnabled(mode != "回放")      # 回放不产生新数据

    # ---------- 源 ----------
    def _toggle_connect(self):
        if self.src is not None:
            self._disconnect(); return
        mode = self.cb_src.currentText()
        try:
            if mode == "串口":
                self.src = S.SerialSource(self.ed_port.text().strip())
            elif mode == "合成":
                self.src = S.synth_writing_B()
            else:
                path, _ = QtWidgets.QFileDialog.getOpenFileName(
                    self, "选择录制的 CSV", "", "CSV (*.csv)")
                if not path:
                    return
                self.src = S.ReplaySource(path)
                self.bl.b0 = self.src.b0; self.bl.ready = True   # 先用记录自带基线
            self.src.start()
        except Exception as e:
            self.src = None
            self.statusBar().showMessage("打不开信号源: %s" % e, 8000)
            return
        self.rb = RingBuffer(BUF_SECONDS * RATE_HZ)
        self.btn_conn.setText("断开")
        # 所有源都在采到 1 秒后自动重取基线 —— 回放也要, 否则 sigma 为 0 会让门控失效
        # (记录开头通常是静止段, 重取得到的 b0 与记录自带的基本一致, 但额外拿到 sigma)
        self._pending_baseline = 1.0
        self.statusBar().showMessage("已连接: %s" % self.src.info.get("name"), 4000)

    def _disconnect(self, note=""):
        if self.rec is not None:
            self._stop_record(valid=False, note=note or "断开连接")
        try:
            self.src.stop()
        except Exception:
            pass
        self.src = None
        self.btn_conn.setText("连接")

    # ---------- 基线 ----------
    def _take_baseline(self, seconds=1.0):
        t, B = self.rb.latest(int(seconds * RATE_HZ))
        if len(B) < 10:
            self.statusBar().showMessage("样本不足, 无法取基线", 4000); return
        self.bl.take(B)
        self.statusBar().showMessage(
            "已取基线 B0=(%.1f, %.1f, %.1f) µT, 门控=%.1f µT"
            % (*self.bl.b0, 3 * self.bl.sigma_norm), 6000)

    # ---------- 录制 ----------
    def _toggle_record(self):
        if self.rec is None:
            if not self.bl.ready:
                self.statusBar().showMessage("请先取基线", 4000); return
            self.rec = Recorder(self.out_dir, self.ed_action.text().strip() or "unnamed",
                                self.bl.b0, self.src.info if self.src else {})
            self.btn_rec.setText("■ 停止")
        else:
            self._stop_record()

    def _stop_record(self, valid=True, note=""):
        try:
            csv_path, _ = self.rec.finish(valid=valid, note=note)
            ok = self.rec.verify(csv_path)
            self.statusBar().showMessage(
                ("已保存 %s" % os.path.basename(csv_path)) if ok
                else ("⚠️ 写出的文件自检失败: %s" % csv_path), 8000)
        except Exception as e:
            self.statusBar().showMessage("录制收尾失败: %s" % e, 8000)
        self.rec = None
        self.btn_rec.setText("● 录制"); self.btn_mark.setText("标记 START")

    def _toggle_mark(self):
        if self.rec is None:
            return
        t, _ = self.rb.latest(1)
        if not len(t):
            return
        if self.btn_mark.text().endswith("START"):
            self.rec.mark_start(float(t[-1])); self.btn_mark.setText("标记 STOP")
        else:
            self.rec.mark_stop(float(t[-1])); self.btn_mark.setText("标记 START")

    # ---------- 主循环 ----------
    def _tick(self):
        if self.src is not None:
            try:
                for (t_s, bx, by, bz) in self.src.read():
                    self.rb.append(t_s, (bx, by, bz))
                    if self.rec is not None and self.bl.ready:
                        self.rec.add(t_s, self.bl.apply(np.array([[bx, by, bz]]))[0])
            except Exception as e:
                self.statusBar().showMessage("采集中断: %s" % e, 8000)
                self._disconnect(note=str(e))
            if self._pending_baseline and self.rb.n_total >= RATE_HZ * self._pending_baseline:
                self._pending_baseline = None
                self._take_baseline()
        self._redraw()

    def _redraw(self):
        win_s = WINDOWS_S[self.cb_win.currentIndex()]
        t, B = self.rb.latest(win_s * RATE_HZ)
        if len(t) == 0:
            return
        dB = self.bl.apply(B)
        self.cur_x.setData(t, dB[:, 0])
        self.cur_y.setData(t, dB[:, 1])
        if self.p_z.isVisible():
            self.cur_z.setData(t, dB[:, 2])

        n_trail = min(len(dB), 2 * RATE_HZ)
        self.c_trail.setData(dB[-n_trail:, 0], dB[-n_trail:, 1])
        last = dB[-1]
        gate = 3.0 * self.bl.sigma_norm if self.bl.ready else 0.0
        d = derive(last, gate)
        self.c_pt.setData([last[0]], [last[1]])
        if d["phi_deg"] is None:
            self.c_vec.setData([], [])
        else:
            self.c_vec.setData([0.0, last[0]], [0.0, last[1]])
        self.lbl_read.setText(
            "|ΔB| %.1f   |ΔBxy| %.1f   φ %s   θ %s   ΔBx %.1f  ΔBy %.1f  ΔBz %.1f   "
            "缓冲 %d   门控 %.1f µT"
            % (d["mag"], d["mag_xy"],
               "—" if d["phi_deg"] is None else "%.1f°" % d["phi_deg"],
               "—" if d["theta_deg"] is None else "%.1f°" % d["theta_deg"],
               last[0], last[1], last[2], self.rb.n_total, gate))


def main(argv=None) -> int:
    app = QtWidgets.QApplication(argv or [])
    w = MonitorWindow()
    w.show()
    return app.exec_()
```

创建 `src/brushbot/monitor/__main__.py`：

```python
import sys
from brushbot.monitor.window import main

sys.exit(main(sys.argv))
```

- [ ] **Step 5: 确认能导入且不崩（无显示环境只验证导入）**

Run: `conda run -n brushbot python -c "import brushbot.monitor.window as w; print('window 模块导入 OK, 有 MonitorWindow:', hasattr(w,'MonitorWindow'), 'main:', callable(w.main))"`
Expected: 打印 `window 模块导入 OK, 有 MonitorWindow: True main: True`

> 若报 `qt.qpa.plugin: Could not load the Qt platform plugin "xcb"`，那是无显示环境的预期行为，
> 只要是在 `QApplication` 构造时才报、`import` 本身成功即可。

- [ ] **Step 6: 手动验收清单（须在有显示器的本机执行）**

Run: `conda run -n brushbot python -m brushbot.monitor`

逐项确认：
1. 窗口打开，左侧 XY 相图、右侧 ΔBx/ΔBy 两栏，ΔBz 默认折叠。
2. 源选「合成」→ 连接 → 曲线开始滚动，1 秒后状态栏提示已自动取基线并显示门控值。
3. 勾选「显示 ΔBz」→ 第三栏出现；取消 → 消失。
4. 切换时窗 5/10/30/60 s → X 轴范围随之变化。
5. 静止时 φ/θ 显示 `—`；有信号时显示角度且 XY 图出现红色方向线。
6. 源选「回放」→ 选 `delta_b_v0_20260724/20260724_144949_line_rl_r01.csv` → 波形与
   `docs/assets/deltab_v0_analysis.png` 中 line_rl 的形状一致；录制按钮置灰。
7. 源选「合成」→ 录制 → 标记 START/STOP → 停止 → 状态栏提示已保存且自检通过；
   `recordings/` 下出现 CSV+JSON。
8. 用分析脚本读回刚录的文件：
   `conda run -n brushbot python scripts/analyze_deltab.py recordings /tmp/rec_check.png`
   应正常输出统计而不报错。

- [ ] **Step 7: 提交**

```bash
git add pyproject.toml src/brushbot/monitor/window.py src/brushbot/monitor/__main__.py && git commit -m "feat(monitor): PyQtGraph window and entry point

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: 使用文档

**Files:**
- Create: `docs/monitor-usage.md`
- Modify: `docs/deltab-v0-analysis.md`（在 §9 之后加一节指针）

**Interfaces:**
- Consumes: 全部前序任务
- Produces: 无代码接口

- [ ] **Step 1: 写使用手册**

创建 `docs/monitor-usage.md`：

````markdown
# ΔB 实时监控窗口 · 使用手册

> 设计见 `docs/superpowers/specs/2026-07-24-deltab-monitor-design.md`。
> 离线交互回放（浏览器版）见 `docs/deltab-v0-analysis.md` §9。

## 安装

```
conda activate brushbot && pip install -e ".[monitor]"
```

## 启动

```
python -m brushbot.monitor
```

## 三种信号源

| 源 | 用途 | 录制 |
|---|---|---|
| 串口 | 实时读 ESP32+MLX90393（默认 `/dev/ttyUSB0` @115200） | ✅ |
| 回放 | 读已录制的 V0 数据集 CSV | ❌（不产生新数据） |
| 合成 | 解析模型产生的虚拟信号，无需硬件 | ✅（JSON 中 `sensor` 标为 `synthetic`） |

## 界面

- **左**：ΔBx–ΔBy 相图，等比例，带拖尾与当前点。
- **右**：ΔBx / ΔBy 两个**独立 Y 轴**的时序图；ΔBz 勾选后出现。
- **状态栏**：`|ΔB|`、`|ΔBxy|`、方位角 φ、极角 θ、三轴瞬时值、缓冲计数、门控阈值。

## 基线与方向门控

连上非回放源后 1 秒自动取基线；任何时候可按「取基线」重取。
取基线时同时测得噪声 σ，门控阈值 = `3·‖σ‖`。
当 `|ΔB|` 低于门控时，φ/θ 显示 `—` 且不画方向线——此时方向由噪声主导，显示出来是假信息。

## 录制

先取基线 → 「● 录制」→ 动作开始时按「标记 START」、结束按「标记 STOP」→「■ 停止」。
输出到 `recordings/`，格式与 `delta_b_v0_20260724/` 一致，可直接被分析脚本消费：

```
python scripts/analyze_deltab.py recordings out.png
```

## 排错

| 现象 | 处理 |
|---|---|
| `打不开信号源` | 确认串口路径与权限：`ls -l /dev/ttyUSB0`；必要时 `sudo usermod -aG dialout $USER` 后重新登录 |
| 曲线不动 | 确认已点「连接」；串口源需固件正在输出 |
| φ/θ 一直是 `—` | 正常——信号未超过噪声门控；或重新取基线 |
| `Could not load the Qt platform plugin "xcb"` | 需要图形界面，不能在纯 SSH 无 X11 下运行 |
````

- [ ] **Step 2: 在分析报告里加指针**

在 `docs/deltab-v0-analysis.md` 的 §9 末尾追加一行：

```markdown
> **实时版**：需要边采边看（或接 Arduino/合成源）时用原生窗口，见 `docs/monitor-usage.md`。
```

- [ ] **Step 3: 提交**

```bash
git add docs/monitor-usage.md docs/deltab-v0-analysis.md && git commit -m "docs: usage manual for the ΔB live monitor window

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## 任务依赖图

```
Task 1 (core) ─────┐
Task 2 (sources) ──┼─→ Task 5 (synth) ─┐
       └→ Task 3 (replay) ─────────────┼─→ Task 6 (window) → Task 7 (docs)
Task 4 (recorder) ───────────────────  ┘
```

Task 1–4 彼此独立，可并行；Task 5 依赖 Task 2；Task 6 依赖全部；Task 7 最后。

## 验收标准

- `conda run -n brushbot python -m pytest -q` 全绿（预期 33 现有 + 26 新增 = **59 passed**；
  其中 core 6、sources 15、recorder 5）。
- `brushbot.monitor.core/sources/recorder` 三个模块 import 后 `sys.modules` 中无 PyQt5/pyqtgraph。
- 用监控窗口录一段合成数据 → `scripts/analyze_deltab.py recordings out.png` 能正常读出。
- 未安装 `[monitor]` extra 的环境里，现有仿真与分析脚本照常可用。
- Task 6 Step 6 的 8 项手动验收全部通过（须在有显示器的机器上确认）。
