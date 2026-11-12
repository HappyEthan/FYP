> 历史交付文档：保留原版本说明与代码片段；当前软件使用方式以 [用户指南](../user-guide.md) 为准。附件链接已更新为现有仓库路径。

# ESP32-S3 + PFDE HBS57 XZ 双轴实验平台交付文档

**版本：** v1.0  
**日期：** 2026-11-09  
**当前交付状态：** 单轴闭环步进电机测试已成功，双轴、回零、限位、报警和正式扫描流程尚未完成。

## 1. 交付结论

本项目当前已经完成以下验证：

- ESP32-S3 可以正常烧录和复位；
- USB 串口可以正常工作；
- `ARM`、`STATUS` 等串口命令可以正常解析；
- 使用 AccelStepper 1.64.0 的单轴测试固件已经成功运行；
- 当前测试轴使用 GPIO35 作为 STEP/PU 控制，GPIO36 作为 DIR/DR 控制；
- 接线采用外部 5 V 共阳方式；
- ENA− 未接入，ALM 未接入；
- 当前机构按 XZ 双轴理解，Y 轴没有电机，不做换道。

“成功”指当前单轴测试固件能够完成控制链路验证。正式使用前仍需要补齐报警、限位、急停、回零和机械参数标定。

## 2. 项目范围和轴定义

当前实验平台控制对象为：

```text
电脑 USB
  -> ESP32-S3
  -> HBS57 控制信号接口
  -> PFDE 闭环步进电机

24 V 电源 -> HBS57 动力输入
电机编码器 -> HBS57 编码器接口
```

实际机构按 **X、Z 两轴**处理。Y 轴没有电机，因此不执行 Y 轴换道。原 `experiment_plan.md` 中关于 Y 轴换道的内容不属于当前控制平台的已实现功能。

## 3. 已知硬件信息

| 项目 | 当前已知信息 | 状态 |
|---|---|---|
| 主控 | ESP32-S3 开发板 | 已使用；具体模组后缀仍需确认 |
| 驱动器 | 普菲德/PFDE HBS57 闭环步进驱动器 | 已确认 |
| 电机 | 闭环步进电机，带编码器 | 已确认；完整型号、电流和扭矩未确认 |
| 机构 | XZ 双轴滑台 | 已确认；Y 轴无电机 |
| 动力电源 | 24 V / 4 A | 已知，双轴余量尚未验证 |
| 控制电源 | 外部 5 V | 用于共阳控制输入 |
| ENA | ENA− 未接入 | 当前测试不使用使能 |
| ALM | 未接入 | 当前测试无法由 ESP32 读取报警 |
| 脉冲分辨率 | 1000 pulse/rev | 用户已确认 |
| 测试库 | AccelStepper 1.64.0 | 当前固件使用 |

