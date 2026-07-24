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
# 法兰端面在 elfin_link6 局部 +z 的偏移(实测: link6 网格局部 z ∈ [0.006, 0.0545])。
# 触角必须挂在端面而非 link6 原点, 否则整根埋在腕壳里, 且腕部会戳穿纸/桌。
FLANGE_FACE = 0.0545


def build_model(urdf=ELFIN_URDF, ant_n=ANT_N, tilt_deg=12.0, paper_z=PAPER_Z,
                ah_stiff=0.02, ah_damp=0.02, timestep=None,
                paper_solref=(0.004, 1.0), paper_solimp=None):
    """MjSpec 组装: Elfin + 末端触角链(微倾, 便于弯) + 纸 + 关节位置执行器.
    paper_z: 纸(BOX)中心高度. 实时接触时应对齐触角尖落点, 否则触角会穿纸(见 watch_write).
    ah_stiff/ah_damp: 触角铰链刚度/阻尼(越小越易弯). paper_solref/solimp+timestep: 接触硬度旋钮。"""
    spec = mujoco.MjSpec.from_file(urdf)
    if timestep is not None:
        spec.option.timestep = timestep
    eef = spec.body("elfin_link6")
    mount = eef.add_body(name="ant_mount", pos=[0, 0, FLANGE_FACE],   # 挂法兰端面, 不埋在腕壳里
                         euler=[0, np.radians(tilt_deg), 0])
    parent = mount
    # 触角沿 mount-local +z 延伸(工具 roll=180 → link6 z 朝下 → +z=世界朝下, 指向纸)
    for i in range(ant_n):
        b = parent.add_body(name=f"ant{i}", pos=[0, 0, 0] if i == 0 else [0, 0, ANT_SEG])
        if i > 0:
            j = b.add_joint(name=f"ah{i}", type=mujoco.mjtJoint.mjJNT_HINGE,
                            axis=[0, 1, 0], stiffness=ah_stiff, damping=ah_damp)
            j.range = [-0.3, 0.3]                       # 限位防折叠(每段<17°)
            j.limited = mujoco.mjtLimited.mjLIMITED_TRUE
        g = b.add_geom(type=mujoco.mjtGeom.mjGEOM_CAPSULE, fromto=[0, 0, 0, 0, 0, ANT_SEG],
                       size=[0.0006, 0, 0], density=1500, rgba=[0.1, 0.4, 0.8, 1])
        g.contype = 4; g.conaffinity = 4               # 触角只与纸(组4)碰, 不碰机械臂
        parent = b
    spec.worldbody.add_geom(type=mujoco.mjtGeom.mjGEOM_PLANE, size=[0.5, 0.5, 0.05],
                            pos=[0, 0, 0], rgba=[0.8, 0.75, 0.7, 1])          # 地面(视觉)
    # 桌子: 从地面撑到纸底, 让纸不再悬空。
    # 注意: URDF 派生的 spec 默认 discardvisual=true, 纯视觉件(contype/conaffinity 全 0)
    # 会被编译丢弃 → 这里给它独立碰撞组 2(臂=1, 触角/纸=4), 谁也碰不着但能留在模型里。
    # 只做薄桌面板(不是从地面起的实心块, 否则机械臂下臂会穿过去)
    paper_bot = paper_z - 0.002
    if paper_bot > 0.014:
        table = spec.worldbody.add_geom(name="table", type=mujoco.mjtGeom.mjGEOM_BOX,
                                        size=[0.10, 0.10, 0.006],          # 12mm 厚桌面
                                        pos=[0.45, 0.0, paper_bot - 0.006],
                                        rgba=[0.55, 0.40, 0.25, 1])
        table.contype = 2; table.conaffinity = 2
    paper = spec.worldbody.add_geom(name="paper", type=mujoco.mjtGeom.mjGEOM_BOX,
                                    size=[0.07, 0.07, 0.002], pos=[0.45, 0.0, paper_z],
                                    rgba=[0.98, 0.98, 0.98, 1])
    paper.contype = 4; paper.conaffinity = 4           # 纸: 与触角碰
    paper.solref = list(paper_solref)                  # 硬接触(小时间常数)→ 减少软穿透
    if paper_solimp is not None:
        paper.solimp = list(paper_solimp)
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
ANT_LEN = ANT_N * ANT_SEG                       # 触角总长
TOOL_LEN = FLANGE_FACE + ANT_LEN                # link6 原点 → 触角尖: 法兰端面 + 触角


