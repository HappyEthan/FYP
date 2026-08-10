# 滤波器模块

> ΔB 信号（MLX90393, 100 Hz）的实时低通滤波：压噪声、保提按信号（0–3 Hz），供显示与 Z 控制环使用。代码：`src/brushbot/filter.py`（Butterworth / OneEuro）、`src/brushbot/monitor/core.py` 的 `EMA`、对比脚本 `scripts/compare_filters.py`。过程细节见 docs/archive/ 与 git 历史。

## 做了什么

- 实现两个逐样本实时滤波器 `ButterworthFilter`（2 阶 biquad, 双线性变换 + 预畸变）与 `OneEuroFilter`（自适应一阶），接口与既有 `EMA` 一致：`update((3,)|(N,3)) → 同形状`、`reset()`，三通道独立。
- 统一 NaN 策略（filter.py 内）：含非有限值的样本**原样透传且不更新内部状态**——下游 ZController 靠看到 NaN 触发 freeze，滤波器不能吞；IIR 状态沾 NaN 会永久报废，必须隔离。
- `scripts/compare_filters.py` 对 18 个配置跑 4 类指标（idle σ / 3 Hz 相位与群延迟 / 10 µT 阶跃 settle / 动态 RMS，以 FFT 零相位截断为离线参考），自动生成 `docs/filter-comparison.md` 与 Pareto 图。
- 设计决策：滤波器放控制器**外部**组合（滤波后信号还要喂显示/日志）；**先滤三分量向量再取 norm**（先 norm 会把噪声整流成正偏置）；**录制永远存原始 ΔB**（滤波是下游的事，raw 数据可事后公平对比任何滤波器）。

## 选型结论

两口径并存，各自成立：

| 口径 | 定稿 | 关键数字 | 用途 |
|---|---|---|---|
| 孤立滤波指标 | **OneEuro mc=0.5 β=0.03** | idle \|σ\| 6.94 → **2.67 µT**；群延迟 3.5 ms；10 µT 阶跃 settle 100 ms；动态 RMS 7.09 µT | 显示 / 离线分析 |
| 控制环在环（Phase 1 层 1） | **EMA α=0.3** | \|σ\| 3.31 µT；3 Hz 相位滞后 22.8°；settle 80 ms；闭环 RMS **9.47%**（OneEuro 为 11.83%） | Z 控制环 |

**为何不矛盾**：孤立指标只看"降噪收益 vs 滞后代价"这枚硬币本身，OneEuro 静止时强降噪、动作时低滞后，确实是 Pareto 更优点。但放进闭环后，滞后按稳定性汇率兑换成增益损失——滤波器每多一点相位滞后，闭环可用 kp 上限就被压低一截，跟踪误差随之变大。OneEuro 慢态等效相位滞后 75.3°（EMA α=0.3 仅 22.8°），其降噪收益在环内被 kp 损失吃光变成净负债，故控制环反而定稿更"钝"的 EMA。选滤波器要先问"给谁用"。

选型规则（脚本内置）：动态 RMS ≤ 最优×1.25 且 10 µT 阶跃 settle ≤100 ms 者中取 idle |σ| 最小。

**两个口径都基于裸态数据，装配态 E0 复测前均非最终定稿**（见"已知局限"①）。

## 各滤波器用法与原理要点

信号在频域与噪声大部分分开：提按能量集中 0–3 Hz，噪声铺满 0–50 Hz（低频略强，1/f 特征）。低通滤波器按截止频率 fc（-3dB 点）放行慢成分、压制快成分；核心矛盾是 **fc 越低降噪越好但相位滞后越大**——天下没有免费的降噪。三种都是因果 IIR（只用当前与过去样本，可实时）；`scipy.signal.filtfilt` 与 FFT 截断是零相位离线方法，只能当"上帝视角参考"，不能上控制环。

### EMA（`brushbot.monitor.core.EMA`）

- 原理：`y = α·x + (1−α)·y_prev`，一阶低通。α 是"信任新数据的程度"——α 小 = 惯性大 = 强降噪但跟不上；α=1 不滤波。滚降 -6 dB/oct。α=0.3 等效 -3dB ≈ 5–6 Hz。
- 构造：`EMA(alpha=0.3)`，α ∈ (0,1]。
- 用法：`y = EMA(0.3).update(dB)`（dB 为 (3,) 或 (N,3)）。
- 坑：**当前实现无 isfinite 分支，一个 NaN 样本即永久毒化状态**（见"已知局限"②）；监控窗口是"每帧 reset+批量重滤"用法，与流式等价（实测差 <1e-5 µT）但语义不同，别混淆。

### Butterworth（`brushbot.filter.ButterworthFilter`）

