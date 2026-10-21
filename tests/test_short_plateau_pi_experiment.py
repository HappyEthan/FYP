"""Exercise the real compiler/recorder and the user-facing offline entry point."""
import json
from pathlib import Path

import numpy as np
import pytest

from tests.test_strokeplan_rotational_entry import fixture
from tests.test_strokeplan_pi_feedback import profile


def generate_trial(tmp_path):
    from scripts.generate_short_plateau_trial import generate
    source = tmp_path/'source'
    source.mkdir()
    _, table, setup, entry = fixture(source)
    table.update(approved=True, transient_approved=True)
    setup['verified'] = True
    for name, value in [('feedforward.json', table), ('settings.json', setup),
                        ('entry_profile.json', entry)]:
        (source/name).write_text(json.dumps(value))
    generate(tmp_path/'trial', source_dir=source)


def test_pi_records_state_only_during_measurement(tmp_path):
    from brushbot.experiments.fake import FakeArm, FakeClock, FakeMagneticSource
    from scripts.run_strokeplan_experiment import build_stack, run_recorded
    from brushbot.target_strokeplan import StrokePlan
    generate_trial(tmp_path)
    root = tmp_path/'trial'
    plan = StrokePlan.load(root/'plateau_160_240_160.npz')
    artifacts = {name: (root/name).read_bytes() for name in
                 ('feedforward.json', 'settings.json', 'entry_profile.json')}
    artifacts['strokeplan.npz'] = (root/'plateau_160_240_160.npz').read_bytes()
    table, setup, entry = [json.loads(artifacts[name]) for name in
                          ('feedforward.json', 'settings.json', 'entry_profile.json')]
    clock = FakeClock()
    arm = FakeArm((-.370, .5, .13, 0., np.pi/12, 0.), clock=clock)
    source = FakeMagneticSource(arm, clock, contact_z_mm=40.)
    engine, hub = build_stack(plan=plan, table=table, setup=setup,
        artifacts=artifacts, label='pi', root=tmp_path/'runs', arm=arm,
        source=source, clock=clock, control_mode='pi', feedback_profile=profile(),
        entry_profile=entry)
    result = run_recorded(engine, hub, clock=clock)
    assert result['state'] == 'END_WAIT', result
    folder = Path(result['run_dir'])
    rows = [json.loads(line) for line in (folder/'control.jsonl').read_text().splitlines()]
    measure = [r for r in rows if r['phase'] == 'measure_00']
    assert len(measure) == engine.feedback_calls == 1501
    assert all(abs(r['i_correction_m']) <= .0002 for r in measure)
    assert any(r['integral_blocked'] for r in measure)
    assert all(r['i_correction_m'] == r['depth_fb_m'] == 0
               for r in rows if r['phase'] != 'measure_00')
    assert engine._spec['control']['ki'] == .05
    assert engine._spec['control']['mode'] == 'pi'
    assert json.loads((folder/'resolved.json').read_text())['control'] == engine._spec['control']


@pytest.mark.parametrize('mode', ['p', 'pi'])
def test_batch_preview_is_offline_and_has_equal_total_limits(tmp_path, monkeypatch, capsys, mode):
    from scripts import run_strokeplan_trial as runner
    generate_trial(tmp_path)
    monkeypatch.setattr(runner, 'TRIAL', tmp_path/'trial')
    monkeypatch.setattr(runner, 'EXPERIMENT', 'short_plateau')
    monkeypatch.setattr(runner, 'MODE', mode)
    monkeypatch.setattr(runner, 'RUN_ROOT', tmp_path/'runs')
    assert runner.main([]) == 0
    out = capsys.readouterr().out
    assert '未连接硬件' in out
    assert '±0.8 mm' in out
    assert '08_短平台P与PI对比' in out
    if mode == 'pi':
        assert 'ki=0.05' in out and '抗饱和' in out
    assert not (tmp_path/'runs').exists()
    monkeypatch.setattr('builtins.input', lambda _: 'NO')
    assert runner.main(['--mode', mode, '--execute']) == 0
    assert not (tmp_path/'runs').exists()


def test_short_target_has_three_equal_platforms_and_preserves_xy(tmp_path):
    from brushbot.target_strokeplan import StrokePlan
    from brushbot.experiments.strokeplan_execution import compile_recorded_plan
    generate_trial(tmp_path)
    root = tmp_path/'trial'
    plan = StrokePlan.load(root/'plateau_160_240_160.npz')
    st = plan.strokes[0]
    assert st.t[-1] == 30
    assert len(st.t) == 1501
    assert np.all(st.g_target[st.t <= 8] == 160)
    assert np.all(st.g_target[(st.t >= 11) & (st.t <= 19)] == 240)
    assert np.all(st.g_target[st.t >= 22] == 160)
    assert st.xy[-1, 0]-st.xy[0, 0] == pytest.approx(.3)
    assert np.diff(st.xy[:, 0])/.02 == pytest.approx(.01)
    read = lambda name: json.loads((root/name).read_text())
    c = compile_recorded_plan(plan, read('feedforward.json'), read('settings.json'),
        label='pi', control_mode='pi', feedback_profile=read('pi_profile.json'),
        entry_profile=read('entry_profile.json'))
    assert c['pose_m_rad'][:, 0].max() == pytest.approx(-.020)
    assert c['pose_m_rad'][-1] == pytest.approx(c['pose_m_rad'][0])
