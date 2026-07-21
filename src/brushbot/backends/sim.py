from brushbot.types import State, Command
from brushbot import config

class ZeroTactile:
    """B1 占位触觉源; B2 换成合成提按 / 真实 g_meas 流。"""
    def value(self) -> float:
        return 0.0

class SimBackend:
    def __init__(self, scene, tactile, substeps: int = 4):
        self.scene = scene
        self.tactile = tactile
        self.substeps = substeps
        self._t = 0.0

    def read(self) -> State:
        return State(tcp_pose=self.scene.tcp_pose(),
                     g_meas=self.tactile.value(),
                     t=self._t)

    def write(self, cmd: Command) -> None:
        pos = cmd.tcp_pose[:3]
        ori = cmd.tcp_pose[3:6]
        # 全位姿 IK: v1 要求笔杆垂直, 姿态必须受控。位置-only 下法兰姿态不受约束
        # (实测 pitch≈-88° 且会解支突跳), 笔的朝向就毫无意义。
        q = self.scene.ik(pos, ori)
        self.scene.set_joints(q)
        for _ in range(self.substeps):
            self.scene.step()
        self._t += self.substeps * config.TICK_DT
