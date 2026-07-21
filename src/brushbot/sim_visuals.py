"""仿真里的可视化道具: 毛笔 + 纸(带实时墨迹贴图)。

纯视觉, 不参与物理与控制 —— 都是 mass=0、无碰撞体, 只为在 GUI 里看到
"机械臂拿笔在纸上一笔一划写字"。
"""

import os
import tempfile

import pybullet as p

from brushbot import config


def add_brush(client_id, bristle_len=0.020, handle_len=0.055):
    """挂一支毛笔(视觉体): 笔尖在 link 原点, 笔杆沿工具 -Z 伸出。

    因为 FIXED_ORI 让工具 +Z 朝下, -Z 即向上, 所以笔杆朝上、笔尖触纸。
    """
    shape = p.createVisualShapeArray(
        shapeTypes=[p.GEOM_CYLINDER, p.GEOM_CYLINDER],
        radii=[0.0035, 0.005],
        lengths=[bristle_len, handle_len],
        visualFramePositions=[
            [0, 0, -bristle_len / 2.0],                      # 笔毫
            [0, 0, -bristle_len - handle_len / 2.0],         # 笔杆
        ],
        rgbaColors=[[0.12, 0.10, 0.10, 1], [0.55, 0.35, 0.15, 1]],
        physicsClientId=client_id,
    )
    return p.createMultiBody(baseMass=0, baseVisualShapeIndex=shape,
                             physicsClientId=client_id)


def follow_tcp(brush_id, robot_id, eef_link, client_id):
    """毛笔跟随末端 link 的位姿(用 link 坐标系, 与 IK 目标一致)。"""
    state = p.getLinkState(robot_id, eef_link, physicsClientId=client_id)
    p.resetBasePositionAndOrientation(brush_id, state[4], state[5],
                                      physicsClientId=client_id)


_PAPER_OBJ = os.path.join(os.path.dirname(__file__), "assets", "paper.obj")


def add_paper(canvas, client_id):
    """在 PAPER_Z 铺一张纸(带 UV 的四边形网格), 返回 bodyId。

    必须用网格: PyBullet 的程序化 GEOM_BOX 没有 UV 坐标, 贴不上图
    (实测 loadTexture / changeTexture 都无效, 纸永远是白的)。
    """
    shape = p.createVisualShape(p.GEOM_MESH, fileName=_PAPER_OBJ,
                                meshScale=[canvas.size, canvas.size, 1],
                                physicsClientId=client_id)
    body = p.createMultiBody(
        baseMass=0, baseVisualShapeIndex=shape,
        basePosition=[canvas.cx, canvas.cy, config.PAPER_Z],
        physicsClientId=client_id)
    push_ink(canvas, body, client_id)
    return body


def add_table(canvas, client_id, height=None):
    """在纸下面垫一张桌子, 免得纸浮在半空看着别扭(纯视觉)。"""
    top = config.PAPER_Z if height is None else height
    half_xy = canvas.size / 2.0 + 0.03
    shape = p.createVisualShape(p.GEOM_BOX,
                                halfExtents=[half_xy, half_xy, top / 2.0],
                                rgbaColor=[0.45, 0.33, 0.22, 1],
                                physicsClientId=client_id)
    return p.createMultiBody(baseMass=0, baseVisualShapeIndex=shape,
                             basePosition=[canvas.cx, canvas.cy, top / 2.0 - 0.002],
                             physicsClientId=client_id)


_ink_counter = [0]


def push_ink(canvas, paper_id, client_id):
    """把画布刷到纸上(墨迹随之浮现)。

    只能走"落盘 -> loadTexture -> changeVisualShape": pybullet 的
    changeTexture 实测不刷新(纸面不变), 是这里唯一可行的更新路径。
    """
    # 文件名必须每次不同: pybullet 按文件名缓存贴图, 重名会拿到旧图(纸不更新)
    _ink_counter[0] += 1
    path = os.path.join(tempfile.gettempdir(),
                        f"brushbot_paper_{os.getpid()}_{_ink_counter[0]}.png")
    canvas.image.save(path)
    texture = p.loadTexture(path, physicsClientId=client_id)
    p.changeVisualShape(paper_id, -1, textureUniqueId=texture,
                        physicsClientId=client_id)
