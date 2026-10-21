---
project: 07-image-to-strokeplan-baseline
status: active
---

# 整字图片到 XY 几何路径

## 目标与范围

将裁好的一张汉字图片转换为可复核的整字几何、节点和路径段，为后续 StrokePlan 生成提供输入。当前先解决 XY 提取与结果检查，之后再关联磁响应。

当前产物是**无笔顺的图像几何路径图**。交叉处的连接、闭环、分离部件和点状部分均保留；路径编号表示数据定位，不表示第几笔或真实书写方向。不会补造磁目标、时间或机器人 Z，也不将几何文件包装成 StrokePlan V3。

输入默认为清晰、单字裁图；无需识别字名。复杂背景可选反色、阈值或局部阈值，并保存处理结果。自动缩小大图后，坐标仍可反算到纠正 EXIF 朝向后的原图。单张成品不能唯一给出交叉处笔顺、回锋或重复覆盖，这些在后续人工／模板适配中处理。

## 方案选择

| 方案 | 用途与取舍 |
|---|---|
| 整体骨架图片 | 可预览字形，但没有可关联磁响应的路径结构。 |
| 骨架图＋节点与路径段 | 本项目采用；保留拓扑及歧义，能够导出坐标、编号、弧长和可复核中间结果。 |
| 直接推断有笔顺的整字计划 | 需要额外笔法、分笔及运动依据，留到 XY 稳定后的阶段。 |

## 处理链路

1. **图像准备**：读取单帧图片，纠正 EXIF，透明背景合成到白色；可裁 ROI，并按明确比例缩小。保存原始字节和处理尺寸。
2. **墨迹分割**：Otsu、固定阈值或局部阈值，支持亮字深底；记录小分量删除，不自动连补断笔。
3. **骨架与拓扑**：复用单笔工具的细化和像素图基础。保留所有达到面积条件的分量。相邻分叉像素归为节点区域，区域内边单独记录，区域外按度为 2 的链追踪。
4. **路径与点状部分**：分离端点—节点路径、闭环和孤立点。遍历检查所有骨架边，保留原始有序像素；普通链采用可关闭的 0.75 px 折线简化，组成环路的路径保留原始几何，避免多段环退化成重合弦线。
5. **坐标与弧长**：默认输出原图尺度的笛卡尔像素 XY；明确指定整图宽度／mm/px 后输出 paper mm。每条路径记录累计弧长与归一化 `s`。
6. **复核与输出**：原图、分割、骨架、XY 路径总览及浏览器交互报告，支持路径选择、显示开关与缩放；数据导出 JSON、CSV 和 NumPy NPZ。

节点区域是图像的连接区域，不声称等于真实笔锋状态。路径在区域边界处连接同一逻辑节点；不为满足几何拼接而生成不存在的内部动作。

## 几何数据与后续磁响应接口

每次提取具有 `geometry_id`，由源图片、处理参数和提取结果共同确定；同一输入和参数产生相同 ID。每条路径具有本结果内确定的 `path_id`。参数、坐标变换或路径几何改变后，生成新的几何标识，防止旧磁响应挂到新路径上。

后续关联键为：

```text
(geometry_id, path_id, s) -> 对应 XY 和有来源的磁响应
```

`s` 是 `geometry.json`、`paths.csv` 和 `xy_paths.npz` 中**规范路径**的累计行程比例；还没有笔顺或时序含义。`raw_paths.csv` 另用 `raw_s` 和 `raw_arc_length` 表示原始像素阶梯路径的弧长，仅用于诊断，不能混作上述关联键。关联实测信号时须另加采集来源和时间／空间对齐，不能由图片补出实测磁响应。

输出角色明确为 `character_xy_geometry`，包括：

- 源图哈希、处理参数、坐标单位和变换；
- 连通部分、节点区域、点状部分；
- 路径 ID、端部节点、是否闭环、XY、原图像素、累计弧长及 `s`；
- 追踪边数、节点区域内部边数、未覆盖边数和需复核标记；
- 原始骨架路径及文件哈希，保留生成依据。

## 验证要求

- 十字、T 形、闭环、多个分离部件、孤立点和相邻分叉区域，都能保留且覆盖所有有效骨架边；不把分支自动命名为笔画。
- 相同输入重复运行的几何 ID、路径编号与坐标一致；尺度／阈值改变能使版本标识变化。
- 大图缩小、ROI、EXIF、反色、透明背景和单位变换可追溯，空白与非法参数明确报错。
- 现有单笔提取与离线比较保持行为兼容。
- 以真实字库整字轮廓做离线示例并目视检查。字体示例不能证明任意书法照片、自动笔顺或真机效果。

