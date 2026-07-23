"""任务1 · 接触涌现形变 (MuJoCo) → 复用 P0 磁学 → ΔB.

触角建成一串铰链连接的分段(离散弹性杆), 微倾斜安装在一个可升降滑座上,
压向地面 → 接触力把触角顶弯(形变不是手掰的, 是撞出来的). 每步读各段世界
位置 → 转到触角根部(传感器)局部系 → sensor_B (P0, 不改) → ΔB.

见 docs/tactile-fem-sim.md. 用 MuJoCo 作为 SOFA 的回退(§5): 更真实接触、
pip 秒装、无显示可跑; 磁学半段与引擎解耦, 原样复用。
"""
import numpy as np
import mujoco
from brushbot.tactile.antenna_model import sensor_B

L = 0.024          # 触角总长 (m)
N = 10             # 分段数
SEG = L / N
R = 0.0006         # 段半径 (m)
TILT_DEG = 18.0    # 安装倾角(绕 y), 给接触一个明确的弯曲方向
H0 = 0.030         # 滑座初始高度 (m), 触角悬空


def _build_xml():
    seg = SEG
    # 递归嵌套 N 个 body, 每个用绕 y 的铰链(带刚度+阻尼)连接 → 在 x-z 面内弯
    def body(i):
        joint = "" if i == 0 else (
            f'<joint name="h{i}" type="hinge" axis="0 1 0" '
            f'stiffness="0.001" damping="0.0001"/>')   # 软铰链: 接触能顶弯
        inner = body(i + 1) if i < N - 1 else ""
        pos = 'pos="0 0 0"' if i == 0 else f'pos="0 0 {-seg}"'
        return (f'<body name="a{i}" {pos}>{joint}'
                f'<geom type="capsule" fromto="0 0 0 0 0 {-seg}" size="{R}" '
                f'density="1500" rgba="0.1 0.4 0.7 1"/>{inner}</body>')
    chain = body(0)
    return f"""
<mujoco>
  <option gravity="0 0 -9.81" timestep="0.001" integrator="implicitfast"/>
  <worldbody>
    <geom name="ground" type="plane" size="0.3 0.3 0.05" pos="0 0 0" rgba="0.9 0.9 0.9 1"/>
    <body name="carriage" pos="0 0 {H0}">
      <joint name="slide" type="slide" axis="0 0 1"/>
      <geom type="box" size="0.004 0.004 0.002" rgba="0.3 0.3 0.3 1"/>
      <body name="mount" euler="0 {TILT_DEG} 0">
        {chain}
      </body>
    </body>
  </worldbody>
  <actuator><position joint="slide" kp="800" ctrlrange="-0.05 0.05"/></actuator>
</mujoco>"""


def _local_centerline(model, data):
    """各段世界位置 → 转到 mount(触角根)局部系, 返回 mm 制中线 (N,3)."""
    root = data.body("mount")
    Rr = root.xmat.reshape(3, 3)
    p0 = root.xpos
    ids = [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, f"a{i}") for i in range(N)]
    pts = np.array([data.xpos[i] for i in ids])          # 世界系
    tip = pts[-1] + Rr @ np.array([0, 0, -SEG])          # 加尖端
    pts = np.vstack([pts, tip])
    local = (pts - p0) @ Rr                               # 世界 → 根局部
    return local * 1000.0                                 # m → mm


def run(press_mm=(0, 3, 6, 9, 12, 15, 18, 21), settle=700):
    """把滑座逐档下压, 每档待稳后读中线并算 ΔB. 返回 (press_mm, dB, centerlines)."""
    model = mujoco.MjModel.from_xml_string(_build_xml())
    data = mujoco.MjData(model)
    sensor = (0.0, 0.0, 3.0)                              # 传感器在根部上方 3mm(局部系)
    mag = (0.4, 1.0)

    def centerline_now():
        cl = _local_centerline(model, data)
        tang = np.gradient(cl, axis=0)
        tang /= (np.linalg.norm(tang, axis=1, keepdims=True) + 1e-12)
        return cl, tang

    # 基线: 悬空(未接触)
    data.ctrl[0] = 0.0
    for _ in range(settle):
        mujoco.mj_step(model, data)
    cl0, t0 = centerline_now()
    B0 = sensor_B(cl0, t0, mag, 1.0, sensor)

    dB, cls = [], []
    for d in press_mm:
        data.ctrl[0] = -d / 1000.0                        # 下压 d mm
        for _ in range(settle):
            mujoco.mj_step(model, data)
        cl, t = centerline_now()
        dB.append(sensor_B(cl, t, mag, 1.0, sensor) - B0)
        cls.append(cl)
    return np.array(press_mm, float), np.array(dB), cls


def demo(out_png):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    press, dB, cls = run()
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.6))
    for cl, d in zip(cls, press):
        a1.plot(cl[:, 0], -cl[:, 2], lw=2, label=f"press {d:.0f}mm")
    a1.scatter([0], [-3], marker="v", s=80, color="crimson", zorder=5, label="sensor")
    a1.set_xlabel("in-plane x (mm)"); a1.set_ylabel("axial depth (mm)")
    a1.set_title("(1) antenna bent by CONTACT (MuJoCo)")
    a1.invert_yaxis(); a1.legend(fontsize=7); a1.grid(alpha=0.3)

    a2.plot(press, dB[:, 0], "-o", label="dBx (in-plane)", lw=2)
    a2.plot(press, dB[:, 1], "-o", label="dBy", lw=2)
    a2.plot(press, dB[:, 2], "-o", label="dBz (axial)", color="k", lw=2.5)
    a2.set_xlabel("press depth (mm)"); a2.set_ylabel("ΔB (arb.)")
    a2.set_title("(2) ΔB from contact deformation"); a2.legend(fontsize=9); a2.grid(alpha=0.3)
    fig.suptitle("Task1: contact -> emergent deformation -> ΔB (MuJoCo, no hardware)", fontsize=12)
    fig.tight_layout(); fig.savefig(out_png, dpi=110)
    return press, dB


def _t(cl):
    t = np.gradient(cl, axis=0); return t / (np.linalg.norm(t, axis=1, keepdims=True) + 1e-12)


if __name__ == "__main__":
    import sys
    press, dB = demo(sys.argv[1] if len(sys.argv) > 1 else "contact.png")
    for d, b in zip(press, dB):
        print(f"press {d:4.0f}mm -> ΔB=({b[0]:+.4f},{b[1]:+.4f},{b[2]:+.4f})  |xy|={np.hypot(b[0],b[1]):.4f}")
