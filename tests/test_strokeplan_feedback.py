"""The first real-arm P trial is bounded at the command boundary."""
import numpy as np
import pytest

from tests.test_target_feedforward import settings, table


def pose(z_mm, x_mm=-200.):
    return np.array([x_mm / 1000., .5, z_mm / 1000., 0., .2617993877991494, 0.])


def test_error_sign_uses_positive_down_depth_and_returns_to_feedforward():
    from brushbot.experiments.strokeplan_feedback import StrokePlanPFeedback

    feedback = StrokePlanPFeedback(table(), settings(), .02, measure_ticks=101)
    ff = pose(29.5)
    feedback.reset(ff)
    commands = []
    for tick in range(101):
        command, correction, limits = feedback.command(
            tick, ff, depth_ff_m=.0075, a_ref_uT=30., a_control_uT=10.)
        commands.append(command)
        assert correction >= -1e-12
        assert command[2] == pytest.approx(.0295 - correction)
    assert min(row[2] for row in commands) < .0295  # too little signal presses down
    assert commands[-1][2] == pytest.approx(.0295)
    lifted, correction, _ = feedback.command(101, pose(29.51),
                                             depth_ff_m=.00749, a_ref_uT=None,
                                             a_control_uT=10.)
    assert lifted[2] == pytest.approx(.02951)
    assert correction == 0.

    feedback.reset(ff)
    for tick in range(10):
        command, correction, _ = feedback.command(
            tick, ff, depth_ff_m=.0075, a_ref_uT=30., a_control_uT=50.)
    assert correction < 0
    assert command[2] > .0295  # too much signal lifts


def test_large_error_is_bounded_in_correction_slew_acceleration_and_depth():
    from brushbot.experiments.strokeplan_feedback import StrokePlanPFeedback

    feedback = StrokePlanPFeedback(table(), settings(), .02, measure_ticks=101)
    ff = pose(19.01)  # nominal depth just under the installation's 18 mm cap
    feedback.reset(ff)
    z = []
    limits_seen = False
    for tick in range(101):
        command, correction, limits = feedback.command(
            tick, ff, depth_ff_m=.01799, a_ref_uT=80., a_control_uT=0.)
        z.append(command[2])
        limits_seen |= bool(limits)
        assert abs(correction) <= .0002 + 1e-12
        assert command[2] >= .019 - 1e-12
    assert limits_seen
    assert np.max(np.abs(np.diff(z))) <= .002 * .02 + 1e-12
    assert np.max(np.abs(np.diff(z, n=2))) <= .04 * .02**2 + 1e-12


@pytest.mark.parametrize('flip_tick,too_much_before_flip', [
    (12, True),   # Rising taper after a rapid measured-signal reversal.
    (80, False),  # Falling taper and the return to pure feedforward.
])
def test_feedback_stays_feasible_when_signal_reverses_near_taper(
        flip_tick, too_much_before_flip):
    from brushbot.experiments.strokeplan_feedback import StrokePlanPFeedback

    feedback = StrokePlanPFeedback(table(), settings(), .02, measure_ticks=101)
    ff = pose(29.5)
    feedback.reset(ff)
    corrections = []
    for tick in range(101):
        too_much = too_much_before_flip if tick < flip_tick else not too_much_before_flip
        measured = 160. if too_much else 0.
        command, correction, _ = feedback.command(
            tick, ff, depth_ff_m=.0075, a_ref_uT=80., a_control_uT=measured)
        assert command[2] == pytest.approx(ff[2] - correction)
        corrections.append(correction)
    corrections = np.asarray(corrections)
    assert corrections[0] == pytest.approx(0.)
    assert corrections[-1] == pytest.approx(0.)
    assert np.max(np.abs(corrections)) <= .0002 + 1e-12
    assert np.max(np.abs(np.diff(corrections))) <= .002 * .02 + 1e-12
    assert np.max(np.abs(np.diff(corrections, n=2))) <= .04 * .02**2 + 1e-12
    command, correction, _ = feedback.command(
        101, ff, depth_ff_m=.0075, a_ref_uT=None, a_control_uT=0.)
    assert correction == 0.
    assert command[2] == pytest.approx(ff[2])


def test_invalid_signal_and_unreachable_nominal_command_abort_before_output():
    from brushbot.experiments.strokeplan_feedback import StrokePlanPFeedback

    feedback = StrokePlanPFeedback(table(), settings(), .02, measure_ticks=101)
    feedback.reset(pose(29.5))
    with pytest.raises(RuntimeError, match='sensor_invalid'):
        feedback.command(0, pose(29.5), depth_ff_m=.0075,
                         a_ref_uT=30., a_control_uT=float('nan'))
    with pytest.raises(RuntimeError, match='workspace_limit'):
        feedback.command(0, pose(16.9), depth_ff_m=.0201,
                         a_ref_uT=30., a_control_uT=10.)


def test_final_nonwriting_command_still_checks_speed_and_acceleration():
    from brushbot.experiments.strokeplan_feedback import StrokePlanPFeedback

    feedback = StrokePlanPFeedback(table(), settings(), .02, measure_ticks=101)
    feedback.reset(pose(29.5))
    with pytest.raises(RuntimeError, match='z_speed_limit'):
        feedback.command(-1, pose(28.9), depth_ff_m=0.,
                         a_ref_uT=None, a_control_uT=0.)
    with pytest.raises(RuntimeError, match='acceleration_limit'):
        feedback.command(-1, pose(29.3), depth_ff_m=0.,
                         a_ref_uT=None, a_control_uT=0.)


@pytest.mark.parametrize('changed', [
    {'ki': .1}, {'kp': float('nan')},
    {'kp': 'oops'},
    {'max_correction_speed_mm_s': 20.},
    {'max_correction_accel_mm_s2': 300.},
])
def test_edited_p_profile_rejects_integral_nonfinite_and_site_limit(changed):
    from brushbot.experiments.strokeplan_feedback import (
        DEFAULT_P_PROFILE, StrokePlanPFeedback,
    )
    profile = dict(DEFAULT_P_PROFILE, **changed)
    with pytest.raises(ValueError):
        StrokePlanPFeedback(table(), settings(), .02,
                            measure_ticks=101, profile=profile)
