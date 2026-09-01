import math
import xmlrpc.client

import pytest

from brushbot.backends.vendor import CPS
from brushbot.backends.huayan import (
    HuayanBackend, HuayanError, _si_to_hrif, _hrif_to_si)
from brushbot.types import Command


class FakeTcp:
    """替身 socket: 记录发送内容, 按预设回复应答。"""
    def __init__(self, reply: bytes):
        self.reply = reply
        self.sent = []

    def send(self, data: bytes):
        self.sent.append(data)

    def recv(self, bufsize: int) -> bytes:
        return self.reply


class FakeRpc:
    """替身 xmlrpc 客户端: vendor 的 Fail 路径会调 rpcClient.HRLog 上报日志。"""
    def __init__(self):
        self.logs = []

    def HRLog(self, level, msg):
        self.logs.append((level, msg))


def client_with_reply(reply: bytes) -> CPS.CPSClient:
    # 绕过 __init__: 真构造函数会立刻连接控制器, 单测里不可用
    c = CPS.CPSClient.__new__(CPS.CPSClient)
    c.tcp = FakeTcp(reply)
    c.rpcClient = FakeRpc()
    return c


class TestUnitConversion:
    def test_si_to_hrif_known_values(self):
        # (0.45m, 0, 0.2m, pi, 0, pi/2) -> (450mm, 0, 200mm, 180deg, 0, 90deg)
        pose = (0.45, 0.0, 0.2, math.pi, 0.0, math.pi / 2)
        assert _si_to_hrif(pose) == pytest.approx(
            [450.0, 0.0, 200.0, 180.0, 0.0, 90.0])

    def test_hrif_to_si_known_values(self):
        fields = ["450.0", "0.0", "200.0", "180.0", "0.0", "90.0"]
        assert _hrif_to_si(fields) == pytest.approx(
            (0.45, 0.0, 0.2, math.pi, 0.0, math.pi / 2))

    def test_round_trip(self):
        pose = (0.123, -0.456, 0.789, 0.1, -0.2, 0.3)
        back = _hrif_to_si([str(v) for v in _si_to_hrif(pose)])
        assert back == pytest.approx(pose)

    def test_hrif_to_si_rejects_non_numeric(self):
        # fail loud: 控制器回了非数字字段, 必须带原始内容抛错
        with pytest.raises(ValueError, match="oops"):
            _hrif_to_si(["450.0", "oops", "200.0", "180.0", "0.0", "90.0"])

    def test_hrif_to_si_rejects_wrong_length(self):
        with pytest.raises(ValueError):
            _hrif_to_si(["450.0", "0.0"])


POSE_FIELDS = ["450.0", "0.0", "200.0", "180.0", "0.0", "90.0"]
POSE_SI = (0.45, 0.0, 0.2, math.pi, 0.0, math.pi / 2)


class FakeCPSClient:
    """替身 CPSClient: 记录调用, 按预设返回。签名与 vendor CPS.py 一致。"""
    def __init__(self, read_reply=None, push_reply=None, servo_reply=None):
        self.read_reply = read_reply or (["0"] + POSE_FIELDS)
        self.push_reply = push_reply or ["0"]
        self.servo_reply = servo_reply or ["0"]
        self.pushed = []       # [(pose, ucs, tcp)]
        self.servo_calls = []  # [(servo_time, lookahead)]

    def HRIF_ReadActTcpPos(self):
        return self.read_reply

    def HRIF_PushServoP(self, pose, ucs, tcp):
        self.pushed.append((list(pose), list(ucs), list(tcp)))
        return self.push_reply

    def HRIF_StartServo(self, servoTime, lookaheadTime):
        self.servo_calls.append((servoTime, lookaheadTime))
        return self.servo_reply


class FakeClock:
    def __init__(self):
        self.t = 100.0  # 非零起点: 验证 State.t 是相对启动时刻的

    def __call__(self):
        return self.t


def make_backend(client=None, **kwargs):
    kwargs.setdefault("servo_dt", 0.02)
    kwargs.setdefault("clock", FakeClock())
    return HuayanBackend(client or FakeCPSClient(), **kwargs)


