# FYP 固件目录

本目录保存两套 ESP32-S3 固件。目录名直接写出目标板卡，烧录时不要把两套固件混用。

## 固件清单

| 目录 | 目标单片机/开发板 | 主要功能 | I2C 接线 |
|---|---|---|---|
| [`esp32s3_pico1_mlx90393_lsm6dsox_monitor_fixed90/`](esp32s3_pico1_mlx90393_lsm6dsox_monitor_fixed90/) | **ESP32-S3-PICO-1**，8 MB Flash + 8 MB PSRAM | MLX90393 多地址磁场采集 + LSM6DSOX IMU 姿态数据 | SDA=GPIO1，SCL=GPIO2 |
| [`xiao_esp32s3_mlx90393_monitor_fixed90/`](xiao_esp32s3_mlx90393_monitor_fixed90/) | **Seeed XIAO ESP32-S3** | MLX90393 fixed90 兼容采集 | 主接线 SDA=GPIO7/D8，SCL=GPIO8/D9；固件保留备用引脚探测 |

## ESP32-S3-PICO-1 IMU 固件

目录：`esp32s3_pico1_mlx90393_lsm6dsox_monitor_fixed90/`

- 编译目标使用 Arduino-ESP32 的 `ESP32S3 Dev Module` 配置，实际板上模块为 ESP32-S3-PICO-1。
- Flash 使用 8 MB，PSRAM 使用 OPI 8 MB，原生 USB CDC 开机。
- MLX90393 自动扫描并独立读取多个地址，当前实板地址为 `0x0C`、`0x0D`、`0x10`。
- LSM6DSOX 位于 `0x6A`，WHO_AM_I 为 `0x6C`；加速度量程 ±4 g，陀螺仪量程 ±500 dps，输出目标约 100 Hz。
- 串口输出 IMU 行：

  ```text
  # imu,t_us,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps,temp_C
  ```

- 串口命令：`IMU ON`、`IMU OFF`、`IMU?`、`REBOOT`。
- 当前版本只包含 I2C 传感器采集和 USB 串口输出，Wi-Fi/BLE 功能尚未加入。

可直接烧录的文件：

- `esp32s3_pico1_mlx90393_lsm6dsox_monitor_fixed90_8MB_merged.bin`：完整 8 MB 镜像，写入地址 `0x0`。
- `esp32s3_pico1_mlx90393_lsm6dsox_monitor_fixed90_8MB_app.bin`：仅应用镜像；需要同时使用同目录 `build/esp32.esp32.esp32s3/flash_args` 中的 bootloader、partition 和地址。

## XIAO ESP32-S3 旧版固件

目录：`xiao_esp32s3_mlx90393_monitor_fixed90/`

这套固件面向 Seeed XIAO ESP32-S3，只采集 MLX90393，保持旧的 fixed90 四列数据协议和 `REBOOT` 命令，不包含 LSM6DSOX IMU 代码。

## 编译与烧录

两套工程均使用 Arduino CLI。进入对应目录后可重新编译；IMU 工程的板卡配置已经写在 `sketch.yaml` 中：

```bash
arduino-cli compile --clean \
  firmware/esp32s3_pico1_mlx90393_lsm6dsox_monitor_fixed90
```

使用完整镜像时，ESP32-S3 进入下载模式后执行：

```bash
esptool --chip esp32s3 --port /dev/ttyACM0 write-flash \
  0x0 firmware/esp32s3_pico1_mlx90393_lsm6dsox_monitor_fixed90/esp32s3_pico1_mlx90393_lsm6dsox_monitor_fixed90_8MB_merged.bin
```

Windows PowerShell 使用 COM 端口。先运行 `arduino-cli board list`，将下面的
`COM7` 替换为当前实际端口：

```powershell
arduino-cli compile --clean firmware\esp32s3_pico1_mlx90393_lsm6dsox_monitor_fixed90
python -m esptool --chip esp32s3 --port COM7 write-flash `
  0x0 firmware\esp32s3_pico1_mlx90393_lsm6dsox_monitor_fixed90\esp32s3_pico1_mlx90393_lsm6dsox_monitor_fixed90_8MB_merged.bin
arduino-cli monitor --port COM7 --config baudrate=115200
```

Windows 需要安装对应的 USB 驱动。ESP32 原生 USB 在复位或进入下载模式后可能
重新枚举，烧录前应再次确认 COM 号。

串口监视器使用 115200 baud。原生 USB 端口可能在进入下载模式或复位后重新枚举，烧录前请用 `arduino-cli board list` 确认实际端口。
