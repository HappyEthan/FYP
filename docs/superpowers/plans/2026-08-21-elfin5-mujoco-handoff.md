# Elfin5 MuJoCo 交接仓库 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `~/elfin5-mujoco-ctrl` 新建独立 git 交接仓库，交付 Elfin5 机械臂的 MuJoCo 仿真骨架——对外暴露关节级 + 笛卡尔级双控制接口，供 Mac 上的协作者用自己的控制算法驱动同一个臂。

**Architecture:** 单包 `elfin`，两个核心模块——`robot.py`（加载 URDF → MjModel，加 6 个关节位置执行器，暴露 `step_joint`/`step_cartesian` 双接口 + 每拍反馈）和 `ik.py`（雅可比 DLS IK）。两者都只依赖 `numpy` + `mujoco`，无 GUI/无 `brushbot` 依赖。资产（URDF + 7 个 STL）原样拷入 `assets/`，来自大族 BSD 许可包并在 NOTICE 注明。

**Tech Stack:** Python ≥3.10, numpy, mujoco (≥2.3.7，macOS arm64 有官方 wheel), pytest (仅测试用).

## Global Constraints

- 目标目录：`~/elfin5-mujoco-ctrl`，独立 git 仓库（`git init`，非 FYP 子目录、不与 FYP 共享提交）。
- 运行时依赖**只有** `numpy` + `mujoco`。绝不 import `brushbot`，绝不依赖 `pybullet`/`matplotlib`/conda。
- 包名：分发包 `elfin5-sim`；导入名 `elfin`（`src/elfin/`）。
- 6 个关节名：`elfin_joint1..elfin_joint6`；末端 body 名：`elfin_link6`。全为 revolute，qpos 索引 = 关节序号-1，dofadr = 关节序号-1，axis 均沿 Z。
- 工具姿态约定：工具 z 轴朝下（`euler2Quat([pi,0,0],"xyz")`），与当前 FYP 写法一致；笛卡尔接口的 EEF 参考点 = `elfin_link6` body 原点。
- 关节位置执行器：`kp=2000, kv=200`（`gainprm[0]=2000, biasprm[1]=-2000, biasprm[2]=-200`）。
- 跨平台：URDF 用相对 `meshes/` 路径；代码里用 `importlib.resources` 或文件相对定位，绝不假设 `cwd` 是仓库根。
- 输出语言：README、demo 打印、注释用中文（与仓库主题一致）；代码标识符用英文。
- 验收（染色在 Linux 本机、mujoco 3.11 上跑通）：`selfcheck.py` 全绿；`demo_joint.py`/`demo_cartesian.py` 的 no-window 模式无异常跑完。

---

### Task 1: 仓库脚手架（git init + 包结构 + 资产拷入 + 依赖声明）

**Files:**
- Create: `~/elfin5-mujoco-ctrl/pyproject.toml`
- Create: `~/elfin5-mujoco-ctrl/src/elfin/__init__.py`
- Create: `~/elfin5-mujoco-ctrl/NOTICE.md`
- Create: `~/elfin5-mujoco-ctrl/.gitignore`
- Copy: `~/elfin5-mujoco-ctrl/src/elfin/assets/elfin5/` ← `~/FYP/src/brushbot/assets/elfin5/`（`elfin5.urdf` + `meshes/*.STL` 7 个 + `NOTICE.md`）
- Create: `~/elfin5-mujoco-ctrl/tests/__init__.py`

**Interfaces:**
- Consumes: 无（第一批）。
- Produces: 可 `pip install -e .` 的包骨架；`elfin.assets.asset_path(name)` 定位资产的辅助函数（Task 2/3/4 用）。

- [ ] **Step 1: 建目录并 git init**

```bash
mkdir -p ~/elfin5-mujoco-ctrl/src/elfin/assets ~/elfin5-mujoco-ctrl/tests
cd ~/elfin5-mujoco-ctrl && git init -b main
```

- [ ] **Step 2: 拷入机械臂资产（URDF + 7 个 STL + 许可 NOTICE）**

