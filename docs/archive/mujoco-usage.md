# MuJoCo 使用手册 · Elfin 写字 + 物理触角

> 快速上手看 `quick_start_mujoco.md`（2 分钟跑起来）；本文是**完整手册**：所有命令、键位、
> 场景构成、可调参数、原理、踩过的坑。代码在 `src/brushbot/tactile/mj_write.py`。
> 独立触角（不带机械臂）的仿真命令见 `docs/tactile-sim-usage.md`。

---

## 1. 环境

`mujoco` 已在 `pyproject.toml` 依赖里，装过本项目就有：

```
conda activate brushbot
```

字形数据（9574 字笔画中线，已 gitignore）：

```
mkdir -p data/makemeahanzi && curl -fsSL https://raw.githubusercontent.com/skishore/makemeahanzi/master/graphics.txt -o data/makemeahanzi/graphics.txt
```

自检（几秒，无需显示器）：

```
python -m brushbot.tactile.mj_write ik
```

应打印 `组合模型 bodies=...` + 三行 `IK -> [...] : 残差 0.0000 m ✅`。

---

## 2. 四种运行模式

| 模式 | 命令 | 作用 | 需显示器 |
|---|---|---|---|
| **watch** ★ | `python -m brushbot.tactile.mj_write watch 永` | 实时窗口，写字 + 触角碰纸 + 交互 | ✅ |
| write | `python -m brushbot.tactile.mj_write write 永 out.png` | 无窗口，出轨迹静图 | ❌ |
| ik | `python -m brushbot.tactile.mj_write ik` | 模型 + IK 自检 | ❌ |
| contact ⚠️ | `python -m brushbot.tactile.mj_write contact 永 out.png` | 接触→ΔB（**WIP，输出不可信**） | ❌ |

**多字**（窗口里按 `n` 逐个切换）：

```
python -m brushbot.tactile.mj_write watch 永 書 王 龍
```

---

## 3. 窗口交互

### 3.1 键位（本项目自定义）

| 键 | 作用 |
|---|---|
| `r` | **重写**当前字（回起笔位、清墨、重跑） |
| `c` | 只清墨（擦干净，不重写） |
| `n` | **下一个字**（命令行给多字时循环切换） |
| `1` | 俯视 —— 看成品字最清楚 |
| `2` | 斜视（默认） |
| `3` | 侧视 —— **看抬笔/落笔、看触角弯**最直观 |
| `4` | 全景 —— 看整条机械臂 |
| `空格` | 暂停 / 继续 |
| `+` / `-` | 播放快 / 慢（×1.5 每次，范围 0.15–8×） |
| `q` | 退出（也可直接关窗） |

> 写完后窗口**不会退出**，仍可转视角、按 `r` 重写、按 `n` 换字。

### 3.2 鼠标 & MuJoCo 内置键

**鼠标**：左键拖 = 转视角 ｜ 右键拖 = 平移 ｜ 滚轮 = 缩放 ｜ 双击 = 选中部件

**MuJoCo 自带**：`Tab` 开关侧栏面板 ｜ `H` 帮助浮层 ｜ `Esc` 退出

> 注意：MuJoCo 内置键位和 PyBullet 版（`quick_start.md`）不同，别混。

---

## 4. 场景构成

```
        ┌─ Elfin5 六轴（URDF，碰撞组 1）
        │
   link6 原点  z=0.2740 (落笔时)
        │  ← 法兰端面偏移 FLANGE_FACE = 0.0545 m
   法兰端面   z=0.2195
        │  ← 触角 ANT_LEN = 0.024 m（8 段铰链胶囊，碰撞组 4）
   触角尖     z≈0.1960
   ─────────  纸面 z=0.1965   （BOX 半厚 0.002，碰撞组 4）
   ─────────  桌面板 z∈[0.1805, 0.1925]（12mm 厚，碰撞组 2 = 谁也不碰）
        │
   地面 z=0（视觉平面）
```

