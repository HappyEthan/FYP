---
project: 04-robot-control
status: archived
---

# StrokePlan 实验交付简表

> 2026-09-27 归档说明：本页恒定80目标等旧命令仅为历史记录，对应多余计划已从 plans/ 删除。删除前原件保留在本地 `runs/brush2/archive/plans-before-cleanup-2026-09-27.tar.gz`，不随 Git 同步。现行计划见 [计划索引](../../../runs/brush2/plans/README.md)。


更新：2026-09-24。用途：接手单笔纯前馈及前馈+P实验，执行并保留磁传感记录。

## 实验条件与文件

- 仓库：`/home/ethan/FYP`；环境：`brushbot`。
- 毛笔：**brush2**；固定 RPY 约 **(0,15,0)°**；坐标 `TCP_brush/Base`。
- 接触参考 Z=40 mm；等待 XYZ=(-200,500,130) mm。每笔手动沾水，在等待位姿启动。
- 路径：沿 +X 200 mm，巡航 10 mm/s，书写约 20.2 s；完整进退流程约 60 s，另需启动基线采集。
- 套件目录：[`runs/brush2/plans/ry15_rz0_suite_60_200_v1/`](../../../runs/brush2/plans/ry15_rz0_suite_60_200_v1/)。使用其中的 `feedforward.json` 和 `settings.json`。
- 操作入口：[纯前馈脚本](../../../scripts/run_strokeplan_feedforward.py)和[前馈+P脚本](../../../scripts/run_strokeplan_p.py)。**每次只执行一笔**，同步记录磁数据；两者各自固定控制模式，唯一必填参数是目标 StrokePlan 的 `.npz` 路径。

| 文件名（省略 `.npz`） | 磁目标 µT | 离线峰值指令加速度 mm/s² |
|---|---|---:|
| `01_gradual_press` | 60→200，渐增 | 已通过编译 |
| `02_single_arch` | 60→200→60，单峰 | 54.47 |
| `03_double_wave` | 60→200→60→200→60，双峰 | 106.14 |
| `04_smooth_levels_wide_transitions` | 60→130→200→95，四平台 | 98.34 |

第 4 条必须使用 **`wide_transitions` 新版**：三段过渡分别在路径 15–60、75–120、135–180 mm，各长 45 mm，保持原 XY 与时间律。原 `04_smooth_levels.npz` 峰值 242.44 mm/s²，仍超限并保留待查。新版按 20 ms 编译通过原 **200 mm/s²** 限制；这是命令轨迹检查，实机加速度未测量。[验证报告](../../../runs/brush2/plans/ry15_rz0_suite_60_200_v1/additional_trials_validation.json) · [新版预览](../../../runs/brush2/plans/ry15_rz0_suite_60_200_v1/04_smooth_levels_wide_transitions_preview/stroke_00.png)

前馈表来自 brush2 的 Ry15 梯子实验；约 14.2857 mm 点使用用户指定的 **250 µT 人工修正**，保留了修正来源。该表已由操作者启用用于试验，动态响应性能尚未验证。

## 单笔操作脚本

在已激活 `brushbot` 的终端、仓库根目录 `/home/ethan/FYP` 执行。两个脚本顶部各自配置前馈表、现场设置、串口、机械臂 IP 和 run 根目录；P 脚本顶部的 `PROFILE` 还配置首试增益与修正限幅，`ki` 必须为 0。更换实验条件时在对应脚本里修改并重新做 `--dry-run`。命令行唯一必填参数是 StrokePlan 文件，例如同一笔恒定 80 µT 目标：

```bash
python scripts/run_strokeplan_feedforward.py runs/brush2/plans/ry15_rz0_constant80_trial_v1/target.npz
```

```bash
python scripts/run_strokeplan_p.py runs/brush2/plans/ry15_rz0_constant80_trial_v1/target.npz
```

