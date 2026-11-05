---
project: 05-data-acquisition
status: active
---

# ESP32-S3 N16R8 + MLX90393 实验采集固件

## 适用硬件与源码

适用于采用 ESP32-S3-WROOM-1-N16R8 的通用开发板，通过板上原生 USB 接口连接电脑，按不同 I²C 地址采集 MLX90393 的原始三轴磁场。本文于 2026-10-19 按当前多地址源码核对。N16R8 表示 16 MB Flash 和 8 MB PSRAM；此模块使用 Quad-SPI Flash 与 Octal-SPI PSRAM。若模块实际标注为 WROOM-2、N16R8V 或其他型号，应按对应模块重新核对编译选项。模块存储器配置及 USB 选项见 [Espressif 官方说明](https://docs.espressif.com/projects/arduino-esp32/en/latest/troubleshooting.html)。

源码：[mlx_s3_n16r8_monitor_fixed90.ino](../../firmware/mlx_s3_n16r8_monitor_fixed90/mlx_s3_n16r8_monitor_fixed90.ino)。整个 sketch 目录包含主程序、`frame_guard.h`、`serial_commands.h` 和 `sketch.yaml`，使用 Arduino IDE 时应保留在同一目录。

固件沿用 [XIAO fixed90 固件](../../firmware/mlx_s3_monitor_fixed90/mlx_s3_monitor_fixed90.ino)的异常帧保护和重启协议，并增加多地址扫描、独立采集与按地址输出。两个头文件随新 sketch 独立保存，方便整目录复制烧录；以后若修改采集保护或重启命令逻辑，需要同步检查两个版本。

## 接线

先断电，再按 **GPIO 编号**连接：

| MLX90393 模块 | S3-N16R8 开发板 |
|---|---|
| VCC / VIN | 3V3，先确认传感器模块支持 3.3 V 供电 |
| GND | GND |
| SDA | GPIO4 / IO4 |
| SCL | GPIO6 / IO6 |

SDA、SCL 使用 3.3 V 电平，上拉到 3.3 V。新板按上述 GPIO4/GPIO6 接线。开发板若有两个 USB 接口，电脑连接标为 **USB / OTG / Native** 的原生接口；UART 接口的串口桥不输出此配置的 `Serial` 数据。USB 接口差异见 [Espressif 串口说明](https://docs.espressif.com/projects/arduino-esp32/en/latest/troubleshooting.html#serial-not-printing)。

固件在 GPIO4/GPIO6 扫描全部非保留 7 位地址 `0x08`–`0x77`，最多为 8 个应答地址建立槽位；只有成功初始化为 MLX90393 的槽位输出数据。多个传感器应使用不同地址并共用总线。固件不自动切换其他引脚；如需改接线，修改主程序中的 `SDA_PIN`、`SCL_PIN` 后重新编译，并同步诊断行中的引脚说明。

## 编译与烧录

依赖 Arduino-ESP32 开发板包和 **Adafruit MLX90393** 库及其依赖。开发环境已有依赖时无需重新安装；以下固定版本用于复现离线编译。ESP32 索引地址来自 [Espressif 安装说明](https://docs.espressif.com/projects/arduino-esp32/en/latest/installing.html)：

```bash
arduino-cli config add board_manager.additional_urls \
  https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core update-index
arduino-cli core install esp32:esp32@3.3.10
arduino-cli lib update-index
arduino-cli lib install "Adafruit MLX90393@2.0.5"
```

在仓库根目录执行。`sketch.yaml` 已设置默认 FQBN，无需在命令中重复板卡参数：

```bash
arduino-cli compile \
  --output-dir outputs/firmware/mlx_s3_n16r8_monitor_fixed90 \
  firmware/mlx_s3_n16r8_monitor_fixed90

arduino-cli board list

# 将 /dev/ttyACM0 替换为新开发板实际的原生 USB 串口。
arduino-cli upload \
  --port /dev/ttyACM0 \
  --input-dir outputs/firmware/mlx_s3_n16r8_monitor_fixed90 \
  firmware/mlx_s3_n16r8_monitor_fixed90
```

使用 Arduino IDE 时，打开新目录内同名 `.ino`，手动设置：

| 选项 | 值 |
|---|---|
| Board | ESP32S3 Dev Module |
| USB Mode | Hardware CDC and JTAG |
| USB CDC On Boot | Enabled |
| Upload Mode | UART0 / Hardware CDC |
| Flash Mode | QIO 80 MHz |
| Flash Size | 16 MB |
| PSRAM | OPI PSRAM |
| Partition Scheme | 16M Flash (3MB APP/9.9MB FATFS) |
| 串口监视器波特率 | 115200 |

原生 USB 的接线仍使用板上的 USB / OTG 口；菜单中的 Hardware CDC 是原生 USB 支持的一种工作模式。Flash 的 QIO 与 PSRAM 的 OPI 是两个独立选项。首次无法进入下载模式时，按住 BOOT，按下并释放 RESET，再释放 BOOT，重新选择枚举出的端口；首次烧录后如未运行，按一次 RESET。见 [Espressif USB CDC 烧录说明](https://docs.espressif.com/projects/arduino-esp32/en/latest/tutorials/cdc_dfu_flash.html)。

## 数据与实验兼容性

- I²C：400 kHz，超时 10 ms。
- 采样调度：每 3000 µs 一轮，先启动所有就绪传感器，再统一等待 2 ms 并逐个读取；约 333 轮/s 是调度目标。各地址的实际有效帧率以对应状态行的 `rate` 为准，设备数量、串口输出、重试及恢复都会影响帧率。
- MLX90393：Gain 1X、16 bit、OSR 0、Filter 0，与旧固件一致。
- 各地址先收集 100 个读数初始化自己的异常帧保护。至少一个传感器就绪后选择主传感器并输出 `READY`；优先使用已就绪的 `0x0C`，否则使用第一个就绪地址。失败槽位每 2 s 重试。
- 主传感器兼容数据行：`t_us,Bx_uT,By_uT,Bz_uT`。每个就绪地址另输出 `# sensor,0xNN,t_us,Bx_uT,By_uT,Bz_uT`，包括主传感器。磁场保留三位小数，时间戳来自原始 `uint32` 微秒计数器。
- 固件输出原始 B，不在板端扣除基线。`# sensor,` 是带地址的数据；其他 `#` 行用于诊断。每秒按地址报告有效帧率、丢帧、读错、重试及恢复计数，主传感器使用 `# fw=fixed90 rate=`，其余使用 `# sensor_status rate=`。
- 各地址独立保留非有限值、近零帧和突跳复读保护，连续失败触发对应传感器恢复。
- 发送 `REBOOT`，以 LF 或 CRLF 换行结束（Arduino 串口监视器选择 Newline 或 Both NL & CR）。固件先返回 `# fw=fixed90 reboot requested`，再重启、初始化并输出 `READY`。`fw=fixed90` 保留为兼容标识，板型通过启动诊断行区分。

`SerialSource` 不指定地址时继续读取主传感器的四列数据，并忽略带地址的重复流。读取其他传感器时，须显式选择对应地址，例如 `SerialSource(port="/dev/ttyACM0", address="0x0D")`；此时只接收该地址的 `# sensor,` 数据。旧固件没有该地址数据时不会自动回退到主流。实验入口是否暴露地址选项，需按对应入口的参数核对。

查看串口数据时，可运行：

```bash
arduino-cli monitor --port /dev/ttyACM0 --config baudrate=115200
```

示例输出（数值仅用于说明格式）：

```text
# MLX90393 multi-address fixed90 @ ESP32-S3 N16R8 (native USB)
# i2c scan SDA=4 SCL=6 range=0x08..0x77
# i2c addr=0x0C
# sensor ready addr=0x0C
# i2c addr=0x0D
# sensor ready addr=0x0D
# fw=fixed90 ready SDA=4 SCL=6 addr=0x0C
# format: # sensor,addr,t_us,Bx_uT,By_uT,Bz_uT
READY
1234567,30.000,-1080.000,-4480.000
# sensor,0x0C,1234567,30.000,-1080.000,-4480.000
# sensor,0x0D,1234600,42.000,-1050.000,-4400.000
```

## 离线验证

2026-10-19 使用 Arduino CLI 1.5.1、Arduino-ESP32 3.3.10 和 Adafruit MLX90393 2.0.5，当前多地址源码按 `sketch.yaml` 的默认 FQBN 编译通过。程序占用 351214 字节，全局变量占用 25060 字节。按上方编译命令可在 `outputs/firmware/mlx_s3_n16r8_monitor_fixed90/` 重新生成对应烧录产物。

2026-10-19 对当前多地址固件、串口源及重启流程运行以下测试，35 项通过，其中多地址测试会在主机上编译并运行包含当前 `.ino` 的 C++ 测试程序，覆盖扫描、按地址输出与恢复逻辑：

```bash
PYTHONPATH=src:. python -m pytest \
  tests/test_multi_address_firmware.py \
  tests/test_monitor_sources.py tests/test_sensor_reboot.py -q
```

以上为离线验证。本轮没有连接新板烧录或测量实际帧率，不能据此确认实板的固件版本或接线。

ESP32 开发板包还可能在 sketch 旁生成 `build/` 导出目录，该目录已在新 sketch 中忽略，不进入 Git。

## 实板检查

1. 串口出现新板启动行、`SDA=4 SCL=6` 和 `READY`。
2. 能连续收到主传感器四列数值及预期地址的 `# sensor,` 数据，移动对应磁体时该地址的三轴数据响应；按地址选择后不重复计入主流。
3. 连续观察至少 60 s，按地址记录有效帧率和 `drop/read_err/recovery`，再与旧板同一传感器及同一装配条件对比。
4. 在没有实验采集占用串口时测试 `REBOOT`，核对 ACK、新的 `READY` 和重启后的新时间戳。

编译和离线协议验证不能确认接线、供电或实测帧率；实验前需完成以上检查。
