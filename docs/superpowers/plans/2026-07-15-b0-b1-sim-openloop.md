# B0 + B1（仿真开环写字）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 PyBullet 仿真里把"算法↔I/O 解耦"的三层控制骨架搭起来，并跑通**开环写字**（复现 CalliRewrite 的位置控宽度），全程不碰实机。

**Architecture:** 三层——① 纯算法层（环境无关，numpy）② 后端层（`RobotBackend` 协议 + `SimBackend`/`FakeBackend`）③ 运行循环。开环写字 = `(p_t,x,y,r)` 笔序 → `process()` 出 `(x,y,z)` 路点 → `OpenLoopController` 逐拍插值出目标位姿 → 后端驱动机械臂 → 记录笔尖轨迹 → 渲染成"墨迹"图。详见 `docs/control-architecture.md`。

**Tech Stack:** Python 3.10, numpy, pybullet, pytest, Pillow(渲染)。

## Global Constraints

- **不碰实机**：只用 PyBullet；实机后端（`HuayanBackend`）不在本计划范围。
- **单位**：仿真内统一 **米 + 弧度**（与 CalliRewrite `process()` 输出一致）。
- **机械臂 URDF 可配置**：默认用 `pybullet_data` 自带的 `kuka_iiwa/model.urdf` 起步；换 Elfin5 URDF 只改 `brushbot/config.py` 里 `ARM_URDF` 一行。
- **姿态 v1 固定**：笔杆垂直，`FIXED_ORI` 常量，不在本阶段做姿态控制。
- **TCP 位姿表示**：`(x, y, z, roll, pitch, yaw)`，位置米、姿态弧度。
- **TDD**：先写失败测试→跑失败→最小实现→跑通→提交。每个任务结束是一个可独立测试的交付物。
- **提交信息**用英文 `feat:`/`test:`/`chore:` 前缀。

---

# Phase B0 · 环境 + 三层骨架

### Task 0: Python 项目与依赖

**Files:**
- Create: `pyproject.toml`
- Create: `src/brushbot/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/test_smoke.py`

**Interfaces:**
- Produces: 可用的 `brushbot` 包 + `pytest` 运行环境。

- [ ] **Step 1: 建 conda 环境并装依赖**

Run: `conda create -y -n brushbot python=3.10 && conda run -n brushbot pip install pybullet numpy pytest pillow`
Expected: 安装成功，无报错。

- [ ] **Step 2: 写 `pyproject.toml`**

```toml
[project]
name = "brushbot"
version = "0.0.1"
requires-python = ">=3.10"
dependencies = ["numpy", "pybullet", "pillow"]

[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v"
```

- [ ] **Step 3: 建包与冒烟测试**

`src/brushbot/__init__.py`:
```python
__version__ = "0.0.1"
```

`tests/__init__.py`: （空文件）

`tests/test_smoke.py`:
```python
import brushbot

def test_import():
    assert brushbot.__version__ == "0.0.1"
```

- [ ] **Step 4: 可编辑安装并跑测试**

Run: `conda run -n brushbot pip install -e . && conda run -n brushbot pytest`
Expected: 1 passed。

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/brushbot/__init__.py tests/__init__.py tests/test_smoke.py
git commit -m "chore: scaffold brushbot python package with pytest"
```

---

### Task 1: 核心数据类型 State / Command

**Files:**
- Create: `src/brushbot/types.py`
- Test: `tests/test_types.py`

**Interfaces:**
- Produces:
  - `State(tcp_pose: tuple[float,...], g_meas: float, t: float)`
  - `Command(tcp_pose: tuple[float,...])`
  - `tcp_pose` 恒为 6 元组 `(x,y,z,roll,pitch,yaw)`。

- [ ] **Step 1: 写失败测试**

`tests/test_types.py`:
```python
from brushbot.types import State, Command

def test_state_fields():
    s = State(tcp_pose=(0.4, 0.0, 0.1, 3.14159, 0.0, 0.0), g_meas=0.0, t=0.0)
    assert s.tcp_pose[0] == 0.4
    assert s.g_meas == 0.0
    assert s.t == 0.0

def test_command_pose_len():
    c = Command(tcp_pose=(0.4, 0.0, 0.1, 3.14159, 0.0, 0.0))
    assert len(c.tcp_pose) == 6
```

- [ ] **Step 2: 跑失败**

Run: `conda run -n brushbot pytest tests/test_types.py`
Expected: FAIL（`No module named brushbot.types`）。

- [ ] **Step 3: 实现**

`src/brushbot/types.py`:
```python
from dataclasses import dataclass

@dataclass
class State:
    tcp_pose: tuple   # (x, y, z, roll, pitch, yaw) 米/弧度
    g_meas: float     # 触觉提按分量 (B1 开环恒为 0)
    t: float          # 仿真时间 (秒)

@dataclass
class Command:
    tcp_pose: tuple   # 目标 (x, y, z, roll, pitch, yaw)
