import copy
import json
from pathlib import Path

import numpy as np
import pytest

from tests.test_strokeplan_rotational_entry import fixture


def inputs(tmp_path):
    from scripts.generate_strokeplan import generate
    from brushbot.target_strokeplan import StrokePlan
    from brushbot.experiments.strokeplan_character import CHARACTER_ENTRY, tangent_rpy
    _, table, setup, _ = fixture(tmp_path)
    setup.update(max_xy_speed_mm_s=80., max_z_speed_mm_s=60., return_speed_mm_s=80.)
    strokes = []
    for offset, heading in [([.020, .010], 0.), ([.060, .010], -np.pi/2)]:
        st = generate(targets_uT=[180.], length_mm=20.).strokes[0]
        x = st.xy[:, 0].copy()
        st.xy = np.c_[x*np.cos(heading), x*np.sin(heading)] + offset
        st.orientation = tangent_rpy(np.full(len(x), heading), 15.)
        strokes.append(st)
    plan = StrokePlan(strokes, dict(source='synthetic', coordinate_frame='paper',
        feature=table['feature'], filter_definition=setup['filter'],
        orientation_convention='base_rpy_rad'))
    return plan, table, setup, dict(CHARACTER_ENTRY)


def test_tilt_tracks_xy_heading_without_forcing_only_ry():
    from brushbot.experiments.strokeplan_character import tangent_rpy
    rpy = np.rad2deg(tangent_rpy(np.array([0., np.pi/2, -np.pi/2, np.pi]), 15.))
    assert rpy == pytest.approx(np.array([[0., 15., 0.], [-15., 0., 0.],
                               [15., 0., 0.], [0., -15., 0.]]), abs=1e-8)


def test_directional_generation_compiles_all_four_strokes(tmp_path):
    from scripts.generate_directional_character_trial import generate
    from brushbot.target_strokeplan import StrokePlan
    report = generate(tmp_path/'directional')
    plan = StrokePlan.load(tmp_path/'directional/character.npz')
    assert len(plan.strokes) == 4
    assert all(st.orientation is not None for st in plan.strokes)
    assert max(np.ptp(st.orientation[:,0]) for st in plan.strokes) > .1
    assert report['compiled_limits']['angular speed'] <= 20.00001
    assert report['compiled_limits']['angular acceleration'] <= 40.00001
    assert report['baseline_count'] == 1


def test_character_goes_directly_between_strokes_and_slows_below_50(tmp_path):
    from brushbot.experiments.strokeplan_execution import compile_recorded_plan
    plan, table, setup, entry = inputs(tmp_path)
    c = compile_recorded_plan(plan, table, setup, label='character', entry_profile=entry)
    poses, phases = c['pose_m_rad'], c['phase']
    assert len(c['plan'].strokes) == 2
    end_first = np.flatnonzero(phases == 'measure_00')[-1]
    start_second = np.flatnonzero(phases == 'measure_01')[0]
    between = poses[end_first+1:start_second]
    assert not np.any(np.linalg.norm(between[:, :2]-poses[0, :2], axis=1) < 1e-6)
    for i, stroke in enumerate(plan.strokes):
        mask = phases == f'measure_{i:02}'
        assert poses[mask, :2] == pytest.approx(stroke.xy+[-.370, .5])
        assert poses[mask, 3:] == pytest.approx(stroke.orientation)
        assert c['g_ref_uT'][mask] == pytest.approx(180.)
        fast = np.flatnonzero(phases == f'lower_fast_{i:02}')
        slow = np.flatnonzero(phases == f'lower_slow_{i:02}')
        assert poses[fast[-1], 2] == pytest.approx(.050)
        assert poses[fast, 2].min() >= .050-1e-9
        speed = abs(np.diff(poses[slow[0]-1:slow[-1]+1, 2]))/.02*1000
        assert speed.max() <= 15.000001
    assert poses[-1] == pytest.approx(poses[0])
    assert phases[np.flatnonzero(phases == 'return_high')[0]-1].startswith('lift_')


def test_directional_character_pi_records_all_strokes_in_one_run(tmp_path):
    from brushbot.experiments.fake import FakeArm, FakeClock, FakeMagneticSource
    from scripts.run_strokeplan_experiment import build_stack, run_recorded
    plan, table, setup, entry = inputs(tmp_path)
    pi = dict(kp=1., ki=.05, max_correction_mm=.8, max_correction_speed_mm_s=2.,
              max_correction_accel_mm_s2=30., taper_ticks=50,
              integral_limit_mm=.2, anti_windup='conditional')
    plan.save(tmp_path/'character.npz')
    artifacts = {'strokeplan.npz': (tmp_path/'character.npz').read_bytes(),
                 **{n: json.dumps(v).encode() for n,v in [('feedforward.json',table),
                    ('settings.json',setup),('entry_profile.json',entry)]}}
    clock = FakeClock(); arm = FakeArm((-.370,.5,.13,0.,np.pi/12,0.),clock=clock)
    arm.realtime_state_reads = False
    source = FakeMagneticSource(arm,clock,contact_z_mm=40.)
    engine,hub=build_stack(plan=plan,table=table,setup=setup,artifacts=artifacts,
        label='character_pi',root=tmp_path/'runs',arm=arm,source=source,clock=clock,
        control_mode='pi',feedback_profile=pi,entry_profile=entry)
    result=run_recorded(engine,hub,clock=clock)
    assert result['state']=='END_WAIT',result
    rows=[json.loads(s) for s in (Path(result['run_dir'])/'control.jsonl').read_text().splitlines()]
    for phase in ['measure_00','measure_01']:
        selected=[r for r in rows if r['phase']==phase]
        assert len(selected)==111
        assert selected[0]['i_correction_m']==0.
        assert any(r['depth_fb_m'] != 0 for r in selected)
    assert all(r['depth_fb_m']==0 for r in rows if not r['phase'].startswith('measure_'))
    assert engine.feedback_calls==222
    events=[json.loads(s)['event'] for s in (Path(result['run_dir'])/'events.jsonl').read_text().splitlines()]
    assert events.count('baseline_fixed')==1


@pytest.mark.parametrize('change', ['assumption', 'workspace', 'orientation_rate'])
def test_character_retains_context_and_dynamic_guards(tmp_path, change):
    from brushbot.experiments.strokeplan_execution import compile_recorded_plan
    plan,table,setup,entry=inputs(tmp_path)
    if change=='assumption': entry['assume_pose_invariant']=False
    elif change=='workspace': setup['workspace_max_mm'][1]=500.
    else: plan.strokes[0].orientation[50,0]=1.
    with pytest.raises(ValueError):
        compile_recorded_plan(plan,table,setup,label='invalid',entry_profile=entry)
