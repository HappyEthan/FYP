import numpy as np
from brushbot.types import Command

class OpenLoopController:
    """开环: 沿 (x,y,z) 路点折线按弧长匀速插值出目标位姿。B1 用。"""
    def __init__(self, waypoints, speed, fixed_ori):
        self.wp = np.asarray(waypoints, dtype=float)   # (N,3)
        seg = np.linalg.norm(np.diff(self.wp, axis=0), axis=1)
        self.cum = np.concatenate([[0.0], np.cumsum(seg)])
        self.total = float(self.cum[-1])
        self.speed = speed
        self.ori = tuple(fixed_ori)
        self._done = False

    def _interp(self, d):
        if d <= 0:
            return tuple(self.wp[0])
        if d >= self.total:
            return tuple(self.wp[-1])
        i = int(np.searchsorted(self.cum, d) - 1)
        seg_len = self.cum[i + 1] - self.cum[i]
        t = 0.0 if seg_len == 0 else (d - self.cum[i]) / seg_len
        pos = self.wp[i] + t * (self.wp[i + 1] - self.wp[i])
        return tuple(pos)

    def step(self, state) -> Command:
        d = self.speed * state.t
        if d >= self.total:
            self._done = True
        x, y, z = self._interp(d)
        return Command(tcp_pose=(x, y, z, *self.ori))

    def done(self) -> bool:
        return self._done
