# 机械臂控制架构 · 算法与 I/O 解耦（Python 仿真 → 华沿 SDK 实机）

> 目的：定下**执行端算法代码的组织方式**，使"先在仿真开发、后接实机"变成**换后端**、而不是重写。
> 核心一句话：**把"控制算法"和"跟谁通信(I/O)"彻底分开——算法是纯 Python，不知道自己在跟 PyBullet 还是真机 Elfin 说话。**
> 关联：`note.md` 的两个接口契约（`StrokePlan` + 实时 `g_meas` 流）；`plan.md` 的 B0/B1/B2；`reference/执行方案-力控.md`。
> 生成 2026-07-13。

---

## 0. 为什么这么设计

- 现在没有机械臂 → 先在**仿真**里开发算法（B1 写字、B2 导纳）。
- Elfin 实机用**华沿 Python SDK**（`HRIF_PushServoP` 流式伺服，无需 ROS/EtherCAT）；仿真用 **PyBullet**（纯 Python）。
- 触觉物理无法仿真 → 仿真只验证**运动学 + 控制环逻辑 + 轨迹**，触觉信号在仿真里用**合成值**顶替。
- 因此：**控制算法（导纳律、前馈、轨迹）是项目的核心贡献，必须与运行环境无关、可 1:1 迁移。** 环境差异全部隔离在"后端适配层"。

---

## 1. 三层结构

```
┌─────────────────────────────────────────────────────┐
│  ① 纯算法层 (plain Python, 无 ROS 无 PyBullet)          │  ← 核心贡献, 环境无关, 永不改
│     AdmittanceController / TrajectoryPlanner           │
│     step(state) -> command                             │
└───────────────▲───────────────────────┬───────────────┘
         state  │                        │ command
┌───────────────┴────────────────────────▼──────────────┐
│  ② 后端适配层 (RobotBackend, 可插拔)                     │  ← 换环境只换这层
│     SimBackend(PyBullet)   |   HuayanBackend(CPS SDK)   │
│     read()->state          |   read()->state           │
│     write(command)         |   write(command)          │
└───────────────▲───────────────────────┬───────────────┘
┌───────────────┴────────────────────────▼──────────────┐
│  ③ 运行循环 (Runner, 两边通用)                          │
│     while: s=backend.read(); c=ctrl.step(s); backend.write(c) │
└────────────────────────────────────────────────────────┘
```

**仿真开发**：backend = `SimBackend`。**实机**：backend = `HuayanBackend`。**① 和 ③ 一行不改，只换 ②。**

---

## 2. 各层职责

| 层 | 职责 | 依赖 | 是否随环境变 |
|---|---|---|---|
| ① 纯算法 | 消费 `StrokePlan` + `g_meas`，产出**笛卡尔位姿设定值**；导纳律/前馈/轨迹/`s→t` | 只 numpy | ❌ 永不变 |
| ② 后端 | 读机器人状态、下发设定值；对接 PyBullet 或 华沿 SDK | pybullet / CPS(HRIF) | ✅ 换环境换这层 |
| ③ 运行循环 | 定频跑 read→step→write（100–200Hz） | 无 | ❌ 通用 |

---

## 3. 实机后端 = 华沿 Python SDK（无需 ROS）

**华沿官方提供 Elfin 的 Python SDK（`CPS` / `HRIF_*`）**（`reference/HuayanRobot_Library_Python_V1.0.11.0.pdf`），Linux `.so`、TCP 连控制器（端口 10003），把 ROS/EtherCAT 全封装在控制器里。所以**实机后端就是薄薄一层 SDK 调用，不用 ROS/Docker/EtherCAT**。

实机后端要用的关键接口：

