---
project: 02-strokeplan
status: active
---

# 用 JSON 调整参考笔画

## 用途与当前状态

这套配方用于先调出形态达标、可重复的参考笔画，再采集过程与成品配对记录。首批提供横、竖、撇、捺、横折五种独立笔画，每笔一份 JSON。修改配方并重新生成即可调整写法，无需为每次试写修改 Python。

配方是便于编辑的生成输入，现行 StrokePlan 仍为 V3 NPZ。生成器复用“中”字的局部圆滑连接、五次平滑磁目标插值，以及沿路径切线倾斜和时间规划。横、竖、横折参考“中”字工程试验中的参数安排；撇、捺的几何和磁目标为新设人工初值，尚无这两类笔画的实测依据。所有目标均标为 `synthetic`。

已完成离线生成、V3 重载校验与预览检查；尚未试写这五笔，也不声称已经得到理想墨迹。该工具用于参考样本准备，人工配方本身不作为论文提出的高质量生成方法。研究定位见[前置工作梳理](../08-system-evaluation/StrokePlan前置工作梳理.md)。

**当前五份配方和已有 NPZ 的磁目标沿用早期“中”字原始响应尺度，尚未转换到最新校准的公共 G 参考。** 用户要求后续采集必须接入最新方向校准，因此需要先显式迁移目标并适配接口：可重新设定校准尺度下的初值，或在支持范围内将旧目标经旧表转换为名义压深，再映射到 G。不能保持原数值只改名为校准目标；另存新配方、计划和参考标识，原文件保留。转换只能保留旧命令意图，不证明力、笔宽或墨迹相同。测量端校准与一张统一表的分工见[实验交付](../08-system-evaluation/实验清单.md#public-feedforward)。

## 配方与已有输出

| 笔画 | 可编辑配方 | 已生成的计划 | 初始安排 |
|---|---|---|---|
| 横 | [heng.json](../../configs/strokes/heng.json) | [StrokePlan](../../runs/brush2/plans/reference_strokes_json_v2/heng/strokeplan.npz) | 120 mm 直线，柔和起笔、行笔平台、尾段目标增加后回落。 |
| 竖 | [shu.json](../../configs/strokes/shu.json) | [StrokePlan](../../runs/brush2/plans/reference_strokes_json_v2/shu/strokeplan.npz) | 120 mm 直线，柔和起笔，后段逐步减小磁目标。 |
| 撇 | [pie.json](../../configs/strokes/pie.json) | [StrokePlan](../../runs/brush2/plans/reference_strokes_json_v2/pie/strokeplan.npz) | 向左下展开的三次 Bézier 曲线，后段目标下降。 |
| 捺 | [na.json](../../configs/strokes/na.json) | [StrokePlan](../../runs/brush2/plans/reference_strokes_json_v2/na/strokeplan.npz) | 向右下展开的三次 Bézier 曲线，后段峰值及局部降速。 |
| 横折 | [hengzhe.json](../../configs/strokes/hengzhe.json) | [StrokePlan](../../runs/brush2/plans/reference_strokes_json_v2/hengzhe/strokeplan.npz) | 100 mm 横接 80 mm 竖，转角圆滑连接、目标峰值及降速。 |

先看[五笔总览](../../runs/brush2/plans/reference_strokes_json_v2/overview.png)。总览画的是目标中心线与磁目标，不是笔宽预测或墨迹仿真。各笔目录还包含 `preview.png`、`target.csv`、`summary.json` 和生成时的 `recipe.json` 快照；`validation_preview/` 是额外的 V3 读回检查，使用实际 paper XY 坐标。

## JSON 字段怎么改

几何参数单位为 mm，速度为 mm/s，角度为度；输出 NPZ 的位置单位转换为 m、姿态转换为弧度。JSON 的 `schema_version: 1` 是配方版本，与 StrokePlan 的 `format_version: 3` 含义不同。

| 字段 | 控制什么 | 调整方式 |
|---|---|---|
| `id`、`name` | 输出目录名、中文笔画名。 | `id` 使用小写字母、数字和下划线，多个输入之间不能重复。 |
| `path.points_mm` | 局部中心线或 Bézier 控制点。 | 横、竖、横折的点为有序路径顶点；撇、捺四点依次为起点、两个切线控制点和终点。 |
| `path.corner_radius_mm` | 折角两侧最大裁切长度。 | 只用于 `rounded_polyline`；沿用“中”字二次曲线连接方式，并非精确圆弧半径。设为 0 保留折线，需要另行检查执行瞬态。 |
| `placement.scale` | 整体几何尺度。 | 大于 1 放大，小于 1 缩小；同时缩放路径和局部转角。不会自动改变磁目标值。 |
| `placement.origin_mm` | 局部原点在 paper 坐标中的位置。 | 改整笔放置位置，尚未加执行设置中的纸面原点偏移。 |
| `placement.rotation_deg` | 局部几何转到 paper 坐标的角度。 | 默认 180°，沿用当前“中”字观看方向：字右对应机械臂 −X，字上对应 −Y。设为 0 时对应 +X、+Y。 |
| `magnetic_target.knots_s_uT` | 在哪里安排多大的磁目标。 | 每项为 `[s, µT]`；位置从 0 严格递增到 1。数值表示磁响应，不能未经标定直接解释为力或笔宽。 |
| `magnetic_target.interpolation` | 控制点之间如何连接。 | 默认 `quintic`，每段采用五次平滑过渡，控制点处斜率为零；也支持 `linear`。 |
| `timing.speed_mm_s` | 整笔巡航速度上限。 | 默认 10；实际速度还受起停及几何、姿态变化限制。提高此值不表示执行和标定已支持该速度。 |
| `timing.speed_knots_s_mm_s` | 局部行程的速度上限。 | 每项为 `[s, mm/s]`，按行程线性插值，并与全局上限取较小值；所有设定值须大于 0，生成器另行处理起停。 |
| `timing.accel_mm_s2` | 时间规划中的切向加速度上限。 | 不等于完整轨迹已经通过机械臂加速度检查；转弯时还沿用原规划的曲率约束。 |
| `timing.angular_speed_deg_s`、`angular_accel_deg_s2` | 姿态时间规划的角速度、角加速度参数。 | 转角处可能进一步降速，采用原“中”字规划的保守比例；不是现场设备设置。 |
| `orientation.tilt_deg` | 沿平滑路径切线的笔杆倾角。 | 默认 15°，生成器允许 `(0, 30]`；改变后需复核对应标定条件。 |
| `orientation.smoothing_mm` | 用于求倾斜方位的切线平滑尺度。 | 默认 1 mm；它平滑姿态方向，不改变 XY 路径本身。 |
| `reference`、`description`、`notes` | 参数来源、写法意图及说明。 | 调试时更新依据，区分人工假设和实际观察。 |
| `filter_definition` | 磁目标采用的特征处理定义。 | 初值为 EMA、α=0.3；需与实际执行和标定保持一致。 |

`s` 是**归一化累计弧长**，不是时间比例。例如 120 mm 横的 `s=0.125` 位于下笔后约 15 mm；放大至 180 mm 后，同一 `s` 位于约 22.5 mm。若希望起笔过渡始终占 15 mm，应同步修改控制点位置。横折修改横竖长度后，也需要检查转角目标峰值和降速点是否仍对齐。

例如，横的这段配置：

```json
"magnetic_target": {
  "interpolation": "quintic",
  "knots_s_uT": [[0, 100], [0.125, 205], [0.35, 175], [0.72, 175], [0.88, 215], [1, 140]]
}
```

将 `[0.88, 215]` 改为 `[0.92, 200]`，表示把尾段磁目标峰值移到更后方并减小幅值；它不自动保证墨迹变细。若只想改变该段节拍，则修改 `speed_knots_s_mm_s`，不用改磁目标位置。

## 重新生成指令

在仓库根目录执行。输出必须是新目录；每次试写保留生成时的配方快照和计划，不覆盖上一轮文件。

一次生成五笔：

```bash
PYTHONPATH=src:. python3 scripts/generate_strokeplan_from_json.py \
  --config configs/strokes/heng.json configs/strokes/shu.json \
           configs/strokes/pie.json configs/strokes/na.json configs/strokes/hengzhe.json \
  --output-dir runs/brush2/plans/reference_strokes_json_v3
```

只重新生成修改后的横：

```bash
PYTHONPATH=src:. python3 scripts/generate_strokeplan_from_json.py \
  --config configs/strokes/heng.json \
  --output-dir runs/brush2/plans/heng_tuning_v1
```

默认生成 NPZ、配方快照、CSV、摘要和预览。`--no-preview` 可跳过图像。字段拼写错误、非法控制点、重复 ID 或已存在的输出目录都会报错，不会静默采用其他参数。

## 接下来如何使用

先调整横或竖，记录本次参数变动、实际墨迹和是否达到参考要求；达标后固定计划再做重复采集。初始几何全部位于同一个纸面区域，五笔是供分别调试的目标，不应直接连续叠写在同一位置。

本生成器仅输出目标，不负责下笔、抬笔和回程。这些仍由执行器的安装设置与进笔配置处理。常规单笔编译器目前支持 +X 固定姿态；已有“中”字实验另有方向姿态执行路径，但其跨方向共用旧前馈表的假设不能当作最新方向模型的验证。特别是撇、捺和横折的连续方向变化，不自动受到四个离散方向标定的完整支持。执行前需单独确认实际使用的前馈和对应入口。

## 实现入口

- [JSON 生成器](../../scripts/generate_strokeplan_from_json.py)：字段校验、路径生成、V3 保存和预览。
- [中字基础生成](../../scripts/generate_calligraphy_trial.py)：圆滑连接与五次磁目标插值。
- [中字方向姿态规划](../../scripts/generate_directional_character_trial.py)：复用的切线倾斜和时间规划；原默认参数保留。
- [V3 契约](strokeplan.md)：目标数据与执行设置、标定和实测记录的边界。
