from brushbot.types import State, Command

class FakeBackend:
    """纯逻辑后端：把命令位姿原样回显，用于单测运行循环与控制器。"""
    def __init__(self, dt: float):
        self.dt = dt
        self._pose = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        self._t = 0.0
    def read(self) -> State:
        return State(tcp_pose=self._pose, g_meas=0.0, t=self._t)
    def write(self, cmd: Command) -> None:
        self._pose = cmd.tcp_pose
        self._t += self.dt
