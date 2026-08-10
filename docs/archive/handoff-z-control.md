# Handoff: Z 轴控制算法开发

> ⚠️ **本文档已被取代（2026-07-31 归档）**：Z 控制 Phase 0/1 已完成，现状总纲见 docs/handoff-z-phase1.md（其 §1.1 硬件状态表与 §3 V0 数据资产部分本文仍有参考价值）。

> 给下一个 session 的交接文档。
> 状态：ΔB 监控窗口已完工；V0 数据集已采集/分析；**Z 控制算法待开发**。
> 分支：`feat/deltab-monitor`（未 merge，18+ commits，40 tests green）

---

## 1. 项目当前状态

### 1.1 硬件

| 组件 | 状态 |
|------|------|
| E-Antenna（仿生磁化触角） | 已磁化，裸触角可用 |
| MLX90393 三轴霍尔传感器 | 已通，100 Hz，µT 输出 |
| ESP32-C3 + 固件 | 已通，串口 `t_us,Bx,By,Bz` 格式 |
| 毛笔本体装配 | ❌ 未集成 |
| Elfin5 6-DOF 协作臂 | ❌ 未到位 |

### 1.2 软件

| 模块 | 状态 |
|------|------|
| `src/brushbot/monitor/` — ΔB 实时监控窗口 | ✅ 完成 |
| `src/brushbot/tactile/` — 触角合成磁学模型 | ✅ 可跑 |
| `src/brushbot/controller.py` — 开环位置控制器 | ✅ B0/B1 已交付 |
| `tests/test_monitor_*.py` — 40 tests | ✅ 全绿 |
| Z 轴闭环控制 | ❌ **待开发** |

---

## 2. 你需要开发什么

### 核心问题

**毛笔接触纸面后，如何用 ΔB 信号控制 Z 轴压深，实现稳定的提按闭环？**

输入：ΔB 三轴信号（100 Hz，µT）
输出：机械臂 Z 轴位移指令（m）
目标：跟踪目标提按曲线 `g_press(s)`，使形变量（|ΔB|）稳定在期望值

### 控制架构（已设计，待实现）

来自 `docs/gate-experiments.md` §0：

```
z_cmd = z_ff(g_d) + Kv·∫(g_d − g_meas)dt
        ↑ 前馈输出的是 z（mm），不是牛顿
```

- **前馈** `z_ff(g_d)`：由 `ΔB↔z` 标定曲线求逆，给"想要这个形变 → 压到哪个 z"
- **反馈**：低增益积分项修正残差
- **关键认知**：**力不进控制环**。控制量是运动学量（形变），牛顿仅用于论文对标

### 分步路线

```
Step 1: 拿到 E2 标定曲线 C: ΔB = f(z)  → 得 z_ff 和 S(z)
Step 2: 单轴纯法向压入 PID/积分控制 → 恒定 |ΔBxy| 闭环
Step 3: 拖拽解耦 → 先把拖拽分量从 ΔB 里剥掉，只留提按分量进控制
Step 4: 时变提按曲线跟踪 → 完整 z_cmd = z_ff + Kv·∫(g_d−g_meas)
```

---

## 3. 已有数据资产

### 3.1 V0 数据集（裸触角，自由手）

路径：`delta_b_v0_20260724/`（5 条有效记录）

| 文件 | 动作 | 样本 | B0 (µT) |
|------|------|------|----------|
| `20260724_142504_idle_r01` | 静止 10s | 1002 | (298.1, 705.9, −5526.6) |
| `20260724_143839_line_lr_r02` | 横线左→右 | 2410 | (270.4, 711.3, −5508.6) |
| `20260724_144949_line_rl_r01` | 横线右→左 | 1300 | — |
| `20260724_144151_circle_cw_r01` | 圆顺时针 | 1846 | — |
| `20260724_144546_circle_ccw_r01` | 圆逆时针 | 2057 | — |

### 3.2 关键数值（来自 `docs/deltab-v0-analysis.md`）

