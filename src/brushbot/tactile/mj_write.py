"""方案 B · 全 MuJoCo: Elfin 臂 + 末端物理触角 + 纸, 写字时触角真形变.

状态(2026-07-23):
  ✅ Phase 1: 组合模型(MjSpec 合成 Elfin URDF + 触角链 + 纸 + 执行器) + 雅可比 DLS IK.
     验证臂能精确到达笛卡尔位姿(残差 0). → build_model(), ik()
  ✅ Phase 2: 走字轨迹→逐点 IK→运动学驱动臂. Elfin 在 MuJoCo 里写出干净的字.
     → write(), demo_write()  (mode "write")
  ⚠️ Phase 3 WIP: 触角接触纸物理弯→ΔB. 静态落笔已验证(压纸/横向弯 3.36mm/抬笔无接触),
     但连续写字的动态积分不稳: 某些拍触角中线换到传感器系时错乱(本该 +z 的段出现在 -z),
     磁偶极子 1/r³ 发散 → ΔB 爆表(10^9%). 试过 pin-step / 伺服+重力补偿 / 加刚度限位均未根治.
     → write_contact(), demo_contact()  (mode "contact")  —— 勿信其 ΔB 输出.
  ✅ Phase 4: 实时 viewer, 看臂一笔一划写字 + 笔尖落点留墨(运动学驱动, 稳).
     → watch_write()  (mode "watch")

后续方向: 改用真实数据集(一横→真实 ΔB 序列)做标定, 合成 ΔB 只是没硬件时的替代.
见 docs/tactile-fem-sim.md.
"""
import numpy as np
import mujoco

ARM_JOINTS = [f"elfin_joint{i}" for i in range(1, 7)]
ELFIN_URDF = "src/brushbot/assets/elfin5/elfin5.urdf"
TIP_BODY = "elfin_link6"             # 刚性法兰(触角挂此, 从它往下伸); 固定末端 body 被 compile 焊入
ANT_N = 8                            # 触角分段
ANT_SEG = 0.003                      # 段长 m
PAPER_Z = 0.20                       # 与 brushbot config 一致


def build_model(urdf=ELFIN_URDF, ant_n=ANT_N, tilt_deg=12.0):
    """MjSpec 组装: Elfin + 末端触角链(微倾, 便于弯) + 纸 + 关节位置执行器."""
    spec = mujoco.MjSpec.from_file(urdf)
    eef = spec.body("elfin_link6")
    mount = eef.add_body(name="ant_mount", pos=[0, 0, 0],
                         euler=[0, np.radians(tilt_deg), 0])
    parent = mount
    # 触角沿 mount-local +z 延伸(工具 roll=180 → link6 z 朝下 → +z=世界朝下, 指向纸)
    for i in range(ant_n):
        b = parent.add_body(name=f"ant{i}", pos=[0, 0, 0] if i == 0 else [0, 0, ANT_SEG])
        if i > 0:
            j = b.add_joint(name=f"ah{i}", type=mujoco.mjtJoint.mjJNT_HINGE,
                            axis=[0, 1, 0], stiffness=0.02, damping=0.02)
            j.range = [-0.3, 0.3]                       # 限位防折叠(每段<17°)
            j.limited = mujoco.mjtLimited.mjLIMITED_TRUE
        g = b.add_geom(type=mujoco.mjtGeom.mjGEOM_CAPSULE, fromto=[0, 0, 0, 0, 0, ANT_SEG],
                       size=[0.0006, 0, 0], density=1500, rgba=[0.1, 0.4, 0.8, 1])
        g.contype = 4; g.conaffinity = 4               # 触角只与纸(组4)碰, 不碰机械臂
        parent = b
    spec.worldbody.add_geom(type=mujoco.mjtGeom.mjGEOM_PLANE, size=[0.5, 0.5, 0.05],
                            pos=[0, 0, 0], rgba=[0.8, 0.75, 0.7, 1])          # 地面(视觉)
    paper = spec.worldbody.add_geom(name="paper", type=mujoco.mjtGeom.mjGEOM_BOX,
                                    size=[0.07, 0.07, 0.001], pos=[0.45, 0.0, PAPER_Z],
                                    rgba=[0.98, 0.98, 0.98, 1])
    paper.contype = 4; paper.conaffinity = 4           # 纸: 与触角碰
    for jn in ARM_JOINTS:
        a = spec.add_actuator(name="m_" + jn, trntype=mujoco.mjtTrn.mjTRN_JOINT,
                              gaintype=mujoco.mjtGain.mjGAIN_FIXED,
                              biastype=mujoco.mjtBias.mjBIAS_AFFINE)
        a.target = jn
        a.gainprm[0] = 2000        # kp
        a.biasprm[1] = -2000       # -kp (位置反馈)
        a.biasprm[2] = -200        # -kv (速度阻尼, 否则纯 P 会发散乱甩)
    return spec.compile()


