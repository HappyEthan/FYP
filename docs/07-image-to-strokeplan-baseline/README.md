---
project: 07-image-to-strokeplan-baseline
status: active
---

# 07 · Image to StrokePlan Baseline

建立图像到完整 StrokePlan 的无学习基线，为 Transformer 提供可比较的模板迁移方案。已有整字骨架 XY、分段模板、局部拖动快速修正和整体缩放对照。新笔画库按参考教程覆盖 28 类基本笔画、38 套写法候选，其中 27 套已换为原图引导线追踪，11 套保留规则候选；字库默认展示“心、永、好、我、建”五个模板合成字，覆盖 14 类、18 种写法，配方支持逐笔长度、宽度、旋转和位移调整；历史字库原型和五笔试点继续保留。真实字帖、磁响应及完整可执行计划仍待独立验证。

完整阶段关系见[根计划](../../plan.md)。先读下面的主题文件；历史材料集中在 `archive/`，按记录日期解释。

第一次了解本工具，可先读[笔画模板库与整字 XY 生成系统介绍](stroke-library-introduction.md)，其中说明模板、布局与配方的关系、五字练习集、人工修正及后续磁响应关联。

日常从[笔画与字的资料库](../../outputs/stroke_templates/index.html)浏览模板和整字结果。首页默认第一个页签“笔画库”，按横、竖、撇、捺、点、提及后续折钩顺序展示；“字库”为第二个页签，默认按“心 → 永 → 好 → 我 → 建”展示五个合成字，选择“全部资料（含旧测试）”可找回历史字体样例。支持搜索、版本切换并进入修正页。同类笔画按参考宽度等比例预览，避免长短写法各自铺满卡片。默认目录内用 CLI 新增结果会自动更新首页，手动复制后运行 catalog；详见[模板使用说明](stroke-template-design.md)。

当前首页的[长横](../../outputs/stroke_templates/strokes/sohu_heng_20261017_final/templates/heng_long/report.html)和[短横](../../outputs/stroke_templates/strokes/sohu_heng_20261017_final/templates/heng_short/report.html)已切换为搜狐教学图白色引导线的追踪候选，可叠加原图、原始追踪线，放大头尾并下载 XY。[本轮新增 25 套追踪模板](../../outputs/stroke_templates/strokes/sohu_basics_20261017_v1/report.html)后，合计 27 套有引导线依据，11 套缺少清晰对应引导线的写法保留并标记；[模板合成永字](../../outputs/stroke_templates/characters/yong_composed_20261017_v2/fit/review.html)已修正参考轮廓适配，默认显示叠加图，支持轮廓内行程诊断、纯 XY 和局部修正。[原始 28 类、38 套规则批次](../../outputs/stroke_templates/strokes/teaching_20261017_full_v2/index.html)继续保留。教学图路径与人工曲线均尚未验证为实测笔尖运动或磁响应。

## 主题文件

| 文档 | 内容 |
|---|---|
| [stroke-library-introduction.md](stroke-library-introduction.md) | 面向首次使用者的系统介绍、五字检查流程和后续用途。 |
| [baseline-design.md](baseline-design.md) | 项目范围、输入输出、阶段验证与待定问题。 |
| [character-xy-extraction.md](character-xy-extraction.md) | 已实现的整字 XY 提取：命令行、报告、坐标约定、导出与磁响应关联接口。 |
| [stroke-template-design.md](stroke-template-design.md) | 引导线与规则笔画库、五字练习集及覆盖情况、模板合成参数、配方离线重建、固定首页、图片标注/修正和证据边界。 |

## 历史实施记录

[初版模板实施计划](archive/stroke-template-implementation-plan.md)的四项任务已完成，保留作实现过程追溯；当前功能与操作以上面的系统介绍及模板使用说明为准。

## 维护方式

本部分采用一个总 README 与按主题命名的 Markdown 文件；同主题继续修订原文件。只有确需追溯的旧设计或结果才进入 `archive/`，不再为单篇文档建立多层目录。
