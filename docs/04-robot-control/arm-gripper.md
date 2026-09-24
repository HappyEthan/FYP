---
project: 04-robot-control
status: active
---

# 机械臂与夹爪操作

本文说明仓库中可用的机械臂与夹爪入口。具体坐标、TCP/UCS、毛笔装配和工作空间以本次现场配置核对；脚本内的示例数值不能跨装配沿用。机械臂命令位姿与实际读回位姿是不同数据。

## 连接和坐标

- 机械臂是华沿 Elfin 系列；原生接口封装在 [`CPSClient`](../../src/brushbot/backends/vendor/CPS.py) 与 [`HuayanBackend`](../../src/brushbot/backends/huayan.py)。较新的实验和回位脚本使用仓库外的 `elfin-dhag-adapter` / `HuayanRobot`，运行前须确认该适配器及其 Python 环境可用。
- 原生 HRIF 位姿使用 mm 和度；仓库内部控制器通常使用 m 和弧度。使用某个脚本前先看它的输入单位。具名 TCP/UCS 以及控制柜内的实际定义要与配置快照一致。
- 进入运动前核对当前 FSM、TCP/UCS、纸面与工具坐标、当前位置、目标和整段路径净空。软件工作空间检查并不等于碰撞检测。异常时使用现场示教器/急停，并检查脚本记录的停止状态。

## 机械臂常用入口

| 操作 | 入口与行为 |
|---|---|
| 查看运动 API 和 20 ms 伺服使用方式 | [`examples/write_air.py`](../../examples/write_air.py) 使用 `MoveL` 到起点，再通过 `HuayanBackend` 流式下发 `PushServoP`；详见[开环写字](openloop.md)。 |
| 返回代码预设等待位姿 | [`scripts/return_to_origin.py`](../../scripts/return_to_origin.py) 读取当前位置、核对预设工作空间、打印当前与目标位姿，人工按 Enter 后执行一次直线 `MoveL`。默认目标和连接参数定义在脚本顶部；移动前须核对整条直线路径。 |
| 运行带记录的笔画实验 | [`scripts/run_strokeplan_experiment.py`](../../scripts/run_strokeplan_experiment.py) 在离线编译后，按批准状态与人工 `RUN` 进入单笔执行；详见[StrokePlan 执行](strokeplan-execution.md)。 |

`return_to_origin.py` 的“原点”是代码配置的笛卡尔等待位姿，不是机械臂关节零位，也不应被解释为任意现场都安全的回零动作。

## 夹爪操作

DH AG-160-95 夹爪由华沿控制柜的 HYGripper 插件控制，电脑不直接连接 RS485。开口宽度单位 mm，`0` 为全闭、`95` 为全开。先用[`gripper_probe.py`](../../examples/gripper_probe.py) 只读连接/状态，再用[`clamp_brush.py`](../../scripts/clamp_brush.py) 夹到指定开口；这两个动作的用途不同：

```bash
python examples/gripper_probe.py --once
python scripts/clamp_brush.py --width-mm 14
```

`clamp_brush.py` 默认 IP 为 `192.168.0.10`、夹爪 ID 为 1，默认目标开口 14 mm；它读连接状态、等待人工 Enter、移动夹爪并等到位，**不移动机械臂，也不自动松爪**。14 mm 只是当前脚本默认值，换笔时应核对实际夹持宽度和力度。若需完整开合验收，可运行[`examples/gripper_test.py`](../../examples/gripper_test.py)：它会依次全闭、全开、到 10 mm，须先清空指间区域并输入 `yes`。

底层[`Gripper`](../../src/brushbot/gripper.py) 提供 `open()`、`close()`、`move_to_width(mm)`、`move_rel(delta_mm)`、`read()`、`stop()`、`clear_fault()` 和 `wait_done()`。移动命令非阻塞；要确认到位须读取状态或 `wait_done()`。速度范围为整数 1–100，力为整数 20–100，宽度 0–95 mm。出现 `60002` 时先核对供电、RS485 线序与示教器 HYGripper 插件连接参数。

写字与 StrokePlan 实验假设笔和夹爪在一次运行中保持固定装配；正常完成、停止与回位脚本不会自动松爪。夹持可靠性及断电行为须由现场条件核对。