def _arm_qadr(model):
    return [model.jnt_qposadr[mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, jn)]
            for jn in ARM_JOINTS]


def ik(model, data, target_pos, target_quat=None, iters=300, damp=1e-3, tol=2e-4):
    """雅可比 DLS IK: 只动 6 个臂关节, 让 TIP_BODY 到达 target. 返回收敛残差(m)."""
    bid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, TIP_BODY)
    qadr = _arm_qadr(model)
    dofs = [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, jn) for jn in ARM_JOINTS]
    dofadr = [model.jnt_dofadr[i] for i in dofs]
    lo = np.array([model.jnt_range[i, 0] for i in dofs])
    hi = np.array([model.jnt_range[i, 1] for i in dofs])
    jacp = np.zeros((3, model.nv)); jacr = np.zeros((3, model.nv))
    for _ in range(iters):
        mujoco.mj_forward(model, data)
        e_pos = target_pos - data.xpos[bid]
        if target_quat is not None:
            negq = np.zeros(4); mujoco.mju_negQuat(negq, data.xquat[bid])
            dqt = np.zeros(4); mujoco.mju_mulQuat(dqt, target_quat, negq)
            e_rot = np.zeros(3); mujoco.mju_quat2Vel(e_rot, dqt, 1.0)
            err = np.concatenate([e_pos, e_rot])
        else:
            err = e_pos
        if np.linalg.norm(e_pos) < tol and (target_quat is None or np.linalg.norm(err[3:]) < 1e-2):
            break
        mujoco.mj_jacBody(model, data, jacp, jacr, bid)
        J = (np.vstack([jacp, jacr]) if target_quat is not None else jacp)[:, dofadr]
        dq = J.T @ np.linalg.solve(J @ J.T + damp * np.eye(J.shape[0]), err)
        q = np.array([data.qpos[a] for a in qadr]) + dq
        q = np.clip(q, lo, hi)
        for k, a in enumerate(qadr):
            data.qpos[a] = q[k]
    mujoco.mj_forward(model, data)
    return float(np.linalg.norm(target_pos - data.xpos[bid])), np.array([data.qpos[a] for a in qadr])


import math
from brushbot import config
from brushbot.controller import OpenLoopController
from brushbot.types import State

DEFAULT_GRAPHICS = "data/makemeahanzi/graphics.txt"
ANT_LEN = ANT_N * ANT_SEG                       # 触角总长, 法兰目标要抬高这么多


def _writing_waypoints(character, size=0.032):
    """汉字 → link6(法兰) 的笛卡尔路点. 触角从法兰往下伸 ANT_LEN, 故 z 抬高."""
    from brushbot.calligraphy.hanzi import load_medians, medians_to_strokes, strokes_to_waypoints
    strokes = medians_to_strokes(load_medians(character, DEFAULT_GRAPHICS), size=size)
    z_down = config.PAPER_Z + (0.0045 - config.Z_TOUCH_REF)
    z_up = config.PAPER_Z + 0.03
    wp = strokes_to_waypoints(strokes, config.CHAR_ORIGIN, z_down, z_up,
                              char_yaw_deg=config.CHAR_YAW_DEG)
    return [(x, y, z + ANT_LEN) for (x, y, z) in wp]


