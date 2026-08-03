# Z Control Phase 0 Implementation Plan

> **For agentic workers:** Execute tasks in order. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Implement overall ΔB tracking control in simulation — ZController class, unit tests, and closed-loop demo that tracks a target |ΔB(t)| curve from V0 data.

**Architecture:** Pure numpy ZController with feedforward (z_ff from calibration curve inverse) + PI feedback on scalar |ΔB| error. No hardware, no GUI dependency. Demo uses contact_sim calibration curve as plant model.

**Tech Stack:** numpy, contact_sim.py (existing), V0 dataset (existing)

## Global Constraints

- Zero new dependencies — all numpy builtins
- All units in meters and µT (matches project convention)
- No GUI imports in core module (tests must pass without display)
- Test plant model uses calibration curve + injected noise

---
### Task 1: ZController class

**Files:**
- Create: `src/brushbot/z_control.py`
- Test: `tests/test_z_control.py`

**Interfaces:**
- Produces: `ZController(calib_z_mm, calib_abs_dB, dt, kp, ki, z_surface, dz_margin, noise_std)` — constructor
- Produces: `ZController.step(dB_meas: ndarray, g_d: float) -> float` — z_cmd in meters (world frame)
- Produces: `ZController.reset()` — clear integrator
- Produces: `ZController.z_ff -> float`, `ZController.z_fb -> float` — debug properties
- Produces: `ZController.frozen -> bool` — whether integrator is currently frozen

- [ ] **Step 1: Write the six test stubs**

Write `tests/test_z_control.py` with all six test functions. Each test uses a shared synthetic calibration curve:

```python
import numpy as np
import pytest
from brushbot.z_control import ZController


# Shared calibration: 0–5 mm press → 0–250 µT |ΔB| (monotonic, linear-ish)
_CALIB_Z = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0], dtype=float)
_CALIB_DB = np.array([0.0, 50.0, 100.0, 150.0, 200.0, 250.0], dtype=float)


def _plant(z_m, calib_z, calib_dB):
    """Synthetic plant: z_offset (m) → |ΔB| (µT). Same curve as calibration."""
    z_mm = z_m * 1000.0
    return float(np.interp(z_mm, calib_z, calib_dB, left=0.0, right=calib_dB[-1]))


def test_z_ff_interpolation():
    """前饋插值在標定範圍內連續，超出範圍時飽和保護。"""
    ctrl = ZController(_CALIB_Z, _CALIB_DB, dt=0.01)
    # Inside range
    z = ctrl._z_ff_lookup(100.0)
    assert 0.001 < z < 0.005, f"z_ff(100) = {z}, expected ~0.002"
    # Outside → clamp to bounds
    z_low = ctrl._z_ff_lookup(-10.0)
    assert z_low == 0.0, f"z_ff(-10) = {z_low}, expected 0.0"
    z_high = ctrl._z_ff_lookup(1e6)
    assert z_high > 0.004, f"z_ff(1e6) = {z_high}, expected ~0.005"
    # z_ff output is in meters
    assert ctrl._z_ff_lookup(150.0) == pytest.approx(0.003, rel=0.01)


def test_reset_clears_integrator():
    """reset 後反饋項歸零。"""
    ctrl = ZController(_CALIB_Z, _CALIB_DB, dt=0.01, ki=1.0)
    # Run a few steps to build up integrator
    for _ in range(50):
        ctrl.step(np.array([0.0, 0.0, 50.0]), 150.0)  # g_d=150 but meas only 50
    assert ctrl.z_fb > 0.001, "z_fb should have built up"
    ctrl.reset()
    assert ctrl.z_fb == 0.0
    assert ctrl.z_fb == pytest.approx(0.0)


def test_z_fb_clamping():
    """反饋超出 DZ_MARGIN 時被限幅，退飽和啟動。"""
    ctrl = ZController(_CALIB_Z, _CALIB_DB, dt=0.01, ki=5.0, dz_margin=1e-3)
    # Large persistent error should saturate the integrator
    for _ in range(200):
        ctrl.step(np.array([0.0, 0.0, 10.0]), 200.0)
    assert abs(ctrl.z_fb) <= 1e-3 + 1e-9, f"z_fb={ctrl.z_fb} exceeded margin"


def test_lift_freezes_integrator():
    """目標 |ΔB| < 閾值時積分凍結（筆擡起時誤差無意義）。"""
    ctrl = ZController(_CALIB_Z, _CALIB_DB, dt=0.01, ki=1.0)
    # Build up some integrator
    for _ in range(50):
        ctrl.step(np.array([0.0, 0.0, 80.0]), 150.0)
    z_before = ctrl.z_fb
    # Now simulate lift: g_d near zero
    for _ in range(50):
        ctrl.step(np.array([0.0, 0.0, 5.0]), 5.0)
    assert ctrl.z_fb == pytest.approx(z_before, abs=1e-9), "z_fb changed during lift"
    assert ctrl.frozen


def test_air_freezes_integrator():
    """測量 |ΔB| < 3σ 時積分凍結（筆懸空時無接觸信號）。"""
    noise_std = 7.0  # µT
    ctrl = ZController(_CALIB_Z, _CALIB_DB, dt=0.01, ki=1.0, noise_std=noise_std)
    # Build up some integrator
    for _ in range(50):
        ctrl.step(np.array([0.0, 0.0, 80.0]), 150.0)
    z_before = ctrl.z_fb
    # Now dB_meas is tiny → no contact
    for _ in range(50):
        ctrl.step(np.array([0.0, 0.0, noise_std]), 150.0)
    assert ctrl.z_fb == pytest.approx(z_before, abs=1e-9), "z_fb changed during air"


def test_step_tracks_constant():
    """固定目標下閉環收斂到 ±5% 誤差。"""
    ctrl = ZController(_CALIB_Z, _CALIB_DB, dt=0.01, kp=0.5, ki=0.2)
    g_d = 120.0  # target |ΔB|
    z_cmd = 0.0
    dB_meas = np.zeros(3)

    for _ in range(300):
        z_cmd = ctrl.step(dB_meas, g_d)
        abs_meas = _plant(z_cmd, _CALIB_Z, _CALIB_DB)
        dB_meas = np.array([abs_meas, 0.0, 0.0])

    error = abs(g_d - np.linalg.norm(dB_meas)) / g_d
    assert error < 0.05, f"steady-state error {error:.3f} > 0.05"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/ethan/FYP && python -m pytest tests/test_z_control.py -v 2>&1 | head -30
```

