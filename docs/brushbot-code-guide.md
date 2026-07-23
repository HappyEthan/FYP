# brushbot 代码详解

> 执行端（机械臂书法）的完整代码导览：每个文件干什么、为什么这么写、踩过哪些坑。
> 对应架构设计见 `docs/control-architecture.md`；上手运行见 `quick_start.md`。
> 生成 2026-07-21。当前状态：B0+B1（仿真开环写字）完成，33 个测试全绿，739 行。

---

## 0. 一句话

**给一个汉字，查出它每一笔的中线，转成机械臂的三维路点，让 Elfin5 在仿真里按笔顺一笔一划写出来，墨迹实时显示在纸上。**

全程**开环**——没有任何反馈修正（那是 B2 的事）。

---

## 1. 文件地图

```
src/brushbot/
├── config.py            21行  所有常量与"为什么是这个值"
├── types.py             11行  State / Command —— 层与层之间只传这两个
├── run.py                8行  ③ 通用运行循环 (read→step→write)
├── controller.py        34行  ① 开环控制器 (弧长匀速插值)
├── scene.py             62行  PyBullet 封装: 载臂/IK/关节/步进
├── backends/
│   ├── base.py           6行  RobotBackend 协议 (read/write)
│   ├── fake.py          13行  ② 假后端 (纯逻辑, 测试用)
│   └── sim.py           30行  ② 仿真后端 + ZeroTactile 占位触觉
├── calligraphy/
│   ├── hanzi.py         59行  真实字形 medians → 路点   ★主力
│   ├── strokeseq.py     25行  CalliRewrite 笔序 → 路点  (复现用)
│   ├── calibration.py   22行  func_brush: 笔宽 r → 笔高 z
│   ├── render.py        31行  离线渲染墨迹 PNG
│   └── inkcanvas.py     43行  实时墨迹画布 (刷进仿真贴图)
├── sim_visuals.py       91行  毛笔/纸/桌子/刷墨 (纯视觉道具)
├── write_hanzi.py       55行  入口A: 写任意汉字   ★主力
├── write_openloop.py    33行  入口B: 写手编笔序 (复现 CalliRewrite)
├── examples/strokes.py   6行  手编的"十"字笔序
└── assets/
    ├── elfin5/          Elfin5 URDF + STL (BSD-3, 见 NOTICE.md)
    └── paper.obj        带 UV 的四边形 = 仿真里的"纸"
scripts/watch_write.py  188行  交互式写字入口 (GUI/按键/重写)
```

**分层**（见 `control-architecture.md`）：

| 层 | 文件 | 特点 |
|---|---|---|
| ① 纯算法 | `controller.py`, `calligraphy/*` | **只依赖 numpy/PIL**，不 import pybullet，可脱离仿真单测 |
| ② 后端 | `backends/*`, `scene.py` | 唯一碰 pybullet 的地方，可插拔 |
| ③ 运行循环 | `run.py` | 8 行，两端通用 |

> 这个分层不是纸面口号：`controller.py` 和 `calligraphy/*` 里**一行 pybullet 都没有**，所以 `test_controller` / `test_hanzi` / `test_inkcanvas` 全是毫秒级纯逻辑测试。将来上实机只换 ②。

---

## 2. 主数据流（写一个"永"）

```
"永"
 │ hanzi.load_medians()          从 graphics.txt 查这个字
 ▼ medians = [[[x,y],…] × 5笔]   字体单位, +y 向上
 │ hanzi.medians_to_strokes()    等比缩放到 3.2cm, 包围盒居中到原点
 ▼ 局部笔画 (米)
 │ hanzi.strokes_to_waypoints()  ① 转 CHAR_YAW_DEG=-90 (字朝外)
 │                               ② 平移到 CHAR_ORIGIN=(0.45,0)
 │                               ③ 每笔: 抬笔趋近 → 落笔走完 → 抬笔
 ▼ 路点 [(x,y,z)] × 47           z 只有两档: z_down / z_up
 │ OpenLoopController.step()     d = speed×t, 折线上取该弧长处的点
 ▼ Command(x,y,z + FIXED_ORI)    每拍一个, 共约 1114 拍
 │ SimBackend.write()            全位姿 IK → 关节角 → POSITION_CONTROL → 步进6步
 ▼ Elfin5 运动
 │ SimBackend.read()             回读笔尖位姿
 ▼ trace
 │ z ≤ PAPER_Z+2mm ?             纯几何判据(不是物理接触)
 ▼ 落笔点 × 361 → InkCanvas(实时贴图) + render_trace(离线PNG)
```

