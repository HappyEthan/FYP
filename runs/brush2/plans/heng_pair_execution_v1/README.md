# brush2 长横与短横：逐笔前馈＋PI执行

入口明确加载“中”实验的feedforward.json、settings.json、entry_profile.json与pi_profile.json。PI为kp=1、ki=0.1、修正上限±0.8mm，只作用于书写阶段。默认离线，不连接硬件；使用--execute仍保留原入口的RUN确认、输入批准、现场坐标校验、自动回等待位、基线检查和记录流程。

| 参数 | 目标文件 | 收笔目标 | 沿XY书写 | 名义完整运动 |
| --- | --- | --- | --- | --- |
| heng | heng_80mm_hidden_tail_v5/heng/strokeplan.npz | 100uT | 15.90s | 37.80s |
| short100 | heng_short_40mm_100_193_v1/heng_short/strokeplan.npz | 100uT | 10.68s | 32.38s |
| short50 | heng_short_40mm_end50_v2/heng_short/strokeplan.npz | 50uT | 10.68s | 当前表不能编译 |

参数中的short100明确指保留的100uT目标。当前前馈表范围约72.52..323.54uT，short50会在硬件连接前被原编译器拒绝，不会替换成100、裁剪或外推。50uT候选仍保留，需补齐低响应段标定再预检执行。另有75uT尾段方案，入口见下文；两者是独立候选。

在项目根目录逐笔运行：

```bash
cd /path/to/FYP
python runs/brush2/plans/heng_pair_execution_v1/run.py heng --dry-run
python runs/brush2/plans/heng_pair_execution_v1/run.py heng --execute
```

手动沾水，确认自动回位和书写区域净空后，在终端输入RUN。完成后更换纸张并重新准备下一笔。short100的预检和执行指令：

```bash
python runs/brush2/plans/heng_pair_execution_v1/run.py short100 --dry-run
python runs/brush2/plans/heng_pair_execution_v1/run.py short100 --execute
```

short50当前只用于复核越界原因：

```bash
python runs/brush2/plans/heng_pair_execution_v1/run.py short50 --dry-run
```

默认机械臂192.168.0.10、串口/dev/ttyACM0、115200波特，可用--ip、--serial-port、--baud显式指定。请使用brush2及匹配的既有TCP_brush/Base配置。进笔仍为30度到15度，接触旋转阶段仍有独立5mm反向移动；本入口不改变起收笔几何、目标或标定。曲线与不同倾斜方位沿用旧表仍属既有实验假设。

完整运动时间包含进笔、加载、抬笔和返回，基线与启动自动定位另计。书写段20秒上限不代表整个程序20秒结束。运行数据位于runs/brush2/当日日期/，包括磁数据、命令与独立10Hz实际TCP记录；实际TCP不参与反馈。

基线不足时，先关闭占用同一串口的Monitor或其他实验，保持笔离纸静止，再单独检查数据流：

```bash
python runs/brush2/plans/heng_pair_execution_v1/check_sensor.py --duration-s 12
```

该入口只打开传感器串口，不连接机械臂，保存原始串口字节raw_serial.log、sensor.csv和summary.json。结果中的baseline_candidate_ready仅表示末尾数据窗口满足既有帧数、时长、噪声、漂移和新鲜度条件；实际书写仍须在原入口独立确认等待位并重新采集基线。退出码0表示候选窗口通过，2表示仍有数据或质量问题。启动或结束处长时间没有帧，会记录在first_valid_delay_s和last_valid_age_s中，不通过降低400帧门槛绕过问题。

2026-10-21的13:08串口检查收到2854字节，但没有磁数据。raw_serial.log显示XIAO固件反复`init failed`，随后`LoadProhibited`崩溃重启。已确认使用XIAO ESP32-S3；实际SDA/SCL接线暂不清楚。当前安装的Adafruit MLX90393 2.0.5在重复`begin_I2C()`时删除I2C设备而不清空指针，存在释放后使用。XIAO固件现为每个候选地址只调用一次`begin_I2C()`，后续初始化重试与采集中恢复使用已有地址的退出模式、复位和重新配置命令。最初的初始化失败原因仍需硬件日志确认。

