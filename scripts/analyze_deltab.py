"""ΔB 数据集分析 (真机 MLX90393). 用法:

    python scripts/analyze_deltab.py delta_b_v0_20260724 [out.png]

做六件事(对应门禁实验, 见 docs/gate-experiments.md):
  A 数据完整性 —— 采样率/丢包/时间单调
  B 噪声底(E0) —— 静止段 σ_ΔB, 并给出 σ vs 带宽(噪声-带宽权衡)
  C 基线治理  —— 跨记录 B0 漂移 + 段内漂移 + 动作后回零残差
  D 幅度/信噪比 —— 各动作峰值与 SNR
  E 方向可分性(E4) —— 反向动作的响应方向夹角(圆用有向面积向量)
  F 三轴结构   —— |ΔBxy| vs |ΔBz|, 检验合成模型"轴向平"的假设
"""
import sys, os, json, glob
import numpy as np


def load(folder):
    """读文件夹 → [{action, t, B(N,3), win, B0, meta}]"""
    recs = []
    for csv in sorted(glob.glob(os.path.join(folder, "*.csv"))):
        jf = csv.replace(".csv", ".json")
        if not os.path.exists(jf):
            continue
        j = json.load(open(jf))
        if j.get("valid") is False:
            continue
        d = np.genfromtxt(csv, delimiter=",", names=True)
        b0 = j["baseline_B0_uT"]
        recs.append(dict(action=j["action"], t=d["t_s"],
                         B=np.c_[d["dBx_uT"], d["dBy_uT"], d["dBz_uT"]],
                         win=j.get("action_window_s"),
                         B0=np.array([b0["Bx_uT"], b0["By_uT"], b0["Bz_uT"]]),
                         meta=j, file=os.path.basename(csv)))
    return recs


def unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v * 0.0


def ang(u, v):
    return float(np.degrees(np.arccos(np.clip(np.dot(unit(u), unit(v)), -1, 1))))


def band_noise(x, fs, fcs):
    """σ vs 低通截止: 用 FFT 只保留 <fc 的分量再求 std → 噪声-带宽权衡曲线."""
    X = np.fft.rfft(x - x.mean())
    f = np.fft.rfftfreq(len(x), 1 / fs)
    out = []
    for fc in fcs:
        Y = X.copy(); Y[f > fc] = 0
        out.append(float(np.std(np.fft.irfft(Y, n=len(x)))))
    return np.array(out)


