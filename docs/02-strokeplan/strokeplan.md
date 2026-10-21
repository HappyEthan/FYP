---
project: 02-strokeplan
status: active
---

# StrokePlan：现行说明与设计

## 定位

**StrokePlan 是书写前确定的笔画目标**，按顺序保存连续接触笔画的 XY 几何、时间规律和目标磁触觉状态。现行软件契约是 **格式版本 3**；本文的 StrokePlan 均指这一契约。格式号用于文件校验，不表示多个并行的现行设计。旧格式只用于历史实验兼容，新计划使用现行入口生成。

XY 中心线只规定经过哪里；接触、速度和姿态不同仍可形成不同墨迹。因此计划同时保存 `xy(t)` 和 `g_target(t)`，并预留姿态参考。计划中的目标与实测磁场、实际 TCP、标定表和本次设备命令必须区分。

## 当前数据契约

实际文件为 `.npz`，由 [`target_strokeplan.py`](../../src/brushbot/target_strokeplan.py) 校验与读写，`format_version=3`。每个文件至少有一条 `Stroke`；每条至少两个样点。

| 层级 | 字段 | 现行含义与约束 |
|---|---|---|
| 笔画 | `s` | XY 累计弧长归一化到 0–1；相邻样点可相同以表示停顿，整笔零长度不允许。 |
| 笔画 | `xy` | `M × 2` 位置，单位 m；坐标系须明确。 |
| 笔画 | `t` | `M` 个秒数，每笔从 0 开始且严格递增；与 `s` 分离以表达速度和停顿。 |
| 笔画 | `g_target` | `M` 个非负 µT 值；当前特征为滤波后 `|ΔBxy|`，是接触/形变代理目标，不等同于力或笔画宽度。 |
| 笔画 | `orientation` | 可选 `M × 3`、有限值、弧度制的 base RPY；启用时元数据须写 `orientation_convention: base_rpy_rad`。 |
| 文件 | `meta` | 至少明确 `source`、`coordinate_frame`、`feature`、`filter_definition`；非纯合成来源须有 `provenance`。 |

`source` 可为 `synthetic`、`demonstration`、`mixed`；`coordinate_frame` 可为 `paper`、`base`；`feature` 固定为 `filtered_dBxy_norm_uT`。单位为 m、s、µT。全部数组长度一致且数值有限。现行文件不含 Z 或内嵌前馈表；校验器也拒绝藏在元数据里的设备/Z 字段。

