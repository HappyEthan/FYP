# Quick Start (MuJoCo) — 看 Elfin5 在 MuJoCo 里写字

> PyBullet 版见 `quick_start.md`。这份是 **MuJoCo** 版：同样是 Elfin5 写字，但跑在 MuJoCo 里，
> 为的是往下接**末端物理触角 + 接触形变 → ΔB**（PyBullet 那套只做开环写字，不做触角物理）。
>
> 📖 **完整手册**（全部参数、场景构成、原理、踩坑记录）见 **`docs/mujoco-usage.md`**。

目标：**一条命令**弹出 MuJoCo 窗口，看机械臂一笔一划写字、笔尖落点留下墨迹点。

---

## 一、一次性准备

在仓库根目录 `~/FYP` 下执行。和 PyBullet 版**共用同一个环境**——`mujoco` 已在项目依赖里，
装过 `pip install -e .` 就已经有了，无需额外安装。

**1. 建环境**（已建过可跳过）

```
conda create -y -n brushbot python=3.10 && conda run -n brushbot pip install -e .
```

**2. 下载字形数据**（Make Me a Hanzi，已 gitignore；PyBullet 版下过就跳过）

```
mkdir -p data/makemeahanzi && curl -fsSL https://raw.githubusercontent.com/skishore/makemeahanzi/master/graphics.txt -o data/makemeahanzi/graphics.txt
```

自检：`conda run -n brushbot python -c "import mujoco; print(mujoco.__version__)"` 应打印版本号（如 3.10.0）。

---

## 二、跑起来（★实时窗口）

```
conda activate brushbot && python -m brushbot.tactile.mj_write watch 永
```

写别的字换参数即可；**给多个字可在窗口里按 `n` 逐个切换**：

```
conda activate brushbot && python -m brushbot.tactile.mj_write watch 永 書 王 龍
```

---

## 三、你会看到什么

1. 弹出 **MuJoCo 窗口**：Elfin5 机械臂 + 一张白纸（BOX），末端从法兰往下伸一根**物理触角**（毛笔的替身，8 段铰链）。
2. 机械臂移到起笔位置，然后**按笔顺一笔一笔写**（笔间抬笔、空中移位）。已放慢到肉眼可看。
3. **落笔时触角尖贴着纸、被顶得微微弯**，抬笔离纸回弹；笔尖落点留下一串黑色墨点，字一笔一划长出来（墨点是标记球，非真实墨迹纹理）。触角尖入纸 <1mm（贴合，非穿透），杆身始终在纸面上方。
4. 终端打印：

   ```
   打开窗口: Elfin 写 '永'; 触角碰纸会弯, 笔尖落点留墨。关窗退出。
   写完(361 墨点)。关窗退出。
   ```

5. 写完后窗口**保持打开**，可以继续转视角看成品；关窗即退出。

---

## 四、窗口里的操作（写完后仍可交互）

**鼠标**：左键拖 = 转视角 ｜ 右键拖 = 平移 ｜ 滚轮 = 缩放 ｜ 双击 = 选中部件

**键盘**：

| 键 | 作用 |
|---|---|
| `r` | **清墨重写**当前字 |
| `c` | 只清墨（擦干净） |
| `n` | **下一个字**（命令行给多字时） |
| `1` | 俯视——看成品字最清楚 |
| `2` | 斜视（默认） |
| `3` | 侧视——**看抬落笔 / 触角弯**最直观 |
| `4` | 全景——看整条机械臂 |
| `空格` | 暂停 / 继续 |
| `+` / `-` | 播放快 / 慢 |
| `q` | 退出（也可直接关窗） |

> 建议：写的过程按 `3` 侧视看触角贴纸和抬落笔，写完按 `1` 俯视看成品。
> MuJoCo 自带：`Tab` 侧栏面板、`H` 帮助浮层。

---

## 五、无窗口 / 静态图（SSH 无显示时用）

出一张写字轨迹静图（link6 法兰 xy 路径 + 触角尖 xy），不弹窗、跑得快：

```
conda activate brushbot && python -m brushbot.tactile.mj_write write 永 mj_write.png
```