def analyze(folder, out_png="deltab_v0_analysis.png"):
    recs = load(folder)
    if not recs:
        print("没找到数据"); return
    idle = next((r for r in recs if r["action"] == "idle"), None)
    acts = [r for r in recs if r["action"] != "idle"]
    print("=" * 74)
    print("ΔB 数据集分析:", folder, " (%d 条有效记录)" % len(recs))
    print("=" * 74)

    # ---------- A 数据完整性 ----------
    print("\n[A] 数据完整性")
    print("  %-12s %6s %8s %9s %9s %s" % ("action", "N", "时长s", "均值Hz", "最大间隔ms", "时间单调"))
    for r in recs:
        dt = np.diff(r["t"])
        print("  %-12s %6d %8.2f %9.2f %9.2f %s" % (
            r["action"], len(r["t"]), r["t"][-1], 1 / dt.mean(), dt.max() * 1e3,
            "✅" if (dt > 0).all() else "❌有回退"))

    # ---------- B 噪声底 (E0) ----------
    print("\n[B] 噪声底 σ_ΔB  (E0 判据的一半; 另一半 S 需 E2 标定)")
    fs = 100.0
    if idle is not None:
        s = idle["B"].std(axis=0)
        print("  idle 全段(10s, 100Hz): σ = (%.2f, %.2f, %.2f) uT   |σ| = %.2f uT"
              % (*s, np.linalg.norm(s)))
        fcs = np.array([1, 2, 3, 5, 10, 20, 50])
        bn = np.array([band_noise(idle["B"][:, k], fs, fcs) for k in range(3)])
        print("  噪声-带宽权衡 (低通截止 → σ, uT):")
        print("     fc(Hz):  " + "".join("%8.0f" % f for f in fcs))
        for k, nm in enumerate("xyz"):
            print("     σ%s   :  " % nm + "".join("%8.2f" % v for v in bn[k]))
    # 各动作的动作前静止段, 交叉验证噪声
    print("  各记录动作前静止段 σ (交叉验证):")
    for r in acts:
        w = r["win"]; pre = r["B"][r["t"] < max(w["start"] - 0.5, 0.5)]
        if len(pre) > 50:
            s = pre.std(axis=0)
            print("     %-12s σ=(%.2f, %.2f, %.2f) uT  (N=%d)" % (r["action"], *s, len(pre)))

    # 由噪声反推 E2 需要达到的最低灵敏度 S (E0 判据: σ_z = σ_ΔB/S ≤ 1/5 × 分辨率)
    if idle is not None:
        s3 = np.array([band_noise(idle["B"][:, k], fs, [3.0])[0] for k in range(3)])
        n3 = float(np.linalg.norm(s3))
        print("  → 提按带宽 3Hz 内的噪声: σ=(%.2f, %.2f, %.2f) uT, |σ|=%.2f uT" % (*s3, n3))
        print("  → 反推 E2 的灵敏度门槛  S_min = 5·|σ| / 目标分辨率:")
        for res in (1.0, 0.5, 0.2):
            print("       目标提按分辨率 %.1f mm  →  S 必须 ≥ %5.1f uT/mm" % (res, 5 * n3 / res))
        print("     (这是硬件必须达到的指标; S 由 E2 实测, 达不到就得改触角/传感器几何)")

    # ---------- C 基线治理 ----------
    print("\n[C] 基线治理")
    B0s = np.array([r["B0"] for r in recs])
    print("  跨记录 B0 绝对值 (uT):")
    for r in recs:
        print("     %-12s (%.1f, %.1f, %.1f)" % (r["action"], *r["B0"]))
    print("  跨记录 B0 跨度: Δ = (%.1f, %.1f, %.1f) uT  ← 每次 Reset 重取, 会话间不可比"
          % tuple(B0s.max(axis=0) - B0s.min(axis=0)))
    if idle is not None:
        t = idle["t"]
        sl = [np.polyfit(t, idle["B"][:, k], 1)[0] for k in range(3)]
        print("  idle 段内漂移(线性斜率): (%.2f, %.2f, %.2f) uT/s → 10s 累计 (%.1f, %.1f, %.1f) uT"
              % (*sl, *(np.array(sl) * 10)))
    print("  动作后回零残差 (动作结束后 1s 起的均值, 应接近 0):")
    for r in acts:
        w = r["win"]; post = r["B"][r["t"] > w["end"] + 1.0]
        if len(post) > 30:
            m = post.mean(axis=0)
            print("     %-12s (%.1f, %.1f, %.1f) uT   |·|=%.1f" % (r["action"], *m, np.linalg.norm(m)))

    # ---------- D 幅度 / 信噪比 ----------
    print("\n[D] 动作幅度与信噪比")
    sig_noise = np.linalg.norm(idle["B"].std(axis=0)) if idle is not None else np.nan
    print("  %-12s %10s %10s %10s %8s" % ("action", "|ΔB|peak", "|ΔBxy|peak", "|ΔBz|peak", "SNR"))
    for r in acts:
        w = r["win"]; m = (r["t"] >= w["start"]) & (r["t"] <= w["end"]); Bw = r["B"][m]
        pk = np.linalg.norm(Bw, axis=1).max()
        pxy = np.hypot(Bw[:, 0], Bw[:, 1]).max(); pz = np.abs(Bw[:, 2]).max()
        print("  %-12s %10.1f %10.1f %10.1f %8.0fx" % (r["action"], pk, pxy, pz, pk / sig_noise))

    # ---------- E 方向可分性 (E4) ----------
    print("\n[E] 方向可分性 (E4 关心的量)")

    def act_win(r):
        w = r["win"]; m = (r["t"] >= w["start"]) & (r["t"] <= w["end"])
        return r["B"][m]

    def mean_dir(r):
        """动作平均响应方向: 对幅值加权(大幅值样本更代表动作方向)."""
        Bw = act_win(r); wgt = np.linalg.norm(Bw, axis=1)
        return unit((Bw * wgt[:, None]).sum(axis=0))

    def area_vec(r):
        """有向面积向量 0.5*Σ(r_i × r_i+1): 环路的法向+绕向, 用于圆."""
        Bw = act_win(r)
        return 0.5 * np.cross(Bw[:-1], Bw[1:]).sum(axis=0)

    by = {r["action"]: r for r in acts}
    for a, b, how in [("line_lr", "line_rl", "mean"), ("circle_cw", "circle_ccw", "area")]:
        if a in by and b in by:
            if how == "mean":
                u, v = mean_dir(by[a]), mean_dir(by[b])
                lbl = "平均响应方向"
            else:
                u, v = unit(area_vec(by[a])), unit(area_vec(by[b]))
                lbl = "有向面积向量(环路法向)"
            th = ang(u, v)
            print("  %s vs %s  [%s]" % (a, b, lbl))
            print("     u=(%+.3f,%+.3f,%+.3f)  v=(%+.3f,%+.3f,%+.3f)" % (*u, *v))
            print("     夹角 = %.1f°   点积 = %.3f   → %s" % (
                th, float(np.dot(u, v)),
                "反向, 可分 ✅" if th > 150 else ("可分" if th > 60 else "⚠️ 难分")))
    # 不同动作类型之间(横 vs 圆)是否也可分
    print("  跨类型夹角(平均响应方向):")
    ks = [k for k in ["line_lr", "line_rl", "circle_cw", "circle_ccw"] if k in by]
    for i in range(len(ks)):
        for jx in range(i + 1, len(ks)):
            print("     %-11s vs %-11s = %6.1f°" % (ks[i], ks[jx], ang(mean_dir(by[ks[i]]), mean_dir(by[ks[jx]]))))

    # ---------- F 三轴结构 (检验合成模型) ----------
    print("\n[F] 三轴结构 —— 检验合成模型的'面内变、轴向平'假设")
    print("  %-12s %10s %10s %10s" % ("action", "std|xy分量|", "std ΔBz", "ΔBz/ΔBxy"))
    for r in acts:
        Bw = act_win(r)
        sxy = np.linalg.norm(Bw[:, :2].std(axis=0)); sz = Bw[:, 2].std()
        print("  %-12s %10.1f %10.1f %10.2f" % (r["action"], sxy, sz, sz / sxy))
    print("  → 若 ΔBz/ΔBxy 接近或大于 1, 说明轴向分量同样携带大量信息,")
    print("    合成模型里'ΔBz 基本平'的结构在真实自由手动作下 **不成立**。")

    _figure(recs, idle, acts, act_win, mean_dir, area_vec, out_png)
    print("\n图 → %s" % out_png)
    return recs


