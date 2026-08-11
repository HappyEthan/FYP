# 触觉仿真 · 合并手册

> 触觉仿真模块：无触角实体时，用"形变引擎 + 自研磁学半段"合成触角 ΔB 信号并可视化，供 B2 闭环预研、E4 可分性判据与演示。代码在 `src/brushbot/tactile/`（`antenna_model.py` 解析梁磁学、`contact_sim.py` 单触角接触、`mj_write.py` 全臂 MuJoCo、`writing_tactile.py` 写字合成 ΔB、`separability.py` 压/拖可分性）与 `scripts/watch_write_tactile.py`。过程细节见 `docs/archive/` 与 git 历史。

---

## 做了什么

统一架构三层，磁学半段与形变引擎解耦：

```
[① 形变引擎: MuJoCo / 解析梁] → [② 磁学(自研)] → [③ 可视化: 3D + ΔB 曲线]
```

② 的模型假设：触角磁化段离散成沿中线的点磁偶极子链（矩沿局部切线；部分磁化，取中线 0.4–1.0 远端段），固定传感器（默认触角根部上方）处叠加偶极子场，`ΔB = B − B0`。实现在 `antenna_model.sensor_B`，引擎无关，**输出为任意单位（省略 μ0/4π）**。原方案是 SOFA FEM（`docs/tactile-fem-sim.md` 保留作方案评估记录），实际按其 §5 回退路线落地为两条：

**路线 1 · MuJoCo 柔性体/接触** —— 形变是接触力"撞出来"的（涌现，不手掰）：

- `contact_sim.py`：单触角 = 铰链串接的离散弹性杆（10 段共 24mm、18° 安装倾角），滑座压向地面 → 接触顶弯 → 每步读中线喂 `sensor_B`。定位：验证"接触涌现形变 → ΔB"整条链路，也是压深-ΔB 曲线的标定演示。
- `mj_write.py`：完整场景 = Elfin5 六轴（URDF）+ 法兰端面挂 8 段触角（24mm、默认 12° 倾角）+ 纸 + 桌，碰撞组只让触角↔纸相碰。混合驱动：臂每子步 `qpos` 硬置回 IK 解（雅可比 DLS，独立 scratch MjData 暖启动，残差 ~1e-4 m），触角自由 `mj_step` 真接触真弯。定位：写字可视化 + 触角物理接触；`watch/write/ik` 可用，`contact` 模式（接触→ΔB）WIP 不可信（见结论）。

**路线 2 · 解析梁** —— 形变解析给定（悬臂梁圆弧弯：尖端转角 + 面内方位角），纯 numpy，快：

- `antenna_model.py`：中线生成 + 磁学半段本体。定位：P0 结构验证——弯 → 面内 Bx,By 变、轴向 Bz 近乎平。
- `writing_tactile.py`：PyBullet 开环写字轨迹逐拍映射为形变——压深→法向弯（固定屈曲方位 40°、7°/mm 穿透），横向位移→拖拽弯（反运动方向），穿透 >0.5mm 才算接触——合成 ΔB。定位：由真实书写运动驱动的"合成 g_meas 源"（B2 输入雏形）。
- `separability.py`：分别下纯压/纯拖指令（小形变线性叠加），量化两者 ΔB 方向夹角 θ 与投影法泄漏。定位：喂 E4 判据。
- `scripts/watch_write_tactile.py`：PyBullet GUI 写字 + 笔尖实时画弯触角 + matplotlib 滚动 ΔB 曲线。

## 怎么用

先 `conda activate brushbot`（或把 `python` 换成 `conda run -n brushbot python`）。`mj_write`/写字类入口需在仓库根目录跑（URDF 相对路径），且需字形数据（已 gitignore）：

```
mkdir -p data/makemeahanzi && curl -fsSL https://raw.githubusercontent.com/skishore/makemeahanzi/master/graphics.txt -o data/makemeahanzi/graphics.txt
```