def write(character="永", speed=0.02, substeps=8):
    """Elfin 在 MuJoCo 里走出字的轨迹(Phase2). 臂用运动学驱动(每拍 IK 设 qpos,
    暖启动保持解连续); 动力学伺服跟不了这么快的轨迹且会解支跳变发散(实测).
    返回 link6/触角尖 轨迹."""
    m = build_model(); d = mujoco.MjData(m)
    wp = _writing_waypoints(character)
    quat = np.zeros(4); mujoco.mju_euler2Quat(quat, [math.pi, 0.0, 0.0], "xyz")
    ik(m, d, np.array(wp[0]), quat)                    # 起点
    ctrl = OpenLoopController(wp, speed=speed, fixed_ori=(math.pi, 0.0, 0.0))
    dt = substeps * m.opt.timestep
    l6 = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "elfin_link6")
    tip = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, f"ant{ANT_N-1}")
    tr_l6, tr_tip = [], []
    t = 0.0
    while not ctrl.done():
        cmd = ctrl.step(State(tcp_pose=(0,) * 6, g_meas=0.0, t=t))
        ik(m, d, np.array(cmd.tcp_pose[:3]), quat, iters=100)   # 运动学: 设 qpos, 暖启动
        mujoco.mj_forward(m, d)
        tr_l6.append(d.xpos[l6].copy()); tr_tip.append(d.xpos[tip].copy())
        t += dt
    return {"model": m, "data": d, "trace_l6": np.array(tr_l6), "trace_tip": np.array(tr_tip)}


def demo_write(character="永", out_png="mj_write.png"):
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    r = write(character)
    l6, tp = r["trace_l6"], r["trace_tip"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 4.6))
    a1.plot(l6[:, 0], l6[:, 1], lw=1); a1.set_aspect("equal"); a1.set_title("link6 (flange) xy path")
    a1.set_xlabel("x"); a1.set_ylabel("y"); a1.grid(alpha=0.3)
    a2.plot(tp[:, 0], tp[:, 1], lw=1, color="crimson"); a2.set_aspect("equal")
    a2.set_title("antenna tip xy (passive, no contact yet)"); a2.set_xlabel("x"); a2.set_ylabel("y"); a2.grid(alpha=0.3)
    fig.suptitle(f"Phase2: Elfin writes '{character}' in MuJoCo (link6 IK-driven)", fontsize=12)
    fig.tight_layout(); fig.savefig(out_png, dpi=110)
    return r


def watch_write(character="永", speed=0.02, substeps=8, realtime=True):
    """★ Phase4 实时窗口: 看 Elfin 一笔一划写字, 末端**物理触角碰纸被顶弯**, 笔尖落点留墨。

    混合驱动(关键): 臂用**运动学锁死**(每拍 IK 求解, 步进后把臂关节 qpos 硬置回目标, 速度清零
    → 臂精确跟轨迹、绝不乱甩); 触角**跑动力学**(mj_step 让铰链在接触下积分 → 撞纸真弯,
    不再穿模)。只做可视化, 不算 ΔB, 故绕开 Phase3 的 ΔB 发散 bug。需显示器(本机跑)。"""
    import time
    try:
        import mujoco.viewer as viewer
    except Exception as e:
        print("需要 mujoco.viewer(本机有显示器时可用):", e); return
    m = build_model(); d = mujoco.MjData(m); scratch = mujoco.MjData(m)
    wp = _writing_waypoints(character)
    quat = np.zeros(4); mujoco.mju_euler2Quat(quat, [math.pi, 0.0, 0.0], "xyz")
    qadr = _arm_qadr(m)
    arm_dof = [m.jnt_dofadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, jn)] for jn in ARM_JOINTS]
    tipid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, f"ant{ANT_N-1}")

    def pin(q):                                          # 臂关节钉在 IK 解, 速度清零
        for k, a in enumerate(qadr):
            d.qpos[a] = q[k]
        d.qvel[arm_dof] = 0.0

    _, q_ik = ik(m, d, np.array(wp[0]), quat)            # 起点位形
    pin(q_ik); mujoco.mj_forward(m, d)
    dt = substeps * m.opt.timestep
    print(f"打开窗口: Elfin 写 '{character}'; 触角碰纸会弯, 笔尖落点留墨。关窗退出。")
    with viewer.launch_passive(m, d) as v:
        eye = np.eye(3).flatten()

        def ink():                                       # 笔尖贴近纸面 → 加一个持久墨点
            tp = d.xpos[tipid]
            if tp[2] <= PAPER_Z + 0.003 and v.user_scn.ngeom < v.user_scn.maxgeom:
                g = v.user_scn.geoms[v.user_scn.ngeom]
                mujoco.mjv_initGeom(g, mujoco.mjtGeom.mjGEOM_SPHERE, [0.0012, 0, 0],
                                    tp.copy(), eye, np.array([0.05, 0.05, 0.05, 1.0]))
                v.user_scn.ngeom += 1

        ctrl = OpenLoopController(wp, speed=speed, fixed_ori=(math.pi, 0.0, 0.0))
        t = 0.0
        while v.is_running() and not ctrl.done():
            cmd = ctrl.step(State(tcp_pose=(0,) * 6, g_meas=0.0, t=t))
            scratch.qpos[:] = d.qpos                     # IK 从当前解暖启动(在 scratch 上, 不扰触角动力学)
            for k, a in enumerate(qadr):
                scratch.qpos[a] = q_ik[k]
            _, q_ik = ik(m, scratch, np.array(cmd.tcp_pose[:3]), quat, iters=100)
            for _ in range(substeps):                    # 臂钉死 + 触角在接触下积分
                pin(q_ik)
                mujoco.mj_step(m, d)
            pin(q_ik); mujoco.mj_forward(m, d)           # 收尾对齐, 渲染用
            ink(); v.sync()
            if realtime:
                time.sleep(dt)
            t += dt
        print(f"写完({v.user_scn.ngeom} 墨点)。关窗退出。")
        while v.is_running():
            v.sync(); time.sleep(0.05)


