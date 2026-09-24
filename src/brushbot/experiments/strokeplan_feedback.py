"""Bounded P correction for one V3 StrokePlan measurement segment.

Depth is positive down.  The arm's base-frame TCP command is
``z_cmd = contact_z - (depth_ff + depth_fb)``.  No controller call is made
outside the segment with a finite magnetic target.
"""
from __future__ import annotations

import math

import numpy as np

from brushbot.z_control import ZController


KP_FIRST_TRIAL = 0.05
MAX_CORRECTION_M = 0.0002
MAX_CORRECTION_SPEED_M_S = 0.002
MAX_CORRECTION_ACCEL_M_S2 = 0.04
TAPER_TICKS = 25
DEFAULT_P_PROFILE = {
    'kp': KP_FIRST_TRIAL, 'ki': 0.,
    'max_correction_mm': MAX_CORRECTION_M * 1000.,
    'max_correction_speed_mm_s': MAX_CORRECTION_SPEED_M_S * 1000.,
    'max_correction_accel_mm_s2': MAX_CORRECTION_ACCEL_M_S2 * 1000.,
    'taper_ticks': TAPER_TICKS,
}


def resolve_p_profile(profile: dict | None, setup: dict) -> dict:
    """Freeze and validate an operator-edited first-stage P profile."""
    chosen = dict(DEFAULT_P_PROFILE if profile is None else profile)
    if set(chosen) != set(DEFAULT_P_PROFILE):
        raise ValueError('P profile fields differ from the first-stage contract')
    if chosen['ki'] != 0:
        raise ValueError('first-stage P trial requires ki=0')
    for key in ('kp', 'max_correction_mm', 'max_correction_speed_mm_s',
                'max_correction_accel_mm_s2'):
        value = chosen[key]
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError('P profile needs finite positive ' + key) from exc
        if isinstance(value, bool) or not np.isfinite(numeric) or numeric <= 0:
            raise ValueError('P profile needs finite positive ' + key)
        chosen[key] = numeric
    ticks = chosen['taper_ticks']
    if isinstance(ticks, bool) or not isinstance(ticks, int) or ticks < 2:
        raise ValueError('P profile taper_ticks must be an integer >= 2')
    if (chosen['max_correction_mm'] > float(setup['max_depth_mm'])
            or chosen['max_correction_speed_mm_s'] > float(setup['max_z_speed_mm_s'])
            or chosen['max_correction_accel_mm_s2'] > float(setup['max_accel_mm_s2'])):
        raise ValueError('P profile correction limit exceeds installation limit')
    chosen['ki'] = 0.
    return chosen


