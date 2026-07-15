from brushbot.types import State, Command
from brushbot.backends.fake import FakeBackend
from brushbot.run import run

class GotoController:
    """两拍后停止，一直命令同一个目标位姿。"""
    def __init__(self, target):
        self.target = target
        self.calls = 0
    def step(self, state: State) -> Command:
        self.calls += 1
        return Command(tcp_pose=self.target)
    def done(self) -> bool:
        return self.calls >= 2

def test_fake_backend_echoes_command():
    b = FakeBackend(dt=0.02)
    b.write(Command(tcp_pose=(1, 2, 3, 0, 0, 0)))
    st = b.read()
    assert st.tcp_pose == (1, 2, 3, 0, 0, 0)
    assert st.t == 0.02

def test_run_records_ticks():
    b = FakeBackend(dt=0.02)
    ctrl = GotoController(target=(0.4, 0.0, 0.1, 0, 0, 0))
    ticks = []
    run(b, ctrl, on_tick=lambda s: ticks.append(s.tcp_pose))
    assert len(ticks) == 2
    assert ticks[-1] == (0.4, 0.0, 0.1, 0, 0, 0)