---

## 3. 逐文件详解

### 3.1 `config.py` —— 常量与它们的来历

每个值背后都有一段故事，改之前先读注释：

| 常量 | 值 | 为什么 |
|---|---|---|
| `ARM_URDF` | `assets/elfin5/elfin5.urdf` | 真机同款。由官方 xacro 展开而来（去 include、求值 `${}`、mesh 路径改相对） |
| `EEF_LINK` | `9` | `elfin_dummy_gripper` = 工具 TCP。链条：6 个 revolute 在 idx 2–7，`end_link`=8，`tcp`=9 |
| `PAPER_Z` | `0.2` | 书写平面高度。**是个抽象数字，不是碰撞体**——仿真里没有物理纸 |
| `Z_TOUCH_REF` | `0.009` | CalliRewrite z 帧里"刚触纸"的参考值，用于把它的 z 映射到仿真 z |
| `FIXED_ORI` | `(π, 0, π/2)` | roll=180° → 工具 Z 朝下（笔杆垂直）。**yaw=90° 是被逼出来的**：yaw=0 会把 J1/J4/J6 顶死在 ±180°（余量 −3°），字的下半边根本走不了；yaw=±90° 余量 +37°。毛笔绕自身轴对称，yaw 本就是自由参数 |
| `CHAR_YAW_DEG` | `-90` | 字在纸上的朝向：让"上"朝远离底座的方向，否则从人的视角看字是躺倒的 |
| `CHAR_ORIGIN` | `(0.45, 0.0)` | 字心在纸面的位置，选在臂的舒适可达区 |
| `TICK_DT` | `1/240` | PyBullet 默认步长 |
| `JOINT_MAX_FORCE` | `2000` | **姿态受约束后 200 不够**：改回 200 会挂 5 个测试、套件从 2s 涨到 38s。仿真用值，非真机力矩规格 |

### 3.2 `types.py` —— 层间唯一的语言

```python
@dataclass
class State:   tcp_pose: tuple; g_meas: float; t: float
@dataclass
class Command: tcp_pose: tuple
```

`tcp_pose` 恒为 **6 元组** `(x, y, z, roll, pitch, yaw)`，位置米、姿态弧度。

`g_meas` 就是给 B2 留的**触觉提按分量**——现在恒为 0（`ZeroTactile`），但接口已经在了，B2 只需换数据源。

### 3.3 `run.py` —— 8 行的通用循环

```python
def run(backend, controller, on_tick=None):
    while not controller.done():
        st = backend.read()          # ← 命令前的状态
        cmd = controller.step(st)
        backend.write(cmd)
        if on_tick is not None:
            on_tick(backend.read())  # ← 写入后的状态(用来记轨迹)
```

**一拍两次 read 是有意的**，不是冗余：第一次给控制器（当前状态），第二次给 `on_tick`（执行后的实际位置，用于记录笔尖轨迹/画墨）。

### 3.4 `controller.py` —— 为什么它是"开环"

```python
def step(self, state) -> Command:
    d = self.speed * state.t      # ← 只用了时间
    ...
```

**只读 `state.t`，完全不看测到的位置**。笔尖实际在哪、写成什么样，都不影响下一条指令——这就是开环的准确定义。

插值机制：把路点折线的累计弧长算好（`np.cumsum`），每拍求 `d = speed×t` 处的点（`searchsorted` 定位段 + 线性插值）。

> 由此得出一个重要性质：**路点密度不影响运动平滑度**（控制器每拍都会插值），但**影响曲线几何保真度**（相邻点之间是直线段）。8 个点的"圆"就是八边形。

### 3.5 `scene.py` —— PyBullet 的唯一入口