```

- [ ] **Step 4: 跑通**

Run: `conda run -n brushbot pytest tests/test_types.py`
Expected: 2 passed。

- [ ] **Step 5: Commit**

```bash
git add src/brushbot/types.py tests/test_types.py
git commit -m "feat: add State and Command core types"
```

---

### Task 2: 后端协议 + FakeBackend + 运行循环

**Files:**
- Create: `src/brushbot/backends/__init__.py`
- Create: `src/brushbot/backends/base.py`
- Create: `src/brushbot/backends/fake.py`
- Create: `src/brushbot/run.py`
- Test: `tests/test_run.py`

**Interfaces:**
- Consumes: `State`, `Command`（Task 1）。
- Produces:
  - `RobotBackend` 协议：`read() -> State`、`write(cmd: Command) -> None`。
  - `FakeBackend(dt: float)`：`write` 时记录命令位姿并把该位姿当作下一次 `read` 的 `tcp_pose`；每次 `write` 令 `t += dt`。
  - `run(backend, controller, on_tick=None)`：循环 `read→step→write`，直到 `controller.done()`；每拍调 `on_tick(state)`。
  - `controller` 约定：`step(state) -> Command`、`done() -> bool`。

- [ ] **Step 1: 写失败测试**

`tests/test_run.py`:
```python
from brushbot.types import State, Command
from brushbot.backends.fake import FakeBackend
from brushbot.run import run

class GotoController:
    """两拍后停止，一直命令同一个目标位姿。"""
    def __init__(self, target):
        self.target = target
        self.calls = 0
    def step(self, state: State) -> Command:
        self.calls += 1
        return Command(tcp_pose=self.target)
    def done(self) -> bool:
        return self.calls >= 2

def test_fake_backend_echoes_command():
    b = FakeBackend(dt=0.02)
    b.write(Command(tcp_pose=(1, 2, 3, 0, 0, 0)))
    st = b.read()
    assert st.tcp_pose == (1, 2, 3, 0, 0, 0)
    assert st.t == 0.02

def test_run_records_ticks():
    b = FakeBackend(dt=0.02)
    ctrl = GotoController(target=(0.4, 0.0, 0.1, 0, 0, 0))
    ticks = []
    run(b, ctrl, on_tick=lambda s: ticks.append(s.tcp_pose))
    assert len(ticks) == 2
    assert ticks[-1] == (0.4, 0.0, 0.1, 0, 0, 0)
```

- [ ] **Step 2: 跑失败**

Run: `conda run -n brushbot pytest tests/test_run.py`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现**

`src/brushbot/backends/__init__.py`: （空文件）

`src/brushbot/backends/base.py`:
```python
from typing import Protocol
from brushbot.types import State, Command

class RobotBackend(Protocol):
    def read(self) -> State: ...
    def write(self, cmd: Command) -> None: ...
```

`src/brushbot/backends/fake.py`:
```python
from brushbot.types import State, Command

class FakeBackend:
    """纯逻辑后端：把命令位姿原样回显，用于单测运行循环与控制器。"""
    def __init__(self, dt: float):
        self.dt = dt
        self._pose = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        self._t = 0.0
    def read(self) -> State:
        return State(tcp_pose=self._pose, g_meas=0.0, t=self._t)
    def write(self, cmd: Command) -> None:
        self._pose = cmd.tcp_pose
        self._t += self.dt
```

`src/brushbot/run.py`:
```python
def run(backend, controller, on_tick=None):
    """定频跑 read->step->write，直到 controller.done()。每拍回调 on_tick(state)。"""
    while not controller.done():
        st = backend.read()
        cmd = controller.step(st)
        backend.write(cmd)
        if on_tick is not None:
            on_tick(backend.read())
```

- [ ] **Step 4: 跑通**

Run: `conda run -n brushbot pytest tests/test_run.py`
Expected: 2 passed。

- [ ] **Step 5: Commit**

```bash
git add src/brushbot/backends/ src/brushbot/run.py tests/test_run.py
git commit -m "feat: add RobotBackend protocol, FakeBackend, run loop"
```

---

### Task 3: 配置 + PyBullet 场景（机械臂 + 纸面）

**Files:**
- Create: `src/brushbot/config.py`
- Create: `src/brushbot/scene.py`
- Test: `tests/test_scene.py`

**Interfaces:**
- Produces:
  - `config.ARM_URDF`（默认 kuka）、`config.PAPER_Z=0.0`、`config.FIXED_ORI=(pi,0,0)`、`config.CHAR_ORIGIN=(0.5,0.0)`、`config.EEF_LINK`。
  - `Scene(gui: bool=False)`：`.load()` 载入平面+机械臂；`.num_joints -> int`；`.tcp_pose() -> tuple6`（末端 link 的位姿，euler）；`.set_joints(q)`；`.ik(pos_xyz, ori_euler) -> list[float]`；`.step()`。

- [ ] **Step 1: 写冒烟测试**

`tests/test_scene.py`:
```python
from brushbot.scene import Scene

