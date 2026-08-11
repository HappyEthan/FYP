# 开环写字模块（B0/B1）

> 本模块 = 三层控制架构 + PyBullet 仿真开环写字管线，复现 CalliRewrite（ICRA 2024）的"位置控宽度"开环基线，为触觉闭环（B2/Z 控制）提供对照。
> 代码：`src/brushbot/`（`run.py`、`write_openloop.py`、`write_hanzi.py`、`controller.py`、`scene.py`、`calligraphy/`、`backends/`）+ `scripts/watch_write.py`。
> 过程细节见 `docs/archive/` 与 git 历史。

## 做了什么

### 三层解耦架构

```
① 纯算法层 (numpy, 零环境依赖)   →  ② 后端 (可插拔)          →  ③ 运行循环 (通用)
   controller / calligraphy          SimBackend (PyBullet)        run.py: read→step→write
                                     FakeBackend (测试)
                                     HuayanBackend (实机, 待写)
```

| 模块 | 文件 | 作用 |
|---|---|---|
| 核心类型 | `types.py` | `State` / `Command`（6 元组 TCP 位姿 + `g_meas` + `t`） |
| 后端协议 | `backends/base.py` | `RobotBackend` Protocol：`read() -> State`、`write(cmd)` |
| 仿真/测试后端 | `backends/sim.py`、`backends/fake.py` | `SimBackend`（全位姿 IK + substeps 推进 + 累计 `t`）、测试桩 |
| 运行循环 | `run.py` | `run(backend, controller, on_tick)`，仿真/实机同一循环 |
| 场景 | `scene.py` + `config.py` | Elfin5 URDF + IK/FK；`PAPER_Z` 是抽象书写平面（非碰撞体） |
| r→z 标定 | `calligraphy/calibration.py` | `func_brush`：笔宽 r → 笔高 z（端口自 CalliRewrite）+ 通用分段线性 |
| 笔序转换 | `calligraphy/strokeseq.py` | `process()`：`(p_t,x,y,r)` → 米制 `(x,y,z)` 路点（含楷书入锋、末尾抬笔） |
| 字形轨迹 | `calligraphy/hanzi.py` | Make Me a Hanzi medians → 缩放/居中 → 每笔"抬-落-走-抬"路点 |
| 控制器 | `controller.py` | `OpenLoopController`：沿路点折线按弧长匀速插值目标位姿（`d = speed * state.t`） |
| 渲染 | `calligraphy/render.py`、`inkcanvas.py` | 笔尖轨迹 → 墨迹 PNG；仿真纸面实时刷墨 |
| 端到端 | `write_openloop.py` / `write_hanzi.py` | 写笔序（"十"）/ 写任意汉字（9574 字） |

两条轨迹来源，共用同一控制器与循环：`write_openloop` 走 CalliRewrite 笔序（笔宽随 r 变化），`write_hanzi` 走真实字形中线（笔宽恒定，提按留给触觉闭环）。姿态用全位姿 IK 保持笔杆垂直（`config.FIXED_ORI`）；Elfin5 为 6-DOF 非冗余臂，位置 IK 精确无解支跳变。

### CalliRewrite 复现要点（对标结论）

CalliRewrite 的本质：**纯开环 PTP 位置控制，笔画粗细完全靠"压多深"（z 高度）凑，z 由一条 r→z 标定曲线决定，无任何力觉/反馈**（详拆见 `docs/callirewrite-arm-control.md`）。

**它缺什么、我们怎么补：**

| CalliRewrite（Dobot） | 本项目 |
|---|---|
| `RoboControl.Control()` 发送循环**未开源**（全仓无脚本调用 `SetPTPCmd`） | 自写 `run.py` 通用循环 + `RobotBackend` 后端抽象，仿真/实机同链路 |
| Dobot DLL（Windows 专用），Elfin 用不了 | `SimBackend`（PyBullet IK）；实机换 `HuayanBackend`（华沿 SDK `HRIF_PushServoP`），算法层不动 |
| `r→z` 标定 + `func_brush` | 移植入 `calligraphy/calibration.py`，方法保留（见下） |
| `process()` 起笔/回锋手工启发式 | 端口入 `calligraphy/strokeseq.py`（楷书入锋 + 末尾抬笔） |
| 无力觉、开环误差累积、sim2real 靠标定凑 | **触觉力控提按 = B2 超越点**：真机采真实触觉，天然缩小 sim2real |