- 原理：2 阶 biquad = 两级惯性串联，滚降 -12 dB/oct，通带最平坦（fc=8 时 3 Hz 处 |H|=0.991，幅值几乎无损，代价全在相位：3 Hz 滞后 31.1° ≈ 29 ms）。系数由双线性变换生成，`tan` 预畸变保证 -3dB 点精确落在 fc。
- 构造：`ButterworthFilter(fc, fs=100.0)`，fc ∈ (0, fs/2)；另有 `freq_response(f)` 查任意频率的复频响。
- 用法：`y = ButterworthFilter(8.0).update(dB)`。
- 坑：裸态数据上被 EMA Pareto 支配——这份噪声能量集中在低频，Butterworth 的高频陡滚降无用武之地却付双倍相位代价。**该结论依赖噪声谱形状**：装配态若电机 EMI 引入高频噪声，Butterworth 可能翻盘。

### OneEuro（`brushbot.filter.OneEuroFilter`）

- 原理：会自己变 α 的 EMA——截止频率 `fc = min_cutoff + β·|速度|`。静止时 fc≈min_cutoff（强降噪），快动作时 β 抬高 fc（低滞后跟手），正合提按"静止要稳、动作要快"。
- 构造：`OneEuroFilter(min_cutoff=1.0, beta=0.0, d_cutoff=1.0, fs=100.0)`；min_cutoff 管静止多稳，beta 管动作多跟手，d_cutoff 平滑内部速度估计（速度靠差分，不平滑会误触发）。
- 用法：`y = OneEuroFilter(0.5, 0.03).update(dB)`。
- 坑：非线性——没有单一"相位滞后"数字，报告里标注的 75.3°/3.5 ms 是慢态线性化等效值，不能与线性滤波器直接比相位，评价要看动态 RMS；settle 随幅值减小而变长（mc=0.5 β=0.03 实测：1 µT→380 ms，10 µT→100 ms，30 µT→50 ms），1 µT 是小信号最坏口径，不代表提按动作。

## 怎么跑对比脚本

全量对比（生成选型报告 + 两张图；报告属过程产物，输出到 docs/archive/）：

```bash
cd /home/ethan/FYP && python scripts/compare_filters.py --out docs/archive/filter-comparison.md
```

一分钟数字 sanity check（预期 raw ≈ 6.9，Butter8 ≈ 3.4，OneEuro ≈ 2.7 µT）：

```bash
cd /home/ethan/FYP && python -c "import sys; sys.path[:0]=['src','scripts']; from compare_filters import load_csv, sigmas; from brushbot.filter import ButterworthFilter, OneEuroFilter; d=load_csv('delta_b_v0_20260724/20260724_142504_idle_r01.csv'); print('raw      |sigma| = %.2f uT' % sigmas(d['dB'])[3]); print('Butter8  |sigma| = %.2f uT' % sigmas(ButterworthFilter(8.0).update(d['dB']))[3]); print('OneEuro  |sigma| = %.2f uT' % sigmas(OneEuroFilter(0.5, 0.03).update(d['dB']))[3])"
```

滤波器单测 + 全量回归：

```bash
cd /home/ethan/FYP && python -m pytest tests/test_filter.py tests/test_compare_filters.py -v && python -m pytest
```

装配态数据到位后重新选型（同一命令、换 CSV）：

```bash
cd /home/ethan/FYP && python scripts/compare_filters.py <装配态csv路径...> --out docs/archive/filter-comparison.md
```

## 已知局限与待验证

来自 2026-08-10 审计（详见 `docs/review-2026-08-10.md`）及既有边界：

1. **两口径选型均基于裸态数据，装配态 E0 复测前都勿定稿**。裸态 σ=6.94 µT 是乐观下界；装配后电机 EMI、振动等会改变噪声谱形状，孤立指标口径（重跑 `compare_filters.py`）与控制环在环口径（重跑 Phase 1 扫描）**两个都要重跑，不预设结论**。
2. **定稿的 EMA 实现归属倒置**：控制环主力滤波器 EMA 住在 `monitor/core.py`（GUI 包）而非 `filter.py`，被控制侧多处反向 import——待迁入 `filter.py`（宜与 `feat/monitor-filter-ui` 合并同批做）。~~NaN 策略缺失~~ **已修（2026-08-10）**：EMA 现与 `filter.py` 策略一致（非有限样本原样透传、不更新内部状态，断流恢复后闭环自动复活），并补齐 EMA 单体 NaN 测试与 `run_loop`×EMA 整链恢复测试。
3. **α=0.3 无单一常量源**：靠字面量在多处各写一遍同步，改参数极易漏改。待收敛为单一常量。
4. 滤波器解决不了的两件事（职责边界，非缺陷）：50 Hz 工频恰在 Nyquist、混叠折回 DC，数学上无解，交固件 ODR/硬件层；机械臂运动的低频磁干扰与提按信号频谱重叠（都在 0–3 Hz），需差分测量（硬件方案）。
5. 目标曲线与闭环测量活在两个频域基（fc=3 零相位砖墙 vs EMA α=0.3），该系统偏差已计入 Q3 误差但未单列为误差来源；`compare_z_arms.py --filter` 默认 OneEuro 与定稿 EMA 相反，装配态复测忘带参数会静默产出错误滤波臂的报告。
