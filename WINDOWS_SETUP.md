# Windows 适配版使用说明

这个 clone 面向核心串口采集、Monitor、StrokePlan 和真机实验脚本。MuJoCo 仿真与
展示版 Monitor 保留在仓库中，但不属于本适配版的验收范围。

## 安装

在 PowerShell 中执行：

```powershell
py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[monitor,windows,test]"
```

如果需要连接机械臂适配器：

```powershell
$env:ELFIN_DHAG_ADAPTER = "D:\path\to\elfin-dhag-adapter"
```

ESP32 连接后先运行 `arduino-cli board list`，将程序参数中的端口写成 `COM7`、
`COM10` 等当前端口。

## 核心检查

```powershell
python -m pytest tests\test_platform_support.py tests\test_local_ipc.py -q
python -m pytest tests\test_monitor_sources.py tests\test_monitor_core.py -q
python -m pytest tests\test_experiment_adapter.py tests\test_experiment_ipc.py -q
python scripts\run_ladder_experiment.py --dry-run --serial-port COM7
```

MuJoCo、`src/brushbot/exhibition*` 及对应测试不包含在上述 Windows 验收命令中。

## 可选外部数据

部分字形、`永` 字模板和字符书写测试需要本地的：

```text
data/makemeahanzi/graphics.txt
```

该数据集不进入 Git。将数据放入 Windows clone 后，再运行依赖字形数据的模板和
整字测试；缺少数据时，核心串口、IPC、文件锁和实验框架测试仍可运行。
