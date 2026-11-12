# Windows 脚本采集

`windows_acquire.py` 是无 GUI 的采集入口。它使用现有 `XZ1` 电机协议和 FYP 的原始磁场协议：

```text
t_us,Bx_uT,By_uT,Bz_uT
```

脚本启动后按以下顺序执行：

1. 发送 `ZERO ALL`，把当前机械位置记为软件坐标 `(0, 0)`，这一步不移动电机；
2. 电机静止，采集空载基线并计算 `B0` 与 `sigma`；
3. X 轴正方向移动 31,250 脉冲（125 mm）；
4. Z 轴上升 5,000 脉冲（20 mm）；当前固件的 Z 上升方向为负脉冲；
5. X 轴返回 31,250 脉冲；
6. Z 轴返回 5,000 脉冲，回到初始 `(0, 0)`；
7. 运动阶段持续记录 Bx、By、Bz、设备时间和电机软件位置。

换算依据是：1000 脉冲/转、4 mm/转，因此 250 脉冲/mm。

## 安装

在 PowerShell 中执行：

```powershell
cd D:\classify-cloth\xz-control
python -m pip install pyserial==3.5
```

电机控制器和磁传感器必须使用两个不同的 COM 口。运行前请关闭 Arduino 串口监视器等占用串口的程序。

## 运行：自动搜索并选择 COM 口

直接双击 [`start_windows_acquire.bat`](start_windows_acquire.bat)，或者在 PowerShell 中省略两个端口参数：

```powershell
cd D:\classify-cloth\xz-control
python .\windows_acquire.py
```

脚本会枚举当前可用的 COM 口，并显示设备描述、VID/PID 和 USB 序列号。先选择电机控制器，再选择磁传感器；第二次选择会自动排除已经选用的电机串口。输入 `R` 可以重新搜索，输入 `Q` 退出。设备重插后编号可能变化，应以设备描述和 VID/PID 为准。

选完端口后，脚本会询问 X 移动距离、Z 上升距离以及 X/Z 速度。距离单位是 mm，速度单位是脉冲/秒。直接回车使用默认值 `X=125 mm`、`Z=20 mm`、速度 `X=1000`、`Z=1000`；脚本会在开始前显示换算出的脉冲数。确认设备后按 Enter 才会发送设零和运动命令，输入 `Q` 可以取消。

运动过程中，控制台会实时显示当前阶段、X/Z 脉冲位置及毫米位置，还有原始 `Bx/By/Bz` 和减基线后的 `dBx/dBy/dBz`。显示单位使用 ASCII 的 `uT`，避免部分 Windows GBK 控制台无法显示 `µT`。

## 运行：直接指定 COM 口

例如电机是 `COM5`，传感器是 `COM6`：

```powershell
cd D:\classify-cloth\xz-control
python .\windows_acquire.py --motor-port COM5 --sensor-port COM6
```

显式指定端口适合批处理或确认设备端口固定的情况；不指定时使用上面的交互式搜索。

如果需要完全跳过距离输入和 Enter 确认，可加 `--no-confirm`；此时使用命令行中的 `--x-mm`、`--z-mm` 值。

默认运动参数为 1000 脉冲/秒、1000 脉冲/秒²。可以在运行时覆盖：

```powershell
python .\windows_acquire.py `
  --motor-port COM5 `
  --sensor-port COM6 `
  --x-speed-pps 800 `
  --z-speed-pps 500 `
  --x-accel-pps2 800 `
  --z-accel-pps2 500
```

如果实际 X 正方向相反，使用 `--x-sign -1`。如果实际 Z 上升方向相反，使用 `--z-up-sign 1`。如需 X 返回后保持 Z 在上方、不执行最后的 Z 回零，可以使用 `--leave-z-up`；默认会完整返回初始零点。

## 输出

默认输出到：

```text
D:\classify-cloth\xz-control\data\experiments_windows\<时间戳>\
```

每次运行包含：

- `sensor.csv`：每个有效串口样本一行，保存原始 `Bx/By/Bz`、`dBx/dBy/dBz`、设备时间、采集阶段、最近一次电机软件位置和 `sample_valid`；
- `metadata.json`：脉冲换算、运动顺序、基线、噪声、无效样本数、串口和结束状态；
- `events.jsonl`：设零、基线、每段运动、错误和完成事件。

基线在 `ZERO ALL` 后、电机开始运动前采集。程序保存 `Bx0`、`By0`、`Bz0`，并按 `dBx = Bx_real - Bx0`、`dBy = By_real - By0`、`dBz = Bz_real - Bz0` 计算。原始 B 值保留不变。质量规则与 FYP monitor 一致：有限值，并标记“跳出后在下一帧返回”的孤立大于 1000 µT 毛刺；原始样本不会被删除。

## 注意

脚本中的位置是 ESP32 固件发出的脉冲计数，不是编码器实测位置。`ZERO ALL` 也不是机械 HOME；当前平台没有由该脚本实现的限位、硬件急停或防下滑保护。首次运行应先把速度、加速度和距离调小，在确认方向和机械安全后再使用 125 mm / 20 mm 参数。
