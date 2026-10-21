---
project: 04-robot-control
status: active
---

# StrokePlan 执行说明

非线性前馈表、受限 PI 的现行控制律及 2026-09-25 实验结论见[完整设计与实验总结](nonlinear-feedforward-pi-summary-2026-09-25.md)。六个实验启动包装已合并为 [`run_strokeplan_trial.py`](../../scripts/run_strokeplan_trial.py)，在脚本前部选择实验并编辑参数；单笔 P 模式仍限定 `ki=0`。

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

统一入口 [`run_strokeplan_trial.py`](../../scripts/run_strokeplan_trial.py) 在前部集中提供中文参数说明。修改 `EXPERIMENT` 选择下列实验，默认 `EXECUTE=False`，只进行离线预检：

| `EXPERIMENT` | 实验 | 主要参数 |
|---|---|---|
| `strokeplan_ff` | 单笔纯前馈 | `STROKEPLAN` |
| `strokeplan_p` | 单笔受限 P | `STROKEPLAN`、`P_PROFILE` |
| `nonlinear` | 160–240 µT 难曲线 FF/P 对比及 P 扫描 | `MODE`、`KP`、`MAX_CORRECTION_MM`、`P_DYNAMICS` |
| `short_plateau` | 160→240→160 短平台 P/PI | `MODE` |
| `ki_scan` | 冻结顺序的六步 Ki 扫描，每次执行一步 | `KI_STEP` |
| `calligraphy` | 中字逐笔或整字 | `MODE`、`STROKE` |

选好参数后直接执行：

```bash
python scripts/run_strokeplan_trial.py
```

脚本前部还提供各实验的输入目录、前馈表、现场设置、串口、IP、输出目录和 TCP 采样开关。`MODE=None` 自动选择当前实验的默认模式；`TRIAL=None` 自动选择对应输入目录。单笔 FF/P 的 `STROKEPLAN` 相对路径从该输入目录计算，也支持绝对路径。切换实验后重新核对装配和输入，不要只替换 NPZ。

也可以临时用命令行覆盖实验选择、目标与执行开关。命令行目标路径相对当前工作目录解析，沿用原入口的用法；脚本前部的 `STROKEPLAN` 相对实验输入目录解析。

```bash
python scripts/run_strokeplan_trial.py --experiment strokeplan_ff PATH_TO_PLAN.npz --dry-run
python scripts/run_strokeplan_trial.py --experiment strokeplan_p PATH_TO_PLAN.npz --dry-run
```

正式运行将前部的 `EXECUTE` 改为 `True`，或显式传入 `--execute`。脚本编译并检查输入批准状态，打印等待位姿与配置；操作者完成沾水并确认自动回位与书写路径净空后输入 `RUN`，才连接设备。连接与坐标核验通过后，脚本按当前 `settings.json` 自动定位：先在当前 XY 抬到转场高度，再高位移动到等待点、对齐姿态，必要时下降至等待高度。到位后仍执行原有等待位检查，清空定位期间积累的传感器数据，再采集基线和开始实验。单笔模式每次只运行一笔；整字模式保留全部笔画预检、一次整字确认和任一笔异常后停止的策略。

启动定位复用四方向实验的限速、限加速度和逐点到位检查。当前位置超出当前配置的工作空间、机械臂未处于 Standby（33）或定位失败时停止，不能通过跳过等待位检查开始写字。定位尝试在 `runs/<brush>/<日期>/positioning/strokeplan_*.json` 中独立保存，失败时也保留记录；成功运行的 `resolved.json` 中另存 `positioning`，包含原始位姿、路线、定位记录路径和传感器缓冲清理结果。启动定位耗时单独记录，不计入目标 StrokePlan 的书写时长。

若要诊断命令 Z 与实际 TCP Z 的差异，将 `RECORD_ACTUAL_TCP=True`，或加 `--record-actual-tcp`，先进行离线预检。`None` 保留各实验原设置：单笔 FF/P 默认关闭，其余实验开启。该选项在确认后另开一条机械臂连接，先验证实际 TCP 可读，再以约 10 Hz 在独立线程记录；首次读取失败时不开始机械臂运动。采集不参与反馈，也不让每个 20 ms 命令拍等待状态查询。

