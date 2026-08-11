# 交付文档：华沿 Elfin E05 机械臂操控 + 触觉传感器（跨项目复用）

> 目的：让另一个项目/会话不依赖本仓库上下文即可操控这台机械臂并接入传感器。
> 面向场景示例：毛刷运动控制——根据传感器信号调节压力，均匀刷曲面。
> 一切结论均为 2026-08-10 真机实测（Elfin E05 + 华沿控制柜），非纸面推断。
> 本文档路径：`/home/ethan/FYP/docs/handoff-e05-arm.md`

---

## 1. 网络连接（两头静态 IP，插线即用）

| 端 | 配置 | 说明 |
|---|---|---|
| 控制柜"第二口"(外部 LAN) | 静态 `192.168.0.10/24` | 示教器网络设置里配置 |
| 控制柜 `enp1s0(HuayanPAD)` 口 | **别动** | 示教器专用，改了平板会断联 |
| 笔记本有线口 | 静态 `192.168.0.100/24`，网关/DNS 留空 | NM 档案"有线连接 1"已配好，重启不丢 |

- 验证：`ping 192.168.0.10`；`nc -zv 192.168.0.10 10003`（SDK 命令口）。
- 两个口独立服务：示教器与外部电脑可同时在线，互不干扰。
- ping RTT 实测 ~0.13ms。

## 2. SDK 本质：明文 TCP 协议（无 .so 依赖）

- 所谓华沿 SDK 就是往 `10003` 端口发 ASCII 命令：`"命令名,0,参数...,;"`，
  回复逗号分隔。另有 xmlrpc 口 `20000`（日志等，非必需）。
- **官方纯 Python 实现已 vendor**：`/home/ethan/FYP/src/brushbot/backends/vendor/CPS.py`
  （2774 行，任意 Python 3 可用，仅标准库）。新项目直接拷这个文件。
- vendor 带两个本地补丁（**别用原始下载版**，在 `~/下载/python乱码目录/`）：
  1. `sendAndRecv` 畸形回复时原版 `os._exit(0)` 杀进程 → 改抛 `HRIFProtocolError`；
  2. `HRIF_ReadActTcpPos` 原版切错段返回**关节角** → 已改切正确段 [7..12]。
- 参考手册：`/home/ethan/FYP/reference/HuayanRobot_Library_Python_V1.0.11.0.pdf`。
  注意手册描述 .so 版 API：`result[]` 不含错误码，纯 Python 版列表头部多一个
  错误码 `'0'`，**所有字段下标整体 +1**。

### 常用 API 速查（线上单位一律毫米/度；返回列表首元素 `'0'`=成功）

```python
from CPS import CPSClient, RbtFSM
c = CPSClient('192.168.0.10')          # 构造即连接
c.HRIF_ReadCurFSM()                    # ['0','33'] → 33 = Standby 就绪(可动)
c.HRIF_ReadActTcpPos()                 # ['0', x,y,z,Rx,Ry,Rz] 字符串, mm/度
c.HRIF_ReadActJointPos()               # ['0', J1..J6] 度
c.HRIF_MoveJ / HRIF_MoveL(...)         # 点位运动, 坐标系名用 "TCP"/"Base"
c.HRIF_StartServo(0.02, 0.05)          # 开伺服流: 周期 20ms, 前瞻 50ms
c.HRIF_PushServoP(pose, ucs, tcp)      # 流式推位姿 — 注意 ucs 在前 tcp 在后
                                       #   (与 PDF 手册参数序不同, 以源码为准!)
c.HRIF_SetOverride(0.25)               # 设速度倍率 25% (示教器同步显示)
c.sendAndRecv('ReadOverride,0,;')      # 读倍率 (vendor 无封装, 裸发命令)
```

## 3. 两种运动模式

**MoveL/MoveJ（点位）**：发目标点，控制器自己规划执行。适合摆位/回零/趋近。
完成判定**不要用** `HRIF_IsMotionDone`（见坑 #2），轮询实际位姿做位置收敛判定
（<0.5mm 连续 3 次）。真机到位误差实测 <0.01mm。

