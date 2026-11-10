# FYP 项目文档导航

文档保留两种互补视图：工程维护按八个项目归属保存，研究阅读按论文研究问题和实验任务导航。同一主题只保留一份正文，避免为了论文章节复制工程文档。Git 跟踪总导航和八个项目目录；`其他/`、`assets/` 与临时文件保留在本地。

## 按论文研究问题导航

论文大纲把磁响应数据拆成“分析、区分、帮助生成”三种用途。下面的研究入口是逻辑分类，不改变文档的唯一 owner；需要追溯具体实现时，继续从对应项目 README 进入。

| 研究入口 | 回答的问题 | 主要文档 | 论文对应 |
|---|---|---|---|
| **F0 · 总体问题与论文** | 研究问题、贡献边界和章节如何组织？ | [论文大纲（本地）](其他/论文大纲_初版_20261023.md)、[当前研究计划书（本地）](其他/proposal_ethan_260925.md)、[研究决策与 TODO（本地）](其他/research-decisions-and-todo.md) | 第 1、2、7、8 章 |
| **F1 · 共同方法与信号** | 磁毛、采集、Bxy 幅值/方向和计划数据如何定义？ | [Monitor + Filter](01-monitor-filter/README.md)、[Data Acquisition](05-data-acquisition/README.md)、[StrokePlan](02-strokeplan/README.md) | 第 3 章 |
| **F2 · A 过程表征** | 横/竖的幅值阶段和横折的方向过渡是否可观察、可量化？ | [笔法操作分析方案](08-system-evaluation/磁响应笔法操作分析方案.md) | 第 4.1、5、6.2 节 |
| **F3 · B 完整笔画分类** | 时间归一化的整笔曲线能区分哪些完整笔画？ | [笔画分类方案](08-system-evaluation/磁响应曲线笔画分类方案.md) | 第 4.2、5、6.3 节 |
| **F4 · C 书写参考应用** | 采集曲线怎样组装为 StrokePlan、执行并复用？ | [多笔画拆分计划](08-system-evaluation/multi-stroke-experiment-plan.md)、[图像到 StrokePlan 基线](07-image-to-strokeplan-baseline/README.md)、[Robot Control](04-robot-control/README.md) | 第 4.3–4.4、6.4–6.5 节 |
| **F5 · 结果与证据** | 每项主张由哪些运行、指标、对照和失败记录支持？ | [实验总览与脚本索引](08-system-evaluation/实验清单.md)、[评价设计](08-system-evaluation/evaluation-design.md)、[XY 离线比较](08-system-evaluation/xy-offline-comparison.md) | 第 5、6 章 |
| **H · 历史** | 哪些设计已被替代，为什么仍保留？ | 各项目 `archive/`、`docs/其他/history/` | 补充材料与追溯 |

F2 和 F3 是两条独立验证任务：过程表征解释整笔内部的预定义阶段，完整分类只回答整条曲线对应的类别，不把一个任务的结果当成另一个任务的证据。F4 是应用路线，是否成立由执行记录和同次成品决定，不要求先完成分类模型。

## 完整项目路线与当前阶段

仓库根目录的 [plan.md](../plan.md) 是**完整项目路线**，记录前期基础、当前进展和后续工作。截至 2026-10-19，brush2 已完成前馈建表、方向校准离线评价及 8 笔独立真机验证，但冻结模型的稳定性和覆盖尚未得到支持。XY 模板与五档经验磁目标方案可并行准备，实际笔宽关系仍待验证。

前期阶段“已完成”指相应设计或基础实现完成，不表示真机性能已验证或项目整体结束。数据采集、系统评价、MuJoCo 后续平台工作、图像到计划和 Transformer 各有独立文档，不能从下面的项目编号推断它们必须先于当前对应关系实验完成。StrokePlan 的现行说明见[项目设计](02-strokeplan/strokeplan.md)；`z_ff` 是否应保存在计划中、学习所需的 Z 数据如何定义，仍在讨论。

