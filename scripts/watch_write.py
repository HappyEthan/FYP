"""看着 Elfin5 拿毛笔在纸上一笔一划写字, 墨迹实时浮现, 可反复重写。

    python scripts/watch_write.py 永
    python scripts/watch_write.py 永 書 王        # 多个字, 按 n 换下一个
    python scripts/watch_write.py 永 --headless   # 不开窗, 只出图

薄封装: 控制逻辑都在已测过的 brushbot.* 里, 这里只负责开窗/放慢/
挂毛笔铺纸/刷墨迹/交互按键。
"""

import sys
import time

import pybullet as p

from brushbot import config, sim_visuals
from brushbot.backends.sim import SimBackend, ZeroTactile
from brushbot.calligraphy.hanzi import (
    load_medians,
    medians_to_strokes,
    strokes_to_waypoints,
)
from brushbot.calligraphy.inkcanvas import InkCanvas
from brushbot.calligraphy.render import render_trace
from brushbot.controller import OpenLoopController
from brushbot.run import run
from brushbot.scene import Scene
from brushbot.write_hanzi import DEFAULT_GRAPHICS

PAPER_SIZE = 0.10          # 纸边长(米)
INK_WIDTH = 0.0015         # 墨迹线宽(米), 与恒定压深对应
REFRESH_EVERY = 20         # 每多少拍把墨迹刷到纸上

# 预设视角 (说明, 距离, yaw, pitch, 目标点偏向底座的比例)
# yaw=270 让机械臂底座落在画面下方(像人坐在纸前朝外写); yaw=0 会把底座甩到左边。
VIEWS = {
    "1": ("俯视(看字最清楚)", 0.26, 270.0, -89.0, 0.0),
    "2": ("斜视(默认)", 0.62, 270.0, -38.0, 0.05),
    "3": ("侧视(看抬笔落笔)", 0.55, 180.0, -10.0, 0.0),
    "4": ("全景(看整臂)", 1.20, 270.0, -35.0, 0.45),
}


def set_view(client_id, key="2"):
    _, dist, yaw, pitch, back = VIEWS[key]
    cx, cy = config.CHAR_ORIGIN
    p.resetDebugVisualizerCamera(cameraDistance=dist, cameraYaw=yaw,
                                 cameraPitch=pitch,
                                 cameraTargetPosition=[cx * (1 - back), cy,
                                                       config.PAPER_Z],
                                 physicsClientId=client_id)


def park(scene):
    """写完把笔抬高挪开, 好让人看清纸上的字(真人写完也会把笔拿开)。"""
    cx, cy = config.CHAR_ORIGIN
    # 停到侧上方: 往底座方向退会正好挡住默认视角(相机在底座一侧)
    scene.set_joints(scene.ik([cx, cy + 0.20, config.PAPER_Z + 0.28],
                              config.FIXED_ORI))
    for _ in range(300):
        scene.step()


def build_waypoints(character, size=0.032, zc_down=0.0045):
    strokes = medians_to_strokes(
        load_medians(character, DEFAULT_GRAPHICS), size=size)
    z_down = config.PAPER_Z + (zc_down - config.Z_TOUCH_REF)
    wp = strokes_to_waypoints(strokes, config.CHAR_ORIGIN, z_down,
                              config.PAPER_Z + 0.03,
                              char_yaw_deg=config.CHAR_YAW_DEG)
    return strokes, wp


