import math
import os

# Elfin5 (大族 6-DOF 协作臂, 真机同款). URDF 由官方 elfin_description 的 xacro 展开而来.
# 6-DOF 非冗余 -> 位置-only IK 精确, 无 KUKA 那种解支跳变. 换回 KUKA 只需改这两行.
_ELFIN5_URDF = os.path.join(os.path.dirname(__file__), "assets", "elfin5", "elfin5.urdf")
ARM_URDF = _ELFIN5_URDF
EEF_LINK = 9           # elfin_dummy_gripper (工具 TCP); 6 revolute=idx2..7, end_link=8, tcp=9
PAPER_Z = 0.2          # 书写平面高度 (米), 选臂可达的中间高度; 仿真里纸是抽象 z 平面
Z_TOUCH_REF = 0.009    # CalliRewrite z 帧里"刚触纸"的参考 z (func_brush 上端附近)
# 笔杆垂直: roll=180° 使工具 Z 轴朝下。yaw 是自由参数(毛笔绕自身轴对称),
# 选 90° 是因为 yaw=0 会把 J1/J4/J6 顶死在 ±180° 限位上(书写区余量 -3°,
# 导致 y 负半边走不了); yaw=±90° 余量 +37°, 最宽裕。
FIXED_ORI = (math.pi, 0.0, math.pi / 2)
CHAR_YAW_DEG = -90.0   # 字在纸上的朝向: 让字的"上"朝远离底座的方向(否则看着是躺倒的)
CHAR_ORIGIN = (0.45, 0.0)         # 字在书写平面上的中心 (x,y 米), 保证臂可达
TICK_DT = 1.0 / 240.0
# 关节位置控制的力矩上限(仿真用, 非真机规格)。姿态受约束后 200 不够:
# 改回 200 会有 5 个测试失败且套件耗时从 2s 涨到 38s(机械臂跟不上目标);
# 2000 时全部通过。
JOINT_MAX_FORCE = 2000.0
