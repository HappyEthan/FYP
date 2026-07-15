# 项目备忘录 · 触觉毛笔书法机器人

> 定位：项目的**决策日志 + 上下文备忘**。和队友/导师同步、或隔一段时间回来续做时，先看这个文件。
> 计划与任务清单见 `plan.md`；技术方案原文见 `reference/`。
> 最近更新：2026-07-13

---

## 1. 一句话项目

一支嵌入仿生触角（E-Antenna + MLX90393 霍尔）的毛笔 + **Elfin5 协作臂**，用**触觉形变闭环**在真纸上复现人类书写的"**提按**"力度曲线。

**核心答辩卖点 / 对比实验** = **闭环触觉力控提按 vs 开环位置控宽度**。
（CalliRewrite 等前作纯开环、无力觉，只靠抬压笔高凑视觉宽度；用触觉力控真实复现提按是本项目的超越点。）

**目标形态**：先"复现"（Motion Copy），后"泛化"（Transformer 写新字，升级项）。

---

## 2. 分工（两人项目）

| 人 | 负责 |
|---|---|
| **队友** | 硬件（毛笔本体集成、双模固件）+ 数采（信号处理、示范采集） |
| **Ethan（本人）** | **机械臂算法 / 执行闭环**；后期做模型泛化 |

> 当前 Ethan 只专注"算法/执行闭环"。硬件+数采以两个**接口契约**（见 §4）对齐。

---

## 3. 资源现状

| 项 | 状态 |
|---|---|
| 仿生触角（已磁化） | ✅ 已有 |
| MLX90393 霍尔 + ESP32 | ✅ 已到、已通（能读 Bx,By,Bz 并串到 PC） |
| 毛笔本体（触角嵌毛+装杆+法兰夹持） | ⏳ 待集成 |
| 双模固件（BLE 无线 + USB 有线，≥100Hz，时间戳） | ⏳ 待做 |
| **机械臂** | **Elfin5**（大族 HansRobot 6-DOF 协作臂，5kg）——**非 UR** |
| Elfin 官方 **Python SDK**（实机用） | ✅ 现成（`reference/HuayanRobot_Library_Python_V1.0.11.0.pdf`）：`from CPS import CPSClient`、Linux `.so`、TCP 连控制器(10003)、含 **Servo 流式** `HRIF_PushServoP`、内置力控、IK/FK |
| 相机、电脑 | ✅ 已有 |

> ⚠️ `reference/` 执行方案示例代码是 `ur_rtde`（UR 专用），不能直接用。**开发方式见 §5**：算法用**纯 Python + PyBullet 仿真**开发；**实机直接用华沿 Python SDK**（`HRIF_PushServoP` 流式笛卡尔伺服，控制器自动逆解——**无需 ROS/Docker/EtherCAT**）。控制代码按"算法 ↔ I/O 解耦、后端可插拔"组织，详见 `docs/control-architecture.md`。Elfin 6-DOF，未来做笔锋姿态（v2）有优势。

---

## 4. 接口契约（两人对齐的唯一边界，务必先对齐）

**契约 1 · 实时触觉信号流**（队友 → Ethan 的控制环）
- 内容：`g_meas`（形变量 / 提按分量，**已按方向解耦侧向拖拽**）+ 时间戳；底层保留原始 `Bx,By,Bz`。
- 要求：**有线低延迟**、≥100Hz（外环 100–200Hz 够用）、抖动小。
- 待定：具体数据格式（USB 串口帧？）、单位、延迟实测值。

**契约 2 · StrokePlan**（可复现的最小单位）
- 结构：`{ xy路径, g_press(s) 目标提按曲线 }`。
- 参数化：提按按**弧长 s∈[0,1]** 表示（与运笔快慢解耦）；空间路径用 Bézier/B样条控制点（构造上 C² 光滑）。
- 来源可换：人写示范 / 模板 / 合成 / 以后的 Transformer——**执行器只认这个契约，不关心来源**。

---

## 5. 已锁定决策

| 维度 | 决定 | 日期 |
|---|---|---|
| 项目方向 | 从旧"书法教学/评估系统"转向"触觉毛笔机器人"；旧代码归档到 `legacy` 分支 | 07-13 |
| 项目重心 | 硬件 + 执行闭环（实机写字复现提按） | 07-13 |
| 交付核心 | Motion Copy 复现；Transformer 泛化 = 升级项 | 07-13 |
| 架构原则 | 执行器与轨迹来源用 **StrokePlan 契约解耦** | 07-13 |
| 反馈表示 | **形变量 + 偏移角**（论文 Fig.7 正解；触角驱动、自带拖拽解耦） | 参见执行方案§1 |
| 控制律 | 前馈标定 `z_ff(g_d)` + 低增益反馈 `Kv∫(g_d−g_meas)dt` | 参见执行方案§3.2 |
| **开发方式** | **纯 Python + PyBullet 仿真**开发算法（**算法与 I/O 解耦、后端可插拔**，见 `docs/control-architecture.md`）；**实机用华沿 Python SDK**（`CPS`/`HRIF_PushServoP` 流式笛卡尔伺服，**无需 ROS/Docker/EtherCAT**）。实机化 = 写一个 `HuayanBackend` + g_meas 切真流，①算法③循环不改 | 07-15 |
| **复现基线** | 复现 CalliRewrite = 开环位置写字 = 计划 B1 = 对比实验的**开环基线** | 07-13 |
| 时间 | 不设限、里程碑递增、核心优先 | 07-13 |

