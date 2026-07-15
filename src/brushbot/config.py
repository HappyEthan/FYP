import math
import pybullet_data
import os

# 默认用 pybullet 自带 KUKA 起步; 换 Elfin5 时改这一行为 Elfin URDF 路径
ARM_URDF = os.path.join(pybullet_data.getDataPath(), "kuka_iiwa", "model.urdf")
EEF_LINK = 6            # KUKA 末端 link index (7-DOF: 0..6)
PAPER_Z = 0.2          # 书写平面高度 (米), 选臂可达的中间高度; 仿真里纸是抽象 z 平面
Z_TOUCH_REF = 0.009    # CalliRewrite z 帧里"刚触纸"的参考 z (func_brush 上端附近)
FIXED_ORI = (math.pi, 0.0, 0.0)   # 笔杆垂直 (随 URDF 调; 本阶段 IK 只约束位置)
CHAR_ORIGIN = (0.45, 0.0)         # 字在书写平面上的中心 (x,y 米), 保证臂可达
TICK_DT = 1.0 / 240.0