def _antenna_centerline(m, d):
    """触角各段世界位置 → 转到 ant_mount(根/传感器)局部系, mm 制中线."""
    mount = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "ant_mount")
    Rm = d.xmat[mount].reshape(3, 3); pm = d.xpos[mount]
    ids = [mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, f"ant{i}") for i in range(ANT_N)]
    pts = np.array([d.xpos[i] for i in ids])
    pts = np.vstack([pts, pts[-1] + Rm @ np.array([0, 0, ANT_SEG])])    # 加尖端(沿 +z)
    return (pts - pm) @ Rm * 1000.0


def _tangents(cl):
    t = np.gradient(cl, axis=0)
    return t / (np.linalg.norm(t, axis=1, keepdims=True) + 1e-12)


def write_contact(character="永", speed=0.02, substeps=8):
    """Phase3 (⚠️ WIP, 勿信 ΔB 输出): 臂伺服驱动 + 触角动力学(接触纸物理弯) → ΔB.
    连续写字动态积分不稳, 某些拍中线错乱致磁场 1/r³ 发散(见模块 docstring).
    静态落笔的接触弯是对的; 动态集成待修. 返回 dB(F,3), B0mag, tip_xy, ncon."""
    from brushbot.tactile.antenna_model import sensor_B
    m = build_model(); d = mujoco.MjData(m); scratch = mujoco.MjData(m)
    wp = _writing_waypoints(character)
    quat = np.zeros(4); mujoco.mju_euler2Quat(quat, [math.pi, 0.0, 0.0], "xyz")
    qadr = _arm_qadr(m)
    arm_dof = [m.jnt_dofadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, jn)] for jn in ARM_JOINTS]

    def step_grav():                              # 一致动力学: 臂伺服跟踪 + 重力补偿(只补臂)
        mujoco.mj_forward(m, d)
        d.qfrc_applied[arm_dof] = d.qfrc_bias[arm_dof]
        mujoco.mj_step(m, d)

    _, q_ik = ik(m, d, np.array(wp[0]), quat)     # 初始位形
    for k, a in enumerate(qadr):
        d.qpos[a] = q_ik[k]
    d.ctrl[:6] = q_ik
    for _ in range(500):                          # 稳定 → 基线(悬空, 无接触)
        step_grav()
    cl0 = _antenna_centerline(m, d)
    B0 = sensor_B(cl0, _tangents(cl0), (0.4, 1.0), 1.0, (0, 0, -3))
    B0m = float(np.linalg.norm(B0))

    ctrl = OpenLoopController(wp, speed=speed, fixed_ori=(math.pi, 0.0, 0.0))
    dt = substeps * m.opt.timestep; t = 0.0
    tipid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, f"ant{ANT_N-1}")
    paper_gid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "paper")
    dB, tip_xy, ncon = [], [], []
    while not ctrl.done():
        cmd = ctrl.step(State(tcp_pose=(0,) * 6, g_meas=0.0, t=t))
        scratch.qpos[:] = d.qpos                  # IK 从上一解暖启动(保持连续, 不受伺服残差扰动)
        for k, a in enumerate(qadr):
            scratch.qpos[a] = q_ik[k]
        _, q_ik = ik(m, scratch, np.array(cmd.tcp_pose[:3]), quat, iters=100)
        d.ctrl[:6] = q_ik
        for _ in range(substeps):
            step_grav()
        cl = _antenna_centerline(m, d)
        dB.append(sensor_B(cl, _tangents(cl), (0.4, 1.0), 1.0, (0, 0, -3)) - B0)
        npap = sum(1 for c in d.contact[:d.ncon] if paper_gid in (c.geom1, c.geom2))
        tip_xy.append(d.xpos[tipid][:2].copy()); ncon.append(npap)
        t += dt
    return {"model": m, "data": d, "dB": np.array(dB), "B0mag": B0m,
            "tip_xy": np.array(tip_xy), "ncon": np.array(ncon)}


