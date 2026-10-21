import json
from pathlib import Path

import numpy as np
import pytest

from brushbot.target_strokeplan import Stroke, StrokePlan
from brushbot.experiments.strokeplan_execution import compile_recorded_plan
from tests.test_strokeplan_experiment import inputs


def fixture(tmp_path):
    _, table, setup, _ = inputs(tmp_path)
    setup.update(contact_z_mm=40., origin_x_mm=-370., vertical_rpy_rad=[0., np.pi/12, 0.])
    table['context'].update(contact_z_mm=40., vertical_rpy_rad=setup['vertical_rpy_rad'])
    table.update(amplitude_uT=[160., 240.], depth_mm=[10., 13.])
    t = np.arange(2001)*.02
    x = .039+.01*t
    g = 160+80*np.sin(np.pi*t/40)**2
    plan = StrokePlan([Stroke(t/40, np.c_[x, np.zeros(len(x))], t, g)],
        dict(source='synthetic', coordinate_frame='paper', feature=table['feature'],
             filter_definition=setup['filter']))
    entry = dict(entry_contact_z_mm=36., entry_ry_deg=30., rotate_s=3.,
                 slide_settle_s=1., load_s=3., travel_mm=450., speed_mm_s=10.,
                 xy_accel_mm_s2=50., post_lift_hold_s=2.,
                 angular_speed_deg_s=10., angular_accel_deg_s2=20.)
    return plan, table, setup, entry


def test_rotates_at_fixed_z_and_preserves_target_xy_and_timing(tmp_path):
    plan, table, setup, entry = fixture(tmp_path)
    c = compile_recorded_plan(plan, table, setup, label='test', entry_profile=entry)
    ph, poses = c['phase'], c['pose_m_rad']
    rotate = poses[ph == 'rotate_contact']
    assert len(rotate) == 150
    assert rotate[:, :3] == pytest.approx(np.tile([-.370, .5, .036], (150, 1)))
    assert np.rad2deg(rotate[-1, 4]) == pytest.approx(15.)
    assert np.rad2deg(rotate[0, 4]) > 29.9
    measure = ph == 'measure_00'
    assert measure.sum() == 2001
    assert poses[measure, :2] == pytest.approx(plan.strokes[0].xy+[-.370, .5])
    assert c['g_ref_uT'][measure] == pytest.approx(plan.strokes[0].g_target)
    assert np.isnan(c['g_ref_uT'][~measure]).all()
    # Full drawing line includes the preparation and finish, exactly 450 mm.
    assert poses[:, 0].max() == pytest.approx(.080)
    assert poses[-1] == pytest.approx(poses[0])
    indices = np.flatnonzero(measure)
    assert np.diff(poses[indices[0]-1:indices[-1]+2, 0]) == pytest.approx(.0002)


@pytest.mark.parametrize('change', ['target_origin', 'too_long', 'wrong_angle', 'out_of_range'])
def test_rotational_entry_rejects_mismatched_path_or_context(tmp_path, change):
    plan, table, setup, entry = fixture(tmp_path)
    if change == 'target_origin':
        plan.strokes[0].xy[:, 0] -= .039
    elif change == 'too_long':
        entry['travel_mm'] = 430.
    elif change == 'wrong_angle':
        setup['vertical_rpy_rad'][1] = 0.
    else:
        plan.strokes[0].g_target[100] = 300.
    with pytest.raises(ValueError):
        compile_recorded_plan(plan, table, setup, label='invalid', entry_profile=entry)


@pytest.mark.parametrize('mode', ['feedforward', 'p'])
def test_recorded_rotation_and_p_only_during_measurement(tmp_path, mode):
    from brushbot.experiments.fake import FakeArm, FakeClock, FakeMagneticSource
    from scripts.run_strokeplan_experiment import build_stack, run_recorded
    plan, table, setup, entry = fixture(tmp_path)
    plan.save(tmp_path/'rotation_target.npz')
    artifacts = {'strokeplan.npz': (tmp_path/'rotation_target.npz').read_bytes(),
                 'feedforward.json': json.dumps(table).encode(),
                 'settings.json': json.dumps(setup).encode(),
                 'entry_profile.json': json.dumps(entry).encode()}
    clock = FakeClock()
    arm = FakeArm((-.370, .5, .13, 0., np.pi/12, 0.), clock=clock)
    arm.realtime_state_reads = False
    source = FakeMagneticSource(arm, clock, contact_z_mm=40.)
    engine, hub = build_stack(plan=plan, table=table, setup=setup,
        artifacts=artifacts, label='rotation', root=tmp_path/'runs', arm=arm,
        source=source, clock=clock, control_mode=mode, entry_profile=entry)
    result = run_recorded(engine, hub, clock=clock)
    assert result['state'] == 'END_WAIT', result
    folder = Path(result['run_dir'])
    assert (folder/'entry_profile.json').read_bytes() == artifacts['entry_profile.json']
    rows = [json.loads(line) for line in (folder/'control.jsonl').read_text().splitlines()]
    assert any(r['phase'] == 'rotate_contact' for r in rows)
    assert all(r['depth_fb_m'] == 0 for r in rows if r['phase'] != 'measure_00')
    assert engine.feedback_calls == (2001 if mode == 'p' else 0)
    c = engine._compiled
    assert np.allclose(c['pose_m_rad'][-1], c['pose_m_rad'][0])


