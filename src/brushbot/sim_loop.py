"""闭环仿真 harness: V0 噪声回放 + Plant + 目标曲线 + 唯一闭环路径 run_loop.

Phase 1 全部验证 (层1 增益扫描 / 层2 开环-闭环对比 / demo) 共享 run_loop,
开环对照臂 = 同一路径、增益置零. 纯 numpy, 无 GUI/MuJoCo 依赖.
见 docs/superpowers/specs/2026-07-30-z-control-phase1-design.md
"""
import numpy as np

FS = 100.0


def load_deltab_csv(path):
    """ΔB CSV → (N,3) µT. 列: t_us,t_s,dBx_uT,dBy_uT,dBz_uT.

    与 scripts/compare_filters.load_csv 同构; src 不 import scripts, 故自带.
    """
    d = np.genfromtxt(path, delimiter=",", names=True)
    return np.column_stack([d["dBx_uT"], d["dBy_uT"], d["dBz_uT"]])


def fft_lowpass(x, fc, fs=FS):
    """FFT 域理想截断 (零相位, 仅离线目标曲线用). x: (N,3) 或 (N,)."""
    X = np.fft.rfft(x, axis=0)
    f = np.fft.rfftfreq(len(x), d=1.0 / fs)
    X[f > fc] = 0.0
    return np.fft.irfft(X, n=len(x), axis=0)


class V0NoiseSource:
    """V0 idle 数据的连续切片回放 (保 1/f 谱). 同 seed → 同序列.

    每次 sample(n) 从内部游标取连续 n 拍并前进; 池尾接镜像延拓, 无缝循环.
    """

    def __init__(self, csv_paths, seed=0):
        pool = np.vstack([load_deltab_csv(p) for p in csv_paths])
        self._pool = pool - pool.mean(axis=0)
        self._ext = np.vstack([self._pool, self._pool[::-1]])
        self._cursor = int(np.random.default_rng(seed).integers(len(self._pool)))

    def sample(self, n):
        """(n,3) 连续噪声样本, 跨调用连续."""
        out = np.empty((n, 3))
        got = 0
        while got < n:
            take = min(n - got, len(self._ext) - self._cursor)
            out[got:got + take] = self._ext[self._cursor:self._cursor + take]
            self._cursor = (self._cursor + take) % len(self._ext)
            got += take
        return out

    def filtered_sigma(self, make_filter=None):
        """样本池过滤波器后的 |σ| (µT); None → 原始 |σ|. noise_std 现算入口."""
        y = self._pool if make_filter is None else make_filter().update(self._pool)
        return float(np.linalg.norm(y.std(axis=0)))
