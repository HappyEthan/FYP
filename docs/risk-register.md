# 风险清单（活文档）

> 来源：`docs/review-2026-08-10.md` §2 审计。**本文是唯一的风险追踪清单**：修一个勾一个，只记状态与修复凭据（commit），详细论证与失效场景看 review 原文对应条目。
> 状态：`[ ]` 未修 / `[~]` 部分修复或已缓解 / `[x]` 已修。审计后新发现的风险直接追加编号。

---

## 高危（真机接入前必须清零）

- [x] **R1 · z_cmd 全链路无限幅** —— 已修 2026-08-10（`e06e90a`）：`step()` 全部出口过 `_clamp()`——绝对位置钳（压深 ≤ 标定量程+dz_margin+1mm，抬笔 ≤ 2cm）+ 单步速率钳（≤1mm/拍；Phase 1 全场景实测合法动态最坏 0.587mm/拍，1.7 倍裕度）。验证：标称 wp_PI 多笔画 z_cmd 与无钳位逐位相等，Phase 1 数字不受影响。runtime spec §5 的"z 有控制器钳位"前提随之成真。真机示范速度标定后可显式收紧 `dz_step_max`（流程见 `docs/z-control.md`）。
- [x] **R2 · NaN 失效链**（EMA 中毒 → guard 输出 NaN → 无告警退化）—— 已修 2026-08-10：`e06e90a` 堵 guard 出口（非有限输出回退上一拍指令）；`80aff7d` EMA 补 NaN 透传（非有限样本原样透传、状态不更新，与 filter.py 策略一致），断流恢复后闭环自动复活。补齐盲区测试：EMA 单体×2 + `run_loop`×EMA 整链恢复。
- [x] **R3 · `to_waypoints()` z 符号自相矛盾 + 缺帧变换** —— 已修 2026-08-10（P1 批）：统一 B1/物理世界帧（压 = `z_surface − z_ff` 纸面下，抬 = 纸面上）+ `origin` 参数（默认 CHAR_ORIGIN，包围盒中心平移）；Q4 升级为链路级测试 `test_waypoints_chain_writes_ink`（过 Scene/IK，断言笔尖真实压到纸面下且落在 origin 附近——旧代码在此测试下 0 落墨）。两帧纪律写入 strokeplan 模块 docstring；真机符号定点拆出为 **R20**。
- [ ] **R4 · S_cal 整表割线隐含线性标定假设**（`z_control.py:61-64`）：全部 Phase 1 数字建立在完美线性合成表上，真实曲线斜率差 ~4× 时有效环路增益被放大、裕度吃穿。**依赖硬件**：E2 真实标定表到手后重审（局部斜率或分段 S_cal），必要时重扫增益。

## 中危

- [~] **R5 · 闭环链绕开 backends 抽象 / HuayanBackend 契约只写了 write 半边** —— 部分推进（2026-08-10 上机日）：TactileExecutor（`runtime.py`）与 HuayanBackend（含 `read()`）已落地并真机验证（读位姿 / MoveL / PushServoP 3000+ 拍）。遗留收口：开环链"每拍两次 `read()` + `state.t` 驱动弧长"在真机上的契约复核；`State.g_meas` 死字段与 `backends/sim.py` 注释的口径统一。
- [x] **R6 · `Stroke.z_ff` 端到端零消费** —— 已修 2026-08-10（P1 批）：新增 `StrokePlan.to_open_z_series()`（开环臂 z 由存储 z_ff 字段插值生成，与 `to_gd_series` 逐拍对齐），Q3 两臂彩排开环臂改用之；`to_waypoints` 修复后也真实消费 z_ff。等价锁测试 `test_open_z_equivalence_lock_linear_calib` 守住 lookup/interp 分叉——标定表转非线性时测试红，逼出"两臂前馈从哪来"的显式决策（与 R4 联动）。
- [x] **R7 · 滤波器归属倒置 + 双频域基** —— 已修 2026-08-10（P2 批）：EMA 正典迁入 `filter.py`（`monitor/core.py` re-export 兼容全部旧 import，PR#1 的 FILTERS 工厂不受影响）；`CONTROL_EMA_ALPHA` 唯一常量源 + `make_control_filter()` 工厂，生产接线（run_tactile / E2E）已切换；频域基差异在 `docs/target-pipeline.md` 验收节单列为误差来源。
- [ ] **R8 · 真实示范数据无生产者**：monitor 录制 5 列 vs 管线输入 7 列（含 `x_m,y_m`）不匹配；磁流×机械臂 FK 双源时间对齐/重采样层零代码——换真数据时最先撞墙处。**依赖录制协议落地**（拖动示教 + 硬件）。
- [x] **R9 · 出厂默认 ki=0.134 未全场景复跑** —— 已复跑 2026-08-10：`compare_z_arms.py --kp-p 1.2077 --ki-p 0 --kp-pi 1.2077 --ki-pi 0.134 --filter "EMA a=0.3"` → `docs/archive/z-phase1-results-factory.md`。出厂口径：baseline PI 9.52%（PI≈P 符合预期）、扰动残留 31.6–41%（均略优于 P）、drift 被骗 62%、相位裕度 115.6°（解析复算）、**Q4 单笔画 0.1937mm PASS 在出厂口径下同样成立**、多笔画 3 笔收敛复确认——所有结论方向与旧口径一致，无翻盘。遗留：多笔画毛刺 0.2434mm 仍为开放项（真机笔尖实测裁决）；`docs/z-control.md` 数字表已双口径回填。
- [ ] **R10 · 参数回填与脚本默认值坑**：`z_control.py` `noise_std` 默认仍是裸态 7.0（run_loop 接线已用 `filtered_sigma()` 现算，但默认值与 kp/ki/noise_std 的属主断言测试仍缺）；`compare_z_arms.py --filter` 默认 OneEuro 与定稿 EMA 相反，复跑忘传参会静默产出错误滤波臂报告。
- [x] **A1 · E2E 验收数字无机器断言、产物零留存**（来自 review §1）—— 已修 2026-08-10（P1 批）：脚本重构为 `run_acceptance()`（Q1≤3 / Q2≤3.5 / Q3 闭环<开环全部 assert，失败非零退出），pytest 属主 `tests/test_target_pipeline_e2e.py` 随套件回归；plan npz + acceptance.json 入库 `docs/acceptance/`。注意基线数字随 R15 口径修正更新：Q3 开环 18.12% vs 闭环 13.22%（旧 17.57/10.60 为硬编码 3.0s 时长口径）。