def test_scene_loads_and_reads_tcp():
    sc = Scene(gui=False)
    sc.load()
    assert sc.num_joints >= 6
    pose = sc.tcp_pose()
    assert len(pose) == 6
    sc.close()

def test_ik_reaches_target():
    sc = Scene(gui=False)
    sc.load()
    target = (0.5, 0.0, 0.3)
    q = sc.ik(target)                 # 位置-only IK
    sc.set_joints(q)
    for _ in range(240):
        sc.step()
    x, y, z = sc.tcp_pose()[:3]
    err = ((x-target[0])**2 + (y-target[1])**2 + (z-target[2])**2) ** 0.5
    assert err < 0.02   # 2cm 内
    sc.close()
```

- [ ] **Step 2: 跑失败**

Run: `conda run -n brushbot pytest tests/test_scene.py`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现 config + scene**

`src/brushbot/config.py`:
```python
import math
import pybullet_data
import os

# 默认用 pybullet 自带 KUKA 起步; 换 Elfin5 时改这一行为 Elfin URDF 路径
ARM_URDF = os.path.join(pybullet_data.getDataPath(), "kuka_iiwa", "model.urdf")
EEF_LINK = 6            # KUKA 末端 link index (7-DOF: 0..6)
PAPER_Z = 0.2          # 书写平面高度 (米), 选臂可达的中间高度; 仿真里纸是抽象 z 平面
Z_TOUCH_REF = 0.009    # CalliRewrite z 帧里"刚触纸"的参考 z (func_brush 上端附近)
FIXED_ORI = (math.pi, 0.0, 0.0)   # 笔杆垂直 (随 URDF 调; 本阶段 IK 只约束位置)
CHAR_ORIGIN = (0.45, 0.0)         # 字在书写平面上的中心 (x,y 米), 保证臂可达
TICK_DT = 1.0 / 240.0
```

`src/brushbot/scene.py`:
```python
import pybullet as p
import pybullet_data
from brushbot import config

class Scene:
    def __init__(self, gui: bool = False):
        self._gui = gui
        self.cid = None
        self.robot = None
        self.num_joints = 0

    def load(self):
        self.cid = p.connect(p.GUI if self._gui else p.DIRECT)
        p.setAdditionalSearchPath(pybullet_data.getDataPath())
        p.setGravity(0, 0, -9.81)
        p.loadURDF("plane.urdf", [0, 0, config.PAPER_Z])
        self.robot = p.loadURDF(config.ARM_URDF, [0, 0, 0], useFixedBase=True)
        self.num_joints = p.getNumJoints(self.robot)

    def tcp_pose(self):
        ls = p.getLinkState(self.robot, config.EEF_LINK)
        pos = ls[0]
        euler = p.getEulerFromQuaternion(ls[1])
        return (pos[0], pos[1], pos[2], euler[0], euler[1], euler[2])

    def ik(self, pos_xyz, ori_euler=None):
        # B1 用位置-only IK, 保证笔尖到达 xyz (姿态 v1 不约束, 留给 B2/实机)
        if ori_euler is None:
            q = p.calculateInverseKinematics(self.robot, config.EEF_LINK, pos_xyz)
        else:
            quat = p.getQuaternionFromEuler(ori_euler)
            q = p.calculateInverseKinematics(self.robot, config.EEF_LINK, pos_xyz, quat)
        return list(q)

    def set_joints(self, q):
        for i in range(min(len(q), self.num_joints)):
            p.setJointMotorControl2(self.robot, i, p.POSITION_CONTROL, q[i], force=200)

    def step(self):
        p.stepSimulation()

    def close(self):
        if self.cid is not None:
            p.disconnect()
            self.cid = None
```

- [ ] **Step 4: 跑通**

Run: `conda run -n brushbot pytest tests/test_scene.py`
Expected: 2 passed（若 `test_ik_reaches_target` 因臂可达域略超，把 `target` 移近或放宽到 0.03）。

- [ ] **Step 5: Commit**

```bash
git add src/brushbot/config.py src/brushbot/scene.py tests/test_scene.py
git commit -m "feat: add pybullet Scene (arm + paper plane + IK/FK)"
```

> **备注（换 Elfin5）**：拿到 Elfin URDF 后，把 `config.ARM_URDF` 指向它、`EEF_LINK` 改成 Elfin 末端 link index、`FIXED_ORI` 按其工具系调。其余代码不动。

---

### Task 4: SimBackend（PyBullet 后端）

**Files:**
- Create: `src/brushbot/backends/sim.py`
- Test: `tests/test_sim_backend.py`

**Interfaces:**
- Consumes: `Scene`（Task 3）、`State`/`Command`（Task 1）。
- Produces:
  - `ZeroTactile`：`.value() -> float` 恒返回 0.0（B1 占位，B2 换真流）。
  - `SimBackend(scene: Scene, tactile, substeps: int=4)`：
    - `read() -> State`：`tcp_pose` 来自 `scene.tcp_pose()`，`g_meas=tactile.value()`，`t` 为累计仿真时间。
    - `write(cmd)`：`scene.ik` → `scene.set_joints` → `scene.step()` 跑 `substeps` 步，`t += substeps*TICK_DT`。

- [ ] **Step 1: 写集成测试**

`tests/test_sim_backend.py`:
```python
import math
from brushbot.scene import Scene
from brushbot.backends.sim import SimBackend, ZeroTactile
from brushbot.types import Command

