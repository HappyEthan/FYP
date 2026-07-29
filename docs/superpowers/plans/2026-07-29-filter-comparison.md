# 实时滤波器对比与选型 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 ButterworthFilter + OneEuroFilter，用 V0 数据对 EMA/Butterworth/OneEuro 做定量对比，生成可重跑的选型报告。

**Architecture:** 新建 `src/brushbot/filter.py`（两个滤波器类，API 对齐现有 `EMA`）+ `scripts/compare_filters.py`（指标计算与报告生成，装配态数据可重跑）。ZController 与现有 EMA 不改动，集成为外部组合。

**Tech Stack:** Python 3.10+，numpy，matplotlib（仅脚本出图），pytest。

**Spec:** `docs/superpowers/specs/2026-07-29-filter-design.md`

## Global Constraints

- 运行时零新增依赖（scipy 未安装，不得引入；Butterworth 系数手写 bilinear transform）。
- 采样率 fs = 100.0 Hz；目标信号带宽 3 Hz；滤波器延迟份额 ≲ 5–10 ms。
- 滤波器 API 与 `src/brushbot/monitor/core.py:64` 的 `EMA` 一致：`update((3,)|(N,3)) → 同形状`、`reset()`；三通道独立；首样本冷启动无跳变。
- NaN 策略：含非有限值的样本**原样透传且不更新内部状态**。
- 数据格式：CSV 列 `t_us,t_s,dBx_uT,dBy_uT,dBz_uT`，位于 `delta_b_v0_20260724/`。
- 所有终端命令写成单行（用户全局要求）。
- 每个 Task 结束跑全量 `pytest`，确认无回归后再 commit。

---

### Task 1: ButterworthFilter

**Files:**
- Create: `src/brushbot/filter.py`
- Test: `tests/test_filter.py`

**Interfaces:**
- Consumes: 无（仅 numpy）。
- Produces: `ButterworthFilter(fc: float, fs: float = 100.0)`，方法 `update(x: np.ndarray) -> np.ndarray`（(3,)|(N,3) → 同形状）、`reset() -> None`、`freq_response(f) -> np.ndarray[complex]`（Hz 标量/数组 → 复数频响）。模块级 `_validate(x) -> (np.ndarray, bool)` 供 Task 2 复用。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_filter.py`：

```python
"""ButterworthFilter / OneEuroFilter 单测. 见 spec §6."""
import numpy as np
import pytest

from brushbot.filter import ButterworthFilter


def run_scalar(filt, values):
    """标量序列复制成三通道跑滤波, 返回第 0 通道输出序列."""
    x = np.repeat(np.asarray(values, dtype=float)[:, None], 3, axis=1)
    return filt.update(x)[:, 0]


