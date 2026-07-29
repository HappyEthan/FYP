# Spec: 监控窗口滤波接入 + XY 拖尾 + 回放进度条

> 日期：2026-07-29
> 分支：master（新分支 feat/monitor-filter-ui）
> 前置：`docs/superpowers/specs/2026-07-29-filter-design.md`（滤波器库）、`docs/filter-comparison.md`（选型报告）、`docs/monitor-usage.md`（窗口现状）

---

## 1. 背景与目标

监控窗口目前用 EMA 批量重滤做显示平滑（`window.py:363-364`），滤波器库（Butterworth/OneEuro）已并入 master 但窗口未接入。

**目标**（三块，均为显示层改造）：
1. 工具栏滤波器选择器 + 原始信号淡色叠影，实时对比降噪效果与滞后代价。
2. XY 圆方向点改用选中滤波器，加最近 3 s 拖尾轨迹。
3. 回放进度条（可拖动 seek）。

**非目标**：
- 不改接触判定、门控、录制语义——**录制的永远是原始 ΔB**，滤波仅影响显示。
- 不做流式增量滤波（保持每帧批量重滤架构，见 §2）。
- MuJoCo 联动（UDP 桥 + SocketSource）为下一个独立项目。
- CLI 参数、XY 幅值刻度圈（用户明确不选）。

## 2. 架构决策

**保持每帧批量重滤**：`_redraw()` 里 `filt.reset(); dB_smooth = filt.update(dB)`，与现状同构。理由：显示效果与流式一致；基线重取后下一帧自动用新 ΔB 重滤，无状态失配；改动最小。OneEuro 批量模式用固定 dt=1/fs（V0 实测 dt 抖动 <0.2%，可忽略）。

选"原始"时 `filt = None`，跳过滤波直接画。

## 3. 滤波器选择器 + 叠影

- 工具栏 "滤波α" 下拉（`cb_alpha`）替换为 "滤波" 下拉（`cb_filter`），选项与工厂：

```python
FILTERS = {  # label -> 构造函数(每次切换/连接时新建); None = 原始
    "原始": None,
    "EMA 0.3": lambda: EMA(0.3),
    "Butter 5Hz": lambda: ButterworthFilter(5.0),
    "Butter 8Hz": lambda: ButterworthFilter(8.0),
    "OneEuro": lambda: OneEuroFilter(0.5, 0.03),
}
```

- 默认选中 "EMA 0.3"（与现状行为一致，不惊动用户习惯）。
- 四个时序图（ΔBx/ΔBy/|ΔBxy|/ΔBz）各加一条原始曲线垫底：淡灰 `#8b949e`、宽 1、约 35% 不透明度；滤波曲线保持现有亮色在上层。选"原始"时叠影隐藏、只画一条原始色曲线。
- `derive()`/接触指示/状态栏读数继续吃**原始** `dB[-1]`，与录制一致。

## 4. XY 圆升级

- 删除独立标量 EMA（`_prev_norm`/`_xy_alpha`）与 "XYα" 下拉——方向平滑统一由滤波选择器负责。
- 方向点 = 滤波后最后样本 `dB_smooth[-1]` 的 (x, y) / `_norm_radius`。
- 拖尾：最近 `TRAIL_S = 3.0` 秒的滤波后归一化轨迹，半透明细线（方向点同色系、约 30% 不透明度）+ 现有端点亮点。数据直接从 `dB_smooth` 切片取，无新增状态。
- 拖尾无独立状态（每帧从 `dB_smooth` 重算），重放/断开/seek 后下一帧自动恢复；`_restart` 现有的 XY 清空逻辑保留不动。
- 选"原始"时方向点/拖尾用原始数据（行为等同现状 α=1）。

## 5. 回放进度条

- `sources.py` `ArraySource` 加公开属性 `progress -> float`（0~1，`_i / len(_t)`，空数组返回 1.0），配套单测。
- 窗口：工具栏下方一行 `QSlider(0..1000)` + 标签 `"%.1f / %.1f s"`，仅当 `src` 有 `seek` 时显示（回放/合成），串口隐藏。
- 播放中每 `_tick` 用 `blockSignals(True)` 更新滑块位置防回环；用户 `sliderReleased` → `src.seek(value/1000)`；seek 不改变暂停状态。
- 与既有 ⟳ 重放（seek(0)）、倍速、暂停共存，不改它们。

## 6. 测试与验收

**自动测试**（无 GUI）：
- `ArraySource.progress`：初始 0、读一半后 ∈ (0,1)、读完 = 1、`seek(0.5)` 后与 `_i` 一致。
- `FILTERS` 工厂：每个非 None 项构造出的对象有 `update`/`reset`，`update((N,3))` 返回 `(N,3)`。
- 现有全部测试无回归。

**手动验收清单**（本机有显示时执行，沿用监控项目惯例）：
```
□ 滤波下拉五个选项可切换，切换即时生效
□ 叠影：淡灰原始毛刺在下、亮色滤波曲线在上；选"原始"时只有一条曲线
□ OneEuro 档：静止段明显比 EMA 稳，快速动作跟手
□ XY 圆有 3 s 拖尾轨迹，重放/seek 后拖尾清空重来
□ 回放模式出现进度条，拖动跳转正确、时间标签正确；串口模式无进度条
□ 录制一段后用 scripts/analyze_deltab.py 验证 CSV 是原始 ΔB（与滤波选择无关）
□ 状态栏接触判定行为与改造前一致
```

## 7. 验收标准

```
□ FILTERS 工厂 + 选择器落地，默认 EMA 0.3
□ 原始叠影四图齐全，"原始"档单曲线
□ XY 拖尾 + XYα 下拉移除
□ ArraySource.progress + 进度条，串口模式隐藏
□ 录制/门控/接触逻辑零改动（diff 可证）
□ 自动测试全绿，手动验收清单交付用户
```