def test_sim_backend_tracks_command():
    sc = Scene(gui=False); sc.load()
    b = SimBackend(sc, ZeroTactile(), substeps=8)
    target = (0.5, 0.0, 0.3, math.pi, 0.0, 0.0)
    for _ in range(60):
        b.write(Command(tcp_pose=target))
    st = b.read()
    x, y, z = st.tcp_pose[:3]
    err = ((x-0.5)**2 + (y-0.0)**2 + (z-0.3)**2) ** 0.5
    assert err < 0.02
    assert st.g_meas == 0.0
    assert st.t > 0.0
    sc.close()
```

- [ ] **Step 2: 跑失败**

Run: `conda run -n brushbot pytest tests/test_sim_backend.py`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现**

`src/brushbot/backends/sim.py`:
```python
from brushbot.types import State, Command
from brushbot import config

class ZeroTactile:
    """B1 占位触觉源; B2 换成合成提按 / 真实 g_meas 流。"""
    def value(self) -> float:
        return 0.0

class SimBackend:
    def __init__(self, scene, tactile, substeps: int = 4):
        self.scene = scene
        self.tactile = tactile
        self.substeps = substeps
        self._t = 0.0

    def read(self) -> State:
        return State(tcp_pose=self.scene.tcp_pose(),
                     g_meas=self.tactile.value(),
                     t=self._t)

    def write(self, cmd: Command) -> None:
        pos = cmd.tcp_pose[:3]
        q = self.scene.ik(pos)          # 位置-only IK (姿态 v1 不约束)
        self.scene.set_joints(q)
        for _ in range(self.substeps):
            self.scene.step()
        self._t += self.substeps * config.TICK_DT
```

- [ ] **Step 4: 跑通**

Run: `conda run -n brushbot pytest tests/test_sim_backend.py`
Expected: 1 passed。

- [ ] **Step 5: Commit**

```bash
git add src/brushbot/backends/sim.py tests/test_sim_backend.py
git commit -m "feat: add SimBackend (pybullet read/write via IK)"
```

---

# Phase B1 · 开环写字（复现 CalliRewrite）

### Task 5: r→z 标定函数（CalliRewrite `func_brush`）

**Files:**
- Create: `src/brushbot/calligraphy/__init__.py`
- Create: `src/brushbot/calligraphy/calibration.py`
- Test: `tests/test_calibration.py`

**Interfaces:**
- Produces:
  - `func_brush(r: float) -> float`：CalliRewrite 毛笔 4 段分段线性 r→z（米）。
  - `piecewise_linear(r, xs, ys, k0, k1) -> float`：通用分段线性（供以后自标定用）。

- [ ] **Step 1: 写失败测试**

`tests/test_calibration.py`:
```python
from brushbot.calligraphy.calibration import func_brush

def test_func_brush_monotonic_decreasing():
    # r 越大(笔画越宽) -> z 越小(压越深)
    zs = [func_brush(r) for r in [0.0002, 0.001, 0.002, 0.003]]
    assert zs[0] > zs[1] > zs[2] > zs[3]

def test_func_brush_overflow_protection():
    assert func_brush(0.01) == -0.006   # 超范围返回极限 z
```

- [ ] **Step 2: 跑失败**

Run: `conda run -n brushbot pytest tests/test_calibration.py`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现（照抄 CalliRewrite `callibrate.ipynb` 的 `func_brush`）**

`src/brushbot/calligraphy/__init__.py`: （空文件）

`src/brushbot/calligraphy/calibration.py`:
```python
def func_brush(radii: float) -> float:
    """CalliRewrite 毛笔 r->z 标定曲线 (米). 见 docs/callirewrite-arm-control.md."""
    r = radii
    if 0 <= r <= 7.72667536e-04:
        return -5.9701493 * (r - 7.72667536e-04) + 4.34974603e-03
    elif r <= 1.78125854e-03:
        return -1.538473 * (r - 7.72667536e-04) + 4.34974603e-03
    elif r <= 2.45866277e-03:
        return -6.028019 * (r - 1.78125854e-03) + 2.79805600e-03
    elif r < 0.0045:
        return -2.37843574 * (r - 2.45866277e-03) - 1.28534957e-03
    return -0.006   # 溢出保护

def piecewise_linear(r, xs, ys, k0, k1):
    """通用分段线性; xs 升序断点, ys 对应值, k0/k1 两端外斜率. 供自标定用。"""
    if r <= xs[0]:
        return k0 * (r - xs[0]) + ys[0]
    for i in range(len(xs) - 1):
        if r <= xs[i + 1]:
            t = (r - xs[i]) / (xs[i + 1] - xs[i])
            return ys[i] + t * (ys[i + 1] - ys[i])
    return k1 * (r - xs[-1]) + ys[-1]
