"""HuayanBackend: 华沿 Elfin 实机后端, 走 vendor CPS.py (明文 TCP 协议).

单位纪律: 对外 (State/Command) 一律 SI (米/弧度), HRIF 线上格式 (毫米/度)
只存在于本模块的换算函数里。姿态角 Rx/Ry/Rz 与 roll/pitch/yaw 的对应关系
未上机验证, B1 阶段建议姿态用示教器抄录的常量直通 (见 docs)。
"""
import math
import time

from brushbot.types import State, Command


class HuayanError(RuntimeError):
    """HRIF 命令返回失败错误码。"""


class HuayanBackend:
    """RobotBackend 实现。client 为 vendor CPS.CPSClient (或同签名替身)。

    servo_dt 必须与 start_servo() 告知控制器的推送周期一致, 运行循环
    需以同一周期定频调用 write() —— 这是伺服流的硬契约。
    """

    def __init__(self, client, servo_dt, lookahead=0.2,
                 tool_coord=(0.0,) * 6, user_coord=(0.0,) * 6,
                 tactile=None, clock=None):
        self.client = client
        self.servo_dt = servo_dt
        self.lookahead = lookahead
        self.tool_coord = list(tool_coord)   # 毫米/度, 示教器标定值直接抄入
        self.user_coord = list(user_coord)
        self.tactile = tactile               # None -> g_meas 恒 0 (B1 开环)
        self._clock = clock if clock is not None else time.monotonic
        self._t0 = self._clock()

    def start_servo(self) -> None:
        ret = self.client.HRIF_StartServo(self.servo_dt, self.lookahead)
        if ret[0] != "0":
            raise HuayanError(f"StartServo failed: {ret!r}")

    def read(self) -> State:
        ret = self.client.HRIF_ReadActTcpPos()
        if ret[0] != "0":
            raise HuayanError(f"ReadActTcpPos failed: {ret!r}")
        g = self.tactile.value() if self.tactile is not None else 0.0
        return State(tcp_pose=_hrif_to_si(ret[1:7]),
                     g_meas=g,
                     t=self._clock() - self._t0)

    def write(self, cmd: Command) -> None:
        # vendor 签名: HRIF_PushServoP(pose, ucs, tcp) —— ucs 在前 (与 PDF 手册不同)
        ret = self.client.HRIF_PushServoP(
            _si_to_hrif(cmd.tcp_pose), self.user_coord, self.tool_coord)
        if ret[0] != "0":
            raise HuayanError(f"PushServoP failed: {ret!r}")


def _si_to_hrif(pose):
    """(x,y,z,roll,pitch,yaw) 米/弧度 -> [X,Y,Z,Rx,Ry,Rz] 毫米/度."""
    x, y, z, roll, pitch, yaw = pose
    return [x * 1000.0, y * 1000.0, z * 1000.0,
            math.degrees(roll), math.degrees(pitch), math.degrees(yaw)]


def _hrif_to_si(fields):
    """HRIF 回复的 6 个字符串字段 (毫米/度) -> (x,y,z,roll,pitch,yaw) 米/弧度."""
    if len(fields) != 6:
        raise ValueError(f"expect 6 pose fields, got {len(fields)}: {fields!r}")
    x, y, z, rx, ry, rz = (float(v) for v in fields)
    return (x / 1000.0, y / 1000.0, z / 1000.0,
            math.radians(rx), math.radians(ry), math.radians(rz))