class TestHuayanBackend:
    def test_read_returns_si_state(self):
        clock = FakeClock()
        b = make_backend(clock=clock)
        clock.t += 0.5
        st = b.read()
        assert st.tcp_pose == pytest.approx(POSE_SI)
        assert st.g_meas == 0.0
        assert st.t == pytest.approx(0.5)  # 相对构造时刻, 不是墙钟绝对值

    def test_read_error_code_raises(self):
        b = make_backend(FakeCPSClient(read_reply=["1023"]))
        with pytest.raises(HuayanError, match="1023"):
            b.read()

    def test_write_pushes_mm_deg_with_tool_and_user_coords(self):
        tool = (1.0, 2.0, 3.0, 0.0, 0.0, 0.0)
        client = FakeCPSClient()
        b = make_backend(client, tool_coord=tool)
        b.write(Command(tcp_pose=POSE_SI))
        (pose, ucs, tcp), = client.pushed
        assert pose == pytest.approx([450.0, 0.0, 200.0, 180.0, 0.0, 90.0])
        assert ucs == [0.0] * 6          # 默认用户坐标全零
        assert tcp == pytest.approx(list(tool))  # 工具坐标原样透传, ucs 在前 tcp 在后

    def test_write_error_code_raises(self):
        b = make_backend(FakeCPSClient(push_reply=["1040"]))
        with pytest.raises(HuayanError, match="1040"):
            b.write(Command(tcp_pose=POSE_SI))

    def test_start_servo_uses_servo_dt_and_lookahead(self):
        client = FakeCPSClient()
        b = make_backend(client, servo_dt=0.02, lookahead=0.2)
        b.start_servo()
        assert client.servo_calls == [(0.02, 0.2)]

    def test_start_servo_error_raises(self):
        b = make_backend(FakeCPSClient(servo_reply=["1005"]))
        with pytest.raises(HuayanError, match="1005"):
            b.start_servo()


class TestVendorSendAndRecv:
    def test_malformed_reply_raises_instead_of_exit(self):
        # 原版 CPS.py 收到少于 3 段的回复会 os._exit(0) 杀死进程,
        # 真机写字中途进程消失不可接受 -> vendor 补丁应改为抛异常
        c = client_with_reply(b"junk")
        with pytest.raises(CPS.HRIFProtocolError):
            c.sendAndRecv("ReadActPos,0,;")

    def test_errorcmd_reply_raises_instead_of_exit(self):
        c = client_with_reply(b"errorcmd,x,y,;")
        with pytest.raises(CPS.HRIFProtocolError):
            c.sendAndRecv("ReadActPos,0,;")

    def test_ok_reply_returns_payload_strings(self):
        # 成功路径行为必须与原版一致: 首段命令名剥掉, OK -> '0', 尾段 ';' 弹出
        c = client_with_reply(b"ReadActPos,OK,450.0,0.0,200.0,180.0,0.0,90.0,;")
        assert c.sendAndRecv("ReadActPos,0,;") == [
            "0", "450.0", "0.0", "200.0", "180.0", "0.0", "90.0"]

    def test_fail_reply_returns_error_when_hrlog_raises(self):
        # 真机 (Elfin E5, 2026-08-28): 该控制器 XML-RPC 未实现 HRLog 方法,
        # sendAndRecv 在 Fail 分支调 sendHRLog 会抛 xmlrpc Fault, 掩盖真错误码.
        # 日志上报是副作用, 必须不阻断错误返回.
        c = client_with_reply(b"HRAppCmd,Fail,60000,;")

        class FaultyRpc:
            def HRLog(self, level, msg):
                raise xmlrpc.client.Fault(-1, "HRLog: unknown method name")

        c.rpcClient = FaultyRpc()
        assert c.sendAndRecv("HRAppCmd,hr_gri_plugins,IsMoving,0,;") == ["60000"]


# 真机实测 (Elfin E5, 2026-08-10) ReadActPos 回复共 24 段 payload:
# [0..5]=关节角 J1-J6, [6..11]=实际 TCP 位姿, [12..23]=零 (未用段)。
# 原版 CPS.py 的 HRIF_ReadActTcpPos 误切关节角段, 示教器对拍时暴露。
_READACTPOS_JOINTS = ["96.588", "-40.114", "83.303", "0.002", "58.487", "0.011"]
_READACTPOS_TCP = ["-67.669", "585.849", "104.431", "179.999", "-1.904", "-83.423"]
_READACTPOS_REPLY = (
    "ReadActPos,OK," + ",".join(_READACTPOS_JOINTS + _READACTPOS_TCP)
    + "," + ",".join(["0.000"] * 12) + ",;").encode()


class TestVendorReadActTcpPos:
    def test_returns_tcp_fields_not_joint_fields(self):
        c = client_with_reply(_READACTPOS_REPLY)
        assert c.HRIF_ReadActTcpPos() == ["0"] + _READACTPOS_TCP

    def test_short_reply_raises(self):
        # 老布局/异常回复不足 13 段时不允许静默切错段
        c = client_with_reply(b"ReadActPos,OK,1.0,2.0,3.0,4.0,5.0,6.0,;")
        with pytest.raises(CPS.HRIFProtocolError):
            c.HRIF_ReadActTcpPos()

    def test_error_code_passthrough(self):
        c = client_with_reply(b"ReadActPos,Fail,1023,;")
        assert c.HRIF_ReadActTcpPos() == ["1023"]
