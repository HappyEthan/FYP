---
project: 04-robot-control
status: active
---

# Z 动态辨识实验

操作入口为 [`run_z_identification.py`](../../scripts/run_z_identification.py)，轨迹与阶段由 [`z_identification.py`](../../src/brushbot/experiments/z_identification.py) 编译。每次只执行一个基础深度的一条 +X 直线，直接给定 Z，触觉 P/PI 关闭。局部增益、有效延迟和重复性需用实测数据辨识；软件验证不代表接触效果、物理净空或模型已通过真机验证。

## 当前配置与进笔

2026-09-25 复录慢扫后，操作者要求将后续默认旋转接触高度从 **Z38 改为 Z36 mm**，本页下述操作参数均已更新。既有原始记录仍按各自快照分析，15:02:32 的复录也使用 Z38。Z36 比 Z38 更低 2 mm，是否降低异常尚需新高度实测；改变起点后，不将 Z38 与 Z36 当作完全相同条件的重复实验。

参数集中在入口脚本顶部的 `SETTINGS`、`SETUP_OVERRIDES`、`DEPTH_PROFILES`、`PROFILE` 和 `SWEEP_PROFILES`。基础现场设置沿用 brush2 套件；本实验将起点设为 X=-370、Y=500 mm，等待 Z=130 mm，书写姿态为 Rx0/Ry15/Rz0。450 mm 行程止于 X=80 mm，巡航速度 10 mm/s。修改纸面位置时更新顶部设置并重新预检。高位固定 Z 返回独立使用安装设置中的 `return_speed_mm_s=20`，完整返回约 42.2 s；下降、抬笔仍采用峰值不超过 10 mm/s 的轨迹。

1. 在上述悬空等待位以 Ry15 采集并固定磁基线。
2. 在高位用 3 s 平滑转到 Ry30，然后以该姿态下降到 Z=36 mm。
3. 保持 TCP 的 XYZ 不变，用 3 s 将 Ry30 转到 Ry15。操作者已说明此动作用于旋转接触纸面；软件只验证 TCP 命令，不证明笔毫扫过的空间无障碍。
4. 开始 +X 行笔。最初 1 s 保持 Z36，随后用 3 s 在持续滑动中加载到基础压深。
5. 执行九个平台、八次过渡。第一平台是到达工作点后的 4 s 稳定观察段。
6. 在末端停止 XY 后，以 Ry15 抬到等待高度，悬空记录 2 s，再高位返回起点。

`entry_contact_z_mm=36` 是旋转接触高度；`contact_z_mm=40` 仍是名义压深参考。两者分开保存。接触后不重新取基线；旋转和进笔信号不进入局部增益拟合。

## 扰动序列

下表为未传 `--delta-mm` 时的预设；本轮实测后的推荐幅度见“第二阶段”，由命令显式覆盖。

| 基础压深 / mm | 大扰动 / mm | 小扰动 / mm | 实际命令压深范围 / mm |
|---:|---:|---:|---:|
| 5 | ±0.60 | ±0.30 | 4.40–5.60 |
| 7.5 | ±0.50 | ±0.25 | 7.00–8.00 |
| 10 | ±0.40 | ±0.20 | 9.60–10.40 |
| 12.5 | ±0.30 | ±0.15 | 12.20–12.80 |
| 15 | ±0.25 | ±0.125 | 14.75–15.25 |

`press-first` 的相对深度依次为 `0,+δ,0,-δ,0,+δ/2,0,-δ/2,0`；`lift-first` 将所有偏移取反。每个平台保持 4 s，过渡 0.4 s，使用起止速度和加速度均为零的五次平滑曲线。序列共 39.2 s，放在 XY 匀速区间。整条滑动约 45.2 s；7.5 mm 默认配置的编译轨迹约 131.54 s，包含高位转姿、接近、抬笔和返回，另需启动基线时间。

上述扰动是候选实验配置，不是已辨识增益。深区如果响应不足，分析会标记弱激励；改变幅度后的数据须按新配置比较。保持时间不足时延长或拆分实验，不自动缩短平台或越出工作空间。

## 执行命令

### 第一阶段：全范围扫描（已完成，命令保留）

先执行四笔全范围扫描，再根据扫描中 60–200 µT 对应的深度选择两三个局部工作点。相同模式的两笔使用相同装配、速度、沾水方式和纸面条件，落在新的平行纸带上。每条命令只执行一笔，单独输入 `RUN`，保存目录自动编号。

| 顺序 | 模式 | Z 变化与测量时序 | 单次完整轨迹 |
|---|---|---|---|
| 1、2 | `sweep-down` | Z36 滑动 3 s，30 s 平滑降至 Z24，保持至少 4 s | 133.12 s |
| 3、4 | `sweep-cycle` | Z36 滑动 3 s，15 s 降至 Z24，保持 3 s，15 s 回到 Z36 | 130.88 s |