上述 `feature` 是当前未做最新方向校准的基线／滤波后幅值。新研究流程要求测量端校准到公共参考，再用一张统一前馈表，见[实验交付](../08-system-evaluation/实验清单.md#public-feedforward)。接入时须显式适配校准特征与参考标识，并迁移旧目标；目前契约与代码没有完成该扩展，不能将现有计划的相同数值静默解释成公共校准目标。

`z_ff` 未来是否成为有标定来源的派生缓存、学习数据需要哪种 Z 标签，仍需单独裁定；接口变更前生成器不得自行加入这些字段。

## 生成边界

生成过程先确定笔画顺序和每笔 XY 曲线，再设置时间 `t` 与目标 `g_target`，计算与 XY 一致的 `s`，最后写入来源、坐标系和磁特征定义并校验。计划采样率无需等于机器人控制频率；XY 不变而时间前进可以表达停顿。

目前可用[合成单笔生成器](../../scripts/generate_strokeplan.py)、[四种目标轮廓生成器](../../scripts/generate_strokeplan_suite.py)及[JSON 参考笔画生成器](../../scripts/generate_strokeplan_from_json.py)。JSON 配方支持横、竖、撇、捺、横折的独立调试，编辑方法见[笔画 JSON 配方](笔画JSON配方.md)。它们输出离线目标，不代表示教测量或真机跟踪。从图像、模板、示教录音或 Transformer 生成同一契约，需分别说明笔画分解、时间/磁目标来源、坐标和滤波定义；只有 XY 的输入不能冒充实测磁目标。

### 从不同来源生成计划

1. **分笔与定序**：确定连续接触段、笔顺、坐标系和尺度；从图像推断的笔顺须标明来源。
2. **建立几何与时间**：生成有序 XY 样点及累计弧长 `s`，再给每笔设置从 0 开始、严格递增的 `t`。起收笔、转折和停顿要考虑速度与加速度；停顿时 XY 可重复，时间仍前进。
3. **建立接触目标**：给样点配对齐的 `g_target`。示教数据保留原始磁信号、基线、处理方法和时间对齐；人工补足目标标为合成或混合来源。笔画宽度可用于视觉评价，不能未经标定直接当作磁目标或压深。
4. **校验与预览**：校验字段、数值和来源，查看 XY、`g(s)`、`g(t)`，再检查现有编译器的执行范围。离线通过不代表真机效果。

当前离线生成已包含直线、局部圆滑折线及 Bézier 曲线，并可复用“中”字的方向姿态时间规划。当前研究先用可编辑配方获取可重复的参考笔画，再研究笔画特征与高质量生成规则；这些人工目标不等于论文生成方法完成，也不要求立即采集 Transformer 训练数据。常规编译器的支持范围与“中”字实验入口需分别核对，离线曲线生成成功不表示其多方向前馈及墨迹效果已验证。

### 姿态来源与扩展

现阶段使用现场固定姿态，并在前馈配置中记录适用姿态；固定姿态不一定垂直。目标姿态、机器人实测姿态与磁传感器响应是三种不同数据，磁幅值既不等于 RPY，也尚不能单独辨识笔杆轴向旋转。

没有示教时，可从图像获得轮廓、候选中心线和连接关系，按规则产生初始姿态，再通过试写和墨迹评价优化少量控制点。最终图像不能唯一恢复速度、接触、姿态或变形历史。根据路径切线安排倾斜方位、在折角处约束角速度等只是研究候选，未进入当前执行器。

有示教时，可研究多相机标记、运动捕捉、IMU、轴向编码器或机器人示教；需同步采集笔尖 XY、笔杆位姿、原始三轴磁场和时间，并记录纸面、相机、标记、笔杆的坐标变换及外参来源。只有笔杆中心线不能确定轴向旋转；命令位姿和实测位姿须分开保存。

当前可选姿态仅为 `M × 3` 的 base RPY，执行器仍只接受与现场固定姿态相同的序列。未来可研究单位四元数及 SLERP、方向性磁目标与动态姿态，但必须先验证可观测性、采集质量和执行能力。建议在元数据中记录 `xy_source`、`stroke_order_source`、`g_target_source`、`orientation_source` 和 `orientation_confidence`；这些是设计建议，不是当前校验器的必需字段。

## 与执行和记录的接口

```text
StrokePlan（XY、时间、磁目标、可选姿态）
  + 独立 FeedforwardConfig（磁目标 → 压深、适用条件）
  + ExecutionSettings（纸面原点、固定姿态、接触零点、安全限制）
  → CompiledTrajectory（插值目标后查表得到 Z；加入下笔、抬笔、回程）
  → 机器人执行 / ExecutionLog（命令、实测、图像、状态）
```

当前[`strokeplan_compile.py`](../../src/brushbot/strokeplan_compile.py)以 20 ms 为执行周期，先按 `t` 插值 XY 与 `g_target`，再查独立前馈表。纸面坐标当前仅做 XY 平移。编译器只接收 +X 直线和与现场固定姿态相同的姿态序列，并检查速度、加速度、单步、深度和工作空间；通用曲线和动态姿态尚未支持。[前馈预览入口](../../scripts/run_feedforward_strokeplan.py)默认离线。

另有[单笔录制实验入口](../../scripts/run_strokeplan_experiment.py)，通过[`strokeplan_execution.py`](../../src/brushbot/experiments/strokeplan_execution.py)把现行目标编译为实验引擎可用的派生轨迹，支持前馈与 P 反馈两种模式，并记录输入快照和磁信号。这个派生轨迹内部复用旧类，但**不是原始 StrokePlan 契约**。每次调用目前限一笔；真机运行还要满足输入批准和现场确认。编译、离线回放和真实书写分别提供不同证据，不能互相代替。

日志应保存实际时间、TCP、原始磁场、基线、滤波特征、Z 命令和异常等，不能回写为计划目标。前馈表要记录毛笔、装配、姿态、方向、速度、滤波和有效范围；超出条件须重新验证。

### 公共校准接入要求（尚未完成）

当前 `feature` 及旧配方仍使用原始基线／滤波后幅值。后续接入须保留 raw 与 calibrated 角色、模型与公共参考标识／哈希：测量端用已知行笔方向和处理后的 Bx、By 求校准值，命令端以同一公共 G 反查 Z。原始向量、符号、幅值与无效原因均需保留；校准值不覆盖原 `a_control_uT`。

旧目标可在严格支持范围内按 `d_old=F_old⁻¹(g_old)`、`g_target_cal=G(d_old)` 保留名义命令意图，或重新设定该参考下的工程初值；两者都另存配方和来源，不保持旧数值只改名。这种转换不保持真实力、笔宽或跨毛笔效果。

横、竖先按实际 Base 行笔方向选曲线；例如横沿 −X 时用 `left`，竖沿 +Y 时用 `up`。撇、捺和横折的连续方向、转弯降速及起收瞬态仍需明确支持规则，不静默选最近轴向。零幅值、越界、缺少方向及不支持阶段不得伪装成有效校准，接触中不更新基线。

接入检查须覆盖同目标同 Z、目标语义、正反换算、阶段与越界，以及下笔、行笔、抬笔、转场的完整轨迹。A/B 专用入口与通用笔画执行器分开验收；模型及过程效果仍需独立实测，不能由软件检查替代。

## 验证顺序与待决策

1. 以合成单笔检查契约、时间语义和离线编译，再验证当前 +X、固定姿态、变磁目标的真机重复性。
2. 获取有来源的示教数据，对齐原始磁信号、基线、命令、几何和时间；区分实测标签与人工目标。
3. 扩展曲线和多方向执行，验证转折处时间与接触目标；再按证据决定动态姿态或方向性磁目标。
4. 设计图像/模板与模型生成评估，分别检查计划质量和实际墨迹；最终图像不能唯一恢复速度、接触或姿态。
5. 明确标定绑定、重算规则和训练标签用途后，裁定 `z_ff` 是否保存；接口变更须同步更新格式、生成器、编译器和测试。

## 代码入口与证据范围

| 用途 | 入口 |
|---|---|
| 目标契约 | [`src/brushbot/target_strokeplan.py`](../../src/brushbot/target_strokeplan.py) |
| 合成目标 | [`scripts/generate_strokeplan.py`](../../scripts/generate_strokeplan.py)、[`scripts/generate_strokeplan_suite.py`](../../scripts/generate_strokeplan_suite.py) |
| 前馈与编译 | [`src/brushbot/feedforward.py`](../../src/brushbot/feedforward.py)、[`src/brushbot/strokeplan_compile.py`](../../src/brushbot/strokeplan_compile.py) |
| 录制执行与 P 反馈 | [`scripts/run_strokeplan_experiment.py`](../../scripts/run_strokeplan_experiment.py)、[`src/brushbot/experiments/strokeplan_execution.py`](../../src/brushbot/experiments/strokeplan_execution.py)、[`src/brushbot/experiments/strokeplan_feedback.py`](../../src/brushbot/experiments/strokeplan_feedback.py) |
| 目标契约测试 | [`tests/test_target_strokeplan.py`](../../tests/test_target_strokeplan.py) |

其他名称中含 `strokeplan` 的实验脚本可能仍读取旧格式，不能仅凭文件名认定它使用现行契约。代码支持范围与真机验证结论应分别陈述。