```

- [ ] **Step 4: 跑通**

Run: `conda run -n brushbot pytest tests/test_calibration.py`
Expected: 2 passed。

- [ ] **Step 5: Commit**

```bash
git add src/brushbot/calligraphy/__init__.py src/brushbot/calligraphy/calibration.py tests/test_calibration.py
git commit -m "feat: port CalliRewrite r->z brush calibration"
```

---

### Task 6: 笔序 → 控制点 `process()`（CalliRewrite 端口）

**Files:**
- Create: `src/brushbot/calligraphy/strokeseq.py`
- Test: `tests/test_strokeseq.py`

**Interfaces:**
- Consumes: `func_brush`（Task 5）。
- Produces:
  - `process(seq, r2z, alpha=0.04, beta=0.5) -> list[tuple[float,float,float]]`
    - `seq`: `list[(p_t, x, y, r)]`，坐标/半径为归一化值。
    - 返回米制 `(x, y, z)` 路点列表；`p_t==1` 为新笔起笔（楷书从左上入锋、悬空 z=0.05 进入）；`p_t==0` 延续；末尾追加 5 点抬笔离纸。
    - 简化：只实现楷书路径（`process()` 里 `type==1` 分支），隶书回锋略。

- [ ] **Step 1: 写失败测试**

`tests/test_strokeseq.py`:
```python
from brushbot.calligraphy.strokeseq import process
from brushbot.calligraphy.calibration import func_brush

def test_process_scales_xy_by_alpha():
    seq = [(0, 0.5, 0.5, 0.001)]     # 延续点
    pts = process(seq, func_brush, alpha=0.04, beta=0.5)
    assert len(pts) == 1
    x, y, z = pts[0]
    assert abs(x - 0.02) < 1e-9      # 0.5 * 0.04
    assert abs(y - 0.02) < 1e-9

def test_process_new_stroke_has_lift_in_point():
    seq = [(1, 0.5, 0.5, 0.001), (0, 0.6, 0.5, 0.001)]
    pts = process(seq, func_brush, alpha=0.04, beta=0.5)
    # 新笔: 入锋点(悬空 z=0.05) + 落点, 再加延续点; 末尾 5 个抬笔点
    zs = [p[2] for p in pts]
    assert max(zs) >= 0.05           # 有悬空入锋
    assert len(pts) >= 3
```

- [ ] **Step 2: 跑失败**

Run: `conda run -n brushbot pytest tests/test_strokeseq.py`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现（端口 `load_data_try.py`，只保留楷书分支）**

`src/brushbot/calligraphy/strokeseq.py`:
```python
def process(seq, r2z, alpha=0.04, beta=0.5):
    """CalliRewrite (p_t,x,y,r) 笔序 -> 米制 (x,y,z) 路点. 楷书入锋; 见
    docs/callirewrite-arm-control.md. 端口自 load_data_try.py。"""
    xs, ys, zs = [], [], []
    n = len(seq)
    for i in range(n):
        p_t, x, y, r = seq[i]
        x_, y_ = x * alpha, y * alpha
        r_ = r * alpha * beta
        h = r2z(r_) * 100.0
        h = (h - 0.09) / 100.0          # CalliRewrite 经验微调
        if p_t == 0:
            xs.append(x_); ys.append(y_); zs.append(h)
        else:                            # p_t == 1: 新笔起笔 (楷书从左上入锋)
            if i == n - 1:
                continue
            xs.append(x_ - 2 * r_); ys.append(y_ - 2 * r_); zs.append(0.05)  # 悬空进入
            xs.append(x_); ys.append(y_); zs.append(h)                        # 落笔
    for _ in range(5):                   # 末尾抬笔离纸
        xs.append(xs[-1]); ys.append(ys[-1]); zs.append(zs[-1] + 0.015)
    return list(zip(xs, ys, zs))
```

- [ ] **Step 4: 跑通**

Run: `conda run -n brushbot pytest tests/test_strokeseq.py`
Expected: 2 passed。

- [ ] **Step 5: Commit**

```bash
git add src/brushbot/calligraphy/strokeseq.py tests/test_strokeseq.py
git commit -m "feat: port CalliRewrite process() stroke-seq to xyz waypoints"
```

---

### Task 7: 开环控制器（沿路点插值出目标位姿）

**Files:**
- Create: `src/brushbot/controller.py`
- Test: `tests/test_controller.py`

**Interfaces:**
- Consumes: `State`/`Command`（Task 1）、`config.FIXED_ORI`。
- Produces:
  - `OpenLoopController(waypoints, speed, fixed_ori)`：`waypoints=list[(x,y,z)]`，`speed` 米/秒。
    - `step(state) -> Command`：按 `d = speed*state.t` 沿路点折线弧长插值当前 `(x,y,z)`，拼 `fixed_ori` 成 6 元组。
    - `done() -> bool`：`speed*state.t >= 总弧长`（最后一次 `step` 之后置位）。
  - 内部 `_interp(d) -> (x,y,z)`：折线弧长插值，超出返回末点。

- [ ] **Step 1: 写失败测试**

`tests/test_controller.py`:
```python
from brushbot.types import State
from brushbot.controller import OpenLoopController

