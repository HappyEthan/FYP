---
project: 07-image-to-strokeplan-baseline
status: archived
---

# 分段笔画模板实施计划

2026-10-19 归档核对：初版四项任务均已完成，相关模块、CLI 和示例已存在。本页保留当时的实施过程，不能作为当前待办或最新功能清单；现行用法见[系统介绍](../stroke-library-introduction.md)和[模板设计与使用](../stroke-template-design.md)。下文测试结论属于原实施记录，不代表本次环境的全库测试状态。

**Goal:** 交付可离线建立、修正、适配和比较的分段 XY 模板工具，并保留后续磁响应关联依据。

**Architecture:** 新增 `brushbot.stroke_templates`，复用图像预处理和几何比较。候选、模板、生成实例分别版本化；CLI 与自包含 HTML 共用核心。

**Tech Stack:** 现有 Python、NumPy、Pillow、Matplotlib；HTML/SVG 原生 JavaScript，不新增产品依赖。

**Spec:** [stroke-template-design.md](../stroke-template-design.md)。原实施时用户已认可对话中的设计并要求执行，按当时工作区连续实施。

## Global Constraints

- 不读写 memory，不连接机器人，不补造磁目标/时间/Z，不修改 V3。
- 保留既有未提交改动；在功能分支原位工作，不擅自提交。依赖现有未跟踪 XY 模块，另建干净 worktree 会丢失依赖。
- 新增 docs 直接归属 07；资源在 outputs，结束运行 docs 检查。
- 模板证据级别和评价参照来源显式显示，字体夹具不是书法实测。

## Review Focus

- 图片/标注哈希不一致、非法锚点或零长度主体不能错挂模板。
- 长度改变不能拉伸头尾，回描不能丢失，阶段和整笔弧长必须区分。
- 多笔交叠、越出图像的宽度不能作为可靠目标。
- 缺模板、形变越界或人工未复核不能被报告成完整且已验证的字。
- HTML 编辑后不能继续显示旧拟合作为当前结果；路径/字名需安全编码。

### Task 1: 数据契约与分段适配

**Files:** `src/brushbot/stroke_templates/{__init__,schema,geometry}.py`; `tests/test_stroke_templates.py`。

**Interfaces:** `validate_annotation`, `build_template`, `validate_template`, `adapt_stroke`。模板以参考宽度为单位；生成结果保留阶段和基线。

- [x] 先写并运行手算几何、锚点、范围、标识测试，确认缺实现失败。
- [x] 实现契约、原型选择、受限主体伸缩/弯曲、头尾相似变换。
- [x] 运行核心测试，记录结果。

### Task 2: 图片标注与宽度

**Files:** `src/brushbot/stroke_templates/{annotations,widths}.py`; `tests/test_stroke_template_annotations.py`。

**Interfaces:** `prepare_annotation`, `reference_from_annotation` 消费 Task 1 契约；字库中线只生成未复核先验。

- [x] 先写图片绑定、交叉遮挡、宽度测量、人工更正和字库缺字测试并见失败。
- [x] 实现保留原图坐标的候选和宽度测量、参考实例建立。
- [x] 运行对应测试。

### Task 3: 可修正报告、CLI 与发布

**Files:** `src/brushbot/stroke_templates/{report,bundle}.py`; `scripts/stroke_templates.py`; `tests/test_stroke_template_cli.py`。

**Interfaces:** prepare/build/fit 子命令消费前两任务；产生可下载标注、模板、几何和 manifest。

- [x] 先写真实 CLI 建模/适配流程、尺度、失败回滚、已有目录保护测试并见失败。
- [x] 实现 HTML 点编辑、阶段锚点、复核及下载、拟合对比与指标；发布清单最后写入。
- [x] 运行 CLI 测试，浏览器验证编辑、下载和过期状态。

### Task 4: 示例、文档与最终验证

**Files:** `src/brushbot/stroke_templates/examples.py`; 脚本 demo 子命令；07 主题指南和 README。

**Interfaces:** 字体夹具建立横/竖原型，保留简单字符作为候选测试；所有来源及非独立评价标注清楚。

- [x] 添加 demo 批次行为测试，先见失败再实现。
- [x] 生成可直接打开的示例、横画伸缩对照及简单整字。
- [x] 更新使用文档、当前状态与证据边界。
- [x] 新增及相关回归、全仓测试、docs layout、diff 检查；按执行技能做一次独立代码审阅，修复必要问题。
