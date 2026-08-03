# 滤波器成果检验命令

> 全部单行，直接复制粘贴。工作目录任意（命令自带 cd）。

> **口径说明**：本文档验收的是**孤立滤波指标**管线（`scripts/compare_filters.py` 的 σ/相位/群延迟/settle 排行）；控制环最终选型是另一口径（在环评估，定稿 EMA α=0.3，见 `docs/z-phase1-sweep.md`）。两者不矛盾，别混用。

## 1. 跑测试（20 个新增测试 + 全量回归）

```bash
cd /home/ethan/FYP && python -m pytest tests/test_filter.py tests/test_compare_filters.py -v
```

预期：`31 passed`（ButterworthFilter 11 + OneEuroFilter 9 + 指标函数 11），全绿。

```bash
cd /home/ethan/FYP && python -m pytest
```

预期：`130 passed`。

## 2. 重新生成对比报告（核心成果）

```bash
cd /home/ethan/FYP && python scripts/compare_filters.py
```

预期：终端打印 14 行配置指标（EMA / 4 个 Butterworth / 9 个 OneEuro 的 |σ|、fftΔ%、3Hz 相位、群延迟、settle、动态 RMS）+ 最后一行 `推荐: OneEuro mc=0.5 b=0.03`（孤立指标口径，非控制环最终选型——见文档开头口径说明）；同时重写 `docs/filter-comparison.md` 和 `docs/assets/filter-comparison.png`。

## 3. 看报告和图

```bash
cat /home/ethan/FYP/docs/filter-comparison.md
```

```bash
xdg-open /home/ethan/FYP/docs/assets/filter-comparison.png
```

图有两个子图：左 = idle 数据 z 通道原始 vs 滤波（降噪效果），右 = 阶跃响应对比（滞后代价）。已知小毛病：子图标题中文显示为方框（matplotlib 默认字体无 CJK，deferred 修复项），曲线和数据不受影响。

## 4. 一分钟数字 sanity check（降噪立竿见影）

```bash
cd /home/ethan/FYP && python -c "import sys; sys.path[:0]=['src','scripts']; from compare_filters import load_csv, sigmas; from brushbot.filter import ButterworthFilter, OneEuroFilter; d=load_csv('delta_b_v0_20260724/20260724_142504_idle_r01.csv'); print('raw      |sigma| = %.2f uT' % sigmas(d['dB'])[3]); print('Butter8  |sigma| = %.2f uT' % sigmas(ButterworthFilter(8.0).update(d['dB']))[3]); print('OneEuro  |sigma| = %.2f uT' % sigmas(OneEuroFilter(0.5, 0.03).update(d['dB']))[3])"
```

预期：raw ≈ 6.9，Butter8 ≈ 3.4，OneEuro ≈ 2.7（µT）。

## 5. 验证回退警告（本次评审加的防呆）

```bash
cd /home/ethan/FYP && python scripts/compare_filters.py delta_b_v0_20260724/20260724_142504_idle_r01.csv --out /tmp/filter-idleonly.md
```

预期：终端出现 `警告: ...` （只有 idle、没有动态数据时，明确告知推荐仅按 σ 排序、选型门槛未生效），报告推荐段同样标注。

## 6. 装配态数据到位后（未来重跑）

```bash
cd /home/ethan/FYP && python scripts/compare_filters.py <装配态csv路径...> --out docs/filter-comparison.md
```

同一条命令、新数据，即完成重新选型。注意：`step_settle_ms` 已改用 10 µT 代表性阶跃幅值（原 deferred 项已完成），推荐已翻转为 OneEuro——此说明仅提醒装配态数据仍需重跑同一命令验证。
