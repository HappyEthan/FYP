"""XY assumption must preserve motion guards and avoid contact lead-in marks."""
import numpy as np
import pytest

from scripts.generate_strokeplan import generate
from brushbot.strokeplan_compile import compile_target_plan
from brushbot.experiments.strokeplan_execution import compile_recorded_plan
from tests.test_strokeplan_rotational_entry import fixture


def stationary_inputs(tmp_path):
    _, table, setup, _ = fixture(tmp_path)
    plan = generate(targets_uT=[180.], length_mm=100.)
    st = plan.strokes[0]
    st.xy[:, 1] = .003 * np.sin(np.pi * st.s)
    st.t = np.arange(len(st.t)) * .04
    arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(st.xy, axis=0), axis=1))]
    st.s = arc / arc[-1]
    entry = dict(mode='stationary', assume_direction_invariant=True,
                 entry_contact_z_mm=36., entry_ry_deg=30., rotate_s=3.,
                 load_s=3., post_lift_hold_s=2.,
                 angular_speed_deg_s=10., angular_accel_deg_s2=20.)
    return plan, table, setup, entry


def test_xy_assumption_is_explicit_and_preserves_original_path(tmp_path):
    plan, table, setup, _ = stationary_inputs(tmp_path)
    with pytest.raises(ValueError, match='only \\+X'):
        compile_target_plan(plan, table, setup)
    poses, phases = compile_target_plan(plan, table, setup, assume_direction_invariant=True)
    measure = np.asarray(phases) == 'measure_00'
    assert poses[measure, 1].max() == pytest.approx(.503)
    assert poses[measure, 0][[0, -1]] == pytest.approx([-.370, -.270])


@pytest.mark.parametrize('mutation, message', [
    ('range', 'outside measured range'), ('speed', 'speed'),
    ('workspace', 'workspace'), ('depth', 'depth'),
])
def test_xy_opt_in_keeps_other_guards(tmp_path, mutation, message):
    plan, table, setup, entry = stationary_inputs(tmp_path)
    if mutation == 'range':
        plan.strokes[0].g_target[10] = 300.
    elif mutation == 'speed':
        plan.strokes[0].t /= 10
    elif mutation == 'workspace':
        setup['workspace_max_mm'][1] = 501.
    else:
        setup['max_depth_mm'] = 8.
    with pytest.raises(ValueError, match=message):
        compile_recorded_plan(plan, table, setup, label='guard', entry_profile=entry)


def test_stationary_rotation_and_load_keep_xy_at_first_target(tmp_path):
    plan, table, setup, entry = stationary_inputs(tmp_path)
    # A nonzero local origin must be reached at clearance height first.
    plan.strokes[0].xy += [.020, .010]
    c = compile_recorded_plan(plan, table, setup, label='stationary', entry_profile=entry)
    phases, poses = c['phase'], c['pose_m_rad']
    assert not any(str(p).startswith('slide_') for p in phases)
    for phase in ('lower_tilted', 'rotate_contact', 'load_workpoint'):
        p = poses[phases == phase]
        assert len(p) > 0
        assert p[:, :2] == pytest.approx(np.tile([-.350, .510], (len(p), 1)))
    rotate = poses[phases == 'rotate_contact']
    assert rotate[:, 2] == pytest.approx(.036)
    assert np.rad2deg(rotate[-1, 4]) == pytest.approx(15.)
    measure = poses[phases == 'measure_00']
    assert measure[0, :2] == pytest.approx([-.350, .510])
    assert measure[-1, :2] == pytest.approx([-.250, .510])
    assert poses[-1] == pytest.approx(poses[0])
    assert c['spec_snapshot']['path']['axis'] == 'xy'
    assert c['spec_snapshot']['path']['assume_direction_invariant'] is True


def test_stationary_xy_requires_boolean_assumption(tmp_path):
    plan, table, setup, entry = stationary_inputs(tmp_path)
    entry['assume_direction_invariant'] = 'true'
    with pytest.raises(ValueError, match='boolean'):
        compile_recorded_plan(plan, table, setup, label='bad_flag', entry_profile=entry)


