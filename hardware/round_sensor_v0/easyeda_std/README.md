# 嘉立创 EDA 标准版原理图 SCH-A2

这是可编辑原理图的本地源文件，现已拆成 **5 个原理图页**，合计 **60 个元件、241 个引脚、37 个命名网络**。各页采用标准版 JSON（`docType=1`），内嵌元件符号、真实引脚、导线、网络标签及不连接标志。在同一个嘉立创 EDA 标准版工程中，同名绿色网络标签跨页保持电气连接，位号在五页间全局唯一。

**中文最终连线版已作为独立的 `圆形传感器_SCH_A2_中文最终版` 保存到嘉立创 EDA 标准版中文版个人工作区。** 五页标题、功能区说明、设计备注、审查备注和页脚均已改为简体中文；芯片型号、引脚名、网络名及封装名作为工程技术标识保留原文。同一页内的信号与控制网络使用连续直角导线；电源、地以及跨页连接保留同名网络标签。五页已逐页检查，设计管理器显示元件 60、网络 37/37，没有可见错误条目；封装管理器列出 60 行、0 个未绑定。在线记录见 `editor_validation_SCH_A2_CN_FINAL.json`。本地仅保留当前 SCH-A2 工作文件、封装备份和初始 PCB 恢复点；更早的设计说明已移入项目根目录的 `archive/hardware/`。

2026-09-15 已在在线工程中核验、映射并保存 **60/60** 个元件；封装管理器最终复核为 60 行、0 个未绑定。全部电阻、电容及 U1–U7 已绑定，U3 在线封装名为 `LGA-14L_L3.0-W2.5-P0.50-TL`；D1-D3、J1、J2、J3、SW1、ANT1、U4 使用已保存到个人库的定制封装。J2 为 3 个 1.50 × 2.00 mm 直焊焊盘、1.80 mm 间距；J3 为 2 × 3 个直径 1.00 mm 的圆形 pogo 焊盘、X/Y 均为 1.27 mm 间距；SW1 为 2 个 1.50 × 2.00 mm 直焊焊盘、2.00 mm 间距。J2/SW1 暂按 30–32 AWG 导线和笔杆壳体应力释放设计，J3 的方向须与编程治具一起锁定。保存后主工程及五个原理图页均无未保存标记。随后手动刷新标准版设计管理器，结果为元件 60、网络 37/37；展开的 37 个网络均无感叹号或错误说明，因此标准版集成的原理图 ERC/连接性检查当前无报错。详见 `footprint_binding_SCH_A2.json` 与 `custom_footprint_plan_SCH_A2.json`。

U1 使用 57 焊盘的 `ESP32-S3-PICO-1-N8R8` 封装，已核对 7 × 7 mm 本体、0.4 mm 外围间距和 4.0 × 4.0 mm 的 GND 焊盘 57。U4 的 `BQ24074_RGT0016B_TI_LAND` 已确认 1–17 一一映射，外围焊盘 0.24 × 0.60 mm、0.50 mm 间距，EP17 为 1.68 × 1.68 mm。D1-D3 的焊盘为 0.30 × 0.50 mm、中心距 0.70 mm。J1 的 17 个符号引脚全部按同名焊盘映射，A1/B12、A4/B9 保持为位置重叠但编号独立的焊盘，4 个壳脚共用 `SH`。ANT1 的 1–4 一一映射，四焊盘均为 1.00 × 0.60 mm，中心按 X=±1.50 mm、Y=±0.65 mm 放置。嘉立创 KiCad 转换器会让 J1/J2/SW1 的带编号矩形多边形焊盘在封装管理器尺寸摘要中显示 0.000 × 0.000 mil，因此转 PCB 后仍必须用原生 DRC 和 Gerber 复核实际几何。ANT1 仍须约 8.0 × 3.4 mm 的全铜层及正反面器件净空，并在最终笔杆、电池与握持条件下调谐。原始生成源 `round_sensor_SCH_A2_multi.json` 的 `package` 字段仍为空；`SCH_round_sensor_SCH_A2_bound60_2026-09-15.json` 保留在线全部封装绑定，`round_sensor_SCH_A2_WIRED_multi.json` 则把这些已审核绑定合并回最终连续连线版。

