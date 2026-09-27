---
project: 04-robot-control
status: active
---

# 非线性前馈 P 参数扫描

本批包含六组参数、九笔完整真机记录，按 Kp 与修正行程统一归组。

- [综合分析报告](analysis/分析报告.md)：共同条件、参数组比较、逐笔结果、误差结构及执行器诊断。
- [六组目标跟随图](analysis/01_六组目标跟随.png)
- [参数组指标图](analysis/02_参数组指标.png)
- [误差结构与组内差异](analysis/03_误差结构与组内差异.png)
- [反馈限幅与实际 TCP 跟随](analysis/04_反馈限幅与TCP跟随.png)
- [参数组指标表](analysis/参数组指标.csv) / [逐笔指标表](analysis/逐笔指标.csv)
- [完整结果与来源哈希](analysis/summary.json)

当前数据支持以 Kp=1、Ki=0、修正 ±0.8 mm 作为后续实验基准；该组平均 MAE 16.58 µT，±20 µT 内比例 65.84%。组内差异及结论范围详见报告。

`raw/` 保存原始记录；`analysis/` 保存统一分析与同名 SVG 图；`analysis/archive/` 保存旧版分析备份。