class TestButterworthFilter:
    def test_invalid_fc_raises(self):
        with pytest.raises(ValueError):
            ButterworthFilter(fc=0.0)
        with pytest.raises(ValueError):
            ButterworthFilter(fc=50.0)  # >= Nyquist

    def test_first_sample_no_jump(self):
        y = ButterworthFilter(fc=8.0).update(np.array([3.0, -2.0, 7.0]))
        np.testing.assert_allclose(y, [3.0, -2.0, 7.0])

    def test_dc_gain_unity(self):
        y = run_scalar(ButterworthFilter(fc=8.0), np.full(200, 5.0))
        assert y[-1] == pytest.approx(5.0, rel=1e-9)

    def test_minus3db_at_fc(self):
        h = ButterworthFilter(fc=8.0).freq_response(8.0)
        assert abs(h) == pytest.approx(1.0 / np.sqrt(2.0), abs=1e-6)

    def test_rolloff_12db_per_oct(self):
        f = ButterworthFilter(fc=4.0)
        # 16→32 Hz 一个倍频程, 理想衰减 4x, 双线性预畸变下放宽到 >3x
        assert abs(f.freq_response(16.0)) / abs(f.freq_response(32.0)) > 3.0

    def test_freq_response_matches_simulation(self):
        # 3 Hz 正弦稳态输出 == 解析频响预测 (同时验证 biquad 与 freq_response)
        f = ButterworthFilter(fc=8.0)
        t = np.arange(2000) / 100.0
        y = run_scalar(f, np.sin(2 * np.pi * 3.0 * t))
        h = f.freq_response(3.0)
        y_pred = np.abs(h) * np.sin(2 * np.pi * 3.0 * t + np.angle(h))
        np.testing.assert_allclose(y[1000:], y_pred[1000:], atol=1e-3)

    def test_step_settles_within_5pct(self):
        # 冷启动于 0, 样本 1 处阶跃到 1; fc=8 Hz 应在 100 ms (10 样本) 内进入 ±5%
        y = run_scalar(ButterworthFilter(fc=8.0),
                       np.concatenate([np.zeros(1), np.ones(99)]))
        assert np.all(np.abs(y[11:] - 1.0) <= 0.05)

    def test_batch_matches_single(self):
        rng = np.random.default_rng(0)
        x = rng.normal(size=(50, 3))
        fa, fb = ButterworthFilter(8.0), ButterworthFilter(8.0)
        ya = fa.update(x)
        yb = np.array([fb.update(xi) for xi in x])
        np.testing.assert_array_equal(ya, yb)

    def test_reset_cold_restart(self):
        f = ButterworthFilter(8.0)
        f.update(np.ones((10, 3)))
        f.reset()
        np.testing.assert_allclose(f.update(np.array([2.0, 2.0, 2.0])), 2.0)

    def test_nan_passthrough_state_intact(self):
        f = ButterworthFilter(8.0)
        f.update(np.full((20, 3), 4.0))
        out = f.update(np.array([np.nan, 4.0, 4.0]))
        assert np.isnan(out[0]) and out[1] == 4.0
        y = f.update(np.array([4.0, 4.0, 4.0]))
        np.testing.assert_allclose(y, 4.0, rtol=1e-6)

    def test_bad_shape_raises(self):
        with pytest.raises(ValueError):
            ButterworthFilter(8.0).update(np.zeros((3, 2)))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/ethan/FYP && python -m pytest tests/test_filter.py -v`
Expected: 全部 FAIL/ERROR，`ModuleNotFoundError: No module named 'brushbot.filter'`

- [ ] **Step 3: 实现**

创建 `src/brushbot/filter.py`：

```python
"""逐样本实时滤波器: 2 阶 Butterworth IIR 与 One Euro 自适应低通.

信号链: MLX90393 (100 Hz) → 滤波器 → ZController (外部组合, 控制环脚本接线).
接口与 monitor/core.py:EMA 一致: update((3,)|(N,3)) → 同形状, reset().
NaN 策略: 含非有限值的样本原样透传且不更新内部状态.

见 docs/superpowers/specs/2026-07-29-filter-design.md
"""
import numpy as np


def _validate(x):
    """输入校验: 返回 ((N,3) 数组, 是否单样本)."""
    x = np.asarray(x, dtype=float)
    single = x.ndim == 1
    if single:
        x = x.reshape(1, 3)
    elif x.ndim != 2 or x.shape[1] != 3:
        raise ValueError("update() 需要 (3,) 或 (N,3) 数组, 当前形状: %s" % (x.shape,))
    return x, single


class ButterworthFilter:
    """2 阶 Butterworth IIR 低通 biquad, 三通道独立, 逐样本实时滤波."""

    def __init__(self, fc: float, fs: float = 100.0):
        if not 0.0 < fc < fs / 2.0:
            raise ValueError("fc 必须在 (0, fs/2) 之间, 当前: %s" % fc)
        self.fc = float(fc)
        self.fs = float(fs)
        # 双线性变换 + 频率预畸变, Q = 1/sqrt(2)
        k = np.tan(np.pi * fc / fs)
        q = 1.0 / np.sqrt(2.0)
        norm = 1.0 / (1.0 + k / q + k * k)
        self._b = np.array([k * k, 2.0 * k * k, k * k]) * norm
        self._a = np.array([2.0 * (k * k - 1.0), 1.0 - k / q + k * k]) * norm
        self._x1 = self._x2 = self._y1 = self._y2 = None

    def update(self, x: np.ndarray) -> np.ndarray:
        x, single = _validate(x)
        out = np.empty_like(x)
        for i, xi in enumerate(x):
            if not np.all(np.isfinite(xi)):
                out[i] = xi          # NaN 透传, 状态不更新
                continue
            if self._x1 is None:     # 冷启动: 以首样本为稳态 (DC 增益=1 → 首输出=输入)
                self._x1 = self._x2 = xi.copy()
                self._y1 = self._y2 = xi.copy()
            yi = (self._b[0] * xi + self._b[1] * self._x1 + self._b[2] * self._x2
                  - self._a[0] * self._y1 - self._a[1] * self._y2)
            self._x2, self._x1 = self._x1, xi.copy()
            self._y2, self._y1 = self._y1, yi
            out[i] = yi
        return out[0] if single else out

    def reset(self) -> None:
        self._x1 = self._x2 = self._y1 = self._y2 = None

    def freq_response(self, f) -> np.ndarray:
        """数字频响 H(e^{j2πf/fs}). f: Hz 标量或数组, 返回复数同形状."""
        z1 = np.exp(-2j * np.pi * np.asarray(f, dtype=float) / self.fs)
        z2 = z1 * z1
        return ((self._b[0] + self._b[1] * z1 + self._b[2] * z2)
                / (1.0 + self._a[0] * z1 + self._a[1] * z2))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /home/ethan/FYP && python -m pytest tests/test_filter.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 全量回归 + Commit**

