---
project: 06-mujoco-simulation-platform
status: active
---

# 06 · MuJoCo Simulation Platform

保留 MuJoCo 机械臂和触角仿真。前期模型已建立；统一接口、桥接和磁响应数值可信度仍有开放问题。

完整阶段关系见[根计划](../../plan.md)。先读下面的主题文件；历史材料集中在 `archive/`，按记录日期解释。

## 项目目的

提供可重复的机械臂与触觉仿真环境，使 Robot Control 能通过稳定接口回放轨迹、记录状态并验证控制链，同时明确模型可以证明什么、不能证明什么。

## 范围

- MuJoCo 场景、纸面、机械臂、工具和触角模型。
- 关节级和笛卡尔级控制接口。
- 面向 Robot Control 的状态读取和轨迹回放接口。
- 与 Monitor + Filter 的数据桥接。
- 可复现实例、仿真验收和模型可信度边界。

本项目不负责选择或设计控制律，也不把仿真 ΔB 绝对数值当作真机结论。

## 输入、输出与依赖

- 输入：控制指令、模型参数、场景配置和 StrokePlan 派生轨迹。
- 输出：仿真关节/末端状态、接触状态、合成触觉信号和验证日志。
- 依赖：Robot Control 定义控制接口；Monitor + Filter 定义观测接口。

## 已知限制与后续讨论

- 当前触角磁学模型的绝对单位和真机标定未统一。
- MuJoCo 接触结果可用于结构与趋势验证，不能直接替代真机误差和带宽测试。
- UDP monitor 桥目前只有设计记录，尚未形成稳定平台能力。

## 主题文件

| 文档 | 内容 |
|---|---|
| [simulation.md](simulation.md) | 机械臂写字与独立触角仿真的详细使用说明。 |

## 历史资料

| 文档 | 内容 |
|---|---|
| [fem-design.md](archive/fem-design.md) | 未采用的 SOFA FEM 路线和回退策略。 |
| [platform-design.md](archive/platform-design.md) | 独立仿真平台的双接口、IK 和实施记录。 |
| [udp-bridge.md](archive/udp-bridge.md) | 仿真到 Monitor 的旧 UDP 接口设想。 |

## 维护方式

本部分采用一个总 README 与按主题命名的 Markdown 文件；同主题继续修订原文件。只有确需追溯的旧设计或结果才进入 `archive/`，不再为单篇文档建立多层目录。
