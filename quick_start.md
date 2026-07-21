# Quick Start — 看 Elfin5 在仿真里写你指定的字

目标：**一条命令**，弹出仿真窗口，看机械臂**拿毛笔在纸上一笔一划写字、墨迹实时浮现**，还能随时重写。

---

## 一、一次性准备（三步）

在仓库根目录 `~/FYP` 下执行。

**1. 建环境**（已建过可跳过）

```
conda create -y -n brushbot python=3.10 && conda run -n brushbot pip install pybullet numpy pytest pillow
```

**2. 安装本项目**

```
conda run -n brushbot pip install -e .
```

**3. 下载字形数据**（Make Me a Hanzi，9574 字的笔画中线，30MB，已 gitignore）

```
mkdir -p data/makemeahanzi && curl -fsSL https://raw.githubusercontent.com/skishore/makemeahanzi/master/graphics.txt -o data/makemeahanzi/graphics.txt
```

---

## 二、跑起来

```
conda activate brushbot && python scripts/watch_write.py 永
```

**想写别的字就换参数**；给多个字可在窗口里按 `n` 逐个切换：

```
conda activate brushbot && python scripts/watch_write.py 永 書 王 龍
```

---

## 三、你会看到什么

1. 弹出 **PyBullet 窗口**：Elfin5 机械臂 + 桌子 + 白纸，末端拿着一支**毛笔**（笔杆垂直向下）。
2. 机械臂移到起笔位置停稳，然后**按笔顺一笔一笔写**（笔间抬笔、空中移位）。速度已放慢到肉眼可看。
3. **墨迹实时出现在纸上**——笔尖压到纸面就留墨，抬笔就断开，字一笔一划长出来。
4. 终端打印：

   ```
   永: 5 笔, 47 个路点
   写完: 落笔点 361 | 墨迹图 -> /tmp/brushbot_永.png | 纸面 -> /tmp/brushbot_永-paper.png
   ```

---

## 四、窗口里的操作（写完后仍可交互）

**鼠标**：左键拖 = 转视角 ｜ 滚轮 = 缩放 ｜ Ctrl（或中键）拖 = 平移

**键盘**：

| 键 | 作用 |
|---|---|
| `r` | **清纸重写**当前字 |
| `c` | 只清纸（擦干净） |
| `n` | 换**下一个字**（命令行给多个字时） |
| `1` | 俯视——看成品字最清楚 |
| `2` | 斜视（默认） |
| `3` | 侧视——**看抬笔/落笔**最直观 |
| `4` | 全景——看整条机械臂 |
| `q` | 退出（也可直接关窗口） |

> 建议：写的过程中按 `3` 侧视看抬落笔，写完按 `1` 俯视看成品。

---

## 五、无窗口模式

```
conda activate brushbot && python scripts/watch_write.py 書 --headless
```

不开窗、跑得快，只出两张图（适合批量）。

想调字号/速度/笔画粗细，改 `scripts/watch_write.py` 里 `run_session()` 的参数：
`size`（字框边长，默认 0.032 米）、`speed`（运笔速度 m/s）、`zc_down`（落笔压深，越小笔画越粗）。

---

## 六、排错

| 现象 | 原因 / 解决 |
|---|---|
| `FileNotFoundError: ...graphics.txt` | 没下数据集，回到准备第 3 步 |
| `KeyError: '某字'` | 该字不在 9574 字里，换个常用字 |
| 没有弹窗 / `Could not create GL context` | 无图形界面（SSH 无 X11）。加 `--headless` |
| `ModuleNotFoundError: brushbot` | 没装包，回到准备第 2 步（在仓库根目录执行） |
| 视野里看不到字 | 按 `1` 切俯视；或滚轮缩放 |

---

## 七、跑测试

```
conda run -n brushbot pytest
```

应为 **32 passed**（缺数据集时会 skip 掉 2 个集成测试）。

---

## 八、能做什么 / 还不能做什么

| | |
|---|---|
| ✅ | 写 9574 个汉字中任意一个，笔顺与笔画中线来自真实字形数据 |
| ✅ | 走任意自定义 `(x,y,z)` 路点轨迹（圆、任意形状） |
| ✅ | 仿真里实时看到墨迹、可反复重写 |
| ⏳ | **提按**——现在笔画**等宽**（像硬笔）。字形数据只给"笔往哪走"，不给"按多重" |

"压深→笔画变粗"要靠**触觉毛笔 + 力控闭环**才算数，那是下一步 **B2**，也是这个项目的核心命题。
