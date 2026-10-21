---
project: 07-image-to-strokeplan-baseline
status: active
---

# 分段笔画模板：设计与使用边界

## 目标与依据

实现可复核的离线模板建立、人工修正和整字 XY 适配。当前笔画库按参考教程覆盖 28 类基本笔画、38 套写法候选，其中 27 套已换为原图引导线追踪、11 套保留规则候选；“永”已使用五个新模板合成，历史五笔试点、横/竖模板和永字字体原型继续保留。规则重建检查页支持事件、相对宽度和主体长度对照，追踪检查页支持原图/原始点列叠加与头尾放大；已有整字结果使用局部 XY 快速修正页。磁响应只保留有版本的关联接口，不补造时间、磁目标或真机结果。

参考 Zhang et al., *Intelligent Chinese calligraphy beautification from handwritten characters for robotic writing*, The Visual Computer 35 (2019), DOI [10.1007/s00371-019-01675-w](https://doi.org/10.1007/s00371-019-01675-w)，§4.1、§5.1、§7.1。借鉴局部特征段和柔性主体分开处理；该论文直接记录分笔输入，本项目另以字库先验和人工修正处理图片分笔。下述算法和界面是本项目的实现设计，不是原论文复现或已验证性能。

## 范围与成功条件

- 输入清晰单字图片、字名、可修正的有向笔画候选和模板；图片坐标为纠正 EXIF 后原图的笛卡尔像素。
- 字库仅给结构和有向中线先验；候选生成明确记录先验来源，不宣称由图片自动恢复真实笔顺。
- 每笔具有起笔、行笔、收笔三阶段；四个锚点为首点、主体起点、主体终点、末点。
- 模板使用主体坐标系、参考宽度单位、局部有向折线与分段描述。单主体模型要求主轴投影单调；横折钩、横撇改用显式折/钩锚点的分段模型，不把复合笔画强压成一条单调曲线。
- 主体沿主轴改变跨度，横向保留局部形状并允许一个受限的平滑弯曲参数。头尾按宽度尺度作相似变换，随主体端部切线的变化旋转，保留参考路径原有连接角；原先平顺的边界保持相切，有意折转不强制拉平。报告原始/生成连接角及变化；不任意拉长局部特征段。
- 宽度来自法线扫描或明确的人工宽度提示；接触图像边界、路径不在墨迹内、多笔交叠时不当成可靠宽度。
- 配置允许范围与样本实际覆盖范围分别记录；超配置范围拒绝，超样本范围提示。几何适配不证明物理宽度或磁响应迁移。
- 输出同框对照统一缩放基线、几何指标、阶段映射、版本与交互 HTML。缺模板的笔画逐笔报告，不静默跳过，也不标整字完成。
- 图像参考、候选路径、命令计划与实测轨迹语义分开。只有 XY 的输出不包装为 StrokePlan V3。

## 数据与接口

1. 可编辑 annotation：图片 SHA-256、原图尺寸、字名、笔画列表；每笔包含类型/变体、XY、四个锚点、人工复核状态、可选宽度提示和来源。编辑后重新生成 annotation_id。
2. 不可变 template：类型/变体/风格、参考样本、归一化原型、分段特征、设计范围、样本覆盖、证据级别和 template_id；加载时验证内容标识。
3. 不可变 fitted geometry：绑定图片、annotation_id、template_id，逐笔保存 proposed/baseline XY、弧长 s、phase_id、阶段内弧长 u、拟合参数、指标和限制。输出单位默认 px，提供整图物理宽度后为 mm。
4. 后续动态关联必须增加 run_id、原始时间、命令/实测角色、校准参考和特征/滤波定义。此版 u 明确是阶段内行程，不代表时间；停顿阶段由后续时间层表达。

所有资源保存到新输出目录；清单最后发布、已有目录拒绝、失败回滚。HTML 内嵌数据，可离线打开。快速页直接编辑生成 XY，可直接保存修正 JSON/CSV；高级标注页修改的是输入先验，仍需重新拟合并隐藏旧指标。

## 验证与证据

单元测试使用可手算的分段路径验证头尾长度保持、主体伸缩、切线连接、相位/弧长、宽度遮挡、越界拒绝和版本绑定。CLI 使用真实子进程验证建模、修正、拟合、尺度和输出保护。

自带示例使用本地 Make Me a Hanzi 字库，只作为工程夹具；横/竖模板与保留字符分开，并记录按字划分。模板与评价参考来自字体先验，报告明确不独立、不支持书法质量结论。真实字帖需经人工分笔和阶段标注后加入；保留字不得参与调参。先估计重复标注差异，再固定容差并运行独立测试，不内置未经论证的合格阈值。

后续磁响应阶段复用用户已完成的方向校准，显式适配软件特征契约；在固定条件下进行长度/接触目标对照和重复试写，保留实际墨迹、原始磁信号及时间，不把测量曲线自动当作标准目标。

## 已实现的入口

脚本为 [`scripts/stroke_templates.py`](../../scripts/stroke_templates.py)，核心位于 [`src/brushbot/stroke_templates/`](../../src/brushbot/stroke_templates/)。教学图缓存在本机后全部离线运行，无新产品依赖。自带数据分别标记教学规则重建、字体或解析几何原型，不能替代实测书写参考。

**固定首页：[笔画与字的资料库](../../outputs/stroke_templates/index.html)。** 第一个页签“笔画库”默认打开，按横、竖、撇、捺、点、提及后续折钩从基础到复合展示；第二个页签“字库”浏览原图、彩色 XY、复核状态，点击进入已有修正页。默认各类最新版本，可搜索并切换全部版本；相同内容的副本合并显示。同一类型/写法/风格内部按清单修改时间选最新，复制后重置时间可能改变版本选择。笔画缩略图保留代表参考的原方向，同一类型先除以各自参考宽度再使用共同显示尺度；搜索单条写法也保留这一比例。该比例用于比较几何形状，不表示不同原图具有相同的物理尺寸。

有教学模板时，“笔画库”的来源默认选“新库 · 教学图与规则”。卡片分别标明“原图引导线追踪”或“规则重建候选（保留）”，并汇总最新教学写法中的两类数量。选择“全部来源（含旧库）”可查看字体和解析几何历史模板；版本开关仍独立控制是否显示同一类型/写法/风格的旧版本。

有合成字时，“字库”的来源默认选“模板合成字”，当前按“心 → 永 → 好 → 我 → 建”显示五字练习集，并标明练习编号、实际写法和覆盖类型数。选择“全部资料（含旧测试）”可浏览历史字体与解析样例；原文件没有删除。没有合成结果的资料库仍默认显示全部资料。来源筛选先于最新版本选择，历史字体结果不会遮住已有合成字。

根目录可选的 `catalog_settings.json` 只规定练习顺序，不限制收录范围；后续新增合成字会继续出现。当前设置为 `{"schema_version":1,"role":"stroke_template_catalog_settings","character_order":["心","永","好","我","建"]}`。未列出的字按其最新版本的笔画数和字名排列，同字各版本保留最新优先。重复字、多字字符串等错误设置会拒绝刷新，并保留原首页。

首页递归收录目录内完整发布且校验通过的模板、整字结果和标注草稿；已有批次不搬动。建议后续使用以下结构，每个版本都是独立数据包：

```text
outputs/stroke_templates/
├── index.html
├── strokes/<类型>/<写法>/<版本>/
└── characters/<字名>/<版本>/
```

CLI 的 prepare/build/fit/demo/yong/teaching/trace-guides/import-guides/compose 在默认资料库目录下成功生成后会自动刷新首页。自定义资料库时增加 `--catalog-root /path/to/library`，输出必须在该根目录下的独立子目录。手动复制完整数据包、删除数据包或直接调用 Python 核心后，运行：

```bash
PYTHONPATH=src:. python scripts/stroke_templates.py catalog
# 自定义位置：追加 --root /path/to/library
```

此命令只刷新自己管理的首页，不改已有数据包；拒绝覆盖已发布包内的页面或用户原有 index.html。损坏包会列出未收录原因，隐藏的临时目录不展示。仅放入图片尚不能自动获得 XY；仍需先 prepare/fit。下载到其他位置的修正 JSON 也不会自动改变原数据包或首页的复核状态。

### 原图引导线入库：长横、短横

首页当前选用[长横](../../outputs/stroke_templates/strokes/sohu_heng_20261017_final/templates/heng_long/report.html)、[短横](../../outputs/stroke_templates/strokes/sohu_heng_20261017_final/templates/heng_short/report.html)的新模型，沿用 `heng/long`、`heng/short` 和 `kai_teaching_rules_v1` 分组，原始规则版本仍可勾选“全部版本”查看。其余写法的当前覆盖见下面的批量更新记录。新模型能直接加载到既有几何适配器，不只是一张对照图。

来源为[欧楷笔画详解，动态图演示，基本笔画字例](https://www.sohu.com/a/291748478_183308)第一组长横、短横教学图。已有[追踪核对批次](../../outputs/stroke_templates/source_reviews/sohu_heng_20261017_v1/index.html)冻结了两张完整原图、有序追踪点及清单；该历史核对页描述的是入库前的候选。程序校验清单与原图 SHA-256、原图尺寸、图像左上坐标到笛卡尔坐标的翻转关系、阶段索引与裁剪框，再分别对起/行/收三段做 0.75 px 容差的折线简化。四个阶段边界和首末点保持原位；长横 471→46 点，短横 238→25 点。最大原始点到对应阶段折线距离分别约 0.750 / 0.728 px，这只衡量简化误差，不是追踪准确率。

每个模板保存 `source.jpg`、完整 `raw_trace.json`、`template.json`、带笔画名称的 `heng_long_xy.csv` / `heng_short_xy.csv` 和自包含 `report.html`。详情页叠加的是实际入库路径，可开关原图/原始追踪线、查看完整教学图、放大头尾、沿弧长移动标记并下载数据。CSV 的 `x_px/y_px` 采用原图左下原点、Y 向上；`x_reference_width/y_reference_width` 对应主体坐标系中的归一化原型。`s` 为整笔弧长进度，`phase_u` 为阶段内弧长进度，均不是时间。

白色引导线会破坏墨迹连通性，因此以灰度 <100 的轮廓作 9 px 闭运算填补白线，再沿主体法线扫描，取有效样本宽度中位数作为几何归一化候选：长横 29.5 px、短横 47.5 px。该估计明确记录处理参数，不生成相对宽度意图、压力或磁目标；模板的 `width_profiles` 留空。两张图没有共同的物理尺度，不能从像素宽度推断实际笔宽关系。路径、阶段解释和宽度估计仍待人工检查，证据保持 `teaching_rule_candidate`、`physical_validation=false`。

重建这个已冻结的两笔批次：

```bash
PYTHONPATH=src:. python scripts/stroke_templates.py import-guides \
  --review-dir outputs/stroke_templates/source_reviews/sohu_heng_20261017_v1 \
  --output-dir outputs/stroke_templates/strokes/sohu_heng_my_v1
```

`import-guides` 同时支持这个历史长短横格式和显式 type/variant 的批量格式；其他笔画需先用 `trace-guides` 根据已校验原图、有向种子、阶段和转折标注建立追踪包。它不自动识别任意教程图的笔顺或阶段。新批次先完整校验再发布，原目录拒绝覆盖。

### 按教程引导线逐类更新（当前版本）

[本轮 25 套入库批次](../../outputs/stroke_templates/strokes/sohu_basics_20261017_v1/report.html)沿用同一搜狐教程，覆盖竖的两种长写法、四种撇、两种捺、三种点、提和清晰对应的折钩组合。加上长横、短横，当前 38 套最新写法中有 **27 套引导线候选、11 套保留规则候选**。保留项是短竖、长点、竖弯、横折提、横折弯、横折弯钩、竖折撇、竖折折钩、横折折撇、横撇弯钩、横折折折钩：本轮没有选定足够清晰且对应同一写法的引导线，不自动替换为别种笔画。

可重建的人工有向种子、ROI、起行收分界及折/钩标签保存在 [`sohu_guides_v1.json`](../../configs/stroke_templates/sohu_guides_v1.json)，25 张来源缓存位于 `reference/stroke_teaching_sohu_v1/`。程序核验 SHA-256 后，将种子吸附到 9 px 内的白线像素，在相邻种子弦周围 10 px 通道中按白线优先追踪，再分别保护阶段边界和每个命名转折点简化。箭头支线依靠人工顺序消歧；仍需核对人工种子是否代表教程本意。部分引导线先于轮廓尖端结束，保留可见线端，不自动补画真实笔尖运动。

18 套黑色墨迹图采用闭运算后法线扫描的标称参考宽度；7 套灰底轮廓图明确使用人工外轮廓宽度提示及坐标依据，不把白色引导线粗细当笔宽。两者仅用于归一化和形变尺度，`width_profiles` 均留空。每页“宽度依据”分别说明来源；原图、完整追踪、简化模板和 CSV 一起发布。

```bash
PYTHONPATH=src:. python scripts/stroke_templates.py trace-guides \
  --specs configs/stroke_templates/sohu_guides_v1.json \
  --source-dir reference/stroke_teaching_sohu_v1 \
  --output-dir outputs/stroke_templates/source_reviews/sohu_my_v1

PYTHONPATH=src:. python scripts/stroke_templates.py import-guides \
  --review-dir outputs/stroke_templates/source_reviews/sohu_my_v1 \
  --output-dir outputs/stroke_templates/strokes/sohu_my_v1
```

### 五字练习集（2026-10-19）

固定首页进入“字库”即可依次检查以下五字。保留现有“永”v2，新四字均使用当前笔画库的精确模板版本合成，没有覆盖旧字或重建笔画模板。

| 顺序 | 字／快速修正页 | 笔画数 | 主要检查内容 |
|---|---|---:|---|
| 1 | [心](../../outputs/stroke_templates/characters/xin_composed_20261019_v1/fit/review.html) | 4 | 左点、右点、卧钩，重复使用同一右点模板。 |
| 2 | [永](../../outputs/stroke_templates/characters/yong_composed_20261017_v2/fit/review.html) | 5 | 横折钩、横撇、斜撇、斜捺及原有布局适配。 |
| 3 | [好](../../outputs/stroke_templates/characters/hao_composed_20261019_v1/fit/review.html) | 6 | 撇点、提、竖钩及女旁与子旁的组合。 |
| 4 | [我](../../outputs/stroke_templates/characters/wo_composed_20261019_v1/fit/review.html) | 7 | 短撇平势、斜钩、多笔交叉。 |
| 5 | [建](../../outputs/stroke_templates/characters/jian_composed_20261019_v1/fit/review.html) | 8 | 横折、悬针竖、横折折撇、平捺及多次折转。 |

合计覆盖横、竖、撇、捺、点、提、竖钩、斜钩、卧钩、横折、横折钩、横撇、撇点、横折折撇 **14 类、18 种写法**，没有穷尽笔画库的 28 类。这个小集合用于检查不同局部特征和整字组合，避免只增加重复横竖的样例。

新增四字的图片、布局标注和可编辑配方位于 [`configs/stroke_templates/practice_20261019_v1/`](../../configs/stroke_templates/practice_20261019_v1/)，子目录分别为 `xin`、`hao`、`wo`、`jian`。字体轮廓与中线来自本地 Make Me a Hanzi 数据；笔画类型、折钩位置和阶段边界由人工指定并绑定该中线版本，其中“好”女旁第三笔明确选为提势。字体没有提供这些运笔类型或阶段标签。每笔标称宽度由该笔独立字体轮廓的法线扫描初始化，仅用作几何适配尺度。

起笔阶段先参考模板局部尺度，再人工对齐布局；“好”的竖钩使用 `width_scale: 0.6`，“建”首笔横折使用 `width_scale: 0.8`，避免起笔错位及短竖段超出适配范围。“建”的平捺主体终点位于布局弧长的 81%，收笔保留模板的局部写法。这些选择已保存在布局与配方中，仍为未确认的几何候选。横折折撇使用库内明确标记的规则候选，其余新增字采用已有引导线模板。

新四字默认显示纯 XY；勾选“布局参考”可叠加定位图。左点、卧钩、横和平捺的部分起收笔仍可能超出参考墨迹；当前未启用强制墨迹内约束，轮廓数值只用于定位差异。不能把未接触纸面时的 XY 一律裁回黑色字形，也不能仅凭这些路径判定它们实际何时提笔。当前只处理 XY，不生成 Z、时间或磁响应。

发现局部问题时，点击对应笔画并在曲线上拖动，可撤销或恢复；整字确认后直接保存 JSON／CSV。导出文件不会自动替换原字库数据。配方详情可查看每笔来源，已发布包中的相对路径 `recipe.json` 可离线重建同一结果；继续改长度、宽度或布局时，编辑配置并生成独立新目录，例如：

```bash
PYTHONPATH=src:. python scripts/stroke_templates.py compose \
  --recipe configs/stroke_templates/practice_20261019_v1/hao/recipe.json \
  --output-dir outputs/stroke_templates/characters/hao_my_v2
```

### 合成参数与“永”字示例

打开[合成永字快速检查](../../outputs/stroke_templates/characters/yong_composed_20261017_v2/fit/review.html)，默认叠加“布局参考”以便核对字形，可取消勾选查看纯 XY，选择局部拖动修正，或直接导出整字 CSV/确认 JSON。[配方与五笔来源](../../outputs/stroke_templates/characters/yong_composed_20261017_v2/report.html)可逐笔打开实际采用的模板快照。字体只提供位置、笔顺、布局和标称宽度初值；五笔生成路径来自本轮的 `dian/right_dot`、`hengzhegou/short_heng_long_shu`、`hengpie/short_heng_curved_pie`、`pie/slant`、`na/slant`，每笔绑定精确 template_id。

布局在 [`yong_layout_v1.json`](../../configs/stroke_templates/yong_layout_v1.json)，保留原始字体 XY 及来源版本，另记录人工语义对齐：横折钩、横撇主体起点从 10% 初值前移；横折钩的 hook 标签从下行起点移至实际底部转钩处；斜捺主体终点移至捺脚前，避免把平出段继续当主体拉伸。这是人工布局解释，不是从字体恢复的真实运笔阶段。

编辑 [`yong_from_library_v2.json`](../../configs/stroke_templates/yong_from_library_v2.json) 后生成独立新目录：

```bash
PYTHONPATH=src:. python scripts/stroke_templates.py compose \
  --recipe configs/stroke_templates/yong_from_library_v2.json \
  --output-dir outputs/stroke_templates/characters/yong_my_v3
```

每笔参数为 `body_scale`（主体弦方向跨度）、`span_scales`（各段额外跨度）、`width_scale`（参考宽度和局部特征尺度）、`rotation_deg` 和 `offset_xy_px: [dx, dy]`；X 向右、Y 向上，平移单位 px。横折钩可用 `span_scales: {"to_turn": 1.1}` 只将横段加长 10%；还有 `to_hook`、`to_body_end`。无命名特征点的单主体使用 `body`。主体/宽度/单段参数范围均为 0.5–1.6，但适配器还检查实际分段变形与图像边界，组合参数并非任意都可行。起收形状按参考宽度缩放，再跟随端部切线旋转；宽度尺度本身不生成墨迹宽度曲线。

v1 仅检查生成路径不超出 600×600 画布，斜捺仍有约 11.15% 行程位于参考墨迹外（1 px 容差）。当前 v2 继续使用相同的五个模板，重新调整各笔参数；[修正前后叠加对照](../../outputs/stroke_templates/source_reviews/yong_alignment_20261017_v1/report.html)使用同一张背景参考和同一坐标系：

| 笔画 | body_scale | width_scale | rotation_deg | offset_xy_px |
|---|---:|---:|---:|---|
| 右点 | 1.1 | 0.75 | 0 | [0, 0] |
| 横折钩 | 1 | 1.15 | 0 | [0, 0] |
| 横撇 | 1 | 1 | 0 | [0, 0] |
| 斜撇 | 0.975 | 0.5 | 2 | [4, 2] |
| 斜捺 | 1.075 | 0.5 | 0 | [0, 2] |

这些比例用于参考模板的几何适配，尤其 width_scale 会改变局部特征尺度；它们没有标定真实笔宽、接触高度或磁响应。参数利用当前字体参考调整，不能作为独立保留字的准确率证据。修改参数后会保存新 recipe_id/geometry_id；类型、布局版本、模板版本不符，缺笔或生成越界时拒绝发布。可以让多笔复用同一模板版本。每个合成包保存布局原图、标注、模板快照和相对路径 `recipe.json`，把该配方交给 compose 即可离线重建；快照目录隐藏于首页扫描，重建历史字不会把旧模板提升成全库最新版。

每笔拟合结果现在保存 `image_consistency`，按原图坐标映射到处理后的墨迹掩膜。以 0.25 px 为目标间隔、最多 20000 个弧长中点样本估计轮廓外行程，同时核对全部生成顶点，避免短小越界被采样漏掉；1 px 容差是原图坐标下的轴对齐邻域，实际采样间隔随结果保存。新“永”配方包含 `image_constraint: {"max_outside_fraction": 0}`，检测到轮廓外采样行程或顶点时拒绝发布，保存配方重建时也重新检查。其他未启用约束的配方仍报告诊断及 `generated_path_outside_reference_ink` 标记；complete 仍仅代表每笔有候选。

快速页和配方报告显示各笔“整图轮廓内行程”，局部修改后不再沿用初始数值。这个检查使用整图墨迹并集，不区分交叉处属于哪一笔，也不是连续路径的数学包含证明或墨迹外形仿真。当前新“永”另用字体先验的每笔独立轮廓复核，五笔均未检测到轮廓外行程或顶点（1 px 容差）；真实图片仍需要可靠分笔或人工复核。路径作为运笔 XY，不应解释为黑色外轮廓本身。

### 教学规则重建批次（28 类、38 套初始写法）

打开[全部基本笔画库](../../outputs/stroke_templates/strokes/teaching_20261017_full_v2/index.html)，按顶部 28 类目录跳转。点击写法卡片可对照完整教学原图、查看起行收 XY、切换灰色相对宽度意图，并点击折转、圆弯、转钩或捺脚事件。[原五笔试点](../../outputs/stroke_templates/strokes/teaching_20261017_v1/index.html)保留为历史版本。

| 基本笔画分类（按参考教程顺序） | 独立保存的写法 |
|---|---|
| 1 横 | 长横、短横 |
| 2 竖 | 垂露竖、悬针竖、短竖 |
| 3 撇 | 斜撇、竖撇、短撇平势、短撇斜势 |
| 4 捺 | 斜捺、平捺 |
| 5 点 | 右点、左点、竖点、长点 |
| 6–10 | 提、竖钩、弧弯钩、戈钩（斜钩）、卧钩 |
| 11–15 | 竖弯、竖弯钩、竖提、横钩、横折 |
| 16–20 | 横折钩、横撇、撇折、撇点、横折弯钩 |
| 21–25 | 竖折、竖折折钩、横折提、横折折撇、横撇弯钩 |
| 26–28 | 横折折折钩、横折弯、竖折撇 |

此处“全部”指这篇参考教程的 28 类，不宣称穷尽所有书体、字形或其他分类标准。教程“横析钩”按横折钩归类，戈钩同时标注常用名称斜钩。短撇平势依据正文的字头写法描述，和斜势共用一张短撇教学图；数值角度为人工初值。

参考资料是[硬笔书法28个基本笔画写法字帖教程](https://zhuanlan.zhihu.com/p/569336204)和[楷书基本笔法十二例](https://www.cn5v.com/2020/03/14226.html)。前者已阅读正文和选用配图，作为结构/方向参考；后者仅核实搜索索引正文，原站配图未核验，作为毛笔笔法的定性约束。硬笔表格中的起行收格往往是累计形态，程序没有把各格骨架拼接，也没有把配图当作实测运动。

[`teaching_recipes.py`](../../src/brushbot/stroke_templates/teaching_recipes.py)保留原五笔，并装配 [`teaching_basics.py`](../../src/brushbot/stroke_templates/teaching_basics.py)中其余写法的三次 Bézier 局部段、阶段、事件、宽度节点；来源映射在 [`teaching_assets.json`](../../src/brushbot/stroke_templates/teaching_assets.json)。控制点、相对宽度数值、事件位置均为人工设定的工程初值。程序按段顺序连接连续 XY；阶段来自配方的 entry/body/exit 标记，不再固定按总弧长的 10%/90% 切分。事件同时保存采样索引、XY、整笔行程 s、阶段内 u 和定性提按/速度提示；s 和 u 都不是时间。

“长度对照”单独改变所选主体段沿自身弦方向的跨度，保留横向曲势；起笔、收笔和局部折/钩/捺脚段保持本地形状，后续段随连接点平移。横折钩的横、竖可独立改变，横撇的横、撇可独立改变。页面预置相对当前配方 ±20% 的单因素对照；范围为 0.5–1.6，超范围选项不提供。这是工程预览范围，并非已验证的通用书法适用范围。

检查后可勾选“我已检查当前几何候选”并下载配方；切换长度会清除该候选的检查状态。“导出当前 XY”直接得到当前所选候选的参考笔宽单位坐标、s、phase_id 和 relative_width_intent。下载本身不修改已发布数据包。要继续调整，可编辑配方中的 body_scales、局部 controls 或 width_knots，再生成独立新版本：

```bash
# 使用本机已缓存且校验的 37 张原图，默认生成 28 类、38 套写法
PYTHONPATH=src:. python scripts/stroke_templates.py teaching \
  --output-dir outputs/stroke_templates/strokes/teaching_my_v1

# 按检查页导出的单笔配方重建；文件名替换为实际下载位置
PYTHONPATH=src:. python scripts/stroke_templates.py teaching \
  --recipes /path/to/hengzhegou_配方.json \
  --source-dir reference/stroke_teaching_v1 \
  --output-dir outputs/stroke_templates/strokes/hengzhegou_my_v2
```

原图本机缓存位于 `reference/stroke_teaching_v1/`，已核验选用的 37 张完整图片及水印；配方绑定原始图片 URL、文件名和 SHA-256。换机器需自行保留/补齐这些原始缓存，生成命令不联网下载、不关闭 TLS 校验。每个模板包包括原始配图字节、配方、生成示意图、标注、template.json 和自包含检查页；整批发布前验证所有源图及配方，已有目录拒绝覆盖。

生成示意图中的灰色宽度来自人工 width_knots，明确标记 `authored_relative_width_intent_not_measured_ink_or_force`；不会对自画轮廓扫描后冒充测宽结果，描述中的有效宽度观测数为 0。`teaching_rule_candidate` 在人工确认或后续再次建模时保持为规则重建证据，`physical_validation` 为 false。

这 38 个 template.json 可由现有适配器加载；拟合时目标笔画的 type/variant 必须匹配（如 dian/right_dot、shu/xuanzhen、hengzhegou/short_heng_long_shu），不能把历史 standard 标签自动视为相同写法。多折笔画的每处折、弯、钩均有独立 landmarks；第二横、第二竖和后续弧段也可单独改变跨度。现有 yong 命令仍生成历史字体功能示例；当前新库合成“永”使用下面单独的 compose 配方入口。当前保存的是模板自身的事件和宽度意图；向任意拟合目标传播这些信息、对齐实测磁响应和实机轨迹仍属后续工作。

### 历史永字字体原型与局部修正

直接测试：[永字快速修正](../../outputs/stroke_templates/yong_20261017_final/fit/review.html)。五笔分别为点、横折钩、横撇、撇、捺，均有字库初始几何模板。正确路径保留，只修正局部；整字确认并保存，不必逐笔设置阶段或每次运行命令。

生成自己的永字功能测试：

```bash
PYTHONPATH=src:. python scripts/stroke_templates.py yong \
  --output-dir outputs/stroke_templates/my_yong_v1
```

打开输出 `fit/review.html`，操作如下：

1. 先整体查看；正确时直接点击“整字确认并保存 JSON”。
2. 有局部问题时选择那一笔，直接在曲线上拖动；范围外的点及其他笔画保持不变。交叉位置优先操作已选笔画。范围以鼠标在线段上的投影位置为中心、沿弧长计算；若稀疏路径在该范围内没有采样点，会提示并保留原数据，可扩大范围、拖动端点或用高级标注插点。
3. 可调“修正范围”、撤销/重做、恢复单笔；无需操作阶段锚点。
4. JSON 保存当前整字的原图 Cartesian px 路径；CSV 直接导出当前图的 XY、弧长、阶段进度，单位看表头。二者无需再次拟合才能得到修正坐标。
5. 下次在同一初始版本的页面中载入保存的 JSON 可继续修改。高级模板标注保留在 `report.html`，它显示原始版本而非本次未保存编辑。

JSON 标记 `path_mode: preserve`，记录来源图片、原 geometry_id、修改的笔画及用户整字确认。后续再次调用 fit 时精确保留这些坐标及折/钩标签，`generation_method: manual_geometry_preserved`；这不是重新套模板得到的结果，也不把自比误差当模板质量。相位边界采用后续阶段所有权，弧长与阶段内 u 根据修正路径重算。高级标注插点/删点/反向时同步维护标签索引；命名特征点可拖动，不可直接删除，行笔边界不得越过它们。

初始类型来自显式永字结构先验，字库原始字段只有轮廓与中线，不自带这些类型标签。折/钩位置对应当前字库中线顶点，保留原始转折点再重采样；标签绑定五条中线的 SHA-256 版本，即使只是插入共线顶点也会拒绝不兼容字库，并提示使用随附字库或 `--no-prior`。五笔原型由同一“永”字库样本建立，所以属于功能测试，**不属于独立保留字评价**，也不是已经验证的书法运动模板。

历史永字字体原型的建立步骤是：读取 `data/makemeahanzi/graphics.txt` 的五条有序中线和轮廓；轮廓渲染成测试图片，中线直接作为 XY 来源，未再次骨架提取。各笔保留原始顶点并补充弧长采样，以约 10%/90% 弧长初始化起行收边界；估计分阶段图像宽度，以行笔起点为局部原点、主体首尾弦为方向、参考行笔宽度为尺度归一化。每笔各保存一个单实例原型及宽度观测，横折钩/横撇另保存结构标签。生成整字时，把这五个模型适配回同一字库中线初始化的布局。因此阶段边界仍是假设，原始中线也未提供逆锋、藏锋或顿笔的真实运动；后续需以人工认可的同风格字帖或实写记录建立参考，并用其他字检验迁移。

历史 [2026-10-15 示例](../../outputs/stroke_templates/examples_20261015_final/index.html)保留旧的未支持提示；不要用其中的旧永字页判断当前能力。重新运行 demo 后，土/王/干/士仍为保留字符，永单列为自身原型演示。

重新生成一批示例（输出目录必须不存在）：

```bash
PYTHONPATH=src:. python scripts/stroke_templates.py demo \
  --output-dir outputs/stroke_templates/my_examples_v1
```

### 从自己的图片开始

```bash
PYTHONPATH=src:. python scripts/stroke_templates.py prepare \
  --image /path/to/character.png --character 土 \
  --output-dir outputs/stroke_templates/my_annotation_v1
```

打开输出 `report.html`。原图哈希和尺寸绑定在标注中；候选由本地字库中线做等比包围盒初始化，并用简单方向规则建议 heng/shu/unknown，**没有自动识别笔画写法**。默认 15%/85% 的阶段边界只是初始化，必须检查。此流程不直接从整字骨架裁短枝，原有骨架工具仍用于原始图像诊断。

在报告中选择笔画，拖点或插点，确认类型、方向和行笔边界；可新增/删除笔画，必要时输入人工宽度提示。每次修改会撤销该笔确认，并隐藏旧拟合/指标；完成复核后勾选确认，下载修正 JSON。程序会根据下载内容计算新 annotation_id。

没有字库先验时使用 `--no-prior`，从一条 unknown 路径开始人工描点。不要把 unknown 改成横来绕过缺模板；复合笔画应建立相应类型/变体和命名 landmarks。单主体适配器仍要求主轴投影单调，带 landmarks 的复合模型按片段分别适配；各片段预设伸缩范围为参考宽度比例下的 0.3–3 倍，额外弯曲受模板 max_bend_widths 约束。

### 建立一类模板

先选择单条已确认的参考笔画：

```bash
PYTHONPATH=src:. python scripts/stroke_templates.py build \
  --annotation /path/to/一_annotation.json --image /path/to/reference.png \
  --stroke-id s01 --style-id my_kai_heng \
  --output-dir outputs/stroke_templates/my_heng_v1
```

图片必须是该标注绑定的原始文件，也可使用 prepare 输出的 `source_image.bin`；不能换成缩小后的 `image.png`。正常建立模板要求参考笔画已确认；只有明确希望保留原型时才加 `--allow-unreviewed`。这个选项不提升证据级别。

多样本建立时使用 `--references /path/to/references.json`，不再传单条 annotation/image/stroke-id。清单示例：

```json
[
  {"annotation": "ref_a/一_annotation.json", "image": "ref_a/original.png", "stroke_id": "s01"},
  {"annotation": "ref_b/二_annotation.json", "image": "ref_b/original.png", "stroke_id": "s02"}
]
```

路径相对清单文件。所有参考必须具有相同类型/变体；用户需保证同一风格。按归一化的主体长宽比、头尾长度和主体弯曲特征选择代表实例；保留每个原始样本、分段宽度观测和来源，不混合平均头尾。

模板默认允许主体长宽比为原型的 0.3–3 倍、额外主体弯曲不超过 2 个参考宽度；这些是**可配置的工程边界，不是实测有效范围**。使用 `--body-aspect-range MIN MAX`、`--max-bend-widths VALUE` 明确配置；样本实际覆盖的范围另行保存。图像裁切、缩放与物理尺寸不同，不能从原图 px 推断真实尺寸适用区间。

### 拟合目标字并比较

```bash
PYTHONPATH=src:. python scripts/stroke_templates.py fit \
  --annotation /path/to/土_annotation.json --image /path/to/target.png \
  --templates outputs/stroke_templates/my_heng_v1/template.json \
              outputs/stroke_templates/my_shu_v1/template.json \
  --image-width-mm 100 \
  --output-dir outputs/stroke_templates/my_character_fit_v1
```

`--image-width-mm` 是纠正 EXIF 后整图含留白的宽度；省略则保留 px。输出坐标原点为原图像素中心，X 向右、Y 向上。模板选择以类型/变体为键，重复提供同类型/变体会拒绝，避免偷偷选择一种风格。

输出 `geometry.json`、`paths.csv`、`baseline_paths.csv`、`xy_paths.npz`、原始图片/标注/模板快照、自包含高级 `report.html`、快速 `review.html` 和 SHA-256 清单。loader 兼容只有高级报告的旧数据包。NPZ 无 pickle，字段含 `xy/s/arc_length/phase_id/phase_u/offsets/stroke_ids/units/geometry_id/role`，没有 `t/g_target/Z`，不是 V3。阶段交界可有重复 XY，但没有时间语义。

报告比较到当前标注候选的双向平均/P95 距离、端点误差和相对笔宽误差；数值不自动判合格，基线与分段方案使用相同主体锚点、朝向和宽度尺度。报告中的原始图坐标为 px；导出的 XY 和比较距离使用所选 px/mm。

`join_diagnostics` 单独报告参考与生成路径的两处连接角，单位 rad，界面显示度数。保留参考折角不表示该折角已被证实为正确笔法；发现多余折角时应修正参考阶段/路径，不能靠自动平滑掩盖。平顺参考的相切保持和非平顺参考的折角保持分别由测试覆盖。

缺模板、宽度不可用或形变超限的笔画保留 `unsupported` 和原因。`complete` 仅指所有笔画都有几何候选；`annotation_reviewed` 仅指输入标注已确认，两者均不表示生成路径、物理书写或磁响应已验证。生成路径超出原图时明确标记，不裁短头尾来掩盖问题。

### 宽度与证据的解释

测宽在起、行、收三个阶段分别沿法线扫描；出界、未落在墨迹内、扫描范围不足及接近其他标注笔画的样点保留缺失。未知交叠、脏背景和错误标注仍会影响测量，需要人工复核。人工提示宽度与自动测量分开保存；模板分段描述中的平均宽度由有效观测计算，缺失不补零。

用户图片经过确认后可成为 `manual_geometry_reviewed` 的几何参考，即使初始路径来自字库。demo 的 `font_fixture`、`synthetic_fixture` 和新库的 `teaching_reconstruction` 不会因勾选确认而变成真实书法参考；快速修正和再次拟合会保留该分类，并检查嵌套来源，包括未显式标记 image_kind 的旧夹具。所有模板的 `physical_validation` 仍为 false。

后续研究需使用用户认可的同风格字帖，先建立约十二条横的试点参考并按字保留测试，再依据重复标注误差固定容差。字体演示尚未完成这项独立实证验证。

## 本轮验证记录

2026-10-15：新增 36 项测试通过，覆盖受保护头尾、宽度缩放、相切/折角、阶段弧长、模板/图片绑定、三阶段测宽、遮挡、并发源文件变化、CLI、输出保护及真实 Chrome 标注下载后重新拟合。浏览器测试在缺少 Chrome 或 websocket-client 的环境下可跳过；产品本身不依赖它们。

全仓 **1109 passed, 7 skipped，62.81 s**。沿用[整字 XY 工具](character-xy-extraction.md)已记录的单个 QApplication 保活入口，避免既有 Monitor 测试的 Qt 生命周期问题；没有修改 Monitor。独立代码审阅发现的连接切线表述已按保留参考折角的原则澄清，并补充连接角诊断与回归；浏览器复查发现的曲线上插点问题已由真实浏览器测试先复现再修复。

最终示例包的 158 个文件校验通过；“土、王、干、士”分别有 3、4、3、3 笔候选，“永”的 5 笔明确未支持。Chrome 实测最终多笔报告的阶段进度、对照图层、插点、拖点、旧结果隐藏、JSON 下载和再拟合，桌面/窄屏已目视复核。以上仅证明软件契约与离线流程。

实现保留在功能分支 `codex/stroke-template-geometry-20261015`，保留了原工作区未提交内容，没有自动提交、合并或运行机器人。真实字帖/物理/磁响应证据仍按前文边界留待后续；没有待处理的审阅 Minor 项。

### 2026-10-17：永字与快速局部修正

相关 **50 项测试通过**，包括永字五笔类型、折钩定位、不同片段长度适配、CLI、精确保留修正路径、再次处理后保留结构标签、旧夹具证据不升级、字库中线版本绑定，以及真实 Chrome 的局部拖动、撤销/重做、整字保存、直接 CSV 导出和高级标注维护标签。独立审阅确认的五项 Important 问题均先由回归复现，再修复验证；物理/磁响应、独立书法准确率和新增其他字类未纳入本次评价。

[最终永字页面](../../outputs/stroke_templates/yong_20261017_final/fit/review.html)五笔全部有候选。输出包 38 个不同文件的 68 项清单哈希校验通过，历史旧永字包仍可加载。最终页面另经真实 Chrome 验证保存→局部修改→载入原 JSON 后恢复相同坐标，其他四笔保持原样；桌面和 390 px 窄屏已目视复核，无横向溢出。永字来自同一字库样本的五个原型，仅用于流程和几何功能演示。

最终全仓回归 **1123 passed, 7 skipped，73.16 s**，仍使用单个 QApplication 保活入口；文档布局和 `git diff --check` 均通过。保留原工作区内容，没有提交、合并或运行机器人。

### 2026-10-17：固定资料库首页

新增 7 项目录集成与真实 Chrome 测试通过，验证 CLI 生成后自动更新同一首页、递归收录和版本切换、损坏/临时包处理、旧页面保护、目录删除后的刷新、中文/空格/符号路径链接、搜索、原方向笔画预览和进入永字修正页。独立审阅发现的 Python 3.10 hashlib 兼容问题已先复现再修复；不依赖 Python 3.11 才提供的接口。

最终首页收录 19 个不同模板版本及 27 个整字/标注版本，0 个校验错误；默认展示 9 类模板/写法和 10 个字的最近版本。桌面与 390 px 窄屏已目视检查，无横向溢出。底层拟合和磁响应处理未改变；现有模板、图片及整字数据包未搬动或重写。

全仓回归 **1130 passed, 7 skipped，74.53 s**。文档布局与 `git diff --check` 通过，未提交或合并工作区内容。

### 2026-10-17：教学规则重建笔画库

[正式新库](../../outputs/stroke_templates/strokes/teaching_20261017_v1/index.html)包含右点、横折钩、横撇、斜撇、斜捺五种候选。五张教学原图按原始字节保存并校验；38 个不同文件的 67 项清单哈希校验通过，五个模板都可校验加载和调用现有几何适配器。固定首页现在收录 24 个模板版本、27 个整字/标注版本，0 个收录错误；新库筛选显示 5 项，全部来源的最近版本为 14 组，历史包未覆盖。

最终相关 **70 项测试通过，23.23 s**，包括离线五笔重建、来源损坏拒绝、不可覆盖发布、独立横/竖跨度、阶段/事件对齐、宽度意图不冒充观测、检查后证据不升级，以及 Chrome 的新旧来源切换、事件跳转、配方/XY 下载和再次生成。相对当前配方的长度对照和 0.5/1.6 边界已由回归覆盖。独立审阅提出的预览图分配前尺寸检查与单笔批次说明问题均先复现再修复；配方单位错误导致超过 4000 万像素时明确拒绝并回滚。正式页面另以真实原图逐笔检查，桌面和 390 px 窄屏无横向溢出。

全仓整体运行仍未全绿：两次分别为 **1114 passed, 28 failed, 7 skipped（66.91 s / 65.54 s）**，失败集中于实验记录器 `logger queue overflow`。同一个接触测试按文件单独运行通过，但全仓收集后只选该测试运行仍失败；排除本次两个教学库测试文件后也能复现。此结果不能当作笔画库或全系统性能验证，本轮未处理这个独立的测试收集/记录问题。上述整体运行早于最后新增的尺寸保护回归；最终 70 项相关验证覆盖了发布代码。

新模板仍为教学规则重建候选，人工检查未替代书法专家认可、真实墨迹/运动或磁响应验证。现有 yong 示例尚未自动切换为新模板合成；下一步可在用户认可这五类形状后显式选择新变体与字布局。

### 2026-10-17：补齐全部 28 类基本笔画

[全量版本](../../outputs/stroke_templates/strokes/teaching_20261017_full_v2/index.html)覆盖参考教程的 28 类、38 套写法，包含 37 张经校验的原始配图。已校验 269 个不同文件的 496 项清单哈希，38 个模型均可加载和调用适配器。固定首页收录 62 个模板版本、27 个整字/标注版本，0 个收录错误；教学来源默认显示 38 套最新写法，启用全部版本可查看 43 套教学模板（含原五笔试点）。

最终相关 **73 项测试通过，24.94 s**。本轮验证覆盖全部类型的实际 CLI 生成和模型适配、长短/方向/尖圆收笔的写法差异、第二横独立伸缩时其余局部段保持，以及既有浏览/下载/再次生成流程。独立审阅另逐个检查所有可调跨度的 0.5/1.6 边界，确认其他局部段保持。打包审阅发现 JSON 配图清单未包含在 wheel；已用真实构建/解包后的导入测试复现，再声明 package-data 修复，安装包在仓库外能加载全部 38 套配方。

正式输出另经 Chrome 逐一打开 38 个真实来源检查页，验证原图加载、阶段曲线、末端事件跳转和页面宽度；28 类目录锚点均存在。实际操作横折折折钩的“横段 2 长 20%”，导出 XY 终点为参考笔宽单位 `(3.94, -7.56)`，配方再生成保留确认状态与规则重建来源。桌面和 390 px 页面已目视复核。以上验证针对软件结构与离线数据契约，尚未证明书法质量或物理响应迁移。

最终全仓运行 **1118 passed, 28 failed, 7 skipped，68.32 s**，沿用单个 QApplication 保活入口。失败仍是前轮已记录的实验采集/记录测试，出现 `logger queue overflow`；本轮笔画相关测试均通过，未改实验记录代码。具体失败项保留如下，不能把本轮验证描述为全仓全绿。

<details>
<summary>全仓 28 项失败测试名称</summary>

```text
tests/test_contact_entry_test.py::test_completed_fake_run_records_vectors_and_metrics
tests/test_contact_entry_test.py::test_servo_restart_latency_is_excluded_from_contact_timeline
tests/test_contact_entry_test.py::test_recorded_contact_driver_does_not_catch_up_in_a_command_burst[0.0]
tests/test_contact_entry_test.py::test_recorded_contact_driver_does_not_catch_up_in_a_command_burst[0.002]
tests/test_contact_entry_test.py::test_contact_continues_after_160_ms_stall_above_z20
tests/test_four_direction_sweep.py::test_execution_rebaselines_in_direction_and_records_no_feedback
tests/test_four_direction_sweep.py::test_constant_height_no_return_run_keeps_direction_baseline
tests/test_four_direction_sweep.py::test_successful_sensor_reboot_is_saved_with_each_trial_baselines
tests/test_four_direction_sweep.py::test_baseline_recovers_after_startup_outlier_without_dropping_raw_data[BASELINE]
tests/test_four_direction_sweep.py::test_baseline_recovers_after_startup_outlier_without_dropping_raw_data[REBASELINE]
tests/test_four_direction_sweep.py::test_bz_variation_is_recorded_but_does_not_gate_xy_baseline
tests/test_run_ladder_experiment.py::test_runner_prompts_after_passes_four_eight_and_twelve
tests/test_run_ladder_experiment.py::test_runner_prompts_to_wet_and_rebaselines_between_every_path
tests/test_run_ladder_experiment.py::test_runner_automatically_rebaselines_after_each_wetting_cycle
tests/test_short_plateau_pi_experiment.py::test_pi_records_state_only_during_measurement
tests/test_strokeplan_rotational_entry.py::test_recorded_rotation_and_p_only_during_measurement[feedforward]
tests/test_strokeplan_rotational_entry.py::test_recorded_rotation_and_p_only_during_measurement[p]
tests/test_strokeplan_rotational_entry.py::test_comparison_keeps_command_samples_in_order_under_scheduler_jitter[late_tick-feedforward]
tests/test_strokeplan_rotational_entry.py::test_comparison_keeps_command_samples_in_order_under_scheduler_jitter[late_tick-p]
tests/test_strokeplan_rotational_entry.py::test_comparison_keeps_command_samples_in_order_under_scheduler_jitter[repeated_poll-feedforward]
tests/test_strokeplan_rotational_entry.py::test_comparison_keeps_command_samples_in_order_under_scheduler_jitter[repeated_poll-p]
tests/test_strokeplan_stationary_entry.py::test_stationary_pi_records_whole_curve_and_resets_at_lift
tests/test_z_identification.py::test_sweep_recording_and_analysis_preserve_directions_without_fitting_delay[sweep-down]
tests/test_z_identification.py::test_sweep_recording_and_analysis_preserve_directions_without_fitting_delay[sweep-cycle]
tests/test_z_identification.py::test_full_run_records_null_targets_segments_and_one_airborne_baseline
tests/test_z_identification.py::test_analysis_exports_quality_flags_and_preserves_raw_input
tests/test_z_identification.py::test_analysis_retains_completed_run_with_timing_quality_flags[skipped]
tests/test_z_identification.py::test_analysis_retains_completed_run_with_timing_quality_flags[balanced_duplicate]
```

</details>

### 2026-10-17：长短横原图路径入库与首页调整

[最终入库批次](../../outputs/stroke_templates/strokes/sohu_heng_20261017_final/report.html)把两条已有追踪线发布为可加载的模板，保留完整来源与原始点列。14 个被清单追踪的文件、含子包在内的 24 项哈希校验通过；两条模板均通过既有适配器。原规则库和原有整字包未改写；本轮两次中间试发布完整保留在 `.guide_sync_trials/`，不进入正式首页索引。

固定首页默认第一个页签为笔画库，第二个为字库；从常用基础笔画到折钩排列，组内仍选最新版本。同类预览统一参考宽度比例，搜索不改变比例。当前收录 64 个不同模板版本、27 个整字/标注版本，0 个收录错误；默认教学来源仍为 38 套最新写法，其中长短横是本次追踪候选。各自详情可切换原图、原始点列、完整原图和头尾放大；连续下载会分别保存 `heng_long_xy.csv` 与 `heng_short_xy.csv`。

最终相关 **81 项测试通过，22.84 s**，包含两笔 CLI 入库、不可覆盖发布、源文件/清单/坐标不一致拒绝、裁剪框保护、原始阶段和回锋保持、模型源图绑定、适配、首页默认页签/排序/最新版本选择、同类显示比例，以及真实 Chrome 的图层切换、进度与连续导出。正式输出另经桌面和 390 px 页面检查，无横向溢出；实际下载分别为 46 / 25 行，末点为原图笛卡尔像素 `(482,324)` / `(404,329)`。独立审阅无待处理问题。上述验证不评价书法真实性或磁响应。

最终全仓运行 **1126 passed, 28 failed, 7 skipped，66.47 s**。失败项与上一节列出的 28 个采集/记录测试完全相同，仍出现 `logger queue overflow`；本轮未改这些实验模块，不能报告为全仓全绿。文档布局与 `git diff --check` 通过。


### 2026-10-17：25 套引导线更新与五模板合成永字

[新 25 套模板批次](../../outputs/stroke_templates/strokes/sohu_basics_20261017_v1/report.html)和[合成永字](../../outputs/stroke_templates/characters/yong_composed_20261017_v1/fit/review.html)已同步到固定首页。当前收录 89 个不同模板版本、28 个整字/标注版本，0 个收录错误；默认教学来源仍显示 38 套最新写法，其中 27 套为引导线追踪、11 套明确保留规则候选。旧数据包未覆盖。新模板的全部阶段边界与命名折/钩点均与原始追踪绑定，简化误差在声明的 0.75 px 容差内；25 个模型均通过校验并可调用适配器。此容差仅表示折线简化误差，不是教程线追踪准确率。

“永”五笔全部使用本轮选定的五个模板版本，布局仍明确来自原字体先验。人工校正了阶段与转钩语义，保留原 XY 和修改记录；合成包自带的相对路径 recipe.json 在其他输出目录重建得到相同 geometry_id。模板快照隐藏于全库版本扫描，重复使用同一模板的多笔可正确生成。独立审阅确认的未清单绑定模板文件、generic trace 缺少类型字段两项问题，以及重复模板复用问题，均由回归先复现后修复，并完成复核。

最终全仓中的 **101 项笔画模板相关测试全部通过，无跳过**，覆盖批量追踪/导入、复合笔画标签、宽度提示来源、模板/布局版本绑定、单笔参数修改不影响其他笔画、保存配方离线重建、快照不改变全库最新版，以及原有浏览、修正与下载。实际输出另经 Chrome 逐一打开 25 个来源详情页，检查原图解码、三阶段、头尾局部、原始追踪图层和末端进度；25 个 CSV 均下载完成并逐一核对点数及末点。固定首页与合成“永”在桌面和 390 px 窄屏无横向溢出；新“永”的五个模板快照来源链接均可打开。25 套原图/路径对照和“永”纯 XY/布局叠加图已目视复核，证据仍为未确认的教学几何候选。

最终全仓 **1146 passed, 28 failed, 7 skipped，89.41 s**，继续使用单个 QApplication 保活入口。28 个失败名称与前文列表完全一致，属于既有实验采集/记录测试，日志包含 logger_fault、FAULT 状态和未完成记录断言；本轮未修改这些模块，不能描述为全仓全绿。文档布局检查与 git diff --check 通过。没有执行机器人或生成实测磁响应。


### 2026-10-17：修复合成永字与布局轮廓不贴合

用户指出勾选“布局参考”后，合成路径与黑色字形不贴合。复现发现 v1 捺尾越出参考墨迹：原逻辑只约束画布范围和少数主体锚点，起收笔依模板参考宽度缩放，缺少图像轮廓检查。当前[永字 v2](../../outputs/stroke_templates/characters/yong_composed_20261017_v2/fit/review.html)使用相同的五个模板版本，利用主体跨度、局部尺度、旋转和位移重新适配；原图、布局及历史输出各自保留版本。[前后对照](../../outputs/stroke_templates/source_reviews/yong_alignment_20261017_v1/report.html)记录相同坐标系下的两版实际路径与检查数值。

旧捺在 1 px 容差下的轮廓外行程约 11.15%；新五笔采样行程与全部顶点检查均未检测到超出参考墨迹。另按字体原始逐笔轮廓独立核对，五笔同样通过，避免整图墨迹并集在交叉处掩盖错位。这个字体先验也用于调参，因此仅证明本字的几何叠加检查通过，不是独立书法质量或真实墨迹预测证据。当前目录有 89 个模板版本、29 个整字/标注版本，0 个收录错误。

新增轮廓行程诊断、可选合成发布约束，以及快速页修改后撤下旧数值的提示。手算回归覆盖画布内但墨迹外、掩膜降采样坐标、笔段穿越轮廓空隙，以及短小中间顶点越界被弧长中点漏采的情形。最后一项由独立审阅提供具体路径，先复现错误发布，再补全顶点检查，审阅复核通过。新配方 recipe.json 离线重建得到相同 geometry_id；当前“永”默认叠加布局参考，可切换纯 XY、局部修改和直接下载。

最终 **107 项模板相关测试全部通过，无跳过**；全仓 **1152 passed, 28 failed, 7 skipped，91.52 s**。28 个失败名称与前文记录完全一致，均在既有采集/记录测试中，没有新增失败项。实际新版及前后对照页已在 Chrome 桌面与 390 px 窄屏目视检查，无横向溢出；实际 CSV 导出 1512 行路径点，五笔 ID 齐全，JSON 保存与新版首页跳转通过。文档布局检查和 git diff --check 通过。

### 2026-10-19：五字练习集与默认合成字筛选

保留原“永”v2，新增“心、好、我、建”四个由当前笔画模板合成的字，共新增 25 笔。默认字库按 4、5、6、7、8 笔的“心 → 永 → 好 → 我 → 建”排列，五字覆盖 14 类、18 种写法。首页仍默认打开笔画库；旧字体测试通过“全部资料（含旧测试）”查看，历史包未删除。当前收录 89 个模板版本、33 个整字／标注版本，0 个收录错误；原模板条目和“永”清单字节均与操作前一致。

四个新包都已逐项校验清单，并由各自包内相对路径配方在独立目录离线重建，geometry_id 与原结果相同。新增四字的全部 25 段行笔主体，在整图墨迹及各笔独立字体轮廓上都未检测到轮廓外行程或顶点（1 px 容差）；部分起收笔仍保留轮廓外诊断。这些字体布局参与了阶段和尺度调整，因此检查结果只表示本批布局适配，不是独立准确率、真实墨迹预测或实测运笔证据。

Chrome 实际操作确认五字顺序、来源筛选、练习编号、写法信息和全部版本；五个快速修正页均可叠加布局、下载当前 JSON 和 CSV。CSV 路径点数依次为心 1202、永 1512、好 1753、我 2024、建 2614，逐笔 ID、坐标数值及 JSON 的来源 geometry_id 均已核对。“心”局部拖动只改变所选一笔，撤销后恢复原路径。首页与整字页均完成桌面和 390 px 窄屏检查，无横向溢出。

独立代码审阅发现：未列入练习顺序的字若新版补全了笔画，直接按每个版本的笔画数排序会让旧草稿排在前面。先以真实“二”字的单笔草稿／双笔新版复现，再改为同字共享最新版本的笔画数排序键，保留版本时间顺序；审阅复核通过。来源筛选先于去重，错误练习顺序不会替换已有首页。

最终 **111 项模板相关测试全部通过，无跳过**；全仓 **1184 passed, 7 skipped，106.44 s，无失败项**。文档布局检查和 git diff --check 通过。此批仅生成 XY，仍需用户检查起收笔写法，未生成 Z、时间或磁响应数据。
