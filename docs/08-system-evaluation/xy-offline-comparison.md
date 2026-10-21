---
project: 08-system-evaluation
status: active
---

# StrokePlan XY 离线比较

## 用途

把单笔图片提取为可复核的有序几何参照，再在同一固定坐标系下比较一个或多个 StrokePlan V3 的 XY。人工 JSON 配方和后续阶段模板生成器共用同一参照与评价规则。

入口为 [`scripts/compare_strokeplan_xy.py`](../../scripts/compare_strokeplan_xy.py)，依赖现有 NumPy、Pillow 和 Matplotlib。程序只离线读取图片和 V3 目标文件。

图片骨架是墨迹的几何表示，不是实测笔尖或 TCP 路径。报告不评价磁目标、节拍、停顿时长、真实墨迹宽度或机器人执行效果，也不给出自动达标结论。相同 XY、不同磁目标或时间的计划具有相同几何评分。

## 第一步：提取并检查参照

先把网络图片保存到本地，裁出一条连续笔画。支持 Pillow 可读的单帧图片；透明背景按白色合成，EXIF 朝向先纠正。图片最多 2,000,000 像素。默认以暗色为前景，使用 Otsu 阈值和 Zhang–Suen 细化。

```bash
PYTHONPATH=src python3 scripts/compare_strokeplan_xy.py extract \
  --image /path/to/single_stroke.png \
  --image-width-mm 138 \
  --origin-mm 140 0 --rotation-deg 180 \
  --source-url 'https://example.org/source-page' \
  --output-dir outputs/xy_comparison/reference_v1
```

`--source-url` 仅记录来源，不下载网页。所有输出使用新目录，已有目录会被拒绝。

### 坐标与尺度

`--image-width-mm` 指**整张图片**的宽度，包括留白。也可以改用 `--mm-per-pixel`，两者只能选一个。无实际尺寸的网络图片使用人为指定的比较尺度；报告中的 mm 不因此成为图片原物的实测尺寸。

图片像素 `(u,v)` 的 u 向右、v 向下。变换先扣除 `origin_px`、翻转 v 轴，再按 mm/px 缩放、旋转并平移到 `origin_mm`：

```text
paper_xy = R(rotation_deg) × [(u-u0), -(v-v0)] × mm_per_pixel + origin_mm
```

`--origin-px` 默认为纠正 EXIF 后的图片中心 `((width-1)/2,(height-1)/2)`；`--origin-mm` 默认 `(0,0)`，`--rotation-deg` 默认 0。上例的 180° 与现有 JSON 配方的放置方向对应，不能作为所有图片的默认朝向。

先确定一次变换，再对所有生成路线共用。比较器直接使用计划中的 paper XY，不自动配准、缩放或反转。base 坐标计划须先明确转换，不能直接混用。

### 提取复核与歧义

打开 `reference_preview.png`，检查原图、分割及骨架、选择后的路径和起终点：

- 默认删除面积小于 8 像素的连通分量，删除量进入报告；可用 `--min-component-pixels` 修改。
- 清理后有多个分量时，输出 `needs_review` 诊断，不静默选择最大分量。可以进一步裁图，或显式指定 `--component-index`；索引从 0 开始，按面积递减排序，省略面积会记录。
- 骨架存在分叉或闭环时，输出 `needs_review`，不自动选主路径。根据预览显式指定两个端点，重新输出到新目录。
- 未指定端点的无分叉路径，采用横向从左到右、纵向从上到下的几何方向假设；这不是从图片识别出了真实笔顺。可用 `--reverse` 明确反向。

例如用像素端点标注一条横画：

```bash
PYTHONPATH=src python3 scripts/compare_strokeplan_xy.py extract \
  --image /path/to/single_stroke.png --image-width-mm 138 \
  --origin-mm 140 0 --rotation-deg 180 \
  --start-px 57 309 --end-px 544 301 \
  --output-dir outputs/xy_comparison/reference_v2
```

端点会吸附到 5 像素以内的骨架节点。两端点间选取骨架最短路，省略的骨架像素数单独记录；它仍需复核，不能因此声称恢复了真实运笔。亮色笔画／深色背景可使用 `--invert`，手动阈值使用 `--threshold 0..254`，阈值作用于可选反色后的亮度。

逐像素路径的阶梯会使累计弧长偏大，因此默认用 **0.75 px** 容差进行 Ramer–Douglas–Peucker 折线简化；该容差会写入参照和报告，所有候选共用。`reference.csv` 是比较用曲线，`skeleton_path.csv` 保留简化前的完整有序骨架。`--simplify-px 0` 可关闭简化。容差由像素尺度决定，不表示已经验证了对应精度。

命令返回 0 表示有可比较路径；返回 2 且 stdout 中 `status: needs_review` 表示只生成了诊断，不能进入比较。空白、无对比度、非法参数等也会报错，但不会生成伪造路径。