Run: `cd /home/ethan/FYP && python -m pytest`
Expected: 全部 PASS（现有测试无回归）

```bash
git add src/brushbot/filter.py tests/test_filter.py && git commit -m "feat(filter): 2nd-order Butterworth biquad real-time filter"
```

---

### Task 2: OneEuroFilter

**Files:**
- Modify: `src/brushbot/filter.py`（追加类）
- Modify: `tests/test_filter.py`（追加测试类）

**Interfaces:**
- Consumes: `_validate` from Task 1。
- Produces: `OneEuroFilter(min_cutoff: float = 1.0, beta: float = 0.0, d_cutoff: float = 1.0, fs: float = 100.0)`，方法 `update(x, dt: float | None = None) -> np.ndarray`、`reset() -> None`、静态方法 `smoothing_alpha(cutoff, dt) -> float|np.ndarray`（供 Task 3 计算等效频响）。

- [ ] **Step 1: 追加失败测试**

在 `tests/test_filter.py` 顶部 import 增加 `OneEuroFilter`：

```python
from brushbot.filter import ButterworthFilter, OneEuroFilter
```

文件末尾追加：

```python
class TestOneEuroFilter:
    def test_invalid_params_raise(self):
        with pytest.raises(ValueError):
            OneEuroFilter(min_cutoff=0.0)
        with pytest.raises(ValueError):
            OneEuroFilter(min_cutoff=1.0, d_cutoff=0.0)

    def test_first_sample_no_jump(self):
        y = OneEuroFilter(1.0, 0.0).update(np.array([3.0, -2.0, 7.0]))
        np.testing.assert_allclose(y, [3.0, -2.0, 7.0])

    def test_static_noise_reduced(self):
        # 静止段 (min_cutoff=1 Hz, beta=0): 输出方差显著低于输入
        rng = np.random.default_rng(1)
        x = rng.normal(0.0, 1.0, size=(2000, 3))
        y = OneEuroFilter(min_cutoff=1.0, beta=0.0).update(x)
        assert y[500:].std() < 0.5 * x[500:].std()

    def test_adaptive_less_lag_when_fast(self):
        # beta>0 时对 100 µT/s 斜坡的稳态滞后应远小于 beta=0
        ramp = 100.0 * np.arange(300) / 100.0
        lag_fixed = ramp[-1] - run_scalar(OneEuroFilter(1.0, beta=0.0), ramp)[-1]
        lag_adapt = ramp[-1] - run_scalar(OneEuroFilter(1.0, beta=0.05), ramp)[-1]
        assert lag_adapt < 0.5 * lag_fixed

    def test_custom_dt_accepted(self):
        # 同一序列用 2 倍 dt 跑, 等效截止相同时收敛更快 (行为不同即可验证 dt 生效)
        f1, f2 = OneEuroFilter(1.0, 0.0), OneEuroFilter(1.0, 0.0)
        x = np.concatenate([np.zeros(1), np.ones(20)])
        y1 = run_scalar(f1, x)
        x3 = np.repeat(x[:, None], 3, axis=1)
        y2 = np.array([f2.update(xi, dt=0.02) for xi in x3])[:, 0]
        assert y2[10] > y1[10]  # 大 dt → 单步权重更大 → 收敛更快

    def test_batch_matches_single(self):
        rng = np.random.default_rng(2)
        x = rng.normal(size=(50, 3))
        fa, fb = OneEuroFilter(1.0, 0.03), OneEuroFilter(1.0, 0.03)
        ya = fa.update(x)
        yb = np.array([fb.update(xi) for xi in x])
        np.testing.assert_array_equal(ya, yb)

    def test_reset_cold_restart(self):
        f = OneEuroFilter(1.0, 0.03)
        f.update(np.ones((10, 3)))
        f.reset()
        np.testing.assert_allclose(f.update(np.array([2.0, 2.0, 2.0])), 2.0)

    def test_nan_passthrough_state_intact(self):
        f = OneEuroFilter(1.0, 0.0)
        f.update(np.full((20, 3), 4.0))
        out = f.update(np.array([np.nan, 4.0, 4.0]))
        assert np.isnan(out[0]) and out[1] == 4.0
        y = f.update(np.array([4.0, 4.0, 4.0]))
        np.testing.assert_allclose(y, 4.0, rtol=1e-6)

    def test_smoothing_alpha_range(self):
        a = OneEuroFilter.smoothing_alpha(1.0, 0.01)
        assert 0.0 < a < 1.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/ethan/FYP && python -m pytest tests/test_filter.py -v -k OneEuro`