def _state(t):
    return State(tcp_pose=(0,0,0,0,0,0), g_meas=0.0, t=t)

def test_interp_midpoint():
    wp = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]   # 长度 1 的直线
    c = OpenLoopController(wp, speed=1.0, fixed_ori=(0.0, 0.0, 0.0))
    cmd = c.step(_state(0.5))                  # 走了 0.5 米
    assert abs(cmd.tcp_pose[0] - 0.5) < 1e-6
    assert len(cmd.tcp_pose) == 6

def test_done_after_full_length():
    wp = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
    c = OpenLoopController(wp, speed=1.0, fixed_ori=(0.0, 0.0, 0.0))
    c.step(_state(0.5)); assert not c.done()
    c.step(_state(1.0)); assert c.done()

def test_interp_clamps_past_end():
    wp = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
    c = OpenLoopController(wp, speed=1.0, fixed_ori=(0.0, 0.0, 0.0))
    cmd = c.step(_state(5.0))
    assert abs(cmd.tcp_pose[0] - 1.0) < 1e-6
```

- [ ] **Step 2: 跑失败**

Run: `conda run -n brushbot pytest tests/test_controller.py`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现**

`src/brushbot/controller.py`:
```python
import numpy as np
from brushbot.types import Command

class OpenLoopController:
    """开环: 沿 (x,y,z) 路点折线按弧长匀速插值出目标位姿。B1 用。"""
    def __init__(self, waypoints, speed, fixed_ori):
        self.wp = np.asarray(waypoints, dtype=float)   # (N,3)
        seg = np.linalg.norm(np.diff(self.wp, axis=0), axis=1)
        self.cum = np.concatenate([[0.0], np.cumsum(seg)])
        self.total = float(self.cum[-1])
        self.speed = speed
        self.ori = tuple(fixed_ori)
        self._done = False

    def _interp(self, d):
        if d <= 0:
            return tuple(self.wp[0])
        if d >= self.total:
            return tuple(self.wp[-1])
        i = int(np.searchsorted(self.cum, d) - 1)
        seg_len = self.cum[i + 1] - self.cum[i]
        t = 0.0 if seg_len == 0 else (d - self.cum[i]) / seg_len
        pos = self.wp[i] + t * (self.wp[i + 1] - self.wp[i])
        return tuple(pos)

    def step(self, state) -> Command:
        d = self.speed * state.t
        if d >= self.total:
            self._done = True
        x, y, z = self._interp(d)
        return Command(tcp_pose=(x, y, z, *self.ori))

    def done(self) -> bool:
        return self._done
```

- [ ] **Step 4: 跑通**

Run: `conda run -n brushbot pytest tests/test_controller.py`
Expected: 3 passed。

- [ ] **Step 5: Commit**

```bash
git add src/brushbot/controller.py tests/test_controller.py
git commit -m "feat: add OpenLoopController with arclength interpolation"
```

---

### Task 8: 墨迹渲染（笔尖轨迹 → PNG）

**Files:**
- Create: `src/brushbot/calligraphy/render.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `config.PAPER_Z`。
- Produces:
  - `render_trace(points, surface_z, out_path, px_per_m=4000, pad=0.01, down_margin=0.002) -> (W,H)`
    - `points=list[(x,y,z)]` 笔尖实际轨迹；`z <= surface_z + down_margin` 视为落笔。
    - 连续落笔点连线画黑，输出 PNG，返回图像宽高像素。
    - 无落笔点时抛 `ValueError`。

- [ ] **Step 1: 写失败测试**

`tests/test_render.py`:
```python
import os
from brushbot.calligraphy.render import render_trace

def test_render_square_creates_png(tmp_path):
    out = str(tmp_path / "sq.png")
    pts = [(0.0, 0.0, 0.0), (0.02, 0.0, 0.0), (0.02, 0.02, 0.0), (0.0, 0.02, 0.0)]
    w, h = render_trace(pts, surface_z=0.0, out_path=out)
    assert os.path.exists(out)
    assert w > 0 and h > 0

def test_render_raises_when_no_pen_down(tmp_path):
    out = str(tmp_path / "none.png")
    pts = [(0.0, 0.0, 0.05), (0.02, 0.0, 0.05)]   # 全悬空
    try:
        render_trace(pts, surface_z=0.0, out_path=out)
        assert False, "should raise"
    except ValueError:
        pass
```

- [ ] **Step 2: 跑失败**

Run: `conda run -n brushbot pytest tests/test_render.py`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现**