四个要点：

**① 可动关节映射（这里曾有真 bug）**
```python
self.movable = [i for i in range(self.num_joints)
                if p.getJointInfo(self.robot, i)[2] != p.JOINT_FIXED]
...
def set_joints(self, q):
    for k, jidx in enumerate(self.movable):   # q[k] → 第 k 个"可动"关节
```
`calculateInverseKinematics` 返回的 `q` **只含可动关节**。早期代码写成 `q[i] → 关节 i`，在 KUKA 上碰巧成立（它没有固定关节），换到 Elfin（前面有 2 个 FIXED）就全错位——IK 值发到了错误的关节，误差 0.85m。

**② IK 可选姿态**：`ik(pos, ori_euler=None)`。传姿态就是全位姿 IK。

**③ 地面在 z=0，纸是抽象平面**：`plane.urdf` 放在 z=0 当地板。曾经把它放在 `PAPER_Z`，结果法兰（`EEF_LINK` 的 link 原点比实际接触面高 3–5cm）撞在平面上下不去，落笔点恒为 0、写不出字。

**④ 力矩用 `config.JOINT_MAX_FORCE`**，不是魔法数字。

### 3.6 `backends/` —— 可插拔的 ②

- **`base.py`**：`RobotBackend` 协议，只有 `read() -> State` 和 `write(cmd)`。结构化鸭子类型，不用继承。
- **`fake.py`**：`FakeBackend` 把命令位姿原样回显、时间按 `dt` 累加。**让运行循环和控制器可以完全脱离 pybullet 单测**。
- **`sim.py`**：
  ```python
  def write(self, cmd):
      pos, ori = cmd.tcp_pose[:3], cmd.tcp_pose[3:6]
      q = self.scene.ik(pos, ori)        # 全位姿 IK: 笔杆必须垂直
      self.scene.set_joints(q)
      for _ in range(self.substeps): self.scene.step()
      self._t += self.substeps * config.TICK_DT
  ```
  曾经这里只用 `ik(pos)`（位置-only），姿态被静默丢弃，法兰 pitch≈−88° 还会解支突跳——挂上毛笔会乱转。

  `ZeroTactile.value()` 恒返回 0，是 B2 的占位。

### 3.7 `calligraphy/hanzi.py` —— 主力轨迹来源

三个纯函数：

```python
load_medians(character, graphics_path)     # graphics.txt 里查这个字 → 每笔中线点列
medians_to_strokes(medians, size=0.032)    # 等比缩放(长边=size) + 包围盒居中
strokes_to_waypoints(strokes, origin, z_down, z_up, char_yaw_deg=0)
```

`strokes_to_waypoints` 做三件事：**按 `char_yaw_deg` 旋转** → **平移到 origin** → **每笔加抬笔趋近/收尾**：

```python
for stroke in strokes:
    wp.append((*place(*stroke[0]), z_up))      # 抬笔到起点上方
    for point in stroke:
        wp.append((*place(*point), z_down))    # 落笔走完这一笔
    wp.append((*place(*stroke[-1]), z_up))     # 抬笔
```

> **关键认知**：medians 只给"笔往哪走"（xy 路径），**不含笔宽/力度**。所以现在写出来是等宽硬笔字。`StrokePlan` 的另一半（提按曲线）只能来自触觉示范——这正是整个项目要解决的。

### 3.8 `calligraphy/calibration.py` —— r → z

`func_brush(r)` 是从 CalliRewrite 逐字端口过来的**4 段分段线性**曲线，斜率全为负（**笔画越宽 → 压得越深**），带溢出保护。

`piecewise_linear` 是通用版，**目前没被调用**，留给以后自己标定用。

### 3.9 `calligraphy/strokeseq.py` —— CalliRewrite 复现路径

`process(seq, r2z, alpha, beta)` 把 `(p_t, x, y, r)` 笔序转成米制 `(x,y,z)`：`z = func_brush(r×alpha×beta)`，并手工加了楷书入锋、末尾抬笔。

