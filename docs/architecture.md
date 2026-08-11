# 代码架构与模块地图

> 全仓代码地图与分层架构（触觉毛笔书法机器人 FYP，执行端 brushbot 包）。过程细节见 `docs/archive/` 与 git 历史。

---

## 分层架构

三层解耦（设计初衷：算法与 I/O 分离，"上实机 = 换后端"）：

| 层 | 位置 | 特点 |
|---|---|---|
| ① 纯算法 | `controller.py`、`z_control.py`、`filter.py`、`strokeplan.py`、`demo_pipeline.py`、`calligraphy/*` | 只依赖 numpy/PIL，不 import pybullet，可毫秒级单测 |
| ② 后端 | `backends/*`、`scene.py` | 对接 PyBullet（实机对接华沿 SDK，未实现） |
| ③ 运行循环 | `run.py`（开环）、`sim_loop.py:run_loop`（闭环） | read → step → write 定频循环 |

当前实际存在**两条链路**，分层的覆盖范围不同（2026-08-10 审计结论，详见 `docs/review-2026-08-10.md`）：

- **开环书写链**：`write_hanzi` / `write_openloop` → `OpenLoopController`（弧长匀速插值，只读时间不看反馈）→ `run.run()` → `SimBackend` → PyBullet。这条链完整走三层，"只换后端层就能上实机"**仅对它成立**。
- **闭环 Z 控制链**：目标曲线（`StrokePlan.g_press` 或合成）→ 滤波（定稿 EMA α=0.3）→ `ZController`（前馈标定反查 + 低增益无量纲 PI）→ `sim_loop.run_loop`。该链目前**自建 Plant（延迟/执行器/扰动模型），不经过 backends 抽象**；真机接入按 2026-08-05 runtime-integration spec 走 `TactileExecutor`（含注入时钟、与 run_loop 位对齐），**尚未实现、纯 spec**。
- 两链的共同前馈来源是 `StrokePlan` 契约（离线目标管线的输出）：`s` 归一化弧长、`xy` 米、`g_press` µT、`z_ff` 米。
- 历史勘误：早期设计文档中的 `AdmittanceController` **从未实现**，实际控制器是 `ZController`；"backends/ 是唯一碰 pybullet 的地方、上实机只换②"的说法仅对开环链成立。

`State`/`Command`（`types.py`）是层间唯一语言：`tcp_pose` 恒为 6 元组（米/弧度），`g_meas` 为触觉提按分量（仿真占位 `ZeroTactile` 恒 0）。

---

## 模块地图

### src/brushbot/ 顶层

| 文件 | 职责 | 层 |
|---|---|---|
| `config.py` | 全部常量（URDF/EEF/纸面高度/姿态/步长等）及取值理由 | 公共 |
| `types.py` | `State` / `Command` 数据类，层间唯一传递物 | 公共 |
| `run.py` | 开环通用运行循环（一拍两次 read：控制器输入 + 轨迹记录） | ③ |
| `controller.py` | `OpenLoopController`：路点折线弧长匀速插值 | ① |
| `filter.py` | 逐样本实时滤波器：EMA（控制环定稿，α 常量源 + `make_control_filter` 工厂）/ Butterworth / One Euro（NaN 透传策略） | ① |
| `z_control.py` | `ZController`：Z 轴闭环（前馈 `calib_lookup_z` 反查 + PI + freeze/积分限幅） | ① |
| `sim_loop.py` | 闭环仿真 harness：V0 噪声回放 + Plant + 唯一闭环路径 `run_loop` | ③（闭环链，自建 Plant） |
| `strokeplan.py` | `StrokePlan`/`Stroke` 契约：开环/闭环共同前馈来源，含 save/load 与路点导出 | ① |
| `demo_pipeline.py` | 离线目标管线：示范 CSV（ΔB+XY 同步）→ StrokePlan，坏数据当场报错 | ① |
| `scene.py` | PyBullet 封装：载臂/全位姿 IK/可动关节映射/步进 | ② |
| `sim_visuals.py` | 纯视觉道具：毛笔/纸/桌/刷墨贴图（无碰撞） | ② 辅助 |
| `write_hanzi.py` | 入口 A：写任意汉字（graphics.txt medians，主力） | 入口 |
| `write_openloop.py` | 入口 B：写手编笔序（复现 CalliRewrite） | 入口 |

### 子包