## 命令行使用

在仓库根目录运行，依赖现有 NumPy、Pillow、Matplotlib，无需训练模型或联网：

```bash
PYTHONPATH=src:. python scripts/extract_character_xy.py \
  --image /path/to/character.png \
  --output-dir outputs/character_xy/my_character_v1
```

打开输出中的 `report.html`。左侧叠加原图与路径，右侧显示 XY；可点击路径编号、开关图层、滚轮缩放、拖动平移、复位视图，并通过滑块检查 `s` 对应的 XY。HTML 内嵌图片与数据，复制单个 HTML 文件也可离线查看。`preview.png` 用于快速总览。

有明确整图物理宽度时：

```bash
PYTHONPATH=src:. python scripts/extract_character_xy.py \
  --image /path/to/character.png --image-width-mm 100 \
  --origin-xy 140 0 --rotation-deg 0 \
  --output-dir outputs/character_xy/my_character_mm_v1
```

`--image-width-mm` 指纠正 EXIF 后**整幅原图含留白**的宽度，不是墨迹宽度或 ROI 宽度。也可用 `--mm-per-pixel`，两者互斥。未提供比例时单位为原图 `px`，不会默认为 mm。

坐标先以原图中心 `((width−1)/2, (height−1)/2)` 为原点，转换为 X 向右、Y 向上，再缩放、逆时针旋转和平移。`--origin-px U V` 可指定原图中的原点，`--origin-xy X Y` 的单位与输出一致。ROI 和缩小不会重新定义原点或物理比例；本工具未做照片透视矫正，斜拍应先校正。

| 参数 | 用途与默认值 |
|---|---|
| `--crop LEFT TOP RIGHT BOTTOM` | EXIF 校正后原图的整数 ROI，右／下边界不包含；默认整图。 |
| `--threshold 0..254` | 固定暗前景阈值；默认 Otsu。 |
| `--adaptive` | 光照不均时使用局部高斯阈值，与固定阈值互斥。 |
| `--adaptive-window` / `--adaptive-offset` | 默认 31 / 10；窗口须为 3..501 的奇数。 |
| `--invert` | 亮字深底时反色。 |
| `--min-component-pixels` | 缩小后墨迹分量最小面积，默认 8；保留极小点可设 1。 |
| `--simplify-px` | 处理后图像的 RDP 容差，默认 0.75；0 保留像素路径；环路路径始终保留原始几何。 |
| `--max-side-px` | 默认最长边 1400，可设 64..4096；处理总面积另限 200 万像素。 |
| `--source-url` | 只记录来源文字，不下载图片。 |

原图不超过 4000 万像素，必须是单帧图片；骨架最多 10 万像素，简化普通链最多 2 万点。空白、非法参数、没有保留前景等情况报错。输出目录必须是新路径，重复运行请使用新目录；先在临时目录完成导出和渲染，再发布文件，清单最后写入，失败时回滚本次目录。

## 输出文件与接口

| 文件 | 内容 |
|---|---|
| `geometry.json` | 完整几何、源图哈希、处理参数、单位、变换、节点区域、路径、统计与复核标记。 |
| `paths.csv` | 规范路径逐点：`path_id, point_index, u_px, v_px, x, y, arc_length, s`。 |
| `raw_paths.csv` | 未简化的有序骨架，末两列为 `raw_arc_length, raw_s`。 |
| `nodes.csv` | 节点代表点、类型、连通部分及原图像素／XY；完整节点区域在 JSON。 |
| `xy_paths.npz` | 无 pickle 的拼接数组，含 `xy, original_pixel_xy, s, arc_length, offsets, path_ids`，另存几何 ID、单位和角色；第 i 段为 `[offsets[i]:offsets[i+1]]`。 |
| `image.png` / `mask.png` / `skeleton.png` | 处理后的原图、二值墨迹、原始骨架；各自使用同一处理图像坐标。 |
| `source_image.bin` | 输入图片原始字节，保留 EXIF 等来源依据。 |
| `report.html` / `preview.png` | 交互复核与静态总览。 |
| `manifest.json` | 角色、版本、几何 ID、文件 SHA-256 与摘要；加载时验证全部文件。 |