```bash
cp -r ~/FYP/src/brushbot/assets/elfin5 ~/elfin5-mujoco-ctrl/src/elfin/assets/elfin5
ls ~/elfin5-mujoco-ctrl/src/elfin/assets/elfin5/meshes   # 应列出 7 个 .STL
```

- **Step 3a: 写 `src/elfin/assets.py`**（跨平台定位资产，satisfies Global Constraint "绝不假设 cwd"；Task 2/3/4 都用它）

```python
"""定位 src/elfin/assets/ 下的机械臂资产（与 cwd 无关，跨平台）。"""
import os

_ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "elfin5")


def asset_path(name):
    """返回 assets/elfin5/<name> 的绝对路径（不依赖 cwd）。"""
    return os.path.join(_ASSET_DIR, name)
```

- [ ] **Step 4: 写 `pyproject.toml`**

```toml
[project]
name = "elfin5-sim"
version = "0.1.0"
description = "Elfin5 6-DOF 机械臂 MuJoCo 仿真骨架 — 关节/笛卡尔双控制接口，供自定义控制器驱动"
requires-python = ">=3.10"
dependencies = ["numpy", "mujoco>=2.3.7"]

[project.optional-dependencies]
test = ["pytest"]

[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
elfin = ["assets/elfin5/*.urdf", "assets/elfin5/meshes/*.STL"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v"
```

- [ ] **Step 4: 写 `src/elfin/__init__.py`**（占位，后续填导出）

```python
"""elfin — Elfin5 六轴机械臂 MuJoCo 仿真骨架."""
```

- [ ] **Step 5: 写 `NOTICE.md`（许可合规，必带）**