Expected: 6 FAILED with `ModuleNotFoundError: no module named brushbot.z_control`

- [ ] **Step 3: Create ZController — constructor with z_ff lookup**

Write `src/brushbot/z_control.py`:

```python
"""Z 轴闭环控制 Phase 0: 整体 ΔB 跟踪.

控制律: z_cmd = z_surface + z_ff(|ΔB_d|) + Kp·e + Ki·∫e
  e = |ΔB_d| − |ΔB_meas|
  前馈为主, 积分仅补残差.

见 docs/superpowers/specs/2026-07-28-z-control-phase0-design.md
"""
import numpy as np


class ZController:
    """整体 ΔB 标量跟踪控制器。"""

    def __init__(self, calib_z_mm: np.ndarray, calib_abs_dB: np.ndarray,
                 dt: float = 0.01, kp: float = 0.5, ki: float = 0.1,
                 z_surface: float = 0.20, dz_margin: float = 3e-3,
                 noise_std: float = 7.0):
        """
        calib_z_mm: (N,) 压深 mm (从接触起点起算)
        calib_abs_dB: (N,) 对应 |ΔB| μT
        dt: 控制周期 (s)
        kp/ki: 比例/积分增益 (z 单位: m)
        z_surface: 纸面高度 (m)
        dz_margin: 积分限幅 ±m
        noise_std: 噪声标准差 (μT), 用于接触判定
        """
        assert len(calib_z_mm) == len(calib_abs_dB) > 1
        # z_ff lookup: |ΔB| μT → z_offset m
        z_offset_m = np.asarray(calib_z_mm, dtype=float) / 1000.0
        self._calib_dB = np.asarray(calib_abs_dB, dtype=float)
        self._z_offset_m = z_offset_m
        self._dt = dt
        self._kp = kp
        self._ki = ki
        self._z_surface = z_surface
        self._dz_margin = dz_margin
        self._noise_std = noise_std

        self._z_fb = 0.0
        self._frozen = False
        # Anti-windup gain (classic back-calculation)
        self._k_aw = 2.0 / ki if ki > 1e-12 else 0.0

    def _z_ff_lookup(self, g_d: float) -> float:
        """|ΔB| (μT) → z_offset (m). 超出标定范围则饱和."""
        return float(np.interp(g_d, self._calib_dB, self._z_offset_m,
                               left=0.0, right=self._z_offset_m[-1]))

    def step(self, dB_meas: np.ndarray, g_d: float) -> float:
        """计算 z_cmd (m, 世界坐标).

        dB_meas: (3,) 当前 ΔB 测量值 (μT)
        g_d: 目标 |ΔB| (μT)
        """
        abs_meas = float(np.linalg.norm(dB_meas))

        # --- 工程保护: 接触/抬笔判定 ---
        if abs_meas < 3.0 * self._noise_std:
            self._frozen = True
        elif g_d < 3.0 * self._noise_std:
            self._frozen = True
        else:
            self._frozen = False

        # --- 前馈 ---
        z_ff = self._z_ff_lookup(g_d)

        # --- 反馈 ---
        if not self._frozen:
            e = g_d - abs_meas
            self._z_fb += self._ki * e * self._dt
            # Back-calculation anti-windup
            z_fb_limited = np.clip(self._z_fb, -self._dz_margin, self._dz_margin)
            self._z_fb += self._k_aw * (z_fb_limited - self._z_fb) * self._dt
            self._z_fb = z_fb_limited

        z_cmd = self._z_surface + z_ff + self._kp * e + self._z_fb
        return float(z_cmd)

    def reset(self):
        """重置积分器."""
        self._z_fb = 0.0
        self._frozen = False

    @property
    def z_ff(self) -> float:
        return self._z_ff_lookup(self._last_g_d) if hasattr(self, '_last_g_d') else 0.0

    @property
    def z_fb(self) -> float:
        return self._z_fb

    @property
    def frozen(self) -> bool:
        return self._frozen
```

