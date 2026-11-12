# HBS57 单轴 Arduino 首次测试步骤

## 0. 上电前检查

1. 断开 HBS57 的 24 V 动力电源，先只连接 ESP32、接口板和外部 5 V 控制电源。
2. 共阳接线：外部 5 V 接 PU+、DR+、ENA+。
3. GPIO35、GPIO36、GPIO37 必须经过 MOSFET、ULN 阵列或光耦，分别控制 PU−、DR−、ENA−；不能把 GPIO 直接接到 HBS57 输入端。
4. 当前 ENA−、ALM 未接入，程序已经设置 `USE_ENA=false`、`USE_ALM=false`。
5. 如果使用 MOSFET/ULN，ESP32 地和接口板控制地要按接口电路连接；如果使用光耦，按光耦隔离接法连接。
6. 如果 Z 轴承载负载，先用机械支撑固定，避免电机未通电时下滑。

## 1. Arduino 烧录

- 打开 `HBS57_single_axis_test.ino`。
- 选择实际 ESP32-S3 开发板；若没有准确型号，先选 `ESP32S3 Dev Module`。
- 串口波特率使用 115200。
- 使用原生 USB 时开启 `USB CDC On Boot`；也可以使用板上的 USB-UART 口。
- 选择正确串口并上传。若无法进入下载模式，按住 BOOT，按一下 RESET，再松开 BOOT 后重新上传。

烧录重启后，串口应看到类似：

```text
HBS57 single-axis test ready
ENA input: NOT CONNECTED
ALM input: NOT CONNECTED
Commands:
...
```

这时电机不会自动转动。

串口发送时只输入命令文字，例如 `STATUS`；不要发送代码块的反引号，也不要把右侧的英文说明一起发送。若收到未知命令，新版程序会打印实际收到的内容，例如：

```text
ERR UNKNOWN_COMMAND [STATUS xxx]
```

这样可以直接看出多余字符。

## 2. 不接 24 V 时测试串口

串口监视器设为 115200、行尾 `Newline`，输入：

```text
STATUS
```

预期：

```text
armed=0 alarm=0 total_pulses=0
```

输入：

```text
ARM
MOVE 10 10
```

此时程序只发 10 个、10 Hz 的测试脉冲。若有示波器或逻辑分析仪，应在 PU+ 与 PU−（或接口板的下拉输出处）看到 10 个脉冲。代码的有效高电平约 5 µs，满足 HBS57 的最低脉冲宽度要求。

## 3. 接入 HBS57 做最小运动测试

1. 确认电机线、编码器线和驱动器电源线没有带电插拔。
2. 把机械滑台放在中间位置，确保没有碰到限位；Z 轴负载要有支撑。
3. 给 HBS57 接通 24 V，观察驱动器电源指示灯。
4. 串口输入：

```text
ARM
MOVE 10 10
```

只观察是否有很小的转动或轻微位移。确认无异常后，再输入：

```text
MOVE 100 20
```

5. 反向测试：

```text
MOVE -10 10
```

负号表示反方向。首次测试不要直接发送大脉冲数。

## 4. 结果判断

- 有脉冲、无运动：检查 PU+/PU− 接线、5 V 控制电源、低侧接口极性，以及驱动器是否设置为单脉冲模式。
- 两个方向相同：把代码中的 `POSITIVE_DIR_SINK_ON` 改为 `false`，重新烧录。
- 完全没有脉冲：检查 GPIO35–37 是否被 ESP32-S3 模组的 Flash/PSRAM 占用；N8R8、N32R16V 等模组要改用 GPIO4–7 或 GPIO8–11。
- 驱动器红灯报警：立即停止脉冲并断开 24 V，检查电机相线、编码器线、电源极性和机械卡阻。
- `DISARM` 或 `STOP` 只能停止软件脉冲，不能代替硬件急停。

## 5. 测试结束

输入：

```text
DISARM
```

然后关闭 HBS57 的 24 V 电源。不要带电拔插电机线或编码器线。