---

## 6. 开放问题 / 待决（TODO 决策）

- [ ] **示范采集方式**（相机追标记 / 拖动示教 Elfin / 先合成模板）——**按下不表，未定**。核心闭环不依赖它（靠 StrokePlan 解耦）。
- [x] **Elfin5 实时控制接口**（已定 07-15，读官方 Python SDK 手册）：**华沿 Python SDK（`CPS`/`HRIF_*`）**，TCP 连控制器；`HRIF_StartServo` + `HRIF_PushServoP` 流式笛卡尔伺服（控制器自动逆解），内置力控(mass/damp/stiff)、IK/FK。→ **实机无需 ROS/Docker/EtherCAT。ROS 纠结作废。**
- [ ] **Servo 频率上限待测**：手册示例周期 0.02s(50Hz)；能否到 100–200Hz 需实机测（周期是 float，理论可设更小）。50Hz 对准静态书法够用。
- [ ] **SDK Python 版本**：Linux `.so` 见到 cp36/cp37；实机后端可能需单独 py3.6/3.7 环境（PyBullet 仿真不受限，后端解耦互不影响）。
- [ ] **SDK 自带仿真**：`HRIF_SetSimulation` 需连着控制器(断电模式)→ **拿到臂/控制器后**才能用；预硬件阶段用 PyBullet。
- [ ] 契约 1/契约 2 的**具体数据格式**与队友敲定。
- [ ] `g_press` 方向解耦"能否干净分离提按 vs 拖拽"——**未证实**，靠 E4 量化。

---

## 7. 关键风险

| 风险 | 说明 | 缓解 / 门禁 |
|---|---|---|
| **E1 带宽（最大风险）** | 论文演示是准静态(~100s级)，写字快 100–300 倍；触角在真实写字速度下能否跟上快速提按**未知** | **E1 阶跃/扫频**是分水岭：过→触角闭环成立；不过→上独立 F/T 力环安全网，触角退回管接触状态/切笔画/偏移角 |
| 迟滞/蠕变 | 触角有粘弹性，快速提按下污染估计 | E3 量化回环面积 |
| 磁干扰漂移 | Elfin 钢法兰+电机磁场使基线 B0 漂；人写 vs 机器人写要可比 | **机器人姿态下重取基线**，必要时背景磁场扣除 |
| 数据稀缺（模型阶段） | 自示范样本少，Transformer 易过拟合 | 小模型+强正则+笔画重组增强；模型是升级项，不阻塞核心 |
| Elfin ≠ UR | 参考代码(ur_rtde)不能直接跑 | 算法用 Python 自写；实机用**华沿 Python SDK**（后端可插拔）——已确认 SDK 完备，无需 ROS |
| Servo 频率 | SDK 示例 50Hz，100–200Hz 上限未测 | 实机测；50Hz 对准静态书法够；不够再评估 |

---

## 8. 门禁实验速查（E1–E4，做完才决定控制方案）

| # | 实验 | 回答什么 | 判据 |
|---|---|---|---|
| **E1** | 阶跃 + 扫频响应 | 能否做快速提按（最关键） | 稳定时间 ≪ 0.1s、3Hz 内幅值不塌 |
| E2 | in-situ 标定（装配态） | ΔB↔形变↔力 曲线（供前馈 `z_ff` + 报告对标0.34N） | 单调、不饱和、斜率够 |
| E3 | 加载-卸载回环 | 迟滞/蠕变多大 | 回环面积小 |
| E4 | 恒力横向拖行 | 拖拽混淆幅度 | 拖拽分量可按方向分离 |

---

## 9. 进展日志