## 打开方式

### 2026-09-15 在线封装绑定与初始 PCB 恢复点

- `SCH_round_sensor_SCH_A2_bound60_2026-09-15.json`：从在线编辑器实际导出的完整五页原理图；本地解析确认 60 个符号均有非空封装字段。恢复已绑定版本时优先使用此文件。
- `round_sensor_SCH_A2_WIRED_multi.json`：当前推荐导入文件；五页采用中文说明和连续同页导线，并保留上述 60/60 已审核封装绑定，云端工程名为 `圆形传感器_SCH_A2_中文最终版`。
- `PCB_round_sensor_SCH_A2_initial_2026-09-15.json`：已保存在线 `PCB_round_sensor_SCH_A2` 的初始 PCB，包含 60 个封装和临时直径 30 mm 圆形边框；暂保留编辑器默认双铜层，叠层尚未冻结。
- 元件仍在板框外的待布局区，尚未布线。原生初次 DRC 返回 160 项“未完成连接”；该结果不能称为 DRC 通过。30 mm 仅为布局工作边界，不能当作最小直径或笔杆定稿尺寸。
- 后续先核对转换后的焊盘几何与叠层，再布局 USB、主控、传感器、电源及天线净空，逐步压缩板框。原始 `round_sensor_SCH_A2_*` 生成源仍未回填在线封装，重新生成不会更新上述在线导出快照。

五页文件及推荐页名如下，顺序也记录在 `sheets_manifest.json`：

- `round_sensor_SCH_A2_01_MCU.json` → `01_MCU`
- `round_sensor_SCH_A2_02_SENSORS.json` → `02_SENSORS`
- `round_sensor_SCH_A2_03_USB.json` → `03_USB`
- `round_sensor_SCH_A2_04_POWER.json` → `04_POWER`
- `round_sensor_SCH_A2_05_RF_BATTERY_DEBUG.json` → `05_RF_BATTERY_DEBUG`

推荐直接在嘉立创 EDA 标准版中文版中使用“文件 → 打开 → 嘉立创 EDA”，导入 `round_sensor_SCH_A2_WIRED_multi.json`；该工程级文件包含全部五页、连续同页导线和 60/60 封装绑定。`round_sensor_SCH_A2_multi.json` 是可重新生成但封装字段为空的中间源。五个单页 JSON 用于单页维护与独立校验，不要把它们分别导入成五个独立工程。SCH-A1 文件保留为上一版审计记录，不应与 SCH-A2 同时放在同一工程中，否则会造成位号重复。

不要把 `design_netlist.json`、`sheets_manifest.json` 或 `bom_draft.json` 当作原理图导入。

`preview.html` 可直接在本机浏览器打开，切换主控、传感器、USB、电源、RF/调试五个分区；不依赖任何外部服务器。五个分页 SVG 供快速预览，工程级 JSON 才是嘉立创 EDA 的可编辑文件。

## 本版电气变更

