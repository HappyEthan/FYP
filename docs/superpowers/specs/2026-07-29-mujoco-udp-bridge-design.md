# Spec: MuJoCo 仿真 → 监控窗口 UDP 桥

> 日期：2026-07-29
> 分支：新分支 feat/mujoco-udp-bridge（从 master 切出；注意 feat/monitor-filter-ui 尚未合并，若其先合并则基于合并后的 master）
> 前置：`docs/mujoco-usage.md`（mj_write 四模式）、`docs/tactile-sim-usage.md`（contact_sim）、`src/brushbot/monitor/sources.py`（源契约）

---

## 1. 背景与目标

监控窗口的源抽象（非阻塞 `read() → [(t_s, Bx, By, Bz)]`）已支持串口/回放/合成，但 MuJoCo 仿真是预算轨迹回放，不是实时联动。本项目打通：**仿真里触角动，监控窗口 ΔB 对应动**。

```
MuJoCo 进程 (contact_sim / mj_write watch)          监控进程
  每步: centerline → sensor_B → ΔB_model             UdpSource.read()
        └→ DeltaBPublisher.step() ──UDP──────────→   parse_serial_line 复用
           "t_us,Bx,By,Bz\n" @ 100 Hz(仿真时间)      → RingBuffer → 基线/滤波/显示
```

进程间桥（而非进程内嵌）的理由：MuJoCo passive viewer 与 Qt 事件循环互不打架；**这个协议就是未来真机的形态**——以后 Elfin 控制环进程发数据、监控进程观察，同一条线。

**非目标**：
- ΔB 标定到真实 µT（模型是任意内部单位，等 E2 实测标定；本桥只保证"形变方向和趋势对应地动"）。
- TCP/重传/多客户端/鉴权（本机回环，丢包由监控测速自然暴露）。
- 反向通道（监控 → 仿真控制）。
- PyBullet 路径（scene.py/write_hanzi 不动）。
- mj_write Phase 3 接触 ΔB 的数值修复（已知 WIP 发散，照发并在文档标注）。

## 2. 协议

- UDP datagram，每帧一行 ASCII：`t_us,Bx,By,Bz`——**与串口固件格式完全一致**，监控端复用 `parse_serial_line`。
- `t_us` = 仿真时间 µs（非墙钟）。发布按**仿真时间 100 Hz 栅格**重采样：仿真时间每跨过一个 10 ms 栅格发一帧（取当前 ΔB）。这样无论仿真实际步长/播放倍速如何，监控端测得速率恒为标称 100 Hz，与整条管线（滤波器、录制）的 100 Hz 假设对齐。
- `B = scale · ΔB_model + B0_nominal`，`B0_nominal = (270, 710, -5500) µT`（与合成源同一惯例）。监控端连接后 1 s 自动取基线，B0 被扣掉，ΔB 显示自然归零。
- 默认地址 `127.0.0.1:9870`（本机回环；发布端目标与接收端 bind 均默认回环，不暴露内网）。

## 3. 发布端（`src/brushbot/tactile/udp_pub.py`，新建）

无 GUI、无 MuJoCo 依赖（纯 socket + numpy 格式化），可单测：

```python
class DeltaBPublisher:
    """把逐步 ΔB 按仿真时间 100 Hz 栅格重采样后以 UDP 行协议发布。"""
    def __init__(self, host: str = "127.0.0.1", port: int = 9870,
                 b0=(270.0, 710.0, -5500.0), scale: float = DEFAULT_SCALE,
                 rate_hz: float = 100.0): ...
    def step(self, sim_t_s: float, dB_model) -> int:
        """每仿真步调用。返回本次实际发送帧数(0..n; 仿真步长>10ms 时可能补发多帧)。"""
    def close(self) -> None: ...
```