`src/brushbot/calligraphy/render.py`:
```python
from PIL import Image, ImageDraw

def render_trace(points, surface_z, out_path, px_per_m=4000, pad=0.01, down_margin=0.002):
    """笔尖轨迹 -> 墨迹 PNG。z<=surface_z+down_margin 视为落笔。"""
    down = [(x, y) for (x, y, z) in points if z <= surface_z + down_margin]
    if not down:
        raise ValueError("no pen-down points to render")
    xs = [p[0] for p in down]; ys = [p[1] for p in down]
    minx, maxx = min(xs) - pad, max(xs) + pad
    miny, maxy = min(ys) - pad, max(ys) + pad
    W = max(1, int((maxx - minx) * px_per_m))
    H = max(1, int((maxy - miny) * px_per_m))
    img = Image.new("L", (W, H), 255)
    dr = ImageDraw.Draw(img)

    def to_px(x, y):
        px = int((x - minx) * px_per_m)
        py = int((maxy - y) * px_per_m)   # y 轴翻转
        return px, py

    prev = None
    for (x, y, z) in points:
        if z <= surface_z + down_margin:
            cur = to_px(x, y)
            if prev is not None:
                dr.line([prev, cur], fill=0, width=3)
            prev = cur
        else:
            prev = None                    # 抬笔断开
    img.save(out_path)
    return (W, H)
```

- [ ] **Step 4: 跑通**

Run: `conda run -n brushbot pytest tests/test_render.py`
Expected: 2 passed。

- [ ] **Step 5: Commit**

```bash
git add src/brushbot/calligraphy/render.py tests/test_render.py
git commit -m "feat: add ink-trace renderer (pen-down xy -> png)"
```

---

### Task 9: 端到端 B1 —— 仿真里开环写一个字

**Files:**
- Create: `src/brushbot/examples/__init__.py`
- Create: `src/brushbot/examples/strokes.py`
- Create: `src/brushbot/write_openloop.py`
- Test: `tests/test_write_openloop.py`

**Interfaces:**
- Consumes: 全部前序（`process`、`OpenLoopController`、`Scene`、`SimBackend`、`ZeroTactile`、`render_trace`、`run`、`config`）。
- Produces:
  - `examples/strokes.py`：`SHI_SEQ`（"十"字两笔，`list[(p_t,x,y,r)]`）。
  - `write_openloop.py`：`write(seq, gui=False, speed=0.05, out_png="/tmp/brushbot_out.png") -> dict`
    - 跑完整开环写字管线，返回 `{"trace": list[(x,y,z)], "png": out_png, "n_down": int}`。
    - 把控制点整体平移到 `config.CHAR_ORIGIN`（保证在臂可达域）。

- [ ] **Step 1: 写集成测试**

`tests/test_write_openloop.py`:
```python
import os
from brushbot.write_openloop import write
from brushbot.examples.strokes import SHI_SEQ

def test_write_shi_produces_trace_and_png(tmp_path):
    out = str(tmp_path / "shi.png")
    res = write(SHI_SEQ, gui=False, speed=0.05, out_png=out)
    assert res["n_down"] > 20            # 有足够落笔点
    assert os.path.exists(res["png"])
    # 落笔轨迹覆盖两笔 -> x,y 都有明显跨度 (十字)
    from brushbot import config
    down = [(x, y) for (x, y, z) in res["trace"] if z <= config.PAPER_Z + 0.002]
    xspan = max(p[0] for p in down) - min(p[0] for p in down)
    yspan = max(p[1] for p in down) - min(p[1] for p in down)
    assert xspan > 0.01 and yspan > 0.01
```

- [ ] **Step 2: 跑失败**

Run: `conda run -n brushbot pytest tests/test_write_openloop.py`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现**

`src/brushbot/examples/__init__.py`: （空文件）

`src/brushbot/examples/strokes.py`:
```python
# "十" 两笔, 归一化坐标 [0,1]; (p_t, x, y, r), p_t=1 起笔
# 第一笔: 横 (左->右, y=0.5); 第二笔: 竖 (上->下, x=0.5)
SHI_SEQ = [
    (1, 0.15, 0.50, 0.0015), (0, 0.40, 0.50, 0.0018), (0, 0.65, 0.50, 0.0018), (0, 0.85, 0.50, 0.0015),
    (1, 0.50, 0.15, 0.0015), (0, 0.50, 0.40, 0.0018), (0, 0.50, 0.65, 0.0018), (0, 0.50, 0.85, 0.0015),
]
```

