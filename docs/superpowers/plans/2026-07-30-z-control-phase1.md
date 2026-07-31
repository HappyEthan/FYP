# Z 控制 Phase 1 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把实时滤波器接进 Z 控制环，无量纲化增益并重新整定，建仿真 harness 跑出层 1（增益扫描）/层 2（开环 vs 闭环扰动对比）的论文数字。

**Architecture:** 新建 `src/brushbot/sim_loop.py`（噪声回放 + Plant + 目标曲线 + 唯一闭环路径 `run_loop` + 指标），改造 `ZController` 增益为无量纲，两个薄脚本产出报告。开环对照臂 = 同一 `run_loop`、Kp=Ki=0。

**Tech Stack:** 纯 numpy + matplotlib（Agg），零新依赖。pytest。

**Spec:** `docs/superpowers/specs/2026-07-30-z-control-phase1-design.md`（本计划的判据来源，实现时对照）。

## Global Constraints

- 零新依赖，`pyproject.toml` 不动；`src/` 不得 import `scripts/`。
- 采样率 FS=100 Hz，dt=0.01 s，贯穿全部代码。
- 铁律：先滤 (N,3)/(3,) 向量再取 norm，永不先 norm 后滤。
- 控制环滤波器实例整段连续运行，`run_loop` 内永不 reset。
- NaN 透传链路（filter → ZController guard）不得破坏。
- 终端命令一律单行（用户全局要求），git commit 用多个 `-m`，结尾 trailer：`Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。
- 每个任务完成时 `python -m pytest tests/ -q` 全绿（当前基线 110 项）。
- 测试用共享标定表：z 0–5 mm ↔ |ΔB| 0–250 µT（`test_z_control.py` 现有 `_CALIB_Z/_CALIB_DB`），其 S_cal = 0.005/250 = 2×10⁻⁵ m/µT。
- V0 噪声数据：`delta_b_v0_20260724/*.csv`，idle 文件名含 "idle"，列 `t_us,t_s,dBx_uT,dBy_uT,dBz_uT`。

---

### Task 1: ZController 增益无量纲化

**Files:**
- Modify: `src/brushbot/z_control.py`
- Test: `tests/test_z_control.py`

**Interfaces:**
- Produces: `ZController(calib_z_mm, calib_abs_dB, dt=0.01, kp=0.3, ki=0.03, z_surface=0.20, dz_margin=3e-3, noise_std=7.0)`，kp/ki 为**无量纲**；新属性 `s_cal -> float`（m/µT）。`step(dB_meas, g_d) -> float`、`reset()`、属性 `z_ff/z_fb/z_surface/frozen` 签名不变。后续所有任务依赖此语义。

- [ ] **Step 1: 写失败测试（新增 2 项 + 更新 2 项）**

在 `tests/test_z_control.py` 追加：

```python
def test_s_cal_from_calib():
    """S_cal = z 跨度 / |ΔB| 跨度 (m/µT)。"""
    ctrl = ZController(_CALIB_Z, _CALIB_DB, dt=0.01)
    assert ctrl.s_cal == pytest.approx(0.005 / 250.0)


def test_kp_dimensionless_semantics():
    """kp=0.5 表示每拍修正误差的 50%: 比例项 = kp·S_cal·e。"""
    ctrl = ZController(_CALIB_Z, _CALIB_DB, dt=0.01, kp=0.5, ki=0.0)
    z_cmd = ctrl.step(np.array([100.0, 0.0, 0.0]), 150.0)  # e = 50, 未 freeze
    expected = 0.20 + 0.003 + 0.5 * ctrl.s_cal * 50.0      # surface + z_ff(150) + Kp 项
    assert z_cmd == pytest.approx(expected)
```

更新 `test_step_tracks_constant`（删 magic number，用默认增益；注释里那段 kp=0.5 极限环历史说明一并删除）：

```python
def test_step_tracks_constant():
    """固定目标下闭环用默认无量纲增益收敛到 ±5%。"""
    ctrl = ZController(_CALIB_Z, _CALIB_DB, dt=0.01)
    g_d = 120.0
    dB_meas = np.zeros(3)
    for _ in range(300):
        z_cmd = ctrl.step(dB_meas, g_d)
        abs_meas = _plant(z_cmd, _CALIB_Z, _CALIB_DB)
        dB_meas = np.array([abs_meas, 0.0, 0.0])
    error = abs(g_d - np.linalg.norm(dB_meas)) / g_d
    assert error < 0.05, f"steady-state error {error:.3f} > 0.05"
```

更新 `test_reset_clears_integrator`：ki=1.0 在新语义下 50 步只积到 7×10⁻⁴ 左右，把 `ki=1.0` 改为 `ki=5.0`（50 步积 5×10⁻³ → 被 clamp 到 3×10⁻³，仍满足 `> 0.001` 断言）。其余测试（clamping/lift/air/z_ff）不改。

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_z_control.py -q`
Expected: `test_s_cal_from_calib` FAIL（no attribute `s_cal`）、`test_kp_dimensionless_semantics` FAIL、`test_step_tracks_constant` FAIL（默认 kp=0.5 有量纲，发散）。

- [ ] **Step 3: 实现无量纲化**

`src/brushbot/z_control.py` 修改点：

```python
# __init__ 签名: kp: float = 0.3, ki: float = 0.03  (docstring: 无量纲增益,
# "每拍将误差的该比例折算为压深修正"; noise_std docstring 加注 "全带宽裸态口径,
# 接滤波后必须显式传滤波后 σ")

# __init__ 排序标定表之后追加:
        db_span = float(self._calib_dB[-1] - self._calib_dB[0])   # 已升序
        assert db_span > 0, "calib |dB| span must be > 0"
        z_span = float(self._z_offset_m.max() - self._z_offset_m.min())
        self._s_cal = z_span / db_span                            # m/µT

# step() 中两处增益使用改为:
            self._z_fb += self._ki * self._s_cal * e * self._dt
        z_cmd = self._z_surface + z_ff + self._kp * self._s_cal * e + self._z_fb

# 新属性:
    @property
    def s_cal(self) -> float:
        """标定斜率 (m/µT), 无量纲增益的换算因子."""
        return self._s_cal
```

模块 docstring 的控制律行改为 `z_cmd = z_surface + z_ff(|ΔB_d|) + kp·S_cal·e + ki·S_cal·∫e`。

- [ ] **Step 4: 跑全套测试确认通过**

Run: `python -m pytest tests/ -q`
Expected: 全绿（110 + 2 新增）。

- [ ] **Step 5: Commit**

`git add src/brushbot/z_control.py tests/test_z_control.py && git commit -m "feat(z-control): dimensionless gains via calibration slope S_cal, usable defaults kp=0.3 ki=0.03" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"`

---

### Task 2: sim_loop 模块骨架 + V0NoiseSource

**Files:**
- Create: `src/brushbot/sim_loop.py`
- Test: `tests/test_sim_loop.py`（新建）

**Interfaces:**
- Produces: `load_deltab_csv(path) -> (N,3) ndarray`；`fft_lowpass(x, fc, fs=FS) -> 同形状`；`V0NoiseSource(csv_paths, seed=0)`，方法 `sample(n) -> (n,3)`（跨调用连续、同 seed 同序列）、`filtered_sigma(make_filter=None) -> float`（µT）。常量 `FS = 100.0`。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_sim_loop.py`：

```python
from pathlib import Path

import numpy as np
import pytest

from brushbot.monitor.core import EMA
from brushbot.sim_loop import FS, V0NoiseSource, load_deltab_csv

ROOT = Path(__file__).resolve().parents[1]
IDLE_CSVS = sorted(p for p in (ROOT / "delta_b_v0_20260724").glob("*.csv")
                   if "idle" in p.stem)

needs_v0 = pytest.mark.skipif(not IDLE_CSVS, reason="V0 idle data not present")


@needs_v0
def test_noise_source_sigma_matches_pool():
    """回放样本的 |σ| 与样本池一致 (它就是池子的切片)。"""
    src = V0NoiseSource(IDLE_CSVS, seed=0)
    pool = np.vstack([load_deltab_csv(p) for p in IDLE_CSVS])
    pool = pool - pool.mean(axis=0)
    sigma_pool = float(np.linalg.norm(pool.std(axis=0)))
    assert src.filtered_sigma(None) == pytest.approx(sigma_pool, rel=1e-9)


@needs_v0
def test_noise_source_seed_reproducible():
    a = V0NoiseSource(IDLE_CSVS, seed=7).sample(500)
    b = V0NoiseSource(IDLE_CSVS, seed=7).sample(500)
    np.testing.assert_array_equal(a, b)
    c = V0NoiseSource(IDLE_CSVS, seed=8).sample(500)
    assert not np.array_equal(a, c)


@needs_v0
def test_noise_source_contiguous_and_wraps():
    """跨调用连续 (1/f 谱保真的前提); 超池长时镜像延拓不报错。"""
    src = V0NoiseSource(IDLE_CSVS, seed=1)
    a = np.vstack([src.sample(100), src.sample(100)])
    src2 = V0NoiseSource(IDLE_CSVS, seed=1)
    b = src2.sample(200)
    np.testing.assert_array_equal(a, b)
    pool_len = len(np.vstack([load_deltab_csv(p) for p in IDLE_CSVS]))
    big = V0NoiseSource(IDLE_CSVS, seed=2).sample(pool_len * 2 + 17)
    assert big.shape == (pool_len * 2 + 17, 3) and np.isfinite(big).all()


@needs_v0
def test_noise_source_low_freq_dominates():
    """idle 噪声是 1/f 形: 低频段功率 > 高频段 (回放保真粗检)。"""
    x = V0NoiseSource(IDLE_CSVS, seed=3).sample(4000)[:, 2]
    P = np.abs(np.fft.rfft(x - x.mean())) ** 2
    f = np.fft.rfftfreq(len(x), d=1.0 / FS)
    assert P[(f > 0) & (f < 5)].sum() > P[f > 40].sum()


@needs_v0
def test_filtered_sigma_reduced_by_filter():
    src = V0NoiseSource(IDLE_CSVS, seed=0)
    assert src.filtered_sigma(lambda: EMA(0.3)) < src.filtered_sigma(None)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_sim_loop.py -q`
Expected: collection error（`brushbot.sim_loop` 不存在）。

- [ ] **Step 3: 实现**

新建 `src/brushbot/sim_loop.py`：

```python
"""闭环仿真 harness: V0 噪声回放 + Plant + 目标曲线 + 唯一闭环路径 run_loop.

Phase 1 全部验证 (层1 增益扫描 / 层2 开环-闭环对比 / demo) 共享 run_loop,
开环对照臂 = 同一路径、增益置零. 纯 numpy, 无 GUI/MuJoCo 依赖.
见 docs/superpowers/specs/2026-07-30-z-control-phase1-design.md
"""
import numpy as np

FS = 100.0


def load_deltab_csv(path):
    """ΔB CSV → (N,3) µT. 列: t_us,t_s,dBx_uT,dBy_uT,dBz_uT.

    与 scripts/compare_filters.load_csv 同构; src 不 import scripts, 故自带.
    """
    d = np.genfromtxt(path, delimiter=",", names=True)
    return np.column_stack([d["dBx_uT"], d["dBy_uT"], d["dBz_uT"]])


def fft_lowpass(x, fc, fs=FS):
    """FFT 域理想截断 (零相位, 仅离线目标曲线用). x: (N,3) 或 (N,)."""
    X = np.fft.rfft(x, axis=0)
    f = np.fft.rfftfreq(len(x), d=1.0 / fs)
    X[f > fc] = 0.0
    return np.fft.irfft(X, n=len(x), axis=0)


class V0NoiseSource:
    """V0 idle 数据的连续切片回放 (保 1/f 谱). 同 seed → 同序列.

    每次 sample(n) 从内部游标取连续 n 拍并前进; 池尾接镜像延拓, 无缝循环.
    """

    def __init__(self, csv_paths, seed=0):
        pool = np.vstack([load_deltab_csv(p) for p in csv_paths])
        self._pool = pool - pool.mean(axis=0)
        self._ext = np.vstack([self._pool, self._pool[::-1]])
        self._cursor = int(np.random.default_rng(seed).integers(len(self._pool)))

    def sample(self, n):
        """(n,3) 连续噪声样本, 跨调用连续."""
        out = np.empty((n, 3))
        got = 0
        while got < n:
            take = min(n - got, len(self._ext) - self._cursor)
            out[got:got + take] = self._ext[self._cursor:self._cursor + take]
            self._cursor = (self._cursor + take) % len(self._ext)
            got += take
        return out

    def filtered_sigma(self, make_filter=None):
        """样本池过滤波器后的 |σ| (µT); None → 原始 |σ|. noise_std 现算入口."""
        y = self._pool if make_filter is None else make_filter().update(self._pool)
        return float(np.linalg.norm(y.std(axis=0)))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_sim_loop.py -q`
Expected: 5 passed。再跑 `python -m pytest tests/ -q` 全绿。

- [ ] **Step 5: Commit**

`git add src/brushbot/sim_loop.py tests/test_sim_loop.py && git commit -m "feat(sim): sim_loop skeleton + V0 idle noise replay source (contiguous, seeded, filtered-sigma)" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"`

---

### Task 3: Plant（延迟 + 一阶执行器 + 标定映射 + 扰动）

**Files:**
- Modify: `src/brushbot/sim_loop.py`
- Test: `tests/test_sim_loop.py`

**Interfaces:**
- Consumes: `V0NoiseSource.sample(n)`（Task 2）。
- Produces: `Plant(calib_z_mm, calib_abs_dB, dt=0.01, tau=0.05, n_delay=2, z_surface=0.20, press_direction=(1.0, 0.3, 0.1), noise=None, calib_scale=1.0, paper_step=None, drift_rate=0.0)`；方法 `step(z_cmd: float) -> (3,) ndarray`（每调用前进一拍）；实时属性 `z_act: float`（执行器实际 z，m）、`abs_true: float`（无噪声真值 |ΔB|，µT）。`paper_step=(t_step_s, dz_m)`，dz>0 = 纸面朝笔抬高（等效压深加深）。`calib_abs_dB` 要求单调升。

- [ ] **Step 1: 写失败测试**

`tests/test_sim_loop.py` 追加（模块 import 行加 `Plant`；Task 2 已用 `@needs_v0` 按函数标注，Plant 测试大多不依赖 V0 数据，无需标注）：

```python
_CAL_Z = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
_CAL_DB = np.array([0.0, 50.0, 100.0, 150.0, 200.0, 250.0])
Z_SURF = 0.20


def _settle(plant, z_cmd, n=200):
    for _ in range(n):
        out = plant.step(z_cmd)
    return out


def test_plant_steady_state_matches_calib():
    plant = Plant(_CAL_Z, _CAL_DB)
    _settle(plant, Z_SURF + 2.0e-3)
    assert plant.abs_true == pytest.approx(100.0, rel=1e-3)


def test_plant_calib_scale():
    plant = Plant(_CAL_Z, _CAL_DB, calib_scale=1.2)
    _settle(plant, Z_SURF + 2.0e-3)
    assert plant.abs_true == pytest.approx(120.0, rel=1e-3)


def test_plant_paper_step_shifts_depth():
    plant = Plant(_CAL_Z, _CAL_DB, paper_step=(1.0, +0.5e-3))
    _settle(plant, Z_SURF + 2.0e-3, n=90)      # t<1s: 未触发
    assert plant.abs_true == pytest.approx(100.0, rel=1e-2)
    _settle(plant, Z_SURF + 2.0e-3, n=200)     # t>1s: 深 0.5mm
    assert plant.abs_true == pytest.approx(125.0, rel=1e-3)


def test_plant_drift_ramp():
    plant = Plant(_CAL_Z, _CAL_DB, drift_rate=2.0)
    out = _settle(plant, Z_SURF, n=100)        # 悬空 1s, 漂移 ~2 µT
    assert np.linalg.norm(out) == pytest.approx(2.0, abs=0.1)


def test_plant_delay_and_tau_timing():
    plant = Plant(_CAL_Z, _CAL_DB, tau=0.05, n_delay=2)
    for _ in range(2):                          # FIFO 排空前不动
        plant.step(Z_SURF + 2.0e-3)
        assert plant.z_act == pytest.approx(Z_SURF)
    for _ in range(5):                          # τ=50ms → 5拍≈1τ → ~63%
        plant.step(Z_SURF + 2.0e-3)
    frac = (plant.z_act - Z_SURF) / 2.0e-3
    assert 0.55 < frac < 0.72


def test_plant_noise_added():
    src = V0NoiseSource(IDLE_CSVS, seed=0) if IDLE_CSVS else None
    if src is None:
        pytest.skip("V0 idle data not present")
    plant = Plant(_CAL_Z, _CAL_DB, noise=src)
    outs = np.array([np.linalg.norm(plant.step(Z_SURF)) for _ in range(500)])
    assert outs.std() > 1.0                     # 悬空但有噪声起伏
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_sim_loop.py -q`
Expected: ImportError `Plant`。

- [ ] **Step 3: 实现 Plant**

`src/brushbot/sim_loop.py` 追加：

```python
class Plant:
    """被控对象: 延迟 FIFO → 一阶执行器 → 标定映射(+扰动) → 三轴合成(+漂移+噪声).

    真实曲线 = calib_abs_dB × calib_scale, 与控制器手里的标定表故意是两份
    (calib_scale≠1 即标定偏差扰动). calib_abs_dB 须单调升.
    paper_step=(t_step_s, dz_m): t≥t_step 后纸面朝笔抬高 dz (压深等效加深).
    drift_rate (µT/s): 沿 press_direction 注入 (与信号同向 = 最坏情形).
    tau/n_delay 为假设值 (真机未标定), 层1 做敏感性抽查.
    """

    def __init__(self, calib_z_mm, calib_abs_dB, dt=0.01, tau=0.05, n_delay=2,
                 z_surface=0.20, press_direction=(1.0, 0.3, 0.1), noise=None,
                 calib_scale=1.0, paper_step=None, drift_rate=0.0):
        self._z_grid_mm = np.asarray(calib_z_mm, float)
        self._db_grid = np.asarray(calib_abs_dB, float) * calib_scale
        self._dt = dt
        self._alpha = 1.0 - np.exp(-dt / tau) if tau > 0 else 1.0
        self._fifo = [z_surface] * max(0, int(n_delay))
        self._z_surface = z_surface
        d = np.asarray(press_direction, float)
        self._dir = d / np.linalg.norm(d)
        self._noise = noise
        self._paper_step = paper_step
        self._drift_rate = drift_rate
        self._t = 0.0
        self.z_act = z_surface
        self.abs_true = 0.0

    def step(self, z_cmd):
        """z 指令 (m, 世界坐标) → dB_raw (3,) µT. 每调用前进一拍."""
        self._fifo.append(float(z_cmd))
        z_delayed = self._fifo.pop(0)
        self.z_act += self._alpha * (z_delayed - self.z_act)
        paper = 0.0
        if self._paper_step is not None and self._t >= self._paper_step[0]:
            paper = self._paper_step[1]
        z_off_mm = (self.z_act - self._z_surface + paper) * 1000.0
        self.abs_true = float(np.interp(z_off_mm, self._z_grid_mm, self._db_grid,
                                        left=0.0, right=self._db_grid[-1]))
        dB = self._dir * (self.abs_true + self._drift_rate * self._t)
        if self._noise is not None:
            dB = dB + self._noise.sample(1)[0]
        self._t += self._dt
        return dB
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_sim_loop.py -q` → 全绿；`python -m pytest tests/ -q` → 全绿。

- [ ] **Step 5: Commit**

`git add src/brushbot/sim_loop.py tests/test_sim_loop.py && git commit -m "feat(sim): Plant with transport delay, first-order actuator, calib mapping and disturbances" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"`

---

### Task 4: 目标曲线（synth_press + press_from_v0）

**Files:**
- Modify: `src/brushbot/sim_loop.py`
- Test: `tests/test_sim_loop.py`

**Interfaces:**
- Produces: `synth_press(cal_max, fs=FS, hold_s=0.5, ramp_s=0.3, press_s=6.0, f0=0.5, f1=3.0, base=0.5, depth=0.3) -> (N,) ndarray`（µT；段结构 悬空|落笔ramp|扫频提按|收笔ramp|悬空，N = (2·hold+2·ramp+press)·fs）；`press_from_v0(csv_path, fc=3.0) -> (N,) ndarray`。

- [ ] **Step 1: 写失败测试**

```python
from brushbot.sim_loop import press_from_v0, synth_press  # import 行合并到文件头


def test_synth_press_structure():
    g = synth_press(cal_max=250.0)
    assert len(g) == int((0.5 + 0.3 + 6.0 + 0.3 + 0.5) * FS)
    assert g[0] == 0.0 and g[-1] == 0.0                    # 首尾悬空
    assert g.max() <= 0.8 * 250.0 + 1e-9                   # base+depth = 0.8·cal_max
    assert g.min() >= 0.0
    press = g[int(0.8 * FS):int(6.8 * FS)]                 # 提按段
    assert press.min() >= 0.2 * 250.0 - 1e-9               # base−depth, 不离纸
    sigma3 = 3 * 2.7                                       # 代表性 3σ 阈值
    assert (g < sigma3).any() and (g > sigma3).any()       # 穿越 freeze 阈值


def test_press_from_v0_zero_phase_norm():
    if not IDLE_CSVS:
        pytest.skip("V0 data not present")
    dyn = sorted(p for p in (ROOT / "delta_b_v0_20260724").glob("*.csv")
                 if "idle" not in p.stem)
    g = press_from_v0(dyn[0])
    raw = np.linalg.norm(load_deltab_csv(dyn[0]), axis=1)
    assert g.shape == raw.shape and np.isfinite(g).all()
    assert g.std() < raw.std()                             # 滤过更平滑
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_sim_loop.py -q` → ImportError。

- [ ] **Step 3: 实现**

```python
def synth_press(cal_max, fs=FS, hold_s=0.5, ramp_s=0.3, press_s=6.0,
                f0=0.5, f1=3.0, base=0.5, depth=0.3):
    """合成提按目标 g_d(t): 悬空→落笔ramp→正弦扫频(f0→f1 Hz)→收笔ramp→悬空.

    幅值: 提按段在 (base±depth)·cal_max 内起伏; 落笔/收笔斜坡保证穿越
    3σ 接触阈值 (freeze 切换的测试场景). 返回 (N,) µT.
    """
    n_hold, n_ramp, n_press = int(hold_s * fs), int(ramp_s * fs), int(press_s * fs)
    A = base * cal_max
    t = np.arange(n_press) / fs
    phase = 2 * np.pi * (f0 * t + (f1 - f0) * t ** 2 / (2 * press_s))
    press = A + depth * cal_max * np.sin(phase)
    return np.concatenate([np.zeros(n_hold), np.linspace(0.0, A, n_ramp), press,
                           np.linspace(press[-1], 0.0, n_ramp), np.zeros(n_hold)])


def press_from_v0(csv_path, fc=3.0):
    """V0 动态段 → 零相位滤波 → |ΔB| 目标曲线. 铁律: 先滤 (N,3) 向量再取 norm."""
    return np.linalg.norm(fft_lowpass(load_deltab_csv(csv_path), fc), axis=1)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_sim_loop.py -q` → 全绿。

- [ ] **Step 5: Commit**

`git add src/brushbot/sim_loop.py tests/test_sim_loop.py && git commit -m "feat(sim): synth_press swept-sine target and press_from_v0 zero-phase target" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"`

---

### Task 5: run_loop + 指标函数

**Files:**
- Modify: `src/brushbot/sim_loop.py`
- Test: `tests/test_sim_loop.py`

**Interfaces:**
- Consumes: `ZController`（Task 1）、`Plant`（Task 3）、目标曲线（Task 4）、滤波器（`update/reset` 契约）。
- Produces: `run_loop(ctrl, filt, g_d, plant) -> dict`，键：`t, g_d, dB_raw(n,3), dB_f(n,3), abs_f, z_cmd, z_ff, z_fb, frozen(bool), z_act, abs_true`；`rms_pct(res, noise_std) -> float`（接触段、%目标量程、以 abs_true 评）；`osc_index(res, f_cut=5.0, fs=FS) -> float`；`freeze_jump(res) -> float`（m）；`diverged(res, z_surface, calib_range_m) -> bool`。

- [ ] **Step 1: 写失败测试**

```python
from brushbot.sim_loop import diverged, freeze_jump, osc_index, rms_pct, run_loop
from brushbot.z_control import ZController
from brushbot.filter import OneEuroFilter


def _make(kp=0.3, ki=0.03, noise=None, **plant_kw):
    ctrl = ZController(_CAL_Z, _CAL_DB, kp=kp, ki=ki, noise_std=7.0)
    plant = Plant(_CAL_Z, _CAL_DB, noise=noise, **plant_kw)
    return ctrl, plant


def test_run_loop_open_arm_is_pure_feedforward():
    """开环臂 (kp=ki=0): z_fb≡0 且 z_cmd = z_surface + z_ff 逐点成立。

    注: res["z_ff"] 是 ZController.z_ff 属性 = 前馈 offset (m), 不含 z_surface。"""
    ctrl, plant = _make(kp=0.0, ki=0.0)
    g = synth_press(cal_max=250.0)
    res = run_loop(ctrl, None, g, plant)
    np.testing.assert_array_equal(res["z_fb"], 0.0)
    np.testing.assert_allclose(res["z_cmd"], 0.20 + res["z_ff"], atol=1e-12)


def test_run_loop_deterministic_same_seed():
    g = synth_press(cal_max=250.0)
    outs = []
    for _ in range(2):
        ctrl, plant = _make(noise=V0NoiseSource(IDLE_CSVS, seed=5)) if IDLE_CSVS \
            else _make()
        outs.append(run_loop(ctrl, OneEuroFilter(0.5, 0.03), g, plant))
    np.testing.assert_array_equal(outs[0]["z_cmd"], outs[1]["z_cmd"])


def test_run_loop_nan_chain_reaches_guard():
    """NaN 从 plant → 滤波透传 → 控制器 freeze 且 z_cmd 有限 (guard 链路)。"""
    class _NaNPlant:
        z_act, abs_true = 0.2, 0.0
        def __init__(self):
            self.k = 0
        def step(self, z_cmd):
            self.k += 1
            return np.full(3, np.nan) if self.k == 50 else np.array([100.0, 0.0, 0.0])
    ctrl = ZController(_CAL_Z, _CAL_DB)
    res = run_loop(ctrl, OneEuroFilter(0.5, 0.03), np.full(100, 150.0), _NaNPlant())
    assert np.isnan(res["abs_f"][49])
    assert np.isfinite(res["z_cmd"]).all()
    assert res["frozen"][49]


def test_run_loop_closed_loop_converges_constant():
    """恒定目标 + 默认增益 + 无噪声 plant: 末段误差 <5% (Phase 0 行为回归)。"""
    ctrl, plant = _make()
    res = run_loop(ctrl, None, np.full(300, 120.0), plant)
    tail = res["abs_true"][-50:]
    assert abs(tail.mean() - 120.0) / 120.0 < 0.05


def test_metrics_contract():
    res = {"g_d": np.array([0.0, 100.0, 100.0, 0.0]),
           "abs_true": np.array([0.0, 90.0, 110.0, 50.0]),
           "z_cmd": np.array([0.2, 0.201, 0.2, 0.201]),
           "frozen": np.array([True, False, False, True])}
    r = rms_pct(res, noise_std=7.0)                       # 接触段 = g_d≥21 的中间两点
    assert r == pytest.approx(np.sqrt((100.0 + 100.0) / 2) / 100.0 * 100.0)
    assert 0.0 <= osc_index(res) <= 1.0
    assert freeze_jump(res) == pytest.approx(1e-3)
    assert not diverged(res, 0.2, 0.005)
    bad = dict(res, z_cmd=np.array([0.2, 0.3, 0.2, 0.2]))
    assert diverged(bad, 0.2, 0.005)                      # 偏 0.1m > 2×5mm
```

（`test_run_loop_open_arm_is_pure_feedforward` 中间两行注释掉的试探行删除，只留最后一行断言——写测试时直接写成单断言版本。）

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_sim_loop.py -q` → ImportError `run_loop`。

- [ ] **Step 3: 实现**

```python
def run_loop(ctrl, filt, g_d, plant):
    """唯一闭环路径. filt=None → 无滤波臂; 开环臂 = ctrl 增益置零.

    滤波器实例整段连续运行, 永不 mid-run reset; NaN 原样透传到 ctrl guard.
    """
    n = len(g_d)
    res = {k: np.empty(n) for k in
           ("g_d", "abs_f", "z_cmd", "z_ff", "z_fb", "z_act", "abs_true")}
    res["dB_raw"] = np.empty((n, 3))
    res["dB_f"] = np.empty((n, 3))
    res["frozen"] = np.empty(n, dtype=bool)
    res["t"] = np.arange(n) / FS
    z_cmd = ctrl.z_surface
    for i in range(n):
        raw = plant.step(z_cmd)
        dB_f = filt.update(raw) if filt is not None else raw
        z_cmd = ctrl.step(dB_f, float(g_d[i]))
        res["dB_raw"][i] = raw
        res["dB_f"][i] = dB_f
        res["abs_f"][i] = np.linalg.norm(dB_f)
        res["g_d"][i] = g_d[i]
        res["z_cmd"][i] = z_cmd
        res["z_ff"][i] = ctrl.z_ff
        res["z_fb"][i] = ctrl.z_fb
        res["frozen"][i] = ctrl.frozen
        res["z_act"][i] = plant.z_act
        res["abs_true"][i] = plant.abs_true
    return res


def rms_pct(res, noise_std):
    """接触段 (g_d ≥ 3σ) 跟踪 RMS, % 目标量程. 以 plant 真值 abs_true 评."""
    m = res["g_d"] >= 3.0 * noise_std
    if not m.any():
        return float("nan")
    err = res["g_d"][m] - res["abs_true"][m]
    return float(np.sqrt(np.mean(err ** 2)) / res["g_d"].max() * 100.0)


def osc_index(res, f_cut=5.0, fs=FS):
    """z_cmd 交流功率中 >f_cut Hz 份额 (0-1). 稳定判定: ≤0.05 (spec §3.3)."""
    z = res["z_cmd"] - res["z_cmd"].mean()
    P = np.abs(np.fft.rfft(z)) ** 2
    f = np.fft.rfftfreq(len(z), d=1.0 / fs)
    tot = float(P[f > 0].sum())
    return float(P[f > f_cut].sum() / tot) if tot > 0 else 0.0


def freeze_jump(res):
    """freeze 切换点 ±5 拍窗内 |Δz_cmd| 单步最大值 (m); 无切换 → 0."""
    edges = np.nonzero(np.diff(res["frozen"].astype(int)))[0]
    dz = np.abs(np.diff(res["z_cmd"]))
    best = 0.0
    for e in edges:
        best = max(best, float(dz[max(0, e - 5):min(len(dz), e + 5)].max()))
    return best


def diverged(res, z_surface, calib_range_m):
    """z_cmd 非有限, 或偏离纸面超 2× 标定量程."""
    z = res["z_cmd"]
    return bool((~np.isfinite(z)).any()
                or np.abs(z - z_surface).max() > 2.0 * calib_range_m)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/ -q` → 全绿。

- [ ] **Step 5: Commit**

`git add src/brushbot/sim_loop.py tests/test_sim_loop.py && git commit -m "feat(sim): run_loop single closed-loop path + metrics (rms_pct, osc_index, freeze_jump, diverged)" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"`

---

### Task 6: demo_z_control.py 改用 run_loop（消除第二条闭环路径）

**Files:**
- Modify: `scripts/demo_z_control.py`

**Interfaces:**
- Consumes: `run_loop`、`Plant`（Task 3/5）、无量纲 `ZController`（Task 1）。
- Produces: 无（终端脚本）；`plot_result` 输入契约不变。

- [ ] **Step 1: 重写 `_run_demo`**

删除函数内的 slope/auto-gain 折算与手写循环，替换为：

```python
from brushbot.sim_loop import Plant, run_loop   # 文件头 import

def _run_demo(target_abs_dB, dt=0.01, kp=None, ki=None,
              calib_z_mm=None, calib_abs_dB=None):
    """闭环 demo: 合成标定 + sim_loop.run_loop (唯一闭环路径)."""
    if calib_z_mm is None or calib_abs_dB is None:
        cal = contact_sim.calibrate()
        calib_z_mm, calib_abs_dB = cal["z_mm"], cal["abs_dB"]
    cal_max = float(calib_abs_dB.max())
    noise_std = max(cal_max * 0.02, 1e-12)
    kw = {}
    if kp is not None:
        kw["kp"] = kp
    if ki is not None:
        kw["ki"] = ki
    ctrl = ZController(calib_z_mm, calib_abs_dB, dt=dt, noise_std=noise_std, **kw)
    target = np.asarray(target_abs_dB, dtype=float).copy()
    if target.max() > 0 and cal_max > 0:
        target *= 0.8 * cal_max / target.max()
    plant = Plant(calib_z_mm, calib_abs_dB, dt=dt)
    res = run_loop(ctrl, None, target, plant)
    return {"time": res["t"], "z_surface": ctrl.z_surface, "target": res["g_d"],
            "meas": res["abs_f"], "z_cmd": res["z_cmd"],
            "z_ff": ctrl.z_surface + res["z_ff"], "z_fb": res["z_fb"],
            "frozen": res["frozen"]}
```

注意：`ZController.z_ff` 属性返回的是 offset（m），Phase 0 demo 的 `plot_result` 期望 `z_ff` 为世界坐标（内部减 z_surface 画图），故映射时加回 `ctrl.z_surface`。`press_direction`/噪声不再需要（plant 无噪声，RMS 更干净）。

- [ ] **Step 2: 运行验证**

Run: `python scripts/demo_z_control.py --output z_control_demo.png`
Expected: 打印 `RMS tracking error (last 75%): X.X%`，X < 5（plant 现在含 τ=50ms + 2 拍延迟，数值与 Phase 0 的 2.1% 不必相同，但须 <5%）。打开图确认三面板正常、无振荡。

Run: `python -m pytest tests/ -q` → 全绿。

- [ ] **Step 3: Commit**

`git add scripts/demo_z_control.py && git commit -m "refactor(scripts): demo_z_control uses sim_loop.run_loop, drops external gain scaling" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"`

---

### Task 7: 层 1 增益扫描脚本 sweep_z_gains.py

**Files:**
- Create: `scripts/sweep_z_gains.py`
- Output: `docs/z-phase1-sweep.md` + `docs/assets/z-phase1-sweep-<slug>.png`（assets 已 gitignored）

**Interfaces:**
- Consumes: sim_loop 全部（Task 2–5）、`ZController`（Task 1）、`compare_filters.ema_freq_response`（同目录 import）、`ButterworthFilter.freq_response`。
- Produces: 报告含每滤波臂工作点 `(kp, ki, rms)` —— Task 8 的 CLI 输入；滤波器定稿候选结论。

- [ ] **Step 1: 写脚本**

```python
#!/usr/bin/env python3
"""层1: {滤波} × {kp, ki} 增益扫描 → 稳定边界 + 工作点 + 报告.

用法 (单行):
    python scripts/sweep_z_gains.py
    python scripts/sweep_z_gains.py --quick
    python scripts/sweep_z_gains.py --csv-dir delta_b_v0_20260724 --out docs/z-phase1-sweep.md

回答 spec §1 的 Q1 (滤波收益) 与 Q2 (稳定边界+裕度).
"""
import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from brushbot.filter import ButterworthFilter, OneEuroFilter  # noqa: E402
from brushbot.monitor.core import EMA                          # noqa: E402
from brushbot.sim_loop import (FS, Plant, V0NoiseSource, diverged, osc_index,  # noqa: E402
                               rms_pct, run_loop, synth_press)
from brushbot.z_control import ZController                     # noqa: E402
from compare_filters import ema_freq_response                  # noqa: E402  (同目录)

CALIB_Z = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
CALIB_DB = np.array([0.0, 50.0, 100.0, 150.0, 200.0, 250.0])
FILTERS = [
    ("none", None, None),
    ("EMA a=0.3", lambda: EMA(0.3), lambda f: ema_freq_response(0.3, f)),
    ("Butter fc=8", lambda: ButterworthFilter(8.0), ButterworthFilter(8.0).freq_response),
    ("OneEuro mc=0.5 b=0.03", lambda: OneEuroFilter(0.5, 0.03), None),  # 非线性: 无频域数
]
OSC_MAX = 0.05     # 稳定判定: osc_index ≤ 5% (spec §3.3 暂定值)
SEED = 42
TAU, N_DELAY = 0.05, 2


def run_cell(make_filter, kp, ki, sigma_f, g_d, csvs, tau=TAU, n_delay=N_DELAY):
    noise = V0NoiseSource(csvs, seed=SEED)
    plant = Plant(CALIB_Z, CALIB_DB, tau=tau, n_delay=n_delay, noise=noise)
    ctrl = ZController(CALIB_Z, CALIB_DB, kp=kp, ki=ki, noise_std=sigma_f)
    res = run_loop(ctrl, make_filter() if make_filter else None, g_d, plant)
    stable = (not diverged(res, ctrl.z_surface, CALIB_Z[-1] / 1000.0)
              and osc_index(res) <= OSC_MAX)
    return rms_pct(res, sigma_f), stable


def sweep(make_filter, kp_grid, ki_grid, sigma_f, g_d, csvs):
    rms = np.empty((len(kp_grid), len(ki_grid)))
    stable = np.empty_like(rms, dtype=bool)
    for i, kp in enumerate(kp_grid):
        for j, ki in enumerate(ki_grid):
            rms[i, j], stable[i, j] = run_cell(make_filter, kp, ki, sigma_f, g_d, csvs)
    return rms, stable


def working_point(rms, stable, kp_grid, ki_grid):
    """稳定且 +2 网格步 (≈2.5×kp / ≈3.7×ki, 保守 ≥2×裕度) 仍稳定者中取 RMS 最小.

    ki=0 行只查 kp 裕度. 返回 (i, j) 或 None."""
    best = None
    for i in range(len(kp_grid)):
        for j in range(len(ki_grid)):
            if not stable[i, j]:
                continue
            i2, j2 = i + 2, (j + 2 if ki_grid[j] > 0 else j)
            if i2 >= len(kp_grid) or j2 >= len(ki_grid) or not stable[i2, j2]:
                continue
            if best is None or rms[i, j] < rms[best]:
                best = (i, j)
    return best


def phase_margin_deg(kp, ki, freq_fn, tau=TAU, delay_s=(N_DELAY + 1) / FS):
    """线性臂解析相位裕度. L = (kp + ki/s)·执行器·延迟·滤波器 (S_cal 与 plant
    斜率互逆, calib_scale=1 时消掉). OneEuro 不适用 (spec 坑3)."""
    f = np.geomspace(0.01, 49.0, 4000)
    w = 2 * np.pi * f
    L = (kp + ki / (1j * w)) * np.exp(-1j * w * delay_s) / (1 + 1j * w * tau)
    if freq_fn is not None:
        L = L * freq_fn(f)
    idx = np.nonzero(np.abs(L) >= 1.0)[0]
    if len(idx) == 0:
        return float("inf")
    return float(180.0 + np.degrees(np.angle(L[idx[-1]])))


def sensitivity(make_filter, kp, ki, sigma_f, g_d, csvs):
    """工作点在 τ×延迟假设网格下的稳定性抽查 (spec §3.3)."""
    rows = []
    for tau in (0.02, 0.05, 0.1):
        for nd in (1, 2, 4):
            r, s = run_cell(make_filter, kp, ki, sigma_f, g_d, csvs, tau=tau, n_delay=nd)
            rows.append((tau, nd, r, s))
    return rows


def make_heatmap(rms, stable, kp_grid, ki_grid, wp, label, out_png):
    import matplotlib
    matplotlib.use("Agg")
    matplotlib.rcParams["font.sans-serif"] = [
        "Noto Sans CJK SC", "Noto Sans CJK HK", "Noto Sans CJK JP", "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7, 5))
    shown = np.where(stable, rms, np.nan)
    im = ax.imshow(shown, origin="lower", aspect="auto", cmap="viridis")
    ax.set(xticks=range(len(ki_grid)), yticks=range(len(kp_grid)),
           xticklabels=["%g" % k for k in ki_grid],
           yticklabels=["%g" % k for k in kp_grid],
           xlabel="ki (无量纲)", ylabel="kp (无量纲)",
           title="%s: 跟踪 RMS %% (灰=不稳定)" % label)
    ax.set_facecolor("0.8")
    if wp is not None:
        ax.plot(wp[1], wp[0], "r*", ms=16, label="工作点")
        ax.legend()
    fig.colorbar(im, ax=ax, label="RMS %")
    fig.tight_layout()
    fig.savefig(out_png, dpi=120)
    plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv-dir", default=str(ROOT / "delta_b_v0_20260724"))
    ap.add_argument("--out", default=str(ROOT / "docs" / "z-phase1-sweep.md"))
    ap.add_argument("--quick", action="store_true", help="缩小网格冒烟")
    args = ap.parse_args(argv)

    csvs = sorted(p for p in Path(args.csv_dir).glob("*.csv") if "idle" in p.stem)
    if not csvs:
        sys.exit("错误: %s 下没有 idle CSV" % args.csv_dir)
    if args.quick:
        kp_grid = np.geomspace(0.1, 1.0, 4)
        ki_grid = np.array([0.0, 0.03, 0.1])
    else:
        kp_grid = np.geomspace(0.05, 3.0, 10)
        ki_grid = np.concatenate([[0.0], np.geomspace(0.005, 0.5, 8)])
    g_d = synth_press(cal_max=CALIB_DB[-1])

    out_md = Path(args.out)
    asset_dir = out_md.parent / "assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for label, mk, freq_fn in FILTERS:
        sigma_f = V0NoiseSource(csvs, seed=SEED).filtered_sigma(mk)
        rms, stable = sweep(mk, kp_grid, ki_grid, sigma_f, g_d, csvs)
        wp = working_point(rms, stable, kp_grid, ki_grid)
        row = {"label": label, "sigma_f": sigma_f, "rms": rms, "stable": stable,
               "wp": wp, "pm": None, "sens": None}
        if wp is not None:
            kp, ki = kp_grid[wp[0]], ki_grid[wp[1]]
            row["pm"] = (phase_margin_deg(kp, ki, freq_fn)
                         if freq_fn is not None or label == "none" else None)
            row["sens"] = sensitivity(mk, kp, ki, sigma_f, g_d, csvs)
        slug = label.replace(" ", "").replace("=", "").replace(".", "")
        make_heatmap(rms, stable, kp_grid, ki_grid, wp, label,
                     asset_dir / ("z-phase1-sweep-%s.png" % slug))
        results.append(row)
        print(label, "wp=", None if wp is None else
              (kp_grid[wp[0]], ki_grid[wp[1]], rms[wp]))
    write_report(results, kp_grid, ki_grid, out_md)
    print("报告:", out_md)


if __name__ == "__main__":
    main()
```

**（2026-07-30 修订：双工作点）** `working_point` 除原规则（wp_P，实测落 ki=0）外，再以 ki>0 约束选出 wp_PI；`sensitivity` 与相位裕度两点都算。`write_report(results, kp_grid, ki_grid, out_md)` 生成 markdown：每臂一节（σ_f、wp_P 与 wp_PI 各自的 kp/ki/RMS、相位裕度或"非线性—时域裕度 2 网格步"、两点的敏感性 3×3 表、热力图标两星、ki=0 现象的盲区解释）；汇总表回答 Q1（各臂工作点 RMS vs "none" 臂 RMS）与 Q2（边界描述 + 裕度数）；注明：稳定判定 OSC_MAX=0.05、+2 网格步的实际倍数（kp ×2.48、ki ×3.73）、τ/n_delay 为假设值、裸态噪声乐观下界、OneEuro 定稿候选结论待层 2 确认。表格格式仿 `docs/filter-comparison.md`。

- [ ] **Step 2: 冒烟运行**

Run: `python scripts/sweep_z_gains.py --quick`
Expected: 4 臂各打印 wp（quick 网格小、边界外裕度查不到时 wp 可为 None——None 时放宽为 +1 步再跑一次确认脚本逻辑，正式跑用全网格）；`docs/z-phase1-sweep.md` 与 4 张 PNG 生成。

- [ ] **Step 3: 正式运行**

Run: `python scripts/sweep_z_gains.py`
Expected: 全网格 4×10×9=360 格，分钟级。检查报告：每臂有工作点与 RMS；"none" 臂 RMS 最差（滤波收益为正）；线性臂相位裕度 ≥45°（若 <45°，工作点规则已保证时域裕度，如实记录数字并在报告标注——不改判据）。

- [ ] **Step 4: 全套测试回归**

Run: `python -m pytest tests/ -q` → 全绿。

- [ ] **Step 5: Commit**

`git add scripts/sweep_z_gains.py docs/z-phase1-sweep.md && git commit -m "feat(scripts): layer-1 gain sweep — stability boundary, working points, phase margins, sensitivity" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"`

---

### Task 8: 层 2 开环 vs 闭环扰动对比 compare_z_arms.py

**Files:**
- Create: `scripts/compare_z_arms.py`
- Output: `docs/z-phase1-results.md` + `docs/assets/z-phase1-arms-*.png`

**Interfaces:**
- Consumes: sim_loop 全部；层 1 报告的工作点（CLI `--kp --ki --filter` 传入）。
- Produces: Q3/Q4 的正式答案表；freeze 毛刺判据结论（触发 spec §2.4 fallback 与否）。

- [ ] **Step 1: 写脚本**

```python
#!/usr/bin/env python3
"""层2: {开环, 闭环-P, 闭环-PI} × {扰动场景} 对比 → 论文数字 + freeze 毛刺检查.

用法 (单行, 两组 kp/ki 取层1报告的 wp_P 与 wp_PI, spec §3.3 双工作点修订):
    python scripts/compare_z_arms.py --kp-p 1.21 --ki-p 0 --kp-pi 1.21 --ki-pi 0.03 --filter "EMA a=0.3"

回答 spec §1 的 Q3 (开环 vs 闭环-P vs 闭环-PI) 与 Q4 (freeze 毛刺, PI 臂为主).
"""
import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from brushbot.filter import ButterworthFilter, OneEuroFilter  # noqa: E402
from brushbot.monitor.core import EMA                          # noqa: E402
from brushbot.sim_loop import (FS, Plant, V0NoiseSource, freeze_jump, osc_index,  # noqa: E402
                               press_from_v0, rms_pct, run_loop, synth_press)
from brushbot.z_control import ZController                     # noqa: E402

CALIB_Z = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
CALIB_DB = np.array([0.0, 50.0, 100.0, 150.0, 200.0, 250.0])
SEED = 42
MAKE_FILTER = {
    "none": None,
    "EMA a=0.3": lambda: EMA(0.3),
    "Butter fc=8": lambda: ButterworthFilter(8.0),
    "OneEuro mc=0.5 b=0.03": lambda: OneEuroFilter(0.5, 0.03),
}
# t_step=4.0s 落在提按段 (0.8–6.8s) 中部
SCENARIOS = [
    ("baseline", {}),
    ("calib x0.8", {"calib_scale": 0.8}),
    ("calib x1.2", {"calib_scale": 1.2}),
    ("paper +0.5mm", {"paper_step": (4.0, +0.5e-3)}),
    ("paper -0.5mm", {"paper_step": (4.0, -0.5e-3)}),
    ("drift +1uT/s", {"drift_rate": +1.0}),
    ("drift -1uT/s", {"drift_rate": -1.0}),
]
# (2026-07-30 二次修订) 多笔画场景另行处理, 不进 SCENARIOS 矩阵:
#   g_multi = np.concatenate([synth_press(cal_max=CALIB_DB[-1])] * 8), plant calib_scale=0.8
#   臂: open / P / PI(ki ∈ {wp_PI 0.005} ∪ kp=wp 行裕度合规的更大稳定 ki 候选, 由 --ki-multi 传入)
#   指标: 每笔 t∈[5.8,6.8)+7.6·k 窗均偏差随笔序 k 的收敛曲线; 判据 = |偏差|≤2σ_f 所需笔数
#   报告: 收敛曲线图 + "Task 9 回填 ki 推荐 = 裕度合规且收敛最快者"


def run_arm(kp, ki, mk, sigma_f, g_d, csvs, plant_kw):
    noise = V0NoiseSource(csvs, seed=SEED)
    plant = Plant(CALIB_Z, CALIB_DB, noise=noise, **plant_kw)
    ctrl = ZController(CALIB_Z, CALIB_DB, kp=kp, ki=ki, noise_std=sigma_f)
    return run_loop(ctrl, mk() if mk else None, g_d, plant), sigma_f


def steady_bias(res):
    """提按末 1s (t∈[5.8, 6.8)) 窗均偏差 (µT, 以真值评).

    该窗口跨越 ~2.5–3Hz 扫频正弦约 3 个周期, 逐样本误差本身有 ±dozens µT 量级的
    跟踪摆动 (并非真正静止的"稳态"); 窗口均值是多周期平均, 幸存下来的只是偏差
    (bias) 分量的估计, 不是瞬时稳态误差。"""
    m = (res["t"] >= 5.8) & (res["t"] < 6.8)
    return float((res["g_d"][m] - res["abs_true"][m]).mean())


def recovery_time_s(res, t_step, sigma_f):
    """t_step 后, 接触段内 (g_d >= 3σ) |误差| 首次连续 0.3s 落回 ±2σ 带内的耗时 (s).

    仅在接触段内评估: ok = err < 2σ 只在 g_d>=3σ 的样本上判定, 接触段外 (收笔/
    悬空, g_d<3σ) 的样本一律不计入 (2026-07-30 修正: 原版收笔段自动满足判据,
    量的是笔画结束). 若在 t_step 后到接触段最后一个样本前始终未凑满连续 0.3s,
    返回 inf (接触段内恢复 → 秒数; 收笔前未恢复 → inf)。"""
    err = np.abs(res["g_d"] - res["abs_true"])
    in_contact = res["g_d"] >= 3.0 * sigma_f
    start = int(t_step * FS)
    need = int(0.3 * FS)
    contact_after = np.nonzero(in_contact[start:])[0]
    if len(contact_after) == 0:
        return float("inf")
    end = start + int(contact_after[-1])
    run = 0
    for i in range(start, end + 1):
        if not in_contact[i]:
            run = 0
            continue
        run = run + 1 if err[i] < 2.0 * sigma_f else 0
        if run >= need:
            return (i - need + 1 - start) / FS
    return float("inf")


def glitch_verdict(res):
    """Q4 判据 (spec §3.4): 切换处单步跳变 ≤ 正常段 p99×2 且 ≤0.2mm,
    且切换后 0.5s 无新增振荡 (整段 osc_index ≤0.05 代理)."""
    dz = np.abs(np.diff(res["z_cmd"]))
    p99 = float(np.percentile(dz[~np.isnan(dz)], 99))
    fj = freeze_jump(res)
    return {"jump_m": fj, "p99_m": p99,
            "ok": fj <= max(2 * p99, 0.0) + 1e-15 and fj <= 0.2e-3
                  and osc_index(res) <= 0.05}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kp-p", type=float, required=True, help="wp_P 的 kp")
    ap.add_argument("--ki-p", type=float, required=True, help="wp_P 的 ki (通常 0)")
    ap.add_argument("--kp-pi", type=float, required=True, help="wp_PI 的 kp")
    ap.add_argument("--ki-pi", type=float, required=True, help="wp_PI 的 ki (>0)")
    ap.add_argument("--filter", default="OneEuro mc=0.5 b=0.03",
                    choices=list(MAKE_FILTER))
    ap.add_argument("--csv-dir", default=str(ROOT / "delta_b_v0_20260724"))
    ap.add_argument("--out", default=str(ROOT / "docs" / "z-phase1-results.md"))
    args = ap.parse_args(argv)

    csvs = sorted(p for p in Path(args.csv_dir).glob("*.csv") if "idle" in p.stem)
    mk = MAKE_FILTER[args.filter]
    sigma_f = V0NoiseSource(csvs, seed=SEED).filtered_sigma(mk)
    g_d = synth_press(cal_max=CALIB_DB[-1])

    arms = (("open", 0.0, 0.0), ("closed-P", args.kp_p, args.ki_p),
            ("closed-PI", args.kp_pi, args.ki_pi))
    rows = []
    for name, plant_kw in SCENARIOS:
        for arm, kp, ki in arms:
            res, _ = run_arm(kp, ki, mk, sigma_f, g_d, csvs, plant_kw)
            rec = (recovery_time_s(res, plant_kw["paper_step"][0], sigma_f)
                   if "paper_step" in plant_kw else None)
            rows.append({"scenario": name, "arm": arm,
                         "rms": rms_pct(res, sigma_f), "bias": steady_bias(res),
                         "recovery": rec, "glitch": glitch_verdict(res),
                         "res": res})
    # 真实感目标复核: baseline 双臂再跑一条 press_from_v0
    dyn = sorted(p for p in Path(args.csv_dir).glob("*.csv") if "idle" not in p.stem)
    v0_rows = []
    if dyn:
        g_v0 = press_from_v0(dyn[0])
        g_v0 = g_v0 * (0.8 * CALIB_DB[-1] / max(g_v0.max(), 1e-9))
        for arm, kp, ki in arms:
            res, _ = run_arm(kp, ki, mk, sigma_f, g_v0, csvs, {})
            v0_rows.append({"arm": arm, "rms": rms_pct(res, sigma_f)})
    write_report(rows, v0_rows, args, sigma_f, Path(args.out))
    print("报告:", args.out)


if __name__ == "__main__":
    main()
```

`write_report` 生成 `docs/z-phase1-results.md`：Q3 主表（场景 × 三臂 → RMS% / 窗均偏差 µT（提按末 1s 均值，附口径注意：窗口跨 ~3 个扫频周期，均值是多周期平均后幸存的偏差分量）/ 恢复时间 s（仅接触段内判定，2026-07-30 修正后语义）），须讲清两个口径差的因果（spec §3.4 修订）：恒定偏差下 P 臂稳态残差 e_ss=d/(1+kp) 只消 ~55% 而 PI→0（该"扣除 baseline 后的纯扰动残留比例"表为 Q3 headline 对比结论）；drift 行加"诚实负面对照：P 臂被骗 ~45%、PI 臂被骗 100%（抗扰与被骗同源），开环免疫——差分测量的论据"注释；Q4 节（baseline 两个闭环臂的 freeze_jump、p99、判据结论，**PI 臂为主**；不通过 → 显著标注"触发 spec §2.4 fallback：Kp 纳入 freeze，需回 Task 9 前处理"）；波形图两张（paper step 恢复对比、起笔/收笔 freeze 放大）存 `docs/assets/z-phase1-arms-paperstep.png` / `-freeze.png`（matplotlib Agg + CJK 字体设置抄 `sweep_z_gains.make_heatmap` 开头）；文末 caveat：裸态噪声乐观下界、τ/n_delay 假设值、结论限"裸态仿真条件"。

- [ ] **Step 2: 运行（工作点取自层 1 报告）**

Run: `python scripts/compare_z_arms.py --kp-p <层1 wp_P kp> --ki-p <层1 wp_P ki> --kp-pi <层1 wp_PI kp> --ki-pi <层1 wp_PI ki> --filter "<层1胜出滤波>"`
Expected: 报告生成。核对叙事方向：calib/paper 场景 PI 臂 ≈ 全补偿、P 臂 ~55% 部分补偿、开环不补；drift 场景开环 bias≈0、P 臂被拉偏 ~45%、PI 臂被拉偏 ~100%；baseline 三臂接近。freeze 判据出结论。若 Q4 不通过：按 spec §2.4 在 `z_control.py` 的 `step()` 中把 Kp 项改为 `(0.0 if self._frozen else self._kp) * self._s_cal * e`，重跑 Task 7 正式扫描 + 本任务，并在两份报告标注 fallback 已触发。

- [ ] **Step 3: 全套测试回归**

Run: `python -m pytest tests/ -q` → 全绿。

- [ ] **Step 4: Commit**

`git add scripts/compare_z_arms.py docs/z-phase1-results.md && git commit -m "feat(scripts): layer-2 open vs closed loop disturbance comparison + freeze glitch verdict" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"`

---

### Task 9: 回填默认增益 + 选型定稿 + 文档/记忆收尾

**Files:**
- Modify: `src/brushbot/z_control.py`（默认 kp/ki）
- Modify: `docs/handoff-z-phase1.md`（状态行）
- Modify: `docs/superpowers/specs/2026-07-30-z-control-phase1-design.md`（§2.4 裁决结果、§3.1 回填值）
- Modify: `/home/ethan/.claude/projects/-home-ethan-FYP/memory/filter-selection-provisional.md` + `MEMORY.md`

**Interfaces:**
- Consumes: 层 1/层 2 报告的工作点与定稿结论。

- [ ] **Step 1: 回填默认增益**

把 `ZController.__init__` 的 `kp=0.3, ki=0.03` 改为层 1 胜出滤波臂的 **wp_PI** 值（积分是设计意图，ki=0 的 wp_P 只作层 2 对照口径），docstring 注明"默认值 = Phase 1 层 1 扫描工作点 wp_PI（裸态仿真，`docs/z-phase1-sweep.md`）"。

- [ ] **Step 2: 全套测试回归**

Run: `python -m pytest tests/ -q`
Expected: 全绿（`test_step_tracks_constant` 与 `test_run_loop_closed_loop_converges_constant` 用默认值，需在新默认下仍收敛；不收敛说明工作点异常，回查层 1）。

- [ ] **Step 3: 文档与记忆收尾**

- spec §2.4：写入 freeze 裁决结果（Kp 保持 / fallback 已触发，附 freeze_jump 数字）。
- spec §3.1：标注回填后的默认值。
- `docs/handoff-z-phase1.md` 头部状态行改为"Phase 1 已完成（裸态仿真），见 z-phase1-sweep.md / z-phase1-results.md"，§3.4 表格各行标注结果文档。
- 记忆 `filter-selection-provisional.md`：写入定稿结论（OneEuro 定稿或退 EMA0.3 + 数字），保留"装配态复测前勿最终定稿"约束；`MEMORY.md` 索引行同步。

- [ ] **Step 4: Commit**

`git add -A src/brushbot/z_control.py docs/handoff-z-phase1.md docs/superpowers/specs/2026-07-30-z-control-phase1-design.md && git commit -m "feat(z-control): backfill default gains from phase-1 sweep; finalize filter verdict and handoff status" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"`

（记忆文件在仓库外，不入 git。）

---

## 验收总检（对照 spec §1）

- Q1/Q2 → `docs/z-phase1-sweep.md`；Q3/Q4 → `docs/z-phase1-results.md`；四问全部有数字。
- `python -m pytest tests/ -q` 全绿。
- 交付物对照 spec §7 清单逐项勾。
