import math
import os

# Elfin5 (大族 6-DOF 协作臂, 真机同款). URDF 由官方 elfin_description 的 xacro 展开而来.
# 6-DOF 非冗余 -> 位置-only IK 精确, 无 KUKA 那种解支跳变. 换回 KUKA 只需改这两行.
_ELFIN5_URDF = os.path.join(os.path.dirname(__file__), "assets", "elfin5", "elfin5.urdf")
ARM_URDF = _ELFIN5_URDF
EEF_LINK = 9           # elfin_dummy_gripper (工具 TCP); 6 revolute=idx2..7, end_link=8, tcp=9
PAPER_Z = 0.2          # 书写平面高度 (米), 选臂可达的中间高度; 仿真里纸是抽象 z 平面
Z_TOUCH_REF = 0.009    # CalliRewrite z 帧里"刚触纸"的参考 z (func_brush 上端附近)
FIXED_ORI = (math.pi, 0.0, 0.0)   # 笔杆垂直 (随 URDF 调; 本阶段 IK 只约束位置)
CHAR_ORIGIN = (0.45, 0.0)         # 字在书写平面上的中心 (x,y 米), 保证臂可达
TICK_DT = 1.0 / 240.0
