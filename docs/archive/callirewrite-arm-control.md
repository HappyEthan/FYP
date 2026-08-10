# CalliRewrite 开环写字 · 技术细节拆解

> 目的：搞清 CalliRewrite（ICRA 2024）**怎么把一串轨迹真正写到纸上**，作为本项目 **B1（复现 = 开环基线）** 的蓝本。
> 依据：`reference/CalliRewrite/` 源码（`callibrate/`）+ `reference/2024_CalliRewrite_精读.md` + 论文 2405.15776。
> 一句话：**纯开环、点到点（PTP）位置控制；"笔画粗细"完全靠"笔压到多低（z 高度）"来凑，z 由一条 `r→z` 标定曲线决定——没有任何力觉/反馈。**
> 生成 2026-07-13。

---

## 0. 硬件与定位

- **机械臂**：4 自由度 **Dobot Magician**，桌面级，**开环**（无力/力矩反馈）。
- **写字工具**：中文用真毛笔；英文/其它用秀丽笔(fude)、平头马克笔。
- **字号**：控制点 x,y ∈ [0,1] 代表"占字宽的比例"，乘 `alpha` 得实际米数（notebook 例 `alpha=0.04` → 4cm 字；论文中文写"千字文"前 24 字约 8×8cm）。
- **本质**：复现的是**外观（笔画宽度的视觉表现）**，不是**提按力度**。这正是本项目要用触觉力控超越的点。

---

## 1. 完整数据流

```
字图 I
  │  阶段一 CNN+LSTM(无监督)  →  阶段二 SAC(RL 工具微调)          [ML, 与臂控制无关]
  ▼
RL 状态序列  data[i] = (p_t, x, y, r)          # p_t 落/抬笔, (x,y) 归一化坐标, r 归一化笔宽
  │  ← load_data_try.process(data, func, alpha, beta)
  │     核心: z = func(r)  (笔宽 → 笔高) ; x,y 乘 alpha ; 起笔/回锋手工逻辑
  ▼
控制点  (x, y, z)  存成 .npz (pos_3d_x / pos_3d_y / pos_3d_z)     # 单位: 米
  │  ← RoboControl.Control(npz_path)   【★该文件未开源，见 §5】
  ▼
Dobot:  逐点 SetPTPCmd(api, PTPMOVLXYZMode, x, y, z, rHead)        # 直线插补, 队列执行, 单位 mm
        开环 · 无反馈 · 无力觉
```

三个真正干活的环节：**① r→z 标定**（建映射）、**② process()**（序列→控制点）、**③ Control()→SetPTPCmd**（下发）。逐个拆。

---

## 2. 环节①：`r→z` 标定（sim2real 桥梁，作者称"最关键"）

代码：`callibrate/callibrate.ipynb`。目的：量出"想要多宽的笔画 → 笔该压到多低"。

**步骤**
1. **手动测量** z 行程两端：`max_z`=笔尖刚触纸的高度，`min_z`=用力压到极限的高度。
   - 毛笔例：`max_z=0.01 m, min_z=-0.006 m`，取 `its=17` 档。
   - 秀丽笔例：`max_z=0.04602, min_z=0.04425`，`its=8` 档。
2. **`generate_npz(zs, max_z, savedir)`**：在每个 z 档画一条**水平横线**（起点抬高 `max_z+0.03` 悬空 → 左端点下降到 `zs[i]` → 右端点保持 `zs[i]` 画出线 → 抬笔）。得到一排不同压深的横线。
3. 机械臂把这些横线**实际画在纸上**（`Control(test.npz)`）。
4. **尺子量**每条线的平均宽度 `widths` → 半径 `rs = widths/2`。
5. **拟合**：把 `(rs, zs)` 散点用**分段线性**拟合（`scipy.optimize.curve_fit`）：
   - 秀丽笔用 `piecewise_linear3`（3 段），毛笔用 `piecewise_linear4`（4 段）。
6. 得到标定函数 `func_brush(r)` / `func_fude(r)`——分段线性、带**溢出保护**（超范围返回极限 z）。

