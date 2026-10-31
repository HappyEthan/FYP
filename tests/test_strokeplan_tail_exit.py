"""The geometric exit must stay independent of magnetic feedback."""
import json
from pathlib import Path

import numpy as np
import pytest

from tests.test_directional_character import inputs
from brushbot.experiments.strokeplan_execution import compile_recorded_plan


def trial(tmp_path):
    plan, table, setup, entry = inputs(tmp_path)
    plan.strokes = plan.strokes[:1]
    entry['tail_exit'] = dict(start_s=.5, end_s=.95, end_z_mm=42.)
    return plan, table, setup, entry


def test_tail_exit_retains_xy_but_lifts_above_paper(tmp_path):
    plan, table, setup, entry = trial(tmp_path)
    compiled = compile_recorded_plan(plan, table, setup, label='exit', entry_profile=entry)
    phases, poses = compiled['phase'], compiled['pose_m_rad']
    drawing = (phases == 'measure_00') | (phases == 'tail_exit_00')
    exit_indices = np.flatnonzero(phases == 'tail_exit_00')
    assert poses[drawing, :2] == pytest.approx(plan.strokes[0].xy + [-.370, .5])
    assert poses[exit_indices[-1], 2] == pytest.approx(.042)
    assert np.diff(poses[exit_indices[0]-1:exit_indices[-1]+1, 2]).min() >= -1e-12
    assert np.isnan(compiled['g_ref_uT'][exit_indices]).all()
    assert np.isfinite(compiled['g_ref_uT'][phases == 'measure_00']).all()
    assert compiled['s'][exit_indices[-1]] == pytest.approx(1.)


@pytest.mark.parametrize('exit_profile', [
    dict(start_s=.9, end_s=.8, end_z_mm=42.),
    dict(start_s=.5, end_s=.95, end_z_mm=39.),
    dict(start_s=.5, end_s=.95, end_z_mm=100.),
    dict(start_s=False, end_s=.95, end_z_mm=42.),
    dict(start_s=.5, end_s=.95, end_z_mm=float('nan')),
])
def test_invalid_exit_is_rejected(tmp_path, exit_profile):
    plan, table, setup, entry = trial(tmp_path)
    entry['tail_exit'] = exit_profile
    with pytest.raises(ValueError, match='tail_exit'):
        compile_recorded_plan(plan, table, setup, label='invalid', entry_profile=entry)


def test_exit_does_not_apply_pi_or_integrate_when_sensor_is_low(tmp_path):
    from brushbot.experiments.fake import FakeArm, FakeClock, FakeMagneticSource
    from scripts.run_strokeplan_experiment import build_stack, run_recorded
    plan, table, setup, entry = trial(tmp_path)
    pi = dict(kp=1., ki=.05, max_correction_mm=.8, max_correction_speed_mm_s=2.,
              max_correction_accel_mm_s2=30., taper_ticks=50,
              integral_limit_mm=.2, anti_windup='conditional')
    plan.save(tmp_path/'exit_target.npz')
    artifacts = {'strokeplan.npz': (tmp_path/'exit_target.npz').read_bytes(),
                 **{name: json.dumps(value).encode() for name, value in
                    [('feedforward.json', table), ('settings.json', setup), ('entry_profile.json', entry)]}}
    clock = FakeClock()
    arm = FakeArm((-.370,.5,.13,0.,np.pi/12,0.), clock=clock)
    arm.realtime_state_reads = False
    source = FakeMagneticSource(arm, clock, contact_z_mm=40.)
    engine, hub = build_stack(plan=plan, table=table, setup=setup, artifacts=artifacts,
                             label='exit_pi', root=tmp_path/'runs', arm=arm, source=source,
                             clock=clock, control_mode='pi', feedback_profile=pi, entry_profile=entry)
    result = run_recorded(engine, hub, clock=clock)
    assert result['state'] == 'END_WAIT', result
    rows = [json.loads(line) for line in (Path(result['run_dir'])/'control.jsonl').read_text().splitlines()]
    exit_rows = [r for r in rows if r['phase'] == 'tail_exit_00']
    assert exit_rows
    assert all(r['a_ref_uT'] is None and r['depth_fb_m'] == 0. and r['i_correction_m'] == 0. for r in exit_rows)
    assert max(r['z_cmd_m'] for r in exit_rows) == pytest.approx(.042)