- 主控 U1 使用 ESP32-S3-PICO-1-N8R8；全部 57 个封装端子逐个定义。内存保留端子及不使用的 GPIO 均有明确不连接标志。
- MLX90393 选定 UTDFN-8 型号 `MLX90393SLQ-ABA-011-RE`，7 位 I2C 地址为 `0x10`；LSM6DSOX 的 SA0 接地，地址为 `0x6A`。
- USB-C 的 A/B 两组数据触点分别并联，CC1/CC2 各用 5.1 kΩ 下拉；D+/D- 使用 TPD2EUSB30A，CC1/CC2/VBUS 各增加 TPD1E10B06 候选。该设计不请求 USB PD 电压，ESD 二极管不代替 CC 短接高压保护控制器。
- BQ24074 的 CE 由 R11 默认下拉，USB 与合规 NTC 电池同时存在时可在主控未启动或 SW1 关闭时自主充电。GPIO10=`CHARGE_DISABLE` 经 R21 串联后只用于高电平主动禁用充电；复位/高阻态不会阻断低电池恢复。
- SW1 只连接 VSYS 到 `PWR_SW_ON`；R19 限流后驱动 LDO EN，R20 负责下拉。U7 的 OUTA 可安全拉低 EN，避免开关直接把 VSYS 短到比较器输出。
- 新增 U7=`TLV6700DSER` 双比较器。通道 A 监测 VSYS，并由 R25 正反馈形成名义约 **3.48 V 关断 / 3.68 V 恢复**的迟滞；USB 插入后 VSYS 升高，可自动恢复。通道 B 产生 GPIO7=`VBUS_VALID_N`，名义约 **4.60 V 置低 / 4.54 V 释放**，避免旧 Q2 在残余 VBUS 上误判，也不把 VBUS 分压直接送入断电 GPIO。C23/C24 分别过滤 VBUS 和 VSYS 感测节点，拔线时延仍须实测小于 3 ms。
- 补入 SiP 22 µF 储能电容及 100 nF 去耦。22 µF 初始按 0805、BAT/OUT 的 10 µF 初始按 0603；有效电容需按实际型号和直流偏压核查。
- GPIO6 暂不接电池 ADC 分压，避免未解决的关机反向供电路径。后续如需要电量显示，加入受控采样电路。
- J3 为六个可接触测试焊盘，用于 EN、BOOT、UART、3V3 和 GND，外部工具不得直接向 LDO 输出反向注入电源。

## 电池、RF 与尚待定值项

J2 为 PACK+、PACK-、CELL_NTC 三个接口。电池必须是带保护的单节 4.2 V 电芯/电池包，目标容量仍按 350–400 mAh 预算；实际尺寸和约 2 小时续航未验证。

**SCH-A2 将 R16 设为 0 Ω、R17 保持 DNP，并把电池接口限定为带 10 kΩ、103AT-2 兼容 NTC 的三线电池包；NTC 必须接在 J2.3 与 PACK- 之间。** NTC 缺失或开路时充电应保持禁止。若实际电芯不是该曲线，必须重新计算 R16/R17，不能用固定电阻假装电芯温度正常。ISET 8.66 kΩ 对应约 103 mA 典型充电电流，还需核对电池额定电流与公差。

R30/R31 为 RF 初始 0 Ω 连接位，C30/C31 为 DNP 匹配位；最终值取决于正式 PCB 和整机调试。天线净空须覆盖所有铜层和正反面器件，不能把“正面空出来”当作完成射频布局。

本地生成源中所有元件的 `package` 字段暂为空，候选封装写在 `Package candidate` 属性中；在线工作副本的临时映射另见 `footprint_binding_SCH_A2.json`。这样不会把同名但未审核、未保存或未导出的库封装误认为已绑定。EP 编号约定：U1=57、U2=9、U4=17、U5=7；U7 使用 WSON DSE-6 的 1=OUTB、2=VDD、3=INB-、4=INA+、5=GND、6=OUTA。后续封装必须与该约定一致或同时修改符号和封装。J1 的四个壳脚共用 `SH` 焊盘号。

USB100 默认输入限流下的 USB-only 冷启动、U7 门限公差、发射瞬态、热和传感器干扰仍需检查。U7 WSON 候选为 LCSC `C2876178`，2026-09-13 检索时可购，但库存和嘉立创贴装属性必须在下单前复核。当前已生成待布局 PCB 草稿，未生成生产 Gerber。

## 尺寸结论更正

