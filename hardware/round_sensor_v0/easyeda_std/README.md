# 嘉立创 EDA 标准版原理图 SCH-A1

这是可编辑原理图的本地源文件，现已拆成 **5 个原理图页**，合计 **55 个元件、229 个引脚、36 个命名网络**。各页采用标准版 JSON（`docType=1`），内嵌元件符号、真实引脚、导线、网络标签及不连接标志。在同一个嘉立创 EDA 标准版工程中，同名绿色网络标签跨页保持电气连接，位号在五页间全局唯一。

**已完成五页合并后的本地连通性检查、五页矢量预览及嘉立创 EDA 标准版中文版在线验证。** `round_sensor_SCH_A1_multi.json` 已导入并保存到个人工作区工程 `round_sensor_SCH_A1`，旧的整页 `Sheet_1` 已删除。工程树只保留五个功能页；刷新设计管理器后显示 **元件 (55)、网络 (36 / 36)**，没有可见错误条目。未绑定 PCB 封装。

## 打开方式

五页文件及推荐页名如下，顺序也记录在 `sheets_manifest.json`：

- `round_sensor_SCH_A1_01_MCU.json` → `01_MCU`
- `round_sensor_SCH_A1_02_SENSORS.json` → `02_SENSORS`
- `round_sensor_SCH_A1_03_USB.json` → `03_USB`
- `round_sensor_SCH_A1_04_POWER.json` → `04_POWER`
- `round_sensor_SCH_A1_05_RF_BATTERY_DEBUG.json` → `05_RF_BATTERY_DEBUG`

推荐直接在嘉立创 EDA 标准版中文版中使用“文件 → 打开 → 嘉立创 EDA”，导入 `round_sensor_SCH_A1_multi.json`；该工程级文件包含全部五页，此路径已在 `lceda.cn/editor` 实测成功。五个单页 JSON 用于单页维护与独立校验，不要把它们分别导入成五个独立工程。`round_sensor_SCH_A1.json` 保留为旧版单页备份，不应再与五页版本同时放在同一工程中，否则会造成位号重复。

不要把 `design_netlist.json`、`sheets_manifest.json` 或 `bom_draft.json` 当作原理图导入。

`preview.html` 可直接在本机浏览器打开，切换主控、传感器、USB、电源、RF/调试五个分区；不依赖任何外部服务器。`round_sensor_SCH_A1.svg` 是整张矢量预览，不含 EDA 编辑功能。

## 本版电气变更

- 主控 U1 使用 ESP32-S3-PICO-1-N8R8；全部 57 个封装端子逐个定义。内存保留端子及不使用的 GPIO 均有明确不连接标志。
- MLX90393 选定 UTDFN-8 型号 `MLX90393SLQ-ABA-011-RE`，7 位 I2C 地址为 `0x10`；LSM6DSOX 的 SA0 接地，地址为 `0x6A`。
- USB-C 的 A/B 两组数据触点分别并联，CC1/CC2 各用 5.1 kΩ 下拉；D+/D- 使用 TPD2EUSB30A，CC1/CC2/VBUS 各增加 TPD1E10B06 候选。该设计不请求 USB PD 电压，ESD 二极管不代替 CC 短接高压保护控制器。
- 新增 Q1（MMBT3904）：BQ24074 的 CE 通过 R11 上拉到 VSYS，由 NPN 拉低。GPIO10=`CHARGE_ALLOW` **高有效**，与早期“GPIO10 直接连接低有效 CE”的草案不同。上电、复位、主控关机时默认不允许充电。
- SW1 接在 VSYS 与 LDO EN 之间，R20 将 EN 下拉；关闭开关关闭 3V3，但充电芯片和电池保护仍与电池连接。该版本不支持关机充电。
- 新增 Q2 和 GPIO7=`VBUS_PRESENT_N` 检测 USB 是否插入。固件必须据此管理 USB 连接和自供电状态，不能在无 VBUS 时一直保持 USB 上拉。
- 补入 SiP 22 µF 储能电容及 100 nF 去耦。22 µF 初始按 0805、BAT/OUT 的 10 µF 初始按 0603；有效电容需按实际型号和直流偏压核查。
- GPIO6 暂不接电池 ADC 分压，避免未解决的关机反向供电路径。后续如需要电量显示，加入受控采样电路。
- J3 为六个可接触测试焊盘，用于 EN、BOOT、UART、3V3 和 GND，外部工具不得直接向 LDO 输出反向注入电源。

## 电池、RF 与尚待定值项

J2 为 PACK+、PACK-、CELL_NTC 三个接口。电池必须是带保护的单节 4.2 V 电芯/电池包，目标容量仍按 350–400 mAh 预算；实际尺寸和约 2 小时续航未验证。

