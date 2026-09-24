# FYP 项目文档导航

本目录把触觉毛笔书法机器人拆分为八个可独立推进的小项目。Git 跟踪总导航和八个项目目录；`其他/`、`assets/` 与临时文件保留在本地。

## 完整项目路线与当前阶段

仓库根目录的 [plan.md](../plan.md) 是**完整项目路线**，记录已完成的前期仿真、Monitor/Filter 设计和开环操控基础，也记录当前与后续工作。当前阶段是沿 XY 行走测量命令 Z 与 `|ΔBxy|` 的初步对应关系，验证重复性，整理适用条件明确的前馈表，再建立并执行单笔 StrokePlan。实验批次的具体 Z 数值随毛笔和装配调整，不属于计划的固定要求。

前期阶段“已完成”指相应设计或基础实现完成，不表示真机性能已验证或项目整体结束。数据采集、系统评价、MuJoCo 后续平台工作、图像到计划和 Transformer 各有独立文档，不能从下面的项目编号推断它们必须先于当前对应关系实验完成。StrokePlan 的现行说明见[项目设计](02-strokeplan/strokeplan.md)；`z_ff` 是否应保存在计划中、学习所需的 Z 数据如何定义，仍在讨论。

## 八个子项目

| 项目 | 职责 | 当前状态 |
|---|---|---|
| [01 Monitor + Filter](01-monitor-filter/README.md) | 信号观测、稳定性验证和滤波比较 | 前期设计与软件基础已完成；装配态适用性待复核 |
| [02 StrokePlan](02-strokeplan/README.md) | 可执行书写计划的数据契约与生成规则 | 现行格式版本 3 已离线实现；Z 字段与学习数据关系待讨论 |
| [03 Transformer](03-transformer/README.md) | 在模板基线上学习残差并生成 StrokePlan | 延后 |
| [04 Robot Control](04-robot-control/README.md) | 真机接口、开环/前馈控制及反馈候选 | 开环操控基础已完成；当前建立磁目标前馈关系 |
| [05 Data Acquisition](05-data-acquisition/README.md) | 同步采集、数据格式和控制验证数据 | 按当前对应关系及后续示范需求推进 |
| [06 MuJoCo Simulation Platform](06-mujoco-simulation-platform/README.md) | 场景、模型、控制接口和仿真验收 | 前期仿真探索已完成；平台接口与数值可信度仍待完善 |
| [07 Image to StrokePlan Baseline](07-image-to-strokeplan-baseline/README.md) | 图像分析、笔画分解和无学习模板迁移 | 等待底层接口稳定后启动 |
| [08 System Evaluation](08-system-evaluation/README.md) | 指标、对照/消融、鲁棒性与结果汇总 | 后续建立正式对照与指标协议 |

每个项目均采用“总 README → 主题文件 → 必要的历史记录”的阅读顺序，合并后的文件只保留一份。

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