| 指标 | 值 |
|------|-----|
| 噪声底全带宽 | σ = (3.21, 3.12, 5.30) µT，|σ| = 6.94 µT |
| 噪声 3Hz 低通 | |σ| = 2.36 µT |
| 信噪比峰值 | 67–136×（信号比噪声大 2 个数量级） |
| 方向可分性 | line 157.5° / circle 172.5°（>60° 判据） |
| 回零残差 | 12–39 µT（噪声 2–6×，E3 迟滞线索） |
| 跨记录 B0 漂移 | ΔBx: 56, ΔBz: 93 µT |

### 3.3 反推的硬件灵敏度门槛

| 目标分辨率 | S 必须 ≥ |
|------|-----|
| 1.0 mm | **11.8 µT/mm** |
| 0.5 mm | **23.7 µT/mm** |
| 0.2 mm | **59.1 µT/mm** |

**这是验收硬件的数字**，E2 标定后对照即可判 E0 过不过。

### 3.4 V0 数据的诚实边界

- ✅ 能做：接口验证、信噪比评估、方向可分性、管线联调
- ❌ 不能做：**任何毫米级/牛顿级的定量标定**——这批是自由手、无压深标签
- 要拿到 `S(z)` 和 `z_ff`，**必须等 V1 纯法向压入数据或实机 E2**

---

## 4. 关键代码路径

```
src/brushbot/
├── monitor/
│   ├── core.py         # RingBuffer, Baseline, EMA, derive()
│   ├── sources.py      # SerialSource, ReplaySource, ArraySource, synth_writing_B()
│   ├── recorder.py     # V0 格式录制
│   └── window.py       # PyQtGraph GUI 窗口
├── tactile/
│   ├── antenna_model.py    # 触角磁学正向模型: bent_centerline() + sensor_B()
│   ├── writing_tactile.py  # 写字运动 → 合成 ΔB: tactile_from_trace()
│   └── separability.py     # 压/拖可分性量化: dB_bend(), study()
├── controller.py       # OpenLoopController（开环，B1 产物）
└── config.py           # PAPER_Z, CHAR_ORIGIN, ARM_URDF 等

scripts/
├── analyze_deltab.py   # V0 分析脚本（噪声/SNR/方向/三轴结构）
└── make_replay.py      # 交互回放 HTML 生成器

tests/
├── test_monitor_core.py       # 7 tests
├── test_monitor_sources.py    # 15 tests
├── test_monitor_recorder.py   # 8 tests
└── test_monitor_contracts.py  # 10 tests

docs/
├── gate-experiments.md        # E0-E5 门禁实验说明
├── deltab-v0-analysis.md      # V0 分析报告
├── b0-b1-results.md           # B0/B1 开环写字成果
├── deltaB-control.md          # ΔB 控制设计（如果有的话）
└── handoff-z-control.md       # ← 本文档
```

---

## 5. 监控窗口快速启动

```bash
conda activate brushbot
cd /home/ethan/FYP
python -m brushbot.monitor
```

工具栏布局：
```
[串口] [回放] [合成]  端口  [连接]  [⟳重放]  [取基线(B)]  [●录制(R)]  [标记(M)]  [⏸暂停]
动作 [line_lr]  时窗 [10s]  滤波α [0.30]  XYα [0.06]  倍速 [1x]
```

键盘：`Space`=暂停 `B`=基线 `R`=录制 `M`=标记 `1-4`=换时窗 (2/5/10/20s)

上半：归一化 XY 单位圆（红点=当前形变方向，绿=接触，灰=悬空）
下半：ΔBx / ΔBy / ☐|ΔBxy|幅度 / ☐ΔBz 时序

回放 V0 数据：点「回放」→「连接」→ 选 `delta_b_v0_20260724/*.csv`

---

## 6. 触角正向模型（已可跑）

### antenna_model.py

```python
from brushbot.tactile.antenna_model import bent_centerline, sensor_B
# bent_centerline(theta_deg, L, N, azim_deg) → 弯曲线 (N,3)
# sensor_B(cl, MAG, scale, SENS) → (Bx, By, Bz) 在传感器位置
```

物理：磁偶极子 → 霍尔传感器，∝ 1/r³。输入弯角+方位 → 输出三轴 B。

