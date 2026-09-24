---
project: 06-mujoco-simulation-platform
status: archived
---

# 触觉 FEM 仿真 · 触角形变 + 同步 ΔB 信号（落地方案）

> 历史方案评估：SOFA FEM 路线未落地；当前保留的仿真实现是 MuJoCo 接触与解析梁磁学。本文件不作为现行实现说明。

> **结果（事后注，2026-07-31）**：实际落地走的是本文 §5 的回退路线（MuJoCo + 解析梁，见 src/brushbot/tactile/ 与 docs/06-mujoco-simulation-platform/simulation.md），完整 SOFA FEM 路线未采纳。本文保留作方案评估记录。

> **目标（边界明确）**：一个**纯仿真演示**——触角在 FEM 里被压/拖而**弯曲**，同时**模拟的三轴 ΔB 信号同步变化**并可视化。**不牵扯控制环、不追求与真机数值一致。**
> 定位：给"物理地生成合成触觉信号"这个方向打样；产物可作 B2 的合成 ΔB 源雏形、也直接支撑 ΔB 标定研究。
> 关联：`docs/04-robot-control/archive/z-control-design.md`（现保留的前馈表＋PI 简明设计）、种子论文 E-Antenna。早期向量投影讨论已移除。
> 生成 2026-07-21。**诚实性见 §6。**

---

## 0. 一句话与验收

**做出**：一个窗口里看到触角软体在弯，旁边一条 `Bx,By,Bz`（或 ΔB）实时曲线跟着动；改变加载（压深/拖向）→ 形变和 ΔB 都随之变。

**验收**：压入 → ΔB 单调变化且可复现；改变加载方向 → ΔB 的方向结构随之改变；能复现你实测的"下压时 Bx,By 变、Bz 近乎不动"（靠调触角的屈曲方向/磁化布置）。

> ⚠️ 对纯演示而言 SOFA 其实偏重——但你想用真 FEM、机器也带得动（Ryzen 9 + RTX 4060），就上。**关键：把架构分层，让"磁学+可视化"这半段与形变引擎解耦**，SOFA 装不动时可无缝换 MuJoCo-flex 或解析梁。

---

## 1. 架构（引擎无关的三层）

```
[① 形变引擎]            [② 磁学(自研核心)]            [③ 可视化]
SOFA FEM 触角     ──►  取形变中线 N 个节点     ──►  3D: 看触角弯
(或 MuJoCo/解析梁)      → 沿中线布磁偶极子链          曲线: Bx,By,Bz 实时
每步给出节点位置        → magpylib 算传感器处 B
                        → ΔB = B − B0
```

**关键认识（再强调）**：**没有任何仿真软件算②**。SOFA 只算①机械形变；`ΔB = f(形变)` 永远是你自己的代码。所以换不换 SOFA 只影响①，②③照旧。

---

## 2. ② 磁学模型（这半段是核心，也是自研点）

**表示**：把触角磁化段离散成沿中线的 `N` 个**点磁偶极子**（种子论文是"部分磁化+分段柔性"，可只在磁化段放偶极子）。
- 每个偶极子矩 `m_i`：若轴向均匀磁化，`m_i` 沿该点**局部切线**方向，模长 `m0`。
- 触角弯曲 → 中线弯 → 各 `m_i` 的**位置和朝向都变** → 传感器处 B 变。

**传感器**：MLX90393 固定在某处（如笔杆顶端/触角根部），只是一个观测点。