两者默认进入单笔真机确认流程：先离线编译和核对批准状态，打印等待位姿及配置路径；操作者手动沾水、核对位置并输入 `RUN` 后才连接设备。可选附加 `--dry-run` 仅做离线预检，不连接设备、不创建实验 run。四种动态目标也只需把上述最后一个 `.npz` 路径换成表中相应文件；第 4 条必须用 `wide_transitions` 版本。每次只执行一笔，自动建立新的实验 `raw/` 逐笔目录，不覆盖历史数据。

## 数据与当前进展

现在每次自动保存到 `runs/brush2/<日期>/<实验>/raw/<时间>_<目标与条件>_第N次/`，包括：

- `manifest.json`：状态、运行环境和文件哈希；`events.jsonl`：阶段及异常。
- `sensor.csv`：传感器记录；`control.jsonl`：目标 `a_ref_uT`、实际滤波响应 `a_control_uT`、误差和 Z 指令。Z 指令不能当作实测 TCP Z。
- `strokeplan.npz`、`feedforward.json`、`settings.json`：本次原始输入快照；另有 `compiled_plan.npz`、`timeline.npz`、`resolved.json`、`setup.json`、`calibration.json`。

截至 2026-09-24 核对，四种目标各两笔、共 8 笔纯前馈真机 run 在 [`runs/brush2/archive/2026-09-24/`](../../../runs/brush2/archive/2026-09-24/)；manifest 均为 `completed`。其目标/实测图与误差 CSV 在[八笔跟随汇总](../../../runs/brush2/archive/2026-09-24/01_四目标纯前馈/analysis/四目标跟随/tracking_summary.csv)。逐笔书写阶段 MAE 约 25.6–59.6 µT，重复间差异明显；`completed` 只说明运行结束，不代表达到磁目标。更早的 `e0fa78` 因 baseline 检查失败中止。

基线当前试验设置：窗口 2 s、至少 400 样本、超时 5 s、三轴标准差上限 [10,10,30] µT、漂移上限 5 µT/s。原 0.1 µT 门限与实测噪声不匹配，已调整并保留检查；详情见 [基线审计](../../../runs/brush2/plans/ry15_rz0_suite_60_200_v1/baseline_policy_review.json)。若再次失败，先读该 run 的诊断与原始数据。

用户接受小漂移及近似跟随，尚未定义数值误差容差。

## 首试磁触觉 P 反馈的软件状态

2026-09-24 的 P 试验由独立操作脚本固定选择 P 模式，共用原单笔记录引擎。仅 `measure_00` 使用 `e = a_ref - a_control`：误差为正时增加正向下压深度，真机 TCP Z 随 `z_cmd = contact_z - (depth_ff + depth_fb)` 减小；误差为负时抬高。`a_control` 仍为基线扣除后 XY 两轴逐样本 EMA α=0.3 的模长，与当前前馈表口径一致。非书写阶段无目标值，不调用反馈控制器，照旧执行进笔和退笔。纯前馈脚本用于同条件对照。

脚本当前首试参数为 `kp=0.05`、`ki=0`。现用表的全跨度斜率为约 0.04119 mm/µT，所以 50 µT 误差的未限幅 P 修正约 0.103 mm；修正幅度限制 ±0.20 mm，修正速度 2 mm/s、修正加速度 40 mm/s²，并在书写段首尾各 25 拍渐入/渐出至零。编辑 `PROFILE` 后，实际值会写入本次 `resolved.json`。最终 TCP 命令还检查现场 `max_depth_mm=20`、工作区、`max_step_mm=2`、`max_z_speed_mm_s=13`、`max_xy_speed_mm_s=30` 和合加速度 `max_accel_mm_s2=200`。无可行命令、传感过期或异常时走安全中止/抬笔；机器人通信故障仍按原机制停机。历史仿真默认 `kp=1.2077, ki=0.134` 不用于真机。