def _figure(recs, idle, acts, act_win, mean_dir, area_vec, out_png):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    n = len(acts)
    fig = plt.figure(figsize=(16, 4.2 * (n + 1) / 2 + 4))
    gs = fig.add_gridspec(3, 4, hspace=0.42, wspace=0.30)

    # 行1: 各动作时序
    for i, r in enumerate(acts[:4]):
        ax = fig.add_subplot(gs[0, i])
        t, B = r["t"], r["B"]
        ax.plot(t, B[:, 0], lw=0.7, label="dBx")
        ax.plot(t, B[:, 1], lw=0.7, label="dBy")
        ax.plot(t, B[:, 2], lw=0.8, color="k", label="dBz")
        w = r["win"]; ax.axvspan(w["start"], w["end"], color="orange", alpha=0.15)
        ax.set_title(r["action"], fontsize=10); ax.set_xlabel("t (s)")
        if i == 0:
            ax.set_ylabel("ΔB (uT)"); ax.legend(fontsize=6)
        ax.grid(alpha=0.3)

    # 行2-1: 噪声底
    ax = fig.add_subplot(gs[1, 0])
    if idle is not None:
        for k, nm in enumerate("xyz"):
            ax.plot(idle["t"], idle["B"][:, k], lw=0.6, label="dB%s" % nm)
        s = idle["B"].std(axis=0)
        ax.set_title("idle noise floor\nsigma=(%.1f,%.1f,%.1f) uT" % tuple(s), fontsize=9)
        ax.set_xlabel("t (s)"); ax.set_ylabel("ΔB (uT)"); ax.legend(fontsize=6); ax.grid(alpha=0.3)

    # 行2-2: 噪声 vs 带宽
    ax = fig.add_subplot(gs[1, 1])
    if idle is not None:
        fcs = np.array([1, 2, 3, 5, 10, 20, 50])
        for k, nm in enumerate("xyz"):
            ax.plot(fcs, band_noise(idle["B"][:, k], 100.0, fcs), "-o", ms=3, label="sigma_%s" % nm)
        ax.set_xscale("log"); ax.set_xlabel("low-pass cutoff (Hz)"); ax.set_ylabel("sigma (uT)")
        ax.set_title("noise vs bandwidth (E0)", fontsize=9); ax.legend(fontsize=6); ax.grid(alpha=0.3)

    # 行2-3: 幅度对比
    ax = fig.add_subplot(gs[1, 2])
    names = [r["action"] for r in acts]
    pk = [np.linalg.norm(act_win(r), axis=1).max() for r in acts]
    ax.bar(range(len(names)), pk, color="steelblue")
    if idle is not None:
        ax.axhline(np.linalg.norm(idle["B"].std(axis=0)), color="crimson", ls="--", label="noise |sigma|")
        ax.legend(fontsize=6)
    ax.set_xticks(range(len(names))); ax.set_xticklabels(names, rotation=30, ha="right", fontsize=7)
    ax.set_ylabel("|ΔB| peak (uT)"); ax.set_title("signal vs noise", fontsize=9); ax.grid(alpha=0.3, axis="y")

    # 行2-4: 跨记录 B0
    ax = fig.add_subplot(gs[1, 3])
    B0s = np.array([r["B0"] for r in recs])
    for k, nm in enumerate("xyz"):
        ax.plot(range(len(recs)), B0s[:, k] - B0s[:, k].mean(), "-o", ms=4, label="B0%s - mean" % nm)
    ax.set_xticks(range(len(recs))); ax.set_xticklabels([r["action"] for r in recs], rotation=30, ha="right", fontsize=7)
    ax.set_ylabel("uT"); ax.set_title("baseline B0 drift across runs", fontsize=9)
    ax.legend(fontsize=6); ax.grid(alpha=0.3)

    # 行3: 相图 (xy / xz) + 方向
    by = {r["action"]: r for r in acts}
    for col, (pa, pb, ttl) in enumerate([("line_lr", "line_rl", "lines"), ("circle_cw", "circle_ccw", "circles")]):
        ax = fig.add_subplot(gs[2, col * 2])
        for nm, c in [(pa, "tab:blue"), (pb, "tab:red")]:
            if nm in by:
                Bw = act_win(by[nm]); ax.plot(Bw[:, 0], Bw[:, 1], lw=0.8, color=c, label=nm)
        ax.set_xlabel("dBx (uT)"); ax.set_ylabel("dBy (uT)"); ax.set_title("%s: xy phase" % ttl, fontsize=9)
        ax.legend(fontsize=6); ax.grid(alpha=0.3); ax.set_aspect("equal", adjustable="datalim")
        ax = fig.add_subplot(gs[2, col * 2 + 1])
        for nm, c in [(pa, "tab:blue"), (pb, "tab:red")]:
            if nm in by:
                Bw = act_win(by[nm]); ax.plot(Bw[:, 0], Bw[:, 2], lw=0.8, color=c, label=nm)
        ax.set_xlabel("dBx (uT)"); ax.set_ylabel("dBz (uT)"); ax.set_title("%s: xz phase" % ttl, fontsize=9)
        ax.legend(fontsize=6); ax.grid(alpha=0.3)

    fig.suptitle("Delta-B V0 dataset analysis (MLX90393, 100 Hz, real hardware)", fontsize=13)
    fig.savefig(out_png, dpi=110, bbox_inches="tight")


if __name__ == "__main__":
    folder = sys.argv[1] if len(sys.argv) > 1 else "delta_b_v0_20260724"
    out = sys.argv[2] if len(sys.argv) > 2 else "deltab_v0_analysis.png"
    analyze(folder, out)
