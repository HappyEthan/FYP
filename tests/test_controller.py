from brushbot.types import State
from brushbot.controller import OpenLoopController

def _state(t):
    return State(tcp_pose=(0,0,0,0,0,0), g_meas=0.0, t=t)

def test_interp_midpoint():
    wp = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]   # 长度 1 的直线
    c = OpenLoopController(wp, speed=1.0, fixed_ori=(0.0, 0.0, 0.0))
    cmd = c.step(_state(0.5))                  # 走了 0.5 米
    assert abs(cmd.tcp_pose[0] - 0.5) < 1e-6
    assert len(cmd.tcp_pose) == 6

def test_done_after_full_length():
    wp = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
    c = OpenLoopController(wp, speed=1.0, fixed_ori=(0.0, 0.0, 0.0))
    c.step(_state(0.5)); assert not c.done()
    c.step(_state(1.0)); assert c.done()

def test_interp_clamps_past_end():
    wp = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
    c = OpenLoopController(wp, speed=1.0, fixed_ori=(0.0, 0.0, 0.0))
    cmd = c.step(_state(5.0))
    assert abs(cmd.tcp_pose[0] - 1.0) < 1e-6