一处非显然的地方：末尾 5 个抬笔点被 `if has_new_stroke and xs:` 门控——因为计划里的测试要求"纯延续输入返回 1 个点"，与"无条件追加"自相矛盾。对真实输入（必以 `p_t=1` 起笔）行为完全相同。注释里写明了**别改回无条件**。

### 3.10 `calligraphy/render.py` vs `inkcanvas.py` —— 两种出图

| | `render_trace` | `InkCanvas` |
|---|---|---|
| 时机 | 运动**结束后**离线出 PNG | **边写边**刷进仿真贴图 |
| 用途 | 存档、评估 | 让你在窗口里看到墨迹浮现 |
| 落笔判据 | `z ≤ surface_z + 2mm` | 同左 |
| 坐标 | 世界 xy → 像素（y 翻转） | 世界 xy → 贴图 uv（y 翻转） |

`InkCanvas` 是纯逻辑（PIL），所以 `world_to_px` / `stroke` / `clear` 全部可单测。

### 3.11 `sim_visuals.py` —— 让你看得见（纯视觉，mass=0 无碰撞）

四个道具 + 一个刷新：

```python
add_brush(cid)        # 笔毫+笔杆两段圆柱; 笔尖在 link 原点, 沿工具 -Z 向上
follow_tcp(...)       # 每拍把笔的位姿设成末端 link 位姿
add_table(canvas,cid) # 桌子, 免得纸浮空
add_paper(canvas,cid) # ★用 assets/paper.obj (带 UV 的网格)
push_ink(canvas, paper_id, cid)   # 落盘 → loadTexture → changeVisualShape
```

**这里藏着两个 PyBullet 陷阱**（我是用 `getCameraImage` 渲染画面才看出来的）：

1. **`createVisualShape(GEOM_BOX)` 没有 UV 坐标，根本贴不上图** —— `loadTexture` 和 `changeTexture` 都静默无效，纸永远白的。必须用**带 UV 的网格**（所以有 `paper.obj`）。
2. **`changeTexture` 不刷新表面**；而 **`loadTexture` 按文件名缓存** —— 复用同名文件会拿到旧图。所以 `push_ink` 每次写**唯一文件名**。

### 3.12 两个写字入口

| | `write_hanzi.py` ★ | `write_openloop.py` |
|---|---|---|
| 轨迹来源 | 真实字形 medians（9574 字） | 手编笔序 `SHI_SEQ`（"十"） |
| 定位 | 主力 | 复现 CalliRewrite 的开环基线 |
| z | 恒定 `zc_down` | `func_brush(r)` 逐点算 |

两者结构一样：建场景 → **用全位姿 IK 在起点停稳** → 跑 `run()` → 渲染。

> "起点停稳"不是可选项：姿态受约束后，从零位直接起步会因姿态突变把臂甩飞。

### 3.13 `scripts/watch_write.py` —— 交互入口（薄封装）

188 行里没有控制逻辑，全是编排：建道具、放慢、刷墨、按键。

- `VIEWS`：4 个预设视角，**yaw=270** 让底座落在画面下方（yaw=0 会把它甩到左边）
- `park(scene)`：写完把笔抬到**侧上方**——往底座方向退会正好挡住相机（相机就在底座那侧）
- 交互：`r` 重写 / `c` 清纸 / `n` 换字 / `1-4` 视角 / `q` 退出

---

## 4. 测试地图（33 个）

