# Runtime 集成：闭环执行链路（TactileExecutor）

> 设计日期：2026-08-05
> 状态：设计（已过 brainstorming，用户逐节确认）
> 关联：`docs/status-2026-07-31.md` §5.3（立项来源）、`docs/control-architecture.md`（三层架构与华沿 SDK 摘录）、`docs/superpowers/specs/2026-07-31-offline-target-pipeline-design.md`（StrokePlan 契约）、`docs/superpowers/specs/2026-07-30-z-control-phase1-design.md`（run_loop 语义基准）
> 范围：TactileExecutor + Sensor/Clock 协议 + Plant/Replay 彩排 + 安全层 + 记录 + HuayanBackend **接口契约**（实现推迟到硬件期）。**不含**：HuayanBackend 实现、MuJoCo UDP 桥、变速执行剖面。

---

## 1. 目标

把已验证的闭环算法从"数组世界"接进"时钟世界"：一条常驻执行链路，在真实时间里消费传感器流、驱动机器人后端，且其闭环语义与仿真验证过的 `sim_loop.run_loop` **逐位等价**（Phase 1 的全部结论自动继承）。纯软件先行：Replay/Sim 彩排今天可跑，真机只换注入件。

## 2. 已定案的设计决定

1. **HuayanBackend 推迟，本期只定接口契约**（§5）。理由：SDK `.so` 仅 py3.6/3.7 且任何调用需 TCP 连真控制器——现在写只能盲写，无法运行验证，违背本仓库"只交可验证代码"惯例。
2. **验收 = 语义对齐 + 墙钟冒烟**（§7 R1/R2）。
3. **方案 A：单线程定频 tick + 可注入 Clock**。100Hz 下 tick 预算 10ms，滤波+插值+查表微秒级，单线程绰绰有余；无锁无队列的确定性是逐位对齐测试的前提。多线程（方案 B）等真机实测出阻塞问题再考虑；`run.py`（方案 C）保持 5 行开环玩具不动，继续服务开环臂。
4. **目标序列开跑前预生成**：执行器启动时调一次 `plan.to_gd_series(...)` 铺出 (g_d(t), xy(t)) 数组，tick 只索引。复用已验收导出、未来速度剖面升级不动执行器、对齐测试与 `run_loop` 消费同一数组。
5. **传感器路径独立于 RobotBackend**：真机上 ΔB 走独立串口不经机械臂，新设 `TactileSensor` 协议；`RobotBackend`（read/write State/Command）原样沿用。
6. **执行器持有控制环独享的滤波实例**（EMA α=0.3），整段永不 reset——坑 2"控制/显示双实例"的落实处。

## 3. 组件设计（新建 `src/brushbot/runtime.py`）

### 3.1 协议

```python
class TactileSensor(Protocol):
    def read_new(self) -> list[np.ndarray]:
        """自上次调用以来的新样本, 每个 (3,) µT, 按到达顺序; 可为空列表(空拍)."""

class Clock(Protocol):
    def tick(self) -> tuple[float, int]:
        """阻塞到下一拍边界. 返回 (t_now_s, overrun): overrun = 本拍迟到的整周期数.
        NullClock 立即返回 (i*dt, 0) —— 离线模式."""
```

- `RealClock(fs=100.0)`：按 `t0 + i·dt` 绝对节拍 sleep-until-next（不用相对 sleep，避免漂移累积）；迟到超过一个周期记 overrun。
- 多样本拍：按到达顺序**逐个**喂滤波器（EMA 状态忠于样本流），执行器取最后输出。空拍：滤波器**不更新**（不喂假样本），控制器照常 step（用上一拍滤波值，g_d 继续推进）。

### 3.2 TactileExecutor

```python
class TactileExecutor:
    def __init__(self, plan: StrokePlan, ctrl: ZController, filt,  # EMA 实例, 执行器独享
                 sensor: TactileSensor, backend: RobotBackend, clock: Clock,
                 stroke_duration_s: float, fs: float = 100.0,
                 fixed_ori=(0.0, 0.0, 0.0), lift: float = 0.015,
                 stale_limit_s: float = 0.2):
        # 启动时: g_d_seq, xy_seq = plan.to_gd_series(stroke_duration_s, fs)

    def run(self) -> TickLog:
        """定频主循环, 跑完目标序列或安全中止. 返回全量记录."""
```

