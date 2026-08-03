# B0 + B1 成果 · 仿真开环写字（复现 CalliRewrite）

> 这份文档让你直接看到 B0+B1 做出了什么：三层控制架构 + 开环写字管线，在 PyBullet 仿真里跑通，全程不碰实机。
> 代码在 `src/brushbot/`，计划在 `docs/superpowers/plans/2026-07-15-b0-b1-sim-openloop.md`。
> 生成 2026-07-15。

---

## 1. 一眼看成果：命令轨迹 vs 仿真实际墨迹

| 命令轨迹（算法层输出，应该写成的样子） | 仿真实际墨迹（引导臂 KUKA 执行出来的样子） |
|:---:|:---:|
| ![commanded](assets/b0b1-commanded.png) | ![actual](assets/b0b1-actual.png) |
| **干净的"十"** —— `process()` 把笔序翻译成的 (x,y,z) 路点 | **畸变** —— 那条伸向左边的长线是 KUKA 冗余 7-DOF IK 解支跳变时法兰大幅摆动扫出来的（右侧仍可辨十字残形） |

**怎么读这两张图（诚实结论）：**
- **左图证明算法/管线是对的**：字形→笔序→`process()`→(x,y,z) 路点，输出的就是一个正确的"十"。这是本阶段的真成果。
- **右图暴露的是引导臂的局限，不是管线的错**：当前用的是 PyBullet 自带的 **KUKA（7-DOF 冗余臂）**，位置-only IK 会在相近目标间跳解，法兰乱摆。这是**已知、已记录、延后到换 Elfin5（6-DOF 非冗余）URDF 时解决**的问题——`src/brushbot/config.py` 改一行 `ARM_URDF` 即可换臂，其余代码不动。
- 一句话：**B1 的目标是"把开环写字这条链路端到端跑通 + 拿到开环基线"，不是追求写得好看**。链路已跑通（下方数据），好看留给 Elfin + B2 触觉闭环。

实测数据（`write(SHI_SEQ)`）：落笔点 `n_down = 196`；实际墨迹 x 跨度 **12.46 cm** vs y 跨度 **2.84 cm**（字本该 ~4cm 见方；x 被 IK 摆动拉宽，正是右图那条长线）。

---

## 2. 测试：18/18 全绿

`conda run -n brushbot pytest`

```
tests/test_calibration.py ..            [ 11%]   r→z 标定曲线(单调/溢出保护)
tests/test_controller.py ...            [ 27%]   开环控制器(弧长插值/终止/越界钳制)
tests/test_render.py ..                 [ 38%]   墨迹渲染(出图/无落笔点报错)
tests/test_run.py ..                    [ 50%]   运行循环 + FakeBackend
tests/test_scene.py ..                  [ 61%]   PyBullet 场景 + IK 到位
tests/test_sim_backend.py .             [ 66%]   SimBackend 跟踪命令位姿
tests/test_smoke.py .                   [ 72%]   包可导入
tests/test_strokeseq.py ..              [ 83%]   process() 笔序→路点
tests/test_types.py ..                  [ 94%]   State/Command 类型
tests/test_write_openloop.py .          [100%]   端到端开环写字集成测试

============================== 18 passed in 0.20s ==============================
```

---

## 3. 做出了什么（B0 + B1）

**三层解耦架构**（`docs/control-architecture.md`）：

```
① 纯算法层 (numpy, 零环境依赖)  →  ② 后端(可插拔)  →  ③ 运行循环(通用)
   controller / calligraphy         SimBackend(现在)      run.py
                                     HuayanBackend(实机, 待写)
```

| 模块 | 文件 | 作用 |
|---|---|---|
| 核心类型 | `types.py` | `State` / `Command`（6 元组位姿） |
| 后端 | `backends/{base,fake,sim}.py` | `RobotBackend` 协议 + 仿真/测试后端 |
| 运行循环 | `run.py` | `read→step→write`，两端通用 |
| 场景 | `scene.py` + `config.py` | PyBullet 机械臂 + 抽象书写平面 + IK/FK |
| 标定 | `calligraphy/calibration.py` | `func_brush`：笔宽 r → 笔高 z（端口自 CalliRewrite） |
| 笔序转换 | `calligraphy/strokeseq.py` | `process()`：`(p_t,x,y,r)` → 米制 `(x,y,z)` 路点 |
| 控制器 | `controller.py` | `OpenLoopController`：沿路点弧长匀速插值出目标位姿 |
| 渲染 | `calligraphy/render.py` | 笔尖轨迹 → 墨迹 PNG |
| 端到端 | `write_openloop.py` + `examples/strokes.py` | 开环写"十"字全流程 |

**为什么这套架构值**：① 算法层是纯 Python、与环境无关，将来上实机**只换 ② 后端**（写一个 `HuayanBackend` 调 `HRIF_PushServoP`），①③ 一行不改。终审已确认这个解耦是真的、可迁移。

---

## 4. 自己复现

```bash
conda run -n brushbot pip install -e .          # 首次
conda run -n brushbot pytest                     # 跑测试(18 passed)
conda run -n brushbot python -c "from brushbot.write_openloop import write; from brushbot.examples.strokes import SHI_SEQ; write(SHI_SEQ, gui=True)"   # 弹窗看机械臂写字
```

---

## 5. 已知限制 / 下一步

| 项 | 状态 |
|---|---|
| KUKA 冗余 IK 解支跳变 → 墨迹畸变 | 已知；换 Elfin5 6-DOF URDF（改 `config.ARM_URDF`）时收 |
| 视觉保真度 | 非 B1 目标；靠 Elfin + B2 触觉力控提按提升 |
| `config.IK_TOLERANCE_M` 去重、`run.py` 双读 | 小清理，留给硬件后端阶段 |
| **B2（下一步）** | 导纳外环 + 合成 `g_meas`，恒定形变→时变提按（仍纯仿真可做） |

> 更新（2026-07-31）：B2 已远超此处设想——Z 控制 Phase 0/1（前馈+PI、滤波进环、增益标定）已在裸态仿真完成，见 docs/handoff-z-phase1.md。
