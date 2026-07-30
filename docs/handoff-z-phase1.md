# Handoff: Z 控制环 Phase 1 —— 滤波接入、目标曲线管线与闭环验证

> 给下一个 session 的交接文档。写于 2026-07-29。
> 状态：滤波器库已完工并选型（过渡结论）；ZController Phase 0 已完工；**Phase 1（滤波进环 + 时变目标跟踪 + 验证）待设计**。
> 取代 `handoff-z-control.md`（其"Z 控制待开发"状态已过时）与 `handoff-filter.md`（滤波器已交付）中的相应章节。
>
> **分支/仓库状态（先读这个再动手）**：
> - `master`：本文档所在，领先 origin 一大批提交（网络 TLS 曾故障），恢复后 `git push`。
> - `feat/monitor-filter-ui`（HEAD `3b33196`）：监控窗口滤波 UI，评审通过但**待用户本机手动验收**（清单在 `docs/monitor-usage.md` 末尾 9+2 项），验收过再合 master。
> - MuJoCo→监控 UDP 桥：spec 已写（`docs/superpowers/specs/2026-07-29-mujoco-udp-bridge-design.md`），**未实现**。

---

## 0. 一句话任务

把已选型的实时滤波器接进 Z 控制环，建立"离线完美目标曲线 + 在线滤波反馈"的双通路架构，在仿真里验证滞后进环后的闭环稳定性与跟踪精度，并跑出"开环 vs 闭环"的对比数字（论文核心卖点的预演）。

## 1. 已有资产盘点

### 1.1 ZController Phase 0（`src/brushbot/z_control.py`，6 tests 全绿）

```
z_cmd = z_surface + z_ff(|ΔB_d|) + Kp·e + Ki·∫e     e = g_d − |ΔB_meas|
```

- 前馈为主（标定表 `calib_z_mm ↔ calib_abs_dB` 插值反查，非单调输入已按 abs_dB 排序修复），积分仅补残差，积分限幅 ±dz_margin。
- 接触/悬空判定：`|ΔB| < 3·noise_std 或 g_d < 3·noise_std` → freeze 积分器。
- NaN/Inf guard：非有限输入 → freeze 并返回安全 z_cmd（**滤波器 NaN 透传策略就是为触发它设计的，别破坏**）。
- Phase 0 验证：合成 plant 恒定 g_d 跟踪 RMS 2.1%（`z_control_demo.png`，`tests/test_z_control.py::test_step_tracks_constant` 的 `_plant`）。
- **Phase 0 故意没接滤波器**，吃原始 ΔB——这就是本期要补的。

### 1.2 滤波器库（`src/brushbot/filter.py`，master，31 tests）

- `ButterworthFilter(fc, fs=100)`：2 阶 biquad，含 `freq_response(f)` 解析频响。
- `OneEuroFilter(min_cutoff, beta, d_cutoff=1.0, fs=100)`：自适应截止，`update(x, dt=None)`，公开 `smoothing_alpha`。
- 两者 API 与 `monitor/core.py:EMA` 一致：`update((3,)|(N,3)) → 同形状`、`reset()`；首样本冷启动无跳变；**NaN 原样透传且不污染内部状态**。

### 1.3 选型结论（过渡）与量化工具

- `python scripts/compare_filters.py` 一条命令出 18 配置 × 4 指标 + Pareto 图 + 报告（`docs/filter-comparison.md`）。装配态数据到位换 CSV 重跑即重新选型。
- **当前推荐 EMA α=0.3**（|σ| 6.94→3.31 µT，3Hz 滞后 22.8°/17.2ms），但有三个保留（详见记忆 `filter-selection-provisional` 与报告注释）：
  1. settle 指标用 1 µT 小信号阶跃，对非线性 OneEuro 是最坏情形；修成 10–30 µT 代表幅值后**推荐预期翻转为 OneEuro mc=0.5 β=0.03**（σ=2.67、动态 RMS 双优）。
  2. spec 的滤波器延迟份额 ≲5–10 ms 与有效降噪在裸态数据下**互斥**（任何降噪够用的滤波器都超预算）——Phase 1 需要重划相位/延迟预算，而不是硬卡 10ms。
  3. 裸态数据是乐观下界；Pareto 图上"EMA 支配 Butterworth"依赖 1/f 噪声谱形状，装配态 EMI 可能翻盘。
- 教学文档 `docs/filter-tutorial.md`（概念、公式、逐节动手命令）——设计时当参考书用。

### 1.4 验证环境

