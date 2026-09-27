---
project: 04-robot-control
status: active
---

# 短平台 P 与 PI 对比

四笔完整真机记录，P 与 PI 各两笔。共同采用 160→240→160 µT、30 s 测量路径，按预定首次平台、深压和返回平台窗口分析。

- [分析报告](analysis/分析报告.md)
- [四笔目标跟随](analysis/01_四笔目标跟随.png)
- [平台指标与误差](analysis/02_平台指标与误差.png)
- [积分与抗饱和](analysis/03_积分与抗饱和.png)
- [实际 TCP 与整体指标](analysis/04_TCP与整体指标.png)
- [指标表](analysis/指标.csv) / [完整统计与来源](analysis/summary.json)

本批 PI 组全程平均 MAE 10.67 µT，P 组为 16.68 µT；±20 µT 内比例分别为 82.41% 和 60.86%。积分实现校验通过，未达到 ±0.2 mm 上限。实际顺序 P、P、PI、PI，模式和先后顺序尚未分离；结论为描述性比较。
