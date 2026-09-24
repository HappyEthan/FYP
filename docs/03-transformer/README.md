---
project: 03-transformer
status: active
---

# 03 · Transformer

目标是生成可书写的完整 StrokePlan。模型研究位于前馈、计划执行和模板基线之后，尚未进入正式训练。

完整阶段关系见[根计划](../../plan.md)。先读下面的主题文件；历史材料集中在 `archive/`，按记录日期解释。

## 项目目的

研究如何从目标字帖或示教信息生成可用于书写的完整 StrokePlan，并评估 Transformer 是否优于无学习模板迁移基线。只预测二维磁序列的早期方案不限定最终模型输出范围；这仍是未来研究目标，不是已实现能力。

## 范围

- 定义模型输入、输出、条件信息和跨模态融合方式。
- 比较模板迁移、序列模型和 Transformer 路线。
- 定义训练数据构建和离线评价方法。

本项目不负责底层硬件采集、实时控制安全或 MuJoCo 场景实现。

## 已知限制与后续讨论

- 图像到执行参数存在一对多问题。
- 数据量不足时，复杂模型很可能不如模板基线。
- 笔杆姿态是否进入模型输出取决于 StrokePlan 和数采项目的结论。

## 主题文件

| 文档 | 内容 |
|---|---|
| [transformer-design.md](transformer-design.md) | 模板、Transformer 输入输出和数据需求。 |
| [implementation-roadmap.md](implementation-roadmap.md) | 从字帖图像到完整 StrokePlan 的阶段计划。 |

## 历史资料

| 文档 | 内容 |
|---|---|
| [teach-replicate.md](archive/teach-replicate.md) | 早期示教—复刻架构与坐标链。 |

## 维护方式

本部分采用一个总 README 与按主题命名的 Markdown 文件；同主题继续修订原文件。只有确需追溯的旧设计或结果才进入 `archive/`，不再为单篇文档建立多层目录。