| 入口 | 命令 | 说明 |
|---|---|---|
| 解析梁 P0 静图 | `python -m brushbot.tactile.antenna_model p0.png` | 形变→ΔB 结构（面内变、轴向平） |
| 解析梁动画 | `python -m brushbot.tactile.antenna_model anim antenna.gif` | 提按脉动 + 拖拽转圈 + (Bx,By) 轨迹 |
| 接触仿真实时 | `python -m brushbot.tactile.contact_sim watch` | 需显示器；循环下压→回弹，控制台打 ΔB |
| 接触仿真标定图 | `python -m brushbot.tactile.contact_sim contact.png` | 逐级压弯（0→21mm）+ ΔB-压深曲线 |
| 写字合成 ΔB | `python -m brushbot.tactile.writing_tactile 永 writing_tactile.png` | 墨迹 + 书写中 ΔB 时序（落笔区间着色） |
| 可分性 CLI | `python -m brushbot.tactile.separability sep.png` | 出图 + 打印 E4 判据阈值 |
| 全臂实时窗口 | `python -m brushbot.tactile.mj_write watch 永 書 王` | 需显示器；多字用 `n` 切换 |
| 全臂轨迹静图 | `python -m brushbot.tactile.mj_write write 永 out.png` | 无窗口 |
| 全臂自检 | `python -m brushbot.tactile.mj_write ik` | 模型 + IK，几秒，无需显示器 |
| 全臂接触→ΔB ⚠️ | `python -m brushbot.tactile.mj_write contact 永 out.png` | **WIP，ΔB 输出不可信** |
| PyBullet GUI | `python scripts/watch_write_tactile.py 永` | 需显示器；末尾加 `nogui` 只验证逻辑 |

`mj_write watch` 窗口键位：`r` 重写、`c` 清墨、`n` 下一字、`1`–`4` 视角（俯/斜/侧/全景）、空格暂停、`+`/`-` 调播放速度、`q` 退出；鼠标左拖转视角、右拖平移、滚轮缩放。

常见排错：没弹窗 = 无图形界面，改用 `write`/`ik`；`ParseXML ... elfin5.urdf` = 不在仓库根目录；`FileNotFoundError: graphics.txt` = 没下字形数据；`KeyError: '某字'` = 不在 9574 字集内。

## 结论（可信 / 不可信边界）

**可信（结构与趋势层面）**：

- 触角弯曲本身物理真实：MuJoCo 接触求解，臂与纸/桌全轨迹零相交，尖端贴纸微弯逐点验证过。
- "形变 → ΔB 的方向结构"可用：弯曲主要改面内 Bx,By、轴向 Bz 近乎不动，与真机实测现象定性一致；压深增大 → ΔB 单调增且可复现。
- 可分性判据可用：投影法把提按从拖拽污染中分出，需两者 ΔB 夹角 θ≥85° 才能 <10% 误差；θ 小则泄漏 ∝cosθ，噪声进一步抬底——这是喂给 E4 的定量前提。
- MuJoCo 调参结论可用：加压量只增穿透（≈0.8×压量）不增弯，弯角由铰链刚度决定（越软越弯、代价是甩动与穿透）；安装倾角为零会变成纯轴向戳、不弯。

**不可信（数值层面）**：

- 全部 ΔB 绝对数值：任意单位、磁化强度/刚度等参数是调的，不是真机数值。带宽、迟滞、磁漂移任何仿真都给不出。真值等真机 E2 标定。
- `mj_write contact` 模式的动态 ΔB：连续写字时某些拍触角中线换到传感器系错乱 → 偶极子 1/r³ 发散 → ΔB 爆到 10^9%，未根治（静态落笔那步是对的）。
- 一句话：这是"物理接地的合成信号发生器"，用来开发/演示/预研，**不用来下数值结论**。

## 已知局限（2026-08-10 审计，详见 `docs/review-2026-08-10.md` R8）

1. **`mj_write.py` 接触 ΔB 数值发散不可信**（其模块 docstring 自承 Phase 3 WIP）：只看"接触有无/趋势"，勿引用任何数值。
2. **无统一"模型单位 → µT"标定入口**：`antenna_model` 输出任意单位（省略 μ0/4π），全仓换算三处各自为政——`scripts/demo_z_control.py` 用"噪声=峰值 2%"的相对量、monitor 的 `synth_writing_B` 硬缩放到 400µT、UDP 桥 spec 用 `DEFAULT_SCALE`。混入真实 µT 数据会静默量纲错配。
3. **tactile/ 与 z_control 是平行世界**：Phase 1 闭环结论（9.47% 等）用的是手编线性标定表，与 MuJoCo/解析梁完全无关；两者唯一连线是 `scripts/demo_z_control.py`，且该脚本仍是 Phase 0 无滤波版本、量纲口径存疑。
4. 提按未闭环：`mj_write` 里笔画仍等宽，压深→笔画变粗要靠触觉闭环（B2 核心命题），仿真里未实现。
5. SOFA FEM 路线未采纳（安装/版本成本高于收益），屈曲"涌现"由 MuJoCo 接触替代；`docs/tactile-fem-sim.md` 仅存档作方案评估。