SCH-A2 改动了充电控制、VBUS 检测、欠压关断和外围数量，早期“7 个大器件 + 42 个外围估算包络”的装箱数据不覆盖本版。早期脚本还只在正面禁止小器件进入 RF 区，没有覆盖背面净空，且不检查网络相关布局。因此该装箱结果不能证明 18 mm 的完整电路可行；PCB 和笔杆尺寸须重做实际封装布局后确定。

## 本地验证与复现

在项目根目录运行：

```sh
python3 hardware/round_sensor_v0/scripts/build_easyeda_schematic.py
python3 hardware/round_sensor_v0/scripts/check_easyeda_schematic.py
```

检查脚本独立读取五个导出的 JSON，以“页名 + 坐标”隔离各页图形连接，识别连续导线组件，再用同名网络标签合并跨页网络并与连接清单比对。检查包括 USB 正反插触点、主控电源/内存保留端子、传感器模式、自主充电控制、U7 分压/反馈值、CC 下拉、NTC 装配状态及悬空引脚标记。结果见 `validation_report.json`，其中分别记录五个源文件及合并数据的 SHA-256。该本地检查不读取在线封装绑定；中文最终版的在线 60/60 绑定与 37/37 设计管理器结果以 `editor_validation_SCH_A2_CN_FINAL.json` 为准。

另外运行了四项检查器测试：正常的五页文件通过；删除传感器页 SCL 导线、在 RF/调试页短接 3V3/GND、误换主控页 USB 数据标签均被拒绝。SCH-A2 的在线导入、60/60 封装绑定与嘉立创原理图设计管理器集成检查已完成；PCB DRC、Gerber、射频、热、机械和实物测试仍未完成。SCH-A1 本地快照与旧在线核对记录已从当前工作目录移除；如需追溯，可从 Git 历史恢复。

## 资料来源

- [嘉立创标准版文件格式](https://docs.easyeda.com/en/DocumentFormat/2-EasyEDA-Schematic-File-Format/index.html)：符号、引脚、导线、网络标签及文件结构。
- [嘉立创标准版多页原理图](https://docs.lceda.cn/cn/Schematic/Multi-Sheet/)：一个原理图支持多个页面，同名网络标签跨页连接，位号需全局唯一。
- [嘉立创标准版原理图设计管理器](https://docs.lceda.cn/cn/Schematic/Design-Manager/)：标准版集成 ERC、错误标志和刷新方式。
- [ESP32-S3-PICO-1 数据手册](https://www.espressif.com/sites/default/files/documentation/esp32-s3-pico-1_datasheet_en.pdf)：端子定义及参考电路。
- [MLX90393 Rev 012](https://www.melexis.com/-/media/files/documents/datasheets/mlx90393-datasheet-melexis.pdf)：UTDFN-8 端子及 0x10 地址。
- [LSM6DSOX](https://www.st.com/resource/en/datasheet/lsm6dsox.pdf)：Mode 1 接法。
- [BQ24074](https://www.ti.com/lit/ds/symlink/bq24074.pdf)、[TLV755P](https://www.ti.com/lit/ds/symlink/tlv755p.pdf)：供电、使能和外围要求。
- [TLV6700](https://www.ti.com/lit/ds/symlink/tlv6700.pdf)：400 mV 门限、两路开漏输出、WSON DSE-6 引脚和迟滞特性。
- [GCT USB4105](https://gct.co/files/drawings/usb4105.pdf)：USB 接口引脚；本项目已有官方 KiCad 封装用于交叉核对接点编号。
- [TPD2EUSB30A](https://www.ti.com/lit/ds/symlink/tpd2eusb30a.pdf)、[TPD1E10B06](https://www.ti.com/lit/ds/symlink/tpd1e10b06.pdf)：ESD 端子和额定值。
- [MMBT3904](https://assets.nexperia.com/documents/data-sheet/MMBT3904.pdf)：B1/E2/C3 端子和 NPN 开关。
- [Johanson 2450AT18D0100001E](https://www.johansontechnology.com/docs/3791/Antenna-2450AT18D0100001E-Rev5.0.pdf)：四端天线及整机净空/调谐要求。
