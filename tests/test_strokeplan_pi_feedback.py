"""PI integration must see the final command bounds, including motion limits."""
import numpy as np
import pytest

from tests.test_strokeplan_feedback import pose
from tests.test_target_feedforward import settings, table


def profile(**changes):
    return dict(dict(kp=1., ki=.05, max_correction_mm=.8,
                     max_correction_speed_mm_s=2., max_correction_accel_mm_s2=30.,
                     taper_ticks=50, integral_limit_mm=.2,
                     anti_windup='conditional'), **changes)


def controller(**changes):
    from brushbot.experiments.strokeplan_pi_feedback import StrokePlanPIFeedback
    return StrokePlanPIFeedback(table(), settings(), .02,
                              measure_ticks=1501, profile=profile(**changes))


def test_unconstrained_integral_slope_and_reset():
    f = controller(kp=.01)
    ff = pose(29.5)
    # No previous pose isolates integral scaling from the motion envelope.
    for tick in range(100, 200):
        f.command(tick, ff, depth_ff_m=.0075, a_ref_uT=30., a_control_uT=29.)
    assert f.integral_m == pytest.approx(.05*f.controller.s_cal*1.*2.)
    assert not f.diagnostics['integral_blocked']
    f.reset(ff)
    assert f.integral_m == 0
    assert f.diagnostics['i_correction_m'] == 0


@pytest.mark.parametrize('z_mm,depth', [(29.5, .0075), (19.01, .01799)])
def test_sustained_saturation_does_not_wind_up_and_taper_returns_zero(z_mm, depth):
    f = controller()
    ff = pose(z_mm)
    f.reset(ff)
    corrections, reasons = [], set()
    for tick in range(1501):
        cmd, correction, limits = f.command(
            tick, ff, depth_ff_m=depth, a_ref_uT=80., a_control_uT=0.)
        corrections.append(correction)
        reasons.update(limits)
        assert f.integral_m == 0
        assert f.diagnostics['integral_blocked']
        assert cmd[2] >= .019-1e-12
    assert 'feedback_amplitude' in reasons
    assert 'feedback_acceleration' in reasons
    assert max(np.abs(corrections)) <= .0008+1e-12
    assert max(np.abs(np.diff(corrections))) <= .002*.02+1e-12
    assert max(np.abs(np.diff(corrections, n=2))) <= .03*.02**2+1e-12
    assert corrections[-1] == pytest.approx(0.)
    f.command(-1, ff, depth_ff_m=depth, a_ref_uT=None, a_control_uT=0.)
    assert f.integral_m == 0
    assert not f.diagnostics['integral_blocked']


def test_integral_cap_and_unwinding_after_error_reversal():
    f = controller(kp=.001, ki=1.)
    ff = pose(29.5)
    for tick in range(100, 500):
        f.command(tick, ff, depth_ff_m=.0075, a_ref_uT=30., a_control_uT=29.)
    assert f.integral_m == pytest.approx(.0002)
    assert f.diagnostics['integral_limit_active']
    f.command(500, ff, depth_ff_m=.0075, a_ref_uT=30., a_control_uT=31.)
    assert 0 < f.integral_m < .0002
    assert not f.diagnostics['integral_blocked']


def test_dynamic_limit_freezes_small_request_below_amplitude_cap():
    f = controller()
    ff = pose(29.5)
    f.reset(ff)
    _, correction, reasons = f.command(100, ff, depth_ff_m=.0075,
                                      a_ref_uT=30., a_control_uT=29.)
    assert 'feedback_acceleration' in reasons
    assert 'feedback_amplitude' not in reasons
    assert correction < f.diagnostics['pi_candidate_m'] < .0008
    assert f.integral_m == 0
    assert f.diagnostics['integral_blocked']


def test_integral_unwinds_while_total_request_remains_above_limit():
    f = controller(kp=.001, ki=1.)
    ff = pose(29.5)
    for tick in range(100, 500):
        f.command(tick, ff, depth_ff_m=.0075, a_ref_uT=30., a_control_uT=29.)
    previous_i = f.integral_m
    # A shallower allowed depth now leaves only 0.01 mm headroom. The negative
    # error should release stored I even though the combined request still clips.
    f.previous = None
    f.before_previous = None
    _, _, reasons = f.command(500, pose(19.01), depth_ff_m=.01799,
                              a_ref_uT=30., a_control_uT=31.)
    assert 'depth_or_workspace' in reasons
    assert 0 < f.integral_m < previous_i
    assert not f.diagnostics['integral_blocked']


@pytest.mark.parametrize('mode', ['p', 'pi'])
def test_taper_brakes_for_first_nonmeasurement_tick(mode):
    from brushbot.experiments.strokeplan_feedback import StrokePlanPFeedback
    f = controller()
    if mode == 'p':
        p = profile()
        p.pop('integral_limit_mm')
        p.pop('anti_windup')
        p['ki'] = 0.
        f = StrokePlanPFeedback(table(), settings(), .02, measure_ticks=1501, profile=p)
    ff = pose(29.5)
    f.reset(ff)
    corrections = [0., 0.]
    for tick in range(1502):
        _, corr, _ = f.command(tick if tick < 1501 else -1, ff, depth_ff_m=.0075,
            a_ref_uT=80. if tick < 1501 else None, a_control_uT=0.)
        corrections.append(corr)
    assert corrections[-2:] == pytest.approx([0., 0.])
    assert max(np.abs(np.diff(corrections, n=2))) <= .03*.02**2 + 1e-12


@pytest.mark.parametrize('change', [dict(ki=0), dict(ki=float('nan')),
    dict(ki=True), dict(integral_limit_mm=1.), dict(integral_limit_mm=-.1),
    dict(anti_windup='none')])
def test_invalid_pi_profile_rejected(change):
    with pytest.raises(ValueError):
        controller(**change)
