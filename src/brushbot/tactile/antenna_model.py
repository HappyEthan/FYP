"""P0 · 触角磁学半段 — 中线形变 → 磁偶极子链 → 传感器处 ΔB (纯 numpy).

无需实体触角、无需 SOFA. 见 docs/06-mujoco-simulation-platform/archive/fem-design.md §2/§4.

思路: 把触角磁化段离散成沿中线的一串点磁偶极子(矩沿局部切线).
触角弯曲 → 偶极子位置+朝向都变 → 固定传感器处的 B 变 → ΔB = B - B0.

单位: 几何用 mm; B 为任意单位(省略 μ0/4π 常数)——本模型只看 ΔB 的结构与
相对变化, 绝对标度无意义(真值等真机 E2). P2 会用 SOFA 的形变节点替换
bent_centerline(), sensor_B() 原样复用.
"""
import numpy as np


def bent_centerline(theta_tip, L=24.0, N=40, azimuth_deg=40.0):
    """夹持在根部的悬臂梁, 弯成圆弧.

    theta_tip: 尖端切线相对初始方向的转角(rad); 0=笔直.
    返回 (pos, tang): 各 (N,3), 中线点(mm) 与 该点局部单位切线.
    约定: 根部在原点, 初始沿 -z(轴向, 朝尖端); 在 XY 面内 azimuth 方向弯曲.
    """
    axis1 = np.array([0.0, 0.0, -1.0])                       # 初始切线
    phi = np.radians(azimuth_deg)
    axis2 = np.array([np.cos(phi), np.sin(phi), 0.0])        # 弯曲方向(XY 面内)
    s = np.linspace(0.0, L, N)
    kappa = theta_tip / L if L > 0 else 0.0                  # 曲率(圆弧)
    th = kappa * s                                           # 各点累计转角
    tang = np.cos(th)[:, None] * axis1 + np.sin(th)[:, None] * axis2
    if kappa == 0.0:
        pos = s[:, None] * axis1
    else:
        pos = (np.sin(th)[:, None] * axis1 + (1.0 - np.cos(th))[:, None] * axis2) / kappa
    return pos, tang


def sensor_B(pos, tang, magnetized=(0.4, 1.0), m0=1.0, sensor=(0.0, 0.0, 3.0)):
    """偶极子链在 sensor 处的磁场 (任意单位, 省略 μ0/4π).

    magnetized: 磁化段占中线的比例区间(种子论文是"部分磁化", 只磁化远端一段
                使偏转更可读). m0: 单偶极子矩模长. sensor: 传感器位置(mm).
    偶极子场: B(r) = [3(m·r̂)r̂ − m] / |r|³, 沿链叠加.
    """
    N = len(pos)
    i0, i1 = int(magnetized[0] * N), int(magnetized[1] * N)
    obs = np.asarray(sensor, float)
    B = np.zeros(3)
    for i in range(i0, i1):
        m = m0 * tang[i]                                     # 矩沿局部切线
        r = obs - pos[i]
        rn = np.linalg.norm(r)
        if rn < 1e-9:
            continue
        rhat = r / rn
        B += (3.0 * np.dot(m, rhat) * rhat - m) / rn ** 3
    return B


def sweep_dB(theta_max_deg=55.0, steps=25, L=24.0, N=40, azimuth_deg=40.0,
             magnetized=(0.4, 1.0), m0=1.0, sensor=(0.0, 0.0, 3.0)):
    """从直(0)扫到弯(theta_max), 返回 (defl_pct, dB) — dB 为 (steps,3) 的 B−B0."""
    thetas = np.radians(np.linspace(0.0, theta_max_deg, steps))
    p0, t0 = bent_centerline(0.0, L, N, azimuth_deg)
    B0 = sensor_B(p0, t0, magnetized, m0, sensor)
    dB = np.empty((steps, 3))
    for k, th in enumerate(thetas):
        p, t = bent_centerline(th, L, N, azimuth_deg)
        dB[k] = sensor_B(p, t, magnetized, m0, sensor) - B0
    defl_pct = np.linspace(0.0, 100.0, steps)
    return defl_pct, dB


