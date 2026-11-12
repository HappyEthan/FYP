# ESP32-S3 + PFDE HBS57 实验平台构建方案（v0.1）

日期：2026-11-09

## 1. 文档边界

`ESP32_S3_PFDE_HBS57_XZ_项目交接文档.md` 和 `experiment_plan.md` 是项目参考资料，不是可以未经核验直接执行的接线指令。本文把其中的已确认信息、待确认信息和网上资料分开记录。

## 2. 当前项目模型

控制链路应为：

```text
电脑 USB
  -> ESP32-S3
  -> 3.3 V 到 5/24 V 的隔离/开漏接口板
  -> HBS57（每轴一个）
  -> 闭环步进电机 + 编码器

24 V 电源 -> 保险/断路器 -> HBS57
急停/限位/报警 -> 硬件安全链 + ESP32 状态输入
ESP32 -> Hall 采集设备的开始/结束触发
```

当前按用户确认，实际机构按 XZ 双轴处理：Y 轴没有电机，不做换道。实验方案中关于 Y 轴换道的段落不纳入当前控制平台；后续若增加 Y 轴，再单独扩展驱动器和通道。

## 3. 网上核对到的器件信息

### HBS57

普菲德 HBS57 手册给出的信息：

- 驱动器是全数字式闭环二相步进驱动器，配 1000 p/r 光学编码器；
- 电源输入 DC 16–70 V，建议 24–48 V；
- 连续输出电流规格上限 7 A；逻辑输入电流约 7–20 mA；
- 控制端子为 PU+/PU−、DR+/DR−、ENA+/ENA−，报警端子为 ALM+/ALM−；
- 电机端子为 A+/A−、B+/B−，编码器端子为 EB+/EB−、EA+/EA−、VCC(+5 V)、EGND；
- 手册不同位置对最高脉冲频率写有 200 kHz 和 300 kHz 两种数值；在型号确认前按 200 kHz 的保守上限设计，细分档位为 400–51200 脉冲/转；
- 脉冲宽度和低电平宽度至少 2.5 µs，DIR 至少提前 5 µs 稳定；
- RS232 只用于专用调试软件和专用线缆，不应直接接 ESP32 UART。

网上商品页显示 PFDE 57HSE 家族有 1.2、2.2、3 N·m 等版本，也有带刹车和 HBS57/HBS57S/HBS57HD 的组合；这只能说明可能的产品家族，不能据此判断本台电机的电流、长度或是否带刹车。“N1.5”不能直接作为固件参数。

### ESP32-S3

如果主控板是 Espressif ESP32-S3-DevKitC-1：

- 板上同时有 USB-to-UART 口和 ESP32-S3 原生 USB 口；
- 原生 USB 使用 GPIO19/GPIO20，UART-to-USB 使用 GPIO43/GPIO44；
- GPIO4–18、GPIO21 等可作普通 I/O；
- 不能把 USB 正在使用的 GPIO19/20 或 UART 正在使用的 GPIO43/44 分配给运动控制；
- 原生 USB CDC 可作为电脑串口；脉冲应使用 ESP32-S3 的 RMT/硬件外设，不依赖主循环中的延时。
- 必须核对模组型号：若是带 Octal Flash/PSRAM 的 ESP32-S3-WROOM-1/1U 或 WROOM-2（例如 DevKitC-1-N8R8、N32R16V），GPIO35、36、37 会被内部 Flash/PSRAM 占用，不能作为外部运动控制口；此时应改用 GPIO4–18 等可用脚。

## 4. 推荐硬件实现

### 4.1 控制输出

HBS57 手册按 5–24 V 控制输入设计。ESP32-S3 是 3.3 V GPIO，所以先按“不能直连”设计：

- 5 V 控制电源接每个 HBS57 的 PU+、DR+，ENA+ 是否使用需按实物手册确认；
- PU−、DR−、ENA− 由 N 沟道 MOSFET/ULN 开漏下拉；
- ESP32 GPIO 只驱动 MOSFET/驱动阵列的栅极/输入；
- 每路默认关闭，复位和 USB 断开时不产生脉冲；
- ALM、限位、原点和急停信号通过光耦或带钳位的 24 V 数字输入模块进入 ESP32，不能把 5/24 V 直接送入 GPIO。

共阳接法的关键是“公共正端接外部控制电源”，不是把 ESP32 GPIO 当作公共正端：

```text
外部 +5V_CTRL  ── PU+  ─┐
                  DR+  ─┼─ 三个正端公共连接
                  ENA+ ─┘

GPIO35 ─开漏/光耦─ PU−   （STEP/PU）
GPIO36 ─开漏/光耦─ DR−   （DIR/DR）
GPIO37 ─开漏/光耦─ ENA−  （ENA，可先悬空）
ALM+/ALM− ─隔离输入─ GPIO38
```

用户已确认这里的公共正端来自外部 5 V，而不是 GPIO35；因此接线方向按标准共阳接法处理。GPIO35–37 仍应分别经开漏/光耦控制三个负端，不能直接把 ESP32 推挽 GPIO 接到 HBS57 输入端。

首轮单轴测试可暂不接 ENA，先用低速脉冲验证方向；HBS57 手册说明 ENA 有效时电机处于自由状态，且通常建议 ENA 端悬空，但具体版本要以驱动器铭牌和对应手册为准。

### 4.2 电源

现有 24 V/4 A 只有 96 W，不能在未知道电机额定电流、负载和加速度时认定能同时带动两轴。先只接一轴并测启动、加速和堵转/高负载时的电压跌落；若电机是常见 4 A 级 57HSE，两轴同时运行时应先按 24 V、8 A 以上的电源余量评估，再以实测数据定额。

