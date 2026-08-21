# Elfin5 臂 MuJoCo 交接仓库 — 设计文档

- 日期：2026-08-21
- 状态：已批准（brainstorming 拍板）
- 目的：给 Mac 上的协作者一个**独立 git 交接仓库**——同一个机械臂（Elfin5）跑 MuJoCo 仿真，
  但控制算法由对方实现。骨架只提供机械臂仿真壳 + 可插拔控制接口，不带写字/触角/纸。

---

## 1. 背景

- 当前 `src/brushbot/tactile/mj_write.py` 在 MuJoCo 里驱动 Elfin5 写字，但深度绑定
  `brushbot` 包（`config`/`OpenLoopController`/`calligraphy.hanzi`/触角/纸），依赖
  `pybullet`、`matplotlib`、图形数据等一堆和"只想要机械臂仿真"无关的东西。
- 别人只在 Mac 上想用**同一个机械臂**、跑**自己的控制算法**，不需要写字能力。
- 因此交接物应剥离为：**纯 Elfin5 机械臂 + MuJoCo + 可插拔控制接口**。

## 2. 已确认的需求决策

| 维度 | 决策 |
|---|---|
| 范围 | 最小骨架：纯机械臂仿真（不带写字/触角/纸） |
| 控制接口 | 关节级 + 笛卡尔级**双接口** |
| 环境 | pip 依赖（`numpy` + `mujoco`），README 给安装步骤 |
| 验证 | demo（正弦激励 + 预定义笛卡尔轨迹）+ 自检脚本 |
| 仓库形态 | **独立新建 git 仓库**（交接物自成一体，不污染 FYP 主线） |

## 3. 仓库结构

```
<handoff-repo>/              # 独立 git 仓库（名称待定，见 §7）
├── pyproject.toml           # name=elfin5-sim；deps: numpy, mujoco
├── README.md                # 中文：五分钟跑起来 + 双接口示例 + 命令
├── NOTICE.md                # 机械臂 URDF 来源（BSD，大族 elfin_robot）——必带，许可合规
├── src/
│   └── elfin/
│       ├── __init__.py
│       ├── robot.py         # 仿真壳：加载 URDF → MjModel；双接口 step_joint/step_cartesian
│       └── ik.py            # 雅可比 DLS IK（移植自 mj_write.ik，去掉触角/纸专有逻辑）
├── assets/
│   └── elfin5/
│       ├── elfin5.urdf      # 原样拷入（相对 meshes/ 路径，跨平台）
│       └── meshes/*.STL     # 7 个，原样拷入
├── examples/
│   ├── demo_joint.py        # 关节级：正弦激励，看六轴摆动
│   └── demo_cartesian.py    # 笛卡尔级：预定义端点点位，内置 IK 驱动到位
└── selfcheck.py             # 自检：模型编译 / IK 收敛 / 接口契约（无显示器可跑）
```

核心只两个文件干实事：`robot.py`（仿真壳 + 双接口）、`ik.py`（IK）。其余是资产和示例。

## 4. 双接口设计（`robot.py`）

别人写控制算法时面对的对象。两种接口都跑同一 `mj_step` 动力学环，关节级是骨架默认，
笛卡尔级是便捷封装。

| 接口 | 别人提供 | 骨架内部做 |
|---|---|---|
| **关节级** `step_joint(q_target)` | 每拍 6×1 关节角（rad）目标 | 更新 `d.ctrl`/`d.qpos` 目标 → 关节 PD（kp/kv 可配置）→ `mj_step` → 返回反馈 |
| **笛卡尔级** `step_cartesian(pose_target)` | 每拍 (x,y,z) [+ 姿态 quat] | 内置 IK 解出 6 关节角 → 走关节 PD → 返回末端实际位姿 + 关节角 |

**每拍反馈**（返回一个 dict，供别人闭环/记录）：
`q_meas`（关节角）、`dq`（关节速度）、`eef_pos`（末端位置）、`eef_quat`（姿态）、`t`（仿真时间）。

**模型参数**：`kp=2000`、`kv=200`（关节 PD，对齐当前 mj_write 写法）；`timestep` 默认取 URDF 的，
可覆盖；支持设定初始 `qpos`。

## 5. IK（`ik.py`）

移植自 `mj_write.ik` 的雅可比 DLS IK（只动 6 个臂关节、从上一解暖启动保持解连续、限位钳制），
去掉触角/纸专有逻辑。返回收敛残差 + 关节角。`robot.py` 的笛卡尔接口内部调用它。

## 6. 验证与交付

**`selfcheck.py`**（无显示器、几秒）：
1. URDF 能编译成 MjModel（路径跨平台、mesh 齐全）
2. IK 在 3 个目标点收敛（残差 < 5mm）
3. 关节接口跑若干拍：关节角在限位内、无 NaN、末端位置合理
4. 笛卡尔接口跑到定点、末端实际位姿到位

**demo**：
- `demo_joint.py`：正弦激励六轴摆动（开窗口看版本）
- `demo_cartesian.py`：走预定义点位（开窗口 / 无窗口出图两版）

**染色测试**：本地（Linux）跑通 `selfcheck.py` + 两个 demo 的 no-window 模式，确认绿了再交付。
无法真在 Mac 上跑，但代码纯 `numpy+mujoco`，macOS arm64 有官方 wheel，跨平台可靠。

## 7. 待定/后续

- **仓库命名与位置**：交接仓库名称与放哪（建议 `~/<name>`，名称如 `elfin5-mujoco-ctrl`），
  是否要推到远端（GitHub）与协作者共享——由用户决定。
- **姿态接口细节**：笛卡尔接口是否要暴露完整 6-DOF 姿态（旋转），或先只做位置 + 固定工具姿态，
  取决于对方算法——默认提供位置 + 可选 quat。
