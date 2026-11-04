# 2026-11-04 历史验证记录

本目录对应 VSYS 加宽前版本。当前板入口和验证见 [2026-11-05 记录](../20261105_vsys/README.md)；本日期的旧正式源与审核包可从 [原发布提交](https://github.com/HappyEthan/FYP/tree/ae69e87/hardware/pen_sensor_strip_v1)恢复。

对应正式 PCB：`easyeda_std/PCB_11x40_四层_3V3两处分支钝角_保存重开_20261104.json`。相对于本目录的文件入口见[工程交接](../../CAD_HANDOFF.md)。

| 检查 | 结果 | 记录 |
|---|---|---|
| 原生 DRC / 网络 | 0 / 27 of 27 | [界面摘录](native_DRC_web_saved_reopened.txt)、[EDA 截图](native_DRC_web_saved_reopened.png) |
| SCH / PCB 逐脚网表 | PASS，43 位号、190 逻辑脚、193 物理焊盘 | [网表报告](netlist_saved_reopened.json) |
| 完整铜并集 | PASS，异网间距/同层异网交叉/悬空铜组均为 0 | [铜形报告](PCB_web_saved_reopened_audit.json) |
| 两处大倒角 | PASS，六端点夹角 >110°，相邻直边 >0.40 mm | [几何报告](saved_geometry_comparison.json)、[同比例对照](两处3V3_修改前后.png) |
| 正式保存重开 | 与候选实际铜形差异 0.0 mm²；1296 个非铺铜图元相同 | [源身份比较](reopened_identity_comparison.json)、[交付状态](delivery_status.json) |
| 供电设计 | USB/BAT 严格选择，无自动回退 | [电源行为审查](power_behavior_review.json) |
| 图像来源 | 网页端原生预览，裁图无几何修改 | [来源记录](preview_provenance.json)、[正反面](PCB_正反面_网页原生预览.png) |

`baselines/` 仅包含修改前源和候选比较源；当前源以 `easyeda_std/` 的保存重开文件为准。完整浏览器截图/文本及其它返工过程留在本地，不纳入公开发布。JSON 报告仅将绝对本地路径改为相对工程路径，并记录原报告哈希；检查数值不变。

这些结果来自 2026-11-04 的实际设计检查。GitHub 发布时核对源文件身份、报告、链接和包完整性，没有把文档发布描述为再次运行 EDA 或实物验收。逐脚网表检查不是完整电气类型 ERC。微观角度扫描不能替代两处同尺度视觉检查，原厂焊盘本身轮廓未改。

本目录的 [manifest.json](manifest.json) 记录本次公开文件的 SHA256。源的制造适用性、USB/RF 实测、温升、装配和首板功能仍待验证。