def _writing_waypoints(character, size=0.032):
    """汉字 → link6(法兰) 的笛卡尔路点. 触角尖在 link6 原点下方 TOOL_LEN 处, 故 z 抬高该值
    (含法兰端面偏移; 只补 ANT_LEN 会让腕壳戳穿纸面)."""
    from brushbot.calligraphy.hanzi import load_medians, medians_to_strokes, strokes_to_waypoints
    strokes = medians_to_strokes(load_medians(character, DEFAULT_GRAPHICS), size=size)
    z_down = config.PAPER_Z + (0.0045 - config.Z_TOUCH_REF)
    z_up = config.PAPER_Z + 0.03
    wp = strokes_to_waypoints(strokes, config.CHAR_ORIGIN, z_down, z_up,
                              char_yaw_deg=config.CHAR_YAW_DEG)
    return [(x, y, z + TOOL_LEN) for (x, y, z) in wp]


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


# 视角预设: (azimuth, elevation, distance, lookat) —— lookat 为 None 时用纸面中心
CAM_PRESETS = {
    1: ("俯视(看成品字)",  90.0, -89.0, 0.22, None),
    2: ("斜视(默认)",     135.0, -35.0, 0.45, None),
    3: ("侧视(看抬落笔)", 180.0,  -6.0, 0.32, None),
    4: ("全景(整条臂)",   135.0, -25.0, 1.40, (0.22, 0.0, 0.30)),
}


