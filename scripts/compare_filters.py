#!/usr/bin/env python3
"""滤波器定量对比: EMA / Butterworth / One Euro → 选型报告.

用法 (单行):
    python scripts/compare_filters.py
    python scripts/compare_filters.py path/to/*.csv --out docs/filter-comparison.md

默认跑 delta_b_v0_20260724/ 全部数据. 装配态 E0 数据到位后, 用装配态 CSV
重跑同一命令即可重新选型 (spec §4).
"""
import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from brushbot.filter import ButterworthFilter, OneEuroFilter  # noqa: E402
from brushbot.monitor.core import EMA                          # noqa: E402

FS = 100.0        # 采样率 Hz
F_SIG = 3.0       # 目标信号带宽 Hz (提按动作)
REF_FC = 3.0      # 动态跟踪参考: FFT 零相位截断频率 Hz
SETTLE_TOL = 0.05
STEP_AMP = 10.0   # 阶跃幅值 µT: 提按 ΔB 代表区间 10–30 µT 的下界 (非线性滤波器
                  # settle 随幅值减小而变长, 下界=区间内最坏情形; 取中值/上界会让
                  # 恰好压线的激进配置胜出, 推荐随幅值漂移). 1 µT 属小信号, 不代表提按.


def load_csv(path):
    """ΔB CSV → dict(name, t, dB). 列: t_us,t_s,dBx_uT,dBy_uT,dBz_uT."""
    d = np.genfromtxt(path, delimiter=",", names=True)
    dB = np.column_stack([d["dBx_uT"], d["dBy_uT"], d["dBz_uT"]])
    return {"name": Path(path).stem, "t": d["t_s"], "dB": dB}


def fft_lowpass(x, fc, fs=FS):
    """FFT 域理想截断 (零相位, 离线参考用). x: (N,3)."""
    X = np.fft.rfft(x, axis=0)
    f = np.fft.rfftfreq(len(x), d=1.0 / fs)
    X[f > fc] = 0.0
    return np.fft.irfft(X, n=len(x), axis=0)


def sigmas(x):
    """(N,3) → (σx, σy, σz, |σ|), 关于各通道均值的标准差."""
    s = x.std(axis=0)
    return float(s[0]), float(s[1]), float(s[2]), float(np.linalg.norm(s))


def ema_freq_response(alpha, f, fs=FS):
    """一阶 EMA 频响 H = α / (1 - (1-α)·z⁻¹)."""
    z1 = np.exp(-2j * np.pi * np.asarray(f, dtype=float) / fs)
    return alpha / (1.0 - (1.0 - alpha) * z1)


def phase_lag_deg(h):
    """复频响 → 相位滞后 (度, 正值=滞后)."""
    return float(-np.degrees(np.angle(h)))


def group_delay_ms(freq_fn, f0=F_SIG, df=0.01):
    """群延迟 τ_g = -dφ/dω 数值微分 @ f0, 返回 ms."""
    phi = np.unwrap(np.angle(freq_fn(np.array([f0 - df, f0 + df]))))
    return float(-(phi[1] - phi[0]) / (2.0 * np.pi * 2.0 * df) * 1000.0)


def f3db(freq_fn):
    """数值求 -3dB 频率 (Hz)."""
    f = np.linspace(0.05, FS / 2.0 - 0.5, 4000)
    mag = np.abs(freq_fn(f))
    idx = np.nonzero(mag <= 1.0 / np.sqrt(2.0))[0]
    return float(f[idx[0]]) if len(idx) else float("nan")


def step_settle_ms(make_filter, tol=SETTLE_TOL, n=500, amp=STEP_AMP):
    """阶跃响应进入并保持 ±tol·amp 所需时间 (ms). 冷启动于 0, 样本 1 阶跃到 amp.

    amp 影响非线性滤波器 (OneEuro 自适应截止) 的结果, 线性滤波器与 amp 无关."""
    x = np.zeros((n, 3))
    x[1:] = amp
    y = make_filter().update(x)[:, 0]
    bad = np.abs(y - amp) > tol * amp
    last = int(np.max(np.nonzero(bad)[0])) if bad.any() else 0
    return last * 1000.0 / FS


def dynamic_rms(make_filter, dB):
    """滤波输出 vs FFT 零相位参考 (REF_FC) 的逐元素 RMS (µT)."""
    y = make_filter().update(dB)
    ref = fft_lowpass(dB, REF_FC)
    return float(np.sqrt(np.mean((y - ref) ** 2)))


