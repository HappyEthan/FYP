# 离线目标曲线管线（§3.2）：示范录音 → StrokePlan

> 设计日期：2026-07-31
> 状态：设计（已过 brainstorming，用户逐节确认）
> 关联：`docs/handoff-z-phase1.md` §3.2（立项来源）、`docs/superpowers/specs/2026-07-30-z-control-phase1-design.md`（消费方 harness）、`docs/callirewrite-arm-control.md`（开环 baseline 蓝本）、记忆 `architecture-strokeplan-interface`
> 范围：管线 + StrokePlan 契约落地 + 合成示范生成器 + 端到端仿真验收。**不含**：真实录制协议实施（等硬件）、执行器 runtime 集成、速度剖面优化。

---

## 1. 目标

把"示范录音 → 可执行目标"的离线管线建成：

```
示范 CSV (ΔB+XY 同步) → 零相位滤波 → 切笔画 → 弧长重参数化 g_press(s)
                       → 标定反查 z_ff(s) → StrokePlan(.npz)
```

一石二鸟：`StrokePlan.to_waypoints()` 即 CalliRewrite 式开环 baseline 轨迹（B1 链路直接执行）；`to_gd_series()` 即闭环臂目标（喂 `run_loop`/未来 runtime）。两臂共享同一份前馈，论文口径"差异=触觉反馈"由数据结构保证。

## 2. 已定案的设计决定

1. **输入格式**：示范 CSV = 监控格式超集 `t_us,t_s,dBx_uT,dBy_uT,dBz_uT,x_m,y_m`（100 Hz）。录制协议约定首尾各 ≥0.5 s 悬空段。真示范到位前用合成生成器产同格式数据开发测试。
2. **StrokePlan = 轻量 dataclass + 导出方法**（`src/brushbot/strokeplan.py`），架构契约就此落地。
3. **验收 = 端到端仿真**：合成示范 → 管线 → 两臂在 sim_loop Plant 上对比（§6 四问）。
4. **模块组织 = 方案 A**：`demo_pipeline.py`（纯函数流水线）与 `strokeplan.py`（数据契约）独立于 `sim_loop.py`（仿真 harness），管线 import `sim_loop.fft_lowpass` 复用。
5. **单位纪律（显式立规）**：计算核心一律 SI（米）；带单位后缀的字段（`calib_z_mm`、`dBx_uT`）允许非 SI，在边界一次性换算；展示层随意。理由：PyBullet/MuJoCo 把链条两端焊死在 SI，米↔毫米换算当前仅存两处（标定表入口、未来 HuayanBackend 内部）已是最小值。**不做毫米化迁移**（2026-07-31 已勘察裁决，24 文件/130 测试的纯 churn，收益为零）。
6. **NaN 纪律与实时链路相反**：离线管线对坏数据**当场报错**（指出行号），不透传——目标曲线的源头必须干净；NaN 透传是实时反馈链路的专属纪律。

## 3. 组件设计

### 3.1 `src/brushbot/strokeplan.py`（新建）

```python
@dataclass
class Stroke:
    s: np.ndarray        # (M,) 均匀弧长网格, 归一化 [0,1]
    xy: np.ndarray       # (M,2) 米
    g_press: np.ndarray  # (M,) µT, 零相位滤波后的目标手感
    z_ff: np.ndarray     # (M,) m, 前馈压深 offset（不含 z_surface）

@dataclass
class StrokePlan:
    strokes: list[Stroke]
    meta: dict           # calib 指纹(哈希或首末值)、fc、M、源文件名、丢弃笔画计数、饱和样本占比
```

方法：

- `to_waypoints(z_surface=0.20, lift=0.015) -> list[tuple[float,float,float]]`
  每笔：起点上方 `(x0, y0, z_surface+lift)` 悬空进入 → M 个 `(x, y, z_surface + z_ff)` → 终点上方抬笔点。裸 (x,y,z) 列表，`OpenLoopController` 零改动消费。
- `to_gd_series(stroke_duration_s, fs=100.0, gap_s=0.5) -> tuple[np.ndarray, np.ndarray]`
  每笔按匀速剖面把 g_press(s) 重采样回时域（s = t/duration），笔画间插 `gap_s` 的 g_d=0 悬空段（触发 freeze 切换，与层 2 场景同构）。返回 `(g_d(T,), xy(T,2))`，可直接喂 `run_loop`。
- `save(path)` / `load(path)`：npz 往返无损（meta 以 JSON 字符串存入 npz）。

### 3.2 `src/brushbot/demo_pipeline.py`（新建，纯函数）

