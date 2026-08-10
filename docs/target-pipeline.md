# 离线目标曲线管线

> 把一次书写示范变成机器人可执行的目标：示范录音 → 零相位滤波 → 切笔画 → 标定反查 → StrokePlan。代码：`src/brushbot/demo_pipeline.py`（纯函数流水线）、`src/brushbot/strokeplan.py`（数据契约）、`scripts/synth_demo.py`（合成示范生成器）、`scripts/demo_target_pipeline.py`（端到端验收）。完整设计过程见 `docs/superpowers/specs/2026-07-31-offline-target-pipeline-design.md`。

## 做了什么

输入一份"磁力计 ΔB + 笔尖 XY 同步录音"的示范 CSV（100 Hz），管线离线产出 StrokePlan：

```
示范 CSV → fft_lowpass 零相位滤波(整段向量, fc=3) → |ΔB| → 阈值切分笔画 → 边界内缩
        → 逐笔弧长重参数化 g_press(s) → 标定表反查 z_ff(s) → StrokePlan(.npz)
```

一石二鸟：`to_waypoints()` 直接是 CalliRewrite 式开环 baseline 轨迹；`to_gd_series()` 是闭环臂目标。两臂共享同一份前馈，论文口径"差异 = 触觉反馈"由数据结构保证。

关键纪律：

- **单位**：计算核心一律 SI（米）；带后缀字段（`calib_z_mm`、`dBx_uT`）在边界一次性换算。
- **NaN 与实时链路相反**：离线数据必须干净——坏数据当场报错并指出行号，不透传。
- **滤波顺序**：先滤 (N,3) 向量再取 norm；整段滤波后再切分（避免短笔段 FFT 边缘伪影）。
- **反查唯一实现**：`z_control.calib_lookup_z` 为模块级公开函数，ZController 与管线共用；反查饱和样本占比进 meta，>5% 打 warning。

## StrokePlan 契约

`src/brushbot/strokeplan.py`，轻量 dataclass：

```python
Stroke:      s (M,) 归一化弧长 [0,1] | xy (M,2) 米 | g_press (M,) µT | z_ff (M,) 米(不含 z_surface)
StrokePlan:  strokes: list[Stroke] + meta: dict (fc/M/sigma/edge_trim_s/丢弃计数/sat_frac/标定指纹/source)
```

- `to_waypoints(z_surface=0.20, lift=0.015)` —— **开环出口**。每笔：起点上方悬空进入 → M 个 `(x, y, z_surface + z_ff)` → 终点上方抬笔。裸 (x,y,z) 列表，`OpenLoopController` 零改动消费。
- `to_gd_series(stroke_duration_s, fs=100.0, gap_s=0.5)` —— **闭环出口**。每笔匀速播放 g_press(s) 回时域，笔间接 `gap_s` 的 g_d=0 悬空段（含末笔，触发 freeze）；悬空段 xy 线性过渡到下笔起点。返回 `(g_d, xy)`，可直接喂 `run_loop`。
- `save(path)` / `load(path)` —— npz 往返无损（meta 以 JSON 字符串存入）。

**输入 CSV 格式**（监控格式超集，7 列，100 Hz）：`t_us,t_s,dBx_uT,dBy_uT,dBz_uT,x_m,y_m`。缺列、非有限值、采样率偏离 100 Hz 均当场报错。

## 怎么跑

生成合成示范（带真值 npz；±50% 变速为默认，`--uniform-speed` 产匀速版）：

```
python scripts/synth_demo.py --out /tmp/demo.csv --truth /tmp/truth.npz
python scripts/synth_demo.py --uniform-speed --seed 7 --out /tmp/demo_uni.csv --truth /tmp/truth_uni.npz
```

端到端验收（合成示范 → 管线 → 两臂 sim_loop 彩排，打印四问数字 + 出图到 `docs/assets/target-pipeline-demo.png`）：

```
python scripts/demo_target_pipeline.py
```

代码内调用：

```python
from brushbot.demo_pipeline import load_demo, build_plan
plan = build_plan(load_demo("demo.csv"), calib_z_mm, calib_abs_dB, fc=3.0, M=200)
plan.save("plan.npz")
```

## 验收结论（四问）

