# Z 控制 Phase 1：滤波进环 + 时变跟踪 + 闭环验证

> 设计日期：2026-07-30
> 状态：设计（已过 brainstorming，用户逐节确认）
> 关联：`docs/handoff-z-phase1.md`（立项输入）、`docs/superpowers/specs/2026-07-28-z-control-phase0-design.md`（Phase 0）、`docs/filter-comparison.md`（选型报告）、`docs/z-phase1-explained.md`（通俗版解说）
> 范围决定：本期 = handoff §3.1（滤波进环）+ §3.3（时变跟踪/增益重调）+ 验证层 1/2。**§3.2 离线目标曲线管线推迟到下期**；层 3 MuJoCo 闭环不做。

---

## 1. 目标

把已选型的实时滤波器（OneEuro mc=0.5 β=0.03，待本期时域仿真定稿）接进 Z 控制环，在滞后进环的条件下重新整定增益，验证时变 g_d 跟踪，并产出"开环 vs 闭环在扰动下"的论文对比数字。

完成判据（handoff §3.4 四问，全部要有数字答案）：

| # | 问题 | 出处 |
|---|---|---|
| Q1 | 滤波接入后时变跟踪 RMS 是多少？比无滤波好多少？ | 层 1 矩阵 |
| Q2 | 滞后进环后增益稳定边界在哪？工作点裕度多少？ | 层 1 扫描 + 线性滤波频域核算 |
| Q3 | 开环 vs 闭环在各扰动下各偏差多少？ | 层 2 对比 |
| Q4 | freeze 切换处有无毛刺？ | 层 2 起笔/收笔波形 |

外加硬约束：现有全部测试无回归。

## 2. 已定案的四个设计决定

1. **开环对照臂 = 同一 `run_loop`、同一 ZController，Kp=Ki=0**（纯 `z_surface + z_ff` 查表）。两臂共享目标曲线、标定表、噪声序列（同 seed）、扰动时刻，论文口径"差异=触觉反馈"由单一代码路径保证。
2. **增益无量纲化进控制器**（§3.1 详述）。
3. **noise_std 不硬编码**：harness 运行时用噪声源现算滤波后 σ 传入。
4. **freeze 期间 Kp 保持作用**（Phase 0 行为不变），由 Q4 毛刺数据裁决；超标则 fallback 为 Kp 一并冻结（预留一行改动，见 §6.3）。

## 3. 组件设计

### 3.1 ZController 改造（`src/brushbot/z_control.py`）

控制律改为：

```
S_cal = (z_max − z_min) / (dB_max − dB_min)      # m/µT，构造时从标定表算
z_cmd = z_surface + z_ff(g_d) + kp·S_cal·e + z_fb
z_fb  += ki·S_cal·e·dt，clamp ±dz_margin          # dz_margin 仍为物理量 ±3 mm
```

- `kp`/`ki` 变为无量纲（语义："每拍把误差的多少比例折算成压深修正"）。**参数名与签名不变，语义变**。
- 暂定默认 `kp=0.3, ki=0.03`（demo 外部折算的现值）；层 1 扫描完成后**用工作点回填默认值**（本期交付物之一）。
- `noise_std` 参数保留（µT 口径），默认 7.0 并在 docstring 注明"全带宽裸态口径，接滤波必须显式传滤波后 σ"。
- NaN/Inf guard、freeze 判定逻辑、`reset()`、属性接口全部不动。
- `demo_z_control.py` 里的外部折算逻辑（`kp=0.3*slope`）删除，直接用默认值。

### 3.2 仿真 harness（新建 `src/brushbot/sim_loop.py`）

纯 numpy，无 GUI/MuJoCo 依赖。四个公开单元：

**`V0NoiseSource(csv_paths, seed)`**
- 加载并拼接 idle CSV（`compare_filters.load_csv` 复用），逐通道去均值 → (N,3) 样本池。
- `sample(n)`：从 seed 决定的随机起点取**连续切片**（保 1/f 谱）；`n` 超池长时镜像拼接补齐。
- `filtered_sigma(make_filter)`：样本池过滤波器后的 |σ|（µT）——noise_std 现算的实现处；`make_filter=None` 返回原始 |σ|。

**`Plant(calib_z_mm, calib_abs_dB, dt=0.01, tau=0.05, n_delay=2, press_direction=默认(1,0.3,0.1)归一, noise=None, calib_scale=1.0, paper_step=None, drift_rate=0.0)`**

`step(z_cmd) → dB_raw (3,)`，内部依次：