Expected: ImportError（`OneEuroFilter` 不存在）

- [ ] **Step 3: 实现**

在 `src/brushbot/filter.py` 末尾追加：

```python
class OneEuroFilter:
    """One Euro 自适应低通 (Casiez et al. 2012), 三通道独立.

    截止频率 fc = min_cutoff + beta·|dx_filt|:
    静止时截止低 (强降噪), 快速动作时截止升高 (低滞后).
    """

    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.0,
                 d_cutoff: float = 1.0, fs: float = 100.0):
        if min_cutoff <= 0.0 or d_cutoff <= 0.0:
            raise ValueError("min_cutoff/d_cutoff 必须 > 0, 当前: %s / %s"
                             % (min_cutoff, d_cutoff))
        self.min_cutoff = float(min_cutoff)
        self.beta = float(beta)
        self.d_cutoff = float(d_cutoff)
        self.fs = float(fs)
        self._x = None   # 上一滤波输出 (3,)
        self._dx = None  # 速度低通状态 (3,)

    @staticmethod
    def smoothing_alpha(cutoff, dt):
        """一阶低通系数 α = 1 / (1 + τ/dt), τ = 1/(2π·cutoff)."""
        tau = 1.0 / (2.0 * np.pi * np.asarray(cutoff, dtype=float))
        return 1.0 / (1.0 + tau / dt)

    def update(self, x: np.ndarray, dt: float | None = None) -> np.ndarray:
        x, single = _validate(x)
        dt = 1.0 / self.fs if dt is None else float(dt)
        out = np.empty_like(x)
        for i, xi in enumerate(x):
            if not np.all(np.isfinite(xi)):
                out[i] = xi          # NaN 透传, 状态不更新
                continue
            if self._x is None:      # 冷启动: 首输出=输入, 速度置零
                self._x = xi.copy()
                self._dx = np.zeros(3)
                out[i] = xi
                continue
            dx = (xi - self._x) / dt
            a_d = self.smoothing_alpha(self.d_cutoff, dt)
            self._dx = a_d * dx + (1.0 - a_d) * self._dx
            cutoff = self.min_cutoff + self.beta * np.abs(self._dx)
            a = self.smoothing_alpha(cutoff, dt)   # (3,) 逐通道自适应
            self._x = a * xi + (1.0 - a) * self._x
            out[i] = self._x
        return out[0] if single else out

    def reset(self) -> None:
        self._x = None
        self._dx = None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /home/ethan/FYP && python -m pytest tests/test_filter.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 全量回归 + Commit**

Run: `cd /home/ethan/FYP && python -m pytest`
Expected: 全部 PASS

```bash
git add src/brushbot/filter.py tests/test_filter.py && git commit -m "feat(filter): One Euro adaptive low-pass filter"
```

---

### Task 3: 对比脚本指标函数

**Files:**
- Create: `scripts/compare_filters.py`（本 Task 只写指标函数，main 在 Task 4）
- Test: `tests/test_compare_filters.py`

**Interfaces:**
- Consumes: `ButterworthFilter`, `OneEuroFilter`, `EMA`（`brushbot.monitor.core`）。
- Produces（Task 4 的 main 使用）: `load_csv(path) -> dict(name, t, dB)`、`fft_lowpass(x, fc, fs=100.0) -> (N,3)`、`sigmas(x) -> (σx, σy, σz, |σ|)`、`ema_freq_response(alpha, f, fs=100.0) -> complex`、`phase_lag_deg(h) -> float`、`group_delay_ms(freq_fn, f0=3.0) -> float`、`f3db(freq_fn) -> float`、`step_settle_ms(make_filter) -> float`、`dynamic_rms(make_filter, dB) -> float`、`build_configs() -> list[dict]`（键 `label/make/freq/fc_ref`，`fc_ref` 为 σ 对照用 FFT 截断频率，OneEuro 用 min_cutoff、EMA 用数值 -3dB）。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_compare_filters.py`：