CSV 的 `u_px, v_px` 始终是纠正 EXIF 后的原图像素中心；`x, y, arc_length` 使用根数据的 `units`。点状部分只在节点中，不伪装为零长度路径；只有点的输入同样能生成报告及空路径数组。

```python
from brushbot.character_xy import extract_character, load_geometry, sample_path

extract_character("character.png", "outputs/character_xy/run_v1")
geometry = load_geometry("outputs/character_xy/run_v1")  # 检查文件哈希及几何 ID
path_id = geometry["paths"][0]["id"]  # 仅在存在曲线路径时
xy = sample_path(geometry, path_id, [0.0, 0.5, 1.0])
attachment_key = (geometry["geometry_id"], path_id, 0.5)
```

无需输出文件时可调用 `analyze_character(...)`，返回 `geometry`、原始像素路径、预处理图、掩膜和骨架等。导出接口与其接收相同的处理／坐标选项。`sample_path` 支持标量或数组，拒绝不存在的路径、非有限值或超出 `[0,1]` 的位置。后续修改几何应重新提取并使用新的 `geometry_id`。

## 如何检查结果

先核对分割是否包含所有部件，再检查骨架是否沿墨迹内部延伸，最后检查 XY 与叠加位置。遇到细小点画消失，先看“小分量删除”标记和面积阈值；遇到笔锋尖角产生短分支，先保留它们作为原始证据，后续再显式决定是否合并／裁除。此版没有自动修复断笔、裁短枝或推断交叉处的连续笔画。

`coverage.total_edges = traced_edges + junction_internal_edges` 且 `untraced_edges = 0`，表示**原始骨架图**的边已全部计入，不表示提取质量或与原图相似度达标。路径简化可能改变局部曲线；通过节点多重图找桥，所有属于环路的路径标记 `in_graph_cycle` 并保留原始像素几何，避免环路被压成重合直线。`statistics.loop_count` 是返回同一节点的路径段数，`cycle_rank` 是整个像素图的独立环数 `E−V+C`，因此多个路径围成的环也能记录。节点区域内部的环仍属于节点区域，不补造对应运动。

骨架是墨迹几何中轴的离散近似；宽笔画、交叠、回锋和重描可能产生额外枝杈，不能直接当作毛笔真实轨迹。纹理背景、印章、相邻字、严重模糊或透视变形需要先整理输入。当前不提供未经标注验证的质量分数，也不承诺任意图片都能稳定恢复笔法。

## 可复现示例

使用仓库已有 `data/makemeahanzi/graphics.txt`，把每个字的全部轮廓渲染为一张图片，再交给通用提取核心；提取不读取字库中心线或笔顺：

```bash
PYTHONPATH=src:. python scripts/generate_character_xy_examples.py \
  --characters 字中永人口 \
  --output-dir outputs/character_xy/my_examples_v1
```

打开批次目录的 `index.html` 查看五个字，每个字均保存输入图片、轮廓来源及独立数据束。示例脚本逐字生成；若某字失败，已完成字的结果保留供诊断，重跑使用新批次目录。全部运行产物位于本地忽略目录 `outputs/character_xy/`，不存入 docs 资源目录。

## 当前阶段与下一步

共享图像基础、拓扑追踪、坐标转换、版本化数据束、命令行和 HTML 复核已实现。测试包含手工拓扑、坐标映射、透明／反色／EXIF、局部阈值、环路退化保护、孤点回退、文件损坏与已有输出保护，并保持既有单笔比较工具兼容。

2026-10-15 验证：新增 38 项测试通过；五个字的数据束均通过加载校验，报告的选择、图层、采样、缩放、拖动、复位及窄屏布局经 Chrome 实测。全仓首次常规入口在 Monitor 窗口创建处发生 Qt 原生段错误；窗口测试单独 7 项通过，与新增测试合跑 45 项通过。全仓采用下述入口保持单个 QApplication 存活至测试结束，结果为 **1073 passed, 7 skipped**，未修改 Monitor 代码：

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python - <<'PY'
from PyQt5.QtWidgets import QApplication
import pytest
qt_application = QApplication.instance() or QApplication([])
raise SystemExit(pytest.main(['-q', '-o', 'addopts=', '-p', 'no:cacheprovider']))
PY
```

下一步先积累你实际使用的字图并人工复核，再增加可记录的分支选择／笔画连接。磁响应作为有来源的独立附加数据挂到已确认的几何版本；之后才装配笔顺、时间、姿态和 StrokePlan。