每 tick（与 `run_loop` 循环体逐语句同构——先读传感器＝上一拍指令的响应，再算新指令）：

```
t, overrun = clock.tick()
samples = sensor.read_new()
for s in samples: dB_f = filt.update(s)      # 空拍则沿用上一 dB_f
z_cmd = ctrl.step(dB_f, g_d_seq[i])
backend.write(Command(tcp_pose=(xy_seq[i,0], xy_seq[i,1], z_cmd, *fixed_ori)))
log.append(...)                               # §3.4 全量
看门狗检查(§3.3)
```

### 3.3 安全层（全部逻辑三条）

1. **空拍容忍**：偶发丢拍不顿笔（见 §3.1）。
2. **看门狗**：连续 ≥ `stale_limit_s`（默认 0.2s = 20 拍）无新样本 → **安全中止**：下发抬笔指令（XY 保持当前，z = `ctrl.z_surface + lift`），停止循环，log 记 abort 原因与拍号。传感器断线时笔不能停在纸上。
3. **overrun 只记不停**：时序超期是健康指标不是错误（sleep 精度平台相关）；NaN 照旧透传给 ZController guard，执行器不拦。

### 3.4 TickLog

每拍一行：`t_s, dBx_uT, dBy_uT, dBz_uT（raw；空拍三列记 NaN，与 n_new=0 双重标记）, dBf_norm_uT, g_d_uT, x_m, y_m, z_cmd_m, frozen, n_new, overrun`。内存累积 + 显式 `save(path)` 落 CSV，附 `summary() -> dict`（overrun 率、最大抖动、abort 信息）。真机期若需防崩溃丢数据再改流式追加（YAGNI，此处注明即可）。

### 3.5 彩排注入件

- **PlantSensor / PlantBackend**（同模块或测试侧，共享一个 `sim_loop.Plant` 实例）：`backend.write(cmd)` → `plant.step(z)` 存结果；`sensor.read_new()` 返回 `[该结果]`。**首拍预热**：适配器以 `z0 = ctrl.z_surface` 初始化，首拍 `read_new()` 返回 `plant.step(z0)`——与 `run_loop` 首迭代（`z_cmd` 初值为 `z_surface`）逐语句一致，杜绝对齐测试的 off-by-one。适配层零语义——测试断言其产出与直接调 Plant 逐位一致。
- **Replay 适配器**：包 monitor `ReplaySource`（其 read() 本就返回批量样本），开环回放真实录音走传感器路径（backend 用 fake）。
- **sigma_f 握手**：执行器构造显式收 `noise_std`；彩排 CLI 从 `V0NoiseSource.filtered_sigma(EMA)` 现算；真机期换"启动静置采集现算"——机制同、来源异。

## 4. 脚本（新建 `scripts/run_tactile.py`）

- `--sim`：合成示范（synth_demo）→ `build_plan` → 执行器真时钟闭环 → 打印 R2 时序统计 + 接触段跟踪 RMS（无扰动下应与 Phase 1 基线 ~9.5% 同量级，第三道互证）→ TickLog 落盘（路径可指定，默认 scratch）。
- `--replay <csv>`：ReplaySource 回放 V0/示范 CSV，backend=fake，验传感器半链 + 时序统计。

## 5. HuayanBackend 接口契约（硬件期实现的规格，本期不写代码）

实现现有 `RobotBackend` 协议（read/write 签名不变）。层内职责：

1. 连接序列：`HRIF_Connect(0, IP, 10003)` → `HRIF_StartServo(0, 0, 0.02, lookahead)`（SDK 摘录见 `docs/control-architecture.md` §3，原始手册 `reference/HuayanRobot_Library_Python_V1.0.11.0.pdf`）。
2. **单位换算封死层内**：SDK 用毫米/角度，对外一律 SI（米/弧度）——与 CalliRewrite 的 ×1000 缺失坑对着干。
3. **50Hz 适配**：SDK 伺服周期 0.02s；执行器 100Hz 照跑，backend 内部每 2 拍取最新经 `HRIF_PushServoP` 下发（执行器无感知）。平均 +10ms 延迟计入回路延迟账——落在层 1 敏感性抽查（n_delay 1–4 拍）范围内，但真机 E 实验须实测确认。
4. **Python 版本预案**：`.so` 仅 py3.6/3.7，若与本项目 3.10+ 不兼容 → py3.7 子进程桥（socket/stdio），`RobotBackend` 契约不变故执行器零改动。
5. `read()` 的 `g_meas` 填 0（触觉不归机械臂后端管，走 TactileSensor）。

