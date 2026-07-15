from dataclasses import dataclass

@dataclass
class State:
    tcp_pose: tuple   # (x, y, z, roll, pitch, yaw) 米/弧度
    g_meas: float     # 触觉提按分量 (B1 开环恒为 0)
    t: float          # 仿真时间 (秒)

@dataclass
class Command:
    tcp_pose: tuple   # 目标 (x, y, z, roll, pitch, yaw)