也可直接使用底层 `run_strokeplan_experiment.py`，显式传入文件、连接参数和 `--control-mode feedforward|p|pi`；P 模式要求匹配的 EMA α=0.3 信号处理与 `ki=0`，PI 由统一实验入口传入完整 PI profile（含积分限幅与条件抗饱和）。上述单笔控制器仅在 `measure_00` 使用 `g_target - g_measured` 做修正；非书写阶段按编译轨迹运行，PI 积分清零。传感器无效、过期或通信异常的处理取决于实验引擎，运行后应核对事件与结束状态。

## 运行产物与结论

录制入口在日期下按实验建 `raw/` 目录，逐笔以新时间、条件和重复次序命名；完整运行 ID 留在 `manifest.json`。每笔保存 `events.jsonl`、`sensor.csv`、`control.jsonl`，并快照 `strokeplan.npz`、`feedforward.json`、`settings.json`、编译轨迹和设置。核对 `manifest` 的最终状态、异常事件、目标与实测曲线以及限幅记录；`completed` 只表示运行结束，不能说明跟踪达标或墨迹改善。P 模式要和相同目标、前馈及装配条件下的纯前馈结果比较。目录示例见[9 月 24 日三类实验](../../runs/brush2/archive/2026-09-24/README.md)。

启用实际 TCP 采集的 run 另有 `actual_tcp.csv` 与 `actual_tcp_meta.json`。CSV 包含六维 SI 位姿、每次请求的单调时钟起止时间、有效标志和错误；元数据包含有效／无效样本数及最大读取耗时。实际位姿是异步采样，`control.jsonl` 的 `actual_pose_available` 仍可能为 `false`；分析时按共同的单调时钟离线对齐，标出样本年龄和缺口，不把每条命令行强行当作同时刻的实际位姿。没有足够新鲜的实际样本时，不计算逐拍 TCP 跟踪误差。

brush2 套件、运行数值与单笔结果以各次 run 的输入快照、manifest 和分析产物为准；当前执行批次完成后再整理按日期的实验记录。自动沾水梯子实验另见[历史方案](archive/wetting.md)，当前 StrokePlan 单笔脚本使用人工沾水。

## 非线性前馈与 P：单条难曲线对比

在 [`run_strokeplan_trial.py`](../../scripts/run_strokeplan_trial.py) 选择 `EXPERIMENT="nonlinear"`，读取本次 160–240 µT 难曲线、非线性表和旋转进笔参数。`MODE="ff"` 或 `"p"` 切换对照；默认只预检，真机逐笔输入 `RUN`。两种模式共用目标与名义前馈轨迹，实际 TCP 采集默认开启，P 参数从实验目录的 `p_profile.json` 读取；顶部的 `KP`、`MAX_CORRECTION_MM`、`P_DYNAMICS` 可选择 P 扫描条件。

```bash
python scripts/run_strokeplan_trial.py --experiment nonlinear --mode ff --dry-run
python scripts/run_strokeplan_trial.py --experiment nonlinear --mode p --dry-run
```

本批次采用高位 Ry30 → Z36 → 固定 XYZ 旋转至 Ry15，随后 +X 滑动 1 s、行走中加载 3 s，再进入 40 s 测量。全线 450 mm（X−370→80），其中测量段 400 mm（X−331→69）；测量前后的 X 运动连续。磁目标包含快慢升降、短平台与多次反转，P 仅在 `measure_00` 生效。

通用入口通过可选 `--entry-profile` 启用该流程；未提供时保留原有固定姿态下笔。旋转模式要求单笔纸面坐标目标与准备段后的连续行笔位置、速度吻合，拒绝不匹配而不自动平移原目标。每次 run 快照 `entry_profile.json`，`resolved.json` 同时保存进笔配置与实际 P 参数；新旋转流程下两种模式的传感器断开均触发中止抬笔。

本次试验文件与执行顺序见[批次说明](../../runs/brush2/plans/06_难曲线160到240_FF与P/README.md)。批次产物中的旧脚本命令保留作历史来源，当前执行使用上面的统一入口。记录到 `runs/brush2/<日期>/06_非线性前馈难曲线对比/raw/`，沿用 sensor/control/events/manifest、输入快照及 actual_tcp 格式。试验表已按用户本次对比请求标记为实验采用，不表示跟踪效果已验证；原候选表与既有实验参数保持原样。