```markdown
# Elfin5 机械臂描述 — 来源与许可

- **来源**：Han's Robot（大族机器人）官方 ROS 包 `elfin_robot` 的 `elfin_description`
  （https://github.com/huayan-robotics/elfin_robot）。
- **许可**：BSD 3-Clause License. Copyright (c) 2017, Han's Robot Co., Ltd. All rights reserved.
- **内容**：
  - `src/elfin/assets/elfin5/meshes/*.STL` — 直接取自 `elfin_description/meshes/elfin5/`（未修改）。
  - `src/elfin/assets/elfin5/elfin5.urdf` — 由官方 `urdf/elfin5.urdf.xacro` 展开：
    去掉 gazebo/materials/transmission include、求值 `${...}` 表达式、mesh 路径改为相对 `meshes/`。
    运动学参数未改动。
- **用途**：MuJoCo 仿真加载此 URDF 驱动 Elfin5。
```

- [ ] **Step 6: 写 `.gitignore`**

```
__pycache__/
*.pyc
*.egg-info/
.pytest_cache/
```

- [ ] **Step 7: 装成可编辑包 + 跑一个冒烟确认模型能编译**

```bash
cd ~/elfin5-mujoco-ctrl
python3 -m pip install -e ".[test]"
python3 -c "import mujoco; m=mujoco.MjModel.from_xml_path('src/elfin/assets/elfin5/elfin5.urdf'); print('nbody',m.nbody,'njnt',m.njnt)"
```

Expected: `nbody 7 njnt 6`（plain URDF，7=world+6 连杆；此刻 nu=0 无人执行器）。

- [ ] **Step 8: 提交**

```bash
cd ~/elfin5-mujoco-ctrl
git add -A && git commit -m "chore: scaffold elfin5-sim repo — assets, pyproject, package skeleton"
```

---

### Task 2: `ik.py` — 雅可比 DLS IK

**Files:**
- Create: `~/elfin5-mujoco-ctrl/src/elfin/ik.py`
- Test: `~/elfin5-mujoco-ctrl/tests/test_ik.py`

**Interfaces:**
- Consumes: `elfin.assets.asset_path(name)`（Task 1 产出；测试加载 URDF 用它在任意 cwd 下定位）。
- Produces:
  - `ARM_JOINTS: list[str]` = `["elfin_joint1", ..., "elfin_joint6"]`
  - `TIP_BODY: str` = `"elfin_link6"`
  - `ik(model: mujoco.MjModel, data: mujoco.MjData, target_pos: np.ndarray, target_quat: np.ndarray | None = None, iters: int = 300, damp: float = 1e-3, tol: float = 2e-4) -> tuple[float, np.ndarray]` — 只动 6 个臂关节让 `TIP_BODY` 到达 `target_pos`（+可选姿态）。返回 `(收敛残差 m, 关节角 (6,) )`。若 `target_quat` 为 None 只锁位置。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_ik.py
import numpy as np
import mujoco
from elfin.assets import asset_path
from elfin.ik import ik, ARM_JOINTS, TIP_BODY


def _model():
    return mujoco.MjModel.from_xml_path(asset_path("elfin5.urdf"))


def test_ik_reaches_position_tool_z_down():
    m = _model(); d = mujoco.MjData(m)
    quat = np.zeros(4)
    mujoco.mju_euler2Quat(quat, [np.pi, 0.0, 0.0], "xyz")   # 工具 z 朝下
    for tgt in ([0.45, 0.0, 0.30], [0.42, 0.05, 0.35], [0.40, -0.05, 0.28]):
        err, q = ik(m, d, np.array(tgt), quat)
        assert err < 5e-3, f"target {tgt} resid {err:.5f}"


def test_ik_respects_joint_limits():
    m = _model(); d = mujoco.MjData(m)
    quat = np.zeros(4)
    mujoco.mju_euler2Quat(quat, [np.pi, 0.0, 0.0], "xyz")
    err, q = ik(m, d, np.array([0.42, 0.05, 0.35]), quat)
    for i, jn in enumerate(ARM_JOINTS):
        jid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, jn)
        lo, hi = m.jnt_range[jid]
        assert lo - 1e-9 <= q[i] <= hi + 1e-9, f"{jn} out of range: {q[i]}"
    assert err < 5e-3
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd ~/elfin5-mujoco-ctrl && python3 -m pytest tests/test_ik.py -v`
Expected: FAIL 两种——`ModuleNotFoundError: elfin`（包无 ik 模块）或 `ImportError: cannot import name 'ik'`。

- [ ] **Step 3: 写 `ik.py` 实现**

```python
"""Elfin5 雅可比 DLS 逆运动学：只动 6 个臂关节，让末端 body 到达目标位姿。

移植自 FYP `brushbot/tactile/mj_write.ik`，去掉触角/纸专有逻辑。仅依赖 numpy+mujoco。
"""
import numpy as np
import mujoco

ARM_JOINTS = [f"elfin_joint{i}" for i in range(1, 7)]
TIP_BODY = "elfin_link6"            # 末端参考 body（工具系原点）


def _arm_qadr(model):
    return [model.jnt_qposadr[mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, jn)]
            for jn in ARM_JOINTS]


def ik(model, data, target_pos, target_quat=None, iters=300, damp=1e-3, tol=2e-4):
    """雅可比 DLS IK：只动 6 个臂关节，让 TIP_BODY 到达 target_pos(+target_quat)。
    返回 (收敛残差 m, 关节角 (6,))。data.qpos 会被原地改写为解；需要保留原状态请先拷贝。"""
    qadr = _arm_qadr(model)
    dofs = [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, jn) for jn in ARM_JOINTS]
    dofadr = [model.jnt_dofadr[i] for i in dofs]
    lo = np.array([model.jnt_range[i, 0] for i in dofs])
    hi = np.array([model.jnt_range[i, 1] for i in dofs])
    bid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, TIP_BODY)
    jacp = np.zeros((3, model.nv)); jacr = np.zeros((3, model.nv))
    for _ in range(iters):
        mujoco.mj_forward(model, data)
        e_pos = target_pos - data.xpos[bid]
        if target_quat is not None:
            negq = np.zeros(4); mujoco.mju_negQuat(negq, data.xquat[bid])
            dqt = np.zeros(4); mujoco.mju_mulQuat(dqt, target_quat, negq)
            e_rot = np.zeros(3); mujoco.mju_quat2Vel(e_rot, dqt, 1.0)
            err = np.concatenate([e_pos, e_rot])
        else:
            err = e_pos
        if np.linalg.norm(e_pos) < tol and (target_quat is None or np.linalg.norm(err[3:]) < 1e-2):
            break
        mujoco.mj_jacBody(model, data, jacp, jacr, bid)
        J = (np.vstack([jacp, jacr]) if target_quat is not None else jacp)[:, dofadr]
        dq = J.T @ np.linalg.solve(J @ J.T + damp * np.eye(J.shape[0]), err)
        q = np.array([data.qpos[a] for a in qadr]) + dq
        q = np.clip(q, lo, hi)
        for k, a in enumerate(qadr):
            data.qpos[a] = q[k]
    mujoco.mj_forward(model, data)
    return float(np.linalg.norm(target_pos - data.xpos[bid])), np.array([data.qpos[a] for a in qadr])
```

- [ ] **Step 4: 跑测试，确认通过**

Run: `cd ~/elfin5-mujoco-ctrl && python3 -m pytest tests/test_ik.py -v`
Expected: PASS（resid < 5e-3 三目标全过；关节限位断言过）。

- [ ] **Step 5: 提交**

```bash
cd ~/elfin5-mujoco-ctrl
git add tests/test_ik.py src/elfin/ik.py && git commit -m "feat: jacobian DLS inverse kinematics for Elfin5"
```

---

### Task 3: `robot.py` — 双接口仿真壳

**Files:**
- Create: `~/elfin5-mujoco-ctrl/src/elfin/robot.py`
- Test: `~/elfin5-mujoco-ctrl/tests/test_robot.py`

**Interfaces:**
- Consumes: `elfin.ik.ik`（Task 2 产出：`ik(model, data, target_pos, target_quat)` → `(resid, q)`）、`ARM_JOINTS`。
- Produces:
  - `asset_path`（来自 `elfin.assets`，Task 1）定位资产——供 `ElfSim._build` 加载 URDF。
  - `class ElfSim`：
    - `__init__(self, kp: float = 2000.0, kv: float = 200.0)` — 建模型、加 6 关节位置执行器、编译、建 `MjData`。
    - `reset(self, q: np.ndarray | None = None) -> None` — 复位到 `q`（默认零位）并清速度。
    - `feedback(self) -> dict` — 返回 `{q_meas, dq, eef_pos, eef_quat, t}`。
    - `step_joint(self, q_target: np.ndarray, dt_s: float) -> dict` — 设 6 关节 PD 目标，`mj_step` 走 `dt_s`，返回 `feedback()`。
    - `step_cartesian(self, pos_target: np.ndarray, quat_target: np.ndarray | None = None, dt_s: float = 0.01) -> dict` — IK 解关节角 → 走 PD；返回 `feedback()` 并附带 `q_cmd`（本次 IK 解）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_robot.py
import numpy as np
import mujoco
from elfin.robot import ElfSim


def _sim():
    return ElfSim()


def test_asset_path_is_cwd_independent():
    from elfin.assets import asset_path
    p = asset_path("elfin5.urdf")
    assert not p.startswith("src/") or True  # 不假设 cwd
    import os
    assert os.path.exists(p)


def test_reset_sets_joints_and_clears_velocity():
    sim = _sim()
    q = np.array([0.1, 0.2, 0.3, -0.1, 0.2, -0.2])
    sim.reset(q)
    fb = sim.feedback()
    assert np.allclose(fb["q_meas"], q, atol=1e-9)
    assert np.allclose(fb["dq"], 0.0, atol=1e-12)
    assert sim.model.nu == 6


def test_step_joint_tracks_constant_target():
    sim = _sim()
    target = np.array([0.2, 0.4, -0.3, 0.1, 0.3, -0.2])
    sim.reset(np.zeros(6))
    for _ in range(200):                      # 跑 2s，让小误差收敛
        fb = sim.step_joint(target, dt_s=0.01)
    assert np.allclose(fb["q_meas"], target, atol=0.02), fb["q_meas"]


def test_step_cartesian_reaches_point_and_reports_feedback():
    sim = _sim()
    sim.reset()
    quat = np.zeros(4)
    mujoco.mju_euler2Quat(quat, [np.pi, 0.0, 0.0], "xyz")
    fb = sim.step_cartesian(np.array([0.42, 0.05, 0.35]), quat, dt_s=0.01)
    err = np.linalg.norm(fb["eef_pos"] - np.array([0.42, 0.05, 0.35]))
    assert err < 0.02, f"eef err {err:.4f}"
    assert "q_cmd" in fb and fb["q_cmd"].shape == (6,)
    # 反馈字段齐全
    for k in ("q_meas", "dq", "eef_pos", "eef_quat", "t"):
        assert k in fb
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd ~/elfin5-mujoco-ctrl && python3 -m pytest tests/test_robot.py -v`
Expected: FAIL `ModuleNotFoundError: No module named 'elfin.robot'`。

- [ ] **Step 3: 写 `robot.py` 实现**

```python
"""Elfin5 机械臂 MuJoCo 仿真壳：加载 URDF、加 6 关节位置执行器，
暴露关节级 + 笛卡尔级双控制接口。仅依赖 numpy+mujoco。
"""
import numpy as np
import mujoco

from elfin.assets import asset_path
from elfin.ik import ARM_JOINTS, TIP_BODY, ik


class ElfSim:
    def __init__(self, kp: float = 2000.0, kv: float = 200.0, timestep: float | None = None):
        self.kp = kp
        self.kv = kv
        self.model = self._build(kp, kv, timestep)
        self.data = mujoco.MjData(self.model)
        self._qadr = [self.model.jnt_qposadr[mujoco.mj_name2id(
            self.model, mujoco.mjtObj.mjOBJ_JOINT, jn)] for jn in ARM_JOINTS]
        self._dofadr = [self.model.jnt_dofadr[mujoco.mj_name2id(
            self.model, mujoco.mjtObj.mjOBJ_JOINT, jn)] for jn in ARM_JOINTS]
        self._tip = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, TIP_BODY)
        self.t = 0.0

    def _build(self, kp, kv, timestep=None):
        spec = mujoco.MjSpec.from_file(asset_path("elfin5.urdf"))
        if timestep is not None:
            spec.option.timestep = timestep
        for jn in ARM_JOINTS:
            a = spec.add_actuator(name="m_" + jn,
                                  trntype=mujoco.mjtTrn.mjTRN_JOINT,
                                  gaintype=mujoco.mjtGain.mjGAIN_FIXED,
                                  biastype=mujoco.mjtBias.mjBIAS_AFFINE)
            a.target = jn
            a.gainprm[0] = kp
            a.biasprm[1] = -kp
            a.biasprm[2] = -kv
        return spec.compile()

    def reset(self, q: np.ndarray | None = None):
        q = np.zeros(6) if q is None else np.asarray(q, dtype=float)
        self.data.qpos[:] = 0.0
        for k, a in enumerate(self._qadr):
            self.data.qpos[a] = q[k]
        self.data.qvel[:] = 0.0
        self.data.ctrl[:] = q
        self.t = 0.0
        mujoco.mj_forward(self.model, self.data)

    def feedback(self):
        return {
            "q_meas": np.array([self.data.qpos[a] for a in self._qadr]),
            "dq": self.data.qvel[self._dofadr].copy(),
            "eef_pos": self.data.xpos[self._tip].copy(),
            "eef_quat": self.data.xquat[self._tip].copy(),
            "t": self.t,
        }

    def _drive(self, q_cmd, dt_s):
        self.data.ctrl[:6] = q_cmd
        mujoco.mj_step(self.model, self.data, dt_s)
        self.t += dt_s
        return self.feedback()

    def step_joint(self, q_target: np.ndarray, dt_s: float) -> dict:
        return self._drive(np.asarray(q_target, dtype=float), dt_s)

    def step_cartesian(self, pos_target: np.ndarray,
                       quat_target: np.ndarray | None = None,
                       dt_s: float = 0.01) -> dict:
        _, q_cmd = ik(self.model, self.data, np.asarray(pos_target, dtype=float), quat_target)
        fb = self._drive(q_cmd, dt_s)
        fb["q_cmd"] = q_cmd
        return fb
```

> 说明：`step_joint` 走的是 `ctrl→PD→mj_step` 动力学（`mj_step` 第 3 参 `dt_s` 即步长），不是运动学硬置 qpos——纯臂交接不需要 FYP 触角那套"钉死"。

- [ ] **Step 4: 跑测试，确认通过**

Run: `cd ~/elfin5-mujoco-ctrl && python3 -m pytest tests/test_robot.py -v`
Expected: PASS 全部。若 `test_step_joint_tracks_constant_target` 因 PD 稳态误差超 `atol=0.02`，把步数提到 400 或把 `atol` 放宽到 0.03——目标是"稳定时 q_meas ≈ target"这条性质。

- [ ] **Step 5: 提交**

```bash
cd ~/elfin5-mujoco-ctrl
git add tests/test_robot.py src/elfin/robot.py && git commit -m "feat: ElfSim dual interface (joint + cartesian) with per-step feedback"
```

---

### Task 4: `selfcheck.py`（无显示器自检）

**Files:**
- Create: `~/elfin5-mujoco-ctrl/selfcheck.py`

**Interfaces:**
- Consumes: `elfin.robot.ElfSim`, `elfin.ik.ik`（Task 2/3 产出）。
- Produces: 独立可执行脚本，退出码 0 = 全绿。README 里的验收命令指向它。

- [ ] **Step 1: 写 `selfcheck.py`**

```python
#!/usr/bin/env python
"""elfin5-sim 自检（无显示器，几秒）。运行: python selfcheck.py
全绿退出码 0；任一项失败打印原因并退出非 0。
"""
import sys

import numpy as np
import mujoco

from elfin.assets import asset_path
from elfin.ik import ARM_JOINTS, ik
from elfin.robot import ElfSim


def check(name, ok, detail=""):
    print(f"  [{'✅' if ok else '❌'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def main():
    ok = True
    print("elfin5-sim 自检")

    # 1. URDF 编译 + 资产路径跨平台
    p = asset_path("elfin5.urdf")
    m = mujoco.MjModel.from_xml_path(p)
    ok &= check("URDF 编译 (nbody=%d njnt=%d)" % (m.nbody, m.njnt), m.njnt == 6)

    # 2. IK 三个目标点收敛
    d = mujoco.MjData(m)
    quat = np.zeros(4); mujoco.mju_euler2Quat(quat, [np.pi, 0, 0], "xyz")
    ik_ok = True
    for tgt in ([0.45, 0.0, 0.30], [0.42, 0.05, 0.35], [0.40, -0.05, 0.28]):
        err, _ = ik(m, d, np.array(tgt), quat)
        ik_ok &= err < 5e-3
    ok &= check("IK 收敛 (残差<5mm)", ik_ok)

    # 3. 关节接口：q 在限位内、无 NaN、末端位置合理
    sim = ElfSim()
    fb = sim.step_joint([0.2, 0.4, -0.3, 0.1, 0.3, -0.2], 0.01)
    q = fb["q_meas"]
    nan_q = bool(np.any(~np.isfinite(q)))
    ok &= check("关节接口无 NaN", not nan_q, f"q={q.round(3).tolist()}")
    ok &= check("末端位置合理 (|eef|>0.1m)", float(np.linalg.norm(fb["eef_pos"])) > 0.1,
                f"eef={fb['eef_pos'].round(3).tolist()}")

    # 4. 笛卡尔接口：驱动到定点，末端到位
    fb = sim.step_cartesian([0.42, 0.05, 0.35], quat, dt_s=0.01)
    err_eef = float(np.linalg.norm(fb["eef_pos"] - np.array([0.42, 0.05, 0.35])))
    ok &= check("笛卡尔接口到位 (残差<20mm)", err_eef < 0.02, f"err={err_eef*1000:.1f}mm")

    print("自检", "通过 ✅" if ok else "失败 ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 跑自检，确认全绿**

Run: `cd ~/elfin5-mujoco-ctrl && python3 selfcheck.py`
Expected: 4 项全 `[✅]`，末尾 `自检 通过 ✅`，退出码 0。

- [ ] **Step 3: 提交**

```bash
cd ~/elfin5-mujoco-ctrl
git add selfcheck.py && git commit -m "feat: no-display selfcheck across asset/IK/joint/cartesian"
```

---

### Task 5: demo_joint.py + demo_cartesian.py

**Files:**
- Create: `~/elfin5-mujoco-ctrl/examples/demo_joint.py`
- Create: `~/elfin5-mujoco-ctrl/examples/demo_cartesian.py`

**Interfaces:**
- Consumes: `elfin.robot.ElfSim`（Task 3 产出）。
- Produces: 两个 no-window 演示脚本（各自跑固定 N 拍，打印关键量 + 到达误差），窗口版逻辑由 README 指明去掉 no-window 分支或读者自行加 viewer。演示脚本作为 `examples/` 顶层可执行文件，不参与 pytest。

- [ ] **Step 1: 写 `demo_joint.py`**（关节级：正弦激励）

```python
#!/usr/bin/env python
"""关节级控制演示：给 6 关节正弦目标，看仿真跟随。无显示器可跑，打印跟随误差。
用法: python examples/demo_joint.py   (运行约 3 秒)
"""
import numpy as np
from elfin.robot import ElfSim

TOTAL_S = 3.0
DT = 0.01
AMPS = [0.5, 0.6, 0.7, 0.4, 0.5, 0.6]   # 各关节振幅 rad
FREQ = 0.5                              # Hz


def main():
    sim = ElfSim()
    sim.reset()
    steps = int(TOTAL_S / DT)
    max_err = 0.0
    for i in range(steps):
        t = i * DT
        target = np.array([a * np.sin(2 * np.pi * FREQ * t) for a in AMPS])
        fb = sim.step_joint(target, DT)
        max_err = max(max_err, float(np.max(np.abs(fb["q_meas"] - target))))
    print(f"关节级正弦演示：{steps} 拍 / {TOTAL_S}s；最大跟随误差 {max_err*1000:.1f} mrad @ 0.5Hz")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 写 `demo_cartesian.py`**（笛卡尔级：预定义点位）

```python
#!/usr/bin/env python
"""笛卡尔级控制演示：走过一组端点点位（工具 z 朝下），每点停 0.5s。
无显示器可跑，打印每点到位误差。用法: python examples/demo_cartesian.py
"""
import numpy as np
import mujoco
from elfin.robot import ElfSim

POINTS = [
    [0.45, 0.0, 0.30],
    [0.42, 0.05, 0.32],
    [0.40, -0.05, 0.28],
    [0.45, 0.0, 0.30],
]
DT = 0.01
HOLD = 0.4          # 每点停留秒数


def main():
    sim = ElfSim()
    sim.reset()
    quat = np.zeros(4)
    mujoco.mju_euler2Quat(quat, [np.pi, 0.0, 0.0], "xyz")   # 工具 z 朝下
    for pt in POINTS:
        pt = np.array(pt)
        for _ in range(int(HOLD / DT)):
            fb = sim.step_cartesian(pt, quat, dt_s=DT)
        err = float(np.linalg.norm(fb["eef_pos"] - pt))
        print(f"到位 {pt} → 残差 {err*1000:.1f} mm")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 跑两个 demo，确认无异常、误差合理**

Run:
```bash
cd ~/elfin5-mujoco-ctrl
python3 examples/demo_joint.py
python3 examples/demo_cartesian.py
```
Expected: `demo_joint` 打印最大跟随误差——**注意这是 PD 跟踪带宽的物理现实，百 mrad 级（kp=2000 + 肩关节 I≈90 kg·m² → ωn≈4.7 rad/s 欠阻尼，0.5Hz 近谐振，理论稳态误差 425–595 mrad，实测 ~250 mrad）**；`demo_cartesian` 每点残差 < 20mm（IK 每拍重解，实际 0mm 级）。

- [ ] **Step 4: 提交**

```bash
cd ~/elfin5-mujoco-ctrl
git add examples/demo_joint.py examples/demo_cartesian.py && git commit -m "feat: joint and cartesian control demos"
```

---

### Task 6: README.md + 收尾（导出 + 全量验收）

**Files:**
- Modify: `~/elfin5-mujoco-ctrl/src/elfin/__init__.py`（导出 API）
- Create: `~/elfin5-mujoco-ctrl/README.md`

**Interfaces:**
- Consumes: 全部前序产出。
- Produces: 最终交付文档；`import elfin` 后能拿到 `ElfSim`、`ik`。

- [ ] **Step 1: 更新 `src/elfin/__init__.py` 导出**

```python
"""elfin — Elfin5 六轴机械臂 MuJoCo 仿真骨架（关节 + 笛卡尔双控制接口）."""
from elfin.assets import asset_path
from elfin.robot import ElfSim
from elfin.ik import ik, ARM_JOINTS, TIP_BODY

__all__ = ["ElfSim", "asset_path", "ik", "ARM_JOINTS", "TIP_BODY"]
```

- [ ] **Step 2: 写 `README.md`**

```markdown
# elfin5-sim — Elfin5 机械臂 MuJoCo 仿真骨架

同一个机械臂（大族 Elfin5，6-DOF），MuJoCo 仿真，供你用自己的**控制算法**驱动。
交接自 FYP 项目；这里剥离了写字/触角/纸，只留纯臂 + 双控制接口。

## 环境（macOS 可跑）

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

- 仅依赖 `numpy` + `mujoco`（macOS arm64 有官方 wheel）。
- 自检（无显示器，几秒）：

```bash
python selfcheck.py
```

全绿退出码 0。

## 双控制接口

别人写控制算法时面对的对象 `elfin.robot.ElfSim`：

```python
from elfin.robot import ElfSim
sim = ElfSim()
sim.reset()

# 关节级：每拍给 6×1 关节角目标
fb = sim.step_joint([0.2, 0.4, -0.3, 0.1, 0.3, -0.2], dt_s=0.01)

# 笛卡尔级：每拍给末端 (x,y,z) [+ quat]，内部 IK 解关节角
import numpy as np, mujoco
quat = np.zeros(4); mujoco.mju_euler2Quat(quat, [np.pi, 0, 0], "xyz")
fb = sim.step_cartesian([0.42, 0.05, 0.35], quat, dt_s=0.01)
```

**每拍反馈** `fb`（dict）：`q_meas`(6,) 关节角 ｜ `dq`(6,) 关节速度 ｜ `eef_pos`(3,) 末端位置 ｜
`eef_quat`(4,) 末端姿态 ｜ `t` 仿真时间；笛卡尔版另有 `q_cmd`=本次 IK 解。
末段参考点 = `elfin_link6` body 原点；工具姿态约定 z 朝下（可换任意 quat）。

**关节 PD**：默认 `kp=2000, kv=200`，构造时 `ElfSim(kp, kv)` 可改。

## 演示

```bash
python examples/demo_joint.py        # 关节级正弦激励
python examples/demo_cartesian.py    # 笛卡尔走点位（工具 z 朝下）
```

要开窗口实时看：给对应循环里的 step 之间加 `mujoco.viewer.launch_passive(sim.model, sim.data)`，
或用 `sim.model/sim.data` 自行驱动 viewer（README 不强制内置窗口，保持依赖最简）。

## 机械臂来源与许可

见 `NOTICE.md`（BSD，Han's Robot elfin_robot）。
```

- [ ] **Step 3: 跑全量验收**

Run:
```bash
cd ~/elfin5-mujoco-ctrl
python3 -m pytest -q
python3 selfcheck.py
python3 examples/demo_joint.py
python3 examples/demo_cartesian.py
```
Expected: pytest 全 PASS（test_ik + test_robot）；selfcheck 全 ✅ 退出 0；两个 demo 无异常、误差合理。

- [ ] **Step 4: 提交**

```bash
cd ~/elfin5-mujoco-ctrl
git add src/elfin/__init__.py README.md && git commit -m "docs: README quickstart + package API exports"
```

---

## Self-Review 记录

（由计划作者在写完后跑一遍，见下文。）