两种模式均在旋转接触之后开始 +X 行走，全程 X 向前，Ry15 不变。完成扫描序列后保持最后 Z 继续滑动至行程末端，再抬笔。Z 扫描使用五次平滑曲线，速度随时间变化：慢扫平均 0.400 mm/s、峰值 0.750 mm/s；快扫平均 0.800 mm/s、峰值 1.50 mm/s。名义压深为 4–16 mm，不将旋转接触点重新定义为压深零点。

```bash
cd /home/ethan/FYP
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

# 两种配置的离线预检，不执行机械臂动作
python scripts/run_z_identification.py --mode sweep-down --dry-run
python scripts/run_z_identification.py --mode sweep-cycle --dry-run

# 1、2：慢扫，各自准备纸面和笔后运行
python scripts/run_z_identification.py --mode sweep-down
python scripts/run_z_identification.py --mode sweep-down

# 3、4：下压—回升，各自准备纸面和笔后运行
python scripts/run_z_identification.py --mode sweep-cycle
python scripts/run_z_identification.py --mode sweep-cycle
```

这四笔先用于观察整体曲线、速率影响及初步重复性。局部动态实验在选定深度后每个深度也做两次、保持同一扰动顺序；不能将两个不同扰动顺序称为同条件重复。两次重复尚不构成独立模型验证数据。

### 第二阶段：局部平台扰动（当前推荐，每个工作点两次）

根据两筆正常慢扫及两笔往返扫描，当前先测试 5、10、12.5 mm 三个工作点。浅、中区原幅度产生的磁变化可能偏小，因此通过 `--delta-mm` 显式设置大扰动，小扰动自动取一半。以下幅度仍为候选激励，能否可靠拟合延迟需检查实测信噪比和平台稳定性；不预先保证可辨识。

| 顺序 | 基础压深 / mm | 基础 Z / mm | 大 / 小扰动 / mm | 压深范围 / mm | 命令 Z 范围 / mm |
|---|---:|---:|---|---|---|
| 1、2 | 5 | 35 | ±1.0 / ±0.5 | 4–6 | 34–36 |
| 3、4 | 10 | 30 | ±1.0 / ±0.5 | 9–11 | 29–31 |
| 5、6 | 12.5 | 27.5 | ±0.5 / ±0.25 | 12–13 | 27–28 |

六笔都用 Z36 旋转接触、Ry15 书写、+X10 mm/s、450 mm 行程。先行走 1 s，再用 3 s 到达基础压深，之后第一平台保持 4 s；首个扰动约在行走 8 s 后开始。每个平台 4 s、平滑过渡 0.4 s，重复使用相同 `press-first` 顺序，每笔内均含下压与回升。单笔完整轨迹约 131–132.5 s，六笔约 13.2 分钟，另加基线采集与人工准备。

```bash
cd /home/ethan/FYP
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

# 离线预检
python scripts/run_z_identification.py --depth-mm 5 --delta-mm 1 --dry-run
python scripts/run_z_identification.py --depth-mm 10 --delta-mm 1 --dry-run
python scripts/run_z_identification.py --depth-mm 12.5 --delta-mm 0.5 --dry-run

# 1、2：5 mm，每次分别准备笔和纸面后运行
python scripts/run_z_identification.py --depth-mm 5 --delta-mm 1 --order press-first
python scripts/run_z_identification.py --depth-mm 5 --delta-mm 1 --order press-first

# 3、4：10 mm
python scripts/run_z_identification.py --depth-mm 10 --delta-mm 1 --order press-first
python scripts/run_z_identification.py --depth-mm 10 --delta-mm 1 --order press-first

# 5、6：12.5 mm
python scripts/run_z_identification.py --depth-mm 12.5 --delta-mm 0.5 --order press-first
python scripts/run_z_identification.py --depth-mm 12.5 --delta-mm 0.5 --order press-first
```

`--delta-mm` 只适用于局部模式，仍经过深度范围、运动限值预检；实际幅度保存至快照并用于目录标签。每笔需输入 `RUN`，不自动串行执行六笔。实验期间反馈关闭，实际 TCP 独立采集保持开启。Z36 的接触效果尚需首笔实测检查，前一笔 Z38 复录不能作为新高度的验证。

### 其他局部平台扰动入口

在仓库根目录、已安装 brushbot 的环境中：

```bash
python scripts/run_z_identification.py --depth-mm 7.5 --dry-run
python scripts/run_z_identification.py --depth-mm 7.5
```

不带 `--dry-run` 时，先打印等待位、进笔方式、范围、时长和运动峰值，操作者完成沾水、核对等待位与路径后输入 `RUN` 才连接设备。默认基础深度 7.5 mm。每次只执行一笔，不自动执行所有深度或多次重复。

反向扰动顺序：

```bash
python scripts/run_z_identification.py --depth-mm 7.5 --order lift-first --dry-run
```