```python
"""compare_filters 指标函数单测."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from compare_filters import (build_configs, dynamic_rms, ema_freq_response,
                             f3db, fft_lowpass, group_delay_ms, phase_lag_deg,
                             sigmas, step_settle_ms)
from brushbot.filter import ButterworthFilter


def test_fft_lowpass_zero_phase():
    # 1 Hz 正弦 + 20 Hz 干扰, 截断 5 Hz: 干扰消失且 1 Hz 分量零相移
    t = np.arange(1000) / 100.0
    sig = np.sin(2 * np.pi * 1.0 * t)
    x = np.repeat((sig + 0.5 * np.sin(2 * np.pi * 20.0 * t))[:, None], 3, axis=1)
    y = fft_lowpass(x, fc=5.0)
    np.testing.assert_allclose(y[:, 0], sig, atol=0.02)


def test_sigmas_shape():
    rng = np.random.default_rng(0)
    s = sigmas(rng.normal(0.0, 2.0, size=(5000, 3)))
    assert len(s) == 4 and s[3] == pytest.approx(np.linalg.norm(s[:3]))


def test_ema_freq_response_dc_unity():
    assert abs(ema_freq_response(0.3, 0.0)) == pytest.approx(1.0)


def test_phase_lag_positive_for_lowpass():
    h = ButterworthFilter(8.0).freq_response(3.0)
    assert phase_lag_deg(h) > 0.0


def test_group_delay_positive():
    f = ButterworthFilter(8.0)
    assert 0.0 < group_delay_ms(f.freq_response) < 50.0


def test_f3db_butterworth_equals_fc():
    f = ButterworthFilter(8.0)
    assert f3db(f.freq_response) == pytest.approx(8.0, abs=0.1)


def test_step_settle_reasonable():
    ms = step_settle_ms(lambda: ButterworthFilter(8.0))
    assert 0.0 < ms <= 100.0


def test_dynamic_rms_lower_for_wider_band():
    # 更高截止 → 跟踪 3 Hz 参考更紧 → RMS 更小 (对纯信号无噪声情形)
    t = np.arange(1000) / 100.0
    x = np.repeat(np.sin(2 * np.pi * 2.0 * t)[:, None], 3, axis=1)
    r_wide = dynamic_rms(lambda: ButterworthFilter(12.0), x)
    r_narrow = dynamic_rms(lambda: ButterworthFilter(5.0), x)
    assert r_wide < r_narrow


def test_build_configs_complete():
    cfgs = build_configs()
    labels = [c["label"] for c in cfgs]
    assert any("EMA" in s for s in labels)
    assert sum("Butter" in s for s in labels) == 4
    assert sum("OneEuro" in s for s in labels) == 9
    for c in cfgs:
        assert callable(c["make"]) and callable(c["freq"]) and c["fc_ref"] > 0.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/ethan/FYP && python -m pytest tests/test_compare_filters.py -v`
Expected: ImportError（`compare_filters` 不存在）

- [ ] **Step 3: 实现指标函数**

创建 `scripts/compare_filters.py`：