**StartServo + PushServoP（流式伺服）**：约定固定周期后逐拍推目标位姿，控制器
实时跟踪。**闭环压力控制必须用这个**。硬契约：必须按约定周期定频推送——
用绝对节拍时钟（`t0+i*dt` sleep-until，不是相对 sleep），参考实现
`/home/ethan/FYP/src/brushbot/runtime.py` 的 `RealClock`。

### 伺服定参（实测扫描结论，直接抄）

| 参数 | 值 | 依据 |
|---|---|---|
| 伺服周期 dServoTime | **0.02s (50Hz)** | 扫描 10/20/50ms×前瞻 50/100/200ms 的甜点 |
| 前瞻 dLookaheadTime | **0.05s** | 跟踪滞后最低 |
| 跟踪滞后 | ~40ms | 互相关实测（±5mm@0.5Hz 正弦） |
| 跟踪 RMS | ~0.07mm | 轨迹形状保真极好 |
| 每拍时间预算 | 读+写 p99 <3ms / 20ms 预算 | RTT p99 0.87ms |

规律：滞后 ≈ 0.6–0.8×前瞻 + 固定项；周期 50ms 时 RMS 翻倍（插值变糙）；
10ms 无收益。扫描数据：`/home/ethan/FYP/servo_scan_20260810/*.csv`。

## 4. 坑清单（每条都是真机踩出来的）

1. **速度倍率**：示教器全局倍率缩放 MoveL/MoveJ（这台默认曾是 **1%**——
   运动慢 100 倍，像卡死）。但**倍率不缩放 PushServoP 伺服流**（5% 与 25%
   实测逐字同结果）→ 伺服模式下倍率**不是安全网**，安全靠你自己的指令限幅。
   `SetOverride` 生效有亚秒延迟，读回要稍等。
2. **IsMotionDone 不可靠**：WayPoint 完成标志在发起运动的同一 TCP 连接内
   长期不置位（新连接一查就是 True）。完成判定用位置收敛。
3. **等待运动要用停滞检测**：距目标距离持续缩小就继续等，N 秒无进展才算失败
   （固定超时会被低倍率骗）。脚本退出**不会**取消已下发的运动。
4. **姿态角约定未完全验证**：Rx/Ry/Rz 的欧拉序没做过单轴对拍。安全策略 =
   **常量姿态直通**：启动时读当前位姿，姿态三字段原样写回，只改 XYZ。
   已知锚点：Rx≈180° = 工具 Z 轴朝下（垂直姿态）。
5. **字段布局**：`ReadActPos` 回复 [1..6]=关节角、[7..12]=TCP 位姿、
   [13..24]=工具/用户坐标（全零=未标定工具）。手册 §3.6.1 对应关系 +1。
6. **工具坐标未标定**：当前控制的是法兰不是刷尖。装刷子后要么在示教器标定
   工具坐标（PushServoP 的 tcp 参数传标定值），要么把偏移吸收进标定流程。
7. FSM 必须是 **33 (Standby)** 才能动；使能在示教器上操作。

## 5. 可复用代码（绝对路径）

conda 环境：`brushbot`（py3.10）。核心只依赖 numpy + 标准库。

| 文件 | 用途 |
|---|---|
| `src/brushbot/backends/vendor/CPS.py` | 协议客户端（拷走即用） |
| `src/brushbot/backends/huayan.py` | `HuayanBackend`：SI(米/弧度)↔线上(mm/度) 封装 + 伺服写 |
| `src/brushbot/runtime.py` | `RealClock`(绝对节拍定频) / `TactileExecutor`(定频闭环执行器: 空拍容忍/断线看门狗抬笔/全量记录, 可作闭环压力控制的骨架) |
| `examples/read_state.py` | 读状态机/关节角/位姿，`--watch` 实时监视 |
| `examples/move_test.py` | 安全动臂测试（限幅+确认+收敛判定） |
| `examples/bench_hrif.py` | RTT/时间预算 benchmark |
| `examples/servo_scan.py` | 伺服跟踪性能扫描（换刷子/负载后建议重跑） |
| `examples/write_air.py` | 完整示例：轨迹→定频伺服流（空中写字，可当模板） |

