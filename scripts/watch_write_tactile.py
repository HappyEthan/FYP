"""本机 GUI: Elfin 写字, 笔尖一根可见触角随压深/拖拽弯曲, 旁边实时滚动 ΔB 曲线.

跑(需显示器): conda run -n brushbot python scripts/watch_write_tactile.py 永
无显示时用 gui=False 只验证逻辑: ... watch_write_tactile.py 永 nogui
"""
import sys
import numpy as np
import pybullet as p

from brushbot import config
from brushbot.scene import Scene
from brushbot.backends.sim import SimBackend, ZeroTactile
from brushbot.controller import OpenLoopController
from brushbot.run import run
from brushbot.calligraphy.hanzi import load_medians, medians_to_strokes, strokes_to_waypoints
from brushbot.write_hanzi import DEFAULT_GRAPHICS
from brushbot.tactile.antenna_model import bent_centerline
from brushbot.tactile.writing_tactile import PRESS_AZIM, K_PRESS, K_DRAG, PEN_EPS
from brushbot.tactile.separability import dB_bend, B0MAG


def _waypoints(char):
    strokes = medians_to_strokes(load_medians(char, DEFAULT_GRAPHICS), size=0.032)
    z_down = config.PAPER_Z + (0.0045 - config.Z_TOUCH_REF)
    z_up = config.PAPER_Z + 0.03
    return strokes_to_waypoints(strokes, config.CHAR_ORIGIN, z_down, z_up,
                                char_yaw_deg=config.CHAR_YAW_DEG)


def _bend_now(tip_prev, tip):
    """当前笔尖 → (总弯角 deg, 弯方位 deg, ΔB三轴). 压+拖 合成."""
    pen = config.PAPER_Z - tip[2]
    if pen <= PEN_EPS:
        return 0.0, 0.0, np.zeros(3)
    # 压(法向, 固定方位) 的弯向量
    th_p = K_PRESS * pen * 1000.0
    vp = th_p * np.array([np.cos(np.radians(PRESS_AZIM)), np.sin(np.radians(PRESS_AZIM))])
    b = dB_bend(th_p, PRESS_AZIM)
    # 拖(反运动方向)
    d = np.array(tip[:2]) - np.array(tip_prev[:2])
    sp = np.hypot(d[0], d[1])
    if sp > 1e-6:
        az = np.degrees(np.arctan2(d[1], d[0])) + 180.0
        th_d = K_DRAG * sp
        vp = vp + th_d * np.array([np.cos(np.radians(az)), np.sin(np.radians(az))])
        b = b + dB_bend(th_d, az)
    theta = float(np.hypot(vp[0], vp[1]))
    azim = float(np.degrees(np.arctan2(vp[1], vp[0])))
    return theta, azim, b


def _draw_antenna(tip, theta, azim, prev_ids):
    """在笔尖画一根弯的触角(调试线). 返回线的 id 列表(下次替换)."""
    pos, _ = bent_centerline(np.radians(theta), L=20.0, N=10, azimuth_deg=azim)
    world = np.array(tip)[None, :] + pos * 0.001          # mm→m, 根在笔尖
    ids = []
    for i in range(len(world) - 1):
        rid = prev_ids[i] if i < len(prev_ids) else -1
        ids.append(p.addUserDebugLine(world[i], world[i + 1], [0.1, 0.4, 0.9],
                                      lineWidth=4, replaceItemUniqueId=rid))
    return ids


def main(char="永", gui=True):
    wp = _waypoints(char)
    sc = Scene(gui=gui); sc.load()
    sc.set_joints(sc.ik(wp[0], config.FIXED_ORI))
    for _ in range(240):
        sc.step()
    backend = SimBackend(sc, ZeroTactile(), substeps=4)
    ctrl = OpenLoopController(wp, speed=0.018, fixed_ori=config.FIXED_ORI)

    live = None
    if gui:
        try:
            import matplotlib; matplotlib.use("TkAgg"); import matplotlib.pyplot as plt
            plt.ion(); fig, ax = plt.subplots(figsize=(6, 3))
            ax.set_title("antenna ΔB (live)"); ax.set_ylabel("% of |B0|"); ax.set_xlabel("tick")
            live = (plt, fig, ax)
        except Exception as e:
            print("实时曲线不可用(继续跑仿真):", e)

    buf, line_ids, prev = [], [], [wp[0]]

    def on_tick(state):
        tip = state.tcp_pose[:3]
        theta, azim, b = _bend_now(prev[0], tip)
        prev[0] = tip
        buf.append([b[0] / B0MAG * 100, b[1] / B0MAG * 100, b[2] / B0MAG * 100])
        if gui:
            line_ids[:] = _draw_antenna(tip, theta, azim, line_ids)
            if live and len(buf) % 8 == 0:
                plt, fig, ax = live
                a = np.array(buf[-300:])
                ax.clear(); ax.set_ylim(-2, 6)
                ax.plot(a[:, 0], label="dBx"); ax.plot(a[:, 1], label="dBy")
                ax.plot(a[:, 2], "k", label="dBz")
                ax.plot(np.hypot(a[:, 0], a[:, 1]), "--", color="crimson", label="|dBxy|")
                ax.legend(fontsize=7, loc="upper right")
                plt.pause(0.001)
            import time; time.sleep(1 / 240)

    run(backend, ctrl, on_tick=on_tick)
    nc = sum(1 for r in buf if np.hypot(r[0], r[1]) > 0.1)
    print(f"完成: {len(buf)} 拍, 接触拍 {nc}")
    if gui:
        print("看窗口. 回车退出."); input()
    sc.close()


if __name__ == "__main__":
    char = sys.argv[1] if len(sys.argv) > 1 else "永"
    gui = not (len(sys.argv) > 2 and sys.argv[2] == "nogui")
    main(char, gui=gui)