**R16、R17 默认不装（DNP）。R16 断开使 TS 没有有效温度通路，充电保持禁止。** 选定实际电池及 NTC 曲线后，计算其允许充电温区，再配置串联/并联电阻。不能只装一个固定电阻来代替电池温度检测。ISET 8.66 kΩ 对应约 103 mA 典型充电电流，还需核对电池额定电流与公差。

R30/R31 为 RF 初始 0 Ω 连接位，C30/C31 为 DNP 匹配位；最终值取决于正式 PCB 和整机调试。天线净空须覆盖所有铜层和正反面器件，不能把“正面空出来”当作完成射频布局。

所有元件的 `package` 字段暂为空，候选封装写在 `Package candidate` 属性中。这样不会把同名但未审核的库封装误认为已绑定。EP 编号约定：U1=57、U2=9、U4=17、U5=7；后续封装必须与该约定一致或同时修改符号和封装。J1 的四个壳脚共用 `SH` 焊盘号。

USB100 默认输入限流下的 USB-only 冷启动、电池低压与 LDO 压降、欠压关机策略、发射瞬态、热和传感器干扰仍需检查。当前没有生成 PCB 或 Gerber。

## 尺寸结论更正

SCH-A1 新增了控制晶体管、VBUS 检测、电源开关和较大储能电容，早期“7 个大器件 + 42 个外围估算包络”的装箱数据不覆盖本版。早期脚本还只在正面禁止小器件进入 RF 区，没有覆盖背面净空，且不检查网络相关布局。因此该装箱结果不能证明 18 mm 的完整电路可行；PCB 和笔杆尺寸须重做实际封装布局后确定。

## 本地验证与复现

在项目根目录运行：

```sh
python3 hardware/round_sensor_v0/scripts/build_easyeda_schematic.py
python3 hardware/round_sensor_v0/scripts/check_easyeda_schematic.py
```

检查脚本独立读取五个导出的 JSON，以“页名 + 坐标”隔离各页图形连接，再用同名网络标签合并跨页网络并与连接清单比对。检查包括 USB 正反插触点、主控电源/内存保留端子、传感器模式、CE 隔离、CC 下拉、DNP 设置及悬空引脚标记。结果见 `validation_report.json`，其中分别记录五个源文件及合并数据的 SHA-256。

另外运行了四项检查器测试：正常的五页文件通过；删除传感器页 SCL 导线、在 RF/调试页短接 3V3/GND、误换主控页 USB 数据标签均被拒绝。五页版已在嘉立创标准版设计管理器中刷新为 55 个元件、36/36 个网络、0 个可见错误。该结果不代表 PCB DRC、封装、射频、热或实物测试已经完成。

## 资料来源

- [嘉立创标准版文件格式](https://docs.easyeda.com/en/DocumentFormat/2-EasyEDA-Schematic-File-Format/index.html)：符号、引脚、导线、网络标签及文件结构。
- [嘉立创标准版多页原理图](https://docs.lceda.cn/cn/Schematic/Multi-Sheet/)：一个原理图支持多个页面，同名网络标签跨页连接，位号需全局唯一。
- [嘉立创标准版原理图设计管理器](https://docs.lceda.cn/cn/Schematic/Design-Manager/)：标准版集成 ERC、错误标志和刷新方式。
- [ESP32-S3-PICO-1 数据手册](https://www.espressif.com/sites/default/files/documentation/esp32-s3-pico-1_datasheet_en.pdf)：端子定义及参考电路。
- [MLX90393 Rev 012](https://www.melexis.com/-/media/files/documents/datasheets/mlx90393-datasheet-melexis.pdf)：UTDFN-8 端子及 0x10 地址。
- [LSM6DSOX](https://www.st.com/resource/en/datasheet/lsm6dsox.pdf)：Mode 1 接法。
- [BQ24074](https://www.ti.com/lit/ds/symlink/bq24074.pdf)、[TLV755P](https://www.ti.com/lit/ds/symlink/tlv755p.pdf)：供电、使能和外围要求。
- [GCT USB4105](https://gct.co/files/drawings/usb4105.pdf)：USB 接口引脚；本项目已有官方 KiCad 封装用于交叉核对接点编号。
- [TPD2EUSB30A](https://www.ti.com/lit/ds/symlink/tpd2eusb30a.pdf)、[TPD1E10B06](https://www.ti.com/lit/ds/symlink/tpd1e10b06.pdf)：ESD 端子和额定值。
- [MMBT3904](https://assets.nexperia.com/documents/data-sheet/MMBT3904.pdf)：B1/E2/C3 端子和 NPN 开关。
- [Johanson 2450AT18D0100001E](https://www.johansontechnology.com/docs/3791/Antenna-2450AT18D0100001E-Rev5.0.pdf)：四端天线及整机净空/调谐要求。