HBS57 手册给出的通用信息包括：DC 16–70 V 输入、推荐 24–48 V、5–24 V 控制输入、约 7–20 mA 逻辑输入电流、1000 p/r 编码器、400–51200 pulse/rev 细分范围，以及脉冲和低电平宽度至少约 2.5 μs。手册不同位置对最高脉冲频率写有 200 kHz 和 300 kHz 两种数值，因此正式系统按 200 kHz 保守设计。[PFDE HBS57 使用说明书](https://offer-product.oss-cn-beijing.aliyuncs.com/product/offer/attachment/null/file/subPdf_304871_173315_20220730-153703398.pdf)

PFDE 商品资料显示 57HSE 电机有 1.2、2.2、3 N·m 等系列和不同 HBS 驱动器组合，但目前不能用商品系列信息代替本台电机的铭牌参数。电机完整型号、额定电流、丝杆导程和是否带刹车仍待确认。

## 4. 当前共阳接线

当前控制信号应按以下关系连接：

```text
外部 +5V_CTRL ───── HBS57 PU+
                 ├─ HBS57 DR+
                 └─ HBS57 ENA+（若未使用 ENA，可不接）

GPIO35 ── 低侧 MOSFET/ULN/光耦 ── HBS57 PU−
GPIO36 ── 低侧 MOSFET/ULN/光耦 ── HBS57 DR−
GPIO37 ── 暂不使用                 HBS57 ENA− 未接
GPIO38 ── 暂不使用                 HBS57 ALM 未接
```

共阳的关键是外部 5 V 接三个正端，控制器分别下拉三个负端。ESP32-S3 GPIO 不能直接接 HBS57 的 5–24 V 输入，必须经过低侧开关或隔离接口。

如果使用 MOSFET/ULN 等非隔离低侧接口，ESP32 地和控制 5 V 负极需要按接口电路连接。如果使用光耦，则按光耦隔离侧布线。

ENA− 未接不会阻止当前脉冲测试。HBS57 手册建议不使用 ENA 时可将 ENA+、ENA− 悬空；如果 ENA+ 已经并入 5 V 而 ENA− 悬空，输入回路没有闭合，通常不会触发 ENA。ALM 未接不影响基本运动，但 ESP32 无法知道驱动器报警。

## 5. ESP32-S3 引脚注意事项

当前测试使用 GPIO35、GPIO36。若开发板是带 Octal Flash/PSRAM 的 ESP32-S3-WROOM-1/1U 或 WROOM-2 变体，例如 N8R8、N32R16V，GPIO35–37 可能被内部存储占用，不能作为外部运动控制口。此时应改用 GPIO4–7 或 GPIO8–11。[ESP32-S3-DevKitC-1 官方用户指南](https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32s3/esp32-s3-devkitc-1/user_guide_v1.0.html)

## 6. AccelStepper 测试固件

固件文件：`HBS57_AccelStepper_1_64_0_single_axis.ino`

库安装：在 Arduino IDE 的库管理器中安装 `AccelStepper` **1.64.0**。Arduino 库页面将该版本标为 V1.64.0。[Arduino AccelStepper 1.64.0](https://docs.arduino.cc/libraries/accelstepper/)

固件采用 AccelStepper 的 `DRIVER` 模式：

- STEP 使用 GPIO35；
- DIR 使用 GPIO36；
- 运动单位为脉冲；
- 速度单位为脉冲/秒；
- 加速度单位为脉冲/秒²；
- 最小脉冲宽度设置为 20 μs；
- ENA 和 ALM 不使用；
- `loop()` 中持续调用 `stepper.run()`；
- 当前默认最大速度为 100 pulse/s，默认加速度为 50 pulse/s²。

### 串口命令

串口波特率为 115200，行尾选择 `Newline`。

```text
ARM
DISARM
MOVE <relative_pulses> <speed_hz>
SPEED <speed_hz>
ACCEL <steps_per_s2>
STOP
ZERO
STATUS
HELP
```

例子：

```text
ARM
MOVE 100 100
STATUS
MOVE -100 100
STOP
DISARM
```

`MOVE` 是相对移动。电机设置为 1000 pulse/rev 时：

```text
MOVE 100 100
```

表示相对移动 100 个脉冲，即电机轴转 36°，速度上限为 100 pulse/s。

`STOP` 和 `DISARM` 是软件停止，不是硬件急停。正式平台必须增加独立急停回路。

## 7. 已完成的测试流程

### 7.1 烧录

烧录日志显示写入完成、校验通过并自动复位：

```text
Writing ... 100.0%
Verifying written data...
Hash of data verified.
Hard resetting via RTS pin...
```

### 7.2 串口启动

启动后可以看到 AccelStepper 固件帮助信息。此前基础固件的 `STATUS` 和 `ARM` 测试已经得到：

```text
armed=0 alarm=0 total_pulses=0
OK ARM
```

### 7.3 单轴运动

用户已确认使用 AccelStepper 测试固件后测试成功。下一步应记录实际测试条件，包括：

- 使用的脉冲数量；
- 速度和加速度；
- X 轴或 Z 轴；
- 是否接有机械负载；
- 24 V 电源电流；
- 驱动器指示灯状态；
- 电机正反向是否一致。

### 7.4 电源电流

测试过程中曾观察到 24 V 驱动器电源约 0.7 A。这个数值约等于 17 W，可能对应闭环驱动器的静止保持电流或自动降流状态；它不能单独证明脉冲是否到达。电机相电流由 HBS57 内部 PWM/闭环控制，不能直接等同于 24 V 电源表读数。

## 8. 无示波器时的脉冲确认方法

最可靠的方法是用示波器分别观察 GPIO35、低侧接口输出和 HBS57 PU−。没有示波器时，可以使用以下顺序：

1. 串口执行 `MOVE 100 100`，确认返回目标位置信息；
2. 在电机轴上做标记，观察 1000 pulse/rev 下是否转动约 36°；
3. 检查 HBS57 绿色电源灯和红色报警灯；
4. 确认 GPIO35 经过低侧接口，而不是直接接 PU−；
5. 如果仍无法判断，可使用临时 GPIO 慢速翻转程序验证 GPIO 和接口板。

## 9. 已知限制

当前固件和平台还存在以下限制：

- ENA 未接入，不能由软件控制电机释放/保持；
- ALM 未接入，软件不能自动检测驱动器故障；
- 没有限位、原点和急停输入；
- 还没有回零流程；
- 还没有软限位；
- 还没有 X/Z 双轴同步控制；
- 还没有丝杆导程和传动比标定；
- 目前不能把脉冲直接换算成毫米；
- 24 V/4 A 双轴同时运行的余量尚未通过实测验证；
- AccelStepper 适合当前低速原型和单轴验证，严格同步、高速脉冲和双轴插补建议后续改用 ESP32-S3 RMT 或硬件定时器。

## 10. 后续交付计划

1. 确认 ESP32-S3 模组后缀，确认 GPIO35/36 是否可用；
2. 记录电机铭牌、额定电流、编码器型号和刹车信息；
3. 确认 HBS57 的实际脉冲模式、细分和电机参数；
4. 接入第二个 HBS57，完成 X/Z 两轴独立点动；
5. 接入 ALM、限位、原点和硬件急停；
6. 确认 Z 轴垂直负载的防下滑措施；
7. 测量丝杆导程和传动比，建立 steps/mm；
8. 增加 `HOME`、`MOVE X Z`、软限位和故障锁存；
9. 接入 Hall 采集设备的开始/结束触发；
10. 进行固定速度、固定接触条件的织物扫描实验。

## 11. 交付文件

- [AccelStepper 单轴测试固件](../../firmware/examples/HBS57_single_axis_test/HBS57_single_axis_test.ino)
- [AccelStepper 固件说明](../hardware/accelstepper-notes.md)
- [GPIO35 慢速测试固件](../../firmware/examples/GPIO35_slow_blink_test/GPIO35_slow_blink_test.ino)
- [ESP32-S3 + HBS57 构建方案](../hardware/platform-setup.md)
- [单轴测试步骤](../hardware/single-axis-test.md)

## 12. 参考资料

- [PFDE HBS57 使用说明书](https://offer-product.oss-cn-beijing.aliyuncs.com/product/offer/attachment/null/file/subPdf_304871_173315_20220730-153703398.pdf)
- [ESP32-S3-DevKitC-1 官方用户指南](https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32s3/esp32-s3-devkitc-1/user_guide_v1.0.html)
- [Arduino AccelStepper 1.64.0](https://docs.arduino.cc/libraries/accelstepper/)
- [AccelStepper 官方文档](https://www.airspayce.com/mikem/arduino/AccelStepper/index.html)

## 附录 A：交付固件完整源码

下面代码与交付文件 `HBS57_AccelStepper_1_64_0_single_axis.ino` 一致。

```cpp#include <Arduino.h>
#include <AccelStepper.h>  // AccelStepper 1.64.0
#include <math.h>

// ===== HBS57 单轴：共阳 + 外部低侧驱动接口 =====
// GPIO35/36 不应直接接 HBS57 输入端，必须经过 NMOS/NPN/ULN/光耦接口。
constexpr uint8_t STEP_PIN = 35;  // 接口板输入 -> HBS57 PU-
constexpr uint8_t DIR_PIN  = 36;  // 接口板输入 -> HBS57 DR-

// 低侧接口若为“GPIO 高电平 -> 下拉导通”，保持 false。
// 若实际波形极性相反，再改为 true。
constexpr bool DIR_INVERT  = false;
constexpr bool STEP_INVERT = false;

constexpr float DEFAULT_MAX_SPEED = 100.0f;  // 脉冲/秒，首轮低速
constexpr float DEFAULT_ACCEL     = 50.0f;   // 脉冲/秒^2
constexpr uint16_t MIN_PULSE_US   = 20;      // HBS57 要求至少约 2.5 us

AccelStepper stepper(AccelStepper::DRIVER, STEP_PIN, DIR_PIN);
bool armed = false;

void printHelp() {
  Serial.println();
  Serial.println("AccelStepper HBS57 single-axis test");
  Serial.println("  ARM");
  Serial.println("  DISARM");
  Serial.println("  MOVE <relative_pulses> <speed_hz>");
  Serial.println("      example: MOVE 100 100");
  Serial.println("  SPEED <speed_hz>");
  Serial.println("  ACCEL <steps_per_s2>");
  Serial.println("  STOP");
  Serial.println("  ZERO");
  Serial.println("  STATUS");
  Serial.println("  HELP");
  Serial.println();
}

void printStatus() {
  Serial.print("armed=");
  Serial.print(armed ? 1 : 0);
  Serial.print(" current=");
  Serial.print(stepper.currentPosition());
  Serial.print(" target=");
  Serial.print(stepper.targetPosition());
  Serial.print(" remaining=");
  Serial.print(stepper.distanceToGo());
  Serial.print(" speed=");
  Serial.println(stepper.speed(), 2);
}

void emergencySoftwareStop() {
  // 软件停止；硬件急停仍需独立实现。
  stepper.moveTo(stepper.currentPosition());
  stepper.setSpeed(0);
}

void handleCommand(String line) {
  line.replace("\r", "");
  line.trim();
  if (line.length() == 0) return;
  line.toUpperCase();

  int split = line.indexOf(' ');
  String command = (split >= 0) ? line.substring(0, split) : line;
  String args = (split >= 0) ? line.substring(split + 1) : "";
  command.trim();
  args.trim();

  if (command == "ARM") {
    armed = true;
    stepper.enableOutputs();
    Serial.println("OK ARM");
    return;
  }

  if (command == "DISARM") {
    armed = false;
    emergencySoftwareStop();
    Serial.println("OK DISARM");
    return;
  }

  if (command == "STOP") {
    emergencySoftwareStop();
    Serial.println("OK STOP");
    return;
  }

  if (command == "ZERO") {
    if (stepper.distanceToGo() != 0) {
      Serial.println("ERR BUSY");
      return;
    }
    stepper.setCurrentPosition(0);
    Serial.println("OK ZERO");
    return;
  }

  if (command == "STATUS") {
    printStatus();
    return;
  }

  if (command == "HELP") {
    printHelp();
    return;
  }

  float value;
  if (command == "SPEED" && sscanf(args.c_str(), "%f", &value) == 1 && value > 0.0f) {
    stepper.setMaxSpeed(value);
    Serial.print("OK SPEED ");
    Serial.println(value, 2);
    return;
  }

  if (command == "ACCEL" && sscanf(args.c_str(), "%f", &value) == 1 && value > 0.0f) {
    stepper.setAcceleration(value);
    Serial.print("OK ACCEL ");
    Serial.println(value, 2);
    return;
  }

  long pulses;
  float speedHz;
  if (command == "MOVE" && sscanf(args.c_str(), "%ld %f", &pulses, &speedHz) == 2) {
    if (!armed) {
      Serial.println("ERR NOT_ARMED");
      return;
    }
    if (pulses == 0 || speedHz <= 0.0f) {
      Serial.println("ERR BAD_MOVE");
      return;
    }

    stepper.setMaxSpeed(fabs(speedHz));
    stepper.move(pulses);  // 相对移动，单位是脉冲
    Serial.print("OK MOVE target=");
    Serial.print(stepper.targetPosition());
    Serial.print(" speed=");
    Serial.println(speedHz, 2);
    return;
  }

  Serial.print("ERR UNKNOWN_COMMAND [");
  Serial.print(line);
  Serial.println("]");
}

void setup() {
  Serial.begin(115200);
  delay(300);

  // 共阳 + 低侧接口时，GPIO 默认不反相；若实测接口波形反相，修改上面的 STEP_INVERT/DIR_INVERT。
  stepper.setPinsInverted(DIR_INVERT, STEP_INVERT, false);
  stepper.setMinPulseWidth(MIN_PULSE_US);
  stepper.setMaxSpeed(DEFAULT_MAX_SPEED);
  stepper.setAcceleration(DEFAULT_ACCEL);
  stepper.setCurrentPosition(0);
  stepper.enableOutputs();
  emergencySoftwareStop();

  Serial.println("HBS57 AccelStepper 1.64.0 ready");
  Serial.println("STEP=GPIO35, DIR=GPIO36, ENA/ALM unused");
  Serial.println("Units: pulses and pulses/second");
  printHelp();
}

void loop() {
  // AccelStepper 必须被高频调用，不能在 loop 中长时间 delay。
  stepper.run();

  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    handleCommand(line);
  }
}
```
