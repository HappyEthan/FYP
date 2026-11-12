# 软件结构

## 运行入口

从项目根目录执行 `python -m xz_control`，由 `xz_control/__main__.py` 调用 `app.main()`，创建 Qt 应用和主窗口。macOS 启动脚本先切换到仓库根目录，再使用根目录虚拟环境运行同一入口。

## 模块职责

| 模块 | 职责 | 主要关联 |
| --- | --- | --- |
| `xz_control/app.py` | 主窗口、控件状态、运动命令与电机串口连接 | 组合传感器、实验和协议模块 |
| `xz_control/protocol.py` | 命令构造、状态解析、参数范围校验、理想运动模拟 | 由主窗口和实验模块调用 |
| `xz_control/sensor.py` | 独立传感器串口、格式识别、时间跟踪、基线校准和曲线 | 提供当前数据和采样信号 |
| `xz_control/experiment.py` | 实验步骤调度、状态跟踪、CSV 与 JSON 文件写入 | 通过回调发送运动命令并读取设备状态 |
| `firmware/XZ_Controller/XZ_Controller.ino` | ESP32-S3 命令处理、双轴脉冲调度和心跳故障处理 | 使用 XZ1 串口协议与主机通信 |

## 数据流

```text
用户操作 → 主窗口 → XZ1 命令 → 电机串口 → ESP32-S3 → HBS57 / XZ 机构
                       ↑                     │
                       └──── 状态 / 确认 ────┘

传感器设备 → 独立串口 → 解析与校准 → 实时曲线
                              └──→ 实验记录

实验流程 → 主窗口提供的命令发送回调
         ← 电机状态与传感器样本
         → data/experiments/<时间戳>/
```

两路串口分别负责运动与传感器数据。模拟器在电脑端生成理想运动状态；实验记录要求真实设备连接。

## 开发与验证

包内使用相对导入；测试通过 `xz_control.*` 导入模块。测试中的串口替身和 Qt 离屏模式允许在不连接硬件时验证软件。

修改协议时，应同时检查 `protocol.py`、固件命令处理和相关测试；修改传感器格式时，检查 `sensor.py` 与 `tests/test_sensor.py`；修改实验调度或输出字段时，检查 `experiment.py` 与 `tests/test_experiment.py`。

`tests/run_firmware_tests.sh` 使用主机 C++ 编译器、Arduino I/O 替身和真实 AccelStepper 源码运行固件逻辑测试，不会上传固件。

## 目录迁移

原 `xz_control/README.md` 移至 `docs/user-guide.md`；固件和测试提升到根目录；截图移至 `docs/images/`；原 `xz_control/test_data/` 移至 `data/recordings/`。原根目录单轴测试程序归入 `firmware/examples/`，草图目录与 `.ino` 文件同名，便于 Arduino IDE 打开。

已有记录中的历史路径、时间戳和元数据保持原样。新实验默认目录为仓库根目录下的 `data/experiments/`，也可在界面中选择其他保存位置。
