"""用真实字形中线(Make Me a Hanzi)在仿真里写一个汉字。

与 write_openloop 的区别: 轨迹来源是真实字形数据而非手编笔序, 因此任意
常用汉字都能写。仍是开环位置控制 —— 笔宽恒定, 提按留给 B2 触觉闭环。
"""

import os

from brushbot import config
from brushbot.backends.sim import SimBackend, ZeroTactile
from brushbot.calligraphy.hanzi import (
    load_medians,
    medians_to_strokes,
    strokes_to_waypoints,
)
from brushbot.calligraphy.render import render_trace
from brushbot.controller import OpenLoopController
from brushbot.run import run
from brushbot.scene import Scene

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_GRAPHICS = os.path.join(_REPO, "data", "makemeahanzi", "graphics.txt")


def write_hanzi(character, graphics_path=DEFAULT_GRAPHICS, size=0.032,
                zc_down=0.0045, gui=False, speed=0.018,
                out_png="/tmp/brushbot_hanzi.png"):
    """写一个汉字, 返回 {trace, png, n_down}。

    size: 字框边长(米)。zc_down: CalliRewrite z 帧的落笔压深(0.0045≈1.5mm 笔宽)。
    """
    strokes = medians_to_strokes(load_medians(character, graphics_path), size=size)
    z_down = config.PAPER_Z + (zc_down - config.Z_TOUCH_REF)
    wp = strokes_to_waypoints(strokes, config.CHAR_ORIGIN, z_down,
                              config.PAPER_Z + 0.03,
                              char_yaw_deg=config.CHAR_YAW_DEG)

    scene = Scene(gui=gui)
    scene.load()
    # 先把笔移到起点上方停稳再开始记录, 否则起笔瞬态会在纸面拖出墨迹。
    # 必须用同样的全位姿 IK: 若这里只约束位置, 姿态会停在 pitch≈-88°,
    # 控制环一开始要求笔杆垂直就会产生巨大跳变。
    scene.set_joints(scene.ik(wp[0], config.FIXED_ORI))
    for _ in range(240):
        scene.step()

    backend = SimBackend(scene, ZeroTactile(), substeps=6)
    controller = OpenLoopController(wp, speed=speed, fixed_ori=config.FIXED_ORI)
    trace = []
    run(backend, controller, on_tick=lambda s: trace.append(s.tcp_pose[:3]))
    scene.close()

    render_trace(trace, surface_z=config.PAPER_Z, out_path=out_png, px_per_m=7000)
    n_down = sum(1 for (x, y, z) in trace if z <= config.PAPER_Z + 0.002)
    return {"trace": trace, "png": out_png, "n_down": n_down}