def build_configs():
    """全部对比配置. fc_ref: σ 对照用的 FFT 截断频率."""
    cfgs = []
    for a in (0.05, 0.1, 0.2, 0.3, 0.5):
        cfgs.append({"label": "EMA a=%g" % a,
                     "make": (lambda a=a: EMA(a)),
                     "freq": (lambda f, a=a: ema_freq_response(a, f)),
                     "fc_ref": f3db(lambda f, a=a: ema_freq_response(a, f))})
    for fc in (5.0, 8.0, 10.0, 12.0):
        cfgs.append({"label": "Butter fc=%g" % fc,
                     "make": (lambda fc=fc: ButterworthFilter(fc)),
                     "freq": ButterworthFilter(fc).freq_response,
                     "fc_ref": fc})
    for mc in (0.5, 1.0, 2.0):
        for beta in (0.01, 0.03, 0.1):
            a_slow = OneEuroFilter.smoothing_alpha(mc, 1.0 / FS)
            cfgs.append({"label": "OneEuro mc=%g b=%g" % (mc, beta),
                         "make": (lambda mc=mc, b=beta: OneEuroFilter(mc, b)),
                         "freq": (lambda f, a=a_slow: ema_freq_response(a, f)),
                         "fc_ref": mc})
    return cfgs


def evaluate(cfg, idle_dB, dyn_runs):
    """单配置 → 指标行 dict."""
    sx, sy, sz, sn = sigmas(cfg["make"]().update(idle_dB))
    rx, ry, rz, rn = sigmas(fft_lowpass(idle_dB, cfg["fc_ref"]))
    dyn = [dynamic_rms(cfg["make"], r["dB"]) for r in dyn_runs]
    return {
        "label": cfg["label"], "fc_ref": cfg["fc_ref"],
        "sigma": (sx, sy, sz), "sigma_norm": sn,
        "fft_sigma_norm": rn, "fft_diff_pct": (sn - rn) / rn * 100.0,
        "phase3_deg": phase_lag_deg(cfg["freq"](F_SIG)),
        "gd_ms": group_delay_ms(cfg["freq"]),
        "settle_ms": step_settle_ms(cfg["make"]),
        "dyn_rms": float(np.mean(dyn)) if dyn else float("nan"),
    }


def recommend(rows):
    """选型: 动态 RMS 在最优 1.25 倍内且阶跃 ≤100 ms 者中, 取 idle |σ| 最小.

    若没有有效动态数据 (全部 dyn_rms=NaN, 如仅提供 idle CSV) 或没有配置通过
    动态 RMS/settle 门槛, 回退为在全表按 idle |σ| 排序取最小者. 返回 dict
    附加 `fallback` 键: 正常路径为 None, 回退路径为原因说明字符串, 供调用方
    (main/write_report) 把这一事实暴露出来, 而不是静默给出一个看似经过门槛
    筛选、实际未经筛选的推荐."""
    valid = [r for r in rows if np.isfinite(r["dyn_rms"])]
    if not valid:
        fallback = "无有效动态 RMS 数据 (全部 dyn_rms=NaN), 未按动态门槛筛选, 仅按 idle |σ| 排序"
        ok = []
    else:
        best_rms = min(r["dyn_rms"] for r in valid)
        ok = [r for r in valid
              if r["dyn_rms"] <= 1.25 * best_rms and r["settle_ms"] <= 100.0]
        fallback = None if ok else "无配置同时满足动态 RMS≤最优×1.25 且阶跃≤100ms, 仅按 idle |σ| 排序"
    rec = dict(min(ok or rows, key=lambda r: r["sigma_norm"]))
    rec["fallback"] = fallback
    return rec


def make_figure(cfgs_sel, idle, out_png):
    """图: idle z 通道滤波对比 + 阶跃响应."""
    plt = _plt()

    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    t = idle["t"][:500]
    axes[0].plot(t, idle["dB"][:500, 2], color="0.8", lw=0.6, label="raw z")
    for cfg in cfgs_sel:
        axes[0].plot(t, cfg["make"]().update(idle["dB"][:500])[:, 2],
                     lw=1.0, label=cfg["label"])
    axes[0].set(xlabel="t (s)", ylabel="ΔBz (µT)", title="Idle 降噪对比 (z)")
    axes[0].legend(fontsize=8)
    n = 100
    x = np.zeros((n, 3))
    x[1:] = STEP_AMP
    ts = np.arange(n) * 1000.0 / FS
    for cfg in cfgs_sel:
        axes[1].plot(ts, cfg["make"]().update(x)[:, 0] / STEP_AMP,
                     lw=1.0, label=cfg["label"])
    axes[1].axhspan(0.95, 1.05, color="0.9")
    axes[1].set(xlabel="t (ms)", ylabel="step response (norm.)",
                title="阶跃响应 (%g µT, 归一化)" % STEP_AMP)
    axes[1].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_png, dpi=120)


