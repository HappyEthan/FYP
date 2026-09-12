# 圆形磁触觉传感板 V0：工程草案

## 当前状态

**最新原理图版本为 [easyeda_std/README.md](easyeda_std/README.md) 所述 SCH-A1（嘉立创 EDA 标准版）。** 已生成标准版 JSON，完成本地序列化连通性检查；在线导入/ERC 尚待验证。以下 V0 连接表和占位图作为历史草案保留，GPIO10 充电控制、电源开关、VBUS 检测及外围数量以 SCH-A1 为准。

尺寸更正：早期小器件装箱仅排除了正面 RF 区，未限制背面天线净空，并且不覆盖 SCH-A1 新增元件。因此不能据此确认 φ18 mm 的完整电路可行或冻结笔杆尺寸。

**这是连接定义和主要器件几何研究，不是可生产 PCB。**

已完成：需求整理、官方器件资料核对、主控/传感器/USB/电池电源连接表、主要器件占位和可复算的几何检查、PDF 审阅图。

未完成：完整 KiCad 原理图、完整外围器件试排、布线、ERC/DRC、RF 匹配、热验证、实际续航和整机机械验证。没有生成 Gerber。本机未发现 KiCad。

## 本轮确认的设计输入

- 圆形 PCB 尽可能小，之后反推 3D 打印笔杆尺寸。
- USB-C 直接装在圆板边缘，由笔杆侧面插入数据线。
- 板载 2.4 GHz 天线，Bluetooth LE 和 USB 双模。
- 内置单节可充电电池，拔掉 USB 后独立工作；续航目标约 2 小时。
- 主控保留 ESP32-S3 系列；集成六轴 IMU 和 MLX90393。

## 候选器件与变化

| 位号 | 候选 | 外形/用途 | 尚需确认 |
|---|---|---|---|
| U1 | ESP32-S3-PICO-1-N8R8 | 7×7 mm；8 MB Flash、8 MB PSRAM、晶振集成 | 采购、LGA 焊盘/焊膏工艺 |
| U2 | MLX90393SLQ-ABA-011-RE | 2×2.5 mm UTDFN-8；磁触觉 | 供货、封装/坐标轴校对、装配距离 |
| U3 | LSM6DSOXTR | 3×2.5 mm，旋转后的名义外形；六轴 IMU | 最终封装核对、采样同步 |
| J1 | GCT USB4105-GF-A-060 | 8.94×7.35 mm，侧插 USB-C | 0.60 mm 壳脚与 0.8 mm PCB 的装配审核 |
| ANT1 | Johanson 2450AT18D0100001E | 3.2×1.6 mm；板载陶瓷天线 | 整机匹配、净空和地平面审核 |
| U4 | BQ24074RGTR | 3×3 mm；充电和电源路径管理 | NTC 网络、充电电流、散热 |
| U5 | TLV75533PDRVR | 2×2 mm；500 mA LDO | 低电量余量、热和瞬态验证 |
| U6 | TPD2EUSB30ADRTR | USB D+/D- ESD 候选 | 焊盘和布局审核 |
| BAT1 | 受保护的单节 4.2 V 充电锂电池，带 NTC | 初步按 350–400 mAh 评估 | 电芯具体型号、尺寸、放电曲线和安全规格 |

U2 是同一传感器家族的更小封装，不可直接沿用 QFN-16 的引脚：本候选订货型号的 7 位 I2C 地址是 **0x10**，旧板的 0x0E 不适用。若供货不合适，回退到 QFN-16 3×3 mm 方案并重新试排；两个封装不共焊盘。

## 电源方案

USB VBUS → BQ24074 IN；受保护电池 → BAT；BQ24074 OUT → TLV75533 IN；LDO OUT → 3V3。

选择线性方案是为了避免电源开关电感靠近磁传感器，不代表磁干扰已经消除。所有大电流回路、USB 壳体和热源仍需实测。

