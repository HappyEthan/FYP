# Spec: Z 控制实时滤波器对比与选型

> 日期：2026-07-29
> 分支：`feat/deltab-monitor`
> 前置文档：`docs/handoff-filter.md`（问题背景与约束）、`docs/deltab-v0-analysis.md`（噪声-带宽权衡）、`docs/superpowers/specs/2026-07-28-z-control-phase0-design.md`（ZController Phase 0）

---

## 1. 背景与目标

Z 控制信号链 `MLX90393 (100 Hz) → 滤波器 → ZController → z_cmd` 中滤波器一段为空。
全带宽噪声 σ_x = 3.21 / σ_z = 5.30 / |σ| = 6.94 µT 直接进控制环会被积分器累积。

**目标**：实现并定量对比三种逐样本实时滤波器（EMA / 2 阶 Butterworth / One Euro），
用 V0 数据产出对比矩阵与选型推荐，并使验证脚本可在装配态数据到位后直接重跑重新选型。

**非目标**：
- 装配态 E0 复测（需硬件在场，本项目纯软件）。
- 修改 ZController 或现有 EMA（GUI 用途）。集成方式为外部组合，控制环脚本自行接线：
  `dB_f = filt.update(dB_raw); z_cmd = zc.step(dB_f, g_d)`。
- 50 Hz 工频折叠（在 Nyquist 处折回 DC，数字滤波无解，交固件 ODR 层）。
- 机械臂运动引入的低频磁场漂移（与提按信号频谱重叠，交差分测量方案）。

## 2. 核心约束（继承 handoff §2.1）

| 约束 | 值 |
|---|---|
| 采样率 | 100 Hz（V0 实测 dt 中位数 9.999 ms，1–99 百分位 [9.999, 10.001] ms，均匀采样假设成立） |
| 目标信号带宽 | 3 Hz（提按动作） |
| 滤波器延迟份额 | ≲ 5–10 ms（总回路预算 ≲ 30 ms） |
| 相位预算 | 滤波器 + 积分器 + 系统延迟总相位滞后 ≤ 135°（留 45° 裕度），滤波器在 3 Hz 处贡献须量化 |
| 运行时依赖 | 零新增（scipy 未安装且不加入运行时依赖） |

## 3. 滤波器实现（`src/brushbot/filter.py`，新建）

两个类，API 与现有 `EMA`（`monitor/core.py:64`）保持一致（OneEuro 的 `update` 额外接受可选 `dt`，缺省行为与 EMA 形态相同），三通道独立：

```python
class ButterworthFilter:
    """2 阶 Butterworth IIR 低通 biquad，逐样本实时滤波。"""
    def __init__(self, fc: float, fs: float = 100.0): ...
    def update(self, x: np.ndarray) -> np.ndarray:
        """(3,) 或 (N,3) → 同形状。批量 = 逐行迭代，与单样本逐位一致。"""
    def reset(self) -> None: ...

class OneEuroFilter:
    """One Euro 自适应低通：静止时强降噪，快速动作时低滞后。"""
    def __init__(self, min_cutoff: float, beta: float, d_cutoff: float = 1.0,
                 fs: float = 100.0): ...
    def update(self, x: np.ndarray, dt: float | None = None) -> np.ndarray:
        """dt 为 None 时用 1/fs；传入真实 dt 时支持非均匀采样。批量输入时 dt 逐行等距应用。"""
    def reset(self) -> None: ...
```

**实现要点**：

- Butterworth 系数用 bilinear transform + 频率预畸变手写计算（~15 行），不依赖 scipy。
  测试中以硬编码解析参考值交叉验证（系数 + 若干频点幅相响应）。
- 首样本冷启动：与 EMA 相同语义，首次 `update` 直接取输入值，无跳变。
- **NaN 策略**：`update()` 收到含非有限值的样本时，**透传该样本（原样返回）且不更新内部状态**。
  理由：ZController 现有 NaN guard 依赖看到 NaN 才 freeze，滤波器不得吞掉；
  同时 IIR 状态被 NaN 污染将永久失效，必须隔离。下一个有效样本从上次有效状态无缝续接。

## 4. 对比脚本（`scripts/compare_filters.py`，新建）

一等交付物。输入任意 ΔB CSV（列格式 `t_us,t_s,dBx_uT,dBy_uT,dBz_uT`），输出对比矩阵、图表、markdown 报告。

**对比对象**：EMA(α=0.3，正确逐样本用法) / Butterworth(fc 扫 {5, 8, 10, 12} Hz) / One Euro(min_cutoff、beta 扫参，起点 min_cutoff=1 Hz)。

**指标矩阵**：

| 指标 | 数据 | 方法 |
|---|---|---|
| 降噪 σ_x/σ_y/σ_z/\|σ\| | idle | 滤波后求 σ；与 FFT 理想截断对照，差异须 < 10% |
| 3 Hz 相位滞后 (°) | 解析 | 频响公式；One Euro 报告慢/快两种速度状态的等效值 |
| 群延迟 / 阶跃到 ±5% 时间 (ms) | 解析 + 仿真 | 纳入 30 ms 延迟预算核算 |
| 动态跟踪 RMS 误差 (µT) | line/circle | 滤波输出 vs FFT 零相位参考的滞后误差 |

**CLI**：`python scripts/compare_filters.py <csv...> --out docs/filter-comparison.md`
默认跑 `delta_b_v0_20260724/` 全部五条数据。装配态数据到位后同一条命令重跑即完成重新选型。

## 5. 报告（`docs/filter-comparison.md`，脚本生成）

必须回答 handoff §2.5 四个数字问题：

1. 3 Hz 信号相位滞后多少度？（每滤波器/每参数）
2. 噪声从 |σ| = 6.94 µT 降到多少？
3. 滤波后等效 σ_z = σ_filtered / S？（S 待装配态标定，报告以参数占位并给出公式）
4. 滤波器贡献多少 ms 延迟？

并给出：**推荐滤波器 + 参数 + 选型理由 + 装配态重跑指令**。

## 6. 测试（`tests/test_filter.py`，新建）

- 阶跃响应：稳态收敛到终值 ±5% 以内，收敛时间与解析预期一致。
- 批量 (N,3) 与逐样本 (3,)×N 输出逐位一致。
- `reset()` 后重新冷启动，无历史残留。
- NaN 样本：原样透传、状态不污染、后续有效样本正常续接。
- Butterworth 频响 spot-check：系数与若干频点幅值对照硬编码解析参考值。
- One Euro：静止段输出方差 < 快速段（自适应行为可观测）。
- 现有全部测试无回归。

## 7. 验收标准

```
□ ButterworthFilter / OneEuroFilter 实现，API 与 EMA 一致
□ idle 数据滤波后 σ 与 FFT 理想截断差异 < 10%
□ compare_filters.py 可对任意 ΔB CSV 重跑，生成 docs/filter-comparison.md
□ 报告回答 handoff §2.5 四个数字问题，给出推荐滤波器 + 参数
□ 单测覆盖 §6 全部条目，现有测试无回归
□ 已知边界写入报告：50 Hz 折叠、机械臂低频漂移非滤波器可解
```
