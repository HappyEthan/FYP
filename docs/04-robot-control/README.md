---
project: 04-robot-control
status: active
---

# 04 · Robot Control

本部分按机械臂与夹爪、开环写字、StrokePlan 执行三个主题组织。现行 StrokePlan 已有前馈与受限 P 反馈的单笔录制入口；命令 Z 不等于实测 TCP Z，实验运行结束也不等于跟踪达标。

完整阶段关系见[根计划](../../plan.md)。先读下面的主题文件；历史材料集中在 `archive/`，按记录日期解释。

## 项目目的

让机械臂安全、可复现地执行 StrokePlan，并用清晰基线衡量后续触觉反馈带来的收益。

## 范围

- 机械臂和夹爪硬件接口、坐标系与安全约束。
- 当前开环/前馈轨迹生成和执行。
- 前馈加反馈的触觉 Z 控制候选及其控制指标。
- 对指令、观测状态、时序和异常停止进行记录。

MuJoCo 场景、模型和仿真平台归 [06 MuJoCo Simulation Platform](../06-mujoco-simulation-platform/README.md)；本项目只拥有控制律和控制器接口。

## 输入、输出与依赖

- 输入：StrokePlan、标定参数和机械臂当前状态。
- 输出：控制指令、执行状态、时序日志和安全结果。
- 依赖：StrokePlan 契约、Data Acquisition 的测试数据；MuJoCo 可作为并行后端。

## 已知限制与后续讨论

- 真机当前没有被证明可直接使用仿真中的反馈增益。
- 纸面坐标、机械臂基坐标和工具坐标之间的符号与单位必须在首次回放前固定。
- 前馈基线未量化前，不应把闭环候选的收益当作真机结论。

## 主题文件

| 文档 | 内容 |
|---|---|
| [arm-gripper.md](arm-gripper.md) | 机械臂连接、坐标、回位和夹爪操作。 |
| [openloop.md](openloop.md) | 中线数据到开环伺服写字的流程与参数。 |
| [strokeplan-execution.md](strokeplan-execution.md) | 现行 StrokePlan 的预检、前馈/P 单笔执行及运行记录。 |

## 早期设计与仿真

| 文档 | 内容 |
|---|---|
| [experiment-platform.md](archive/experiment-platform.md) | 首轮实验平台的设计、配置和操作历史。 |
| [ladder-2026-09-17.md](archive/ladder-2026-09-17.md) | 旧双向梯子设计；不代替后续实测。 |
| [z-control-design.md](archive/z-control-design.md) | Z 控制的前馈表＋PI 方案、原因及当前 P 实验边界。 |
| [wetting.md](archive/wetting.md) | 梯子实验自动沾水设计与当时实施记录。 |

## 已完成批次的实验记录

| 文档 | 证据范围 |
|---|---|
| [ladder-2026-09-23.md](archive/ladder-2026-09-23.md) | brush2 四姿态、八次完整 run 的梯子实验。 |

StrokePlan 执行实验仍在进行，完成后再将其临时材料整理为按日期的实验记录。

## 维护方式

本部分采用一个总 README 与按主题命名的 Markdown 文件；同主题继续修订原文件。只有确需追溯的旧设计或结果才进入 `archive/`，不再为单篇文档建立多层目录。