@pytest.mark.parametrize('mode', ['ff', 'p'])
def test_comparison_cli_previews_both_modes_without_hardware(tmp_path, monkeypatch, capsys, mode):
    from scripts import run_strokeplan_trial as runner
    plan, table, setup, entry = fixture(tmp_path)
    plan.save(tmp_path/'hard_160_240.npz')
    from brushbot.experiments.strokeplan_feedback import DEFAULT_P_PROFILE
    for name, data in [('feedforward.json',table),('settings.json',setup),
                       ('entry_profile.json',entry),('p_profile.json',DEFAULT_P_PROFILE)]:
        (tmp_path/name).write_text(json.dumps(data))
    monkeypatch.setattr(runner,'TRIAL',tmp_path)
    monkeypatch.setattr(runner,'EXPERIMENT','nonlinear')
    monkeypatch.setattr(runner,'RUN_ROOT',tmp_path/'runs')
    assert runner.main(['--mode',mode,'--dry-run']) == 0
    output = capsys.readouterr().out
    assert 'Z36' in output and '独立采集' in output and '离线预检通过' in output
    assert not (tmp_path/'runs').exists()


@pytest.mark.parametrize('mode', ['feedforward', 'p'])
def test_rotational_comparison_disconnect_lifts_in_both_modes(tmp_path, mode):
    from brushbot.experiments.fake import FakeArm, FakeClock, FakeMagneticSource
    from scripts.run_strokeplan_experiment import build_stack, run_recorded
    plan, table, setup, entry = fixture(tmp_path)
    plan.save(tmp_path/'disconnect_target.npz')
    artifacts = {'strokeplan.npz':(tmp_path/'disconnect_target.npz').read_bytes(),
                 'feedforward.json':json.dumps(table).encode(),
                 'settings.json':json.dumps(setup).encode(),
                 'entry_profile.json':json.dumps(entry).encode()}
    clock=FakeClock();arm=FakeArm((-.370,.5,.13,0.,np.pi/12,0.),clock=clock)
    arm.realtime_state_reads=False
    source=FakeMagneticSource(arm,clock,contact_z_mm=40.)
    engine,hub=build_stack(plan=plan,table=table,setup=setup,artifacts=artifacts,
        label='disconnect',root=tmp_path/'runs',arm=arm,source=source,clock=clock,
        control_mode=mode,entry_profile=entry)
    original=source.read_frames
    def disconnected():
        if engine.state == 'RUN' and (engine.snapshot().get('telemetry') or {}).get('phase') == 'measure_00':
            raise OSError('synthetic disconnected device')
        return original()
    source.read_frames=disconnected
    result=run_recorded(engine,hub,clock=clock)
    assert result['state'] == 'ABORTED'
    assert arm.pose[2] == pytest.approx(.13)
    assert 'source_disconnected' in result['last_error']


@pytest.mark.parametrize('mode', ['feedforward', 'p'])
@pytest.mark.parametrize('disturbance', ['late_tick', 'repeated_poll', 'deadline'])
def test_comparison_keeps_command_samples_in_order_under_scheduler_jitter(
        tmp_path, mode, disturbance):
    """A late/extra poll must not turn 10 mm/s into a 500 mm/s² XY jump."""
    from brushbot.experiments.fake import FakeArm, FakeClock, FakeMagneticSource
    from scripts.run_strokeplan_experiment import build_stack, run_recorded
    plan, table, setup, entry = fixture(tmp_path)
    plan.save(tmp_path/'jitter_target.npz')
    artifacts = {'strokeplan.npz': (tmp_path/'jitter_target.npz').read_bytes(),
                 'feedforward.json': json.dumps(table).encode(),
                 'settings.json': json.dumps(setup).encode(),
                 'entry_profile.json': json.dumps(entry).encode()}
    clock = FakeClock()
    arm = FakeArm((-.370, .5, .13, 0., np.pi/12, 0.), clock=clock)
    arm.realtime_state_reads = False
    source = FakeMagneticSource(arm, clock, contact_z_mm=40.)
    engine, hub = build_stack(plan=plan, table=table, setup=setup,
        artifacts=artifacts, label='jitter', root=tmp_path/'runs', arm=arm,
        source=source, clock=clock, control_mode=mode, entry_profile=entry)
    injected = False

    def disturb(_):
        nonlocal injected
        if not injected and (engine.snapshot().get('telemetry') or {}).get('phase') == 'measure_00':
            injected = True
            if disturbance == 'repeated_poll':
                engine.step()  # Same clock instant; do not emit a duplicate point.
            else:
                clock.advance(.025 if disturbance == 'late_tick' else .2)

    result = run_recorded(engine, hub, clock=clock, live_output_fn=disturb)
    assert injected
    if disturbance == 'deadline':
        assert result['state'] == 'ABORTED'
        assert result['last_error'] == 'deadline_miss'
        assert arm.pose[2] == pytest.approx(.13)
        return
    assert result['state'] == 'END_WAIT', result['last_error']
    rows = [json.loads(line) for line in
            (Path(result['run_dir'])/'control.jsonl').read_text().splitlines()]
    assert len(rows) == len(engine._compiled['t_s'])
    assert np.diff([r['t_s'] for r in rows]) == pytest.approx(.02)
    measure = [r for r in rows if r['phase'] == 'measure_00']
    assert len(measure) == 2001
    assert np.diff([r['x_cmd_m'] for r in measure]) == pytest.approx(.0002)