def test_faster_transit_shortens_air_motion_and_preserves_contact_samples(tmp_path):
    plan, table, setup, entry = stationary_inputs(tmp_path)
    setup['return_speed_mm_s'] = 20.
    plan.strokes[0].xy += [.020, .010]
    slow = compile_recorded_plan(plan, table, setup, label='slow', entry_profile=entry)
    fast_setup = dict(setup, max_xy_speed_mm_s=40., max_z_speed_mm_s=20.,
                      return_speed_mm_s=40.)
    fast_entry = dict(entry, transit_speed_mm_s=20., air_rotate_s=1.5,
                      angular_speed_deg_s=20., angular_accel_deg_s2=40.)
    fast = compile_recorded_plan(plan, table, fast_setup, label='fast', entry_profile=fast_entry)
    for phase in ('rotate_contact', 'load_workpoint', 'measure_00'):
        assert fast['pose_m_rad'][fast['phase'] == phase] == pytest.approx(
            slow['pose_m_rad'][slow['phase'] == phase])
    for phase in ('high_transfer_00', 'lower_tilted', 'lift', 'return_high', 'rotate_air'):
        nslow = np.count_nonzero(slow['phase'] == phase)
        nfast = np.count_nonzero(fast['phase'] == phase)
        assert nfast < nslow
        assert nfast == pytest.approx(nslow / 2, abs=1)
    assert fast['pose_m_rad'][-1] == pytest.approx(slow['pose_m_rad'][-1])


def test_fast_air_rotation_still_checks_angular_limits(tmp_path):
    plan, table, setup, entry = stationary_inputs(tmp_path)
    entry.update(air_rotate_s=1.5, transit_speed_mm_s=20.)
    with pytest.raises(ValueError, match='angular speed'):
        compile_recorded_plan(plan, table, setup, label='too_fast', entry_profile=entry)


def test_stationary_pi_records_whole_curve_and_resets_at_lift(tmp_path):
    import json
    from pathlib import Path
    from brushbot.experiments.fake import FakeArm, FakeClock, FakeMagneticSource
    from scripts.run_strokeplan_experiment import build_stack, run_recorded

    plan, table, setup, entry = stationary_inputs(tmp_path)
    pi = dict(kp=1., ki=.05, max_correction_mm=.8,
              max_correction_speed_mm_s=2., max_correction_accel_mm_s2=30.,
              taper_ticks=50, integral_limit_mm=.2, anti_windup='conditional')
    plan.save(tmp_path/'stationary_target.npz')
    artifacts = {'strokeplan.npz': (tmp_path/'stationary_target.npz').read_bytes(),
                 **{n: json.dumps(v).encode() for n, v in [
                     ('feedforward.json', table), ('settings.json', setup),
                     ('entry_profile.json', entry)]}}
    clock = FakeClock()
    arm = FakeArm((-.370, .5, .13, 0., np.pi/12, 0.), clock=clock)
    arm.realtime_state_reads = False
    source = FakeMagneticSource(arm, clock, contact_z_mm=40.)
    engine, hub = build_stack(plan=plan, table=table, setup=setup, artifacts=artifacts,
        label='stationary_pi', root=tmp_path/'runs', arm=arm, source=source,
        clock=clock, control_mode='pi', feedback_profile=pi, entry_profile=entry)
    result = run_recorded(engine, hub, clock=clock)
    assert result['state'] == 'END_WAIT', result
    rows = [json.loads(line) for line in
            (Path(result['run_dir'])/'control.jsonl').read_text().splitlines()]
    assert sum(r['phase'] == 'measure_00' for r in rows) == 1021
    assert max(r['y_cmd_m'] for r in rows) == pytest.approx(.503)
    assert all(r['depth_fb_m'] == 0 for r in rows if r['phase'] != 'measure_00')
    assert engine.feedback.integral_m == 0
