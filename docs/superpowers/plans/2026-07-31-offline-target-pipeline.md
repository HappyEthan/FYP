# 离线目标曲线管线（§3.2）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建成"示范 CSV（ΔB+XY）→ 零相位滤波 → 切笔画 → 弧长重参数化 → 标定反查 → StrokePlan"离线管线，含带真值的合成示范生成器与端到端两臂验收。

**Architecture:** 新建 `strokeplan.py`（数据契约 + 两个导出方法）与 `demo_pipeline.py`（纯函数流水线，复用 `sim_loop.fft_lowpass`）；`z_control.py` 提取共享反查函数；scripts 下合成生成器 + E2E 验收脚本。

**Tech Stack:** 纯 numpy + matplotlib(Agg)，零新依赖，pytest。

**Spec:** `docs/superpowers/specs/2026-07-31-offline-target-pipeline-design.md`（判据来源，实现时对照）。

## Global Constraints

- 零新依赖，`pyproject.toml` 不动；`src/` 不得 import `scripts/`（scripts 可 import src 与同目录）。
- FS=100 Hz 贯穿；计算核心 SI 单位（米），带后缀字段（`calib_z_mm`、`dBx_uT`）例外并在边界一次换算。
- 铁律：先滤 (N,3) 向量再取 norm。
- **离线 NaN 纪律与实时相反**：坏数据当场报错（指出位置），不透传。
- 示范 CSV 列（顺序固定）：`t_us,t_s,dBx_uT,dBy_uT,dBz_uT,x_m,y_m`。
- 终端命令一律单行；git commit 用多个 `-m`，结尾 trailer：`Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。
- 每任务完成时 `python -m pytest tests/ -q` 全绿（当前基线 130 项）。
- 测试共享标定表：`_CALIB_Z = [0..5] mm ↔ _CALIB_DB = [0..250] µT`（`test_z_control.py` 现有）。
- V0 噪声数据 `delta_b_v0_20260724/*.csv`（idle 文件名含 "idle"）；用到它的测试沿用 `needs_v0` skip 惯例。

---

### Task 1: strokeplan.py — 数据契约 + npz 往返

**Files:**
- Create: `src/brushbot/strokeplan.py`
- Test: `tests/test_strokeplan.py`（新建）

**Interfaces:**
- Produces: `Stroke(s (M,), xy (M,2) m, g_press (M,) µT, z_ff (M,) m)`；`StrokePlan(strokes: list[Stroke], meta: dict)`，方法 `save(path)`、类方法 `load(path) -> StrokePlan`。常量 `FS = 100.0`。后续所有任务依赖这些名字。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_strokeplan.py`：

```python
import numpy as np
import pytest

from brushbot.strokeplan import FS, Stroke, StrokePlan


def _stroke(m=50, seed=0):
    rng = np.random.default_rng(seed)
    s = np.linspace(0.0, 1.0, m)
    return Stroke(s=s, xy=rng.normal(0.02, 0.01, (m, 2)),
                  g_press=rng.uniform(0.0, 200.0, m),
                  z_ff=rng.uniform(0.0, 0.005, m))


def _plan2():
    return StrokePlan(strokes=[_stroke(seed=1), _stroke(seed=2)],
                      meta={"fc": 3.0, "M": 50, "sigma": 2.5})


def test_npz_roundtrip(tmp_path):
    plan = _plan2()
    p = tmp_path / "plan.npz"
    plan.save(p)
    back = StrokePlan.load(p)
    assert len(back.strokes) == 2
    for a, b in zip(plan.strokes, back.strokes):
        np.testing.assert_array_equal(a.s, b.s)
        np.testing.assert_array_equal(a.xy, b.xy)
        np.testing.assert_array_equal(a.g_press, b.g_press)
        np.testing.assert_array_equal(a.z_ff, b.z_ff)
    assert back.meta == plan.meta


def test_empty_plan_roundtrip(tmp_path):
    p = tmp_path / "empty.npz"
    StrokePlan(strokes=[], meta={}).save(p)
    assert StrokePlan.load(p).strokes == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_strokeplan.py -q`
Expected: collection error（`brushbot.strokeplan` 不存在）。

- [ ] **Step 3: 实现**

新建 `src/brushbot/strokeplan.py`：

```python
"""StrokePlan: 离线目标管线的输出契约, 开环/闭环两臂的共同前馈来源.

Stroke 单位纪律: xy/z_ff 为米 (SI), g_press 为 µT (带后缀量纲); s 为归一化弧长.
见 docs/superpowers/specs/2026-07-31-offline-target-pipeline-design.md
"""
import json
from dataclasses import dataclass, field

import numpy as np

FS = 100.0


@dataclass
class Stroke:
    s: np.ndarray        # (M,) 均匀弧长网格 [0,1]
    xy: np.ndarray       # (M,2) 米
    g_press: np.ndarray  # (M,) µT, 零相位滤波后的目标手感
    z_ff: np.ndarray     # (M,) m, 前馈压深 offset (不含 z_surface)


@dataclass
class StrokePlan:
    strokes: list
    meta: dict = field(default_factory=dict)

    def save(self, path):
        arrays = {"n_strokes": np.array(len(self.strokes)),
                  "meta_json": np.array(json.dumps(self.meta))}
        for i, st in enumerate(self.strokes):
            arrays["s%d_s" % i] = np.asarray(st.s, float)
            arrays["s%d_xy" % i] = np.asarray(st.xy, float)
            arrays["s%d_g" % i] = np.asarray(st.g_press, float)
            arrays["s%d_z" % i] = np.asarray(st.z_ff, float)
        np.savez(path, **arrays)

    @classmethod
    def load(cls, path):
        d = np.load(path, allow_pickle=False)
        n = int(d["n_strokes"])
        strokes = [Stroke(s=d["s%d_s" % i], xy=d["s%d_xy" % i],
                          g_press=d["s%d_g" % i], z_ff=d["s%d_z" % i])
                   for i in range(n)]
        return cls(strokes=strokes, meta=json.loads(str(d["meta_json"])))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_strokeplan.py -q` → 2 passed；`python -m pytest tests/ -q` → 全绿（130+2）。

- [ ] **Step 5: Commit**

`git add src/brushbot/strokeplan.py tests/test_strokeplan.py && git commit -m "feat(plan): StrokePlan/Stroke dataclasses with lossless npz round-trip" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"`

---

### Task 2: StrokePlan 导出 — to_waypoints + to_gd_series + B1 兼容

**Files:**
- Modify: `src/brushbot/strokeplan.py`
- Test: `tests/test_strokeplan.py`

**Interfaces:**
- Consumes: Task 1 的 Stroke/StrokePlan；`brushbot.controller.OpenLoopController(waypoints, speed, fixed_ori)`（`.step(State) -> Command`，`State(tcp_pose, g_meas, t)`）。
- Produces: `StrokePlan.to_waypoints(z_surface=0.20, lift=0.015) -> list[tuple[float,float,float]]`；`StrokePlan.to_gd_series(stroke_duration_s, fs=FS, gap_s=0.5) -> (g_d (T,), xy (T,2))`。T = n_strokes × (round(duration·fs) + round(gap·fs))——**每笔后都跟一段悬空**（含最后一笔，给 freeze 收尾，与 synth_press 尾部悬空同构）。

- [ ] **Step 1: 写失败测试**

`tests/test_strokeplan.py` 追加：

```python
def test_waypoints_structure():
    plan = _plan2()
    wps = plan.to_waypoints(z_surface=0.20, lift=0.015)
    m = len(plan.strokes[0].s)
    assert len(wps) == 2 * (m + 2)                      # 每笔: 进入 + M + 抬笔
    x0, y0 = plan.strokes[0].xy[0]
    assert wps[0] == pytest.approx((x0, y0, 0.215))     # 悬空进入点
    assert wps[1][2] == pytest.approx(0.20 + plan.strokes[0].z_ff[0])
    assert wps[m + 1][2] == pytest.approx(0.215)        # 抬笔点
    zs = np.array([w[2] for w in wps])
    assert (zs >= 0.20 - 1e-12).all() and (zs <= 0.215 + 1e-12).all()


def test_gd_series_structure():
    plan = _plan2()
    g_d, xy = plan.to_gd_series(stroke_duration_s=2.0, fs=100.0, gap_s=0.5)
    n_st, n_gap = 200, 50
    assert len(g_d) == len(xy) == 2 * (n_st + n_gap)
    assert (g_d >= 0).all()
    np.testing.assert_array_equal(g_d[n_st:n_st + n_gap], 0.0)   # 笔间悬空
    np.testing.assert_array_equal(g_d[-n_gap:], 0.0)             # 尾部悬空
    assert g_d[0] == pytest.approx(plan.strokes[0].g_press[0])


def test_waypoints_drive_openloop_controller():
    """B1 兼容 (spec Q4): OpenLoopController 原样消费 to_waypoints."""
    from brushbot.controller import OpenLoopController
    from brushbot.types import State
    ctrl = OpenLoopController(_plan2().to_waypoints(), speed=0.02,
                              fixed_ori=(0.0, 0.0, 0.0))
    for i in range(50):
        cmd = ctrl.step(State(tcp_pose=(0, 0, 0, 0, 0, 0), g_meas=0.0, t=i * 0.01))
        x, y, z = cmd.tcp_pose[:3]
        assert np.isfinite([x, y, z]).all() and 0.19 <= z <= 0.22
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_strokeplan.py -q` → AttributeError（无 to_waypoints）。

- [ ] **Step 3: 实现**

`strokeplan.py` 的 `StrokePlan` 追加两个方法：

```python
    def to_waypoints(self, z_surface=0.20, lift=0.015):
        """开环路点 (CalliRewrite 式 baseline): 每笔 悬空进入 -> M 点 -> 抬笔.

        输出裸 (x,y,z) 列表 (世界系, 米), OpenLoopController 零改动消费."""
        wps = []
        for st in self.strokes:
            x0, y0 = (float(st.xy[0, 0]), float(st.xy[0, 1]))
            xe, ye = (float(st.xy[-1, 0]), float(st.xy[-1, 1]))
            wps.append((x0, y0, z_surface + lift))
            for (x, y), z in zip(st.xy, st.z_ff):
                wps.append((float(x), float(y), z_surface + float(z)))
            wps.append((xe, ye, z_surface + lift))
        return wps

    def to_gd_series(self, stroke_duration_s, fs=FS, gap_s=0.5):
        """闭环目标: 每笔匀速播放 g_press(s), 每笔后接 g_d=0 悬空段 (含最后一笔).

        悬空段 xy 从本笔终点线性过渡到下一笔起点 (末笔停在原地).
        返回 (g_d (T,), xy (T,2)), 可直接喂 sim_loop.run_loop."""
        n_st = int(round(stroke_duration_s * fs))
        n_gap = int(round(gap_s * fs))
        t_norm = np.linspace(0.0, 1.0, n_st)
        frac = np.linspace(0.0, 1.0, n_gap)[:, None]
        g_parts, xy_parts = [], []
        for k, st in enumerate(self.strokes):
            g_parts.append(np.interp(t_norm, st.s, st.g_press))
            xy_parts.append(np.column_stack(
                [np.interp(t_norm, st.s, st.xy[:, 0]),
                 np.interp(t_norm, st.s, st.xy[:, 1])]))
            last = np.asarray(st.xy[-1], float)
            nxt = (np.asarray(self.strokes[k + 1].xy[0], float)
                   if k + 1 < len(self.strokes) else last)
            g_parts.append(np.zeros(n_gap))
            xy_parts.append(last[None, :] * (1.0 - frac) + nxt[None, :] * frac)
        return np.concatenate(g_parts), np.vstack(xy_parts)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_strokeplan.py -q` → 5 passed；`python -m pytest tests/ -q` → 全绿。

- [ ] **Step 5: Commit**

`git add src/brushbot/strokeplan.py tests/test_strokeplan.py && git commit -m "feat(plan): to_waypoints (open-loop arm, B1-compatible) and to_gd_series (closed-loop arm) exports" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"`

---

### Task 3: z_control.py — 提取共享反查 calib_lookup_z

**Files:**
- Modify: `src/brushbot/z_control.py`
- Test: `tests/test_z_control.py`

**Interfaces:**
- Produces: 模块级 `calib_lookup_z(g, calib_z_mm, calib_abs_dB) -> z_offset`（g 标量→float，(K,) 数组→(K,) 数组；单位 m；内部按 abs_dB 排序；低于下界→0.0，超上界→最大压深）。`ZController` 行为完全不变（委托此函数）。Task 5 的管线依赖它。

- [ ] **Step 1: 写失败测试**

`tests/test_z_control.py` 追加：

```python
def test_calib_lookup_z_matches_controller_and_vectorizes():
    from brushbot.z_control import calib_lookup_z
    ctrl = ZController(_CALIB_Z, _CALIB_DB, dt=0.01)
    for g in (-10.0, 0.0, 75.0, 150.0, 999.0):
        assert calib_lookup_z(g, _CALIB_Z, _CALIB_DB) == pytest.approx(
            ctrl._z_ff_lookup(g))
    arr = calib_lookup_z(np.array([0.0, 150.0, 999.0]), _CALIB_Z, _CALIB_DB)
    np.testing.assert_allclose(arr, [0.0, 0.003, 0.005])
    # 非单调标定输入同样正确 (排序在函数内)
    shuffled = np.array([2, 0, 4, 1, 5, 3])
    assert calib_lookup_z(150.0, _CALIB_Z[shuffled], _CALIB_DB[shuffled]) \
        == pytest.approx(0.003)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_z_control.py -q` → ImportError `calib_lookup_z`。

- [ ] **Step 3: 实现**

`z_control.py` 在 `ZController` 类定义前追加模块级函数，并让 `_z_ff_lookup` 委托：

```python
def calib_lookup_z(g, calib_z_mm, calib_abs_dB):
    """标定反查: 目标 |ΔB| (µT) -> 压深 offset (m). 全项目唯一实现.

    内部按 abs_dB 排序 (容忍非单调标定输入); 低于下界 -> 0.0, 超上界 -> 最大压深
    (饱和保护). g 为标量返回 float, 为数组返回同形状数组.
    ZController 与离线管线 (demo_pipeline) 共用本函数."""
    abs_dB = np.asarray(calib_abs_dB, dtype=float)
    z_m = np.asarray(calib_z_mm, dtype=float) / 1000.0
    idx = np.argsort(abs_dB)
    out = np.interp(g, abs_dB[idx], z_m[idx], left=0.0, right=float(z_m[idx][-1]))
    return float(out) if np.isscalar(g) or np.ndim(g) == 0 else out
```

`ZController` 改为**真委托**（不留第二份 interp 副本）：`__init__` 的排序段同时保留 mm 口径的已排序表，`_z_ff_lookup` 直接调用公开函数：

```python
# __init__ 排序段追加一行 (原 self._calib_dB / self._z_offset_m 保留, s_cal 计算不变):
        self._calib_z_mm_sorted = np.asarray(calib_z_mm, dtype=float)[sort_idx]

    def _z_ff_lookup(self, g_d: float) -> float:
        """|ΔB| (μT) → z_offset (m). 委托 calib_lookup_z (全项目唯一反查实现)."""
        return float(calib_lookup_z(g_d, self._calib_z_mm_sorted, self._calib_dB))
```

（对已排序数组再 argsort 是恒等置换，行为逐位不变；每拍对 6 元素 argsort 的开销在 100 Hz 下可忽略。等价性由 Step 1 测试钉死。）

- [ ] **Step 4: 跑全套测试确认通过**

Run: `python -m pytest tests/ -q` → 全绿（+1）。

- [ ] **Step 5: Commit**

`git add src/brushbot/z_control.py tests/test_z_control.py && git commit -m "feat(z-control): public calib_lookup_z shared by controller and offline pipeline" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"`

---

### Task 4: demo_pipeline.py — 载入、σ 估计、切笔画

**Files:**
- Create: `src/brushbot/demo_pipeline.py`
- Test: `tests/test_demo_pipeline.py`（新建）

**Interfaces:**
- Produces: `DEMO_COLS`（7 列名 tuple）；`load_demo(csv_path) -> {"t": (N,), "xy": (N,2), "dB": (N,3)}`；`estimate_sigma(g_clean, fs=100.0, head_s=0.5) -> float`；`segment_strokes(g_clean, sigma, fs=100.0, min_len_s=0.3) -> (segs: list[(start,end)], n_dropped: int)`（end 为开区间）。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_demo_pipeline.py`：

```python
import numpy as np
import pytest

from brushbot.demo_pipeline import (DEMO_COLS, estimate_sigma, load_demo,
                                    segment_strokes)

FS = 100.0


def _write_csv(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        f.write(",".join(DEMO_COLS) + "\n")
        for r in rows:
            f.write(",".join("%.9g" % v for v in r) + "\n")


def _rows(n=100, dB=(1.0, 2.0, 3.0)):
    return [(i * 1e4, i * 0.01, *dB, 0.001 * i, 0.0) for i in range(n)]


def test_load_demo_ok(tmp_path):
    p = tmp_path / "demo.csv"
    _write_csv(p, _rows())
    d = load_demo(p)
    assert d["xy"].shape == (100, 2) and d["dB"].shape == (100, 3)
    assert d["dB"][0, 2] == pytest.approx(3.0)


def test_load_demo_missing_xy_columns(tmp_path):
    p = tmp_path / "v0_style.csv"
    with open(p, "w", encoding="utf-8") as f:
        f.write("t_us,t_s,dBx_uT,dBy_uT,dBz_uT\n0,0,1,2,3\n1,0.01,1,2,3\n")
    with pytest.raises(ValueError, match="x_m"):
        load_demo(p)


def test_load_demo_nan_reports_row(tmp_path):
    p = tmp_path / "bad.csv"
    rows = _rows()
    rows[7] = (7e4, 0.07, float("nan"), 2.0, 3.0, 0.007, 0.0)
    _write_csv(p, rows)
    with pytest.raises(ValueError, match="9"):        # 表头 1 行 + 0 始下标 7 → 第 9 行
        load_demo(p)


def test_estimate_sigma_from_quiet_head():
    rng = np.random.default_rng(0)
    g = np.concatenate([np.abs(rng.normal(0, 2.0, 60)),
                        150.0 + rng.normal(0, 2.0, 400)])
    assert estimate_sigma(g, fs=FS, head_s=0.5) == pytest.approx(
        g[:50].std(), rel=1e-9)


def test_estimate_sigma_rejects_loud_head():
    rng = np.random.default_rng(1)
    g = np.abs(rng.normal(100.0, 40.0, 400))          # 一上来就在写
    with pytest.raises(ValueError, match="悬空"):
        estimate_sigma(g, fs=FS)


def test_segment_strokes_finds_runs_and_drops_short():
    sigma = 2.0                                        # 3σ = 6
    g = np.zeros(1000)
    g[100:400] = 100.0                                 # 笔 1: 3.0s
    g[500:520] = 100.0                                 # 过短 (0.2s < 0.3s) → 丢
    g[600:950] = 100.0                                 # 笔 2: 3.5s
    segs, dropped = segment_strokes(g, sigma, fs=FS, min_len_s=0.3)
    assert segs == [(100, 400), (600, 950)]
    assert dropped == 1


def test_segment_strokes_merges_chatter_and_gates_noise_peaks():
    """(2026-07-31 二次修订) 边界抖动并入主段; 低峰值噪声游走静默弃置不计数."""
    sigma = 2.0
    g = np.zeros(1000)
    g[100:400] = 100.0
    g[404:412] = 100.0        # 边界抖动: 间隙 4 拍 < merge_gap → 并入主段
    g[600:625] = 7.0          # 噪声游走: 超 3σ=6 但峰值 < 6σ=12 → 静默弃置
    segs, dropped = segment_strokes(g, sigma, fs=FS)
    assert segs == [(100, 412)]
    assert dropped == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_demo_pipeline.py -q` → collection error（模块不存在）。

- [ ] **Step 3: 实现**

新建 `src/brushbot/demo_pipeline.py`：

```python
"""离线目标曲线管线: 示范 CSV (ΔB+XY 同步) -> StrokePlan.

纪律 (与实时链路相反): 离线数据必须干净 -- 坏数据当场报错, 不透传.
见 docs/superpowers/specs/2026-07-31-offline-target-pipeline-design.md
"""
import numpy as np

FS = 100.0
DEMO_COLS = ("t_us", "t_s", "dBx_uT", "dBy_uT", "dBz_uT", "x_m", "y_m")


def load_demo(csv_path):
    """示范 CSV -> {"t": (N,), "xy": (N,2), "dB": (N,3)}. 缺列/非有限值当场报错."""
    d = np.genfromtxt(csv_path, delimiter=",", names=True)
    names = d.dtype.names or ()
    missing = [c for c in DEMO_COLS if c not in names]
    if missing:
        raise ValueError(
            "示范 CSV 缺列 %s (V0 监控格式没有 x_m/y_m; 示范录制格式见 "
            "spec 2026-07-31-offline-target-pipeline §2): %s" % (missing, csv_path))
    cols = np.column_stack([np.atleast_1d(d[c]) for c in DEMO_COLS])
    bad = ~np.isfinite(cols)
    if bad.any():
        row = int(np.flatnonzero(bad.any(axis=1))[0]) + 2   # +1 表头, +1 改 1 始计数
        raise ValueError("示范 CSV 含非有限值, 首个坏行为第 %d 行: %s" % (row, csv_path))
    return {"t": np.atleast_1d(d["t_s"]),
            "xy": np.column_stack([np.atleast_1d(d["x_m"]), np.atleast_1d(d["y_m"])]),
            "dB": np.column_stack([np.atleast_1d(d["dBx_uT"]),
                                   np.atleast_1d(d["dBy_uT"]),
                                   np.atleast_1d(d["dBz_uT"])])}


def estimate_sigma(g_clean, fs=FS, head_s=0.5):
    """滤波后 σ 估计: 取首段悬空 (录制协议规定首尾悬空 >=0.5s) 的 std.

    首段不安静 (std 超全段 std 的一半) -> 报错; 可在 build_plan 显式传 sigma 绕过."""
    head = g_clean[:int(head_s * fs)]
    if len(head) < int(0.2 * fs):
        raise ValueError("录音太短 (%d 拍), 无法从首段估计 σ" % len(g_clean))
    sigma = float(head.std())
    if sigma > 0.5 * float(np.std(g_clean)):
        raise ValueError(
            "首段 %.1fs 不像悬空段 (std=%.2f µT), 录制需首尾悬空 >=0.5s; "
            "或给 build_plan 显式传 sigma" % (head_s, sigma))
    return sigma


def segment_strokes(g_clean, sigma, fs=FS, min_len_s=0.3, merge_gap_s=0.15,
                    peak_k=6.0):
    """接触段切分: g >= 3σ 的连续区间 [(start, end)). 返回 (segs, n_dropped).

    (2026-07-31 二次修订+顺序修正, Task 5 评审驱动) 滤波后噪声相关时间 ~0.15s,
    悬空段与边界处噪声会间歇性穿越 3σ, 碎出大量低峰值短 run. 三道门**顺序关键**:
    ① 幅度门在先: 峰值 < peak_k·σ 的 run 是噪声游走, 静默弃置 (不是"被丢弃的
      笔画", 不计数) —— 先清场, 否则噪声碎 run 会当"桥墩"让合并传递性地连穿
      整个悬空段;
    ② 间隙合并: 幸存强 run 之间间隙 < merge_gap_s 的合并 (桥接笔画中途轻按+
      噪声造成的短暂低压中断);
    ③ 长度计数: 合并后短于 min_len_s 的才计入 n_dropped."""
    mask = np.concatenate([[False], g_clean >= 3.0 * sigma, [False]])
    d = np.diff(mask.astype(int))
    runs = [(int(a), int(b))
            for a, b in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1))
            if g_clean[a:b].max() >= peak_k * sigma]          # ① 幅度门
    merge_gap = int(merge_gap_s * fs)
    merged = []
    for a, b in runs:                                          # ② 间隙合并
        if merged and a - merged[-1][1] < merge_gap:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    min_len = int(min_len_s * fs)
    segs = [r for r in merged if r[1] - r[0] >= min_len]       # ③ 长度计数
    return segs, int(len(merged) - len(segs))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_demo_pipeline.py -q` → 6 passed；`python -m pytest tests/ -q` → 全绿。

- [ ] **Step 5: Commit**

`git add src/brushbot/demo_pipeline.py tests/test_demo_pipeline.py && git commit -m "feat(pipeline): demo CSV loader with fail-loud validation, sigma estimate, stroke segmentation" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"`

---

### Task 5: demo_pipeline.py — 弧长重参数化 + build_plan

**Files:**
- Modify: `src/brushbot/demo_pipeline.py`
- Test: `tests/test_demo_pipeline.py`

**Interfaces:**
- Consumes: Task 1-4 全部（`fft_lowpass` 来自 `brushbot.sim_loop`，`calib_lookup_z` 来自 `brushbot.z_control`，`Stroke/StrokePlan` 来自 `brushbot.strokeplan`）。
- Produces: `reparam_arclength(xy_seg, g_seg, M=200) -> (s, xy_s, g_s)`（弧长 <1mm 抛 ValueError）；`build_plan(demo, calib_z_mm, calib_abs_dB, fc=3.0, M=200, sigma=None) -> StrokePlan`（meta 键：`fc, M, sigma, n_dropped_short, n_dropped_arc, sat_frac, calib_fingerprint`）。

- [ ] **Step 1: 写失败测试**

`tests/test_demo_pipeline.py` 追加（文件头 import 行合并 `build_plan, reparam_arclength`，另加 `from brushbot.strokeplan import StrokePlan`）：

```python
_CAL_Z = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
_CAL_DB = np.array([0.0, 50.0, 100.0, 150.0, 250.0, 200.0])  # 故意乱序尾: 反查须容忍


def _g_true_s(s):
    """真值 g(s): 边缘 10% ramp + 中段正弦提按, 峰值 185 µT."""
    g = 125.0 + 60.0 * np.sin(2.0 * np.pi * 2.0 * s)
    return g * np.clip(np.minimum(s, 1.0 - s) / 0.1, 0.0, 1.0)


def _make_demo(speed_mod=0.5, seed=3, noise_std=2.0, n_strokes=2,
               stroke_s=3.0, gap_s=0.8):
    """合成示范 dict (带白噪声, 变速): 返回 (demo, s_grid, g_true(s_grid)).

    变速: s(t) = t + speed_mod·sin(2πt)/(2π), 单调; speed_mod=0 → 匀速."""
    rng = np.random.default_rng(seed)
    n, ngap = int(stroke_s * FS), int(gap_s * FS)
    tn = np.linspace(0.0, 1.0, n)
    s_of_t = tn + speed_mod * np.sin(2.0 * np.pi * tn) / (2.0 * np.pi)
    s_of_t = (s_of_t - s_of_t[0]) / (s_of_t[-1] - s_of_t[0])
    s_grid = np.linspace(0.0, 1.0, 400)
    # (2026-07-31 修正) 悬空段 XY 必须从上笔终点线性平移到下笔起点, 不许原地停住后瞬移:
    # 真实的手不会瞬移; 零相位滤波会把接触边界抹进悬空段一两拍, 切分段若裹进瞬移点,
    # 一步假弧长会吃掉大块 s 轴 (实测笔 1 恢复 RMS 98 µT 的根因).
    starts = [np.array([0.0, 0.01 * k]) for k in range(n_strokes)]
    ends = [np.array([0.04, 0.01 * k]) for k in range(n_strokes)]
    frac = np.linspace(0.0, 1.0, ngap)[:, None]
    g_parts = [np.zeros(ngap)]
    xy_parts = [np.tile(starts[0], (ngap, 1))]          # 初始悬空: 停在首笔起点
    for k in range(n_strokes):
        g_parts.append(np.interp(s_of_t, s_grid, _g_true_s(s_grid)))
        x = 0.04 * s_of_t
        y = np.full(n, 0.01 * k)
        xy_parts.append(np.column_stack([x, y]))
        nxt = starts[k + 1] if k + 1 < n_strokes else ends[k]
        g_parts.append(np.zeros(ngap))
        xy_parts.append(ends[k][None, :] * (1.0 - frac) + nxt[None, :] * frac)
    g = np.concatenate(g_parts)
    xy = np.vstack(xy_parts)
    direction = np.array([1.0, 0.3, 0.1]) / np.linalg.norm([1.0, 0.3, 0.1])
    dB = direction[None, :] * g[:, None] + rng.normal(0.0, noise_std, (len(g), 3))
    t = np.arange(len(g)) / FS
    return {"t": t, "xy": xy, "dB": dB}, s_grid, _g_true_s(s_grid)


def _true_s(st):
    """几何真值 s: _make_demo 的笔画是 x=0.04·s 的直线, 故 x/0.04 精确给出每个
    恢复样本的真实 s —— 不依赖"恢复段支撑 == 真值支撑"假设 (边界内缩后两者必然不同)."""
    return np.clip(st.xy[:, 0] / 0.04, 0.0, 1.0)


def _geom_rms(st, lo=0.1, hi=0.9):
    """恢复 g_press vs 几何对齐真值的内部区间 RMS."""
    ts = _true_s(st)
    m = (ts >= lo) & (ts <= hi)
    return float(np.sqrt(np.mean((st.g_press[m] - _g_true_s(ts[m])) ** 2)))


def _on_true_grid(st, grid):
    """恢复 g_press 重采样到几何真值 s 网格. argsort 是单调性防御: 强滤波
    (如 fc=3) 下段边界残留的悬空移动样本会使 ts 折返, 乱序结点让 np.interp 出
    垃圾; 本测试的 fc=10 下 ts 本就单调, 排序为 no-op. 残留样本的影响由
    边界内缩 (build_plan trim) 和网格裁剪共同控制, 排序本身不构成排除机制."""
    ts = _true_s(st)
    idx = np.argsort(ts)
    return np.interp(grid, ts[idx], st.g_press[idx])


def test_reparam_arclength_uniform_grid_and_short_arc():
    n = 100
    xy = np.column_stack([np.linspace(0.0, 0.04, n), np.zeros(n)])
    s, xy_s, g_s = reparam_arclength(xy, np.linspace(0.0, 1.0, n), M=50)
    np.testing.assert_allclose(s, np.linspace(0.0, 1.0, 50))
    np.testing.assert_allclose(xy_s[:, 0], 0.04 * s, atol=1e-12)
    with pytest.raises(ValueError, match="1mm"):
        reparam_arclength(np.zeros((50, 2)), np.ones(50), M=10)


def test_build_plan_segments_and_recovers_truth():
    """恢复精度 (spec Q1 单测版): 带噪变速示范 → 逐笔几何对齐 RMS ≤ 3 µT."""
    demo, s_grid, g_true = _make_demo(speed_mod=0.5)
    plan = build_plan(demo, _CAL_Z, _CAL_DB)
    assert len(plan.strokes) == 2
    assert plan.meta["edge_trim_s"] == pytest.approx(0.17)
    for st in plan.strokes:
        assert _geom_rms(st) <= 3.0
        assert (st.z_ff >= 0.0).all() and (st.z_ff <= 0.005).all()
    # (2026-07-31 恢复) 噪声毛刺由 segment_strokes 的合并+幅度门吸收, 不再污染丢弃计数
    assert plan.meta["n_dropped_short"] == 0 and plan.meta["sat_frac"] == 0.0


def test_speed_invariance():
    """速度解耦 (spec Q2 单测版): 匀速 vs 变速恢复互差 ≤ 1 µT (几何网格上比).

    用 fc=10 弱滤波隔离"时域滤波×速度"耦合 (fc=3 下写快的段被滤得更狠, 互差
    ~2.4 µT——那是全管线固有属性而非重参数化缺陷, 由 E2E 如实报告, spec §8.5).
    本测试只考弧长重参数化本身."""
    d_uni, _, _ = _make_demo(speed_mod=0.0, seed=5, noise_std=0.5)
    d_var, _, _ = _make_demo(speed_mod=0.5, seed=5, noise_std=0.5)
    p_uni = build_plan(d_uni, _CAL_Z, _CAL_DB, fc=10.0)
    p_var = build_plan(d_var, _CAL_Z, _CAL_DB, fc=10.0)
    grid = np.linspace(0.1, 0.9, 200)
    for a, b in zip(p_uni.strokes, p_var.strokes):
        diff = _on_true_grid(a, grid) - _on_true_grid(b, grid)
        assert float(np.sqrt(np.mean(diff ** 2))) <= 1.0


def test_build_plan_saturation_counted():
    demo, _, _ = _make_demo(noise_std=0.5)
    small_cal = np.array([0.0, 50.0, 100.0])            # 上界 100 < 峰值 185
    plan = build_plan(demo, np.array([0.0, 1.0, 2.0]), small_cal)
    assert plan.meta["sat_frac"] > 0.05
    for st in plan.strokes:
        assert st.z_ff.max() <= 0.002 + 1e-12           # 饱和到最大压深
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_demo_pipeline.py -q` → ImportError `reparam_arclength`。

- [ ] **Step 3: 实现**

`demo_pipeline.py` 追加（文件头 import：`from brushbot.sim_loop import fft_lowpass`、`from brushbot.strokeplan import Stroke, StrokePlan`、`from brushbot.z_control import calib_lookup_z`）：

```python
def reparam_arclength(xy_seg, g_seg, M=200):
    """时域笔段 -> 均匀弧长域 (s, xy_s, g_s). 总弧长 < 1mm 抛 ValueError.

    XY 停顿产生的 s 平台是合法输入 (非降序列, np.interp 安全)."""
    ds = np.hypot(*np.diff(np.asarray(xy_seg, float), axis=0).T)
    s = np.concatenate([[0.0], np.cumsum(ds)])
    if s[-1] < 1e-3:
        raise ValueError("笔画弧长 %.3g m < 1mm (原地按压不算笔画)" % s[-1])
    s = s / s[-1]
    s_grid = np.linspace(0.0, 1.0, M)
    xy_s = np.column_stack([np.interp(s_grid, s, xy_seg[:, 0]),
                            np.interp(s_grid, s, xy_seg[:, 1])])
    return s_grid, xy_s, np.interp(s_grid, s, np.asarray(g_seg, float))


def build_plan(demo, calib_z_mm, calib_abs_dB, fc=3.0, M=200, sigma=None):
    """编排整条管线: 整段零相位滤波 -> norm -> σ -> 切分 -> 逐笔重参数化 -> 反查.

    铁律: 先滤 (N,3) 向量再取 norm. 整段滤波后再切分 (避免短笔段 FFT 边缘伪影)."""
    g_clean = np.linalg.norm(fft_lowpass(demo["dB"], fc), axis=1)
    if sigma is None:
        sigma = estimate_sigma(g_clean)
    segs, n_dropped_short = segment_strokes(g_clean, sigma)
    # 边界内缩: 零相位砖墙低通把接触边界抹开 ~0.5/fc, 段边缘裹进的"悬空但在移动"
    # 样本会伪造弧长 (实测 40mm 笔画被污染 17-21%); 收缩后段内每拍 XY 都真实在纸上.
    trim = int(round(0.5 * FS / fc))
    cal_max = float(np.max(calib_abs_dB))
    strokes, n_dropped_arc, n_sat, n_tot = [], 0, 0, 0
    for a, b in segs:
        a, b = a + trim, b - trim
        if b - a < int(0.1 * FS):              # 裁后过短 → 并入过短丢弃计数
            n_dropped_short += 1
            continue
        try:
            s, xy_s, g_s = reparam_arclength(demo["xy"][a:b], g_clean[a:b], M)
        except ValueError:
            n_dropped_arc += 1
            continue
        n_sat += int((g_s > cal_max).sum())
        n_tot += len(g_s)
        strokes.append(Stroke(s=s, xy=xy_s, g_press=g_s,
                              z_ff=np.asarray(calib_lookup_z(
                                  g_s, calib_z_mm, calib_abs_dB), float)))
    sat_frac = n_sat / max(n_tot, 1)
    meta = {"fc": float(fc), "M": int(M), "sigma": float(sigma),
            "edge_trim_s": trim / FS,
            "n_dropped_short": int(n_dropped_short),
            "n_dropped_arc": int(n_dropped_arc), "sat_frac": float(sat_frac),
            "calib_fingerprint": [float(np.min(calib_z_mm)), float(np.max(calib_z_mm)),
                                  float(np.min(calib_abs_dB)), cal_max]}
    if sat_frac > 0.05:
        print("警告: %.1f%% 样本超标定范围被饱和 -- 示范力度超出标定表, 建议重标"
              % (100.0 * sat_frac))
    if n_dropped_short or n_dropped_arc:
        print("提示: 丢弃过短笔画 %d 段 / 短弧长 %d 段" % (n_dropped_short, n_dropped_arc))
    return StrokePlan(strokes=strokes, meta=meta)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_demo_pipeline.py -q` → 10 passed；`python -m pytest tests/ -q` → 全绿。若 `test_build_plan_segments_and_recovers_truth` 的 RMS 略超 3 µT：**不许放宽判据**——先检查内部裁剪区间与真值口径，仍超则以 BLOCKED 上报实测数字（判据是 spec §6 定的）。

- [ ] **Step 5: Commit**

`git add src/brushbot/demo_pipeline.py tests/test_demo_pipeline.py && git commit -m "feat(pipeline): arc-length reparameterization and build_plan orchestration with recovery/speed-invariance tests" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"`

---

### Task 6: scripts/synth_demo.py — 带真值的合成示范生成器

**Files:**
- Create: `scripts/synth_demo.py`

**Interfaces:**
- Consumes: `brushbot.sim_loop.V0NoiseSource`、`brushbot.demo_pipeline.DEMO_COLS`。
- Produces: 模块函数 `make_demo(n_strokes=3, stroke_s=3.0, gap_s=0.8, speed_mod=0.5, seed=42, noise=None) -> (rows (N,7) ndarray, truth: dict)`（truth 键 `s_grid` + `g0..g{K-1}`，即每笔真值 g(s_grid)）；`write_demo_csv(path, rows)`；CLI `main()`。Task 7 同目录 import `make_demo/write_demo_csv`。

- [ ] **Step 1: 写脚本**

```python
#!/usr/bin/env python3
"""合成示范生成器: 产出带真值的示范 CSV (+truth npz), 供管线开发与 E2E 验收.

用法 (单行):
    python scripts/synth_demo.py --out /tmp/demo.csv --truth /tmp/truth.npz
    python scripts/synth_demo.py --uniform-speed --seed 7 --out /tmp/demo_uni.csv --truth /tmp/truth_uni.npz
"""
import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from brushbot.demo_pipeline import DEMO_COLS          # noqa: E402
from brushbot.sim_loop import V0NoiseSource           # noqa: E402

FS = 100.0
DIRECTION = np.array([1.0, 0.3, 0.1]) / np.linalg.norm([1.0, 0.3, 0.1])


def g_true_s(s, base=125.0, depth=60.0):
    """真值 g(s): 边缘 10% ramp + 2 周期正弦提按 (量程内, 峰值 185 µT)."""
    g = base + depth * np.sin(2.0 * np.pi * 2.0 * s)
    return g * np.clip(np.minimum(s, 1.0 - s) / 0.1, 0.0, 1.0)


def stroke_path(k, m):
    """第 k 笔 XY (米): 直线与半圆弧交替, 逐笔 y 下移 1cm."""
    t = np.linspace(0.0, 1.0, m)
    y0 = 0.01 * k
    if k % 2 == 0:
        return np.column_stack([0.04 * t, np.full(m, y0)])
    ang = np.pi * t
    return np.column_stack([0.02 - 0.02 * np.cos(ang), y0 + 0.012 * np.sin(ang)])


def true_s_on_path(xy, k):
    """恢复样本 XY -> 几何真值 s (E2E 对齐用; 与管线边界内缩配套, 不假设支撑一致).

    直线笔画 (偶 k) 用 x/0.04; 半椭圆弧 (奇 k) 用参数角反解."""
    xy = np.asarray(xy, float)
    if k % 2 == 0:
        return np.clip(xy[:, 0] / 0.04, 0.0, 1.0)
    y0 = 0.01 * k
    ang = np.arctan2((xy[:, 1] - y0) / 0.012, (0.02 - xy[:, 0]) / 0.02)
    return np.clip(ang / np.pi, 0.0, 1.0)


def make_demo(n_strokes=3, stroke_s=3.0, gap_s=0.8, speed_mod=0.5, seed=42,
              noise=None):
    """(rows (N,7), truth). speed_mod: 变速幅度 (0=匀速; 0.5 → 速度在 0.5~1.5x 摆动)."""
    n, ngap = int(stroke_s * FS), int(gap_s * FS)
    tn = np.linspace(0.0, 1.0, n)
    s_of_t = tn + speed_mod * np.sin(2.0 * np.pi * tn) / (2.0 * np.pi)
    s_of_t = (s_of_t - s_of_t[0]) / (s_of_t[-1] - s_of_t[0])
    s_grid = np.linspace(0.0, 1.0, 400)
    truth = {"s_grid": s_grid}
    # 悬空段 XY 线性平移到下笔起点 (与 Task 5 _make_demo 同一修正: 手不会瞬移,
    # 瞬移会在切分边界伪造大步弧长)
    paths = [stroke_path(k, 400) for k in range(n_strokes)]
    frac = np.linspace(0.0, 1.0, ngap)[:, None]
    g_parts = [np.zeros(ngap)]
    xy_parts = [np.tile(paths[0][0], (ngap, 1))]        # 初始悬空: 停在首笔起点
    for k in range(n_strokes):
        path = paths[k]
        g_parts.append(np.interp(s_of_t, s_grid, g_true_s(s_grid)))
        xy_parts.append(np.column_stack([np.interp(s_of_t, s_grid, path[:, 0]),
                                         np.interp(s_of_t, s_grid, path[:, 1])]))
        truth["g%d" % k] = g_true_s(s_grid)
        nxt = paths[k + 1][0] if k + 1 < n_strokes else path[-1]
        g_parts.append(np.zeros(ngap))
        xy_parts.append(path[-1][None, :] * (1.0 - frac) + nxt[None, :] * frac)
    g = np.concatenate(g_parts)
    xy = np.vstack(xy_parts)
    if noise is not None:
        nz = noise.sample(len(g))
    else:
        nz = np.random.default_rng(seed).normal(0.0, 2.0, (len(g), 3))
    dB = DIRECTION[None, :] * g[:, None] + nz
    t_s = np.arange(len(g)) / FS
    rows = np.column_stack([t_s * 1e6, t_s, dB, xy])
    return rows, truth


def write_demo_csv(path, rows):
    header = ",".join(DEMO_COLS)
    np.savetxt(path, rows, delimiter=",", header=header, comments="",
               fmt="%.9g")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--strokes", type=int, default=3)
    ap.add_argument("--uniform-speed", action="store_true")
    ap.add_argument("--csv-dir", default=str(ROOT / "delta_b_v0_20260724"),
                    help="V0 idle CSV 目录 (存在则用真噪声, 否则白噪声)")
    args = ap.parse_args(argv)

    idle = sorted(p for p in Path(args.csv_dir).glob("*.csv") if "idle" in p.stem)
    noise = V0NoiseSource(idle, seed=args.seed) if idle else None
    rows, truth = make_demo(n_strokes=args.strokes,
                            speed_mod=0.0 if args.uniform_speed else 0.5,
                            seed=args.seed, noise=noise)
    write_demo_csv(args.out, rows)
    np.savez(args.truth, **truth)
    print("示范 CSV: %s (%d 拍, 噪声=%s)  真值: %s"
          % (args.out, len(rows), "V0" if noise else "white", args.truth))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 冒烟验证（生成物能被管线消费）**

Run: `python scripts/synth_demo.py --out /tmp/claude-1000/-home-ethan-FYP/c8d6cdda-7d97-453e-9372-91a0ed39c687/scratchpad/demo.csv --truth /tmp/claude-1000/-home-ethan-FYP/c8d6cdda-7d97-453e-9372-91a0ed39c687/scratchpad/truth.npz && python -c "import sys; sys.path.insert(0,'src'); from brushbot.demo_pipeline import load_demo, build_plan; import numpy as np; d=load_demo('/tmp/claude-1000/-home-ethan-FYP/c8d6cdda-7d97-453e-9372-91a0ed39c687/scratchpad/demo.csv'); p=build_plan(d, np.array([0.,1,2,3,4,5]), np.array([0.,50,100,150,200,250])); print('strokes:', len(p.strokes), 'meta:', p.meta)"`
Expected: 打印 `strokes: 3`，`sat_frac` 为 0.0（真值峰 185 < 250），`n_dropped_*` 为 0。

- [ ] **Step 3: 全套测试回归**

Run: `python -m pytest tests/ -q` → 全绿（脚本不入测试）。

- [ ] **Step 4: Commit**

`git add scripts/synth_demo.py && git commit -m "feat(scripts): synthetic demo generator with ground truth, variable-speed profile, V0 noise" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"`

---

### Task 7: scripts/demo_target_pipeline.py — 端到端两臂验收

**Files:**
- Create: `scripts/demo_target_pipeline.py`
- Output: 终端验收数字 + `docs/assets/target-pipeline-demo.png`（gitignored）

**Interfaces:**
- Consumes: 同目录 `synth_demo.make_demo/write_demo_csv`；`demo_pipeline.load_demo/build_plan`；`strokeplan.StrokePlan`；`sim_loop.Plant/V0NoiseSource/run_loop/rms_pct`；`z_control.ZController/calib_lookup_z`。
- Produces: 终端打印 spec §6 四问中 Q1/Q2/Q3 的数字（Q4 已由 Task 2 测试回答）；三面板图。

- [ ] **Step 1: 写脚本**

```python
#!/usr/bin/env python3
"""E2E 验收 (spec §6): 合成示范 -> 管线 -> 两臂对比.

Q1 恢复精度 / Q2 速度解耦 / Q3 开环 vs 闭环 (calib×0.8). Q4 由
tests/test_strokeplan.py::test_waypoints_drive_openloop_controller 回答.

用法 (单行):
    python scripts/demo_target_pipeline.py
"""
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from brushbot.demo_pipeline import build_plan, load_demo        # noqa: E402
from brushbot.sim_loop import (Plant, V0NoiseSource, rms_pct,   # noqa: E402
                               run_loop)
from brushbot.z_control import ZController, calib_lookup_z      # noqa: E402
from brushbot.monitor.core import EMA                           # noqa: E402
from synth_demo import (g_true_s, make_demo, true_s_on_path,    # noqa: E402
                        write_demo_csv)

FS = 100.0
CALIB_Z = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
CALIB_DB = np.array([0.0, 50.0, 100.0, 150.0, 200.0, 250.0])
SEED = 42
STROKE_DURATION_S = 3.0


def _geom_rms(st, k, lo=0.1, hi=0.9):
    """恢复 g_press vs 几何对齐真值的内部 RMS (对齐经 true_s_on_path, 支撑无关)."""
    ts = true_s_on_path(st.xy, k)
    m = (ts >= lo) & (ts <= hi)
    return float(np.sqrt(np.mean((st.g_press[m] - g_true_s(ts[m])) ** 2)))


def _on_grid(st, k, grid):
    ts = true_s_on_path(st.xy, k)
    idx = np.argsort(ts)              # 边界残留样本可致 ts 非单调, 排序后插值
    return np.interp(grid, ts[idx], st.g_press[idx])


def main():
    csvs = sorted(p for p in (ROOT / "delta_b_v0_20260724").glob("*.csv")
                  if "idle" in p.stem)
    noise = V0NoiseSource(csvs, seed=SEED) if csvs else None
    work = Path(tempfile.mkdtemp(prefix="pipeline-e2e-"))

    # --- 生成两份示范 (同真值, 变速/匀速) 并过管线 ---
    plans, truths = {}, {}
    for name, mod in (("var", 0.5), ("uni", 0.0)):
        rows, truth = make_demo(speed_mod=mod, seed=SEED, noise=noise)
        p = work / ("demo_%s.csv" % name)
        write_demo_csv(p, rows)
        plans[name] = build_plan(load_demo(p), CALIB_Z, CALIB_DB)
        truths[name] = truth
    plan = plans["var"]

    # --- Q1: 恢复精度 (变速+V0 噪声 vs 真值, 逐笔几何对齐 RMS) ---
    q1 = [_geom_rms(st, k) for k, st in enumerate(plan.strokes)]
    print("Q1 恢复精度: 逐笔 RMS = %s µT (判据 ≤3)" %
          ", ".join("%.2f" % v for v in q1))

    # --- Q2: 速度解耦 (几何真值网格上比) ---
    grid = np.linspace(0.1, 0.9, 200)
    q2 = [float(np.sqrt(np.mean((_on_grid(a, k, grid) - _on_grid(b, k, grid)) ** 2)))
          for k, (a, b) in enumerate(zip(plans["uni"].strokes, plans["var"].strokes))]
    print("Q2 速度解耦(全管线 fc=3, 含时域滤波×速度耦合): 互差 RMS = %s µT"
          " (如实报告, sanity ≤3.5; 纯重参数化判据 ≤1 由单测 fc=10 隔离回答)" %
          ", ".join("%.2f" % v for v in q2))

    # --- Q3: 两臂彩排 (calib×0.8) ---
    g_d, _ = plan.to_gd_series(STROKE_DURATION_S)
    sigma_f = (V0NoiseSource(csvs, seed=SEED).filtered_sigma(lambda: EMA(0.3))
               if csvs else 2.0)
    z_open = 0.20 + np.asarray(calib_lookup_z(g_d, CALIB_Z, CALIB_DB), float)
    results = {}
    for arm in ("open", "closed"):
        pl_noise = V0NoiseSource(csvs, seed=SEED) if csvs else None
        plant = Plant(CALIB_Z, CALIB_DB, noise=pl_noise, calib_scale=0.8)
        if arm == "open":
            abs_true = np.empty(len(z_open))
            for i, z in enumerate(z_open):   # 开环: 逐拍执行 z_ff, 不读传感器
                plant.step(z)
                abs_true[i] = plant.abs_true
            res = {"g_d": g_d, "abs_true": abs_true,
                   "z_cmd": z_open, "frozen": g_d < 3.0 * sigma_f}
        else:
            ctrl = ZController(CALIB_Z, CALIB_DB, noise_std=sigma_f)
            res = run_loop(ctrl, EMA(0.3), g_d, plant)
        results[arm] = res
        print("Q3 %s: 接触段 RMS = %.2f%%" % (arm, rms_pct(res, sigma_f)))

    # --- 图: 三面板 (Q1 恢复对比 / Q2 两剖面重叠 / Q3 两臂跟踪) ---
    import matplotlib
    matplotlib.use("Agg")
    matplotlib.rcParams["font.sans-serif"] = [
        "Noto Sans CJK SC", "Noto Sans CJK HK", "Noto Sans CJK JP", "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(3, 1, figsize=(10, 10))
    st = plan.strokes[0]
    tr = truths["var"]
    axes[0].plot(tr["s_grid"], tr["g0"], "k-", lw=2, label="真值 g(s)")
    axes[0].plot(true_s_on_path(st.xy, 0), st.g_press, "--", lw=1.2,
                 label="管线恢复 (几何对齐)")
    axes[0].set(xlabel="s", ylabel="g (µT)", title="Q1: 恢复精度 (笔 0)")
    axes[0].legend(fontsize=8)
    axes[1].plot(true_s_on_path(plans["uni"].strokes[0].xy, 0),
                 plans["uni"].strokes[0].g_press, lw=1.2, label="匀速示范")
    axes[1].plot(true_s_on_path(plans["var"].strokes[0].xy, 0),
                 plans["var"].strokes[0].g_press, "--", lw=1.2,
                 label="±50% 变速示范")
    axes[1].set(xlabel="s", ylabel="g (µT)", title="Q2: 速度解耦")
    axes[1].legend(fontsize=8)
    t_axis = np.arange(len(g_d)) / FS
    axes[2].plot(t_axis, g_d, "k-", lw=1.5, label="目标 g_d")
    for arm, style in (("open", ":"), ("closed", "--")):
        axes[2].plot(t_axis, results[arm]["abs_true"], style, lw=1.2, label=arm)
    axes[2].set(xlabel="t (s)", ylabel="|ΔB| (µT)",
                title="Q3: calib×0.8 下两臂跟踪 (真值口径)")
    axes[2].legend(fontsize=8)
    fig.tight_layout()
    out_png = ROOT / "docs" / "assets" / "target-pipeline-demo.png"
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=120)
    print("图:", out_png)


if __name__ == "__main__":
    main()
```

开环臂语义：逐拍把 z_ff 轨迹喂给 Plant、只记录物理真值 `plant.abs_true`，不构造控制器、不读传感器输出（返回向量直接忽略）——这就是"闭着眼睛照乐谱弹"。

- [ ] **Step 2: 运行并核对验收数字**

Run: `python scripts/demo_target_pipeline.py`
Expected: Q1 各笔 ≤3 µT；Q2 各笔 ≤3.5 µT（全管线含滤波×速度耦合的如实数字，预期 ~2–3）；Q3 closed RMS < open RMS（方向与层 2 一致：开环全吃标定偏差、闭环砍约一半）；PNG 生成。若某项超判据：**不改判据、不调参凑数**，如实记录数字并以 DONE_WITH_CONCERNS 上报。

- [ ] **Step 3: 全套测试回归**

Run: `python -m pytest tests/ -q` → 全绿。

- [ ] **Step 4: Commit**

`git add scripts/demo_target_pipeline.py && git commit -m "feat(scripts): E2E pipeline acceptance — recovery, speed invariance, two-arm rehearsal" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"`

---

### Task 8: 收尾 — handoff/spec/记忆更新

**Files:**
- Modify: `docs/handoff-z-phase1.md`（§3.2 状态）
- Modify: `docs/superpowers/specs/2026-07-31-offline-target-pipeline-design.md`（§6 数字回填）
- Modify: `/home/ethan/.claude/projects/-home-ethan-FYP/memory/architecture-strokeplan-interface.md` + `MEMORY.md`（仓库外，不入 git）

**Interfaces:**
- Consumes: Task 7 打印的 Q1/Q2/Q3 实测数字、Task 2 的 Q4 测试名。

- [ ] **Step 1: 文档回填**

- spec §6 表格追加"实测"列：Q1/Q2/Q3 写入 Task 7 数字，Q4 写"通过（`test_waypoints_drive_openloop_controller`）"。
- `docs/handoff-z-phase1.md` §3.2 节首加一行：`> **状态更新（2026-07-31）：已完成。** 管线 `src/brushbot/demo_pipeline.py` + `StrokePlan`（`src/brushbot/strokeplan.py`）落地，验收四问见 `docs/superpowers/specs/2026-07-31-offline-target-pipeline-design.md` §6。真实示范录制协议仍待硬件（XY 来源倾向机械臂拖动示教）。`
- 记忆 `architecture-strokeplan-interface.md`：更新为"已落地"状态——StrokePlan dataclass 位置、两个导出方法名、npz 存取、单位纪律一句话；`MEMORY.md` 索引行同步。

- [ ] **Step 2: 全套测试回归**

Run: `python -m pytest tests/ -q` → 全绿。

- [ ] **Step 3: Commit**

`git add docs/handoff-z-phase1.md docs/superpowers/specs/2026-07-31-offline-target-pipeline-design.md && git commit -m "docs: offline target pipeline delivered — acceptance numbers backfilled, StrokePlan contract landed" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"`

---

## 验收总检（对照 spec）

- spec §6 四问全部有数字/测试答案（Q1-Q3 → Task 7 输出回填进 spec；Q4 → Task 2 测试）。
- `python -m pytest tests/ -q` 全绿（基线 130 + 新增 16）。
- 交付物对照 spec §9 清单逐项勾。
