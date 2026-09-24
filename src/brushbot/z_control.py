"""Z 轴闭环控制 Phase 0: 整体 ΔB 跟踪.

控制律: z_cmd = z_surface + z_ff(|ΔB_d|) + kp·S_cal·e + ki·S_cal·∫e
  e = |ΔB_d| − |ΔB_meas|
  前馈为主, 积分仅补残差.

见 docs/04-robot-control/archive/z-control-design.md
"""
import numpy as np

from brushbot import config


def calib_lookup_z(g, calib_z_mm, calib_abs_dB):
    """标定反查: 目标 |ΔB| (µT) -> 压深 offset (m). 全项目唯一实现.

    内部按 abs_dB 排序 (容忍非单调标定输入); 低于下界 -> 0.0, 超上界 -> 最大压深
    (饱和保护). g 为标量返回 float, 为数组返回同形状数组.
    ZController 与离线管线 (demo_pipeline) 共用本函数."""
    abs_dB = np.asarray(calib_abs_dB, dtype=float)
    z_m = np.asarray(calib_z_mm, dtype=float) / 1000.0
    idx = np.argsort(abs_dB)
    out = np.interp(g, abs_dB[idx], z_m[idx], left=0.0, right=float(z_m[idx][-1]))
    return float(out) if np.isscalar(g) or np.ndim(g) == 0 else out