1. **传输延迟**：z_cmd 进 `n_delay` 拍 FIFO（默认 2 拍=20 ms）。
2. **一阶执行器**：`z_act += (1−e^(−dt/τ))·(z_delayed − z_act)`，τ 默认 50 ms。**τ 与 n_delay 均为假设值**（真机未标定），层 1 做敏感性抽查（§4.1）。
3. **标定映射**：`z_off = z_act − (z_surface + paper_offset(t))`；`paper_step=(t_step, dz)` 在 t≥t_step 时给纸面加 ±dz。真实曲线 = 控制器标定表 × `calib_scale`（**plant 与控制器的曲线故意是两份**，`calib_scale≠1` 即标定偏差扰动）。插值出无噪声真值 `abs_true`。
4. **合成输出**：`dB_raw = press_direction·abs_true + drift_rate·t·press_direction + noise.sample(1)`。漂移沿 press_direction 注入（与信号同向 = 最坏情形，反馈无法区分）。

**`synth_press(fs=100, cal_max, ...)`** —— 层 1 标准目标曲线：悬空 0.5 s → 落笔 ramp 0→0.5·cal_max（0.3 s）→ 提按正弦扫频 0.5→3 Hz、幅度 ±0.3·cal_max（6 s）→ 收笔 ramp→0（0.3 s）→ 悬空 0.5 s。落笔/收笔斜坡保证穿越 3σ 阈值（触发 freeze 切换）。

**`press_from_v0(csv_path)`** —— 真实感目标：V0 动态段 (N,3) 经 `compare_filters.fft_lowpass`（零相位）后取 norm。先滤向量再取 norm（铁律）。

**`run_loop(ctrl, filt, g_d, plant) → dict`** —— 唯一闭环路径：

```python
for i, g in enumerate(g_d):
    raw  = plant.step(z_cmd)              # 上一拍指令的物理响应
    dB_f = filt.update(raw) if filt else raw
    z_cmd = ctrl.step(dB_f, g)
```

- 滤波器实例整段连续运行，**永不 mid-run reset**；NaN 照常透传到 ZController guard。
- 返回全量数组：t、g_d、dB_raw、dB_f、|dB_f|、z_cmd、z_ff、z_fb、frozen、z_act、abs_true。

**指标函数**（同模块）：
- `rms_pct(res)`：跟踪 RMS，%目标量程，**仅在 g_d ≥ 3·noise_std 的接触段上计算**。
- `osc_index(res)`：z_cmd 频谱中 >5 Hz 份额（rfft），振荡判定。
- `freeze_jump(res)`：freeze 切换点 ±5 拍窗口内 |Δz_cmd| 单步最大值。
- `diverged(res)`：z_cmd 非有限或偏离纸面超 2× 标定量程。

### 3.3 层 1 脚本（新建 `scripts/sweep_z_gains.py`）

- 矩阵：滤波 {None, EMA(0.3), Butterworth(8), OneEuro(0.5, 0.03)} × kp ∈ 对数网格 [0.05, 3]（10 点）× ki ∈ {0} ∪ 对数网格 [0.005, 0.5]（8 点）；目标 = `synth_press`，噪声 = V0 idle，固定 seed。
- 每格记录 rms_pct / osc_index / diverged；**稳定判定 = 不发散且 osc_index ≤ 0.05**（z_cmd 交流功率中 >5 Hz 份额不超过 5%，暂定值；若实测区分度差可调，调整值连理由写进报告脚注）。
- **工作点规则**：在"(2·kp, 2·ki) 仍稳定"的格子里取 rms_pct 最小者——时域 2 倍增益裕度，对非线性 OneEuro 同样适用。
- **频域核算**（仅线性滤波臂，回答 Q2 的"裕度多少度"）：开环传函 = PI(kp·S_cal, ki·S_cal) × 执行器(τ, n_delay) × plant 斜率 × 滤波器 `freq_response`，解析算相位裕度；OneEuro 不做频域数（坑 3），只报时域裕度倍数。
- **敏感性抽查**：各滤波臂的工作点在 τ ∈ {20, 50, 100} ms × n_delay ∈ {1, 2, 4} 下复跑，确认稳定性结论不被假设值翻转。
- 产出：每滤波臂 kp×ki 热力图 + 稳定边界（PNG，gitignored）+ `docs/z-phase1-sweep.md` 报告（表格 + 工作点 + 频域数 + 全部 caveat）。

**滤波器定稿规则**：OneEuro 工作点闭环 RMS ≤ EMA0.3 工作点，且层 2 全场景无失稳/毛刺异常 → 选型定稿 OneEuro；否则退 EMA0.3。结论写进报告与记忆。

### 3.4 层 2 脚本（新建 `scripts/compare_z_arms.py`）

- 固定：层 1 选出的滤波器 + 工作点；臂 {开环 kp=ki=0, 闭环}；目标 = `synth_press`（另跑一条 `press_from_v0` 复核）。
- 场景矩阵：