def _plt():
    """Agg 后端 + CJK 字体的 matplotlib.pyplot (中文标签不出方框)."""
    import matplotlib
    matplotlib.use("Agg")
    matplotlib.rcParams["font.sans-serif"] = [
        "Noto Sans CJK SC", "Noto Sans CJK HK", "Noto Sans CJK JP", "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False
    import matplotlib.pyplot as plt
    return plt


def make_pareto(rows, out_png):
    """噪声-滞后 Pareto 散点: x=3Hz 相位滞后°, y=idle |σ| µT. 左下=最优方向.

    颜色取 Okabe-Ito 无障碍色板; OneEuro 用空心标记 + 形状双编码,
    因其相位为慢态线性化等效值, 与线性滤波器不可直接比相位.
    """
    plt = _plt()

    families = [  # (前缀, 颜色, 标记, 实心)
        ("EMA", "#0072B2", "o", True),
        ("Butter", "#E69F00", "s", True),
        ("OneEuro", "#009E73", "^", False),
    ]
    fig, ax = plt.subplots(figsize=(7.5, 5.5))
    for prefix, color, marker, filled in families:
        pts = [r for r in rows if r["label"].startswith(prefix)]
        xs = [r["phase3_deg"] for r in pts]
        ys = [r["sigma_norm"] for r in pts]
        ax.scatter(xs, ys, s=70, marker=marker, zorder=3,
                   facecolors=color if filled else "none",
                   edgecolors=color, linewidths=1.6,
                   label=prefix + ("" if filled else " (慢态等效相位)"))
        for r in pts:  # 直接标注参数, 文字用中性墨色而非系列色
            ax.annotate(r["label"].replace(prefix, "").strip(),
                        (r["phase3_deg"], r["sigma_norm"]),
                        textcoords="offset points", xytext=(6, 4),
                        fontsize=7.5, color="#444444")
    ax.set(xlabel="3 Hz 相位滞后 (°)", ylabel="idle |σ| (µT)",
           title="噪声-滞后权衡 (左下为 Pareto 最优方向)")
    ax.margins(x=0.14, y=0.08)   # 给右缘的直接标注留位置
    ax.grid(True, color="0.9", lw=0.6, zorder=0)
    ax.legend(fontsize=8, loc="upper right")
    fig.tight_layout()
    fig.savefig(out_png, dpi=120)


def write_report(rows, rec, runs, out_md, out_png):
    lines = [
        "# 滤波器对比报告 (脚本生成)",
        "",
        "> 生成命令: `python scripts/compare_filters.py`",
        "> 数据: %s" % ", ".join(r["name"] for r in runs),
        "> 装配态 E0 数据到位后, 用装配态 CSV 重跑同一命令即可重新选型.",
        "",
        "## 对比矩阵",
        "",
        "| 配置 | σx/σy/σz (µT) | \\|σ\\| (µT) | FFT 对照差 % | 3Hz 相位滞后° | 群延迟 ms | 阶跃(" + "%g" % STEP_AMP + "uT)±5% ms | 动态 RMS µT |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            "| %s | %.2f/%.2f/%.2f | %.2f | %+.1f | %.1f | %.1f | %.0f | %.2f |"
            % (r["label"], *r["sigma"], r["sigma_norm"], r["fft_diff_pct"],
               r["phase3_deg"], r["gd_ms"], r["settle_ms"], r["dyn_rms"]))
    lines += [
        "",
        "注: OneEuro 的相位/群延迟为慢态线性化等效值 (cutoff=min_cutoff), 快态滞后由动态 RMS 体现;",
        "FFT 对照差 % 的 <10% 验收判据适用于 2 阶 Butterworth (spec §7), 一阶滤波器 ENBW 更宽, 差异天然更大;",
        "阶跃 settle 用 %g µT 阶跃测量 = 提按 ΔB 代表区间 10–30 µT 的下界 (区间内最坏情形):" % STEP_AMP,
        "OneEuro 为非线性滤波器, settle 随幅值减小而变长 (实测 mc=0.5 b=0.03: 1 µT→380 ms, 10 µT→100 ms,",
        "30 µT→50 ms); 用中值/上界评会让恰好压 100ms 线的激进配置胜出, 推荐随幅值漂移 (10→30 µT 扫描",
        "实测: mc=0.5 b=0.03 全程通过, mc=2 b=0.01 / mc=0.5 b=0.01 仅在 ≥20/30 µT 通过).",
        "线性滤波器 (EMA/Butterworth) settle 与幅值无关. 1 µT 属小信号口径, 不代表提按动作.",
        "",
        "## 推荐",
        "",
    ]
    if rec.get("fallback"):
        lines.append(
            "**%s** — ⚠️ 无配置通过动态 RMS/settle 门槛（或无动态数据），"
            "本推荐仅按 idle |σ| 排序，不代表滞后可接受 (%s)." % (rec["label"], rec["fallback"]))
    else:
        lines.append(
            "**%s** — 选型规则: 动态 RMS ≤ 最优×1.25 且阶跃 ≤100 ms 者中取 idle |σ| 最小." % rec["label"])
    lines += [
        "",
        "handoff §2.5 四问 (以推荐配置回答):",
        "",
        "1. 3 Hz 相位滞后: **%.1f°**%s" % (
            rec["phase3_deg"], " (慢态等效)" if "OneEuro" in rec["label"] else ""),
        "2. 噪声: |σ| 从全带宽 6.94 µT → **%.2f µT**" % rec["sigma_norm"],
        "3. 等效 Z 噪声: σ_z = σ_filtered/S = %.2f/S mm (S 待装配态 E2 标定, µT/mm)" % rec["sigma"][2],
        "4. 滤波器延迟: 群延迟 **%.1f ms** @ 3 Hz (延迟预算 ≲10 ms)" % rec["gd_ms"],
        "",
        "## 已知边界 (滤波器无法解决)",
        "",
        "- 50 Hz 工频位于 Nyquist, 折叠回 DC — 交固件 ODR/硬件层 (handoff §4).",
        "- 机械臂运动低频磁场漂移与提按信号频谱重叠 — 交差分测量方案 (deltaB-control.md §8.1).",
        "- 裸态数据为乐观下界, 装配态 E0 复测后须重跑本报告.",
        "",
        "![对比图](assets/filter-comparison.png)",
        "",
        "![噪声-滞后 Pareto](assets/filter-pareto.png)",
        "",
        "散点图读法: 左下角为 Pareto 最优方向; EMA α 扫描与 Butterworth fc 扫描各成一条权衡曲线,",
        "同等相位滞后下更低的点降噪更强. OneEuro (空心三角) 的横坐标是慢态线性化等效值,",
        "不能与线性滤波器直接比相位——其真实动态滞后见对比矩阵的动态 RMS 列.",
        "",
    ]
    Path(out_md).write_text("\n".join(lines), encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csvs", nargs="*", help="ΔB CSV; 默认 delta_b_v0_20260724/ 全部")
    ap.add_argument("--out", default=str(ROOT / "docs" / "filter-comparison.md"))
    args = ap.parse_args(argv)

    paths = [Path(p) for p in args.csvs] or sorted(
        (ROOT / "delta_b_v0_20260724").glob("*.csv"))
    runs = [load_csv(p) for p in paths]
    idle_runs = [r for r in runs if "idle" in r["name"]]
    dyn_runs = [r for r in runs if "idle" not in r["name"]]
    if not idle_runs:
        sys.exit("错误: 输入中没有 idle 数据 (文件名含 'idle'), 无法算降噪指标")
    idle_dB = np.vstack([r["dB"] for r in idle_runs])

    cfgs = build_configs()
    rows = [evaluate(c, idle_dB, dyn_runs) for c in cfgs]
    rec = recommend(rows)

    out_md = Path(args.out)
    out_png = out_md.parent / "assets" / "filter-comparison.png"
    out_png.parent.mkdir(parents=True, exist_ok=True)
    sel_labels = {rec["label"], "EMA a=0.3", "Butter fc=8"}
    make_figure([c for c in cfgs if c["label"] in sel_labels],
                idle_runs[0], out_png)
    make_pareto(rows, out_md.parent / "assets" / "filter-pareto.png")
    write_report(rows, rec, runs, out_md, out_png)

    for r in rows:
        print("%-22s |σ|=%.2f fftΔ=%+.1f%% φ3=%.1f° gd=%.1fms settle=%.0fms rms=%.2f"
              % (r["label"], r["sigma_norm"], r["fft_diff_pct"], r["phase3_deg"],
                 r["gd_ms"], r["settle_ms"], r["dyn_rms"]))
    if rec.get("fallback"):
        print("警告:", rec["fallback"])
    print("推荐:", rec["label"], "→ 报告:", out_md)


if __name__ == "__main__":
    main()