- `DEFAULT_SCALE`：实现时用 contact_sim 一次标准按压实测确定，取"峰值 |ΔB| ≈ 400 µT"（与合成源量级一致），值和标定方法写进模块 docstring。CLI 可用 `--udp-scale` 覆盖。
- 非有限值样本跳过不发（防污染监控端）。
- 发送失败（socket 错误）静默丢帧不抛（仿真不能因监控未开而崩）。

**接线**（两处，均为 opt-in CLI 参数 `--udp [PORT]`，缺省不发布、零行为变化）：
1. `contact_sim.py watch`——在现有打印 ΔB 的循环处调 `pub.step(d.time, dB)`。ΔB 链路可信，是联动验证的基准。
2. `mj_write.py watch`——同样接线；ΔB 数值 WIP（文档已知发散），照发，docs 标注"趋势可看、数值不可信"。

## 4. 监控端（`sources.py` 新增 `UdpSource` + 窗口第 4 个源按钮）

```python
class UdpSource:
    """UDP 行协议源. 报文格式与串口固件一致, 复用 parse_serial_line."""
    def __init__(self, addr: str = "127.0.0.1:9870"): ...
    # start/stop/read/info/bad_lines —— 契约与 SerialSource 一致
```

- 非阻塞 socket（`setblocking(False)`），`read()` 收尽当拍全部报文，逐行 `parse_serial_line`，坏包计 `bad_lines`；`t_us` 首包归零逻辑与 SerialSource 相同。
- `info = {"name": "udp:<port>", "nominal_rate_hz": 100.0, "units": "uT", "addr": ...}`。
- 无 `seek` → 进度条自动隐藏（现有 `hasattr(src, "seek")` 判定，零改动）；非 ReplaySource → 允许录制（联动数据可录可分析）。

窗口（`window.py`）：源按钮排加 "UDP"（串口/回放/合成/UDP）；mode=="UDP" 时 `ed_port` 复用为地址输入框（显示默认 `127.0.0.1:9870`）；`cb_speed` 对 UDP 禁用（同串口）。`_sync_controls`/`_toggle_connect` 相应扩展。**滤波/录制/基线/门控管线零改动**——UdpSource 只是第 4 种源。

## 5. 测试与验收

**自动测试**（无 GUI，回环 socket 可测）：
- `DeltaBPublisher`：本地收端验证行格式可被 `parse_serial_line` 解析；栅格 pacing（语义：发出所有"≤ 当前 sim_t 且未发过"的栅格点，含 t=0——喂 sim_t 递增到 0.045 s 应收到恰好 5 帧，t_us = 0/10000/20000/30000/40000）；单步跨多栅格时补发多帧；scale/b0 数值正确；非有限值跳过。
- `UdpSource`：回环发 3 帧 → `read()` 返回 3 样本且 t 归零；坏报文计 bad_lines 不崩；未 start 时 read 返回空。
- 现有全部测试无回归。

**手动验收**（用户本机，追加到 docs/monitor-usage.md 清单）：
```
□ 终端A: python -m brushbot.tactile.contact_sim watch --udp; 终端B: 监控连 UDP → 触角按压时窗口 ΔB 对应起伏, 状态栏 ~100 Hz
□ 监控端取基线后 ΔB 归零; 滤波各档正常工作
□ mj_write watch --udp: 写字过程窗口有对应波形(数值不可信已知)
□ 关掉监控仿真不受影响; 关掉仿真监控显示测速掉零不崩
□ UDP 模式无进度条、倍速禁用; 可正常录制
```

## 6. 验收标准

```
□ DeltaBPublisher + UdpSource 落地, 自动测试覆盖 §5 全部条目
□ contact_sim / mj_write 的 --udp 均可用, 缺省不发布零行为变化
□ 监控端 UDP 按钮 + 地址框, 滤波/录制/基线管线零改动
□ DEFAULT_SCALE 标定方法记录在 udp_pub.py docstring
□ docs/mujoco-usage.md、docs/monitor-usage.md 更新(含 mj_write 数值不可信标注)
□ 现有测试无回归
```