- USB-C CC1、CC2 各自通过 5.1 kΩ 下拉到 GND；不是充电专用的 6 针 USB-C。
- EN1/EN2 默认下拉，使用 BQ24074 USB100 模式；成功枚举且主机允许后才切到 USB500。需处理 USB suspend；不得直接默认向任意端口取 500 mA。
- ISET 初始候选 8.66 kΩ / 1%，典型快充电流约 103 mA；最终按电池允许电流和电阻/芯片公差确认。
- ILIM 预留约 3.24 kΩ；仅在核算允许后使用可编程限流模式，USB100/500 不靠这个电阻切换。
- 电池 NTC 必须贴近电芯或使用电池包自带 NTC；TS 接口不能用固定电阻绕过温度保护。网络阻值、NTC 曲线与电池允许充电温区尚未定稿。
- TMR 留空选择默认安全定时，不能接地禁用；ITERM 留空采用默认终止阈值。
- BQ24074 不替代电池包的过充、过放、短路保护。外接电池焊盘必须清楚标极性并有线缆应力释放。
- 无升压功能：低电量时，BAT → 电源路径 → LDO 的压降会降低 3V3。约 3.5–3.6 V 只能作为待验证的停机阈值起点，不能认为电池一直能放到 3.0 V。
- 用户电源开关和硬件欠压策略尚未完成；软件休眠不是彻底断电。电池装入前必须完成此项审核。
- 充电、USB 通信、BLE 发射都需分别测传感器噪声。首次机械/触觉标定建议不边充边测，再验证充电状态是否可用。

## 2 小时续航预算（不是实测）

以电池端平均电流 60/90/120 mA 为设计场景、可用容量系数暂取 0.70：400 mAh 对应约 4.67/3.11/2.33 小时。

120 mA 场景下，2 小时需要约 343 mAh，所以优先比较 350–400 mAh 电池。平均电流、低压提前停机、温度和容量衰减必须实测；若实际平均电流高于该预算，目标可能不达标。电池尺寸也会反过来限制笔杆，而不仅是 PCB。

## 尺寸研究的解读

脚本比较同一种分区方式下的 φ16、φ18、φ20 mm，不是全局最小化搜索。

- 使用真实封装名义外形；USB 焊盘/固定脚来自 KiCad 官方库并与 GCT 图纸核对。
- 普通芯片额外加 0.25 mm 的占位边界，这不等同于正式封装 courtyard。
- 天线先使用 4×6 mm 的保守评估区（来自该型号矩形参考布局）；迁移到圆板需要射频审核，不能把该区域当作圆板厂商批准的规则。
- 两面显示均采用同一顶视投影，背面不是面向 PCB 背面的镜像制造图；不能据此手工确定芯片方向。
- 对 USB 固定脚给背面留机械避让；完整过孔/背面焊接空间仍需 CAD 检查。
- 尚未纳入全部电容、电阻、ESD、电源开关、测试焊盘及走线空间。几何通过只表示本组主要器件不冲突。
- USB 插口处增加 0.2 mm 浅平边，壳体两角仍会超出圆形 PCB 包络；打印侧窗须局部避让。脚本报告包含 USB 壳体的径向包络，不能只报 PCB 直径。
- MLX 暂放背面圆心，仅为占位假设；实际敏感点、坐标轴、磁体间距必须随触角结构重新确认。

### 纳入外围器件后的第二级占位检查

`build_component_placement.py` 进一步加入 19 个电阻、12 个电容、RF 匹配位、USB/CC/VBUS ESD 候选、电池焊盘和 6 个测试焊盘。所有小阻容暂按 0402（公制 1005）估算，并加 0.15–0.20 mm 的算法间隔。

这仍然只是器件体/估算焊盘包络的二维装箱：**没有网络引导、走线、过孔、回流路径、差分阻抗、铜皮、散热、钢网或装配检查。** 搜索排下不等于可布线；搜索失败也不证明该直径绝对不可能。

输出 `generated/component_placement_checks.json` 和各直径 SVG 便于复核。只有完成正式 PCB 布线、DRC 和 3D 装配，才能冻结笔杆内径。

## 外围器件初始表

