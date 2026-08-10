# 风险清单（活文档）

> 来源：`docs/review-2026-08-10.md` §2 审计。**本文是唯一的风险追踪清单**：修一个勾一个，只记状态与修复凭据（commit），详细论证与失效场景看 review 原文对应条目。
> 状态：`[ ]` 未修 / `[~]` 部分修复或已缓解 / `[x]` 已修。审计后新发现的风险直接追加编号。

---

## 高危（真机接入前必须清零）

- [x] **R1 · z_cmd 全链路无限幅** —— 已修 2026-08-10（`e06e90a`）：`step()` 全部出口过 `_clamp()`——绝对位置钳（压深 ≤ 标定量程+dz_margin+1mm，抬笔 ≤ 2cm）+ 单步速率钳（≤1mm/拍；Phase 1 全场景实测合法动态最坏 0.587mm/拍，1.7 倍裕度）。验证：标称 wp_PI 多笔画 z_cmd 与无钳位逐位相等，Phase 1 数字不受影响。runtime spec §5 的"z 有控制器钳位"前提随之成真。真机示范速度标定后可显式收紧 `dz_step_max`（流程见 `docs/z-control.md`）。
- [x] **R2 · NaN 失效链**（EMA 中毒 → guard 输出 NaN → 无告警退化）—— 已修 2026-08-10：`e06e90a` 堵 guard 出口（非有限输出回退上一拍指令）；`80aff7d` EMA 补 NaN 透传（非有限样本原样透传、状态不更新，与 filter.py 策略一致），断流恢复后闭环自动复活。补齐盲区测试：EMA 单体×2 + `run_loop`×EMA 整链恢复。
- [ ] **R3 · `to_waypoints()` z 符号自相矛盾 + 缺帧变换**（`strokeplan.py:54-58`）：抬笔 B1 帧、压笔 z-control 帧，B1 帧下笔不落纸；直接吐示范原始坐标（在机器人底座内），缺 `CHAR_ORIGIN` 变换。修复时把 Q4"B1 兼容"从形状级升级为过 Scene/IK 的链路级测试。**建议与 R6 同批修。**
- [ ] **R4 · S_cal 整表割线隐含线性标定假设**（`z_control.py:61-64`）：全部 Phase 1 数字建立在完美线性合成表上，真实曲线斜率差 ~4× 时有效环路增益被放大、裕度吃穿。**依赖硬件**：E2 真实标定表到手后重审（局部斜率或分段 S_cal），必要时重扫增益。

## 中危

- [~] **R5 · 闭环链绕开 backends 抽象 / HuayanBackend 契约只写了 write 半边** —— 部分推进（2026-08-10 上机日）：TactileExecutor（`runtime.py`）与 HuayanBackend（含 `read()`）已落地并真机验证（读位姿 / MoveL / PushServoP 3000+ 拍）。遗留收口：开环链"每拍两次 `read()` + `state.t` 驱动弧长"在真机上的契约复核；`State.g_meas` 死字段与 `backends/sim.py` 注释的口径统一。
- [ ] **R6 · `Stroke.z_ff` 端到端零消费**："两臂共享前馈由数据结构保证"未由代码保证——两臂彩排开环臂现场重算 `calib_lookup_z`，未走 `to_waypoints()`；线性标定表恰好掩盖 `lookup(interp)` vs `interp(lookup)` 分叉，真实非线性表下分叉直接混进论文核心数字。修法：开环臂改走 `to_waypoints()` + 加等价性锁测试。**建议与 R3 同批修。**
- [ ] **R7 · 滤波器归属倒置 + 双频域基**：EMA 住在 `monitor/core.py`（GUI 包）被控制侧 5+ 处反向 import，α=0.3 靠字面量多处同步；目标曲线（fc=3 零相位砖墙）与闭环测量（EMA，有滞后）活在两个频域基，该系统偏差已计入 Q3 的 10.60% 但未单列。修法：EMA 迁入 `filter.py` + 单一常量源（**宜与 `feat/monitor-filter-ui` 合并同批做**）；频域基差异在文档单列为误差来源。
- [ ] **R8 · 真实示范数据无生产者**：monitor 录制 5 列 vs 管线输入 7 列（含 `x_m,y_m`）不匹配；磁流×机械臂 FK 双源时间对齐/重采样层零代码——换真数据时最先撞墙处。**依赖录制协议落地**（拖动示教 + 硬件）。
- [ ] **R9 · 出厂默认 ki=0.134 未全场景复跑**：9.47% / 116° / Q4 PASS 全是 ki=0/0.005 口径；出厂配置已知的唯一逐拍指标（多笔画 freeze 毛刺 0.2434mm）超 0.2mm 暂定上限。**可纯软件先跑**：`compare_z_arms.py --ki-pi 0.134` 全场景重跑，统一口径；毛刺物理危害等真机笔尖实测裁决（见 `docs/z-control.md` 开放项）。
- [ ] **R10 · 参数回填与脚本默认值坑**：`z_control.py` `noise_std` 默认仍是裸态 7.0（run_loop 接线已用 `filtered_sigma()` 现算，但默认值与 kp/ki/noise_std 的属主断言测试仍缺）；`compare_z_arms.py --filter` 默认 OneEuro 与定稿 EMA 相反，复跑忘传参会静默产出错误滤波臂报告。
- [ ] **A1 · E2E 验收数字无机器断言、产物零留存**（来自 review §1）：四问验收只 print 不 assert，验收证据在 .gitignore 中，StrokePlan 从未 `save()` 落盘。修法：`demo_target_pipeline.py` 升级为 assert（或包成 pytest），plan npz + 数字 JSON 入库。