| 用途 | 接口 |
|---|---|
| 连接 | `HRIF_Connect(0, IP, 10003)` |
| 启动在线伺服 | `HRIF_StartServo(0,0, dServoTime, dLookaheadTime)`（示例周期 0.02s=50Hz） |
| **流式下发笛卡尔位姿** | **`HRIF_PushServoP(0,0, dPcs, dTcp, dUcs)`**（dPcs=[X,Y,Z,Rx,Ry,Rz]，**控制器自动逆解，连 IK 都不用自己写**） |
| 读当前 TCP 位姿 | `HRIF_ReadActTcpPos` |
| （备选/安全网）内置力控 | `HRIF_SetForceControlState` + `HRIF_SetMassParams/SetDampParams/SetStiffParams`（用腕部 F/T） |
| （需要时）IK/FK | `HRIF_GetInverseKin` / `HRIF_GetForwardKin` |

> 注意：SDK `.so` 见到 py3.6/3.7 版本；`HRIF_SetSimulation` 仿真模式需**连着控制器**（断电模式）→ 拿到臂/控制器后才能用，预硬件阶段用 PyBullet。Servo 频率上限（能否 >50Hz）需实机测。

---

## 4. 代码骨架

> 骨架/伪代码，API 以 pybullet / 华沿 SDK 手册为准。

**① 纯算法层 `controller.py`（无环境依赖、可单测）**
```python
from dataclasses import dataclass

@dataclass
class State:
    pose: tuple          # 当前 TCP 位姿 (x,y,z, ...)
    g_meas: float        # 触觉提按分量(合成 or 真流)
    arclength: float     # 当前弧长 s∈[0,1]
    dt: float

@dataclass
class Command:
    pose: tuple          # 目标 TCP 位姿设定值

class AdmittanceController:
    def __init__(self, stroke_plan, calib, Kv, z_surface, ORI):
        self.plan, self.calib, self.Kv = stroke_plan, calib, Kv
        self.z_surface, self.ORI, self.z_fb = z_surface, ORI, 0.0

    def step(self, st: State) -> Command:
        s   = st.arclength
        g_d = self.plan.press_curve(s)                 # StrokePlan: 目标提按曲线
        x, y = self.plan.path_xy(s)                    # StrokePlan: 平面路径
        z_ff = self.calib(g_d)                         # 前馈: 标定曲线, 扛快速提按
        self.z_fb += self.Kv * (g_d - st.g_meas) * st.dt   # 低增益反馈, 只纠残差
        # z_fb 限幅省略
        z = self.z_surface + z_ff + self.z_fb
        return Command(pose=(x, y, z, *self.ORI))
```

**② 后端接口 + 两实现 `backends.py`**
```python
from typing import Protocol

class RobotBackend(Protocol):
    def read(self) -> State: ...
    def write(self, cmd: Command) -> None: ...

class SimBackend:                      # 现在用: PyBullet
    def __init__(self, urdf_path, tactile_source):
        import pybullet as p
        self.p = p; self.robot = p.loadURDF(urdf_path, useFixedBase=True)
        self.tactile = tactile_source  # 合成 g_meas, 或从仿真接触力算
    def read(self) -> State:
        pose = self._fk()                          # 从关节读 TCP 位姿
        return State(pose, self.tactile.value(), self._s(), dt=1/150)
    def write(self, cmd: Command):
        q = self.p.calculateInverseKinematics(self.robot, EEF_LINK, cmd.pose[:3])
        self.p.setJointMotorControlArray(self.robot, JOINTS, self.p.POSITION_CONTROL, q)
        self.p.stepSimulation()

class HuayanBackend:                   # 实机用: 华沿 Python SDK (CPS/HRIF)
    def __init__(self, ip, tactile_stream):
        from CPS import CPSClient
        self.cps = CPSClient(); self.cps.HRIF_Connect(0, ip, 10003)
        self.cps.HRIF_StartServo(0, 0, 0.02, 0.2)  # 周期 50Hz, 前瞻 0.2s
        self.tactile = tactile_stream              # 队友契约1: 真实 g_meas 流
    def read(self) -> State:
        r = []; self.cps.HRIF_ReadActTcpPos(0, 0, r)   # 读当前 TCP 位姿
        return State(tuple(map(float, r)), self.tactile.latest(), self._s(), dt=1/50)
    def write(self, cmd: Command):
        dPcs = list(cmd.pose)                        # [X,Y,Z,Rx,Ry,Rz] mm/deg
        self.cps.HRIF_PushServoP(0, 0, dPcs, [0]*6, [0]*6)  # 控制器自动逆解
```