```python
#!/usr/bin/env python3
"""滤波器定量对比: EMA / Butterworth / One Euro → 选型报告.

用法 (单行):
    python scripts/compare_filters.py
    python scripts/compare_filters.py path/to/*.csv --out docs/filter-comparison.md

默认跑 delta_b_v0_20260724/ 全部数据. 装配态 E0 数据到位后, 用装配态 CSV
重跑同一命令即可重新选型 (spec §4).
"""
import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from brushbot.filter import ButterworthFilter, OneEuroFilter  # noqa: E402
from brushbot.monitor.core import EMA                          # noqa: E402

FS = 100.0        # 采样率 Hz
F_SIG = 3.0       # 目标信号带宽 Hz (提按动作)
REF_FC = 3.0      # 动态跟踪参考: FFT 零相位截断频率 Hz
SETTLE_TOL = 0.05


def load_csv(path):
    """ΔB CSV → dict(name, t, dB). 列: t_us,t_s,dBx_uT,dBy_uT,dBz_uT."""
    d = np.genfromtxt(path, delimiter=",", names=True)
    dB = np.column_stack([d["dBx_uT"], d["dBy_uT"], d["dBz_uT"]])
    return {"name": Path(path).stem, "t": d["t_s"], "dB": dB}


def fft_lowpass(x, fc, fs=FS):
    """FFT 域理想截断 (零相位, 离线参考用). x: (N,3)."""
    X = np.fft.rfft(x, axis=0)
    f = np.fft.rfftfreq(len(x), d=1.0 / fs)
    X[f > fc] = 0.0
    return np.fft.irfft(X, n=len(x), axis=0)


def sigmas(x):
    """(N,3) → (σx, σy, σz, |σ|), 关于各通道均值的标准差."""
    s = x.std(axis=0)
    return float(s[0]), float(s[1]), float(s[2]), float(np.linalg.norm(s))


def ema_freq_response(alpha, f, fs=FS):
    """一阶 EMA 频响 H = α / (1 - (1-α)·z⁻¹)."""
    z1 = np.exp(-2j * np.pi * np.asarray(f, dtype=float) / fs)
    return alpha / (1.0 - (1.0 - alpha) * z1)


def phase_lag_deg(h):
    """复频响 → 相位滞后 (度, 正值=滞后)."""
    return float(-np.degrees(np.angle(h)))


def group_delay_ms(freq_fn, f0=F_SIG, df=0.01):
    """群延迟 τ_g = -dφ/dω 数值微分 @ f0, 返回 ms."""
    phi = np.unwrap(np.angle(freq_fn(np.array([f0 - df, f0 + df]))))
    return float(-(phi[1] - phi[0]) / (2.0 * np.pi * 2.0 * df) * 1000.0)


def f3db(freq_fn):
    """数值求 -3dB 频率 (Hz)."""
    f = np.linspace(0.05, FS / 2.0 - 0.5, 4000)
    mag = np.abs(freq_fn(f))
    idx = np.nonzero(mag <= 1.0 / np.sqrt(2.0))[0]
    return float(f[idx[0]]) if len(idx) else float("nan")


def step_settle_ms(make_filter, tol=SETTLE_TOL, n=500):
    """阶跃响应进入并保持 ±tol 所需时间 (ms). 冷启动于 0, 样本 1 阶跃到 1."""
    x = np.zeros((n, 3))
    x[1:] = 1.0
    y = make_filter().update(x)[:, 0]
    bad = np.abs(y - 1.0) > tol
    last = int(np.max(np.nonzero(bad)[0])) if bad.any() else 0
    return last * 1000.0 / FS


def dynamic_rms(make_filter, dB):
    """滤波输出 vs FFT 零相位参考 (REF_FC) 的逐元素 RMS (µT)."""
    y = make_filter().update(dB)
    ref = fft_lowpass(dB, REF_FC)
    return float(np.sqrt(np.mean((y - ref) ** 2)))


def build_configs():
    """全部对比配置. fc_ref: σ 对照用的 FFT 截断频率."""
    cfgs = [{"label": "EMA a=0.3", "make": lambda: EMA(0.3),
             "freq": lambda f: ema_freq_response(0.3, f),
             "fc_ref": f3db(lambda f: ema_freq_response(0.3, f))}]
    for fc in (5.0, 8.0, 10.0, 12.0):
        cfgs.append({"label": "Butter fc=%g" % fc,
                     "make": (lambda fc=fc: ButterworthFilter(fc)),
                     "freq": ButterworthFilter(fc).freq_response,
                     "fc_ref": fc})
    for mc in (0.5, 1.0, 2.0):
        for beta in (0.01, 0.03, 0.1):
            a_slow = OneEuroFilter.smoothing_alpha(mc, 1.0 / FS)
            cfgs.append({"label": "OneEuro mc=%g b=%g" % (mc, beta),
                         "make": (lambda mc=mc, b=beta: OneEuroFilter(mc, b)),
                         "freq": (lambda f, a=a_slow: ema_freq_response(a, f)),
                         "fc_ref": mc})
    return cfgs
```

注意：OneEuro 的 `freq` 是**慢态线性化**（cutoff=min_cutoff 的一阶低通），报告中须注明这是慢态等效值，快态滞后用动态 RMS 体现。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /home/ethan/FYP && python -m pytest tests/test_compare_filters.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 全量回归 + Commit**

Run: `cd /home/ethan/FYP && python -m pytest`
Expected: 全部 PASS

```bash
git add scripts/compare_filters.py tests/test_compare_filters.py && git commit -m "feat(scripts): filter comparison metric functions"
```

---

### Task 4: 报告生成 main + 跑 V0 数据出报告

**Files:**
- Modify: `scripts/compare_filters.py`（追加 main 与报告生成）
- Create（脚本生成）: `docs/filter-comparison.md`、`docs/assets/filter-comparison.png`