详细值见 `generated/passive_schedule.json`。关键项包括：USB CC 各 5.1 kΩ；USB D+/D- 串联电阻初始 22 Ω；I2C 上拉 4.7 kΩ；BQ24074 的 ILIM/ISET 初始 3.24 kΩ/8.66 kΩ；IN/BAT/OUT 分别预留 1/10/10 µF；LDO 输入输出各 1 µF；两颗传感器电源各 100 nF。

电池 NTC 网络、RF 匹配值、USB VBUS/CC 的最终 ESD 器件以及所有电容耐压/直流偏置均未冻结。0402 只是尺寸假设，需让贴片厂确认工艺和良率。

## 固件迁移要求

- U1 GPIO1/2 为 SDA/SCL；U2 为 0x10、U3 SA0 接地为 0x6A。
- GPIO4 接 MLX INT；GPIO5 接 IMU INT1；采样按各自 DRDY 打时间戳，不把两次依次读出的数据当作同步采样。
- USB 使用 GPIO19 D-、GPIO20 D+。下载恢复需要 GPIO0 和 EN，预留 UART0 TX/RX/GND 测试点。
- GPIO10 控制充电使能 CE（低有效），GPIO11/12 控制 EN1/EN2，GPIO13/14 读 PGOOD/CHG（开漏输出需上拉到 3V3）。
- GPIO6 可用于经分压后的电池电压检测；其电阻值、断电隔离与 ADC 校准待定。
- 不使用 PICO-N8R8 内部 PSRAM 占用的 28、38–42 号封装脚；不要把封装脚号与 GPIO 号混淆。
- BLE 为 BLE GATT 等协议，不是经典蓝牙 SPP。USB 与 BLE 应共享序号和采样时间戳。

## 文件和复现

- `CAD_HANDOFF.md`：进入正式 EDA 和 3D 结构设计时使用的尺寸、层叠、布局和验收约束。
- `scripts/build_review.py`：生成连接定义、几何检查和 PDF 审阅稿，不生成生产文件。
- `generated/connections.json`：逐针连接草案。
- `generated/geometry_checks.json`：主要器件占位检查。
- `generated/component_placement_checks.json`：加入外围器件后的随机装箱检查。
- `generated/passive_schedule.json`：外围阻容初始值和待定项。
- `generated/placement_18mm.svg` 等：双面器件投影预览；不是制造层。
- 项目根目录 `output/pdf/round_sensor_v0_review.pdf`：原理连接表、尺寸图、风险清单。
- `references/`：官方来源资料；ST PDF 下载失败时，以官方在线数据手册核对并保留链接，不伪造本地 PDF。

运行：使用带 reportlab 的 Python 执行 `scripts/build_review.py`。电路与尺寸仍需在正式 EDA 中重建/审查；PDF 不是 KiCad 自动导出的原理图。

## 官方来源

1. https://www.espressif.com/sites/default/files/documentation/esp32-s3-pico-1_datasheet_en.pdf （引脚表、外围电路、7×7 mm 封装）
2. https://www.melexis.com/-/media/files/documents/datasheets/mlx90393-datasheet-melexis.pdf （Rev 012；订货表、UTDFN-8 引脚和封装）
3. https://www.st.com/resource/en/datasheet/lsm6dsox.pdf （引脚表、Mode 1 接法）
4. https://gct.co/files/drawings/usb4105.pdf （USB 插座尺寸、壳脚和引脚表）
5. https://www.johansontechnology.com/docs/3791/Antenna-2450AT18D0100001E-Rev5.0.pdf （第 3 页净空；第 5 页圆板方案仅为参考，无相应评估板）
6. https://www.ti.com/lit/ds/symlink/bq24074.pdf （引脚、限流、NTC、充电与电源路径）
7. https://www.ti.com/lit/ds/symlink/tlv755p.pdf （DRV 引脚、输入输出电容、压降、热）
8. https://www.ti.com/lit/ds/symlink/tpd2eusb30a.pdf （USB 数据线 ESD）
9. https://gitlab.com/kicad/libraries/kicad-footprints （USB4105 和通用 LGA 封装；保留原始文件，不主张原创）