def watch_write(chars="永", speed=0.02, substeps=8, realtime=True):
    """★ Phase4 实时窗口: 看 Elfin 一笔一划写字, 末端**物理触角碰纸被顶弯**, 笔尖落点留墨。

    混合驱动(关键): 臂用**运动学锁死**(每拍 IK 求解, 步进后把臂关节 qpos 硬置回目标, 速度清零
    → 臂精确跟轨迹、绝不乱甩); 触角**跑动力学**(mj_step 让铰链在接触下积分 → 撞纸真弯,
    不再穿模)。只做可视化, 不算 ΔB, 故绕开 Phase3 的 ΔB 发散 bug。需显示器(本机跑)。

    交互键: r 重写 | c 清墨 | n 下一个字 | 1/2/3/4 视角 | 空格 暂停 | +/- 快慢 | q 退出
    chars: 单个字或多字序列(用 n 切换), 如 "永" 或 "永書王"。"""
    import time
    try:
        import mujoco.viewer as viewer
    except Exception as e:
        print("需要 mujoco.viewer(本机有显示器时可用):", e); return
    chars = list(chars)
    # 纸对齐触角尖落点(尖停纸面、其余在纸上方, 不穿模); 留 1mm 压量→触角尖贴纸微弯。
    # 硬接触(solimp)把软穿透压到 <1mm(屏幕看不出); 压量再大只会增穿透不增弯(实测)。
    pen_tip_z = config.PAPER_Z + (0.0045 - config.Z_TOUCH_REF)   # 触角尖落笔目标高度
    paper_top = pen_tip_z + 0.001
    m = build_model(paper_z=paper_top - 0.002,                   # BOX 半厚 0.002
                    paper_solimp=[0.98, 0.999, 0.0001, 0.5, 2])
    d = mujoco.MjData(m); scratch = mujoco.MjData(m)
    quat = np.zeros(4); mujoco.mju_euler2Quat(quat, [math.pi, 0.0, 0.0], "xyz")
    qadr = _arm_qadr(m)
    arm_dof = [m.jnt_dofadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, jn)] for jn in ARM_JOINTS]
    tipid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, f"ant{ANT_N-1}")
    paper_ctr = (config.CHAR_ORIGIN[0], config.CHAR_ORIGIN[1], paper_top)

    def pin(q):                                          # 臂关节钉在 IK 解, 速度清零
        for k, a in enumerate(qadr):
            d.qpos[a] = q[k]
        d.qvel[arm_dof] = 0.0

    ui = {"restart": True, "clear": False, "next": False,
          "pause": False, "quit": False, "cam": 2, "rate": 1.0}

    def key_callback(keycode):
        k = chr(keycode).lower() if 32 <= keycode < 127 else ""
        if k == "r":
            ui["restart"] = True
        elif k == "c":
            ui["clear"] = True
        elif k == "n":
            ui["next"] = True; ui["restart"] = True
        elif k == " ":
            ui["pause"] = not ui["pause"]
            print("  ⏸ 暂停" if ui["pause"] else "  ▶ 继续")
        elif k in "1234":
            ui["cam"] = int(k)
        elif k in "+=":
            ui["rate"] = min(ui["rate"] * 1.5, 8.0); print(f"  速度 x{ui['rate']:.1f}")
        elif k == "-":
            ui["rate"] = max(ui["rate"] / 1.5, 0.15); print(f"  速度 x{ui['rate']:.1f}")
        elif k == "q":
            ui["quit"] = True

    dt = substeps * m.opt.timestep
    print(f"桌上放纸, 纸面高={paper_top:.4f}m; 触角尖贴纸微弯, 落点留墨。")
    print("键位: r 重写 | c 清墨 | n 下一个字 | 1 俯视 2 斜视 3 侧视 4 全景 | 空格 暂停 | +/- 快慢 | q 退出")
    with viewer.launch_passive(m, d, key_callback=key_callback) as v:
        eye = np.eye(3).flatten()
        q_ik = np.zeros(6); ctrl = None; idx = 0; cam_applied = None; t = 0.0

        def ink():                                       # 笔尖贴近纸面 → 加一个持久墨点
            tp = d.xpos[tipid]
            if tp[2] <= paper_top + 0.003 and v.user_scn.ngeom < v.user_scn.maxgeom:
                g = v.user_scn.geoms[v.user_scn.ngeom]
                mujoco.mjv_initGeom(g, mujoco.mjtGeom.mjGEOM_SPHERE, [0.0012, 0, 0],
                                    tp.copy(), eye, np.array([0.05, 0.05, 0.05, 1.0]))
                v.user_scn.ngeom += 1

        while v.is_running() and not ui["quit"]:
            if ui["restart"]:                            # r / n: 回起笔位, 清墨, 重开
                if ui["next"]:
                    idx = (idx + 1) % len(chars); ui["next"] = False
                ch = chars[idx]
                wp = _writing_waypoints(ch)
                _, q_ik = ik(m, d, np.array(wp[0]), quat, iters=300)
                pin(q_ik); mujoco.mj_forward(m, d)
                ctrl = OpenLoopController(wp, speed=speed, fixed_ori=(math.pi, 0.0, 0.0))
                v.user_scn.ngeom = 0; t = 0.0; ui["restart"] = False
                print(f"写 '{ch}' ({len(wp)} 路点)")
            if ui["clear"]:
                v.user_scn.ngeom = 0; ui["clear"] = False
            if cam_applied != ui["cam"]:                 # 1/2/3/4: 切视角
                name, az, el, dist, look = CAM_PRESETS[ui["cam"]]
                with v.lock():
                    v.cam.azimuth = az; v.cam.elevation = el; v.cam.distance = dist
                    v.cam.lookat[:] = look if look is not None else paper_ctr
                cam_applied = ui["cam"]; print(f"  视角 {ui['cam']}: {name}")
            if ui["pause"] or ctrl.done():               # 暂停 / 写完: 只刷新, 保持可交互
                v.sync(); time.sleep(0.03); continue
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
            if ctrl.done():
                print(f"  写完 '{chars[idx]}' ({v.user_scn.ngeom} 墨点) — r 重写 / n 下一个字")
            if realtime:
                time.sleep(dt / ui["rate"])
            t += dt


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
        watch_write("".join(sys.argv[2:]) or "永")       # 可给多字: watch 永 書 王 (n 键切换)
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
