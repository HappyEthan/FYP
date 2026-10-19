import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import MultipleLocator


ROOT = Path(__file__).resolve().parents[1] / "raw"
RUNS = {
    "a8a59a": ROOT / "16-31-50_宽过渡_P2_修正0p25mm_速度2_加速度50_第1次",
    "10f17a": ROOT / "已清理的原始记录",
}

# Historical comparison only: raw 10f17a was removed by approved 2026-09-25
# curation. The saved PNG and compact summary remain, but this plot cannot be
# regenerated from the surviving runs.
if not RUNS["10f17a"].is_dir():
    raise SystemExit(
        "Original comparison run was retired; see ../已清理实验摘要.json "
        "and ../修正上限精选/ for current plots")


def read_run(path):
    rows = [json.loads(line) for line in (path / "control.jsonl").read_text().splitlines()]
    rows = [row for row in rows if row["phase"] == "measure_00"]
    assert len(rows) == 1011
    return {
        "x": np.array([(row["x_cmd_m"] + 0.2) * 1000 for row in rows]),
        "target": np.array([row["a_ref_uT"] for row in rows]),
        "measured": np.array([row["a_control_uT"] for row in rows]),
        "correction": np.array([row["depth_fb_m"] * 1000 for row in rows]),
    }


runs = {name: read_run(path) for name, path in RUNS.items()}
assert np.allclose(runs["a8a59a"]["x"], runs["10f17a"]["x"])
assert np.allclose(runs["a8a59a"]["target"], runs["10f17a"]["target"])
x = runs["a8a59a"]["x"]

plt.rcParams.update({
    "font.family": "Noto Sans CJK SC",
    "font.size": 11,
    "axes.spines.top": False,
    "axes.spines.right": False,
})
blue, orange, gray = "#2864a0", "#d66c2c", "#4d5560"
fig, axes = plt.subplots(
    3, 1, figsize=(12.4, 9.3), sharex=True,
    gridspec_kw={"height_ratios": [2.15, 1.3, 1.15], "hspace": 0.2},
)
fig.text(0.08, 0.975, "同一 P 增益下的两笔磁触觉跟随对比", ha="left", va="top", fontsize=18, fontweight="bold")
fig.text(0.08, 0.924, "brush2 · 04_smooth_levels_wide_transitions · kp = 2.0 · 书写段 1011 拍 / 笔", ha="left", color=gray, fontsize=10.5)

top, middle, bottom = axes
top.plot(x, runs["a8a59a"]["target"], color=gray, lw=2, ls=(0, (4, 3)), label="目标磁响应")
top.plot(x, runs["a8a59a"]["measured"], color=blue, lw=1.75,
         label="a8a59a  ±0.25 mm / 2 mm/s / 50 mm/s²")
top.plot(x, runs["10f17a"]["measured"], color=orange, lw=1.75,
         label="10f17a  ±0.30 mm / 4 mm/s / 60 mm/s²")
top.set_ylabel("磁响应 |ΔBxy| (µT)")
top.set_ylim(0, 410)
top.legend(loc="upper left", frameon=False, fontsize=9.2)
top.text(194, 370, "100–150 mm 段\n10f17a 平均高于目标 153 µT", ha="right", va="top",
         color=orange, fontsize=10, bbox=dict(facecolor="white", edgecolor="none", alpha=0.8, pad=2))

for name, color in (("a8a59a", blue), ("10f17a", orange)):
    run = runs[name]
    middle.plot(x, run["measured"] - run["target"], color=color, lw=1.55)
    bottom.plot(x, run["correction"], color=color, lw=1.55)
middle.axhline(0, color=gray, lw=1, ls=(0, (3, 3)))
middle.set_ylabel("实测 − 目标 (µT)")
middle.set_ylim(-100, 200)
middle.text(4, 173, "全段 MAE  19.37 µT  /  58.00 µT", color=gray, fontsize=10)
bottom.axhline(0, color=gray, lw=1, ls=(0, (3, 3)))
bottom.set_ylabel("反馈修正压深 (mm)")
bottom.set_xlabel("沿 +X 的路径累计距离 (mm)；绝对 X 命令 = 距离 − 200 mm")
bottom.set_ylim(-0.36, 0.36)
bottom.yaxis.set_major_locator(MultipleLocator(0.15))
bottom.xaxis.set_major_locator(MultipleLocator(25))

for ax in axes:
    ax.axvspan(100, 150, color="#f1d5ba", alpha=0.45, zorder=0)
    ax.set_xlim(0, 200)
    ax.grid(axis="y", color="#dfe3e8", lw=0.75)
    ax.tick_params(axis="both", length=0, pad=6)
top.text(125, 405, "异常区间", ha="center", va="top", color="#9e5728", fontsize=9)
fig.text(0.08, 0.025,
         "注：两笔同时改变了修正幅度、速度和加速度上限；图示为观测差异，不能归因于单一参数。Z 为命令值，无逐拍实际 TCP 位姿。",
         ha="left", color=gray, fontsize=9)
fig.subplots_adjust(left=0.095, right=0.975, top=0.875, bottom=0.13)
fig.savefig(Path(__file__).with_name("a8a59a-vs-10f17a.png"), dpi=180, facecolor="white")