## 低危 / 工程卫生

- [ ] **R11** "3σ" 接触门实为 |ΔB| 分布 ~5.3σ（σ 取三轴 std 的模再比标量范数），命名误导、起收笔时机偏保守。
- [ ] **R12** 常量分叉：合成标定表字面量 3 份、`PAPER_Z=0.2` 3 份（`z_control`/`strokeplan` 不 import `config`）、采样率 5 处且 `run_loop` FS 与 `ctrl._dt` 无一致性校验。
- [ ] **R13** 切分门槛静默吞短笔画（fc=3 时 <约0.64s 整段消失，楷书"点"/快撇量级）；饱和/丢弃报警走 print，meta 的 `sat_frac`/`n_dropped` 无人检查。
- [ ] **R14** p99 标度阈值隐含"笔画占录音 >1%"未记录（长闲置段录音会退化）；`estimate_sigma` 首段判据对含漂移的真实录音脆弱。
- [ ] **R15** `stroke_duration_s` 未持久化（spec 硬要求"示范速度≈执行速度"无落点，回放靠两个文件的字面量巧合相等）；StrokePlan npz 无版本号。
- [ ] **R16** Q1 验收口径缩水：`_geom_rms` 只算 s∈[0.1,0.9] 内部 80%，起收笔沿被排除；XY 通道恢复误差结构性不可见。
- [~] **R17** 文档过时 —— 大头已在 2026-08-10 文档精简中处理（一模块一文档 + 引用修复）；剩 `src/brushbot/README.md` 仍停留在 B0+B1 时代。
- [ ] **R18** git 卫生：`origin/feat/deltab-monitor` 已完全并入 master，可删；`.superpowers/sdd` 报告跨 plan 同名覆盖不入库。
- [ ] **R19** 测试可移植性与数据单薄：6 项测试依赖仓内 V0 CSV，数据移走**静默 skip 而非 fail**；全部噪声结论建立在一份 ~10s 裸态 idle 录音上（长仿真绕回镜像延拓）——装配态 E0 后重录重估。

---

## 建议批次（修复顺序参考，来自 review §3）

1. ~~P0 安全三件套~~：R1 ✅ + R2 ✅（noise_std 属主测试归 R10，未清）
2. **P1 StrokePlan 出口**：R3 + R6 + A1 + R15（同一片代码，一批修完）
3. **P2 合并窗口**：R7 + R12（趁 `feat/monitor-filter-ui` 合并做归属/常量收敛）
4. **纯软件可先行**：R9（出厂增益复跑）、R11、R13、R14、R16、R17、R18、R19（skip→fail 部分）
5. **等硬件**：R4（E2 标定）、R8（录制协议）、R5 收口（真机开环链复核）、R19 数据部分（装配态 E0）