`src/brushbot/write_openloop.py`:
```python
from brushbot import config
from brushbot.scene import Scene
from brushbot.backends.sim import SimBackend, ZeroTactile
from brushbot.controller import OpenLoopController
from brushbot.calligraphy.strokeseq import process
from brushbot.calligraphy.calibration import func_brush
from brushbot.calligraphy.render import render_trace
from brushbot.run import run

def write(seq, gui=False, speed=0.05, out_png="/tmp/brushbot_out.png"):
    # 1. 笔序 -> 米制 (x,y,z) 路点
    pts = process(seq, func_brush, alpha=0.04, beta=0.5)
    # 2. 平移到书写平面可达中心; z 从 CalliRewrite 帧映射到仿真帧:
    #    z_sim = PAPER_Z + (zc - Z_TOUCH_REF)  (触纸->平面, 压->平面下, 抬->平面上)
    ox, oy = config.CHAR_ORIGIN
    wp = [(x + ox, y + oy, config.PAPER_Z + (z - config.Z_TOUCH_REF))
          for (x, y, z) in pts]
    # 3. 搭场景 + 后端
    sc = Scene(gui=gui); sc.load()
    backend = SimBackend(sc, ZeroTactile(), substeps=4)
    ctrl = OpenLoopController(wp, speed=speed, fixed_ori=config.FIXED_ORI)
    # 4. 跑开环, 记录笔尖轨迹
    trace = []
    run(backend, ctrl, on_tick=lambda s: trace.append(s.tcp_pose[:3]))
    sc.close()
    # 5. 渲染墨迹 (纸面 = PAPER_Z)
    render_trace(trace, surface_z=config.PAPER_Z, out_path=out_png)
    n_down = sum(1 for (x, y, z) in trace if z <= config.PAPER_Z + 0.002)
    return {"trace": trace, "png": out_png, "n_down": n_down}
```

- [ ] **Step 4: 跑通**

Run: `conda run -n brushbot pytest tests/test_write_openloop.py`
Expected: 1 passed。
> 若落笔点不足/跨度不够：调 `speed`（更慢=更多采样）或 `SimBackend.substeps`，并确认 `CHAR_ORIGIN` 在臂可达域内（KUKA 可达 ~0.8m）。

- [ ] **Step 5: 人眼验收（可选，看写出来啥样）**

Run: `conda run -n brushbot python -c "from brushbot.write_openloop import write; from brushbot.examples.strokes import SHI_SEQ; print(write(SHI_SEQ, gui=False, out_png='shi.png')['png'])"`
Expected: 生成 `shi.png`，肉眼是一个"十"字。

- [ ] **Step 6: Commit**

```bash
git add src/brushbot/examples/ src/brushbot/write_openloop.py tests/test_write_openloop.py
git commit -m "feat: end-to-end open-loop writing of a character in sim"
```

---

### Task 10: 全量测试 + 简短 README

**Files:**
- Create: `src/brushbot/README.md`
- Test: 全部现有测试

**Interfaces:**
- Produces: `src/brushbot/README.md`（如何建环境、跑测试、写字），无新代码接口。

- [ ] **Step 1: 跑全量测试**

Run: `conda run -n brushbot pytest`
Expected: 全部 passed（types/run/scene/sim_backend/calibration/strokeseq/controller/render/write_openloop + smoke）。

- [ ] **Step 2: 写 README**

`src/brushbot/README.md`:
```markdown
# brushbot — 机械臂书法执行端（仿真）

三层架构（算法↔I/O 解耦），见 `docs/control-architecture.md`。当前为 B0+B1：PyBullet 仿真里开环写字（复现 CalliRewrite）。

## 环境
    conda create -y -n brushbot python=3.10
    conda run -n brushbot pip install -e .

## 测试
    conda run -n brushbot pytest

## 开环写字 demo
    conda run -n brushbot python -c "from brushbot.write_openloop import write; from brushbot.examples.strokes import SHI_SEQ; write(SHI_SEQ, gui=True)"

## 换 Elfin5 URDF
改 `brushbot/config.py` 的 `ARM_URDF` / `EEF_LINK` / `FIXED_ORI`，其余不动。

## 下一步 (B2)
加 `AdmittanceController` + 合成 `g_meas`，`SimBackend` 的 `ZeroTactile` 换成合成提按源；实机写 `HuayanBackend`（见 `docs/control-architecture.md`）。
```

- [ ] **Step 3: Commit**

```bash
git add src/brushbot/README.md
git commit -m "docs: add brushbot README for B0+B1"
```

---

## 完成标准（Definition of Done）

- `conda run -n brushbot pytest` 全绿。
- `write(SHI_SEQ, gui=True)` 在 PyBullet 里能看到机械臂沿"十"字轨迹运动，生成的 PNG 肉眼是"十"字。
- 三层架构成型：换 Elfin URDF 只改 `config.py`；上 B2 只加算法层控制器 + 换触觉源，① 后端读写与 ③ 运行循环不动。

## 不在本计划范围（留给后续）

- **B2**：`AdmittanceController`（前馈 `z_ff` + 低增益反馈）、合成/真实 `g_meas`、恒定形变→时变提按。
- **实机**：`HuayanBackend`（`HRIF_PushServoP`）、纸面三点标定、安全限幅、E1 门禁。
- **真实 CalliRewrite 字**：跑其 ML 出 `(p_t,x,y,r)` 序列（本计划用手写 `SHI_SEQ` 顶替）。
- **真 Elfin URDF**：获取后按 Task 3 备注替换。
```
