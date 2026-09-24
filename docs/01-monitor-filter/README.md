---
project: 01-monitor-filter
status: active
---

# 01 · Monitor + Filter

前期软件基础已完成。这里维护信号观测、录制和展示；当前实验的正式滤波／统计口径仍待确定。现行信号监视器是 `src/brushbot/monitor/`，入口为 `python -m brushbot.monitor`；`exhibition_monitor/` 是另一条展示界面支线。

完整阶段关系见[根计划](../../plan.md)。先读下面的主题文件；历史材料集中在 `archive/`，按记录日期解释。

## 主题文件

| 文档 | 内容 |
|---|---|
| [exhibition-monitor.md](exhibition-monitor.md) | 桌面展示工作站与人工页原型的合并设计。 |
| [monitor.md](monitor.md) | 当前 `brushbot.monitor` 的信号监视与录制，以及可选实验／返回面板的接入边界。 |

## 历史资料

| 文档 | 内容 |
|---|---|
| [filter-history.md](archive/filter-history.md) | 滤波器原理、选型设计和早期验收记录。 |
| [monitor-history.md](archive/monitor-history.md) | 早期信号源、滤波界面、工作台与审查记录。 |

## 维护方式

本部分采用一个总 README 与按主题命名的 Markdown 文件；同主题继续修订原文件。只有确需追溯的旧设计或结果才进入 `archive/`，不再为单篇文档建立多层目录。