**实测拟合结果（可直接看的技术细节）**
```python
def func_brush(radii):                     # 毛笔, 4 段
    if   0 <= radii <= 7.72667536e-04: z = -5.9701493 *(radii-7.72667536e-04)+4.34974603e-03
    elif radii <= 1.78125854e-03:      z = -1.538473  *(radii-7.72667536e-04)+4.34974603e-03
    elif radii <= 2.45866277e-03:      z = -6.028019  *(radii-1.78125854e-03)+2.79805600e-03
    elif radii <  0.0045:              z = -2.37843574*(radii-2.45866277e-03)-1.28534957e-03
    else: return -0.006                    # 溢出保护(压到极限)

def func_fude(radii):                      # 秀丽笔, 3 段
    if   0 <= radii <= 0.00026555923:  z = -3.06968833*(radii-0.00026555923)+0.0453094035
    elif radii <= 0.000553636283:      z = -1.444032  *(radii-0.00026555923)+0.0453094035
    elif radii <= 0.00071875:          z = -3.66324702*(radii-0.000553636283)+0.044893411
    else: return 0.04425                   # 溢出保护
```
> 斜率全为负：**r 越大（笔画越宽）→ z 越小（压得越深）**。这就是"位置控宽度"的数学核心。作者强调**每支笔、每张纸都要重标**。

---

## 3. 环节②：`process()` —— 序列转控制点

代码：`callibrate/load_data_try.py`。输入 `data[i]=(p_t, x, y, r)`，输出三条列表 `record_x/y/z`。

**逐点核心逻辑**
```python
x_, y_ = x*alpha, y*alpha        # 归一化坐标 → 米 (alpha=字号, 如 0.04)
r_     = r*alpha*beta            # 归一化笔宽 → 米 (beta 调粗细对比度)
h = func(r_) * 100 ; h -= 0.09 ; h /= 100   # z=func(r), 再做一点微调(经验偏置)
```

**两类点**
- `p_t == 0`（延续笔）：直接把 `(x_, y_, h)` 追加进轨迹。
- `p_t == 1`（新笔起笔）：先做**入锋/回锋**动作，再落到 `h`：
  - **楷书**（`type==1`）：从左上方 `(x_-2r_, y_-2r_)` 悬空(z=0.05)进入 → 落到当前点 h。
  - **隶书**（`type==0`）：正上方悬空进入 → 落笔 → 沿**下一点反方向**回退 `2r_`（回锋）→ 再下行到当前点。
- **每笔结束/整字结束**：末尾追加 5 个点，z 逐步 `+0.015` 抬笔离纸。

> 要点：**起笔/回锋是手工硬编码的启发式**（不是学出来的），且只区分楷/隶两种。z 的 `-0.09/100` 是经验微调。这些都是"复现外观"层面的 trick。

---

## 4. 环节③：Dobot 下发 —— `SetPTPCmd`

代码：`callibrate/DobotDllType.py`（DLL 封装）。真正让臂动的调用：

```python
SetPTPCmd(api, ptpMode, x, y, z, rHead, isQueued=0)
#   ptpMode = PTPMode.PTPMOVLXYZMode (=2)   直线插补(MOVL), 笛卡尔 XYZ
#   x, y, z : 目标位置 (Dobot 坐标系, 单位 mm)
#   rHead   : 末端旋转 (写字固定, 通常 0)
```
- 典型时序（Dobot 标准用法，推断自 API）：`ConnectDobot` → `SetHOMECmd` 回零 → `SetPTPCommonParams(velocityRatio, accelerationRatio)` / `SetPTPCoordinateParams(xyzVel, xyzAcc, ...)` 设速度加速度 → 逐点 `SetPTPCmd(..., isQueued=1)` 压入队列 → `SetQueuedCmdStartExec` 开始执行。
- **`PTPMOVLXYZMode`**：点到点**直线**运动，臂沿直线走到目标 → 相邻控制点间是直线段（折线逼近曲线）。
- **单位注意**：`process()` 产出的是**米**（notebook 打印 0.025 / 0.07602 等即米）；而 Dobot API 用 **mm** → 缺失的 `Control()` 里必然有 **×1000 缩放**（见 §5）。

---

## 5. ⚠️ 未开源 / 需自己补的部分