每拍 `control.jsonl` 保留目标、实测、误差、`depth_ff_m`、`depth_fb_m`、新增 `depth_cmd_m`、最终 `z_cmd_m`、`limit_active` 与 `limit_reasons`；`resolved.json` 记录模式及限幅。以上 Z 均为**命令值**，不是实测 TCP 位姿。

假传感器/假机械臂测试覆盖方向、阶段门控、幅度及动态限幅、传感器过期/异常/断开后的中止。对既有 8 笔纯前馈日志的[P 反馈命令边界回放](../../../runs/brush2/archive/2026-09-24/01_四目标纯前馈/analysis/P反馈命令边界回放/summary.json)逐拍通过算法和命令边界检查：每笔 1011 个书写拍，最大反馈压深修正 0.20 mm；所有正常运行的最终命令均在上述现场边界内。紧急抬笔仍采用原有退离流程。回放使用历史实测信号计算反事实命令，**不能预测闭环后的新磁信号，也不能声称跟随效果改善**。早期两个回放目录为同一批数据的中间输出，已清理。

恒定 80 µT 的 P 真机首笔 `d316b0` 在书写第 20 拍因反馈渐入包络与加速度约束无交集而安全中止，事件记录 `lift_completed`；随后 `42004d` 完成整笔。后者书写 1011 拍的目标为 80 µT，EMA 实测的平均绝对误差约 13.94 µT；没有同条件恒定目标纯前馈 run，不能归因于 P 改善。控制器已增加渐入/渐出包络的制动可行区间，不放宽幅度、速度、加速度或最终 Z 现场限制；复现故障的离线前缀现能通过原中止拍，8 笔历史信号影子回放与两组反转测试也通过。

之后四种变化目标各两笔 P 真机 run 均为 `completed`。[P 跟随总览图](../../../runs/brush2/archive/2026-09-24/02_P反馈与增益扫描/analysis/四目标P跟随/target_vs_measured_overview.png)、[有符号误差总览图](../../../runs/brush2/archive/2026-09-24/02_P反馈与增益扫描/analysis/四目标P跟随/signed_error_overview.png)和[逐笔指标 CSV](../../../runs/brush2/archive/2026-09-24/02_P反馈与增益扫描/analysis/四目标P跟随/tracking_summary.csv)沿用原纯前馈绘图口径，另有八张单笔图与 `source_and_method.json`。每张图用书写阶段记录的目标与 EMA α=0.3 实测磁幅值；X 轴是命令位置，非实测 TCP。第 3 种目标第二笔 MAE 约 67.3 µT，偏差明显；`completed` 仍不等于效果达标，也不能仅凭这些图将差异归因于 P 控制。

## 接手 prompt

```text
请接手 /home/ethan/FYP 的 StrokePlan 实验。先读 AGENTS.md 和 docs/04-robot-control/strokeplan-execution.md，再核对当前套件配置及最新 runs。此处交接记录是 2026-09-24 的历史快照。
本轮使用 brush2、RPY≈(0,15,0)°，+X 200 mm、10 mm/s。纯前馈与前馈+P分别使用 scripts/run_strokeplan_feedforward.py 和 scripts/run_strokeplan_p.py；执行时命令行只给单笔 StrokePlan 的 .npz 路径，前馈表、设置、串口等在脚本顶部修改。每笔手动沾水、核对等待位姿并输入 RUN；数据沿用 runs/brush2 日期目录。
第4条使用 04_smooth_levels_wide_transitions.npz，原版加速度超限；不得通过提高加速度限制来绕过。当前四种目标各两笔纯前馈、各两笔P均completed；恒定80µT P模式有一笔安全中止、一笔completed。跟随图分别位于 strokeplan_tracking_8 与 strokeplan_p_tracking_8；分析时逐笔核对效果，不以completed判定达标。
我接受小幅 baseline 漂移及近似目标跟随，不要求精确追踪。保留现有质量检查、前馈来源和人工修正记录；分析时区分目标、实测磁响应及命令 Z，区分离线验证、运行完成和效果验证。不要自动连续执行多笔或覆盖历史数据。
```