```python
load_demo(csv_path) -> {"t": (N,), "xy": (N,2), "dB": (N,3)}
# 校验 7 列齐全；缺 x_m/y_m → 报错并提示与 V0 老格式的差异；任何非有限值 → 报错并指出首个坏行

estimate_sigma(g_clean, fs=100.0, head_s=0.5) -> float
# 首段悬空的 std；若首段明显非静止（std 超过一个宽松阈值，如 > 全段 std 的一半）→
# 报错提示"录制需首尾悬空 ≥0.5s，或显式传 sigma"

segment_strokes(g_clean, sigma, fs=100.0, min_len_s=0.3, merge_gap_s=0.15, peak_k=6.0)
#   -> (segs: list[tuple[int,int]], n_dropped)
# 接触 = g ≥ 3σ 连续段。鲁棒性（2026-07-31 实施期修订，实测驱动）：滤波后噪声的
# 相关时间 ~0.15s，g 在接触边界缓慢穿越阈值时噪声造成抖动穿越，纯阈值切分会碎出
# 大量短 run。三道门依次处理：① 间隙 < merge_gap_s 的相邻 run 合并（边界抖动吸收
# 进主段）；② 合并后峰值 < peak_k·σ 的 run 是噪声游走，静默弃置——它们不是"被丢弃
# 的笔画"，不计入 n_dropped；③ 过了幅度门但短于 min_len_s 的 run 才计入 n_dropped
# （真正可疑的短笔画）。

reparam_arclength(xy_seg, g_seg, M=200) -> (s, xy_s, g_s)
# 累计弧长归一化 + 均匀 M 点重采样（np.interp）；总弧长 < 1 mm → 该笔丢弃并计数
# XY 停顿产生的 s 平台是合法输入（非降序列，interp 安全）

build_plan(demo, calib_z_mm, calib_abs_dB, fc=3.0, M=200, sigma=None) -> StrokePlan
# 编排：sim_loop.fft_lowpass 整段 (N,3) 向量（先滤向量再取 norm，铁律）→ norm
# → σ（sigma 参数可覆盖）→ 切分 → 边界内缩 trim → 逐笔重参数化 → z_ff 反查 → 打包
```

**滤波顺序决策**：整段滤波后再切笔画（避免短笔画的 FFT 边缘伪影；切分用滤后信号，边界干净）。

**边界内缩（2026-07-31 实施期修订，实测驱动）**：零相位砖墙低通把接触边界抹开约 **0.5/fc**（fc=3Hz → ~0.17s ≈ 17 拍），切分段因此会裹进"悬空但笔在移动"的样本——实测漏 14–20 拍、给 40mm 笔画伪造 17–21% 弧长，把 g_press(s) 的 s 轴整体拉歪。真实示范同样存在此物理（笔画间笔在空中移动）。故 `build_plan` 在切分后把每段边界向内收缩 `trim = round(0.5·fs/fc)` 拍再重参数化；裁后过短的段并入丢弃计数。代价是每边丢 ~0.17s 的起笔/收笔沿（该区间 g 小、z_ff 贡献小，执行端本来就从悬空 ramp 进入），换来的是段内每一拍的 XY 都真实在纸上。meta 记录 `edge_trim_s`。

**共享反查（小重构）**：把 `ZController._z_ff_lookup` 的排序+插值+饱和逻辑提为 `z_control.py` 模块级公开函数 `calib_lookup_z(g, calib_z_mm, calib_abs_dB) -> z_offset_m`，`ZController` 与管线共用——"想要多重→压多深"全项目只允许一份实现。反查饱和样本占比记入 `meta`，>5% 时 warning（示范力度超出标定范围的信号）。

### 3.3 `scripts/synth_demo.py`（新建）——带真值的合成示范生成器

- K 笔（直线+圆弧混合），每笔已知 `g_press_true(s)`（落笔 ramp → 提按起伏 → 收笔，s 域定义）。
- **±50% 正弦变速剖面**（把 s 域真值播放成变速时域信号——弧长重参数化的专属考题；另可产匀速版本供不变性测试）。
- `ΔB = press_direction × g + V0 idle 噪声切片`（`V0NoiseSource` 复用，同 seed 可复现）；笔画间 ≥0.5s 悬空段；首尾悬空段满足录制协议。
- 产出：示范 CSV（§2 格式）+ 真值 npz（每笔 `g_press_true(s)` 于同一 s 网格）。

### 3.4 `scripts/demo_target_pipeline.py`（新建）——端到端验收

合成示范 → `build_plan` → 三件事：

1. **恢复精度**：管线 g_press(s) vs 真值逐笔 RMS（§6 Q1）；
2. **速度解耦**：匀速 vs 变速两份示范各自过管线，恢复结果互差 RMS（§6 Q2）；
3. **两臂彩排**：sim_loop Plant + `calib_scale=0.8` 扰动下，开环臂（`to_waypoints` 的 z 序列直接执行）vs 闭环臂（`to_gd_series` 喂 `run_loop`，EMA α=0.3 + 出厂默认增益），出跟踪 RMS 对比 + 波形图（§6 Q3）。

产出打印验收数字 + PNG（docs/assets/，gitignored）。不生成常驻 md 报告（一次性验收，数字进 spec/handoff 收尾更新即可）。

## 4. 错误处理汇总