1. **`RoboControl.py`（含 `Control()` 发送循环）没有在仓库里**。全仓搜 `SetPTPCmd` 只出现在 DLL 封装，无任何脚本调用它。`Control()` 的行为可从 notebook + `process()` + API 完整反推，但**现成的"读 npz → 逐点下发"循环代码是缺的**。其职责推断为：
   ```
   Control(npz): 读 pos_3d_x/y/z → 连接/回零/设参数 → for 每点: SetPTPCmd(MOVLXYZ, x*1000, y*1000, z*1000, 0, isQueued=1) → StartExec
   ```
2. **Dobot 那套（`DobotDll.dll` + `DobotDllType.py`）是 Windows + Dobot 专用**，Elfin 上完全用不了 → 控制层必须重写。
3. **拿到某个字的控制点序列**需要跑他们的 ML：下载 Google Drive 权重 → `seq_extract` 出粗序列 → `rl_finetune` 的 SAC（`Callienv.py` 里 `np.save` 出 `(p_t,x,y,r)` 的 `.npy`）→ `process()` → npz。**SAC 参数是按具体字/工具单独训的**，成本高。

---

## 6. 映射到本项目（PyBullet 仿真 → 华沿 SDK 实机）

> ROS2/Gazebo 路线已于 07-15 放弃，实际技术栈是纯 Python + PyBullet；下表按此更新（B1 已实际交付，见 `docs/b0-b1-results.md`）。

| CalliRewrite（Dobot） | 你在本项目上 | 取舍 |
|---|---|---|
| `SetPTPCmd(MOVLXYZ,...)` 逐点直线 | `OpenLoopController` 沿路点弧长插值 → `SimBackend` 用 PyBullet IK 逐步驱动（实机则 `HuayanBackend` 走华沿 SDK `HRIF_PushServoP`） | 🔁 换实现（已完成，B1） |
| `RoboControl.Control()` 发送循环 | `run.py` 通用 read→step→write 循环，两端（Sim/实机）通用 | ✍️ 已重写（B1 产物） |
| `r→z` 标定 + `func_brush` | 同思路：`calligraphy/calibration.py` 移植 `func_brush`（笔宽 r → 笔高 z） | ✅ 已借方法（B1） |
| `process()` 起笔/回锋启发式 | `calligraphy/strokeseq.py` 的 `process()`，可先不要精细起笔/回锋，直接走 xy+固定 z 验证链路 | ⏭️ 可选 |
| 开环、位置控宽度 | **已实现 = B1 开环基线**（PyBullet 仿真，`write_openloop.py`） | ✅ 复现完成 |
| —（无力觉） | **换成触觉力控提按 = B2/Z 控制超越点**（Phase 0/1 已完成，见 `docs/handoff-z-phase1.md`） | 🚀 你的贡献 |

**复现路径（已走完）**：手工/合成一份 `(x,y,z)` 控制点 npz → `OpenLoopController` + `SimBackend`（PyBullet）逐点开环描出 → 得到 B1 开环基线与控制链路验证。实机迁移只需换 `HuayanBackend`（华沿 SDK），算法层不动。

---

## 7. 局限（作者自陈）与提示

- 失败源：笔画分割不准、机械臂**误差累积**、**sim2real gap**（标定不准）。
- 对你的提示：① 开环误差累积 → 你有**触觉闭环**可对抗；② 它靠标定凑宽度、你直接真机采真实触觉，天然缩小 sim2real；③ 起笔/回锋它是手工启发式、你后续可由示范/模型学。

---

## 8. 代码位置速查

| 文件 | 内容 |
|---|---|
| `reference/CalliRewrite/callibrate/callibrate.ipynb` | r→z 标定全流程 + `func_brush/func_fude` |
| `reference/CalliRewrite/callibrate/load_data_try.py` | `process()` 序列→控制点 |
| `reference/CalliRewrite/callibrate/DobotDllType.py` | Dobot DLL 封装（`SetPTPCmd` @1819, `PTPMode` @260, 参数设置函数）|
| `reference/CalliRewrite/rl_finetune/Callienv/envs/Callienv.py` | RL 环境，`np.save` 产出 `(p_t,x,y,r)` .npy（@361-362）|
| `RoboControl.py` | **未开源**（发送循环，需自己重写）|
| `reference/2024_CalliRewrite_精读.md` | 论文精读（方法/指标/借鉴地图）|