## 第二步：比较多个计划

```bash
PYTHONPATH=src python3 scripts/compare_strokeplan_xy.py compare \
  --reference-dir outputs/xy_comparison/reference_v2 \
  --plan JSON=runs/brush2/plans/reference_strokes_json_v2/heng/strokeplan.npz \
  --plan phase=/path/to/phase_plan.npz \
  --stroke-index 0 --samples 501 \
  --reference-reviewed \
  --output-dir outputs/xy_comparison/comparison_v1
```

每个 `--plan` 使用 `名称=路径`；支持 1–8 个不同名称。`phase` 路径只是调用示例，工具不自行实现阶段模板生成。多笔计划只评价指定索引的那一笔，`--stroke-index` 从 0 开始并应用于每个候选。未选笔画不计入本次结果。

`--reference-reviewed` 记录调用者已经检查提取与方向，不执行自动审核；不传时仍能比较，但报告明确标为未确认复核。所有计划和参照验证完毕后才创建比较目录。

## 输出与指标

`overview.png` 包含原图、参考路径、固定坐标叠加和沿程误差四联图。叠加图始终绘制原始路径顶点，不随指标采样数减少而删除折点。`report.html` 包含内嵌图片、指标表和解释范围，可直接用浏览器打开；`report.json`、`metrics.csv` 和逐候选 CSV 供进一步分析。

| 指标 | 含义 |
|---|---|
| `bidirectional_mean_distance_mm` | 两条路径各按累计弧长均匀采样，计算到对方原始折线段的最近距离，再对两个方向等权平均。 |
| `bidirectional_p95_distance_mm` | 上述采样距离的 95 分位；不是精确 Hausdorff 距离。 |
| `vertex_max_distance_mm` | 双向原始顶点到对方折线的最大距离，帮助发现稀疏均匀采样漏掉的折点偏离。它也不是连续曲线的精确最大距离。 |
| `ordered_mean_distance_mm` / `ordered_p95_distance_mm` | 按归一化累计行程配对后的欧氏误差；与时间配对不同。 |
| `start_error_mm` / `end_error_mm` | 保留指定方向的起终点误差。 |
| `length_error_mm` / `length_ratio` | 计划与参考的总行程差、计划长度／参考长度；重复走线保留在累计行程中。 |

默认每条路径均匀取 501 点，可设为 2–10,000；较复杂曲线应采用足够采样并检查原图，不能只看均值。最近距离对反向和重复走线不敏感，必须结合有序误差、端点及长度阅读。静止的重复 XY 点只在几何计算中去重，不修改原始计划，停顿时长不计分。

参照保存原始图片字节、解码图片、mask、骨架、参考 CSV、预览及处理参数；比较包保存经过校验的参照快照和候选 NPZ。文件 SHA256、像素到 mm 的变换一致性和重复来源哈希会复核，原始外部文件移动后仍可使用冻结参照。

## 对照和证据边界

同一份参考用于两条生成路线；对齐、采样数和端点规则保持一致。若生成器直接复制该参考骨架，再与同一骨架比较，低误差主要说明拟合／重采样正确，不能独立证明泛化。生成规则使用未参与调参的目标验证，并保存人工标注和来源关系。

起笔、回锋、转折等动作可能有意偏离墨迹骨架。本工具先画出完整所选笔画并报告几何差异；不会根据评分好坏自动删除阶段。需要阶段评价时，另行预先固定阶段参照和对应规则。

本地示例保存在 `outputs/xy_comparison/examples_20261015/`：将 Make Me a Hanzi 的横、撇逐笔轮廓栅格化，与既有 JSON 配方及字库中线基线比较。字库中线基线不是所提议的阶段生成方法；其磁目标仅为 V3 几何示例占位，不用于执行。字体图片也不代替真实书法照片或真实运动参照。

## 实现与验证

- [`geometry.py`](../../src/brushbot/xy_comparison/geometry.py)：弧长采样、双向折线距离、有序误差及长度。
- [`image_reference.py`](../../src/brushbot/xy_comparison/image_reference.py)：分割、细化、显式路径选择和冻结参照。
- [`report.py`](../../src/brushbot/xy_comparison/report.py)：V3 输入校验、四联图及可携带报告。
- `tests/test_xy_comparison.py`、`tests/test_xy_image_reference.py`、`tests/test_xy_comparison_cli.py`：已知偏移、反向、重复覆盖、分叉、透明背景、来源一致性和完整 CLI 等验证。

```bash
PYTHONPATH=src:. python3 -m pytest tests/test_xy_comparison.py \
  tests/test_xy_image_reference.py tests/test_xy_comparison_cli.py
python scripts/check_docs_layout.py
```