**Interfaces:**
- Consumes: Task 3 全部函数。
- Produces: CLI `python scripts/compare_filters.py [csv...] --out docs/filter-comparison.md`；`recommend(rows) -> dict`。

- [ ] **Step 1: 实现 main 与报告生成**

在 `scripts/compare_filters.py` 末尾追加：

```python
def evaluate(cfg, idle_dB, dyn_runs):
    """单配置 → 指标行 dict."""
    sx, sy, sz, sn = sigmas(cfg["make"]().update(idle_dB))
    rx, ry, rz, rn = sigmas(fft_lowpass(idle_dB, cfg["fc_ref"]))
    dyn = [dynamic_rms(cfg["make"], r["dB"]) for r in dyn_runs]
    return {
        "label": cfg["label"], "fc_ref": cfg["fc_ref"],
        "sigma": (sx, sy, sz), "sigma_norm": sn,
        "fft_sigma_norm": rn, "fft_diff_pct": (sn - rn) / rn * 100.0,
        "phase3_deg": phase_lag_deg(cfg["freq"](F_SIG)),
        "gd_ms": group_delay_ms(cfg["freq"]),
        "settle_ms": step_settle_ms(cfg["make"]),
        "dyn_rms": float(np.mean(dyn)) if dyn else float("nan"),
    }


def recommend(rows):
    """选型: 动态 RMS 在最优 1.25 倍内且阶跃 ≤100 ms 者中, 取 idle |σ| 最小."""
    valid = [r for r in rows if np.isfinite(r["dyn_rms"])]
    best_rms = min(r["dyn_rms"] for r in valid) if valid else float("nan")
    ok = [r for r in valid
          if r["dyn_rms"] <= 1.25 * best_rms and r["settle_ms"] <= 100.0]
    return min(ok or rows, key=lambda r: r["sigma_norm"])


def make_figure(cfgs_sel, idle, out_png):
    """图: idle z 通道滤波对比 + 阶跃响应."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    t = idle["t"][:500]
    axes[0].plot(t, idle["dB"][:500, 2], color="0.8", lw=0.6, label="raw z")
    for cfg in cfgs_sel:
        axes[0].plot(t, cfg["make"]().update(idle["dB"][:500])[:, 2],
                     lw=1.0, label=cfg["label"])
    axes[0].set(xlabel="t (s)", ylabel="ΔBz (µT)", title="Idle 降噪对比 (z)")
    axes[0].legend(fontsize=8)
    n = 100
    x = np.zeros((n, 3))
    x[1:] = 1.0
    ts = np.arange(n) * 1000.0 / FS
    for cfg in cfgs_sel:
        axes[1].plot(ts, cfg["make"]().update(x)[:, 0], lw=1.0, label=cfg["label"])
    axes[1].axhspan(0.95, 1.05, color="0.9")
    axes[1].set(xlabel="t (ms)", ylabel="step response", title="阶跃响应")
    axes[1].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_png, dpi=120)


def write_report(rows, rec, runs, out_md, out_png):
    lines = [
        "# 滤波器对比报告 (脚本生成)",
        "",
        "> 生成命令: `python scripts/compare_filters.py`",
        "> 数据: %s" % ", ".join(r["name"] for r in runs),
        "> 装配态 E0 数据到位后, 用装配态 CSV 重跑同一命令即可重新选型.",
        "",
        "## 对比矩阵",
        "",
        "| 配置 | σx/σy/σz (µT) | \\|σ\\| (µT) | FFT 对照差 % | 3Hz 相位滞后° | 群延迟 ms | 阶跃±5% ms | 动态 RMS µT |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            "| %s | %.2f/%.2f/%.2f | %.2f | %+.1f | %.1f | %.1f | %.0f | %.2f |"
            % (r["label"], *r["sigma"], r["sigma_norm"], r["fft_diff_pct"],
               r["phase3_deg"], r["gd_ms"], r["settle_ms"], r["dyn_rms"]))
    lines += [
        "",
        "注: OneEuro 的相位/群延迟为慢态线性化等效值 (cutoff=min_cutoff), 快态滞后由动态 RMS 体现;",
        "FFT 对照差 % 的 <10% 验收判据适用于 2 阶 Butterworth (spec §7), 一阶滤波器 ENBW 更宽, 差异天然更大.",
        "",
        "## 推荐",
        "",
        "**%s** — 选型规则: 动态 RMS ≤ 最优×1.25 且阶跃 ≤100 ms 者中取 idle |σ| 最小." % rec["label"],
        "",
        "handoff §2.5 四问 (以推荐配置回答):",
        "",
        "1. 3 Hz 相位滞后: **%.1f°** (慢态等效)" % rec["phase3_deg"],
        "2. 噪声: |σ| 从全带宽 6.94 µT → **%.2f µT**" % rec["sigma_norm"],
        "3. 等效 Z 噪声: σ_z = σ_filtered/S = %.2f/S mm (S 待装配态 E2 标定, µT/mm)" % rec["sigma"][2],
        "4. 滤波器延迟: 群延迟 **%.1f ms** @ 3 Hz (延迟预算 ≲10 ms)" % rec["gd_ms"],
        "",
        "## 已知边界 (滤波器无法解决)",
        "",
        "- 50 Hz 工频位于 Nyquist, 折叠回 DC — 交固件 ODR/硬件层 (handoff §4).",
        "- 机械臂运动低频磁场漂移与提按信号频谱重叠 — 交差分测量方案 (deltaB-control.md §8.1).",
        "- 裸态数据为乐观下界, 装配态 E0 复测后须重跑本报告.",
        "",
        "![对比图](assets/filter-comparison.png)",
        "",
    ]
    Path(out_md).write_text("\n".join(lines), encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csvs", nargs="*", help="ΔB CSV; 默认 delta_b_v0_20260724/ 全部")
    ap.add_argument("--out", default=str(ROOT / "docs" / "filter-comparison.md"))
    args = ap.parse_args(argv)

    paths = [Path(p) for p in args.csvs] or sorted(
        (ROOT / "delta_b_v0_20260724").glob("*.csv"))
    runs = [load_csv(p) for p in paths]
    idle_runs = [r for r in runs if "idle" in r["name"]]
    dyn_runs = [r for r in runs if "idle" not in r["name"]]
    if not idle_runs:
        sys.exit("错误: 输入中没有 idle 数据 (文件名含 'idle'), 无法算降噪指标")
    idle_dB = np.vstack([r["dB"] for r in idle_runs])

    cfgs = build_configs()
    rows = [evaluate(c, idle_dB, dyn_runs) for c in cfgs]
    rec = recommend(rows)

    out_md = Path(args.out)
    out_png = out_md.parent / "assets" / "filter-comparison.png"
    out_png.parent.mkdir(parents=True, exist_ok=True)
    sel_labels = {rec["label"], "EMA a=0.3", "Butter fc=8"}
    make_figure([c for c in cfgs if c["label"] in sel_labels],
                idle_runs[0], out_png)
    write_report(rows, rec, runs, out_md, out_png)

    for r in rows:
        print("%-22s |σ|=%.2f fftΔ=%+.1f%% φ3=%.1f° gd=%.1fms settle=%.0fms rms=%.2f"
              % (r["label"], r["sigma_norm"], r["fft_diff_pct"], r["phase3_deg"],
                 r["gd_ms"], r["settle_ms"], r["dyn_rms"]))
    print("推荐:", rec["label"], "→ 报告:", out_md)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 跑脚本生成报告**

Run: `cd /home/ethan/FYP && python scripts/compare_filters.py`
Expected: 打印 14 行配置指标 + 推荐行；生成 `docs/filter-comparison.md` 与 `docs/assets/filter-comparison.png`

- [ ] **Step 3: 验证验收判据（spec §7）**

逐项核对脚本输出：

1. 所有 `Butter fc=*` 行的 `fftΔ` 绝对值 < 10%（spec 验收；一阶滤波器不适用此判据，报告注释已说明）。
2. 推荐配置的群延迟 ≤ 10 ms 或在报告中明确超出原因。
3. `docs/filter-comparison.md` 包含四问答案、推荐配置、已知边界、重跑指令。
4. 图片正常渲染（打开 PNG 目视检查两个子图）。

若判据 1 失败：先检查 `fft_lowpass` 截断频率与 `fc_ref` 是否一致、σ 是否都关于均值计算；这是对照口径问题而非滤波器实现问题时，修对照口径。

- [ ] **Step 4: 全量回归**

Run: `cd /home/ethan/FYP && python -m pytest`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/compare_filters.py docs/filter-comparison.md docs/assets/filter-comparison.png && git commit -m "feat(scripts): filter comparison report generation + V0 results"
```

---

## 完成后

- 验收清单 = spec §7 全部条目。
- 后续（不在本计划内）：控制环脚本按外部组合接线 `dB_f = filt.update(dB_raw); z_cmd = zc.step(dB_f, g_d)`；装配态 E0 数据到位后重跑 `python scripts/compare_filters.py <装配态csv...>`。