ESP32 建议由 USB 或独立 5 V 降压供电，不能把 24 V 直接接到 3V3；电机电源、控制 5 V 和逻辑地按接口板方案布线，动力线和编码器线分开走线。

### 4.3 安全链

急停必须切断驱动器动力或硬件禁止运动，不能只发送 `STOP`。Z 轴若为垂直轴，先确认抱闸或机械防下滑措施；限位、原点、报警要有故障锁存，复位后不能自动重新运动。

## 5. 首个电机测试 GPIO

用户计划使用 GPIO35、36、37、38 进行首个电机测试。只有在开发板模组确认不是上述 Octal Flash/PSRAM 变体时，才按以下语义约定；实际固件保留可配置性：

| GPIO | 建议用途 | 方向 |
|---|---|---|
| 35 | X_STEP / PU 控制 | 输出，经开漏/光耦接口 |
| 36 | X_DIR / DR 控制 | 输出，经开漏/光耦接口 |
| 37 | X_ENA 控制 | 输出，经开漏/光耦接口 |
| 38 | X_ALM/FAULT 状态 | 输入，经光耦/电平转换 |

共阳接线时，HBS57 的 PU+、DR+、ENA+ 接外部 5–24 V 控制电源，ESP32 不直接接 PU−、DR−、ENA−；GPIO 只驱动低侧开关。GPIO38 若不是报警输入而是示波器测试点或触发输出，应在固件中改名，不能把 5/24 V 报警信号直接送入 GPIO。

## 6. 两轴暂定 GPIO 表（只作为模板）

| 功能 | GPIO |
|---|---:|
| A_STEP | 4 |
| A_DIR | 5 |
| B_STEP | 6 |
| B_DIR | 7 |
| A_ENA | 8 |
| B_ENA | 9 |
| A_ALM | 10 |
| B_ALM | 11 |
| A_LIMIT/HOME | 12/13 |
| B_LIMIT/HOME | 14/15 |
| 采集开始/结束触发 | 16/17 |
| 硬件急停状态输入 | 18 |

这里的 A/B 按当前机构对应 X/Z；Y 轴暂不分配 GPIO。首个电机测试优先使用上表 GPIO35–38，第二轴再从剩余安全 GPIO 中分配。

## 7. 固件路线

1. 第一阶段只用脉冲数，不换算毫米；实现 `ARM`、`DISARM`、`JOG`、`MOVE`、`STOP`、`ZERO`、`STATUS`。
2. 加入 `HOME`、`FAULT`、`CLEAR_FAULT`、`TRIG` 后，再接实验采集设备。
3. Arduino 可用于串口协议和低速验证；正式双轴同步脉冲使用 ESP32-S3 RMT/硬件定时器。
4. 运动换算公式固定为：

```text
steps_per_mm = pulses_per_rev × gear_ratio / screw_lead_mm
rpm = step_rate × 60 / pulses_per_rev
```

在确认丝杆导程、传动比和驱动器实际细分前，禁止把 `JOG 10` 解释成 10 mm。

## 8. 建议验收顺序

1. 确认 ESP32-S3 模组型号；若为 N8R8/N32R16V 等 Octal 变体，先把 GPIO35–37 改到 GPIO4–18 的可用脚。
2. 首轮 GPIO/波形测试不要求先改 DIP；真正给驱动器上电前，仍要核对电源、动力和编码器端子，避免接错。
3. 确认平台轴向以及 Z 轴是否垂直。
4. 断开电机动力，验证 5 V 控制电路和急停链。
5. 只接一个 HBS57、电机和编码器；低速发送 10–100 个脉冲。
6. 用示波器确认脉冲宽度≥2.5 µs、低电平宽度≥2.5 µs、DIR 提前≥5 µs。
7. 验证正反向、编码器反馈、ALM 和停止；再接第二轴。
8. 接入限位/原点和硬件触发，做单条 X 扫描。
9. 以实测位移标定 steps/mm，再设置软限位和速度/加速度。
10. 最后做双轴联动和正式织物试次采集。

## 9. 下一步需要的实物信息

- X、Y、Z 每个电机的铭牌正面照片；
- 每台 HBS57 的正面、端子标签和 DIP 拨码照片；
- ESP32-S3 开发板正反面和 USB 口标识；
- 24 V 电源铭牌；
- 滑台全景及各轴方向/限位/原点传感器照片；
- Hall 采集设备型号、触发输入电平和接口定义；
- 确认 GPIO38 的实际用途是 ALM/FAULT 输入、示波器测试点，还是采集触发输出。

## 10. 参考资料

- [PFDE HBS57 使用说明书](https://offer-product.oss-cn-beijing.aliyuncs.com/product/offer/attachment/null/file/subPdf_304871_173315_20220730-153703398.pdf)
- [Espressif ESP32-S3-DevKitC-1 官方用户指南](https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32s3/esp32-s3-devkitc-1/user_guide_v1.0.html)
- [Espressif ESP32-S3 系列数据手册](https://www.espressif.com/sites/default/files/documentation/esp32-s3_datasheet_en.pdf?hkey=EF798316E3902B6ED9A73243A3159BB0)
- [Espressif ESP32-S3 RMT 官方文档](https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-reference/peripherals/rmt.html)
- [PFDE 57HSE/HBS57 商品家族页面（仅用于识别候选型号）](https://i-item.jd.com/10068095852460.html)