| # | 问题 | 判据 | 实测 |
|---|---|---|---|
| Q1 | 带噪变速录音里恢复的 g_press(s) 离真值多远？ | 逐笔 RMS ≤ 3 µT | 2.70 / 2.06 / 2.41 µT ✓ |
| Q2 | 匀速 vs 变速示范的恢复结果差多少？ | 单测（fc=10 隔离耦合）≤ 1 µT；全管线 fc=3 如实报告（sanity ≤ 3.5） | 单测 0.37 / 0.40 µT ✓；E2E 2.57 / 1.68 / 2.26 µT（落在预测 ~2–3 µT 耦合带）✓ |
| Q3 | 目标喂两臂，calib×0.8 扰动下各偏多少？ | 闭环 RMS < 开环 RMS，方向与层 2 结论一致 | 开环 17.57% vs 闭环 10.60% ✓ |
| Q4 | to_waypoints 能否被 B1 链路原样消费？ | OpenLoopController 实际驱动通过 | 通过（`tests/test_strokeplan.py::test_waypoints_drive_openloop_controller`）✓ |

## 三项设计发现

实施期实测驱动的三条结论，比代码本身更值钱：

1. **砖墙滤波把接触边界抹宽 ~0.5/fc → 切分段边界内缩。** 零相位砖墙低通把接触边界抹开约 0.5/fc（fc=3 Hz → ~0.17 s ≈ 17 拍），切分段会裹进"悬空但笔在移动"的样本——实测给 40 mm 笔画伪造 17–21% 弧长，把 g_press(s) 的 s 轴整体拉歪。对策：`build_plan` 切分后把每段边界向内收缩 `trim = round(0.5·fs/fc)` 拍再重参数化。代价是每边丢 ~0.17 s 的起笔/收笔沿（该区间 g 小、z_ff 贡献小），换来段内每一拍的 XY 都真实在纸上。meta 记录 `edge_trim_s`。

2. **滤波旁瓣随信号幅度缩放 → 阈值 T = max(3σ, 5%·p99)。** 零相位砖墙滤波的旁瓣振铃随**信号**幅度缩放（实测 185 µT 笔画在悬空段留下 4–7 µT ≈ 2–4% 峰值的旁瓣），纯噪声口径的 3σ 阈值会在旁瓣上碎出成片伪 run，任何噪声标度的幅度门都挡不住——切分阈值必须同时随信号规模缩放：`T = max(3σ, rel_peak·p99(g_clean))`，旁瓣（≤4%）天然落在 5% 线下。

3. **时域滤波×书写速度耦合是管线固有属性 → 录制协议"示范速度≈执行速度"为硬要求。** 零相位滤波工作在时域：示范里写得快的段，其提按内容被压进更高频段、被 fc 低通削得更狠——同一真值曲线，±50% 变速与匀速两份示范经 fc=3 全管线后互差 ~2.4 µT；fc=10 弱滤波下互差回落到重参数化本征水平 <1 µT，证明这不是弧长重参数化的缺陷。含义：速度剖面差异大的示范之间不宜直接混用目标曲线。

## 已知局限与待验证

（含 2026-08-10 审计结论，详见 `docs/review-2026-08-10.md`）

**示范录制协议两条硬要求**（违反则管线静默失真或直接报错）：

1. **示范速度 ≈ 目标执行速度**——既因拖拽分量污染量级要一致（示范 |ΔB| 混压+拖总手感），也因时域滤波×速度耦合（发现 3）。
2. **首尾各留 ≥ 0.5 s 悬空**——σ 估计取自首段悬空 std；首段不安静 `estimate_sigma` 报错（可显式传 `sigma=` 绕过）。

**审计发现的局限**：

1. 四问验收数字可复现但**无机器断言**——`demo_target_pipeline.py` 只 print 不判定，验收产物（数字/图）未落盘归档。
2. `to_waypoints()` 存在 **z 符号跨帧矛盾**且缺 CHAR_ORIGIN 帧变换，接真实机械臂前待修。
3. 两臂彩排的开环臂**并未实际走 `to_waypoints()`**（Q3 用 `calib_lookup_z(g_d)` 逐拍重查代替），`Stroke.z_ff` 至今端到端零消费。
4. 切分门槛（min_len 0.3 s + 两侧各内缩 0.17 s）下**短于 ~0.64 s 的笔画被静默丢弃**（fc=3 时，仅计入 meta 计数）——楷书点、短撇等短笔画受影响，待真实示范上验证或按笔画类型调 fc。
5. 输入 7 列格式目前**唯一生产者是合成脚本**；真实示范需要磁流 × 机械臂 FK 的双源时间对齐层，该层零代码。
6. meta **未记录每笔时长**，`to_gd_series` 的 `stroke_duration_s` 只能靠调用方硬编码（示范的时域信息实际录了但没进 StrokePlan）。