Wait — the `z_ff` property needs the last g_d. Let me store it:

```python
    def step(self, dB_meas, g_d):
        ...
        self._last_g_d = g_d
        ...
```

Also, `self._kp * e` — I need `e` defined in the frozen case too. Let me restructure:

```python
    def step(self, dB_meas, g_d):
        abs_meas = float(np.linalg.norm(dB_meas))
        e = g_d - abs_meas
        self._last_g_d = g_d

        # Contact / lift detection
        if abs_meas < 3.0 * self._noise_std or g_d < 3.0 * self._noise_std:
            self._frozen = True
        else:
            self._frozen = False

        # Feedforward
        z_ff = self._z_ff_lookup(g_d)

        # Feedback (only integrate when not frozen)
        if not self._frozen:
            self._z_fb += self._ki * e * self._dt
            z_fb_limited = np.clip(self._z_fb, -self._dz_margin, self._dz_margin)
            self._z_fb += self._k_aw * (z_fb_limited - self._z_fb) * self._dt
            self._z_fb = z_fb_limited

        z_cmd = self._z_surface + z_ff + self._kp * e + self._z_fb
        return float(z_cmd)
```

---
### Task 2: Add calibrate() to contact_sim.py

**Files:**
- Modify: `src/brushbot/tactile/contact_sim.py`
- Create: `scripts/demo_z_control.py`

**Interfaces:**
- Consumes: `ZController` from Task 1
- Produces: `contact_sim.calibrate()` — returns calibration curve
- Produces: `demo_z_control.py` — closed-loop demo script

- [ ] **Step 1: Rewrite Task2 heading in the plan**

- [ ] **Step 2: Add `calibrate()` to contact_sim.py**

```python
def calibrate(press_mm=None, settle=500):
    """Run calibration: press in steps, return calibration curve.

    Returns dict with:
        z_mm: (N,) press depths (mm, from 0)
        abs_dB: (N,) |ΔB| at each press
        dB: (N, 3) ΔB vector at each press
    """
    if press_mm is None:
        press_mm = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 18, 20, 22)
    z, dB_arr, _ = run(press_mm, settle=settle)
    return {
        "z_mm": z,
        "abs_dB": np.linalg.norm(dB_arr, axis=1),
        "dB": dB_arr,
    }
```