def write_once(scene, canvas, paper, brush, wp, speed=0.018, pace=0.006):
    """跑一遍轨迹, 边写边把墨刷到纸上, 返回笔尖轨迹。"""
    scene.set_joints(scene.ik(wp[0], config.FIXED_ORI))   # 先到起点停稳
    for _ in range(240):
        scene.step()

    backend = SimBackend(scene, ZeroTactile(), substeps=6)
    controller = OpenLoopController(wp, speed=speed, fixed_ori=config.FIXED_ORI)
    trace = []
    st = {"prev": None, "n": 0}
    down_z = config.PAPER_Z + 0.002

    def tick(state):
        pos = state.tcp_pose[:3]
        trace.append(pos)
        st["n"] += 1
        sim_visuals.follow_tcp(brush, scene.robot, config.EEF_LINK, scene.cid)
        if pos[2] <= down_z:                       # 落笔 -> 留墨
            if st["prev"] is not None:
                canvas.stroke(st["prev"][0], st["prev"][1],
                              pos[0], pos[1], INK_WIDTH)
            st["prev"] = pos
        else:
            st["prev"] = None                      # 抬笔 -> 断开
        if st["n"] % REFRESH_EVERY == 0:
            sim_visuals.push_ink(canvas, paper, scene.cid)
        if pace:
            time.sleep(pace)

    run(backend, controller, on_tick=tick)
    sim_visuals.push_ink(canvas, paper, scene.cid)
    park(scene)                                    # 抬笔挪开, 露出成品字
    sim_visuals.follow_tcp(brush, scene.robot, config.EEF_LINK, scene.cid)
    return trace


def _save(trace, canvas, out_png):
    render_trace(trace, surface_z=config.PAPER_Z, out_path=out_png, px_per_m=7000)
    paper_png = out_png.replace(".png", "-paper.png")
    canvas.image.save(paper_png)
    n_down = sum(1 for (x, y, z) in trace if z <= config.PAPER_Z + 0.002)
    print(f"写完: 落笔点 {n_down} | 墨迹图 -> {out_png} | 纸面 -> {paper_png}")


def _pressed(keys, ch):
    return ord(ch) in keys and keys[ord(ch)] & p.KEY_WAS_TRIGGERED


def run_session(characters, out_png, gui=True, pace=0.006, hold=True,
                size=0.032, zc_down=0.0045, speed=0.018):
    scene = Scene(gui=gui)
    scene.load()
    canvas = InkCanvas(config.CHAR_ORIGIN, PAPER_SIZE, resolution=512)
    sim_visuals.add_table(canvas, scene.cid)
    paper = sim_visuals.add_paper(canvas, scene.cid)
    brush = sim_visuals.add_brush(scene.cid)
    if gui:
        set_view(scene.cid, "2")

    idx = 0

    def write(i):
        strokes, wp = build_waypoints(characters[i], size, zc_down)
        print(f"{characters[i]}: {len(strokes)} 笔, {len(wp)} 个路点")
        trace = write_once(scene, canvas, paper, brush, wp, speed, pace)
        _save(trace, canvas, out_png)

    write(idx)

    if hold:
        print("\n窗口保持可交互 —— 鼠标: 左键拖=转视角 | 滚轮=缩放 | Ctrl拖=平移")
        print("  r = 清纸重写当前字      c = 只清纸")
        print("  n = 换下一个字" + (f" (共 {len(characters)} 个)" if len(characters) > 1 else " (只给了一个字)"))
        for k, (name, *_r) in VIEWS.items():
            print(f"  {k} = {name}")
        print("  q = 退出\n")
        while True:
            try:
                keys = p.getKeyboardEvents(physicsClientId=scene.cid)
            except p.error:
                break                              # 窗口被关掉
            if _pressed(keys, "q"):
                break
            if _pressed(keys, "c"):
                canvas.clear()
                sim_visuals.push_ink(canvas, paper, scene.cid)
                print("纸已清空")
            if _pressed(keys, "r"):
                canvas.clear()
                sim_visuals.push_ink(canvas, paper, scene.cid)
                write(idx)
            if _pressed(keys, "n"):
                idx = (idx + 1) % len(characters)
                canvas.clear()
                sim_visuals.push_ink(canvas, paper, scene.cid)
                write(idx)
            for k in VIEWS:
                if _pressed(keys, k):
                    set_view(scene.cid, k)
            time.sleep(1.0 / 60.0)
    scene.close()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    headless = "--headless" in sys.argv
    characters = args or ["永"]
    out_png = f"/tmp/brushbot_{characters[0]}.png"
    run_session(characters, out_png,
                gui=not headless, pace=0.0 if headless else 0.006,
                hold=not headless)


if __name__ == "__main__":
    main()
