"""任务2 · 压/拖可分性量化 → 喂 E4 判据.

问题(deltaB-control.md §5.2 前提② / E4): 提按(压)和拖拽都表现为触角侧向弯,
都落在磁场 XY 面. 投影法能否把"提按量"从"拖拽污染"里分出来?

做法(纯 Python, 用 P0 解析模型分别下纯压/纯拖指令, 小形变下线性叠加):
- 压: 在固定的"屈曲方位" φp 弯, 幅值=提按量; 其 ΔB 方向 = 标定方向 up.
- 拖: 在方位 φd 弯(书写方向); 与压的 ΔB 夹角 θ.
- 投影法: 把测得 ΔB 投到 up 上估提按 → 拖拽泄漏 = cos(θ)·(拖/压).
- 结论: 投影法要 θ→90°(近正交)才干净; 噪声/迟滞进一步抬高误差底.

产出: 一张"提按估计误差 vs θ(+噪声)"图 + 打印 E4 判据阈值.
"""
import numpy as np
from brushbot.tactile.antenna_model import bent_centerline, sensor_B

L, N, MAG, SENS = 24.0, 40, (0.4, 1.0), (0.0, 0.0, 3.0)
B0 = sensor_B(*bent_centerline(0.0, L, N, 0.0), MAG, 1.0, SENS)
B0MAG = np.linalg.norm(B0)


def dB_bend(theta_deg, azim_deg):
    """纯弯(azimuth 方位, theta 幅值)相对静止的 ΔB(三轴)."""
    return sensor_B(*bent_centerline(np.radians(theta_deg), L, N, azim_deg), MAG, 1.0, SENS) - B0


def unit_dir(azim_deg, probe=6.0):
    v = dB_bend(probe, azim_deg)
    return v / np.linalg.norm(v)


def study(out_png, press_th=25.0, drag_th=25.0, press_azim=0.0,
          drag_azims=np.linspace(0, 90, 19), noise_fracs=(0.0, 0.1, 0.3),
          trials=400, seed=0):
    """press_th/drag_th: 压/拖的弯幅(deg). noise_fracs: 噪声(占压信号幅值的比例).
    返回并画: 提按估计误差(占真值%) vs θ(压拖在磁空间夹角), 不同噪声。"""
    rng = np.random.default_rng(seed)
    up = unit_dir(press_azim)

    # 压标定: 幅值 -> 沿 up 的投影(单调), 供反演
    cal_th = np.linspace(1.0, 55.0, 40)
    cal_proj = np.array([dB_bend(t, press_azim) @ up for t in cal_th])
    invert = lambda proj: np.interp(proj, cal_proj, cal_th)  # 投影 -> 提按幅值

    press_vec = dB_bend(press_th, press_azim)                # 真提按贡献
    press_sig = np.linalg.norm(press_vec)                    # 压信号幅值(定噪声尺度)

    thetas, err_mean, err_std = [], {f: [] for f in noise_fracs}, {f: [] for f in noise_fracs}
    for az in drag_azims:
        ud = unit_dir(az)
        theta = np.degrees(np.arccos(np.clip(up @ ud, -1, 1)))
        thetas.append(theta)
        total = press_vec + dB_bend(drag_th, az)             # 压+拖(线性叠加)
        for f in noise_fracs:
            sigma = f * press_sig
            noise = rng.normal(0, sigma, size=(trials, 3))
            est = invert((total + noise) @ up)               # 投影估计的提按幅值
            e = (est - press_th) / press_th * 100.0          # 相对真提按 %
            err_mean[f].append(np.mean(e)); err_std[f].append(np.std(e))
    thetas = np.array(thetas)

    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 4.6))
    # A: 磁空间几何(压 vs 两个拖方位)
    for az, c in [(15, "#e67"), (45, "#6a6"), (80, "#48c")]:
        ud = unit_dir(az); th = np.degrees(np.arccos(np.clip(up @ ud, -1, 1)))
        a1.plot([0, ud[0]], [0, ud[1]], c, lw=2.5, label=f"drag θ={th:.0f}°")
    a1.plot([0, up[0]], [0, up[1]], "k", lw=3, label="press (up)")
    a1.set_aspect("equal"); a1.axhline(0, color="#ddd"); a1.axvline(0, color="#ddd")
    a1.set_title("(1) ΔB direction: press vs drag (Bx-By)"); a1.set_xlabel("dBx"); a1.set_ylabel("dBy")
    a1.legend(fontsize=8)
    # B: 误差 vs θ
    for f in noise_fracs:
        m = np.array(err_mean[f]); s = np.array(err_std[f])
        lab = f"noise {int(f*100)}%" if f else "no noise"
        a2.plot(thetas, m, "-o", ms=3, label=lab)
        if f: a2.fill_between(thetas, m - s, m + s, alpha=0.15)
    a2.axhline(10, ls="--", color="gray"); a2.axhline(-10, ls="--", color="gray")
    a2.text(2, 12, "+/-10% target", color="gray", fontsize=8)
    a2.set_xlabel("theta = angle(press, drag) in ΔB space (deg)")
    a2.set_ylabel("press estimate error (% of true)")
    a2.set_title(f"(2) projection leakage (press=drag={press_th:.0f} deg bend)")
    a2.legend(fontsize=8); a2.grid(alpha=0.3)
    fig.suptitle("Task2: can projection separate press from drag? (feeds E4)", fontsize=12)
    fig.tight_layout(); fig.savefig(out_png, dpi=110)

    # 判据
    m0 = np.abs(err_mean[0.0])
    idx = np.where(m0 < 10.0)[0]
    theta_need = thetas[idx[0]] if len(idx) else float("nan")
    return {"thetas": thetas, "err_mean": err_mean, "err_std": err_std,
            "theta_for_10pct": theta_need, "press_sig_pctB0": press_sig / B0MAG * 100}


if __name__ == "__main__":
    import sys
    r = study(sys.argv[1] if len(sys.argv) > 1 else "sep.png")
    print(f"压信号幅值 = {r['press_sig_pctB0']:.1f}% of |B0|")
    print(f"[投影法, 无噪声] 提按误差<10% 需要 θ ≥ {r['theta_for_10pct']:.0f}°")
    for f in r["err_mean"]:
        e90 = r["err_mean"][f][-1]; s90 = r["err_std"][f][-1]
        print(f"  噪声{int(f*100):2d}%: θ=90°(近正交)处 误差 {e90:+.1f}% ± {s90:.1f}%")