- [ ] **Step 3: Write demo_z_control.py**

```python
"""Phase 0 Demo: 整体 ΔB 跟踪闭环仿真.

Usage:
    python scripts/demo_z_control.py --output z_control_demo.png
    python scripts/demo_z_control.py --v0 delta_b_v0_20260724/20260724_143839_line_lr_r02 --output demo_line.png
    python scripts/demo_z_control.py --v0 delta_b_v0_20260724/20260724_144151_circle_cw_r01 --output demo_circle.png

Output: three-panel figure — target |ΔB| vs measured, z_cmd decomposition, error.
"""
import argparse
import pathlib

import numpy as np

from brushbot.z_control import ZController
from brushbot.tactile import contact_sim


def _load_v0(path):
    """Load V0 CSV, return (t_s, abs_dB) arrays."""
    d = np.genfromtxt(path, delimiter=",", names=True)
    t = d["t_s"]
    dB = np.c_[d["dBx_uT"], d["dBy_uT"], d["dBz_uT"]]
    abs_dB = np.linalg.norm(dB, axis=1)
    return t, abs_dB


def _synthetic_target(n=400, fs=100.0):
    """Synthetic target: ramp up, hold, step down, hold."""
    t = np.arange(n) / fs
    profile = np.zeros(n)
    n_ramp = 80
    n_hold1 = 120
    profile[:n_ramp] = np.linspace(0, 200.0, n_ramp)       # touch down
    profile[n_ramp:n_ramp + n_hold1] = 200.0                 # press steady
    profile[n_ramp + n_hold1:n_ramp + n_hold1 + n_ramp] = \
        np.linspace(200.0, 100.0, n_ramp)                    # partial lift
    profile[n_ramp + n_hold1 + n_ramp:] = 100.0              # lighter press
    return t, profile


def _run_demo(target_abs_dB, dt=0.01, kp=0.3, ki=0.15,
              calib_z_mm=None, calib_abs_dB=None):
    """Run closed-loop demo with synthetic plant.

    Returns dict of arrays for plotting.
    """
    if calib_z_mm is None:
        calib_z_mm = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0,
                               6.0, 7.0, 8.0, 9.0, 10.0, 12.0, 14.0, 16.0,
                               18.0, 20.0, 22.0])
    if calib_abs_dB is None:
        # Use contact_sim to generate realistic calibration
        cal = contact_sim.calibrate()
        calib_z_mm = cal["z_mm"]
        calib_abs_dB = cal["abs_dB"]

    ctrl = ZController(calib_z_mm, calib_abs_dB, dt=dt, kp=kp, ki=ki)

    # Synthetic plant: same as calibration, plus noise
    z_off_mm_grid = np.linspace(0, calib_z_mm[-1], 500)
    abs_dB_grid = np.interp(z_off_mm_grid, calib_z_mm, calib_abs_dB)

    press_direction = np.array([1.0, 0.3, 0.1])
    press_direction = press_direction / np.linalg.norm(press_direction)

    n = len(target_abs_dB)
    time = np.arange(n) * dt
    z_cmd_arr = np.empty(n)
    z_ff_arr = np.empty(n)
    z_fb_arr = np.empty(n)
    meas_arr = np.empty(n)
    frozen_arr = np.empty(n, dtype=bool)

    dB_meas = np.zeros(3)
    for i, g_d in enumerate(target_abs_dB):
        z_cmd = ctrl.step(dB_meas, g_d)
        z_off_mm = (z_cmd - ctrl._z_surface) * 1000.0
        abs_meas = float(np.interp(z_off_mm, z_off_mm_grid, abs_dB_grid,
                                    left=0.0, right=abs_dB_grid[-1]))
        noise = np.random.default_rng(42).normal(0, 7.0)
        abs_meas = max(0.0, abs_meas + noise)
        dB_meas = press_direction * abs_meas

        z_cmd_arr[i] = z_cmd
        z_ff_arr[i] = ctrl.z_ff
        z_fb_arr[i] = ctrl.z_fb
        meas_arr[i] = abs_meas
        frozen_arr[i] = ctrl.frozen

    return {
        "time": time,
        "target": np.asarray(target_abs_dB),
        "meas": meas_arr,
        "z_cmd": z_cmd_arr,
        "z_ff": z_ff_arr,
        "z_fb": z_fb_arr,
        "frozen": frozen_arr,
    }


def plot_result(result, out_path):
    """Three-panel figure: tracking, z decomposition, error."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 8), sharex=True)

    t = result["time"]
    # Panel 1: Tracking
    ax1.plot(t, result["target"], "k-", lw=2, label="target |ΔB|_d")
    ax1.plot(t, result["meas"], "--", color="crimson", lw=1.5, label="|ΔB_meas|")
    frozen_mask = result["frozen"]
    if frozen_mask.any():
        ax1.fill_between(t, 0, result["target"].max() * 0.1,
                          where=frozen_mask, color="gray", alpha=0.15,
                          label="frozen")
    ax1.set_ylabel("|ΔB| (µT)")
    ax1.legend(fontsize=9)
    ax1.grid(alpha=0.3)

    # Panel 2: z decomposition
    z_surface = 0.20  # config.PAPER_Z
    ax2.plot(t, (result["z_cmd"] - z_surface) * 1000, "k-", lw=2, label="z_cmd offset")
    ax2.plot(t, (result["z_ff"] - z_surface) * 1000, ":", color="steelblue", lw=1.5, label="z_ff")
    ax2.plot(t, result["z_fb"] * 1000, "-.", color="orange", lw=1.5, label="z_fb")
    ax2.set_ylabel("z offset (mm)")
    ax2.legend(fontsize=9)
    ax2.grid(alpha=0.3)

    # Panel 3: Error
    error = (result["target"] - result["meas"]) / np.clip(result["target"], 1.0, None) * 100
    ax3.plot(t, error, lw=1.5, color="crimson")
    ax3.axhline(5, ls=":", color="gray"); ax3.axhline(-5, ls=":", color="gray")
    ax3.text(t[-1] * 0.02, 5.5, "±5%", fontsize=8, color="gray")
    ax3.set_ylabel("relative error (%)")
    ax3.set_xlabel("time (s)")
    ax3.grid(alpha=0.3)

    rms = float(np.sqrt(np.mean(error[len(error)//4:] ** 2)))
    ax3.set_title(f"relative error (last 75% RMS: {rms:.1f}%)")

    fig.suptitle("Phase 0: overall ΔB tracking — closed loop in simulation", fontsize=13)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    print(f"Saved: {out_path}")
    plt.close(fig)
    return rms


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--v0", type=str, default=None,
                   help="V0 CSV path for target |ΔB(t)|")
    p.add_argument("--output", type=str, default="z_control_demo.png",
                   help="Output image path")
    args = p.parse_args()

    if args.v0:
        target_t, target_abs_dB = _load_v0(args.v0)
    else:
        target_t, target_abs_dB = _synthetic_target()

    result = _run_demo(target_abs_dB, dt=0.01)
    rms = plot_result(result, args.output)

    print(f"RMS tracking error (last 75%): {rms:.1f}%")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run demo to verify**

```bash
cd /home/ethan/FYP && python scripts/demo_z_control.py --output z_control_demo.png
```

Expected: prints "RMS tracking error: <5%" and saves figure.

- [ ] **Step 5: Run V0 demo**

```bash
cd /home/ethan/FYP && python scripts/demo_z_control.py --v0 delta_b_v0_20260724/20260724_143839_line_lr_r02 --output demo_line_lr.png
```

Expected: prints RMS error, saves figure.

- [ ] **Step 6: Commit**

```bash
git add src/brushbot/tactile/contact_sim.py scripts/demo_z_control.py
git commit -m "feat(z-control): add contact_sim calibrate() + demo script

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
<｜end▁of▁thinking｜>

<｜｜DSML｜｜tool_calls>
<｜｜DSML｜｜invoke name="Read">
<｜｜DSML｜｜parameter name="file_path" string="true">/home/ethan/FYP/docs/superpowers/specs/2026-07-28-z-control-phase0-design.md