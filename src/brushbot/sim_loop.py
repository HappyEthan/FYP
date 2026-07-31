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


class Plant:
    """被控对象: 延迟 FIFO → 一阶执行器 → 标定映射(+扰动) → 三轴合成(+漂移+噪声).

    真实曲线 = calib_abs_dB × calib_scale, 与控制器手里的标定表故意是两份
    (calib_scale≠1 即标定偏差扰动). calib_abs_dB 须单调升.
    paper_step=(t_step_s, dz_m): t≥t_step 后纸面朝笔抬高 dz (压深等效加深).
    drift_rate (µT/s): 沿 press_direction 注入 (与信号同向 = 最坏情形).
    tau/n_delay 为假设值 (真机未标定), 层1 做敏感性抽查.
    """

    def __init__(self, calib_z_mm, calib_abs_dB, dt=0.01, tau=0.05, n_delay=2,
                 z_surface=0.20, press_direction=(1.0, 0.3, 0.1), noise=None,
                 calib_scale=1.0, paper_step=None, drift_rate=0.0):
        self._z_grid_mm = np.asarray(calib_z_mm, float)
        self._db_grid = np.asarray(calib_abs_dB, float) * calib_scale
        self._dt = dt
        self._alpha = 1.0 - np.exp(-dt / tau) if tau > 0 else 1.0
        self._fifo = [z_surface] * max(0, int(n_delay))
        self._z_surface = z_surface
        d = np.asarray(press_direction, float)
        self._dir = d / np.linalg.norm(d)
        self._noise = noise
        self._paper_step = paper_step
        self._drift_rate = drift_rate
        self._t = 0.0
        self.z_act = z_surface
        self.abs_true = 0.0

    def step(self, z_cmd):
        """z 指令 (m, 世界坐标) → dB_raw (3,) µT. 每调用前进一拍."""
        self._fifo.append(float(z_cmd))
        z_delayed = self._fifo.pop(0)
        self.z_act += self._alpha * (z_delayed - self.z_act)
        paper = 0.0
        if self._paper_step is not None and self._t >= self._paper_step[0]:
            paper = self._paper_step[1]
        z_off_mm = (self.z_act - self._z_surface + paper) * 1000.0
        self.abs_true = float(np.interp(z_off_mm, self._z_grid_mm, self._db_grid,
                                        left=0.0, right=self._db_grid[-1]))
        dB = self._dir * (self.abs_true + self._drift_rate * self._t)
        if self._noise is not None:
            dB = dB + self._noise.sample(1)[0]
        self._t += self._dt
        return dB


def synth_press(cal_max, fs=FS, hold_s=0.5, ramp_s=0.3, press_s=6.0,
                f0=0.5, f1=3.0, base=0.5, depth=0.3):
    """合成提按目标 g_d(t): 悬空→落笔ramp→正弦扫频(f0→f1 Hz)→收笔ramp→悬空.

    幅值: 提按段在 (base±depth)·cal_max 内起伏; 落笔/收笔斜坡保证穿越
    3σ 接触阈值 (freeze 切换的测试场景). 返回 (N,) µT.
    """
    n_hold, n_ramp, n_press = int(hold_s * fs), int(ramp_s * fs), int(press_s * fs)
    A = base * cal_max
    t = np.arange(n_press) / fs
    phase = 2 * np.pi * (f0 * t + (f1 - f0) * t ** 2 / (2 * press_s))
    press = A + depth * cal_max * np.sin(phase)
    return np.concatenate([np.zeros(n_hold), np.linspace(0.0, A, n_ramp), press,
                           np.linspace(press[-1], 0.0, n_ramp), np.zeros(n_hold)])


def press_from_v0(csv_path, fc=3.0):
    """V0 动态段 → 零相位滤波 → |ΔB| 目标曲线. 铁律: 先滤 (N,3) 向量再取 norm."""
    return np.linalg.norm(fft_lowpass(load_deltab_csv(csv_path), fc), axis=1)


def run_loop(ctrl, filt, g_d, plant):
    """唯一闭环路径. filt=None → 无滤波臂; 开环臂 = ctrl 增益置零.

    滤波器实例整段连续运行, 永不 mid-run reset; NaN 原样透传到 ctrl guard.
    """
    n = len(g_d)
    res = {k: np.empty(n) for k in
           ("g_d", "abs_f", "z_cmd", "z_ff", "z_fb", "z_act", "abs_true")}
    res["dB_raw"] = np.empty((n, 3))
    res["dB_f"] = np.empty((n, 3))
    res["frozen"] = np.empty(n, dtype=bool)
    res["t"] = np.arange(n) / FS
    z_cmd = ctrl.z_surface
    for i in range(n):
        raw = plant.step(z_cmd)
        dB_f = filt.update(raw) if filt is not None else raw
        z_cmd = ctrl.step(dB_f, float(g_d[i]))
        res["dB_raw"][i] = raw
        res["dB_f"][i] = dB_f
        res["abs_f"][i] = np.linalg.norm(dB_f)
        res["g_d"][i] = g_d[i]
        res["z_cmd"][i] = z_cmd
        res["z_ff"][i] = ctrl.z_ff
        res["z_fb"][i] = ctrl.z_fb
        res["frozen"][i] = ctrl.frozen
        res["z_act"][i] = plant.z_act
        res["abs_true"][i] = plant.abs_true
    return res


def rms_pct(res, noise_std):
    """接触段 (g_d ≥ 3σ) 跟踪 RMS, % 目标量程. 以 plant 真值 abs_true 评."""
    m = res["g_d"] >= 3.0 * noise_std
    if not m.any():
        return float("nan")
    err = res["g_d"][m] - res["abs_true"][m]
    return float(np.sqrt(np.mean(err ** 2)) / res["g_d"].max() * 100.0)


def osc_index(res, f_cut=5.0, fs=FS):
    """z_cmd 交流功率中 >f_cut Hz 份额 (0-1). 稳定判定: ≤0.05 (spec §3.3)."""
    z = res["z_cmd"] - res["z_cmd"].mean()
    P = np.abs(np.fft.rfft(z)) ** 2
    f = np.fft.rfftfreq(len(z), d=1.0 / fs)
    tot = float(P[f > 0].sum())
    return float(P[f > f_cut].sum() / tot) if tot > 0 else 0.0


def freeze_jump(res):
    """freeze 切换点 ±5 拍窗内 |Δz_cmd| 单步最大值 (m); 无切换 → 0."""
    edges = np.nonzero(np.diff(res["frozen"].astype(int)))[0]
    dz = np.abs(np.diff(res["z_cmd"]))
    best = 0.0
    for e in edges:
        best = max(best, float(dz[max(0, e - 5):min(len(dz), e + 5)].max()))
    return best


def diverged(res, z_surface, calib_range_m):
    """z_cmd 非有限, 或偏离纸面超 2× 标定量程."""
    z = res["z_cmd"]
    return bool((~np.isfinite(z)).any()
                or np.abs(z - z_surface).max() > 2.0 * calib_range_m)