**r→z 标定思路**（sim2real 桥梁，作者称最关键）：手测 z 行程两端（刚触纸 `max_z`、压到极限 `min_z`）→ 分档取若干 z，每档在纸上画一条横线 → 尺量每条线宽取半径 → `(r, z)` 散点分段线性拟合（毛笔 4 段）→ 得 `func_brush(r)`，带溢出保护。斜率全为负：**r 越大（笔画越宽）→ z 越小（压得越深）**。每支笔、每张纸都要重标。

## 怎么跑

首次安装（仓库根目录）：`conda run -n brushbot pip install -e .`

下载字形数据（写汉字需要，30MB）：`mkdir -p data/makemeahanzi && curl -fsSL https://raw.githubusercontent.com/skishore/makemeahanzi/master/graphics.txt -o data/makemeahanzi/graphics.txt`

写笔序"十"（横竖两直线，弹窗看机械臂执行）：`conda run -n brushbot python -c "from brushbot.write_openloop import write; from brushbot.examples.strokes import SHI_SEQ; print(write(SHI_SEQ, gui=True))"`

写任意汉字 + 实时看墨迹渲染（窗口内 r=重写 c=清纸 n=换字 1-4=视角 q=退出）：`conda activate brushbot && python scripts/watch_write.py 永`

多字轮换：`conda activate brushbot && python scripts/watch_write.py 永 書 王 龍`

无窗口批量出图：`conda activate brushbot && python scripts/watch_write.py 書 --headless`

跑测试：`conda run -n brushbot pytest`

调参改 `scripts/watch_write.py` 的 `run_session()`：`size`（字框边长，默认 0.032 m）、`speed`（运笔速度 m/s）、`zc_down`（落笔压深，越小笔画越粗）。

## 结果

- **链路端到端跑通**：字形/笔序 → `process()`/`strokes_to_waypoints()` → 弧长插值 → IK → 仿真执行 → 墨迹渲染，全程一条 `run()` 循环。命令轨迹见 `docs/assets/b0b1-commanded.png`。
- **执行臂结论**：早期 KUKA（7-DOF 冗余）位置 IK 解支跳变导致墨迹严重畸变（`docs/assets/b0b1-actual.png`）；换 Elfin5（6-DOF 非冗余，真机同款 URDF，`config.ARM_URDF` 一行切换）后位置 IK 精确、畸变消除（`docs/assets/b0b1-actual-elfin.png`）。
- **任意汉字可写**：9574 字库按真实笔顺书写，样例 `docs/assets/hanzi-永.png`、`docs/assets/hanzi-書.png`。
- **架构验证**：算法层纯 Python 与环境无关，上实机只需新增后端实现；该解耦经复审确认可迁移（read 侧契约除外，见下）。
- **能力边界**：字形数据只给"笔往哪走"不给"按多重"，`write_hanzi` 笔画等宽；"压深→笔画变粗"由触觉闭环（B2/Z 控制）接手，正是本项目核心命题。

## 已知局限

来自 2026-08-10 审计（详见 `docs/review-2026-08-10.md`）：

1. **backend.read() 每拍两次 + read 侧契约未定义**：`run.py` 每拍先 `read()` 喂控制器、`write()` 后再 `read()` 喂 `on_tick`；弧长推进依赖 `state.t`（由 `SimBackend` 按 substeps 累计）。未来 `HuayanBackend` 的契约只定义了 write 侧，read 侧（`State.t` 从哪来、read 是否 TCP 往返、每拍两次是否可接受）没有规格，实机前必须补。
2. **三套 waypoint 生产者，坐标系口径不统一**：`calligraphy/hanzi.py`、`calligraphy/strokeseq.py` 的输出都经 `CHAR_ORIGIN` 平移落到纸面可达区；而 `strokeplan.to_waypoints()` 直接吐示范世界坐标（且 z 符号自相矛盾），真喂 `Scene.ik()` 解不出。合流前需统一帧变换口径。
3. **（实机项）纸面标定未做**：真实 `z_surface` 的三点示教流程尚未实现，`PAPER_Z=0.2` 只是仿真抽象平面。
4. r→z 曲线是 CalliRewrite 的笔/纸标出来的经验曲线，换笔换纸需按上述流程重标；起笔/回锋是手工启发式，非学习所得。
