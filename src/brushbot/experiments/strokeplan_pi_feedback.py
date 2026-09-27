"""Slow PI with conditional integration against the complete output envelope.

Positive error requests greater depth. Ki is in 1/s with the same global
calibration scale as P. The stored integral is in metres of depth correction.
"""
import math

from brushbot.experiments.strokeplan_feedback import (
    DEFAULT_P_PROFILE, StrokePlanPFeedback, resolve_p_profile,
)


def resolve_pi_profile(profile, setup):
    required = set(DEFAULT_P_PROFILE) | {'integral_limit_mm', 'anti_windup'}
    if not isinstance(profile, dict) or set(profile) != required:
        raise ValueError('PI requires an explicit profile with integral_limit_mm and anti_windup')
    chosen = resolve_p_profile({k: (0. if k == 'ki' else profile[k])
                               for k in DEFAULT_P_PROFILE}, setup)
    for key in ('ki', 'integral_limit_mm'):
        value = profile[key]
        try:
            number = float(value)
        except (ValueError, TypeError) as exc:
            raise ValueError('PI requires finite positive ' + key) from exc
        if isinstance(value, bool) or not math.isfinite(number) or number <= 0:
            raise ValueError('PI requires finite positive ' + key)
        chosen[key] = number
    if chosen['integral_limit_mm'] > chosen['max_correction_mm']:
        raise ValueError('integral limit exceeds total correction limit')
    if profile['anti_windup'] != 'conditional':
        raise ValueError('PI requires conditional anti_windup')
    chosen['anti_windup'] = 'conditional'
    return chosen


class StrokePlanPIFeedback(StrokePlanPFeedback):
    resolve_profile = staticmethod(resolve_pi_profile)

    def reset(self, initial_pose):
        super().reset(initial_pose)
        self._nonmeasurement()

    def _nonmeasurement(self):
        self.integral_m = 0.
        self.diagnostics = dict(p_request_m=0., i_correction_m=0.,
            pi_candidate_m=0., pi_request_m=0., integral_delta_requested_m=0.,
            integral_blocked=False, integral_limit_active=False,
            feedback_lower_m=None, feedback_upper_m=None)

    def _raw_correction(self, depth_ff, a_ref, a_control):
        error = a_ref - a_control
        self.calls += 1
        self._p = self.profile['kp'] * self.controller.s_cal * error
        self._delta_i = self.profile['ki'] * self.controller.s_cal * error * self.dt_s
        limit = self.profile['integral_limit_mm'] / 1000.
        proposed = self.integral_m + self._delta_i
        self._candidate_i = min(max(proposed, -limit), limit)
        self._i_limited = abs(proposed) >= limit
        return self._p + self._candidate_i, []

    def _constrain_request(self, raw, lower, upper):
        # Includes amplitude/taper, slew, acceleration, braking, workspace,
        # depth and combined TCP dynamics. Do not accumulate into a limit;
        # an integral change that drives the request back toward it is allowed.
        delta = self._candidate_i - self.integral_m
        blocked = ((raw > upper + 1e-12 and delta > 0)
                   or (raw < lower - 1e-12 and delta < 0))
        if not blocked:
            self.integral_m = self._candidate_i
        accepted = self._p + self.integral_m
        self.diagnostics = dict(p_request_m=self._p, i_correction_m=self.integral_m,
            pi_candidate_m=raw, pi_request_m=accepted,
            integral_delta_requested_m=self._delta_i,
            integral_blocked=blocked, integral_limit_active=self._i_limited,
            feedback_lower_m=lower, feedback_upper_m=upper)
        return accepted
