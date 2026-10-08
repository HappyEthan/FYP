# 圆形传感板工程

更新：2026-10-06。当前入口以 [CAD_HANDOFF.md](CAD_HANDOFF.md) 为准。

## 当前入口｜Q1直接修复

- [最终保存重开 PCB](easyeda_std/Q1直接修复_20261006/PCB_Q1直接修复_孔距收尾_保存重开_20261006.json)
- [完整五页 SCH](easyeda_std/Q1直接修复_20261006/SCH_Q1替料_最终五页回读_20261006.json)
- [博后审阅包，仅审核](manufacturing/仅审核禁止生产/圆形传感板_Q1修复最终审阅_20261006.zip)
- [冻结需求](DESIGN_BASELINE_XIAO_PICO.md)

当前41位置、20网络、36件SMT，18mm候选圆板；Q1=DMP2165UW-7/C388477，原生保存重开DRC0/未连接0。工厂层叠/钢网/机器基准、USB首板范围和真实笔杆装配待确认，未放行生产、未下单。

以下9月29日记录为历史；T版、43元件/21网和原Q1报错不代表当前状态。历史脚本不能直接重跑覆盖当前工程。

## 2026-09-29 T版历史入口

- [当前云端 PCB：T 检查点原生回读](easyeda_std/PCB_克隆板USB接口工艺修正_云端回读_20260929.json)
- [T 云端保存与接口制造输出核验](easyeda_std/克隆板T接口云端与制造核验_20260929.json)
- [S 连接器问题来源，已由 T 局部修正](easyeda_std/克隆板S连接器孔与开窗审核_20260929.json)
- [当前五页原理图：全部封装绑定的原生回读](easyeda_std/usb_keep_min_candidate/原生回读_全部封装绑定.json)
- [原理图网页预览](easyeda_std/usb_keep_min_candidate/预览.html)：方便阅读，原生回读才是封装绑定依据。
- [交接与下一步](CAD_HANDOFF.md)
- [当前电源预算、缺项与验证清单](电源审核_R_20260929.md)
- [冻结需求](DESIGN_BASELINE_XIAO_PICO.md)
- [小型化待办](小型化调整方案.md)

当前为 43 元件、21 网络、18 mm 候选圆板；保留 USB-C、PICO 主控、FPC 天线、板载 IMU 和 MLX90393、笔头四线接口、BOOT/RESET。没有改为 UART，不再要求两小时续航。

**尚未完成整板验收，禁止按此下单生产。** 当前云端检查点为 T，已覆盖同一个克隆并关闭重开核验；原版未动、未新增云端 PCB。T 修正两 USB 定位孔附近铜距及四固定槽偏心：两地焊盘靠孔边回收0.05mm、两条5V线局部避让、四槽孔中心回到铜中心。新制造包四层最小名义孔铜距约0.201758mm，四槽最窄名义铜环约0.199545mm；全部89孔3916对的最小孔边距0.248025mm。两处地盘锡膏跟随新铜形，阻焊边界采样覆盖。原生 DRC 仍1项Q1、未连接0，地网一组。43元件位置、21网络、规则、USB数据线、RF、L2/L3铺铜缓存和18mm板框保持；底层仅T295附近一片地铜边界重建。S及更早修正保留。完整USB、电源性能、盘中孔/钢网/双面装配和工厂审核仍待完成。

## 目录说明

当前审核包：[T Gerber，仅审核禁止生产](manufacturing/仅审核禁止生产/Gerber_圆形传感板_T_仅审核禁止生产_20260929.zip)。本次几何检查不包含工厂补偿、刀具与对位公差；约0.2018mm的最小间距并非宽裕制造余量。后续优先收口Q1、PICO盘中孔和双面装配条件，并审核最终BOM/贴片坐标；不擅自上传、采购或下单。

- `easyeda_std/`：当前设计、有效封装、验证记录及脚本依赖的历史输入。除上方当前入口外，其余旧 PCB 文件不是可直接恢复为工作板的最新版。
- `scripts/`：当前生成、验证、回归测试及其依赖。带旧版名称的辅助模块仍被当前工具导入，不应按名称直接删除或独立运行。
- `references/`：当前器件及工艺参考资料。
- `archive/`：保留生成器固定输入、封装模板、局部修正恢复点，以及含独有未保存修改的旧工作板。
- 根目录专题审核：保留电气、机械、射频、制造风险依据；其中历史坐标、数量和待办不覆盖本页及交接文件。

## 历史检查入口（输入版本固定，不能用于证明当前板）

在本目录运行（本地检查不等于原生 ERC/DRC 或制造放行）：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_a5_rf_route_20260918.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_a5_usb_keep_candidate.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_a5_usb_keep_footprints.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_pcb_a5_pico_stencil.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/audit_clone_ground_spacing_s_20260929.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/audit_clone_connector_s_20260929.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/audit_clone_connector_t_20260929.py
```

## 清理与恢复

T修改前S恢复点、本地候选/报告及临时原生回读集中在 `archive/T接口修正与S恢复_20260929/`，当前T回读与报告在 `easyeda_std/`，T审核Gerber在 `manufacturing/仅审核禁止生产/`。本轮下载均已归入工程，没有删除恢复文件或新增云端版本。旧S、R及固定哈希脚本保留作历史对照，不能重跑旧修改脚本覆盖T。

2026-09-29 已整理下载目录的 99 个本工程文件：4 个 R 核验/Q 恢复输入移至 `archive/R核验与Q恢复_20260929/`，当前 R Gerber 移至 `manufacturing/仅审核禁止生产/`；其余 94 个散文件合并留档到 `archive/下载历史_20260929.zip`，原件移入 `/Users/liuchunyu/.Trash/fyp_pcb_downloads_20260929`。当前 R PCB、原理图和现有脚本依赖未删除，云端未改动。每个移动文件和压缩包内容均已进行 SHA256 核验。见[本次清理清单](清理清单_20260929.json)。

历史报告内的 Downloads 路径是当时的来源记录，不再代表文件现址；按本次清单定位，或从历史压缩包按原文件名取出。旧一次性修改脚本不要直接重跑，需要历史输入时先恢复到独立临时目录并改用该路径。当前 R Gerber 审核脚本已改用工程内路径。

后续下载只作传输中转：核验后当前资料入工程，恢复资料集中归档，试排临时文件放独立临时目录；不逐轮堆积下载，不新增云端版本。

2026-09-18 曾从工作目录移出 310 个旧文件，共 37,422,848 字节（约 35.7 MiB），含被替换的旧说明原件。原件按原目录结构保存在 `/Users/liuchunyu/.Trash/fyp_round_sensor_cleanup_20260918`，没有永久删除。七份入口说明已重新整理，不是设计改版。

完整逐文件路径和 SHA256 见[清理清单](清理清单_20260918.json)。需要恢复时只取具体文件，不要整体覆盖当前工程。不要重复执行一次性清理脚本；未提交或推送 Git，也未处理其他 FYP 目录。