class StrokePlanPFeedback:
    """Shape the controller's depth request and check each final TCP command."""

    def __init__(self, table: dict, setup: dict, dt_s: float, *, measure_ticks: int,
                 profile: dict | None = None):
        if dt_s != .02 or measure_ticks < 2:
            raise ValueError('P trial requires a 20 ms segment with at least two ticks')
        self.dt_s = float(dt_s)
        self.setup = setup
        self.measure_ticks = int(measure_ticks)
        self.profile = resolve_p_profile(profile, setup)
        self.max_correction_m = self.profile['max_correction_mm'] / 1000.
        self.max_correction_speed_m_s = self.profile['max_correction_speed_mm_s'] / 1000.
        self.max_correction_accel_m_s2 = self.profile['max_correction_accel_mm_s2'] / 1000.
        self.taper_ticks = self.profile['taper_ticks']
        self.contact_z_m = float(setup['contact_z_mm']) / 1000.
        self.max_depth_m = float(setup['max_depth_mm']) / 1000.
        self.controller = ZController(
            np.asarray(table['depth_mm'], dtype=float),
            np.asarray(table['amplitude_uT'], dtype=float),
            dt=dt_s, kp=self.profile['kp'], ki=0., z_surface=0.,
            z_press_max=self.max_depth_m, z_lift_max=0., dz_step_max=1.)
        self.reset(None)

    def reset(self, initial_pose):
        self.controller.reset()
        self.previous = None if initial_pose is None else np.asarray(initial_pose, float).copy()
        self.before_previous = None if initial_pose is None else self.previous.copy()
        self.previous_correction = 0.
        self.previous_correction_step = 0.
        self.calls = 0

    def command(self, measure_tick: int, feedforward_pose, *, depth_ff_m: float,
                a_ref_uT: float | None, a_control_uT: float):
        nominal = np.asarray(feedforward_pose, dtype=float)
        if nominal.shape != (6,) or not np.isfinite(nominal).all():
            raise RuntimeError('workspace_limit')
        self._check_workspace(nominal)
        correction = 0.
        reasons = []
        command = nominal.copy()
        if a_ref_uT is not None:
            if (not isinstance(measure_tick, int) or measure_tick < 0
                    or measure_tick >= self.measure_ticks):
                raise RuntimeError('feedback_phase_invalid')
            if not math.isfinite(a_ref_uT) or not math.isfinite(a_control_uT):
                raise RuntimeError('sensor_invalid')
            depth_ff = float(depth_ff_m)
            if (not math.isfinite(depth_ff) or depth_ff < 0
                    or depth_ff > self.max_depth_m + 1e-12):
                raise RuntimeError('depth_limit')
            if not math.isclose(nominal[2], self.contact_z_m - depth_ff,
                                abs_tol=1e-9):
                raise RuntimeError('depth_limit')
            requested_depth = self.controller.step_magnitude(
                a_control_uT, a_ref_uT, depth_ff_m=depth_ff)
            self.calls += 1
            raw = requested_depth - depth_ff
            if self.controller.limit_active:
                reasons.append('controller_depth')
            edge = min(measure_tick, self.measure_ticks - 1 - measure_tick)
            envelope = self.max_correction_m * min(1., edge / self.taper_ticks)
            intervals = [(-envelope, envelope, 'feedback_amplitude')]
            if self.previous is not None:
                delta = self.max_correction_speed_m_s * self.dt_s
                intervals.append((self.previous_correction - delta,
                                  self.previous_correction + delta, 'feedback_speed'))
                center = self.previous_correction + self.previous_correction_step
                delta = self.max_correction_accel_m_s2 * self.dt_s**2
                intervals.append((center - delta, center + delta,
                                  'feedback_acceleration'))
                # A correction near the moving amplitude cap must have enough
                # room to brake on later ticks.  The minimum/maximum reachable
                # correction after k ticks of full braking is affine in the
                # correction selected now, so each future cap gives an interval.
                horizon = min(
                    self.measure_ticks - 1 - measure_tick,
                    math.ceil(self.max_correction_speed_m_s * self.dt_s / delta) + 1)
                braking_low, braking_high = -math.inf, math.inf
                for ahead in range(1, horizon + 1):
                    future_edge = min(measure_tick + ahead,
                                      self.measure_ticks - 1 - measure_tick - ahead)
                    future_cap = self.max_correction_m * min(1., future_edge / self.taper_ticks)
                    span = delta * ahead * (ahead + 1) / 2
                    offset = ahead * self.previous_correction
                    braking_low = max(braking_low,
                                      (-future_cap + offset - span) / (ahead + 1))
                    braking_high = min(braking_high,
                                       (future_cap + offset + span) / (ahead + 1))
                intervals.append((braking_low, braking_high, 'feedback_braking'))
            # Convert admissible TCP Z intervals to positive-down correction.
            z_lo = max(self.contact_z_m - self.max_depth_m,
                       float(self.setup['workspace_min_mm'][2]) / 1000.)
            z_hi = min(self.contact_z_m,
                       float(self.setup['workspace_max_mm'][2]) / 1000.)
            intervals.append((nominal[2] - z_hi, nominal[2] - z_lo,
                              'depth_or_workspace'))
            for z_low, z_high, name in self._dynamic_z_intervals(nominal):
                intervals.append((nominal[2] - z_high, nominal[2] - z_low, name))
            lower = max(item[0] for item in intervals)
            upper = min(item[1] for item in intervals)
            if lower > upper + 1e-12:
                raise RuntimeError('feedback_envelope_limit')
            correction = min(max(raw, lower), upper)
            for low, high, name in intervals:
                if raw < low - 1e-12 or raw > high + 1e-12:
                    reasons.append(name)
            command[2] = nominal[2] - correction
        self._check_final(command)
        self.before_previous = None if self.previous is None else self.previous.copy()
        self.previous = command.copy()
        self.previous_correction_step = correction - self.previous_correction
        self.previous_correction = correction
        return command, float(correction), sorted(set(reasons))

    def _check_workspace(self, pose):
        xyz_mm = pose[:3] * 1000.
        if (np.any(xyz_mm < np.asarray(self.setup['workspace_min_mm']) - 1e-9)
                or np.any(xyz_mm > np.asarray(self.setup['workspace_max_mm']) + 1e-9)):
            raise RuntimeError('workspace_limit')

    def _dynamic_z_intervals(self, pose):
        if self.previous is None:
            return []
        dt = self.dt_s
        old = self.previous
        xy_step = float(np.linalg.norm(pose[:2] - old[:2]))
        xy_limit = float(self.setup['max_xy_speed_mm_s']) / 1000. * dt
        if xy_step > xy_limit + 1e-9:
            raise RuntimeError('speed_limit')
        step = float(self.setup['max_step_mm']) / 1000.
        if xy_step > step + 1e-9:
            raise RuntimeError('step_limit')
        z_step = math.sqrt(max(0., step**2 - xy_step**2))
        z_speed = float(self.setup['max_z_speed_mm_s']) / 1000. * dt
        result = [(old[2] - z_step, old[2] + z_step, 'step'),
                  (old[2] - z_speed, old[2] + z_speed, 'z_speed')]
        if self.before_previous is not None:
            before = self.before_previous
            xy_acc = float(np.linalg.norm(pose[:2] - 2*old[:2] + before[:2])) / dt**2
            accel = float(self.setup['max_accel_mm_s2']) / 1000.
            if xy_acc > accel + 1e-9:
                raise RuntimeError('acceleration_limit')
            z_acc = math.sqrt(max(0., accel**2 - xy_acc**2)) * dt**2
            center = 2*old[2] - before[2]
            result.append((center - z_acc, center + z_acc, 'acceleration'))
        return result

    def _check_final(self, pose):
        self._check_workspace(pose)
        if self.contact_z_m - pose[2] > self.max_depth_m + 1e-9:
            raise RuntimeError('depth_limit')
        for low, high, name in self._dynamic_z_intervals(pose):
            if pose[2] < low - 1e-9 or pose[2] > high + 1e-9:
                raise RuntimeError(name + '_limit')