class ZController:
    """整体 ΔB 标量跟踪控制器。"""

    def __init__(self, calib_z_mm: np.ndarray, calib_abs_dB: np.ndarray,
                 dt: float = 1.0 / config.FS, kp: float = 1.2077, ki: float = 0.134,
                 z_surface: float = config.PAPER_Z, dz_margin: float = 3e-3,
                 noise_std: float = 7.0, z_press_max: float = None,
                 z_lift_max: float = 0.02, dz_step_max: float = 1e-3,
                 deadband_uT: float = 0.0):
        """
        Parameters
        ----------
        calib_z_mm : (N,) 压深 mm (从接触起点起算)
        calib_abs_dB : (N,) 对应 |ΔB| μT
        dt : 控制周期 (s)
        kp/ki : 误差到压深的比例/积分增益。默认数字来自早期裸态仿真，
            不作为当前 StrokePlan 真机参数；现行单笔反馈入口显式使用 ki=0。
            控制思路见 docs/04-robot-control/archive/z-control-design.md。
        z_surface : 纸面高度 (m)
        dz_margin : 积分限幅 ±m
        noise_std : 噪声标准差 (μT), 全带宽裸态口径，接滤波后必须显式传滤波后 σ；用于接触判定
        z_press_max : 绝对位置钳·压深上限 (m, 相对 z_surface)。物理不变量：无论上游
            数据多坏，笔尖最深压到这里。None (默认) = 标定量程 + dz_margin + 1mm 裕度
            （正常前馈+满积分权限永远碰不到；断线补零等故障场景会碰到）。
        z_lift_max : 绝对位置钳·抬笔上限 (m, 相对 z_surface)。
        dz_step_max : 单步速率钳 (m/拍)。默认 1mm/拍 (=100mm/s @100Hz)：Phase 1
            全场景 (wp_P/wp_PI/open × baseline/calib0.8/paper_step/drift) 实测合法
            单拍变化最大 0.587mm/拍 (快速收笔沿的 kp 响应)，默认值取 ~1.7 倍裕度，
            正常书写永不咬合；坏数据下指令以有限速度爬而非瞬移。真机示范速度
            标定后可显式收紧。
        """
        assert len(calib_z_mm) == len(calib_abs_dB) > 1
        # Sort by abs_dB so np.interp works correctly even with non-monotonic input
        abs_dB = np.asarray(calib_abs_dB, dtype=float)
        z_offset_m = np.asarray(calib_z_mm, dtype=float) / 1000.0
        sort_idx = np.argsort(abs_dB)
        self._calib_dB = abs_dB[sort_idx]
        self._z_offset_m = z_offset_m[sort_idx]
        self._calib_z_mm_sorted = np.asarray(calib_z_mm, dtype=float)[sort_idx]

        # Calculate calibration slope S_cal (m/µT)
        db_span = float(self._calib_dB[-1] - self._calib_dB[0])   # 已升序
        assert db_span > 0, "calib |dB| span must be > 0"
        z_span = float(self._z_offset_m.max() - self._z_offset_m.min())
        self._s_cal = z_span / db_span                            # m/µT

        self._dt = dt
        self._kp = kp
        self._ki = ki
        self._z_surface = z_surface
        self._dz_margin = dz_margin
        self._noise_std = noise_std
        if not np.isfinite(deadband_uT) or deadband_uT < 0:
            raise ValueError("deadband_uT must be finite and >= 0")
        self._deadband_uT = float(deadband_uT)

        if z_press_max is None:
            z_press_max = float(self._z_offset_m.max()) + dz_margin + 1e-3
        self._z_press_max = z_press_max
        self._z_lift_max = z_lift_max
        self._dz_step_max = dz_step_max

        self._z_fb = 0.0
        self._frozen = False
        self._z_prev = None
        self._limit_active = False

    def _z_ff_lookup(self, g_d: float) -> float:
        """|ΔB| (μT) → z_offset (m). 委托 calib_lookup_z (全项目唯一反查实现)."""
        return float(calib_lookup_z(g_d, self._calib_z_mm_sorted, self._calib_dB))

    def _clamp(self, z_raw: float) -> float:
        """输出安全钳: 非有限回退 → 绝对位置钳 → 单步速率钳. 所有 return 必经此处.

        非有限值回退到上一拍指令 (无历史则纸面高度)——否则 clip(NaN) 仍是 NaN,
        钳位形同虚设. _z_prev 恒为已钳值, 故速率钳后仍在绝对界内."""
        z = float(z_raw)
        if not np.isfinite(z):
            z = self._z_prev if self._z_prev is not None else self._z_surface
        z = min(max(z, self._z_surface - self._z_lift_max),
                self._z_surface + self._z_press_max)
        if self._z_prev is not None:
            z = min(max(z, self._z_prev - self._dz_step_max),
                    self._z_prev + self._dz_step_max)
        self._z_prev = z
        return z

    def step(self, dB_meas: np.ndarray, g_d: float) -> float:
        """计算 z_cmd (m, 世界坐标).

        Parameters
        ----------
        dB_meas : (3,) 当前 ΔB 测量值 (μT)
        g_d : 目标 |ΔB| (μT)

        Returns
        -------
        z_cmd : float  z 命令 (m)
        """
        abs_meas = float(np.linalg.norm(dB_meas))
        e = g_d - abs_meas
        self._last_g_d = g_d

        # NaN/Inf guard: freeze and return safe z_cmd
        if not (np.isfinite(abs_meas) and np.isfinite(g_d)):
            self._frozen = True
            return self._clamp(self._z_surface + self._z_ff_lookup(g_d) + self._z_fb)

        # Contact / lift detection
        if abs_meas < 3.0 * self._noise_std or g_d < 3.0 * self._noise_std:
            self._frozen = True
        else:
            self._frozen = False

        # Feedforward
        z_ff = self._z_ff_lookup(g_d)

        # Feedback (only integrate when not frozen)
        if not self._frozen:
            self._z_fb += self._ki * self._s_cal * e * self._dt
            self._z_fb = np.clip(self._z_fb, -self._dz_margin, self._dz_margin)

        z_cmd = self._z_surface + z_ff + self._kp * self._s_cal * e + self._z_fb
        return self._clamp(z_cmd)

    def step_magnitude(self, a_meas_uT: float, a_ref_uT: float, *,
                       depth_ff_m: float) -> float:
        """Track the explicit 2-D magnetic magnitude using positive-down depth.

        The caller computes ``hypot(dBx, dBy)`` and supplies the same frozen
        feedforward depth used by the open-loop arm.  Experiment code constructs
        this controller with ``z_surface=0`` so the return value is depth itself.
        """
        values = np.asarray([a_meas_uT, a_ref_uT, depth_ff_m], dtype=float)
        if not np.isfinite(values).all():
            raise ValueError("magnitude control inputs must be finite")
        measured, reference, depth_ff = map(float, values)
        error = reference - measured
        error_band = np.sign(error) * max(abs(error) - self._deadband_uT, 0.0)
        proportional = self._kp * self._s_cal * error_band

        integral_candidate = self._z_fb
        if error_band != 0.0:
            integral_candidate += self._ki * self._s_cal * error_band * self._dt
            integral_candidate = float(np.clip(
                integral_candidate, -self._dz_margin, self._dz_margin))

        raw_candidate = self._z_surface + depth_ff + proportional + integral_candidate
        lower = self._z_surface - self._z_lift_max
        upper = self._z_surface + self._z_press_max
        if self._z_prev is not None:
            lower = max(lower, self._z_prev - self._dz_step_max)
            upper = min(upper, self._z_prev + self._dz_step_max)
        pushes_deeper_limit = error_band > 0 and raw_candidate > upper
        pushes_lift_limit = error_band < 0 and raw_candidate < lower
        if not (pushes_deeper_limit or pushes_lift_limit):
            self._z_fb = integral_candidate

        raw = self._z_surface + depth_ff + proportional + self._z_fb
        command = self._clamp(raw)
        self._limit_active = not np.isclose(command, raw, rtol=0.0, atol=1e-15)
        self._frozen = error_band == 0.0
        return command

    def reset(self):
        """重置积分器与速率钳历史 (视为新一段运行, 首拍不受速率钳约束)."""
        self._z_fb = 0.0
        self._frozen = False
        self._z_prev = None
        self._limit_active = False

    @property
    def z_ff(self) -> float:
        return self._z_ff_lookup(self._last_g_d) if hasattr(self, '_last_g_d') else 0.0

    @property
    def z_surface(self) -> float:
        """纸面高度 (m)."""
        return self._z_surface

    @property
    def dt(self) -> float:
        """控制周期 (s); run_loop 用它做 FS 一致性 fail-loud 校验."""
        return self._dt

    @property
    def z_fb(self) -> float:
        return self._z_fb

    @property
    def frozen(self) -> bool:
        return self._frozen

    @property
    def s_cal(self) -> float:
        """标定斜率 (m/µT), 无量纲增益的换算因子."""
        return self._s_cal

    @property
    def z_press_max(self) -> float:
        """绝对位置钳·压深上限 (m, 相对 z_surface)."""
        return self._z_press_max

    @property
    def z_lift_max(self) -> float:
        """绝对位置钳·抬笔上限 (m, 相对 z_surface)."""
        return self._z_lift_max

    @property
    def dz_step_max(self) -> float:
        """单步速率钳 (m/拍)."""
        return self._dz_step_max

    @property
    def limit_active(self) -> bool:
        return self._limit_active
