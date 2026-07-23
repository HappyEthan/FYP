# 触觉仿真 · 使用手册（看触角形变 + ΔB）

> 纯仿真看"触角形变 + 模拟 ΔB 信号"。无需触角实体。代码在 `src/brushbot/tactile/`。
> 方案见 `docs/tactile-fem-sim.md`；ΔB 控制见 `docs/deltaB-control.md`。

---

## 0. 先激活环境（每个终端一次）

```
conda activate brushbot
```

之后下面每条命令直接用。若不想激活，把每条 `python` 换成 `conda run -n brushbot python`。

---

## 1. ★ 实时 3D：看触角被压弯（推荐，需显示器）

打开 MuJoCo 窗口，触角循环下压→回弹而弯曲，控制台同步打印 ΔB。关窗退出。

```
python -m brushbot.tactile.contact_sim watch
```

---

## 2. 接触形变静图（触角被逐级压弯 + ΔB）

```
python -m brushbot.tactile.contact_sim contact.png
```

生成 `contact.png`：左=触角被接触顶弯（压 0→21mm），右=ΔB 随压深。

---

## 3. 形变 + ΔB 动画 GIF（提按脉动 + 拖拽转圈）

```
python -m brushbot.tactile.antenna_model anim antenna.gif
```

生成 `antenna.gif`：左=触角中线弯，中=ΔB 时序，右=(Bx,By) 矢量轨迹。

---

## 4. P0 静图（形变 → ΔB 结构：面内变、轴向平）

```
python -m brushbot.tactile.antenna_model p0.png
```

---

## 5. 压/拖可分性（喂 E4 判据）

```
python -m brushbot.tactile.separability sep.png
```

生成 `sep.png` + 控制台打印判据（投影法需 θ≥85° 才 <10% 误差）。

---

## 6. 看图（Linux）

```
xdg-open contact.png
```

```
xdg-open antenna.gif
```

---

## 说明

- 图默认落在**当前目录**；想放别处就把 `contact.png` 换成 `docs/assets/contact.png` 等路径。
- 各模块的函数（`sensor_B`、`run`、`sweep_dB`…）可直接 import 复用；`sensor_B` 是引擎无关的磁学半段，接 SOFA/MuJoCo/解析梁都用它。
- **诚实边界**：这些是物理接地的**合成模型**，任意单位、参数是调的——复现的是"结构/趋势"（哪个轴变、迟滞形态、压/拖能否分），**不是真机数值**。真值要真机 E2 标定。