| 情形 | 行为 |
|---|---|
| CSV 缺列 / 含非有限值 | 报错（指出缺哪列 / 首个坏行行号），不静默跳过 |
| 首段悬空缺失（σ 估计不可信） | 报错提示录制协议，允许显式 `sigma=` 覆盖 |
| 笔画过短（<0.3 s）或弧长过短（<1 mm） | 丢弃 + meta 计数，`build_plan` 结束时打印摘要 |
| g 超出标定范围 | 饱和到边界（与 ZController 同一函数），占比进 meta，>5% warning |
| npz load 时标定指纹与当前表不符 | 由消费方自查（meta 提供指纹），本期不强制 |

## 5. 测试策略（tests/test_strokeplan.py + tests/test_demo_pipeline.py）

- **strokeplan**：npz 往返逐字段相等；`to_waypoints` 结构（悬空进入/抬笔点次序、z 范围合法、总点数 = Σ(M+2)）；`to_gd_series` 长度、悬空段位置、g_d 非负。
- **pipeline**：合成 3 笔示范 → 切出恰好 3 笔且边界 ±2 拍；**变速不变性**（同一真值、两种速度剖面 → 恢复差 RMS ≤ 1 µT）；恢复精度（≤ 3 µT）；饱和保护与 meta 计数；三条报错路径（缺列/NaN/首段不静）各一测。
- **B1 兼容**：`to_waypoints` 输出实际驱动 `OpenLoopController` 若干步不抛错（§6 Q4）。
- V0 数据缺失 → `needs_v0` 惯例优雅 skip；全部现有 130 项测试无回归。

## 6. 验收（四问四数字）

| # | 问题 | 判据 |
|---|---|---|
| Q1 | 带噪变速录音里恢复的 g_press(s) 离真值多远？ | 逐笔 RMS ≤ 3 µT（≈零相位滤波残噪水平，量程 200 µT 的 1.5%） |
| Q2 | 匀速 vs 变速示范的恢复结果差多少？ | 单测（fc=10 弱滤波，隔离耦合）互差 RMS ≤ 1 µT——纯考弧长重参数化；全管线 fc=3 的 E2E 互差**如实报告**（含"时域滤波×速度"固有耦合，预期 ~2–3 µT，sanity 上限 3.5 µT）（2026-07-31 实施期修订，见 §8.5） |
| Q3 | 管线产出目标喂两臂，calib×0.8 下各偏多少？ | 闭环 RMS < 开环 RMS，方向与层 2 结论一致 |
| Q4 | to_waypoints 能否被 B1 链路原样消费？ | OpenLoopController 实际驱动通过 |

## 7. 文件变动

| 文件 | 动作 |
|---|---|
| `src/brushbot/strokeplan.py` | **新建** |
| `src/brushbot/demo_pipeline.py` | **新建** |
| `src/brushbot/z_control.py` | 小改：提取 `calib_lookup_z` 公开函数，ZController 委托 |
| `scripts/synth_demo.py` / `scripts/demo_target_pipeline.py` | **新建** |
| `tests/test_strokeplan.py` / `tests/test_demo_pipeline.py` | **新建** |
| `pyproject.toml` | 不变（零新依赖） |

## 8. 风险与边界

1. **示范 \|ΔB\| 混拖拽分量**：录出的 g_press 是"压+拖总手感"，与 Phase 0/1 标量口径自洽，但 z_ff 反查带系统偏差——反馈的存在意义正在于此（层 2 已证明）；彻底分离等 Phase 2。录制协议应注明"示范速度接近目标执行速度"（拖拽污染量级一致）。
2. **真实录制协议未定案**（XY 来源倾向机械臂拖动示教，但等硬件）——管线只依赖 CSV 格式，协议变化不影响本期代码。
3. **匀速执行剖面是权宜**：`to_gd_series` 用匀速，真实书写速度剖面（示范的时域信息其实录了）留到 runtime 期按需启用——YAGNI，本期不做。
4. 合成示范的 press_direction 是固定向量，真实示范方向会随笔画变化——对标量管线无影响（norm 不变），Phase 2 才需要方向保真。
5. **时域滤波×书写速度耦合（2026-07-31 实测发现）**：零相位滤波工作在时域，示范里写得快的段其提按内容被压进更高频段、被 fc 低通削得更狠——同一真值曲线，±50% 变速与匀速两份示范经 fc=3 全管线后互差 ~2.4 µT。这是管线固有属性而非重参数化缺陷（fc=10 弱滤波下互差回落到重参数化本征水平 <1 µT）。含义：录制协议"示范速度接近目标执行速度"从建议升级为要求（第二条理由）；速度剖面差异大的示范之间不宜直接混用目标曲线。

## 9. 交付物

1. `strokeplan.py` + `demo_pipeline.py` + 两个脚本 + 测试全绿（130 + 新增）
2. §6 四问的数字答案（脚本打印，收尾时写进 handoff §3.2 状态更新）
3. `calib_lookup_z` 重构后现有测试无回归