def demo(out_png):
    """P0 figure: left = antenna straight->bent; right = synchronized ΔB (as % of |B0|).
    English labels to avoid missing-CJK-glyph boxes in matplotlib."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    L, N, az, mag, sens = 24.0, 40, 40.0, (0.4, 1.0), (0.0, 0.0, 3.0)
    axis2 = np.array([np.cos(np.radians(az)), np.sin(np.radians(az)), 0.0])

    fig, (axL, axR) = plt.subplots(1, 2, figsize=(11, 4.6))

    # LEFT: several deformed centerlines, projected to (in-plane offset, axial depth)
    for th_deg, col in zip([0, 20, 35, 50], ["#bbb", "#7aa", "#488", "#066"]):
        p, _ = bent_centerline(np.radians(th_deg), L, N, az)
        lateral = p @ axis2                      # in-plane offset
        axial = -p[:, 2]                         # axial depth (0 root -> L tip)
        axL.plot(lateral, axial, color=col, lw=2.5, label=f"tip {th_deg} deg")
    axL.scatter([0], [-3], marker="v", s=90, color="crimson", zorder=5, label="sensor")
    axL.axhline(L * mag[0], ls=":", color="orange", lw=1)
    axL.text(0.2, L * mag[0] - 0.4, "magnetized segment start", color="orange", fontsize=8)
    axL.set_xlabel("in-plane offset (mm)"); axL.set_ylabel("axial depth (mm)")
    axL.set_title("(1) Antenna centerline: straight -> bent")
    axL.invert_yaxis(); axL.legend(fontsize=8, loc="lower right"); axL.grid(alpha=0.3)

    # RIGHT: ΔB vs deformation, normalized to % of |B0|
    p0, t0 = bent_centerline(0.0, L, N, az)
    B0mag = np.linalg.norm(sensor_B(p0, t0, mag, 1.0, sens))
    defl, dB = sweep_dB(55.0, 25, L, N, az, mag, 1.0, sens)
    pc = 100.0 / B0mag
    axR.plot(defl, dB[:, 0] * pc, label="dBx", lw=2)
    axR.plot(defl, dB[:, 1] * pc, label="dBy", lw=2)
    axR.plot(defl, dB[:, 2] * pc, label="dBz (axial)", lw=2.5, color="k")
    axR.plot(defl, np.hypot(dB[:, 0], dB[:, 1]) * pc,
             label="|dB_xy| (in-plane)", lw=2.5, ls="--", color="crimson")
    axR.set_xlabel("deformation (tip deflection %)")
    axR.set_ylabel("ΔB as % of |B0|")
    axR.set_title("(2) Synchronized ΔB signal")
    axR.legend(fontsize=9); axR.grid(alpha=0.3)
    axR.annotate("in-plane grows, axial stays flat\n(reproduces observed Bx,By change / Bz ~0)",
                 xy=(0.5, 0.04), xycoords="axes fraction", fontsize=8.5, color="crimson")

    fig.suptitle("P0: antenna deformation -> simulated dB  (pure sim, no hardware)", fontsize=13)
    fig.tight_layout()
    fig.savefig(out_png, dpi=110)
    return {"defl_pct": defl, "dB": dB}


def _trajectory(F1=80, F2=70):
    """形变随时间的脚本: 相位1=提按循环(方向固定, 幅值起伏);
    相位2=拖拽(弯度恒定, 方向旋转). 返回 [(theta_rad, azimuth_deg), ...]."""
    traj = []
    for k in range(F1):                         # 相位1: 提按 (两次不等幅按压)
        t = k / F1
        env = abs(np.sin(np.pi * t * 2.0)) * (0.6 + 0.4 * t)   # 两个逐渐加重的按压
        traj.append((np.radians(50.0 * env), 40.0))
    for k in range(F2):                         # 相位2: 拖拽 (弯度恒, 方向转一圈)
        t = k / F2
        traj.append((np.radians(35.0), 40.0 + 360.0 * t))
    return traj


def animate(out_gif, fps=20):
    """实时动画: 左=触角弯; 中=ΔB 时序滚动; 右=(Bx,By) 矢量轨迹.
    相位1 提按 → 幅值脉动/Bz 平; 相位2 拖拽 → 方向旋转/幅值恒."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation, PillowWriter

    L, N, mag, sens = 24.0, 40, (0.4, 1.0), (0.0, 0.0, 3.0)
    traj = _trajectory()
    F = len(traj)

    # 预计算全程 ΔB 与中线
    p0, t0 = bent_centerline(0.0, L, N, 40.0)
    B0 = sensor_B(p0, t0, mag, 1.0, sens)
    pc = 100.0 / np.linalg.norm(B0)
    curves, dB = [], np.empty((F, 3))
    for i, (th, az) in enumerate(traj):
        p, t = bent_centerline(th, L, N, az)
        curves.append((p @ np.array([np.cos(np.radians(az)), np.sin(np.radians(az)), 0.0]), -p[:, 2], az))
        dB[i] = (sensor_B(p, t, mag, 1.0, sens) - B0) * pc
    xy_lim = np.abs(dB[:, :2]).max() * 1.15
    ts_lim = np.abs(dB).max() * 1.1

    fig, (a1, a2, a3) = plt.subplots(1, 3, figsize=(13.5, 4.4))
    a1.set_title("(1) antenna bending"); a1.set_xlabel("in-plane offset (mm)")
    a1.set_ylabel("axial depth (mm)"); a1.set_xlim(-9, 9); a1.set_ylim(25, -1)
    a1.scatter([0], [-3], marker="v", s=80, color="crimson", zorder=5)
    a2.set_title("(2) ΔB vs time"); a2.set_xlabel("frame"); a2.set_ylabel("ΔB (% of |B0|)")
    a2.set_xlim(0, F); a2.set_ylim(-ts_lim, ts_lim); a2.axvline(80, ls=":", color="gray")
    a2.text(30, ts_lim * 0.82, "PRESS", color="gray"); a2.text(105, ts_lim * 0.82, "DRAG", color="gray")
    a3.set_title("(3) (Bx,By) vector"); a3.set_xlabel("ΔBx (%)"); a3.set_ylabel("ΔBy (%)")
    a3.set_xlim(-xy_lim, xy_lim); a3.set_ylim(-xy_lim, xy_lim); a3.set_aspect("equal")
    a3.axhline(0, color="#ddd"); a3.axvline(0, color="#ddd")

    (line_ant,) = a1.plot([], [], lw=3, color="#066")
    (lx,) = a2.plot([], [], lw=1.8, label="ΔBx"); (ly,) = a2.plot([], [], lw=1.8, label="ΔBy")
    (lz,) = a2.plot([], [], lw=2.2, color="k", label="ΔBz")
    (lm,) = a2.plot([], [], lw=2.2, ls="--", color="crimson", label="|ΔBxy|")
    a2.legend(fontsize=8, loc="lower left", ncol=2)
    (hod,) = a3.plot([], [], lw=1.2, color="#888"); (dot,) = a3.plot([], [], "o", color="crimson", ms=8)
    fig.suptitle("P0 live: antenna deforms -> simulated ΔB moves in sync", fontsize=13)
    fig.tight_layout()

    xs = np.arange(F)
    mag_xy = np.hypot(dB[:, 0], dB[:, 1])

    def upd(i):
        lat, ax, az = curves[i]
        line_ant.set_data(lat, ax)
        lx.set_data(xs[:i + 1], dB[:i + 1, 0]); ly.set_data(xs[:i + 1], dB[:i + 1, 1])
        lz.set_data(xs[:i + 1], dB[:i + 1, 2]); lm.set_data(xs[:i + 1], mag_xy[:i + 1])
        hod.set_data(dB[:i + 1, 0], dB[:i + 1, 1]); dot.set_data([dB[i, 0]], [dB[i, 1]])
        return line_ant, lx, ly, lz, lm, hod, dot

    anim = FuncAnimation(fig, upd, frames=F, blit=True)
    anim.save(out_gif, writer=PillowWriter(fps=fps))
    plt.close(fig)
    return {"frames": F, "dB": dB}


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "demo"
    out = sys.argv[2] if len(sys.argv) > 2 else ("p0.gif" if mode == "anim" else "p0.png")
    (animate if mode == "anim" else demo)(out)