- [ ] **R20 · 真机 z 符号定点未做**（2026-08-10 R3 修复时拆出；即 plan.md B2"符号/坐标系核对"的具体化）：ZController / sim_loop / TactileExecutor 全链用**压深正向帧**（压 = z_surface **+** 深度），而物理世界（Elfin z 上正）压笔 = z **下降**——真机上若把 z_cmd 原样当 TCP z 下发，"压笔"会抬臂、看门狗"抬笔"（`z_surface + lift`）语义也依赖帧向。定点动作：E2 装配态标定确认 dB–z 斜率符号后，在 **HuayanBackend 一处**做帧翻转（或显式确认安装方向使压深正向成立），并加符号一致性测试。真机首次接触实验前必须完成。

## 低危 / 工程卫生

- [ ] **R11** "3σ" 接触门实为 |ΔB| 分布 ~5.3σ（σ 取三轴 std 的模再比标量范数），命名误导、起收笔时机偏保守。
- [x] **R12** 常量分叉 —— 已修 2026-08-10（P2 批）：`config.FS` 为采样主频唯一定义（sim_loop/strokeplan/demo_pipeline/filter/runtime 全部引用）；`ZController` 默认 `z_surface=config.PAPER_Z`、`dt=1/config.FS`；合成线性标定表收敛为 `sim_loop.CALIB_Z_MM_LINEAR`/`CALIB_ABS_DB_LINEAR`（4 个脚本改引用，并在定义处标注 R4 直线警告）；`run_loop` 新增 `ctrl.dt`×FS 一致性 fail-loud 校验；钉住测试 `tests/test_constants.py`。
- [ ] **R13** 切分门槛静默吞短笔画（fc=3 时 <约0.64s 整段消失，楷书"点"/快撇量级）；饱和/丢弃报警走 print，meta 的 `sat_frac`/`n_dropped` 无人检查。
- [ ] **R14** p99 标度阈值隐含"笔画占录音 >1%"未记录（长闲置段录音会退化）；`estimate_sigma` 首段判据对含漂移的真实录音脆弱。
- [x] **R15** `stroke_duration_s` 未持久化 —— 已修 2026-08-10（P1 批）：`build_plan` 把逐笔裁后净接触时长写入 `meta["stroke_durations_s"]`；`to_gd_series(None)`/`to_open_z_series(None)` 默认按存储时长回放（缺失则 fail-loud），显式标量/序列可覆盖；npz 带 `format_version=2`。
- [ ] **R16** Q1 验收口径缩水：`_geom_rms` 只算 s∈[0.1,0.9] 内部 80%，起收笔沿被排除；XY 通道恢复误差结构性不可见。
- [~] **R17** 文档过时 —— 大头已在 2026-08-10 文档精简中处理（一模块一文档 + 引用修复）；剩 `src/brushbot/README.md` 仍停留在 B0+B1 时代。
- [ ] **R18** git 卫生：`origin/feat/deltab-monitor` 已完全并入 master，可删；`.superpowers/sdd` 报告跨 plan 同名覆盖不入库。
- [ ] **R19** 测试可移植性与数据单薄：6 项测试依赖仓内 V0 CSV，数据移走**静默 skip 而非 fail**；全部噪声结论建立在一份 ~10s 裸态 idle 录音上（长仿真绕回镜像延拓）——装配态 E0 后重录重估。

---

## 建议批次（修复顺序参考，来自 review §3）

1. ~~P0 安全三件套~~：R1 ✅ + R2 ✅（noise_std 属主测试归 R10，未清）
2. ~~P1 StrokePlan 出口~~：R3 ✅ + R6 ✅ + A1 ✅ + R15 ✅（2026-08-10，`feat/z-cmd-clamp` 分支）
3. ~~P2 归属/常量收敛~~：R7 ✅ + R12 ✅（2026-08-10；`feat/monitor-filter-ui` 已开 PR#1 待 GUI 手动验收，EMA re-export 保证其零冲击）
4. **纯软件可先行**：~~R9~~ ✅（2026-08-10 复跑无翻盘）、R10、R11、R13、R14、R16、R17、R18、R19（skip→fail 部分）
5. **等硬件**：R4（E2 标定）、R8（录制协议）、R5 收口（真机开环链复核）、**R20（真机 z 符号定点，首次接触实验前必须）**、R19 数据部分（装配态 E0）