| 测试文件 | 数量 | 测什么 | 需要 pybullet? |
|---|---|---|---|
| `test_types` | 2 | 数据类字段/6元组 | ❌ |
| `test_run` | 2 | FakeBackend 回显 + 循环记录 | ❌ |
| `test_controller` | 3 | 弧长插值/终止/越界钳制 | ❌ |
| `test_calibration` | 2 | r→z 单调性/溢出保护 | ❌ |
| `test_hanzi` | 6 | 查字/缩放居中/抬落笔结构/**字旋转** | ❌ |
| `test_inkcanvas` | 5 | 世界→像素/画墨/清空/字节长度 | ❌ |
| `test_render` | 2 | 出图/无落笔点报错 | ❌ |
| `test_scene` | 3 | 载入/IK到位/**多场景不串扰** | ✅ |
| `test_sim_backend` | 2 | 位置跟踪/**姿态保持垂直** | ✅ |
| `test_write_openloop` | 1 | 端到端写"十" | ✅ |
| `test_write_hanzi` | 2 | 端到端写"永"/字不存在报错 | ✅（缺数据集自动 skip） |

**24/33 是纯逻辑测试**，毫秒级——这是分层的直接收益。

---

## 5. 踩过的坑（最值钱的部分）

| # | 坑 | 症状 | 真因 |
|---|---|---|---|
| 1 | IK 关节映射 | 误差 0.85m，字写一半 | `q[k]` 对应第 k 个**可动**关节，不是关节索引 k。KUKA 无固定关节碰巧掩盖 |
| 2 | 假的可达性验证 | 探测说"IK 完美 err=0"，实跑却走不到 | `resetJointState` **无视关节限位**；电机控制不会 |
| 3 | `FIXED_ORI` 的 yaw | 字只写出上半边 | yaw=0 把 J1/J4/J6 顶死在 ±180°（余量 −3°）。改 90° 得 +37° |
| 4 | 力矩不足 | 5 个测试挂，套件 2s→38s | 姿态受约束后 200 不够，2000 才跟得上 |
| 5 | 起步姿态突变 | 笔尖飞到 ±0.9m | 起点停稳必须用**同样的全位姿 IK** |
| 6 | 纸是碰撞体 | 落笔点恒为 0 | 平面放在 `PAPER_Z` 挡住法兰。纸应是抽象 z 平面，地面放 z=0 |
| 7 | 盒子贴不了图 | 纸永远空白 | `GEOM_BOX` 无 UV，必须用网格 |
| 8 | 贴图不刷新 | 墨迹不出现 | `changeTexture` 无效；`loadTexture` 按**文件名缓存** |
| 9 | 相机方位 | 底座在字左边、字躺倒 | yaw 决定底座在画面哪侧；字还需转 −90° 才正 |
| 10 | 停靠位置 | 默认视角被挡死 | 往底座方向退 = 退到相机跟前 |

> 共同教训：**pybullet 里"看起来对"和"真的对"经常不是一回事**。多次靠 `getCameraImage` 渲染画面 / 实测数值才定位到真因，光读代码看不出来。

---

## 6. 我想改 X，该动哪里？

| 想做什么 | 改哪 |
|---|---|
| 写别的字 | 命令行参数即可，无需改码 |
| 换机械臂 | `config.ARM_URDF` / `EEF_LINK` / `FIXED_ORI`（新臂要重新确认 yaw 的关节余量） |
| 字更大/更小 | `write_hanzi(size=...)` 或 `watch_write` 的 `size` |
| 笔画更粗 | `zc_down` 调小（压更深）。注意**要与字号相称**——直接照 `func_brush` 的真实毛笔半径给会糊成一团 |
| 运笔更慢 | `speed`（米/秒） |
| 墨迹更清晰 | `InkCanvas(resolution=...)`、`INK_WIDTH` |
| 刷新更跟手 | `REFRESH_EVERY` 调小（代价：更多落盘） |
| **加提按（B2）** | ① `ZeroTactile` → 合成/真实 `g_meas` ② 新增 `AdmittanceController`（前馈 `z_ff(g_d)` + 低增益反馈）③ `InkCanvas.stroke` 的 `width_m` 按压深变化 |
| 上实机 | 只写一个 `HuayanBackend`（`HRIF_ReadActTcpPos` 读 / `HRIF_PushServoP` 写），①③ 不动 |

---

## 7. 现在还没有的

- ❌ **提按**：笔画等宽。字形数据只给"笔往哪走"，不给"按多重"
- ❌ **任何反馈**：不测力、不测形变、不看写成什么样
- ❌ **物理接触**：纸不是碰撞体，落笔是几何判据
- ❌ **笔锋姿态**：笔杆恒垂直，无中锋/侧锋
- ❌ **运笔节奏**：全程匀速

这些正是 **B2（触觉力控提按）** 与后续的工作内容，也是项目"闭环 vs 开环"核心对比实验的另一半。