## 6. 测试策略（tests/test_runtime.py，全合成数据，无硬件依赖）

- Clock：NullClock 立即返回；RealClock 短跑 0.2s 拍数正确、时间轴单调。
- Plant 适配器：喂已知 z 序列 → ΔB 与直接调 Plant 逐位一致。
- **对齐（R1 测试版）**：单笔 StrokePlan，执行器（NullClock）z_cmd 与 `run_loop` 逐位相等，覆盖 freeze 穿越段。
- 空拍容忍：每 3 拍空 1 拍 → 不崩、z_cmd 有限、滤波器状态与"只喂真样本参考"一致。
- 双样本拍：滤波器按序消化，状态与逐个 update 参考一致。
- 看门狗：断供 → 恰在阈值拍触发 abort、末条指令为抬笔、log 记原因。
- NaN 链路回归：NaN → 透传 → frozen → z_cmd 有限。
- TickLog：列齐全、save 往返、overrun 计入、summary 正确。

## 7. 验收（两问两数字）

| # | 问题 | 判据 | 实测（2026-08-10, 本机 Linux desktop） |
|---|---|---|---|
| R1 | Runtime 闭环语义 ≡ `run_loop`？ | 同 StrokePlan/Plant/seed 下 z_cmd 序列**逐位相等**（零容差）。过关即继承 Phase 1 全部验证结论 | ✅ **逐位相等**（`tests/test_runtime.py::TestAlignmentR1`，`np.array_equal` 零容差，含 freeze 穿越段；反证：EMA α 改 0.31 即不等，测试有辨别力） |
| R2 | 真时钟 100Hz 跑得稳？ | 完整执行 ~10s StrokePlan：overrun 率 ≤1%、最大单拍抖动 ≤5ms（暂定值，平台相关；实测数字如实回填本表，超标时如实记录并给理由，不静默调判据） | ✅ `--sim` 1050 拍（10.5s）：**overrun 0（0.00%）、最大抖动 0.69ms**；接触段跟踪 RMS 11.5%（基线 ~9.5% 同量级）。`--replay` 附验：录音耗尽触发看门狗，恰在阈值拍抬笔中止 |

## 8. 文件变动

| 文件 | 动作 |
|---|---|
| `src/brushbot/runtime.py` | **新建**：协议 + Clock + TactileExecutor + TickLog + Plant/Replay 适配 |
| `scripts/run_tactile.py` | **新建**：--sim / --replay 彩排 CLI |
| `tests/test_runtime.py` | **新建** |
| `src/brushbot/run.py`、`backends/` | **不动** |
| `pyproject.toml` | 不变（零新依赖） |

## 9. 风险与边界

1. **R2 判据平台相关**：本机（Linux desktop）的 sleep 精度不代表最终部署机；数字挂"本机"标签，换机复测。
2. **50Hz 适配的延迟账是纸面推算**：真机 E 实验实测 servo 实际接收率与端到端延迟后复核（`deltaB-control.md` §6.4 老风险的最终裁决场）。
3. **Replay 模式不闭环**：回放的 ΔB 与 z 无因果，只验传感器半链——闭环彩排的唯一形态是 Plant 注入件，如实区分两者的证据力。
4. **执行器不做 XY 安全边界检查**：XY 来自已验收的 StrokePlan（数值有界），z 有控制器钳位；真机期若需工作空间围栏，加在 HuayanBackend 层（机器人侧本也有自己的限位）。

## 10. 交付物

1. `runtime.py` + CLI + 测试全绿（148 + 新增）
2. R1/R2 数字答案回填 §7
3. `docs/status-2026-07-31.md` §5 与记忆状态同步（收尾任务）