固件源码随仓库上传，编译产物保留本地。另一台电脑先按下文命令编译到`outputs/firmware/mlx_s3_xiao_init_retry_safe_v1/`，再退出Monitor、实验程序和Arduino串口监视器，在项目根目录刷入：

```bash
arduino-cli upload \
  --fqbn esp32:esp32:XIAO_ESP32S3:USBMode=hwcdc,CDCOnBoot=default \
  --port /dev/ttyACM0 \
  --input-dir outputs/firmware/mlx_s3_xiao_init_retry_safe_v1 \
  firmware/mlx_s3_monitor_fixed90
python runs/brush2/plans/heng_pair_execution_v1/check_sensor.py --duration-s 12
```

本修复版启动标记为`# fw=fixed90 build=xiao-init-retry-safe-v1`。日志会打印现有8组SDA/SCL探测结果，候选地址仍为0x0C、0x0D、0x1E、0x1F；不是任意引脚或任意地址的穷举。`ready SDA=... SCL=... addr=...`报告最终使用的接线。`no candidate ACK`表示该组脚位的候选地址无应答；`stage=driver/configuration/warmup failed`区分后续失败阶段。串口检查结束后，可在其输出目录的raw_serial.log查看这些行。修复版保留1X增益、16位分辨率、OSR0、FILTER0、400kHz总线、3000微秒采样周期和四列磁数据协议；物理数据流与基线质量须重新验证。

重新编译命令（只生成文件，不刷入）：

```bash
arduino-cli compile \
  --fqbn esp32:esp32:XIAO_ESP32S3:USBMode=hwcdc,CDCOnBoot=default \
  --build-path /tmp/fyp-xiao-init-retry-safe-v1-build \
  --output-dir outputs/firmware/mlx_s3_xiao_init_retry_safe_v1 \
  --jobs 2 firmware/mlx_s3_monitor_fixed90
```

## 在另一台电脑复现

从同一父目录克隆 FYP 和机械臂适配库；以下命令使用本次上传所在分支。Python 要求 3.10 或更高，可在已激活的虚拟环境中安装依赖。

```bash
git clone --branch codex/stroke-template-geometry-20261015 https://github.com/HappyEthan/FYP.git
git clone https://github.com/HappyEthan/elfin-dhag-adapter.git
python -m pip install -e ./elfin-dhag-adapter
python -m pip install -e './FYP[monitor]'
cd FYP
```

本次核对适配库版本为 `72ae70bae612e969ebe3c8de5cedd2d4324bc2b1`。先用 `--dry-run` 核对参数；实机使用自己的 `--ip`、`--serial-port`，并核对保存的 TCP、Base 和纸面位置。

| 方案入口（项目根目录内） | 可选参数 | 说明 |
| --- | --- | --- |
| `runs/brush2/plans/heng_pair_execution_v1/run.py` | `heng`、`short100`、`short50` | 原进笔流程；50uT候选当前预检拒绝 |
| `runs/brush2/plans/heng_pair_entry_load_then_rotate_v2/run.py` | `heng`、`short100` | 先30度加载，再旋转至15度 |
| `runs/brush2/plans/heng_tail_2mm_end75_v6/run.py` | `heng75`、`control75` | 75uT尾段，约2mm与原小尾端几何对照 |

例如：

```bash
python runs/brush2/plans/heng_tail_2mm_end75_v6/run.py heng75 --dry-run
```

四个生成脚本的预览步骤统一使用仓库内 `scripts/preview_strokeplan.py`，无需本机 Codex Skill。生成脚本会拒绝覆盖已有方案；复现实机运动直接使用已保存的目标和 `run.py` 即可。

XIAO 固件编译环境：Arduino-ESP32 3.3.10、Adafruit MLX90393 2.0.5、Adafruit BusIO 1.17.4。安装 Arduino CLI 后可准备依赖：

```bash
arduino-cli config add board_manager.additional_urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core update-index
arduino-cli core install esp32:esp32@3.3.10
arduino-cli lib update-index
arduino-cli lib install 'Adafruit MLX90393@2.0.5' 'Adafruit BusIO@1.17.4'
```

10月21日的原始磁场、控制日志、配置快照、分析及串口诊断保存在 `runs/brush2/2026-10-21/`。其中含中止实验，不能将所有记录视为成功结果。