打印形如 `写完: 1567 拍  link6 x跨=0.030 y跨=0.032 m`，图落在 `mj_write.png`。

只想验证组合模型 + IK 通不通（最快自检，几秒）：

```
conda activate brushbot && python -m brushbot.tactile.mj_write ik
```

应打印 `组合模型 bodies=14 ...` 和三行 `IK -> [...] : 残差 0.0000 m ✅`。

---

## 六、和 PyBullet 版的区别

| | PyBullet（`quick_start.md`） | MuJoCo（本文） |
|---|---|---|
| 入口 | `scripts/watch_write.py 永` | `python -m brushbot.tactile.mj_write watch 永` |
| 实时窗口 | ✅ | ✅（Phase 4） |
| 末端驱动 | 刚性毛笔（运动学） | **臂运动学锁死 + 触角跑动力学**（混合） |
| 触角碰纸 | 无触角 | ✅ **物理接触、尖端贴纸微弯**（实时可见，杆身不穿纸） |
| 墨迹 | 纸面真实墨迹纹理 + 存 PNG | 笔尖落点标记球（简版） |
| 多字 `n` 切换 | ✅ | ❌（一次一个字） |
| 触角形变→**ΔB 数值** | 无 | ⚠️ Phase 3 **WIP**（见下；窗口只做可视化，不算 ΔB） |

**为什么要 MuJoCo 版**：PyBullet 只做"臂把笔移到哪"。MuJoCo 版末端是**能被纸顶弯的物理触角**，
写字时你能实时看到触角随落笔/抬笔弯曲/回弹——目标是往下做"触角形变 → ΔB"，对接触觉毛笔的核心命题。
**注意**：窗口里的触角弯曲是**物理真实的**，但把它换算成 ΔB 数值那一步仍是 WIP（见第七节），
所以窗口只看形变、不显示 ΔB。

---

## 七、⚠️ 触角接触 → ΔB（Phase 3，WIP，勿信输出）

```
conda activate brushbot && python -m brushbot.tactile.mj_write contact 永 mj_contact.png
```

这会跑"写字时触角物理接触纸 → ΔB"，但**目前动态积分不稳**（某些拍触角中线错乱 → 磁场 1/r³ 发散 →
ΔB 爆表）。**静态落笔的接触弯是对的，连续写字的 ΔB 不可信**。原因与现状见 `mj_write.py` 模块 docstring。

> 方向：改用**真实数据集**（一横 → 真实 ΔB 序列）做标定，合成 ΔB 只是没硬件时的替代。
> 见 `docs/gate-experiments.md`（E5 数据采集）、`docs/tactile-fem-sim.md`。

---

## 八、排错

| 现象 | 原因 / 解决 |
|---|---|
| `需要 mujoco.viewer(...)` / 没弹窗 | 无图形界面（SSH 无 X11）。用第五节的 `write`/`ik`（无窗口） |
| `FileNotFoundError: ...graphics.txt` | 没下字形数据，回到准备第 2 步 |
| `KeyError: '某字'` | 该字不在 9574 字里，换个常用字 |
| `ModuleNotFoundError: brushbot` / `mujoco` | 没装包，`pip install -e .`（在仓库根目录） |
| 字体告警 `Glyph ... missing from font` | 只是 matplotlib 存图时中文标题的告警，不影响结果 |
| 窗口里看不到字 | 滚轮拉近、左键转到俯视 |

---

## 九、能做 / 还不能做

| | |
|---|---|
| ✅ | MuJoCo 里 Elfin 写任意汉字（笔顺/中线来自真实字形数据），实时看 + 出静图 |
| ✅ | 组合模型（Elfin URDF + 物理触角链 + 纸）+ 雅可比 DLS IK（残差 0） |
| ✅ | 写字时**触角物理接触纸、尖端贴纸微弯**（实时窗口可见，臂锁死不乱甩，杆身不穿纸） |
| ⚠️ | 触角形变 → **ΔB 数值**：静态对、**动态 WIP**（不可信，见第七节） |
| ⏳ | **提按**——笔画仍等宽；压深→变粗要靠触觉闭环（B2 核心命题） |