def demo_contact(character="永", out_png="mj_contact.png"):
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    r = write_contact(character)
    dB = r["dB"]; pc = 100.0 / r["B0mag"]; ct = r["ncon"] > 0; xy = r["tip_xy"]
    F = len(dB); xs = np.arange(F)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.6))
    a1.plot(xy[ct, 0], xy[ct, 1], ".", ms=2, color="k")
    a1.set_aspect("equal"); a1.set_title("(1) antenna tip where in contact"); a1.grid(alpha=0.3)
    a2.plot(xs, dB[:, 0] * pc, label="dBx", lw=1)
    a2.plot(xs, dB[:, 1] * pc, label="dBy", lw=1)
    a2.plot(xs, dB[:, 2] * pc, label="dBz", lw=1.4, color="k")
    a2.plot(xs, np.hypot(dB[:, 0], dB[:, 1]) * pc, label="|dBxy|", lw=1.6, ls="--", color="crimson")
    inb = False
    for i in range(F):
        if ct[i] and not inb:
            s = i; inb = True
        elif not ct[i] and inb:
            a2.axvspan(s, i, color="orange", alpha=0.08); inb = False
    if inb:
        a2.axvspan(s, F, color="orange", alpha=0.08)
    a2.set_title("(2) PHYSICAL ΔB (antenna bent by contact)"); a2.set_xlabel("tick")
    a2.set_ylabel("ΔB (% of |B0|)"); a2.legend(fontsize=8, ncol=2); a2.grid(alpha=0.3)
    fig.suptitle(f"Phase3: Elfin writes '{character}', antenna physically bends -> real ΔB", fontsize=12)
    fig.tight_layout(); fig.savefig(out_png, dpi=110)
    return r


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "ik"
    if mode == "watch":
        watch_write(sys.argv[2] if len(sys.argv) > 2 else "永")
    elif mode == "write":
        ch = sys.argv[2] if len(sys.argv) > 2 else "永"
        out = sys.argv[3] if len(sys.argv) > 3 else "mj_write.png"
        r = demo_write(ch, out)
        l6 = r["trace_l6"]
        print("写完: %d 拍  link6 x跨=%.3f y跨=%.3f m" %
              (len(l6), np.ptp(l6[:, 0]), np.ptp(l6[:, 1])))
    elif mode == "contact":
        ch = sys.argv[2] if len(sys.argv) > 2 else "永"
        out = sys.argv[3] if len(sys.argv) > 3 else "mj_contact.png"
        r = demo_contact(ch, out)
        dB = r["dB"]; ct = r["ncon"] > 0; pc = 100.0 / r["B0mag"]
        print("写完: %d 拍  接触拍=%d  接触时 |ΔBxy| 均=%.1f%% max=%.1f%%  ΔBz max=%.1f%%" %
              (len(dB), int(ct.sum()),
               np.hypot(dB[ct, 0], dB[ct, 1]).mean() * pc if ct.any() else 0,
               np.hypot(dB[ct, 0], dB[ct, 1]).max() * pc if ct.any() else 0,
               np.abs(dB[ct, 2]).max() * pc if ct.any() else 0))
    else:
        m = build_model(); print("组合模型 bodies=%d joints=%d actuators=%d" % (m.nbody, m.njnt, m.nu))
        q_down = np.zeros(4); mujoco.mju_euler2Quat(q_down, [math.pi, 0, 0], "xyz")
        for tgt in [[0.45, 0.0, 0.30], [0.42, 0.05, 0.35], [0.40, -0.05, 0.28]]:
            d = mujoco.MjData(m)
            err, q = ik(m, d, np.array(tgt), q_down)
            print("IK -> %s : 残差 %.4f m %s" % (tgt, err, "✅" if err < 0.005 else "⚠️"))