（以上均在 `/home/ethan/FYP/` 下；git 分支 `feat/huayan-backend`。）

## 6. 传感器（触觉磁传感）

**原理**：软触角/弹性体内嵌磁铁，形变改变磁场；MLX90393 三轴磁力计读
`(Bx,By,Bz)`。压力越大形变越大，`|ΔB|` 越大——**信号是形变量的代理，不是
牛顿力**；需要标定映射到压深/压力（种子论文：Ren et al. Nat. Commun. 2025，
0.34N 基准出处，见 `/home/ethan/FYP/reference/`）。

**硬件链路**（FYP 项目为队友自制，新项目若同款可照抄）：
- MLX90393 (I2C, Burst+DRDY) → ESP32 → USB 串口，固件输出行格式
  **`t_us,Bx,By,Bz` @ 115200**，目标 ≥100Hz。
- 解析参考实现：`/home/ethan/FYP/src/brushbot/monitor/sources.py` 的
  `SerialSource`（含跨包半行处理）。

**信号处理链（顺序重要）**：
1. **基线**：`ΔB = B − B0`，B0 = 静置均值；温漂/重装会漂，每段重取。
2. **滤波**：控制环用 **EMA α=0.3**（`/home/ethan/FYP/src/brushbot/monitor/core.py`
   的 `EMA` 类），显示用可另配；铁律——**先滤 (N,3) 向量再取 norm**。
3. **接触判定**：`|ΔB| ≥ 3σ`（σ = 滤波后噪声标准差，静置实测）。
4. **必存原始三轴** `B_raw`，派生量可重算。
5. 标定：分档压深记 `(z, Bx,By,Bz)` → `|ΔB|↔z` 查表（参考
   `/home/ethan/FYP/docs/gate-experiments.md` E2 实验设计）。

## 7. 对"毛刷均匀刷曲面"项目的映射建议

这个任务 = FYP 里的"**恒定形变闭环**"（目标信号恒定），比 FYP 的时变提按
更简单。可直接复用的控制结构（`/home/ethan/FYP/src/brushbot/z_control.py`）：

```
沿曲面路径逐拍:  z_cmd = z_path(s) + z_ff + kp·S_cal·e + ki·S_cal·∫e
                 e = g_ref − |ΔB_meas|      # g_ref = 恒定目标形变
```

- `z_path(s)`：曲面名义轨迹（法向进给量叠加在它上面）；曲面弯曲处修正应沿
  **法向**而非世界 z——姿态若要随曲面法向变化，必须先做坑 #4 的姿态对拍。
- 输出安全钳照抄：非有限回退 + 绝对位置钳（最大压深）+ 单步速率钳。
- 执行骨架照抄 `TactileExecutor` 模式：定频 tick → 读传感器 → 算 z 修正 →
  PushServoP；断线看门狗（0.2s 无样本→沿法向退刷）必须保留。

## 8. 首次上机流程（新项目 bring-up 清单）

1. 插网线 → `ping 192.168.0.10` → `nc -zv 192.168.0.10 10003`
2. `python examples/read_state.py`：确认 FSM=33、位姿与示教器一致
3. 检查倍率：`sendAndRecv('ReadOverride,0,;')`，点位测试期建议 ≤25%
4. `python examples/move_test.py`：±10mm 安全动臂，验证 MoveL 链路
5. 装刷子后重跑 `examples/servo_scan.py`：负载变了，跟踪滞后/RMS 要复测
6. 传感器串口先单独验证（`monitor` 模块可直接当示波器用），再进闭环
7. **急停放手边；伺服模式安全=指令限幅（倍率无效，见坑 #1）**
