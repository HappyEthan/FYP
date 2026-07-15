from brushbot.types import State, Command

def test_state_fields():
    s = State(tcp_pose=(0.4, 0.0, 0.1, 3.14159, 0.0, 0.0), g_meas=0.0, t=0.0)
    assert s.tcp_pose[0] == 0.4
    assert s.g_meas == 0.0
    assert s.t == 0.0

def test_command_pose_len():
    c = Command(tcp_pose=(0.4, 0.0, 0.1, 3.14159, 0.0, 0.0))
    assert len(c.tcp_pose) == 6