| 文件 | 职责 | 层 |
|---|---|---|
| `backends/base.py` | `RobotBackend` 协议（read/write，结构化鸭子类型） | ② |
| `backends/fake.py` | 假后端：命令回显 + 时间累加，纯逻辑测试用 | ② |
| `backends/sim.py` | PyBullet 后端（全位姿 IK）+ `ZeroTactile` 占位触觉 | ② |
| `calligraphy/hanzi.py` | 真实字形 medians → 缩放居中 → 路点（主力轨迹来源） | ① |
| `calligraphy/strokeseq.py` | CalliRewrite 笔序 → 米制路点（复现用） | ① |
| `calligraphy/calibration.py` | `func_brush`：笔宽 r → 笔高 z 分段线性标定 | ① |
| `calligraphy/render.py` | 运动结束后离线渲染墨迹 PNG | ① |
| `calligraphy/inkcanvas.py` | 实时墨迹画布（PIL，边写边刷进仿真贴图） | ① |
| `monitor/core.py` | 监控无 GUI 核心：环形缓冲/基线/派生量（EMA 已迁 `filter.py`，此处 re-export） | 独立支线 |
| `monitor/sources.py` | 可插拔信号源（串口/仿真/回放），输出原始 B | 独立支线 |
| `monitor/recorder.py` | 录制成 V0 数据集格式（CSV+JSON） | 独立支线 |
| `monitor/window.py` | PyQtGraph 监控窗口（唯一允许 import GUI 库的模块） | 独立支线 |
| `tactile/antenna_model.py` | P0 磁学半段：中线形变 → 偶极子链 → 传感器 ΔB（纯 numpy） | 触觉仿真 |
| `tactile/contact_sim.py` | MuJoCo 接触涌现形变 → 复用 P0 磁学 → ΔB | 触觉仿真 |
| `tactile/writing_tactile.py` | 写字运动实时驱动合成 ΔB（合成 g_meas 源） | 触觉仿真 |
| `tactile/separability.py` | 压/拖可分性量化，喂 E4 判据 | 触觉仿真 |
| `tactile/mj_write.py` | 方案 B 全 MuJoCo：臂 + 物理触角 + 纸 | 触觉仿真 |
| `examples/strokes.py` | 手编"十"字笔序样例 | 数据 |

### scripts/

| 脚本 | 职责 |
|---|---|
| `watch_write.py` | 交互式写字入口（GUI/按键/换字/视角） |
| `watch_write_tactile.py` | 写字 + 笔尖触角弯曲 + 实时 ΔB 曲线 GUI |
| `analyze_deltab.py` | V0 数据集分析：完整性/噪声底/基线/幅度/可分性 |
| `make_replay.py` | ΔB 数据集打包为自包含交互式回放 HTML |
| `compare_filters.py` | 滤波器定量对比（EMA/Butterworth/OneEuro）孤立指标选型 |
| `sweep_z_gains.py` | 层 1：{滤波}×{kp,ki} 增益扫描 → 稳定边界与工作点 |
| `compare_z_arms.py` | 层 2：{开环, 闭环-P, 闭环-PI}×{扰动场景} 对比 |
| `demo_z_control.py` | Phase 0 demo：整体 ΔB 跟踪闭环三联图 |
| `synth_demo.py` | 合成示范生成器：带真值的示范 CSV + truth npz |
| `demo_target_pipeline.py` | 离线管线 E2E 验收：合成示范 → StrokePlan → 两臂对比 |

`tests/` 与模块一一对应（纯逻辑测试为主，仅 scene/sim_backend/write_* 少数文件需 pybullet，缺数据集自动 skip）。

---

## 文档地图

| 文档 | 内容 |
|---|---|
| `docs/z-control.md` | Z 轴闭环：ZController、sim_loop、增益标定与两臂对比 |
| `docs/filter.md` | 滤波器库与选型（孤立指标 vs 在环评估两口径） |
| `docs/monitor.md` | ΔB 实时监控：使用、录制、回放 |
| `docs/tactile-sim.md` | 触觉仿真（MuJoCo 路线）使用与现状 |
| `docs/openloop-writing.md` | 开环写字链：轨迹来源、PyBullet 场景、踩坑 |
| `docs/target-pipeline.md` | 离线目标管线：示范 CSV → StrokePlan |
| `docs/gate-experiments.md` | 门禁实验（E0/E1/E4 等）设计与判据 |
| `docs/status-2026-07-31.md` | 项目状态快照（08-05 更新） |
| `docs/review-2026-08-10.md` | 全仓审计：完成度核验、风险论证、跨会话脱节（时点快照） |
| `docs/risk-register.md` | **风险活清单**：审计风险的追踪状态与修复凭据，修一个勾一个 |
| `docs/superpowers/specs/` | 各模块设计档案（monitor / z-control Phase 0/1 / filter / 离线管线 / 2026-08-05 runtime-integration 等） |

---

## 环境与运行

- conda 环境 `brushbot`（Python ≥3.10）；依赖由 `pyproject.toml` 声明：numpy、pybullet、pillow、matplotlib、mujoco；监控 GUI 额外 `[monitor]`（pyqtgraph、PyQt5、pyserial）。
- 安装：`conda create -y -n brushbot python=3.10 && conda run -n brushbot pip install -e .`
- 写字：`conda activate brushbot && python scripts/watch_write.py 永`
- 监控：`conda activate brushbot && python -m brushbot.monitor`
- 测试：`conda run -n brushbot pytest`