**③ 运行循环 `run.py`（两边同一份）**
```python
backend = SimBackend(urdf, synthetic_press)   # 实机时: HuayanBackend(ip, real_tactile)
ctrl    = AdmittanceController(stroke_plan, calib, Kv, z_surface, ORI)
while running:
    st  = backend.read()
    cmd = ctrl.step(st)
    backend.write(cmd)
    sleep_until_next_tick(150)                 # 100–200 Hz
```

---

## 5. 关键约定

- **设定值类型 = 笛卡尔位姿**（x,y,z + 姿态）。下发方式：
  - Sim：`p.calculateInverseKinematics` 逆解后驱动关节。
  - 实机：**`HRIF_PushServoP` 直接推笛卡尔位姿，控制器自动逆解**（无需自己写 IK），这是流式在线伺服、适合逐拍闭环。
- **`g_meas` 不属于机器人后端**：它是**队友触觉流（契约1）**的独立输入。
  - Sim：合成提按曲线，或用仿真里"笔尖 vs 刚性平面"的接触力。
  - 实机：队友的实时有线流。
  - 所以 `State` 有**两个来源**：机器人位姿 + g_meas。
- **`StrokePlan`（契约2）** 直接喂算法层（`plan.path_xy(s)` / `plan.press_curve(s)`）。
- **频率**：外环 100–200Hz；`s→t` 用弧长参数化 + 速度剖面（v1 定速）。

---

## 6. sim → 实机 迁移清单

| 要不要改 | 项 |
|---|---|
| ❌ 不改 | ① 纯算法层（导纳/前馈/轨迹）、③ 运行循环、`StrokePlan` 消费 |
| ✅ 换实现 | ② 后端：`SimBackend` → `HuayanBackend`（华沿 SDK，`PushServoP`） |
| ✅ 换来源 | `g_meas`：合成 → 队友真实触觉流 |
| ➕ 新增 | 实机安全（限幅、保护停止）、纸面 `z_surface` 标定、机器人姿态下 re-baseline |

> 结论：控制算法从头到尾是**同一份 Python**；实机化 = 写一个 `HuayanBackend`（几十行 SDK 调用）+ 切 g_meas 来源。

---

## 7. 映射到计划（`plan.md`）

- **B0**：搭 Python 环境（先 PyBullet，不装 ROS）；拿 Elfin URDF（PyBullet 直接 `loadURDF`）。
- **B1**：`SimBackend` + 开环写字（复现 CalliRewrite）——`ctrl` 退化为"只走 xy + 固定/给定 z"。
- **B2**：加 `AdmittanceController` + 合成 `g_meas`，在仿真里验证外环结构与稳定性。
- **实机阶段**：写 `HuayanBackend`（华沿 SDK）；真实 `g_meas`、E1 门禁、安全限幅（细节见 `reference/执行方案-力控.md`、`reference/HuayanRobot_Library_Python_V1.0.11.0.pdf`）。

---

## 8. 待定 / 依赖

- **实机接口已定 = 华沿 Python SDK**（`HRIF_PushServoP` 流式笛卡尔伺服，无需 ROS/Docker/EtherCAT）。待实机确认：**Servo 频率上限**（示例 50Hz，能否更高）、**SDK `.so` 的 Python 版本**（见到 py3.6/3.7，实机后端可能需单独环境）、`HRIF_SetSimulation` 需连控制器。
- **仿真器**：先 **PyBullet**（最省事、内置 IK、直接读 URDF）；要更真实接触动力学再考虑 **MuJoCo**。
- **Elfin URDF**：从官方 `elfin_robot` 包 / 大族 3D 模型下载获取。