**碰撞组设计**：触角(4) ↔ 纸(4) 相碰；臂(1) 与两者都不碰（避免自碰干扰）；桌子(2) 谁也不碰（纯装饰）。

**关键常量**（`mj_write.py` 顶部）：

| 常量 | 值 | 含义 |
|---|---|---|
| `FLANGE_FACE` | 0.0545 | link6 原点 → 法兰端面（实测 link6 网格局部 z 范围） |
| `ANT_N` / `ANT_SEG` | 8 / 0.003 | 触角段数 / 段长 → `ANT_LEN` = 0.024 |
| `TOOL_LEN` | 0.0785 | link6 原点 → 触角尖 = `FLANGE_FACE + ANT_LEN` |
| `PAPER_Z` | 0.20 | 抽象书写平面（与 `brushbot.config` 一致） |

---

## 5. 可调参数

### 5.1 命令行/函数参数

```python
watch_write(chars="永", speed=0.02, substeps=8, realtime=True)
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `chars` | "永" | 单字或多字串，`n` 键切换 |
| `speed` | 0.02 | 运笔速度 m/s（改轨迹本身；窗口里 `+/-` 只改播放快慢，不改轨迹） |
| `substeps` | 8 | 每拍物理子步；调大=接触更稳但更慢 |
| `realtime` | True | False = 全速跑（不 sleep） |

### 5.2 模型参数

```python
build_model(urdf, ant_n=8, tilt_deg=12.0, paper_z=PAPER_Z,
            ah_stiff=0.02, ah_damp=0.02, timestep=None,
            paper_solref=(0.004, 1.0), paper_solimp=None)
```

| 参数 | 作用 | 调参经验（实测） |
|---|---|---|
| `tilt_deg` | 触角安装倾角 | 给接触一个明确弯曲方向；0 会变成纯轴向压（不弯只戳） |
| `ah_stiff` / `ah_damp` | 触角铰链刚度/阻尼 | **越软越弯**，但写字时会甩：0.008 能弯到 33°，代价是穿透从 1.6→2.9mm |
| `paper_z` | 纸 BOX 中心高 | **必须对齐触角尖落点**，否则不是穿纸就是够不着 |
| `paper_solref/solimp` | 接触硬度 | 调硬减少软穿透；实测**穿透 ≈ 0.8×压量**，压量才是主因 |

**压量**（`watch_write` 内）：`paper_top = pen_tip_z + 0.001`。实测压量 vs 效果：

| 压量 | 尖端穿透 | 弯角 |
|---|---|---|
| 0.5mm | 0.17mm | ~4° |
| **1.0mm（当前）** | **0.67mm** | **~4–8°** |
| 2.0mm | 1.67mm | ~4° |

> 结论：**加压量只增穿透、不增弯**（弯主要由铰链刚度决定）。当前取"贴合不穿"这个稳的点。

---

## 6. 原理：为什么是"臂运动学 + 触角动力学"混合驱动

| 方案 | 结果 |
|---|---|
| 全运动学（`mj_forward`） | 臂精确，但**触角不碰纸、刚性穿过去** ❌ |
| 全动力学（伺服跟踪） | 触角会碰，但**臂跟不上轨迹、解支跳变发散乱甩** ❌ |
| **混合（当前）** | 臂每子步 `qpos` 硬置回 IK 解 + `qvel=0`（钉死，绝不甩）；触角自由跑 `mj_step`（真碰真弯）✅ |

IK 在**独立的 `scratch` MjData** 上求解并从上一解暖启动，避免扰动 `d` 里的触角动力学状态、也保持解支连续。

**只做可视化、不算 ΔB** —— 因此绕开了 Phase 3 的 ΔB 发散 bug（见 §8）。

---

## 7. 代码 API

```python
from brushbot.tactile.mj_write import build_model, ik, write, watch_write

