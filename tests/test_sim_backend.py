from brushbot.scene import Scene
from brushbot.backends.sim import SimBackend, ZeroTactile
from brushbot.types import Command
from brushbot import config
import math

# 目标姿态一律用 config.FIXED_ORI(项目选定的"笔杆垂直"): 别的 yaw 会把
# J1/J4/J6 顶到 ±180° 限位上, 那是姿态不可达, 不是后端的问题。
TARGET = (0.45, 0.0, 0.22, *config.FIXED_ORI)


def _settle(backend, target, n=150):
    for _ in range(n):
        backend.write(Command(tcp_pose=target))


def test_sim_backend_tracks_command():
    sc = Scene(gui=False); sc.load()
    b = SimBackend(sc, ZeroTactile(), substeps=8)
    _settle(b, TARGET)
    st = b.read()
    x, y, z = st.tcp_pose[:3]
    err = ((x - TARGET[0]) ** 2 + (y - TARGET[1]) ** 2 + (z - TARGET[2]) ** 2) ** 0.5
    assert err < 0.01
    assert st.g_meas == 0.0
    assert st.t > 0.0
    sc.close()


def test_sim_backend_holds_commanded_orientation():
    """v1 笔杆垂直: 后端必须把命令姿态也送进 IK, 不能只管位置。

    位置-only IK 下法兰姿态不受控(实测 pitch≈-88° 且会解支突跳), 毛笔会乱转。
    """
    sc = Scene(gui=False); sc.load()
    b = SimBackend(sc, ZeroTactile(), substeps=8)
    _settle(b, TARGET)
    roll, pitch, _ = b.read().tcp_pose[3:6]
    assert abs(abs(roll) - math.pi) < 0.05      # 工具 Z 朝下
    assert abs(pitch) < 0.05
    sc.close()