### writing_tactile.py — 合成 ΔB 源

```python
from brushbot.tactile.writing_tactile import tactile_from_trace
# tactile_from_trace(trace (F,3)) → (dB (F,3), contact (F,))
```
用运动学算压深+拖拽→弯角→ΔB。**单位是内部任意值，不是 µT**——`synth_writing_B()` 里做了缩放。

### separability.py — 压/拖分解

```python
from brushbot.tactile.separability import dB_bend, unit_dir
# dB_bend(theta_deg, azim_deg) → 纯弯 ΔB 向量
# unit_dir(azim_deg) → 该方位的单位 ΔB 方向
```
投影法：把 ΔB 投到标定的"提按方向"上→提出提按分量；剩余的是拖拽。要求 θ（压-拖夹角）近 90°。

---

## 7. E2 标定：拿到控制参数的前置条件

### 需要的数据

纯法向压入（不横拖），从接触点 z0 起，按 0.2mm 分档下压，每档待稳记 `(z, Bx, By, Bz)`。

### 从标定曲线 C 得到的

1. **灵敏度** `S(z) = ∂|ΔB|/∂z` — 曲线的导数（不是单一数字）
2. **前馈** `z_ff(g_d)` — 曲线求逆："要这个 |ΔB| → 压到哪个 z"
3. **工作区间** — 单调段、未饱和段
4. **增益调度** — `Kv_eff = Kv_nom / S(z)`（深压端 S 最小，需更大增益）

### 实现要点

- 标定文件格式：`(z_mm, |ΔB|, ΔBx, ΔBy, ΔBz)` 的 CSV
- 逆映射：`np.interp(g_target, |ΔB|_array, z_mm_array)`（需先验证单调）
- `z_ff` 不能超出标定范围——用 `np.clip` 加饱和保护

---

## 8. 已知风险与注意事项

| 风险 | 来源 | 缓解 |
|------|------|------|
| **装配态 B0 偏移** | Elfin 钢法兰 + 电机磁场 | B0 必须在装配态重取，不能用裸触角的值 |
| **灵敏度不足** | 触角刚度/磁化/距离 | 磁场 ∝ 1/r³，缩传感器-磁端距离最有效 |
| **动作后不回零** | 粘弹迟滞（E3） | τ 需实测；抬笔后等 τ 才重估基线 |
| **ΔBz 不小** | V0 分析 F 节 | 合成模型"轴向平"假设不成立——不能倚赖 ΔBz 做控制 |
| **拖拽混入提按** | E4 未做 | 投影法需 θ>60°，真值等纯压/纯拖实验 |
| **裸触角 vs 装配态** | 全局 | S、θ、B0、σ_z 全部要装配态复测；裸态只做 kill test |

---

## 9. 建议的第一次动作

1. 先跑监控窗口看数据：`python -m brushbot.monitor` → 回放一个 V0 文件，感受信号形态
2. 用合成源熟悉动作窗：工具栏切「合成」→ 连接，看 `synth_writing_B()` 造的笔-拖-抬周期
3. 读 `docs/deltab-v0-analysis.md` 和 `docs/gate-experiments.md` §E2 节
4. 在 `src/brushbot/` 下新建 `z_control.py`，写最简单的：从 buffer 取 ΔB → 算 |ΔBxy| → 和目标比 → 输出 z_cmd（先不连机械臂，纯 numpy 逻辑）
5. 写对应的 `tests/test_z_control.py`，用合成数据验证

## 10. 运行命令速查

```bash
conda activate brushbot
cd /home/ethan/FYP

# 跑所有测试 (40 tests)
python -m pytest tests/test_monitor_core.py tests/test_monitor_sources.py tests/test_monitor_recorder.py tests/test_monitor_contracts.py -v

# 分析 V0 数据
python scripts/analyze_deltab.py delta_b_v0_20260724 docs/assets/deltab_v0_analysis.png

# 生成交互回放 HTML
python scripts/make_replay.py delta_b_v0_20260724 deltab_replay.html

# 启动实时监控窗口
python -m brushbot.monitor

# 合成模型压/拖可分性
python -m brushbot.tactile.separability sep.png
```
