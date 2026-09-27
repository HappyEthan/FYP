---
project: 04-robot-control
status: active
---

# 短平台 Ki 参数扫描

Ki=0.025、0.05、0.10三组各两笔，按预定平台窗口评分，保留完整30 s和返回过程指标。

- [综合分析报告](analysis/分析报告.md)
- [六笔目标跟随](analysis/01_六笔目标跟随.png)
- [主评分与返回表现](analysis/02_主评分与返回表现.png)
- [积分状态与反馈限幅](analysis/03_积分状态与反馈限幅.png)
- [返回误差与实际TCP](analysis/04_返回误差与实际TCP.png)
- [逐笔指标](analysis/逐笔指标.csv) / [参数组指标](analysis/参数组指标.csv)
- [完整统计与来源](analysis/summary.json)

**Ki=0.10为优先验证候选，尚未最终定值。** 其平台主评分6.29 µT、全程MAE9.87 µT、±20内85.98%；返回过程MAE12.11 µT，高于Ki=0.05的9.41 µT。按预定规则保留该指标冲突，下一步聚焦0.05与0.10。
