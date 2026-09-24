"""无 GUI 核心: 环形缓冲 + 基线 + 派生量. 禁止 import 任何 GUI 库."""
import numpy as np

from brushbot.filter import EMA   # noqa: F401  归属修正(R7): 正典在 filter.py, 此处 re-export 兼容旧 import


class RingBuffer:
    """定长环形缓冲, O(1) 写入. 存 (t_s, Bx, By, Bz)."""

    def __init__(self, capacity: int):
        if capacity < 1:
            raise ValueError("capacity 必须 >= 1")
        self.capacity = int(capacity)
        self._t = np.zeros(self.capacity, dtype=float)
        self._B = np.zeros((self.capacity, 3), dtype=float)
        self._w = 0          # 下一个写入位置
        self.n_total = 0     # 累计写入总数

    def append(self, t_s: float, b) -> None:
        self._t[self._w] = t_s
        self._B[self._w] = b
        self._w = (self._w + 1) % self.capacity
        self.n_total += 1

    def latest(self, n: int):
        """返回最近 n 个样本 (t, B), 按时间升序; 不足则返回全部."""
        m = min(int(n), self.capacity, self.n_total)
        if m <= 0:
            return np.empty(0), np.empty((0, 3))
        idx = (self._w - m + np.arange(m)) % self.capacity
        return self._t[idx].copy(), self._B[idx].copy()

    def latest_seconds(self, seconds: float):
        """按样本时间戳返回最近 seconds 秒，而非假定固定采样率。"""
        t, B = self.latest(self.capacity)
        if len(t) == 0:
            return t, B
        start = float(t[-1]) - max(float(seconds), 0.0)
        first = int(np.searchsorted(t, start, side="left"))
        return t[first:], B[first:]


class Baseline:
    """基线 B0 与噪声 σ. ΔB = B - B0."""

    def __init__(self):
        self.b0 = np.zeros(3)
        self.sigma = np.zeros(3)
        self.ready = False

    def take(self, B: np.ndarray, update_b0: bool = True) -> None:
        """用一段静止样本 (N,3) 取基线, 同时算三轴标准差.

        update_b0=False 时只重新测 sigma(仍会置 ready=True), b0 保持不变——
        用于回放源: 记录自带的 b0 要原样保留(否则回放不再逐点复现原始 ΔB),
        但门控仍需要一份真实测得的 sigma。
        """
        B = np.asarray(B, dtype=float)
        if B.ndim != 2 or B.shape[1] != 3 or len(B) == 0:
            raise ValueError("take() 需要形如 (N,3) 的非空数组")
        if update_b0:
            self.b0 = B.mean(axis=0)
        self.sigma = B.std(axis=0)
        self.ready = True

    @property
    def sigma_norm(self) -> float:
        return float(np.linalg.norm(self.sigma))

    def apply(self, B: np.ndarray) -> np.ndarray:
        """原始 B → ΔB."""
        return np.asarray(B, dtype=float) - self.b0

def derive(dB, gate: float) -> dict:
    """单个 ΔB 向量 → 幅值与方向. 幅值低于 gate 时方向置 None(噪声主导, 无意义)."""
    d = np.asarray(dB, dtype=float).reshape(3)
    mag_xy = float(np.hypot(d[0], d[1]))
    mag = float(np.linalg.norm(d))
    if mag < gate:
        return {"mag": mag, "mag_xy": mag_xy, "phi_deg": None, "theta_deg": None}
    return {
        "mag": mag,
        "mag_xy": mag_xy,
        "phi_deg": float(np.degrees(np.arctan2(d[1], d[0]))),
        "theta_deg": float(np.degrees(np.arctan2(mag_xy, d[2]))),
    }


def frame_quality_mask(samples, spike_uT: float = 1000.0,
                       return_uT: float = 250.0) -> np.ndarray:
    """标记可安全进入显示/基线/滤波的帧。

    非有限帧直接无效。中间样本若相对前后样本均跳变至少 ``spike_uT``，
    而前后样本彼此相差不超过 ``return_uT``，判为孤立数字毛刺。该规则保留
    持续的大幅物理信号，只排除一个采样周期内跳出又返回的读回异常。

    原始记录不得据此删除样本；调用方应保存此掩码作为质量字段。
    """
    samples = np.asarray(samples, dtype=float)
    if samples.ndim != 2 or samples.shape[1] != 3:
        raise ValueError("frame_quality_mask 需要形如 (N,3) 的数组")
    mask = np.all(np.isfinite(samples), axis=1)
    if len(samples) < 3:
        return mask
    prev, cur, nxt = samples[:-2], samples[1:-1], samples[2:]
    isolated = ((np.linalg.norm(cur - prev, axis=1) >= float(spike_uT)) &
                (np.linalg.norm(cur - nxt, axis=1) >= float(spike_uT)) &
                (np.linalg.norm(nxt - prev, axis=1) <= float(return_uT)))
    mask[1:-1] &= ~isolated
    return mask


def robust_symmetric_limit(values, floor: float = 50.0,
                           percentile: float = 99.5) -> float:
    """为实时曲线计算忽略 NaN/Inf 的对称显示范围。"""
    values = np.asarray(values, dtype=float)
    finite = np.abs(values[np.isfinite(values)])
    if not len(finite):
        return float(floor)
    return max(float(np.percentile(finite, percentile)), float(floor))