实际 TCP 默认独立连接约 10 Hz 采集，首次读取失败不开始运动。`--no-record-actual-tcp` 显式关闭此证据流。后台读取不参与反馈；后续读取缺失或错误保存在 `actual_tcp_meta.json`，不能把插值结果当作同步实测位姿。

新轨迹显式检查平移速度、加速度、单步位移、工作空间，以及角速度和角加速度。角速度候选上限 10°/s，角加速度 20°/s²；正常 3 s 转姿的峰值约 9.37°/s 和 9.62°/s²。机械臂底层仍需支持固定 TCP 的姿态变化。

传感无效、过期、断开或 Ctrl+C 在运行阶段进入既有中止抬笔流程，保持最后命令姿态，不在接触状态自动转回。该异常退出继承原引擎的停止机制，不等同于正常轨迹的完整动态保证。机械臂通信失效时终止并保存故障记录，不继续盲发轨迹。

## 保存与溯源

```text
runs/brush2/YYYY-MM-DD/05_Z动态辨识/
  raw/HH-MM-SS_压深7p5mm_扰动0p5mm_先下压_第N次/
  analysis/<分析批次>/
```

沿用上海本地日期和独立 run ID。每笔保存 `manifest.json`、`resolved.json`、`setup.json`、`settings.json`、`settings_source.json`、`identification.json`、`segments.json`、`motion_metrics.json`、`compiled_plan.npz`、`timeline.npz`、`sensor.csv`、`control.jsonl`、`events.jsonl`，以及默认开启的 `actual_tcp.csv`、`actual_tcp_meta.json`。

`settings_source.json` 是源设置原文；`settings.json` / `setup.json` 是包含当前起点和姿态覆盖的有效设置。输入快照保存 SHA256。重复编号用于区分目录；分析需比较完整配置，不能仅凭“第N次”合并不同实验条件。

控制记录增加 `segment_id`、`segment_kind`、`plateau_index` 和 `prescribed_depth_m`。磁目标及磁误差均为 null。兼容字段 `depth_ff_m` 保存给定名义深度，来源是激励轨迹，不是前馈表；`depth_fb_m=0`。派生 NPZ 标明 `derived_identification_timeline`，不是 V3 磁目标文件，不应传给 StrokePlan 执行入口。

扫描目录分别使用 `连续下压_Z36到24mm_单程30s_第N次` 和 `下压回升_Z36到24mm_单程15s_第N次` 标签，并保存 `mode` 及完整时序。扫描模式不接受 `--depth-mm` / `--delta-mm` / `--order`，避免将局部扰动参数误用于扫描。

## 离线分析

```bash
python scripts/analyze_z_identification.py PATH_TO_RUN
python scripts/analyze_z_identification.py RUN_1 RUN_2 RUN_3 --output PATH_TO_NEW_ANALYSIS_DIR
```

默认在对应实验的 `analysis/` 下建新目录，不覆盖原始数据或已有分析。输出每笔 JSON、三面板图（命令/异步实测 Z、Ry、磁响应）、`transition_metrics.csv` 和保留逐笔结果的 `comparison.json`。

同一分析入口支持扫描数据：按下压/回升分别以 0.25 mm 名义命令深度分箱，输出 `sweep_curves.csv`、逐笔 JSON 和三面板图；纯扫描批次不生成平台转换表，也不拟合静态 K、延迟或时间常数。分箱标准差是笔内变化，不是跨笔重复性；曲线包含动态滞后、纸面位置和含水状态影响，不自动升级为前馈表。

每个平台取末尾 0.8 s 统计均值、标准差和趋势。局部静态增益按相邻平台的磁变化除以实际给定深度变化计算。动态模型拟合实际记录的命令波形及主机时间，使用一阶响应加有效延迟的网格候选；不会把平滑输入当作理想阶跃。主机控制行在命令发送前取时，模型包含伺服、通信、采集和滤波效应，不是纯笔毫材料参数。

平台趋势超过 3 µT/s、响应小于相邻平台波动标准差的三倍（标准差下限 1 µT）、非正增益、模型搜索触边或拟合质量不足时会标记。这些是初始诊断阈值，不是统计置信区间或已验证的 PI 整定标准。延迟搜索步长 20 ms；0 延迟估计不证明物理延迟为零。实际 TCP 仅用于辅助观察，不用于制造高频姿态证据。

平台记录同时统计计划 tick 的缺失、重复和实际时间覆盖。轻微跳拍仍输出分析，但相邻转换标记 `timing_irregularity`，不直接用于初始整定；平台时长偏差超过 80 ms 或首尾覆盖不足另加标记。尾部少于 20 个有效样本或覆盖不足 0.6 s 时停止拟合并报告证据不足。

扫描阶段已完成并补录一笔慢扫；当前按第二阶段命令执行 5、10、12.5 mm 局部扰动，每个工作点做两次。后续要检验模型预测时另采独立数据。相同深度的不同重复若差异明显，应保留这一结果，不能强行导出单一可靠 K。