## 类别一：StrokePlan 生成与实施

本类保留生成方法、数据契约、执行实现、离线评价、后续设计及配套工具。各项目 README 保留其余主题与必要的设计历史入口。

| 项目 | 职责 | 当前状态 |
|---|---|---|
| [01 Monitor + Filter](01-monitor-filter/README.md) | 信号观测、稳定性验证和滤波比较 | 前期设计与软件基础已完成；装配态适用性待复核 |
| [02 StrokePlan](02-strokeplan/README.md) | 可执行书写计划的数据契约与生成规则 | 现行格式版本 3 已离线实现；Z 字段与学习数据关系待讨论 |
| [03 Transformer](03-transformer/README.md) | 在模板基线上学习残差并生成 StrokePlan | 延后 |
| [04 Robot Control](04-robot-control/README.md) | 真机接口、开环/前馈控制及反馈候选 | 已有 brush2 执行及独立验证；可靠映射与通用笔画校准接入待完成 |
| [05 Data Acquisition](05-data-acquisition/README.md) | 同步采集、数据格式和控制验证数据 | 已有 brush2 采集与验证记录；继续完善数据规范和前馈适用性 |
| [06 MuJoCo Simulation Platform](06-mujoco-simulation-platform/README.md) | 场景、模型、控制接口和仿真验收 | 前期仿真探索已完成；平台接口与数值可信度仍待完善 |
| [07 Image to StrokePlan Baseline](07-image-to-strokeplan-baseline/README.md) | 图像分析、笔画分解和无学习模板迁移 | 已实现骨架 XY、28 类基本笔画的 38 套教学模板（27 套引导线追踪、11 套保留规则候选）、心永好我建五个模板合成字、局部快速修正及默认笔画优先的资料库首页；真实字帖、磁响应和完整 StrokePlan 待验证 |
| [08 System Evaluation](08-system-evaluation/README.md) | 指标、对照/消融、鲁棒性与结果汇总 | 后续建立正式对照与指标协议 |

每个项目均采用“总 README → 主题文件 → 必要的历史记录”的阅读顺序，合并后的文件只保留一份。

## 类别二：实验记录与脚本索引

已完成或被替代的实验，统一更新总览，不再分别维护交付、交接、阶段汇总和重复结果正文。原始数据、配置快照、指标、图表与复现程序继续保存在对应 `runs/`，由总览链接。

| 文档 | 用途与当前边界 |
|---|---|
| [实验总览与脚本索引](08-system-evaluation/实验清单.md) | 历史实验统一入口：21 组、196 次现存真机运行，其中 182 次完成；查用途、脚本、条件、结果、方向模型定义及证据。 |

每组注明日期、毛笔与装配条件；`completed` 只表示流程结束，效果是否达标按结果判断。

## 本地跨项目资料

`docs/其他/` 在本地保存跨项目架构、研究决策、文档政策和历史记录，不进入 Git。尚未确认归属的文件不能直接归为“其他”，应先放入临时入口 `docs/tmp/`。

## 新文件与资源入口

- 归属明确的 Markdown 直接放入对应项目或 `docs/其他/`，并填写与目录一致的 YAML 元信息。
- 归属不明确的 Markdown 可暂存到 `docs/tmp/`，但任务结束前必须完成分类。
- PNG、GIF、PDF 等所有新资源必须先进入 `docs/tmp/`，确认所有者后再移入 `docs/assets/<项目>/` 或 `docs/assets/other/`。
- `docs/assets/` 根目录不能直接存放文件；资源目录中不能存放 Markdown。
- 每次新增或移动文件后运行 `python scripts/check_docs_layout.py`；`tmp` 中仍有文件时检查必定失败。

## Git 跟踪边界

Git 仅跟踪本页和八个项目目录。`docs/其他/`、`docs/assets/`、`docs/tmp/` 不上传。现行做法应核对近期计划、对应项目文档和实际代码；同一主题不另存副本。
