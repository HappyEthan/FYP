# 监控窗口滤波接入 + XY 拖尾 + 回放进度条 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 监控窗口接入可选滤波器（选择器 + 原始叠影 + XY 拖尾）并补回放进度条，录制/门控语义零改动。

**Architecture:** `FILTERS` 工厂放 `monitor/core.py`（无 GUI 依赖、可单测）；窗口保持每帧批量重滤，`_redraw` 整体重写一次到位；`ArraySource` 加 `progress`/`duration_s` 公开属性支撑进度条。

**Tech Stack:** Python 3.10+，numpy，PyQt5 + pyqtgraph（GUI，仅 window.py），pytest。

**Spec:** `docs/superpowers/specs/2026-07-29-monitor-filter-ui-design.md`

## Global Constraints

- 分支 `feat/monitor-filter-ui`（从 master 切出，控制器已建好）。
- **本机无 PyQt5**：window.py 不可运行/不可 import。GUI 改动验证 = `python -m py_compile` + 全量 pytest 无回归 + 评审细读 diff；手动验收清单交付用户。
- **录制/门控/接触判定零改动**：`derive()`、gate、`Recorder.add` 继续吃原始 `dB`，滤波仅影响显示曲线与 XY 圆。
- 滤波默认档 "EMA 0.3"（与现状行为一致）；批量重滤模式（每帧 `reset()` + 整窗 `update()`）。
- `sources.py` 禁止 import GUI 库；`core.py` 同样禁止。
- 所有终端命令写成单行。
- 每个 Task 结束跑全量 `python -m pytest` 确认无回归后再 commit。

---

### Task 1: ArraySource.progress / duration_s

**Files:**
- Modify: `src/brushbot/monitor/sources.py`（`ArraySource` 类内，`done` 属性之后插入）
- Test: `tests/test_monitor_sources.py`（末尾追加）

**Interfaces:**
- Consumes: 现有 `ArraySource`（`_t`、`_i`、`seek(frac)`）。
- Produces: `ArraySource.progress -> float`（属性，0~1，空数组返回 1.0）、`ArraySource.duration_s -> float`（属性，`t[-1]-t[0]`，空数组返回 0.0）。Task 4 的进度条依赖这两个名字。

- [ ] **Step 1: 写失败测试**

在 `tests/test_monitor_sources.py` 末尾追加（确认文件顶部已有 `import numpy as np`、`import pytest`、`from brushbot.monitor import sources as S`，缺哪个补哪个）：

```python
def test_progress_and_duration():
    t = np.arange(100) / 100.0
    src = S.ArraySource(t, np.zeros((100, 3)), rate_hz=100.0)
    assert src.progress == 0.0
    assert src.duration_s == pytest.approx(0.99)
    src.start()
    src.seek(0.5)
    assert src.progress == pytest.approx(0.5, abs=0.02)
    src.seek(1.0)
    assert src.progress == 1.0
    assert src.done


def test_progress_empty_array():
    src = S.ArraySource([], np.zeros((0, 3)))
    assert src.progress == 1.0
    assert src.duration_s == 0.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/ethan/FYP && python -m pytest tests/test_monitor_sources.py -v -k progress`
Expected: FAIL，`AttributeError: 'ArraySource' object has no attribute 'progress'`

- [ ] **Step 3: 实现**

在 `src/brushbot/monitor/sources.py` 的 `ArraySource.done` 属性（`return self._i >= len(self._t)`）之后、`info` 属性之前插入：