- **2026-07-13**
  - 深度阅读 `reference/` 全部方案，确认项目重定向。
  - 通过提问锁定：重心=执行闭环、核心=Motion Copy 复现、架构=StrokePlan 解耦、机构=Elfin5、旧代码归档。
  - Git：旧"书法教学/评估系统"代码归档到 **`legacy` 分支**；`master` 重置为 `reference/` + 计划文档（并把之前未跟踪的 reference/ 纳入、将内嵌的 CalliRewrite 展平为普通文件）。
  - 建立 `note.md`（本文件）+ `plan.md`；提交并推送到 `origin/master`。
  - **分析 CalliRewrite 机械臂控制**：纯开环 PTP 位置控制，笔宽靠 `z=func(r)` 标定映射的笔高来凑（"位置控宽度"）。链路 = RL 状态 `(p_t,x,y,r)` → `process()` 出 `(x,y,z)` npz → `RoboControl.Control()` 逐点 `SetPTPCmd` 下发。⚠️ **`RoboControl.py`(发送循环) 未开源**、Dobot DLL 仅 Windows/Dobot → 控制层需自己重写。**复现 CalliRewrite = B1 开环基线**。
  - 写 `docs/callirewrite-arm-control.md`：CalliRewrite 开环写字技术细节拆解。
  - **开发方式决策（含修订）**：先定"ROS2+Gazebo"，后查证 Elfin 实时控制以 **ROS/EtherCAT 为中心**（EtherCAT=控制器↔关节的 1000Hz 实时总线，ROS 驱动充当 master；官方驱动是 Foxy），遂**改为纯 Python + PyBullet 仿真开发**（免 ROS 学习成本、发挥算法长处），**ROS 仅实机阶段用**。代码按"算法↔I/O 解耦、后端可插拔"组织 → 写 `docs/control-architecture.md`。实机接口/ROS 版本延后到臂到位再定。
  - 配好 **ESP32 开发环境**（arduino-cli + esp32 core + MLX90393 库，编译验证通过）→ `~/esp32-brush-test/ESP32使用手册.md`（属队友硬件部分，本机备查）。
- **2026-07-15**
  - 读华沿官方 **Python SDK 手册**（`reference/HuayanRobot_Library_Python_V1.0.11.0.pdf`）+ Elfin 软件操作说明书。**决定性发现：实机用华沿 Python SDK 即可，无需 ROS/Docker/EtherCAT**——之前所有 ROS 版本/Docker/EtherCAT 的纠结作废。关键接口：`HRIF_Connect`(TCP 10003)、`HRIF_StartServo`+`HRIF_PushServoP`(流式笛卡尔伺服，控制器自动逆解)、内置力控(`SetMass/Damp/StiffParams`)、`HRIF_GetInverseKin/ForwardKin`。注意点：SDK 自带仿真需连控制器→预硬件仍用 PyBullet；`.so` 为 py3.6/3.7；servo 频率上限待实机测。
  - 据此把 note/plan/`docs/control-architecture.md` 的实机后端从 "ROS" 改为 "华沿 Python SDK(`HuayanBackend`)"。两个华沿手册 PDF **放本地 `reference/` 但 gitignore**（厂商专有，不发布到公开仓库）。
  - **下一步**：不变——搭 Python+PyBullet 环境（B0）+ B1 开环写字；实机后端(`HuayanBackend`)等臂到位再写。

---

## 10. 参考索引（`reference/`）

| 文档 | 内容 |
|---|---|
| `文献资料库.md` | 23 篇文献分方向整理 + 优先级 + 研究缺口 |
| `执行方案-力控.md` | ★执行端核心：反馈表示决策、导纳+触角形变、E1–E4 门禁、落地待办 |
| `模型方案.md` | 字形→轨迹+提按 的 Transformer（升级项） |
| `数采方案.md` | 数据采集流程、信号处理、时间同步 |
| `硬件方案-handoff.md` | 触觉毛笔硬件设计、双模取数、数据接口契约 |
| `导纳控制+触角形变-详解与论文带读.md` | 导纳/前馈反馈原理精读 |
| `前馈标定+低增益反馈-原理与文献.md` | 控制律理论依据 |
| `霍尔传感器-MLX90393-详细文档.md` | 传感器信号/标定 |
| `2024_CalliRewrite_精读.md` | 最接近的前作精读（拿什么/扔什么/超越点） |
| 种子论文 PDF | Ren et al., Nat. Commun. 16:3135 (2025)，Fig.7 触角毛笔嵌 UR3e |
| `CalliRewrite/` | 参考实现源码（图像→笔迹→书写） |
| **`HuayanRobot_Library_Python_V1.0.11.0.pdf`** | ★Elfin 官方 Python SDK 手册（实机控制的关键：连接/Servo/力控/IK-FK） |
| `Elfin软件操作说明书V6.4.pdf` | Elfin 软件/示教器操作手册 |

**本项目自产文档（`docs/`）：**

| 文档 | 内容 |
|---|---|
| `docs/control-architecture.md` | 执行端控制架构：算法↔I/O 解耦、后端可插拔、Python 仿真→华沿 SDK 实机、代码骨架 |
| `docs/callirewrite-arm-control.md` | CalliRewrite 开环写字技术细节（r→z 标定、process()、Dobot 下发、缺失件） |

> ESP32 开发环境手册在 `~/esp32-brush-test/ESP32使用手册.md`（本机，非本仓库）。
