"""将既有笔尖轨迹离线映射为合成触觉 ΔB，不依赖特定仿真平台。

思路(不做重物理耦合): 写字照旧(Elfin 开环), 每一拍从运动算触角形变:
  - 压深 penetration = PAPER_Z - z_tip (>0=压入纸)  → 法向弯(提按分量, 固定屈曲方位)
  - 横向位移 dxy                                     → 拖拽弯(方向=反运动方向)
  - 只在接触时(penetration>阈值)有信号; 抬笔→ΔB=0
形变经触角模型 sensor_B → 合成 ΔB。输入轨迹可以来自独立的仿真或回放；
这里不执行机械臂书写。见 docs/06-mujoco-simulation-platform/archive/fem-design.md / deltaB-control.md.
"""
import numpy as np
from brushbot import config
from brushbot.tactile.separability import dB_bend

PRESS_AZIM = 40.0      # 触角轴向压的屈曲方位(触角固定属性, deg)
K_PRESS = 7.0          # 压弯增益: deg per mm 穿透
K_DRAG = 1200.0        # 拖弯增益: deg per (m 每拍横向位移)
PEN_EPS = 5e-4         # 0.5mm 穿透 = 接触阈值


def tactile_from_trace(trace):
    """逐拍笔尖位置 (F,3) → 合成 ΔB (F,3) 与 接触布尔 (F,)."""
    tr = np.asarray(trace, float)
    dxy = np.diff(tr[:, :2], axis=0, prepend=tr[:1, :2])      # 每拍横向位移
    dB = np.zeros((len(tr), 3))
    contact = np.zeros(len(tr), bool)
    for i in range(len(tr)):
        pen = config.PAPER_Z - tr[i, 2]                       # 穿透(m)
        if pen <= PEN_EPS:
            continue                                          # 抬笔: 无接触
        contact[i] = True
        b = dB_bend(K_PRESS * pen * 1000.0, PRESS_AZIM)       # 法向(提按)
        sp = np.hypot(dxy[i, 0], dxy[i, 1])
        if sp > 1e-6:
            az = np.degrees(np.arctan2(dxy[i, 1], dxy[i, 0])) + 180.0   # 反运动方向
            b = b + dB_bend(K_DRAG * sp, az)                  # 拖拽
        dB[i] = b
    return dB, contact