```python
    @property
    def progress(self) -> float:
        """播放进度 0~1. 空数组视为已播完, 返回 1.0."""
        n = len(self._t)
        return 1.0 if n == 0 else min(self._i / n, 1.0)

    @property
    def duration_s(self) -> float:
        """记录总时长 (s). 空数组返回 0.0."""
        return float(self._t[-1] - self._t[0]) if len(self._t) else 0.0
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /home/ethan/FYP && python -m pytest tests/test_monitor_sources.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 全量回归 + Commit**

Run: `cd /home/ethan/FYP && python -m pytest`
Expected: 全部 PASS

```bash
git add src/brushbot/monitor/sources.py tests/test_monitor_sources.py && git commit -m "feat(monitor): ArraySource progress/duration_s properties"
```

---

### Task 2: FILTERS 工厂（core.py）

**Files:**
- Modify: `src/brushbot/monitor/core.py`（顶部 import + `EMA` 类之后追加）
- Test: `tests/test_monitor_core.py`（末尾追加）

**Interfaces:**
- Consumes: `brushbot.filter.ButterworthFilter/OneEuroFilter`（已在 master）、本文件 `EMA`。
- Produces: `FILTERS: dict[str, callable | None]` —— label → 无参构造函数（`None` = 原始不滤波）。键序即窗口下拉顺序。Task 3 依赖此名字与 "EMA 0.3" 键。

- [ ] **Step 1: 写失败测试**

在 `tests/test_monitor_core.py` 末尾追加（确认顶部有 `import numpy as np`，缺则补）：

```python
def test_filters_factory():
    from brushbot.monitor.core import FILTERS
    assert list(FILTERS.keys())[0] == "原始" and FILTERS["原始"] is None
    assert "EMA 0.3" in FILTERS and len(FILTERS) == 5
    x = np.random.default_rng(0).normal(size=(50, 3))
    for label, make in FILTERS.items():
        if make is None:
            continue
        f = make()
        y = np.asarray(f.update(x))
        assert y.shape == (50, 3), label
        f.reset()
        y2 = np.asarray(f.update(x))
        assert np.allclose(y, y2), "%s reset 后不确定" % label
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/ethan/FYP && python -m pytest tests/test_monitor_core.py -v -k filters`
Expected: FAIL，`ImportError: cannot import name 'FILTERS'`

- [ ] **Step 3: 实现**

`src/brushbot/monitor/core.py` 顶部 import 区追加一行：

```python
from brushbot.filter import ButterworthFilter, OneEuroFilter
```

`EMA` 类定义结束之后（`derive` 函数之前）追加：

```python
# 窗口滤波选择器工厂: label -> 无参构造函数; None = 原始不滤波.
# 参数依据 docs/filter-comparison.md 选型报告.
FILTERS = {
    "原始": None,
    "EMA 0.3": lambda: EMA(0.3),
    "Butter 5Hz": lambda: ButterworthFilter(5.0),
    "Butter 8Hz": lambda: ButterworthFilter(8.0),
    "OneEuro": lambda: OneEuroFilter(0.5, 0.03),
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /home/ethan/FYP && python -m pytest tests/test_monitor_core.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 全量回归 + Commit**

Run: `cd /home/ethan/FYP && python -m pytest`
Expected: 全部 PASS

```bash
git add src/brushbot/monitor/core.py tests/test_monitor_core.py && git commit -m "feat(monitor): FILTERS factory for display filter selection"
```

---

### Task 3: 窗口滤波选择器 + 原始叠影 + XY 拖尾

**Files:**
- Modify: `src/brushbot/monitor/window.py`

**Interfaces:**
- Consumes: `FILTERS`（Task 2）。
- Produces: 窗口成员 `self.filt`（当前滤波器实例或 None）、`self.cb_filter`、`self.c_trail`、ghost 曲线 `self.cur_x_raw/cur_y_raw/cur_mag_raw/cur_z_raw`。Task 4 不依赖本任务新名字。

无自动化 GUI 测试（本机无 PyQt5）。验证 = py_compile + 全量 pytest + 自查清单（Step 5）。

- [ ] **Step 1: 常量与 import**

`window.py` 顶部：import 行 `from brushbot.monitor.core import RingBuffer, Baseline, EMA, derive` 改为：

```python
from brushbot.monitor.core import RingBuffer, Baseline, FILTERS, derive
```

常量区（`RATE_TOLERANCE = 0.02` 之后）追加：

```python
DEFAULT_FILTER = "EMA 0.3"
TRAIL_S = 3.0            # XY 圆拖尾时长 (s)
```

- [ ] **Step 2: __init__ 与工具栏改造**

`__init__` 中 `self.ema = EMA(alpha=0.3)` 改为：

```python
        self.filt = FILTERS[DEFAULT_FILTER]()
```

`__init__` 中删除这两行（被拖尾/选择器取代）：

```python
        self._xy_alpha = 0.06
        self._prev_norm = None
```

`_build_ui` 中，"滤波α" 与 "XYα" 两个下拉块（从 `bar.addWidget(QtWidgets.QLabel(" 滤波α "))` 到 `bar.addWidget(self.cb_xy_alpha)` 共两段）整体替换为：

```python
        bar.addWidget(QtWidgets.QLabel(" 滤波 "))
        self.cb_filter = QtWidgets.QComboBox()
        self.cb_filter.addItems(list(FILTERS.keys()))
        self.cb_filter.setCurrentText(DEFAULT_FILTER)
        self.cb_filter.setFixedWidth(110)
        bar.addWidget(self.cb_filter)
```

信号连接区：删除 `self.cb_alpha.currentTextChanged.connect(self._set_alpha)` 和 `self.cb_xy_alpha.currentTextChanged.connect(self._set_xy_alpha)`，追加：

```python
        self.cb_filter.currentTextChanged.connect(self._set_filter)
```

方法 `_set_alpha` 与 `_set_xy_alpha` 整体替换为：

```python
    def _set_filter(self, label: str):
        make = FILTERS.get(label)
        self.filt = None if make is None else make()
```

- [ ] **Step 3: 曲线对象（叠影 + 拖尾）**

`_build_ui` 中 `self.c_vec = ...` 之后追加拖尾曲线：

```python
        self.c_trail = self.p_xy.plot(pen=pg.mkPen((255, 77, 109, 75), width=1))
        self.c_trail.setZValue(-1)
```

四条彩色曲线（`self.cur_x = ...` 到 `self.cur_z = ...`）之后追加叠影：

```python
        ghost_pen = pg.mkPen((139, 148, 158, 90), width=1)
        self.cur_x_raw = self.p_x.plot(pen=ghost_pen)
        self.cur_y_raw = self.p_y.plot(pen=ghost_pen)
        self.cur_mag_raw = self.p_mag.plot(pen=ghost_pen)
        self.cur_z_raw = self.p_z.plot(pen=ghost_pen)
        for c in (self.cur_x_raw, self.cur_y_raw, self.cur_mag_raw, self.cur_z_raw):
            c.setZValue(-1)
```

- [ ] **Step 4: _redraw 重写 + 清理**

`_redraw` 方法从开头到 `# 接触指示` 注释之前（即滤波、setData、归一化 XY 圆整段）替换为：

```python
    def _redraw(self):
        win_s = WINDOWS_S[self.cb_win.currentIndex()]
        t, B = self.rb.latest(win_s * RATE_HZ)
        if len(t) == 0:
            return
        dB = self.bl.apply(B)
        # 批量重滤(仅显示; 录制/门控/接触判定仍用原始 dB)
        if self.filt is None:
            dB_smooth = dB
        else:
            self.filt.reset()
            dB_smooth = np.atleast_2d(self.filt.update(dB))  # 单样本帧防 (3,) 塌缩
        mag_xy = np.hypot(dB_smooth[:, 0], dB_smooth[:, 1])
        mag_xy_raw = np.hypot(dB[:, 0], dB[:, 1])

        self.cur_x.setData(t, dB_smooth[:, 0])
        self.cur_y.setData(t, dB_smooth[:, 1])
        if self.p_mag.isVisible():
            self.cur_mag.setData(t, mag_xy)
        if self.p_z.isVisible():
            self.cur_z.setData(t, dB_smooth[:, 2])
        # 原始叠影(选"原始"时隐藏, 避免同一条线画两遍)
        if self.filt is not None:
            self.cur_x_raw.setData(t, dB[:, 0])
            self.cur_y_raw.setData(t, dB[:, 1])
            if self.p_mag.isVisible():
                self.cur_mag_raw.setData(t, mag_xy_raw)
            if self.p_z.isVisible():
                self.cur_z_raw.setData(t, dB[:, 2])
        else:
            for c in (self.cur_x_raw, self.cur_y_raw, self.cur_mag_raw, self.cur_z_raw):
                c.setData([], [])

        gate = 3.0 * self.bl.sigma_norm if self.bl.ready else float("inf")
        last = dB[-1]
        d = derive(last, gate)
        # 归一化半径(基准仍取原始幅值最大值)
        if len(mag_xy_raw):
            self._norm_radius = max(self._norm_radius, float(mag_xy_raw.max()))

        # —— 归一化 XY 圆: 滤波后方向点 + 拖尾 ——
        if self._norm_radius > 1e-9:
            n_trail = min(len(dB_smooth), int(TRAIL_S * RATE_HZ))
            tr = dB_smooth[-n_trail:] / self._norm_radius
            self.c_trail.setData(tr[:, 0], tr[:, 1])
            nx, ny = float(tr[-1, 0]), float(tr[-1, 1])
            self.c_pt.setData([nx], [ny])
            self.c_vec.setData([0.0, nx], [0.0, ny])
        else:
            self.c_trail.setData([], [])
            self.c_pt.setData([], [])
            self.c_vec.setData([], [])
```

`# 接触指示` 起到方法结束保持原样不动。

其余清理（`_prev_norm`/`ema` 的残留引用）：

- `_restart` 中 `self._prev_norm = None` 改为 `self.c_trail.setData([], [])`。
- `_toggle_connect` 中 `self.ema = EMA(alpha=float(self.cb_alpha.currentText()))` 改为 `self._set_filter(self.cb_filter.currentText())`；`self._prev_norm = None` 改为 `self.c_trail.setData([], [])`。

改完全文 grep 确认无残留：`grep -n "cb_alpha\|cb_xy_alpha\|_xy_alpha\|_prev_norm\|self.ema\|EMA(" src/brushbot/monitor/window.py` 应无任何输出。

- [ ] **Step 5: 验证 + 自查**

Run: `cd /home/ethan/FYP && python -m py_compile src/brushbot/monitor/window.py && python -m pytest`
Expected: 编译无输出，测试全部 PASS

自查清单（写进报告）：
- `Recorder.add`、`derive(last, gate)`、gate 计算行与改造前逐字符一致（`git diff` 检查）
- "原始" 档路径：`self.filt is None` → 不调用任何滤波器
- 叠影/拖尾对象在 `_build_ui` 创建一次，`_redraw` 只 setData

- [ ] **Step 6: Commit**

```bash
git add src/brushbot/monitor/window.py && git commit -m "feat(monitor): filter selector with raw ghost overlay and XY trail"
```

---

### Task 4: 回放进度条 + 文档 + 手动验收清单

**Files:**
- Modify: `src/brushbot/monitor/window.py`
- Modify: `docs/monitor-usage.md`

**Interfaces:**
- Consumes: `ArraySource.progress/duration_s`（Task 1）、`seek(frac)`（现有）。
- Produces: 无后续依赖。

- [ ] **Step 1: 进度条 UI**

`_build_ui` 中主工具栏构建完成后（`self.cb_speed` 信号连接之后、`pg.setConfigOptions` 之前）追加：

```python
        self.bar_prog = self.addToolBar("回放进度")
        self.sl_prog = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.sl_prog.setRange(0, 1000)
        self.lbl_prog = QtWidgets.QLabel(" 0.0 / 0.0 s ")
        self.bar_prog.addWidget(self.sl_prog)
        self.bar_prog.addWidget(self.lbl_prog)
        self.bar_prog.setVisible(False)
        self._prog_dragging = False
        self.sl_prog.sliderPressed.connect(self._prog_press)
        self.sl_prog.sliderReleased.connect(self._prog_release)
```

- [ ] **Step 2: 进度条逻辑**

`_update_health` 方法之后追加三个方法：

```python
    def _prog_press(self):
        self._prog_dragging = True

    def _prog_release(self):
        self._prog_dragging = False
        if self.src is not None and hasattr(self.src, "seek"):
            self.src.seek(self.sl_prog.value() / 1000.0)

    def _update_progress(self):
        has_seek = self.src is not None and hasattr(self.src, "seek")
        if self.bar_prog.isVisible() != has_seek:
            self.bar_prog.setVisible(has_seek)
        if not has_seek:
            return
        dur = self.src.duration_s
        if not self._prog_dragging:
            self.sl_prog.blockSignals(True)
            self.sl_prog.setValue(int(self.src.progress * 1000))
            self.sl_prog.blockSignals(False)
        self.lbl_prog.setText(" %.1f / %.1f s " % (self.src.progress * dur, dur))
```

`_tick` 末尾 `self._update_health()` 之后追加一行：

```python
        self._update_progress()
```

- [ ] **Step 3: 更新 docs/monitor-usage.md**

通读该文档，做以下修改（保持原文风格）：
1. 所有提到 "滤波α" 下拉的地方改为 "滤波" 下拉，说明五个档位（原始 / EMA 0.3 / Butter 5Hz / Butter 8Hz / OneEuro）及叠影：淡灰细线 = 原始，亮色 = 滤波后；选"原始"单曲线。
2. 删除 "XYα" 相关描述，改为：XY 圆方向点用选中滤波器平滑，带 3 s 拖尾轨迹。
3. 新增回放进度条说明：仅回放/合成源显示，可拖动跳转，seek 后时序图窗口内可能短暂残留旧段（与 ⟳ 重放行为一致）。
4. 文档末尾追加手动验收清单一节：

```markdown
## 手动验收清单（2026-07-29 滤波 UI 改造）

在有显示器的机器上 `python -m brushbot.monitor` 逐项勾选：

- [ ] 滤波下拉五个选项可切换，切换即时生效
- [ ] 叠影：淡灰原始毛刺在下、亮色滤波曲线在上；选"原始"时只有一条曲线
- [ ] OneEuro 档：静止段明显比 EMA 稳，快速动作跟手
- [ ] XY 圆有 3 s 拖尾轨迹，⟳ 重放 / 进度条 seek 后拖尾在数秒内刷新为新轨迹（短暂新旧混合属正常，与时序图残留行为一致）
- [ ] 回放模式出现进度条，拖动跳转正确、时间标签正确；串口模式无进度条
- [ ] 录制一段后检查 CSV 是原始 ΔB（换滤波档重录，数值不变）
- [ ] 状态栏接触判定行为与改造前一致
```

- [ ] **Step 4: 验证**

Run: `cd /home/ethan/FYP && python -m py_compile src/brushbot/monitor/window.py && python -m pytest`
Expected: 编译无输出，测试全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/brushbot/monitor/window.py docs/monitor-usage.md && git commit -m "feat(monitor): replay progress bar + usage docs and manual acceptance checklist"
```

---

## 完成后

- 验收 = spec §7 清单；GUI 项待用户本机按 docs/monitor-usage.md 手动验收清单执行。
- 下一个独立项目：MuJoCo 联动（仿真侧 UDP 发布器 + SocketSource）。
