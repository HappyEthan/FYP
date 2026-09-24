---
project: 01-monitor-filter
status: archived
---

# 滤波器设计、教程与验收历史

滤波器原理、选型设计和早期验收记录。

孤立滤波指标与历史闭环中的选型是不同证据；当前梯子实验的正式滤波和统计口径仍未裁定。

## 章节导航

- [Spec: Z 控制实时滤波器对比与选型](#source-1)
- [滤波器手把手教程：从零理解你自己的设计](#source-2)
- [Handoff: Z 控制即時濾波器設計](#source-3)
- [滤波器成果检验命令](#source-4)

<a id="source-1"></a>

## Spec: Z 控制实时滤波器对比与选型

来源版本：`2026-07-29-filter-design.md`。

> 日期：2026-07-29
> 分支：`feat/deltab-monitor`
> 前置文档：`docs/01-monitor-filter/archive/filter-history.md`（问题背景与约束）、`docs/01-monitor-filter/sensor-v0-results.md`（噪声-带宽权衡）、`docs/04-robot-control/archive/z-control-design.md`（前馈表＋PI 控制思路）

---

<a id="source-1-1-背景与目标"></a>
### 1. 背景与目标

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

<a id="source-1-2-核心约束继承-handoff-21"></a>
### 2. 核心约束（继承 handoff §2.1）

| 约束 | 值 |
|---|---|
| 采样率 | 100 Hz（V0 实测 dt 中位数 9.999 ms，1–99 百分位 [9.999, 10.001] ms，均匀采样假设成立） |
| 目标信号带宽 | 3 Hz（提按动作） |
| 滤波器延迟份额 | ≲ 5–10 ms（总回路预算 ≲ 30 ms） |
| 相位预算 | 滤波器 + 积分器 + 系统延迟总相位滞后 ≤ 135°（留 45° 裕度），滤波器在 3 Hz 处贡献须量化 |
| 运行时依赖 | 零新增（scipy 未安装且不加入运行时依赖） |

<a id="source-1-3-滤波器实现srcbrushbotfilterpy新建"></a>
### 3. 滤波器实现（`src/brushbot/filter.py`，新建）

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

<a id="source-1-4-对比脚本scriptscomparefilterspy新建"></a>
### 4. 对比脚本（`scripts/compare_filters.py`，新建）

一等交付物。输入任意 ΔB CSV（列格式 `t_us,t_s,dBx_uT,dBy_uT,dBz_uT`），输出对比矩阵、图表、markdown 报告。

**对比对象**：EMA(α=0.3，正确逐样本用法) / Butterworth(fc 扫 {5, 8, 10, 12} Hz) / One Euro(min_cutoff、beta 扫参，起点 min_cutoff=1 Hz)。

**指标矩阵**：

| 指标 | 数据 | 方法 |
|---|---|---|
| 降噪 σ_x/σ_y/σ_z/\|σ\| | idle | 滤波后求 σ；与 FFT 理想截断对照，差异须 < 10% |
| 3 Hz 相位滞后 (°) | 解析 | 频响公式；One Euro 报告慢/快两种速度状态的等效值 |
| 群延迟 / 阶跃到 ±5% 时间 (ms) | 解析 + 仿真 | 纳入 30 ms 延迟预算核算 |
| 动态跟踪 RMS 误差 (µT) | line/circle | 滤波输出 vs FFT 零相位参考的滞后误差 |

**CLI**：`python scripts/compare_filters.py <csv...> --out docs/01-monitor-filter/filter-comparison.md`
默认跑 `delta_b_v0_20260724/` 全部五条数据。装配态数据到位后同一条命令重跑即完成重新选型。

<a id="source-1-5-报告docs01-monitor-filterfilter-comparisonmd脚本生成"></a>
### 5. 报告（`docs/01-monitor-filter/filter-comparison.md`，脚本生成）

必须回答 handoff §2.5 四个数字问题：

1. 3 Hz 信号相位滞后多少度？（每滤波器/每参数）
2. 噪声从 |σ| = 6.94 µT 降到多少？
3. 滤波后等效 σ_z = σ_filtered / S？（S 待装配态标定，报告以参数占位并给出公式）
4. 滤波器贡献多少 ms 延迟？

并给出：**推荐滤波器 + 参数 + 选型理由 + 装配态重跑指令**。

<a id="source-1-6-测试teststestfilterpy新建"></a>
### 6. 测试（`tests/test_filter.py`，新建）

- 阶跃响应：稳态收敛到终值 ±5% 以内，收敛时间与解析预期一致。
- 批量 (N,3) 与逐样本 (3,)×N 输出逐位一致。
- `reset()` 后重新冷启动，无历史残留。
- NaN 样本：原样透传、状态不污染、后续有效样本正常续接。
- Butterworth 频响 spot-check：系数与若干频点幅值对照硬编码解析参考值。
- One Euro：静止段输出方差 < 快速段（自适应行为可观测）。
- 现有全部测试无回归。

<a id="source-1-7-验收标准"></a>
### 7. 验收标准

```
□ ButterworthFilter / OneEuroFilter 实现，API 与 EMA 一致
□ idle 数据滤波后 σ 与 FFT 理想截断差异 < 10%
□ compare_filters.py 可对任意 ΔB CSV 重跑，生成 docs/01-monitor-filter/filter-comparison.md
□ 报告回答 handoff §2.5 四个数字问题，给出推荐滤波器 + 参数
□ 单测覆盖 §6 全部条目，现有测试无回归
□ 已知边界写入报告：50 Hz 折叠、机械臂低频漂移非滤波器可解
```

<a id="source-2"></a>

## 滤波器手把手教程：从零理解你自己的设计

来源版本：`filter-tutorial.md`。

> 面向本项目（触觉毛笔机器人）的滤波器入门。直觉为主，关键公式逐项解释。
> 每节配一条可直接粘贴的单行命令，用你自己的代码和 V0 数据动手复现。
> 所有命令在 `/home/ethan/FYP` 下执行。

---

<a id="source-2-0-你的问题是什么"></a>
### 0. 你的问题是什么

传感器链路：MLX90393 霍尔传感器以 **100 Hz**（每 10 ms 一次）输出磁场三分量。触角形变改变磁场，所以 ΔB 就是"提按力度"的代理信号。

问题：传感器完全静止时，读数也在抖——这是**噪声**。实测静止 60 秒的标准差 |σ| = 6.94 µT。而你关心的**信号**（毛笔提按动作）本身可能只有几十 µT。噪声若直接进 Z 轴控制环，积分器会把它累积成机械臂的真实抖动。

滤波器的任务：**留下信号，压掉噪声**。这份教程解释它靠什么做到、代价是什么、你的三种滤波器各是什么原理。

---

<a id="source-2-1-频率视角区分信号和噪声的唯一把手"></a>
### 1. 频率视角：区分信号和噪声的唯一把手

时域上信号和噪声混在一起没法拆。关键换个视角：**任何波形都可以看成许多不同快慢的正弦波叠加**（傅里叶的思想）。"快慢"用频率（Hz，每秒摆动次数）衡量。

- **你的信号**：提按动作是手部动作，一秒最多起伏两三次 → 能量集中在 **0–3 Hz**。
- **你的噪声**：随机抖动，能量散布在**所有频率**上。

所以信号和噪声在时域重叠，在**频域大部分是分开的**：3 Hz 以上基本全是噪声。滤波器就是频域里的"门卫"——按频率放行或拦截。

动手——看你自己 idle 数据的频谱（横轴频率，纵轴各频率成分的强度）：

```bash
python -c "import numpy as np, matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt; d=np.genfromtxt('delta_b_v0_20260724/20260724_142504_idle_r01.csv',delimiter=',',names=True); x=d['dBz_uT']; f=np.fft.rfftfreq(len(x),0.01); A=np.abs(np.fft.rfft(x-x.mean()))/len(x); plt.semilogy(f[1:],A[1:]); plt.xlabel('Hz'); plt.ylabel('amplitude (uT)'); plt.title('idle dBz spectrum'); plt.savefig('/tmp/idle_spectrum.png',dpi=110); print('saved /tmp/idle_spectrum.png')" && xdg-open /tmp/idle_spectrum.png
```

你会看到能量从低频到高频缓慢下降、铺满整个 0–50 Hz——这就是纯噪声的样子（低频略强，即"1/f 特征"，§8 会用到这个观察）。

**两个由 100 Hz 采样率决定的硬边界**：

1. **Nyquist 频率 = 采样率/2 = 50 Hz**。每秒 100 个点，最快只能"看清"每秒 50 次的摆动。比 50 Hz 更快的成分不会消失，而是**伪装成低频混进来**（混叠 aliasing）。
2. 市电工频恰好 50 Hz，正好落在 Nyquist 边界上，混叠后**折回直流附近**——任何数字滤波器都无法把它和真实信号分开。这是你文档里写"50 Hz 工频交给固件/硬件层解决"的原因：这不是偷懒，是数学上无解。

---

<a id="source-2-2-滤波器是什么一个频率选择器"></a>
### 2. 滤波器是什么：一个"频率选择器"

**低通滤波器（low-pass）**：放行低频（慢的，信号），衰减高频（快的，噪声）。你的三种滤波器都是低通。

核心参数是**截止频率 fc（-3dB 点）**：信号幅值被衰减到约 70.7%（即功率减半，-3 dB）的那个频率。fc 以下基本原样通过，fc 以上逐渐压低。"逐渐"的坡度叫**滚降**（roll-off），单位 dB/octave（每翻一倍频率多衰减多少分贝）。

**为什么不能要一个"理想滤波器"**（fc 以下完全通过、以上完全砍掉）？因为完美的频率切割需要**看到未来的样本**。你的控制环每 10 ms 就要出一个 z 指令，只能用"现在和过去"的数据——这叫**因果滤波器**。这就是当初 handoff 排除两种做法的原因：

- `scipy.signal.filtfilt`（双向零相位）：先正着滤再倒着滤，需要整段数据 → 只能离线用；
- FFT 截断（`analyze_deltab.py` 的做法）：整段变换到频域再切 → 同样离线。

它们在项目里的正确角色是**离线理想参考**——`compare_filters.py` 用 FFT 零相位截断当"上帝视角答案"来给实时滤波器打分，但绝不能上控制环。

---

<a id="source-2-3-最简单的滤波器ema你已有的那个"></a>
### 3. 最简单的滤波器：EMA（你已有的那个）

`src/brushbot/monitor/core.py` 的 `EMA` 类，一行核心：

```
y_t = α · x_t + (1−α) · y_{t−1}
```

逐项读：**新输出 = α 份的新读数 + (1−α) 份的旧输出**。

- `x_t`：本拍传感器读数（含噪声）
- `y_{t−1}`：上一拍的滤波输出（历史的浓缩）
- `α ∈ (0,1]`：**信任新数据的程度**

直觉：**惯性**。α 小 = 惯性大 = 新读数只能微微推动输出 → 噪声的随机推挤互相抵消（强降噪），但真实动作也推不动它（跟不上）。α = 1 就是不滤波。

这个一行公式其实就是**一阶低通滤波器**：它有明确的 -3dB 截止频率，α 越小截止越低。动手看 α 和降噪、截止频率的关系（用你的 idle 数据）：

```bash
python -c "import sys; sys.path[:0]=['src','scripts']; from compare_filters import load_csv, sigmas, f3db, ema_freq_response; from brushbot.monitor.core import EMA; d=load_csv('delta_b_v0_20260724/20260724_142504_idle_r01.csv'); [print('a=%.2f  |sigma|=%.2f uT  f3db=%.1f Hz'%(a, sigmas(EMA(a).update(d['dB']))[3], f3db(lambda f,a=a: ema_freq_response(a,f)))) for a in (0.05,0.1,0.2,0.3,0.5)]"
```

输出（α 越小 → 截止越低 → 噪声 σ 越小）：

```
a=0.05  |sigma|=2.03 uT  f3db=0.8 Hz
a=0.30  |sigma|=3.31 uT  f3db=5.7 Hz   ← 监控窗口默认档
a=0.50  |sigma|=4.25 uT  f3db=11.5 Hz
```

EMA 的滚降是 **-6 dB/oct**（频率每翻倍多衰减一半）——比较平缓，高频噪声压得不够狠。这引出下一个。

---

<a id="source-2-4-butterworth两级惯性串联srcbrushbotfilterpy"></a>
### 4. Butterworth：两级惯性串联（`src/brushbot/filter.py`）

**二阶** Butterworth 直觉上 = 两级"惯性"串联，所以滚降翻倍：**-12 dB/oct**，高频噪声压得比 EMA 狠一倍（分贝意义上）。"Butterworth" 这个设计的特点是**通带最平坦**：fc 以内的信号几乎不失真地通过（3 Hz 处幅值衰减 <1%，你可以在下一条命令里看到 |H|=0.991）。

代码里的核心是 5 个系数的**差分方程**（biquad，双二阶节）：

```
y_t = b0·x_t + b1·x_{t−1} + b2·x_{t−2} − a1·y_{t−1} − a2·y_{t−2}
```

逐项读：新输出 = 最近**三拍输入**的加权和，再叠加最近**两拍输出**的反馈。前半（b 系数）像一个三点小平均，后半（a 系数）就是"惯性"——输出记得自己的历史。EMA 是它的退化版（只有 b0 和 a1）。

系数 `b0..a2` 从哪来？`__init__` 里那几行 `k = tan(π·fc/fs)` 是**双线性变换**：把教科书里的模拟（连续时间）Butterworth 原型"折算"到 10 ms 一拍的数字世界的标准配方。`tan` 那步叫预畸变，作用只有一个：**保证 -3dB 点精确落在你要的 fc 上**（测试 `test_minus3db_at_fc` 验证的就是这件事）。答辩讲到这层即可，推导不必背。

---

<a id="source-2-5-天下没有免费的降噪相位滞后"></a>
### 5. 天下没有免费的降噪：相位滞后

这是整个滤波器设计的**核心矛盾**，务必吃透。

滤波器本质是"往回看的加权平均"——输出必然**迟到**。频域语言叫**相位滞后**（单位：度）：一个 3 Hz 的正弦经过滤波后，波形整体向后错开一个角度。换算成时间：

```
延迟(ms) = 相位滞后° / (360 × 频率Hz) × 1000
```

动手——问你自己的 Butterworth：3 Hz 信号过一次 8 Hz 滤波，迟到多少？

```bash
python -c "import sys; sys.path.insert(0,'src'); import numpy as np; from brushbot.filter import ButterworthFilter; h=ButterworthFilter(8.0).freq_response(3.0); print('|H|=%.3f  phase=%.1f deg  delay=%.1f ms'%(abs(h), -np.degrees(np.angle(h)), -np.degrees(np.angle(h))/(360*3)*1000))"
```

输出：`|H|=0.991 phase=31.1deg delay=28.8ms` —— 幅值几乎不损（0.991），但 3 Hz 成分迟到约 29 ms。

细心的话你会发现 29 ms 已经超出下面说的 5–10 ms 份额——没错，**任何降噪够用的滤波器在裸态数据下都超预算**，这是选型报告记录在案的已知张力（预算和降噪目标互斥），装配态复测后需要重新划预算，而不是说这个滤波器不能用。

> **历史更新**：当时曾用仿真闭环重新评估滤波延迟。该扫描报告现已移除；这里的 5–10 ms 预算不应当作当前真机定值，需结合实测执行延迟和闭环稳定性重新确定。

**为什么控制环在意这个**：你的 Z 控制是闭环——测量 → 算误差 → 出指令 → 影响下一次测量。环路里每一处延迟都在消耗**相位裕度**（可以粗糙理解为"闭环距离自激振荡还剩多少安全余量"，工程上要留 ≥45°）。积分器天生吃掉最多 90°，系统传输/执行再吃一截，所以留给滤波器的份额只有 **≲5–10 ms**。这就是"截止频率越低降噪越好，但滞后越大环越不稳"这个跷跷板的由来：

```
fc ↓  →  噪声 σ ↓（好）  但  相位滞后 ↑（坏）
fc ↑  →  相位滞后 ↓（好）  但  噪声 σ ↑（坏）
```

**选滤波器 = 在这个跷跷板上选一个坐标点**。这正是 Pareto 散点图（§8）画的东西。

---

<a id="source-2-6-one-euro会自己变-α-的-ema"></a>
### 6. One Euro：会自己变 α 的 EMA

固定截止的滤波器被迫在"静止时够稳"和"动作时跟手"之间二选一。One Euro（Casiez 2012，最初为鼠标/手势指针设计）的思路：**别固定，看情况**。

```
截止频率 fc = min_cutoff + β · |信号速度|
```

- 静止时速度 ≈ 0 → fc ≈ `min_cutoff`（很低，如 0.5 Hz）→ 强降噪；
- 快速动作时速度大 → fc 被 β 抬高 → 低滞后跟手。

三个参数各管什么：`min_cutoff` 管静止时多稳；`beta` 管动作时多跟手；`d_cutoff` 是内部对"速度估计"本身做的平滑（速度是差分算的，本身噪声大，不平滑会误触发）。

动手——感受自适应：喂一个 100 µT/s 的斜坡（模拟持续下压），比较 β=0 和 β=0.05 的稳态滞后：

```bash
python -c "import sys; sys.path.insert(0,'src'); import numpy as np; from brushbot.filter import OneEuroFilter; ramp=100*np.arange(300)/100; x=np.repeat(ramp[:,None],3,axis=1); print('beta=0    lag=%.1f uT'%(ramp[-1]-OneEuroFilter(1.0,0.0).update(x)[-1,0])); print('beta=0.05 lag=%.1f uT'%(ramp[-1]-OneEuroFilter(1.0,0.05).update(x)[-1,0]))"
```

输出：β=0 滞后 15.9 µT，β=0.05 滞后 1.3 µT——**动作中滞后缩小一个数量级**，而静止降噪能力不变。这正是提按信号"静止要稳、动作要快"的理想形状。

代价是**非线性**：它的行为随信号幅值变化，没有单一的"相位滞后"数字可讲。所以对比报告里它的相位标注"慢态等效"、散点图用空心标记，评价它要看动态 RMS 指标；也因此小信号阶跃测出的 settle 数字（1 µT → 380 ms）是最坏情形，真实提按幅值（几十 µT）下会缩到 ~50 ms——报告注释专门写了这条，防止误杀。

在监控窗口里最直观：滤波下拉切到 OneEuro，静止段比 EMA 稳，动手晃触角时又跟得上。

---

<a id="source-2-7-你的系统设计决策一览每条一句为什么"></a>
### 7. 你的系统设计决策一览（每条一句为什么）

| 决策 | 为什么 |
|---|---|
| 滤波器放控制器**外部**（`dB_f = filt.update(dB); zc.step(dB_f, ...)`） | 滤波后信号还要喂显示/日志；滤波器在控制器 freeze 期间要继续跟踪；生命周期各自独立 |
| **先滤三分量向量，再取 norm** | norm 是非线性操作，先 norm 会把噪声整流出正偏置；先滤能同时降方差和偏置 |
| NaN **透传且不更新状态** | 下游 ZController 靠看到 NaN 触发 freeze 保护，滤波器不能吞；IIR 内部状态沾 NaN 会永久报废，必须隔离 |
| 监控窗口**每帧批量重滤**而非流式 | 显示效果与流式一致（实测差 <1e-5 µT），但天然兼容基线重取，代码简单 |
| **录制的永远是原始 ΔB** | 滤波是下游的事；raw 数据录下来可以事后对任何滤波器做公平对比（本教程所有命令都受益于此） |
| 50 Hz 工频不在滤波器职责内 | 混叠折回 DC，数学上无解（§1），交固件 ODR/硬件层 |
| 机械臂运动的低频磁干扰不在滤波器职责内 | 与提按信号**频谱重叠**（都在 0–3 Hz），频率门卫分不开同频段的东西，需要差分测量（硬件方案） |

---

<a id="source-2-8-怎么量化效果--读-pareto-图"></a>
### 8. 怎么量化效果 + 读 Pareto 图

一条命令跑全套（18 个配置 × 4 指标 + 两张图 + 报告）：

```bash
python scripts/compare_filters.py && xdg-open docs/assets/filter-pareto.png
```

四个指标分别回答什么：

1. **idle σ**（收益）——噪声压到多少 µT；将来除以灵敏度 S 就是机械臂 Z 抖动多少 mm。
2. **3 Hz 相位滞后 / 群延迟**（代价）——吃掉多少相位裕度预算。
3. **阶跃 settle**（代价，时域）——突然下压后多久跟上（注意 OneEuro 的小信号最坏情形口径）。
4. **动态 RMS**（综合）——真实运动数据上和"离线上帝视角答案"（FFT 零相位截断）差多远。

**Pareto 散点图读法**：x=滞后代价，y=残余噪声，**左下角最优**。每族滤波器的参数扫描连成一条权衡曲线；若 A 曲线整条压在 B 下面，叫 A "Pareto 支配" B——同等代价收益更高，B 全线出局。

当前图上的发现：**裸态数据上 EMA 支配 Butterworth**。原因回到 §1 频谱观察：这份噪声能量集中在低频（1/f），Butterworth 引以为傲的高频陡滚降没东西可压，却要付双倍相位代价。**这个结论依赖噪声谱形状**：装配到 Elfin 后若电机 EMI 引入高频噪声，Butterworth 就会翻盘——所以装配态 E0 复测后必须重跑（同一命令，换 CSV 路径）。

---

<a id="source-2-9-答辩速查可能被问的问题"></a>
### 9. 答辩速查：可能被问的问题

- **为什么不用 Kalman 滤波？** Kalman 需要信号的运动模型（状态方程），目前提按动作无可靠模型；EMA/Butterworth/OneEuro 是无模型方案，先解决有无。有了标定和轨迹模型后 Kalman 是升级项。
- **为什么不用 FIR（有限冲激响应）滤波器？** 达到同等降噪需要几十阶，群延迟 = 阶数一半 × 10 ms，远超预算。IIR（你的三种都是）用反馈以极少计算达到同等选择性。
- **为什么采样 100 Hz？** 信号带宽 3 Hz，理论 6 Hz 就够采（Nyquist），100 Hz 留了 16 倍余量——余量都被用来"在数字域降噪"（采得密，噪声才有高频成分可滤）。
- **滤波器会不会滤掉提按信号本身？** fc 选在 5–12 Hz，是信号带宽 3 Hz 的 2–4 倍，3 Hz 处幅值损失 <1%（§5 实测 |H|=0.991）。损失的只有相位（迟到），不是幅值。
- **为什么最后选了 EMA α=0.3 而不是更高级的？** 见 §8：这份数据的噪声谱让一阶结构性价比最高，且它就是监控窗口的默认档。这是**过渡结论**，装配态复测和 settle 口径修正后预期翻转为 OneEuro——选型脚本可一键重跑正是为此。

**历史说明（2026-07-31）**：settle 口径修正后，孤立滤波指标曾推荐 OneEuro；当时的仿真闭环比较选用 EMA α=0.3。旧扫描结果现已移除，这两种口径都不构成当前装配态或真机控制的最终滤波选型。现行实验以实际前馈表与设置中记录的滤波定义为准。

<a id="source-2-10-术语速查"></a>
### 10. 术语速查

| 术语 | 一句话 |
|---|---|
| 低通 / 截止频率 fc | 放行慢成分拦截快成分 / 衰减到 70.7%（-3dB）的分界频率 |
| 滚降 dB/oct | 截止后每翻倍频率多压多少；一阶 -6，二阶 -12 |
| Nyquist / 混叠 | 采样率一半，能看清的最快频率 / 超出的伪装成低频混入 |
| 相位滞后 / 群延迟 | 输出波形迟到的角度 / 换算成毫秒的迟到时间 |
| 因果滤波器 | 只用现在和过去样本（实时可用）；filtfilt/FFT 截断非因果（仅离线） |
| IIR / FIR | 有反馈（省算力，你的三种）/ 无反馈纯加权平均（延迟大） |
| biquad | 二阶差分方程的标准实现形式（5 个系数） |
| σ（sigma） | 标准差，噪声大小的度量 |
| Pareto 支配 | 同等代价下收益全面更优，对手全线出局 |

<a id="source-3"></a>

## Handoff: Z 控制即時濾波器設計

来源版本：`handoff-filter.md`。

> ⚠️ **本文档已完成历史使命（2026-07-31 归档）**：滤波器库已交付（src/brushbot/filter.py）。历史孤立指标口径见 docs/01-monitor-filter/filter-comparison.md；旧仿真在环扫描结果已移除。以下内容仅作立项背景历史参考。

> 給下一個 session 的交接文件。
> 狀態：監控窗口已有 EMA 平滑顯示（視覺用途）；**Z 控制迴路的即時濾波器尚未設計與實現**。
> 分支：`feat/deltab-monitor`
> 關聯：`docs/01-monitor-filter/sensor-v0-results.md`（噪聲-帶寬權衡）、`docs/04-robot-control/archive/z-control-design.md`（前饋表＋PI 控制思路）。舊 E0 門禁文檔已移除。

---

<a id="source-3-0-為什麼濾波器需要獨立的交接文件"></a>
### 0. 為什麼濾波器需要獨立的交接文件

Z 控制迴路的信號鏈是：

```
MLX90393 (100 Hz, µT) → 濾波器 → ZController → z_cmd → 機械臂
                            ↑
                    這一段目前是空的
```

Phase 0 的 `ZController` 直接吃原始 ΔB，沒有做任何濾波。這是故意的——Phase 0 先驗證控制結構。但從 V0 分析已知，**100 Hz 全帶寬噪聲 σ_x = 3.21 µT、σ_z = 5.30 µT**，直接進控制迴路會：
- 噪聲被積分器累積（積分項對高頻噪聲沒有自然衰減）
- 方向分量在低 |ΔB| 時由噪聲主導（方向門控只過濾了 φ/θ 顯示，沒過濾控制輸入）

**濾波器是控制迴路的必要組成，不是可選項。**

---

<a id="source-3-1-現有濾波器盤點什麼已經有了什麼不能直接用"></a>
### 1. 現有濾波器盤點（什麼已經有了，什麼不能直接用）

<a id="source-3-11-ema-濾波器corepyema"></a>
#### 1.1 EMA 濾波器（`core.py:EMA`）

```
y_t = α·x_t + (1-α)·y_{t-1}
參數：α = 0.3（監控窗口默認值）
```

**現有用途**：僅用於 GUI 即時曲線平滑顯示（`window.py:362-364`）。每次重繪前 reset EMA 再 batch 跑整個緩衝區——不是逐幀即時濾波。

**不直接用於控制的理由**：

| 問題 | 影響 |
|---|---|
| 無預定義的頻率響應 | α=0.3 對應的 -3dB 截止頻率 ∼ f_s·α/(2π) ≈ 4.8 Hz @ 100Hz，但只是近似，未經設計 |
| batch reset 用法 | 監控窗口每幀 reset+batch 跑——控制迴路需要逐樣本的持續濾波 |
| 無相位特性分析 | EMA 的群延遲是頻率相關的，但未量化，無法納入延遲預算 |

<a id="source-3-12-fft-域低通analyzedeltabpybandnoise"></a>
#### 1.2 FFT 域低通（`analyze_deltab.py:band_noise`）

```
FFT → 截斷 f > fc → IFFT → 求 σ
```

**現有用途**：離線分析工具，用於 V0 分析報告生成噪聲-帶寬權衡曲線。**不是即時濾波器**，僅用來回答「截止到 X Hz 時噪聲是多少」。

**已產出的關鍵數字**（V0 idle，10 s @ 100 Hz）：

| fc (Hz) | 1 | 2 | 3 | 5 | 10 | 20 | 50 |
|---|---|---|---|---|---|---|---|
| σ_x | 0.53 | 0.66 | 0.80 | 1.01 | 1.40 | 2.01 | 3.21 |
| σ_y | 0.46 | 0.65 | 0.79 | 0.96 | 1.37 | 1.93 | 3.12 |
| σ_z | 1.63 | 1.86 | 2.08 | 2.33 | 2.88 | 3.64 | 5.30 |

---

<a id="source-3-2-你需要設計什麼"></a>
### 2. 你需要設計什麼

<a id="source-3-21-核心約束"></a>
#### 2.1 核心約束

| 約束 | 值 | 來源 |
|---|---|---|
| 採樣率 | 100 Hz（Δt = 10 ms） | MLX90393 固件配置 |
| 目標信號帶寬 | 3 Hz（提按動作） | `gate-experiments.md` E1 判據 |
| 總迴路延遲預算 | ≲ 30 ms | `deltaB-control.md` §6.4 延遲預算 |
| 濾波器可用的延遲 | ≲ 5–10 ms（總預算中感測器+傳輸+運算份額） | 工程判斷 |
| 噪聲目標 | σ_z = σ_ΔB/S ≤ 1/5 × 提按分辨率 | `gate-experiments.md` E0 判據 |

<a id="source-3-22-核心矛盾"></a>
#### 2.2 核心矛盾

**噪聲抑制 vs 相位滯後是同一枚硬幣的兩面。**

```
截止頻率越低 → 噪聲抑制越好 → σ_z 越小
截止頻率越低 → 相位滯後越大 → 迴路穩定性越差
```

```
例子（2 階 Butterworth @ 100 Hz 採樣）：
  fc = 5 Hz  → 3 Hz 處相位滯後約 40°
  fc = 10 Hz → 3 Hz 處相位滯後約 15°
  fc = 3 Hz  → 3 Hz 處相位滯後約 90° ← 已逼近積分器的相位貢獻
```

**總相位滯後 = 濾波器 + 積分器（≤90°）+ 系統延遲（360°×f×T_delay）+ 觸角動態（≤90°）**

要留 ≥45° 相位裕度，需要把所有 LP 濾波器相位 + 積分 + 延遲的總和控制在 ≤135°。其中濾波器在 3 Hz 處的貢獻不能太大。

<a id="source-3-23-推薦的濾波器設計方向"></a>
#### 2.3 推薦的濾波器設計方向

**首選：2 階 Butterworth IIR 低通**，fc ≈ 8–12 Hz（3 Hz 處衰減 < 0.2 dB，噪聲衰減約 √(10/fc) ≈ 2–3×）。

理由：
- 2 階在 3 Hz 處的相位滯後可控（~10–20° @ 3 Hz，視 fc 而定）
- 截止後衰減 -12 dB/oct，足夠壓制 50 Hz 工頻（若存在）
- 代碼量極小——三行程式（biquad），無外部依賴
- 零延遲（因果濾波器，不需要未來樣本）

**備選：1 階 IIR（即 EMA 的正確用法）**，fc ≈ 3–5 Hz。在 3 Hz 處相位滯後約 45°（略大），但實現最簡單。如果濾波後 3 Hz 處的相位裕度仍大於 45°，可直接用。

**不要用**：
- ❌ `scipy.signal.filtfilt`（雙向零相位）——需要未來樣本，不是即時濾波
- ❌ FFT 域濾波（`analyze_deltab.py:band_noise` 的做法）——批次處理，不是即時
- ❌ 高階 FIR（>10 階）——群延遲過大

<a id="source-3-24-濾波器介面設計"></a>
#### 2.4 濾波器介面設計

為了和現有 EMA 保持一致、方便替換測試，建議遵循相同 API：

```python
class IIRFilter:
    """2 階 Butterworth IIR 低通，逐樣本即時濾波。"""

    def __init__(self, fc: float, fs: float = 100.0):
        """fc: -3dB 截止頻率 (Hz)；fs: 採樣率 (Hz)。"""

    def update(self, x: np.ndarray) -> np.ndarray:
        """輸入 (3,) 或 (N,3)，返回同形狀濾波值。
           支援單樣本（控制迴路即時用）和批量（離線分析用）。"""

    def reset(self) -> None:
        """清零狀態。"""
```

<a id="source-3-25-驗證要求"></a>
#### 2.5 驗證要求

濾波器設計完成後，必須回答以下數字（不是跑一次看曲線，是**算出具體數值**）：

| 問題 | 如何回答 |
|---|---|
| 「3 Hz 信號的相位滯後多少度？」 | 算 group delay @ 3 Hz（或量脈衝響應） |
| 「噪聲從 σ=6.94 µT 降到多少？」 | 用 V0 idle 數據跑濾波後求 σ |
| 「濾波後等效 Z 噪聲 σ_z 是多少？」 | σ_z = σ_filtered / S（S 取 E2 實測最小值） |
| 「濾波器貢獻了多少延遲？」 | group delay ≤ X ms → 納入延遲預算 |

---

<a id="source-3-3-噪聲-帶寬權衡的延遲視角新分析"></a>
### 3. 噪聲-帶寬權衡的延遲視角（新分析）

V0 分析 §2 給了 σ vs fc 的靜態視角。控制設計需要的是**動態視角**——濾波後的噪聲和相位滯後一起看。

<a id="source-3-31-靜態噪聲已量化"></a>
#### 3.1 靜態噪聲已量化（✅）

| fc (Hz) | σ_x | σ_y | σ_z | \|σ\| |
|---|---|---|---|---|---|
| 全帶寬 (50) | 3.21 | 3.12 | 5.30 | 6.94 |
| 10 | 1.40 | 1.37 | 2.88 | 3.48 |
| 5 | 1.01 | 0.96 | 2.33 | 2.71 |
| 3 | 0.80 | 0.79 | 2.08 | 2.36 |

<a id="source-3-32-動態相位需重新計算-待做"></a>
#### 3.2 動態相位需重新計算（❌ 待做）

上面的噪聲數字用的是 FFT 域理想截斷（零相位），但即時濾波器有相位滯後。**真實即時濾波器的輸出噪聲 σ 會比 FFT 截斷略大**（因為相位失真導致波形變形），差異通常 < 10%，但需要實測。

---

<a id="source-3-4-已知的裝配態額外噪聲源"></a>
### 4. 已知的裝配態額外噪聲源

裸觸角的 σ = 6.94 µT 是**樂觀下界**。裝配到 Elfin 上後，以下額外噪聲會疊加上來：

| 噪聲源 | 機制 | 預計幅度 | 頻譜特徵 |
|---|---|---|---|
| **電機 EMI** | PWM 驅動器 → 磁場波動 | 未知，可能很大 | 集中在 PWM 頻率（~20 kHz）及其諧波 → 對 DC–3Hz 影響可能較小 |
| **法蘭剩磁** | Elfin 鋼法蘭被磁化 | 直流偏置，不是噪聲 | B0 會偏，不影響 σ |
| **電源線 50 Hz** | 工頻耦合 | 若存在，幅度未知 | 50 Hz 窄帶 —— **剛好在 Nyquist 頻率處，會折疊回 DC** ⚠️ |
| **機械臂運動** | 電機電流隨位姿變化 | 10–100 µT 量級（未測） | 低頻（<5 Hz），與提按信號頻譜重疊——**無法用濾波分離** ⚠️ |
| **振動** | 機械臂動態振動 → 傳感器微動 → 磁場變化 | 取決於臂的剛度 | 通常 >10 Hz |

**最重要的待辦**：裝配態 E0 復測。裸態數字之後的所有推導都必須用裝配態數字重算。

**最棘手的噪聲源**：機械臂運動引入的低頻磁場變化與提按信號**頻譜重疊**，不是濾波器能處理的——需要**差分測量**（`deltaB-control.md` §8.1 方案 E 建議的參考磁力計）。這是硬件層面的問題，濾波器無能為力。

---

<a id="source-3-5-代碼路徑"></a>
### 5. 代碼路徑

```
src/brushbot/
├── monitor/core.py              # EMA 類（現有，視覺用途）：line 64-101
├── z_control.py                 # ZController（現有，未使用濾波）
└── filter.py                    # ← 新建：IIRFilter / 其他即時濾波實現

scripts/
└── analyze_deltab.py            # FFT 域 band_noise()（現有，離線用途）：line 46-53

tests/
├── test_monitor_core.py         # EMA 單測（現有）
└── test_filter.py               # ← 新建：濾波器單測
```

---

<a id="source-3-6-建議的第一次動作"></a>
### 6. 建議的第一次動作

1. **先測裝配態 E0**（最高優先級）：裸態數字之後的一切推導都依賴這一步。沒有裝配態 σ_ΔB，濾波器設計只是紙上作業。
2. **在 `src/brushbot/` 下新建 `filter.py`**，實現 2 階 Butterworth biquad。用 `np.array` 存狀態，零外部依賴。
3. **用 V0 idle 數據跑量化對比**：EMA (α=0.3) vs IIR (fc=8 Hz) 的噪聲衰減和相位滯後。
4. **寫 `tests/test_filter.py`**：覆蓋單樣本/批量/步階響應/reset。
5. **掛入 ZController**：在 `step()` 中加一個可選的 filter 參數，默認 `None`（不啟用）。Phase 1 再默認啟用。

---

<a id="source-3-7-驗收標準"></a>
### 7. 驗收標準

```
□ IIRFilter 類已實現，API 與 EMA 一致
□ 能對 V0 idle 數據輸出濾波後的 σ_ΔB（與 FFT 理想截斷對照，差異 < 10%）
□ ZController 支援可選的 filter 參數
□ 單測覆蓋：階躍響應衰減到 ±5%、reset 歸零、批量/單樣本一致性
□ 所有現有測試無 regression
□ 文檔記錄：濾波器的 -3dB 截止、3 Hz 處相位滯後、貢獻延遲 ms
```

<a id="source-4"></a>

## 滤波器成果检验命令

来源版本：`filter-quickcheck.md`。

> 历史验收记录：以下命令记录当时的滤波器测试流程，不能代替现行实验、真机安全检查或当前滤波口径选择。

> 原记录采用单行命令；执行前须核对当前文件与环境。

> **口径说明**：本文档验收的是**孤立滤波指标**管线（`scripts/compare_filters.py` 的 σ/相位/群延迟/settle 排行），不直接决定真机控制环的滤波配置。

<a id="source-4-1-跑测试20-个新增测试--全量回归"></a>
### 1. 跑测试（20 个新增测试 + 全量回归）

```bash
cd /home/ethan/FYP && python -m pytest tests/test_filter.py tests/test_compare_filters.py -v
```

预期：`31 passed`（ButterworthFilter 11 + OneEuroFilter 9 + 指标函数 11），全绿。

```bash
cd /home/ethan/FYP && python -m pytest
```

预期：`130 passed`。

<a id="source-4-2-重新生成对比报告核心成果"></a>
### 2. 重新生成对比报告（核心成果）

```bash
cd /home/ethan/FYP && python scripts/compare_filters.py
```

预期：终端打印 14 行配置指标（EMA / 4 个 Butterworth / 9 个 OneEuro 的 |σ|、fftΔ%、3Hz 相位、群延迟、settle、动态 RMS）+ 最后一行 `推荐: OneEuro mc=0.5 b=0.03`（孤立指标口径，非控制环最终选型——见文档开头口径说明）；同时重写 `docs/01-monitor-filter/filter-comparison.md` 和 `docs/assets/filter-comparison.png`。

<a id="source-4-3-看报告和图"></a>
### 3. 看报告和图

```bash
cat /home/ethan/FYP/docs/01-monitor-filter/filter-comparison.md
```

```bash
xdg-open /home/ethan/FYP/docs/assets/filter-comparison.png
```

图有两个子图：左 = idle 数据 z 通道原始 vs 滤波（降噪效果），右 = 阶跃响应对比（滞后代价）。已知小毛病：子图标题中文显示为方框（matplotlib 默认字体无 CJK，deferred 修复项），曲线和数据不受影响。

<a id="source-4-4-一分钟数字-sanity-check降噪立竿见影"></a>
### 4. 一分钟数字 sanity check（降噪立竿见影）

```bash
cd /home/ethan/FYP && python -c "import sys; sys.path[:0]=['src','scripts']; from compare_filters import load_csv, sigmas; from brushbot.filter import ButterworthFilter, OneEuroFilter; d=load_csv('delta_b_v0_20260724/20260724_142504_idle_r01.csv'); print('raw      |sigma| = %.2f uT' % sigmas(d['dB'])[3]); print('Butter8  |sigma| = %.2f uT' % sigmas(ButterworthFilter(8.0).update(d['dB']))[3]); print('OneEuro  |sigma| = %.2f uT' % sigmas(OneEuroFilter(0.5, 0.03).update(d['dB']))[3])"
```

预期：raw ≈ 6.9，Butter8 ≈ 3.4，OneEuro ≈ 2.7（µT）。

<a id="source-4-5-验证回退警告本次评审加的防呆"></a>
### 5. 验证回退警告（本次评审加的防呆）

```bash
cd /home/ethan/FYP && python scripts/compare_filters.py delta_b_v0_20260724/20260724_142504_idle_r01.csv --out /tmp/filter-idleonly.md
```

预期：终端出现 `警告: ...` （只有 idle、没有动态数据时，明确告知推荐仅按 σ 排序、选型门槛未生效），报告推荐段同样标注。

<a id="source-4-6-装配态数据到位后未来重跑"></a>
### 6. 装配态数据到位后（未来重跑）

```bash
cd /home/ethan/FYP && python scripts/compare_filters.py <装配态csv路径...> --out docs/01-monitor-filter/filter-comparison.md
```

同一条命令、新数据，即完成重新选型。注意：`step_settle_ms` 已改用 10 µT 代表性阶跃幅值（原 deferred 项已完成），推荐已翻转为 OneEuro——此说明仅提醒装配态数据仍需重跑同一命令验证。