**计算**：用 [`magpylib`](https://magpylib.readthedocs.io)（`pip install magpylib`）——它能从一组磁体/偶极子（`magpylib.misc.Dipole`）算任意观测点的 `B`。或手写偶极子场公式 `B(r)=μ0/4π·[3(m·r̂)r̂−m]/|r|³` 叠加。
- 静止直立 → `B0`；形变 → `B`；`ΔB = B − B0`。

**复现你的实测现象（"压→Bx,By 变，Bz 不动"）**：
- 若传感器在触角轴线上、触角笔直轴向磁化 → 静态 B 沿轴(z)；**纯轴向压缩几乎不动偶极子横向位置 → Bz 变化小**。
- 你观察到 Bx,By 变 → 说明**轴向压导致侧向屈曲**（触角细长、载荷略偏心）。**FEM 里给触角一点预弯/偏心载荷，屈曲会自然涌现**，偶极子横移 → Bx,By 变。**这正是 SOFA 比解析模型强的地方**：屈曲是涌现的，不用手工规定。
- ⚠️ 但这也意味着**提按和拖拽都落在 XY 面**——正是最难解耦的情形。**这个 demo 恰好能用来研究"两者到底能不能分开"**（对应 `deltaB-control.md` 的投影法前提与 E4 判据）。

---

## 3. SOFA 落地要点

### 3.1 安装（有坑，按此走）
- **首选二进制发布**：从 [sofa-framework releases](https://github.com/sofa-framework/sofa/releases) 下含 **SofaPython3** 的 Linux 包，设 `SOFA_ROOT` 与 `PYTHONPATH`（[官方安装文档](https://sofapython3.readthedocs.io/en/latest/content/Installation.html)）。
- ⚠️ **Python 版本必须与二进制匹配**：**2024 版用 Python 3.12**（`sudo apt install python3.12-dev pybind11-dev` + numpy/scipy）。**和你 brushbot 的 3.10 conda 环境不同 → 单开一个 py3.12 环境专给 SOFA 用**（本 demo 独立，不进 brushbot 控制环，互不影响）。
- 备选：源码编译（重，几十分钟~小时级，能自选 Python 版本）；或找旧版二进制匹配 3.10。
- **P1 先只验证**：`runSofa` 能开、`import Sofa` 在 py3.12 里成功、跑通官方一个 beam/软体样例——**装不通就立刻走 §5 回退，别硬耗**。

### 3.2 触角力学建模
- **首选梁模型**：`BeamFEMForceField`（一串 beam 单元）——细杆最自然，**节点即中线**，直接喂②，快、稳。
- 备选体网格：细圆柱 tetra + `TetrahedronFEMForceField`（更真，取中线需额外处理）。
- 材料：种子论文 DragonSkin 20 + Ecoflex（软硅胶），杨氏模量 ~百 kPa 量级；**参数先粗调到"看起来像"，本 demo 不追数值精确**。
- 加载方式（驱动形变）：① 尖端加力/加位移；② 与一个平面接触（模拟压纸）；③ 侧向拖（模拟拖笔）。演示用②③最贴题。

### 3.3 每步耦合（SOFA 控制器）
用 `Sofa.Core.Controller` 的 `onAnimateEndEvent`：每仿真步读节点位置数组 → 构建偶极子链 → magpylib 算 B → 存/画 ΔB。

### 3.4 可视化
- **3D 形变**：SOFA 自带 GL 视图（`runSofa`）直接看。
- **ΔB 曲线**：两种做法——(a) 控制器里把 ΔB 推给一个 `matplotlib` 动画/滚动曲线（另一线程/进程，避免和 SOFA 主循环抢）；(b) 先跑一段、录 ΔB(t)，再回放形变视频 + 同步曲线（最稳，先做这个）。

---

## 4. 分阶段计划（每阶段可独立验收）

| 阶段 | 做什么 | 验收 |
|---|---|---|
| **P0 磁学半段先行**（不依赖 SOFA） | 纯 Python：给定一条"中线折线"→偶极子链→magpylib→B。手工把中线从直摆到弯，看 ΔB 变 | 直→弯，ΔB 单调变；能调出"横移→Bx,By 变、Bz 稳" |
| **P1 SOFA 装通** | 装 py3.12+SofaPython3，跑通官方梁/软体样例 | `import Sofa` OK、样例能动。**装不通→§5 回退** |
| **P2 触角形变** | 建触角梁模型，尖端加力/接触 → 弯 | GL 里看到合理弯曲，节点位置可读出 |
| **P3 耦合** | P1 的 SOFA 每步 → P0 的磁学 → ΔB | 压得越深 ΔB 越大且可复现 |
| **P4 同步可视化** | 形变 3D + ΔB 曲线同步显示 | 一眼看到"弯的同时 ΔB 在变" ← **主目标达成** |
| **P5（可选）压 vs 拖对比** | 分别做纯压入、纯横拖，比 ΔB 方向结构 | 定量看两者在磁空间的可分性（喂 E4/解耦研究） |

> **建议顺序 P0 先做**：磁学半段是核心且与 SOFA 无关，先用纯 Python 拿到"形变→ΔB"的可信映射，SOFA 只是后面给它喂更真的形变。这样即便 SOFA 卡住，你也已经有能演示的东西。

---

## 5. 风险与回退

| 风险 | 回退 |
|---|---|
| **SOFA/SofaPython3 装不通**（版本/依赖折腾） | ①换 **MuJoCo `flex`/composite**（pip 装、py3.10 即可、接触涌现）；②或**解析悬臂梁**（纯 numpy，当天出）。**②③磁学+可视化半段原样复用**，只换形变来源 |
| 内存 15GB 偏紧 | 细杆网格别太密；别多开重仿真 |
| SOFA 主循环与 matplotlib 抢线程 | 先用"录制→回放+曲线"（P4 的稳妥做法），实时曲线作进阶 |
| 磁参数/材料是猜的 | 本 demo 只求定性；数值真值等真机 E2 |

---

## 6. 诚实性：这个 demo 证明什么、不证明什么

- ✅ **证明**：一条"形变→ΔB"的**自洽物理管线**能跑；能定性展示提按/拖拽在磁空间的不同结构；可当 B2 合成 ΔB 源、可在仿真里预研 ΔB 标定与解耦。
- ❌ **不证明**：真实触角的 ΔB 数值、**带宽、迟滞、磁漂移**——这些是**硬件的事，任何仿真都替代不了**（E0–E4 的存在理由）。合成 ΔB 的结构对不对，最终仍要真机比对。
- 一句话：**它是"物理接地的合成信号发生器"，不是真机替身。** 用来开发/演示/预研，不用来下结论。

---

## 7. 环境与依赖

- **SOFA 环境**（独立）：Python **3.12** + SofaPython3(随 SOFA 二进制) + `numpy scipy magpylib matplotlib`。
- **回退环境**：brushbot 的 py3.10 + `mujoco`（或纯 numpy）+ `magpylib matplotlib`。
- 机器：Ryzen 9 7845HX / 15GB / RTX4060——**跑小软体 FEM 绰绰有余**（GPU 用不到，SOFA 走 CPU）。

## 参考
- SofaPython3 安装：https://sofapython3.readthedocs.io/en/latest/content/Installation.html
- SOFA releases：https://github.com/sofa-framework/sofa/releases
- magpylib（永磁体/偶极子磁场计算）：https://magpylib.readthedocs.io
- 种子论文 E-Antenna（部分磁化+分段柔性、MLX90393）：`reference/` 内 PDF
- `docs/04-robot-control/archive/z-control-design.md`（现保留的前馈表＋PI 简明设计；旧投影解耦及 E0–E4 讨论已移除）
