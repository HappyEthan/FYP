from brushbot import config
from brushbot.scene import Scene
from brushbot.backends.sim import SimBackend, ZeroTactile
from brushbot.controller import OpenLoopController
from brushbot.calligraphy.strokeseq import process
from brushbot.calligraphy.calibration import func_brush
from brushbot.calligraphy.render import render_trace
from brushbot.run import run

def write(seq, gui=False, speed=0.05, out_png="/tmp/brushbot_out.png"):
    # 1. 笔序 -> 米制 (x,y,z) 路点
    pts = process(seq, func_brush, alpha=0.04, beta=0.5)
    # 2. 平移到书写平面可达中心; z 从 CalliRewrite 帧映射到仿真帧:
    #    z_sim = PAPER_Z + (zc - Z_TOUCH_REF)  (触纸->平面, 压->平面下, 抬->平面上)
    ox, oy = config.CHAR_ORIGIN
    wp = [(x + ox, y + oy, config.PAPER_Z + (z - config.Z_TOUCH_REF))
          for (x, y, z) in pts]
    # 3. 搭场景 + 后端; 先用同样的全位姿 IK 把笔移到起点停稳
    #    (姿态受控后, 从零位直接起步会因姿态突变而甩飞)
    sc = Scene(gui=gui); sc.load()
    sc.set_joints(sc.ik(wp[0], config.FIXED_ORI))
    for _ in range(240):
        sc.step()
    backend = SimBackend(sc, ZeroTactile(), substeps=4)
    ctrl = OpenLoopController(wp, speed=speed, fixed_ori=config.FIXED_ORI)
    # 4. 跑开环, 记录笔尖轨迹
    trace = []
    run(backend, ctrl, on_tick=lambda s: trace.append(s.tcp_pose[:3]))
    sc.close()
    # 5. 渲染墨迹 (纸面 = PAPER_Z)
    render_trace(trace, surface_z=config.PAPER_Z, out_path=out_png)
    n_down = sum(1 for (x, y, z) in trace if z <= config.PAPER_Z + 0.002)
    return {"trace": trace, "png": out_png, "n_down": n_down}