- **合成 plant**（`test_z_control.py::_plant`）：Phase 0 用的一阶执行器 + 标定映射，最便宜，可扩展。
- **V0 真实噪声**（`delta_b_v0_20260724/*.csv`）：idle 段可以当噪声样本库注入仿真（比高斯白噪声真实——它有 1/f 特征）。
- **MuJoCo**：`contact_sim.py watch` 真实接触物理、ΔB 链路可信；`mj_write.py watch` 整臂写字但 Phase 3 接触 ΔB **数值发散不可信**（只看趋势）。UDP 桥实现后可以把仿真流进监控窗口看。
- 监控窗口（验收后）：滤波选择器 + 原始叠影，肉眼核对滤波行为。

## 2. 设计输入（数字表）

| 量 | 值 | 来源 |
|---|---|---|
| 采样率 | 100 Hz | 固件 |
| 信号带宽 | 3 Hz（提按） | gate-experiments E1 |
| 原始噪声 |σ| | 6.94 µT（裸态，乐观下界） | V0 idle |
| 滤波后 σ（候选） | EMA0.3: 3.31 / OneEuro(0.5,0.03): 2.67 µT | filter-comparison.md |
| 滤波滞后（候选） | EMA0.3: 17.2ms / Butter8: ~13ms / OneEuro 慢态相位 75°但动态 RMS 最优 | 同上 |
| 总回路延迟预算 | ≲30 ms（**滤波份额需重划**，见 §1.3 保留 2） | deltaB-control.md §6.4 |
| 相位裕度目标 | ≥45°（滤波+积分+系统延迟总滞后 ≤135°） | handoff-filter §2.2 |
| 灵敏度 S (µT/mm) | **未标定**（等装配态 E2）；σ_z_equiv = σ_filtered/S | gate-experiments |
| ZController 默认 noise_std | 7.0 µT（全带宽口径，**接滤波后必须改**） | z_control.py |

## 3. 本期要设计的四块

### 3.1 滤波器接入控制环（外部组合，已定案）

```python
filt = <选型配置>          # 控制环独享实例, 与显示滤波器无关
for dB_raw in stream:
    dB_f = filt.update(dB_raw)      # 先滤 (3,) 向量
    z_cmd = zc.step(dB_f, g_d)      # 控制器内部取 norm
```

铁律：先滤向量再取 norm（norm 非线性，先 norm 会整流出正偏置）；控制环滤波器**连续运行、笔画中途永不 reset**（freeze 期间也照常 update，保持跟踪）；NaN 照旧透传给 ZController 的 guard。

配套修改：`noise_std` 改为滤波后 σ（EMA0.3→3.31 或届时选型值），接触判定阈值 3σ 从 21 µT 降到 ~10 µT——这是降噪收益变现的地方，忘了改等于白滤。

### 3.2 离线目标曲线管线（前馈通路 + 开环 baseline，一石二鸟）

用户已确认的架构方向：示范录制的 raw ΔB → **离线零相位滤波**（`compare_filters.fft_lowpass` 现成可用）→ 干净 `g_press(s)` → 标定表反查 → `z_ff(t)` 前馈轨迹 → 进 `StrokePlan`。

- 目标曲线用理想滤波是**正确的**（数据完整，无因果性约束），实时滤波器只管反馈通路——两个滤波各司其职，别混。
- 纯开环执行这条轨迹 = 论文对照组（CalliRewrite 式），先建它，闭环是加法：两条实验臂共享前馈，差异干净落在"有无触觉反馈"。
- 没有真实示范数据前，可用合成 g_press 曲线（synth 源的思路）把管线跑通。

### 3.3 闭环 Phase 1：时变 g_d 跟踪 + 增益重调

- Phase 0 只验证了恒定 g_d；Phase 1 目标是跟踪时变 `g_press(s)`（0–3 Hz 起伏）。
- **滞后进环是新变量**：滤波器 ~15–30 ms 滞后加进回路后，Phase 0 的 Kp=0.5/Ki=0.1 可能不再安全，需在仿真里扫增益找稳定边界，留 ≥45° 裕度选工作点。
- freeze 逻辑与时变 g_d 的交互要过一遍：g_d 曲线穿越 3σ 阈值时（起笔/收笔）freeze 反复切换，确认无积分器抖动/毛刺。

### 3.4 验证方案（建议分三层，由廉到贵）

