---
project: 08-system-evaluation
status: active
---

# 08 · System Evaluation

正式三组对照为纯前馈、无容差反馈、有容差反馈。评价协议在可复现前馈和 StrokePlan 执行基础上建立。

完整阶段关系见[根计划](../../plan.md)。先读下面的主题文件；历史材料集中在 `archive/`，按记录日期解释。

实验结果集中维护在[实验总览](实验清单.md)，生成方法与正式评价设计继续独立保留。

## 主题文件

| 文档 | 内容 |
|---|---|
| [multi-stroke-experiment-plan.md](multi-stroke-experiment-plan.md) | brush2 五档磁响应与宽度意图对照、图像／描述到阶段表及曲线的方案，含长横初值；正式实验参数与结果图方案待定。 |
| [StrokePlan前置工作梳理.md](StrokePlan前置工作梳理.md) | brush2 首轮独立验证现状，以及参考笔画、经验目标曲线、特征研究和高质量生成的阶段关系。 |
| [实验总览与脚本索引](实验清单.md) | 历史实验的统一结果入口：21 组、196 次运行的用途、脚本、条件、结果、方向模型定义和证据链接。 |
| [evaluation-design.md](evaluation-design.md) | 项目范围、输入输出、阶段验证与待定问题。 |
| [xy-offline-comparison.md](xy-offline-comparison.md) | 单笔图片参考路径提取、固定坐标下的 StrokePlan XY 叠加、误差指标与离线比较工具。 |

## 维护方式

本部分采用一个总 README 与按主题命名的 Markdown 文件；同主题继续修订原文件。只有确需追溯的旧设计或结果才进入 `archive/`，不再为单篇文档建立多层目录。