m = build_model()                       # → mujoco.MjModel（Elfin+触角+纸+桌+执行器）
err, q = ik(m, d, target_pos, target_quat)   # 雅可比 DLS，只动 6 个臂关节；返回(残差 m, 关节角)
r = write("永")                          # → {model, data, trace_l6, trace_tip}
watch_write("永書")                      # 实时窗口（需显示器）
```

---

## 8. 踩过的坑（都已修，留档避免重犯）

| 坑 | 现象 | 根因 / 修法 |
|---|---|---|
| **触角埋在腕壳里** | 怎么调纸高都"穿模" | 触角挂在 link6 **原点**只伸 24mm，但 link6 网格伸到 54.5mm → **腕部**比纸低 31mm 在戳纸。修：挂到**法兰端面** `FLANGE_FACE`，路点补 `TOOL_LEN` |
| **桌子凭空消失** | `add_geom` 加了却编译不出来 | URDF 派生的 spec 默认 `discardvisual=true`，**纯视觉件(contype=conaffinity=0)被编译丢弃**。修：给独立碰撞组 2 |
| **实心桌块被臂穿过** | 加桌子后小臂穿桌 | 从地面到纸底的实心块占了臂的工作空间。修：改 **12mm 薄桌面板** |
| **触角刚性穿纸** | 触角不碰纸直接穿过 | 用了 `mj_forward`（无接触动力学）。修：混合驱动跑 `mj_step` |
| **臂乱甩** | 伺服跟踪时发散 | 纯 P 无阻尼 + 解支跳变。修：臂改运动学钉死 |
| **IK 分支跳变** | 轨迹突然翻转 | 从抖动状态暖启动。修：在 `scratch` 上从上一解暖启动 |
| **`bid=-1`** | 找不到末端 body | 固定关节的 body 被 compile 焊入。修：用 `elfin_link6` |
| ⚠️ **Phase3 ΔB 发散** | ΔB 爆到 10^9% | 某些拍触角中线换到传感器系时错乱 → 磁偶极 1/r³ 发散。**未根治，WIP** |

---

## 9. 排错

| 现象 | 解决 |
|---|---|
| `需要 mujoco.viewer(...)` / 没弹窗 | 无图形界面（SSH 无 X11）。改用 `write` / `ik` 无窗口模式 |
| 窗口里**没有棕色桌子** | 跑的是旧代码 → `pip install -e .`（仓库根目录） |
| `FileNotFoundError: graphics.txt` | 没下字形数据，见 §1 |
| `ParseXML: Error opening file ...elfin5.urdf` | **不在仓库根目录跑**（URDF 是相对路径）。`cd ~/FYP` 再跑 |
| `KeyError: '某字'` | 该字不在 9574 字里，换常用字 |
| 字体告警 `Glyph ... missing from font` | matplotlib 存图时中文标题告警，不影响结果 |
| 看不到字/触角 | 按 `1` 俯视 或 `3` 侧视；滚轮拉近 |

---

## 10. 状态与边界

| | |
|---|---|
| ✅ | Phase 1 组合模型 + 雅可比 DLS IK（残差 ~1e-4 m） |
| ✅ | Phase 2 写任意汉字（笔顺/中线来自真实字形数据） |
| ✅ | Phase 4 实时窗口 + 交互（重写/换字/视角/暂停/调速） |
| ✅ | 触角**物理接触纸、尖端贴纸微弯**；臂与纸/桌**零相交**（全轨迹逐点验证） |
| ⚠️ | Phase 3 触角形变 → **ΔB 数值**：静态对、**动态 WIP 不可信** |
| ⏳ | **提按**——笔画仍等宽；压深→变粗要靠触觉闭环（B2 核心命题） |

**诚实边界**：窗口里的触角弯曲是**物理真实的**（MuJoCo 接触求解），但"弯曲 → ΔB 数值"那步仍是
WIP；参数（磁化强度、刚度）是调的，**不是真机数值**。真值要真机标定——见
`docs/gate-experiments.md`（E2 标定、E5 数据采集）。