1. **合成 plant + V0 真实噪声注入**（最优先）：扩展 `_plant`，g_d 用合成提按曲线，噪声从 V0 idle CSV 里采样叠加（保真 1/f 谱）。跑矩阵：{无滤波, EMA0.3, Butter8, OneEuro} × {Kp/Ki 扫描}，产出跟踪 RMS 和稳定边界图。
2. **扰动注入**：标定表整体偏移 ±20%、纸面高度阶跃 ±0.5mm、传感器漂移斜坡——验证反馈通路真的在补开环补不了的东西（这就是论文对比数字的来源）。
3. **MuJoCo contact_sim 闭环**（可选，贵）：把 ZController 挂到 contact_sim 的触角上做真实接触物理闭环。注意其 ΔB 是模型任意单位，标定表要现场用仿真数据生成。

验证完成必须回答的数字（handoff-filter §2.5 风格）：

| 问题 | 怎么答 |
|---|---|
| 滤波接入后时变跟踪 RMS 是多少？比无滤波好多少？ | 层 1 矩阵 |
| 滞后进环后增益稳定边界在哪？工作点裕度多少度？ | Kp/Ki 扫描 + 频域核算 |
| 开环 vs 闭环在扰动下各偏差多少？ | 层 2 对比 |
| freeze 切换处有无毛刺？ | 起笔/收笔段仿真波形 |

## 4. 已知坑清单（评审攒下来的，别重踩）

1. `noise_std` 忘改 → 接触判定过度保守（§3.1）。
2. 控制环与显示的滤波器**必须是两个实例**；控制环实例永不 mid-stroke reset。
3. OneEuro 是非线性滤波器：没有单一"相位滞后"数字，频域增益裕度核算对它不适用——评它用时域仿真（层 1/2），别拿慢态 gd=3.5ms 进预算（那是线性化伪影，真实慢态相位延迟 ~70ms）。
4. settle/相位口径的坑见 §1.3；引用对比报告数字时连注释一起引。
5. `ZController.step` 的 Kp 项在 freeze 时仍然作用（只有积分被冻结）——设计时变跟踪时确认这是想要的行为。
6. 机械臂运动的低频磁漂移与信号同频段，滤波器无解（差分测量是硬件方案）；50 Hz 折叠同理。仿真验证时别把这类扰动"滤掉"了当成功。
7. 别在 `feat/monitor-filter-ui` 分支上开新工作；从 master 切新分支。

## 5. 代码路径地图

```
src/brushbot/
├── z_control.py                 # ZController Phase 0（本期主要改造对象）
├── filter.py                    # ButterworthFilter / OneEuroFilter（直接用，别改）
└── monitor/core.py              # EMA + FILTERS 工厂（显示用）

scripts/
└── compare_filters.py           # fft_lowpass(零相位参考)/load_csv/sigmas 都可 import 复用

tests/
├── test_z_control.py            # _plant 合成执行器（扩展起点）
└── test_filter.py               # 滤波器契约（回归保护）

docs/
├── filter-comparison.md         # 选型报告（含全部 caveat 注释）
├── filter-tutorial.md           # 概念参考书
├── superpowers/specs/2026-07-28-z-control-phase0-design.md
└── superpowers/specs/2026-07-29-filter-design.md
```

## 6. 建议的第一次动作

1. 读 `docs/superpowers/specs/2026-07-28-z-control-phase0-design.md` + 本文档 §1.3 的三个保留。
2. （可选 5 分钟）给 `step_settle_ms` 加幅值参数重跑选型，把"预期翻转为 OneEuro"变成实锤或证伪——Phase 1 选哪个滤波器就有依据了。
3. 走 brainstorming → spec → plan → subagent 流程设计 Phase 1（本仓库惯例），范围建议：§3.1 + §3.3 + 验证层 1/2 为一期，§3.2 离线管线可并入或单独一期（它无依赖可先行）。
4. 验收锚点：§3.4 的四个数字问题全部有答案，全部现有测试无回归。

## 7. 关联文档

- `docs/handoff-filter.md` — 滤波器立项背景（已完成，历史参考）
- `docs/handoff-z-control.md` — Phase 0 前的总盘点（硬件状态表仍有效）
- `docs/deltaB-control.md` — 控制总体设计（§6.4 延迟预算、§8.1 差分测量）
- `docs/gate-experiments.md` — E0/E1/E2 实验判据（S 标定在 E2）
- `docs/filter-quickcheck.md` — 滤波器成果检验命令
- 记忆：`filter-selection-provisional`、`monitor-filter-ui-pending-acceptance`、`architecture-strokeplan-interface`
