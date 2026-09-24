---
project: 04-robot-control
status: active
---

# StrokePlan 执行说明

本说明使用现行格式版本 3 的[StrokePlan 目标契约](../02-strokeplan/strokeplan.md)。目标文件保存 XY、逐点时间和 `g_target`；执行器另读前馈表和现场设置，按时间插值目标后查表生成 Z 命令。`compiled_plan.npz` 与执行日志是派生产物，不是原始 StrokePlan。旧格式脚本[`execute_strokeplan.py`](../../scripts/execute_strokeplan.py)读取内嵌 Z 的历史文件，不应作为现行目标的执行入口。

## 当前执行范围

[`strokeplan_compile.py`](../../src/brushbot/strokeplan_compile.py)目前按 20 ms 编译，只支持 +X 直线、固定姿态以及前馈表适用范围内的速度和磁目标；纸面坐标只支持 XY 平移。编译器检查目标长度、时间、深度、工作空间、速度、加速度和单步位移。真实轨迹净空、纸面和装配条件仍须现场核对。带记录的[`strokeplan_execution.py`](../../src/brushbot/experiments/strokeplan_execution.py)每次只接收一笔。

## 输入文件与现场核对

| 输入 | 作用 | 必须核对 |
|---|---|---|
| `target.npz` | 现行 StrokePlan 目标 | 来源、坐标系、磁特征/滤波定义、笔数、XY、时间和目标范围。 |
| `feedforward.json` | 目标磁响应到前馈压深的映射 | 标定来源、毛笔/传感器/姿态、速度方向、有效范围与批准状态。 |
| `settings.json` | 本次现场设置 | TCP/UCS、纸面原点、接触/等待高度、固定姿态、工作空间、夹爪及运动/采集限制、现场核验状态。 |

磁目标是滤波后的 `|ΔBxy|`（µT），不是实测力。前馈表和设置需与本次毛笔、装配、纸面及信号处理一致；Z 命令不是实际 TCP Z。任何输入变化先重新预检，不能通过放宽限制来掩盖超限目标。

## 离线预检

通用录制入口可显式指定三个文件，默认不连接硬件，也不创建实验 run。将大写路径替换为本次实际文件：

```bash
python scripts/run_strokeplan_experiment.py PATH_TO_PLAN.npz \
  --feedforward PATH_TO_FEEDFORWARD.json --settings PATH_TO_SETTINGS.json --dry-run
```

另可用[`run_feedforward_strokeplan.py`](../../scripts/run_feedforward_strokeplan.py)单独预览编译轨迹；不带 `--execute` 时离线运行，`--preview <新文件.csv>` 可输出轨迹 CSV 和溯源报告。检查打印的等待位姿、Z 范围、总时长与编译限制。离线预检只检查软件契约和命令边界，不证明实际响应、净空或目标跟踪。

## 单笔真机录制

项目提供两个固定模式包装脚本：[`run_strokeplan_feedforward.py`](../../scripts/run_strokeplan_feedforward.py) 为纯前馈，逐拍记录磁响应但不据此修正 Z；[`run_strokeplan_p.py`](../../scripts/run_strokeplan_p.py) 仅在书写阶段使用受限 P 修正。**两个脚本默认进入真机确认流程**，先只用 `--dry-run`：

```bash
python scripts/run_strokeplan_feedforward.py PATH_TO_PLAN.npz --dry-run
python scripts/run_strokeplan_p.py PATH_TO_PLAN.npz --dry-run
```

包装脚本顶部固定前馈表、设置、串口、IP、输出目录和 P 参数；换毛笔或现场条件时须逐项核对，不要只替换 NPZ。正式运行时去掉 `--dry-run`，脚本先编译并检查输入批准状态，打印等待位姿与配置；操作者完成沾水、确认处于等待位和路径净空后输入 `RUN`，才连接设备。每次只运行一笔，不能把多个 NPZ 当成自动连续执行。

也可直接使用通用入口，显式传入 `--execute`、文件、连接参数和 `--control-mode feedforward|p`；P 模式当前要求匹配的 EMA α=0.3 信号处理与 `ki=0`。控制器仅在 `measure_00` 使用 `g_target - g_measured` 做修正；非书写阶段按编译轨迹运行。传感器无效、过期或通信异常的处理取决于实验引擎，运行后应核对事件与结束状态。

## 运行产物与结论

录制入口按新时间和短 ID 建 run，保存 `manifest.json`、`events.jsonl`、`sensor.csv`、`control.jsonl`，并快照 `strokeplan.npz`、`feedforward.json`、`settings.json`、编译轨迹和设置。核对 `manifest` 的最终状态、异常事件、目标与实测曲线以及限幅记录；`completed` 只表示运行结束，不能说明跟踪达标或墨迹改善。P 模式要和相同目标、前馈及装配条件下的纯前馈结果比较。

brush2 套件、运行数值与单笔结果以各次 run 的输入快照、manifest 和分析产物为准；当前执行批次完成后再整理按日期的实验记录。自动沾水梯子实验另见[历史方案](archive/wetting.md)，当前 StrokePlan 单笔脚本使用人工沾水。