| 场景 | 参数 | 预期叙事 |
|---|---|---|
| 无扰动 | — | 基线 |
| 标定偏差 | calib_scale ∈ {0.8, 1.2} | 闭环补偿，开环整体偏差 ~±20% |
| 纸面阶跃 | 提按中段 ±0.5 mm | 闭环有限拍恢复，开环持续偏差 |
| 传感器漂移 | ±1 µT/s（整段 ~8 µT） | **诚实负面对照**：开环免疫，闭环被骗——量化差分测量必要性（坑 6） |

- 指标：接触段 RMS、稳态偏差（末段窗口均值误差）、纸面阶跃恢复时间（回到 ±2σ 带内耗时）。
- **Q4 毛刺判据**：freeze 切换处单步 |Δz_cmd| ≤ 正常跟踪段单步 |Δz_cmd| 的 p99 × 2，且绝对值 ≤ 0.2 mm，且切换后 0.5 s 内无新增振荡。超标 → 触发 §2.4 fallback（Kp 纳入 freeze），复跑层 1 工作点确认后更新本 spec。
- 产出：`docs/z-phase1-results.md`（§1 四问的正式答案表 + 波形图）。

## 4. 测试策略

### 4.1 更新 `tests/test_z_control.py`

- `test_step_tracks_constant`：删 kp=1e-5 magic number，**用默认增益**收敛（无量纲化的验收）。
- 新增：S_cal 计算正确性（已知标定表 → 已知斜率）；kp/ki 语义（单位阶跃误差下修正量 = kp·S_cal·e）。
- 其余 5 项测试语义不变，按需适配。

### 4.2 新建 `tests/test_sim_loop.py`

- 噪声源：σ 与样本池一致（±容差）；seed 可复现；切片连续性（低频功率显著高于高频——1/f 保真的粗检）。
- Plant：无扰动稳态输出与标定映射一致；calib_scale/paper_step/drift 各自生效且量级正确；τ/n_delay 的阶跃时序正确。
- run_loop：开环臂 z_fb≡0 且 z_cmd 与 z_ff 逐点一致；同 seed 两次运行逐位相同；注入 NaN → 滤波透传 → 控制器 freeze 且 z_cmd 有限（guard 链路回归）；闭环 + 默认增益 + 恒定目标收敛（Phase 0 行为回归）。

### 4.3 验收

§1 四问在 `docs/z-phase1-sweep.md` / `docs/z-phase1-results.md` 中全部有数字答案；`python -m pytest tests/` 全绿。

## 5. 文件变动

| 文件 | 动作 |
|---|---|
| `src/brushbot/z_control.py` | 改：增益无量纲化 + docstring |
| `src/brushbot/sim_loop.py` | **新建**：NoiseSource / Plant / 目标曲线 / run_loop / 指标 |
| `scripts/sweep_z_gains.py` | **新建**：层 1 扫描 → 报告 |
| `scripts/compare_z_arms.py` | **新建**：层 2 对比 → 报告 |
| `scripts/demo_z_control.py` | 改：删外部增益折算，改用 run_loop（消除第二条闭环路径） |
| `tests/test_z_control.py` | 改：适配无量纲增益 |
| `tests/test_sim_loop.py` | **新建** |
| `docs/z-phase1-sweep.md` / `docs/z-phase1-results.md` | 脚本产出 |
| `pyproject.toml` | 不变（零新依赖） |

## 6. 风险与已知边界

1. **τ=50 ms / n_delay=2 是假设值**：结论以敏感性抽查范围为限；真机执行器标定后需复核工作点。
2. **裸态噪声是乐观下界**（坑 6/选型保留 3）：全部数字挂"裸态"标签；装配态 E0 后重跑两个脚本即可复核（脚本吃 CSV 路径参数）。
3. **OneEuro 定稿仍是仿真结论**：装配态复测可能翻盘（EMI 谱形），记忆 `filter-selection-provisional` 的"勿定稿"约束继续有效，本期只定"裸态仿真条件下"的选型。
4. **漂移场景闭环劣化是特性不是 bug**：报告必须如实呈现（论证差分测量），禁止调参"修掉"它。
5. **计算量**：层 1 矩阵 ≈ 4×10×9 ≈ 360 次 run × ~800 拍，纯 numpy 秒级到分钟级，无需并行。
6. 真机运行时的"控制/显示滤波器双实例"约束（坑 2）属于集成期职责，本期 harness 天然单实例，不涉及。

## 7. 交付物清单

1. 改造后的 `ZController`（无量纲增益，扫描后回填的可用默认值）
2. `sim_loop.py` + 两个脚本 + 全部测试绿
3. `docs/z-phase1-sweep.md`：Q1/Q2 答案 + 稳定边界图 + 滤波器定稿结论
4. `docs/z-phase1-results.md`：Q3/Q4 答案 + 开环/闭环对比表 + freeze 波形
5. 更新记忆 `filter-selection-provisional`（定稿结论）与 handoff 文档状态行
