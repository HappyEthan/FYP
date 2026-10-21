"""The Ki scan selects frozen profiles and remains offline until operator RUN."""
import json

import pytest

from tests.test_short_plateau_pi_experiment import generate_trial


def prepare(tmp_path, monkeypatch):
    from scripts import run_strokeplan_trial as runner
    generate_trial(tmp_path)
    root=tmp_path/'trial'
    base=json.loads((root/'pi_profile.json').read_text())
    for ki in [.025,.05,.1]:
        (root/f'pi_ki_{ki:g}.json').write_text(json.dumps(dict(base,ki=ki)))
    (root/'protocol.json').write_text(json.dumps({'ki_sequence':[.05,.025,.1,.1,.025,.05]}))
    monkeypatch.setattr(runner,'TRIAL',root)
    monkeypatch.setattr(runner,'EXPERIMENT','ki_scan')
    monkeypatch.setattr(runner,'RUN_ROOT',tmp_path/'runs')
    return runner,root


@pytest.mark.parametrize('step,ki', [(1,.05),(2,.025),(3,.1),(4,.1),(5,.025),(6,.05)])
def test_each_step_uses_expected_gain_and_shared_limits(tmp_path,monkeypatch,capsys,step,ki):
    runner,root=prepare(tmp_path,monkeypatch)
    before={p.name:p.read_bytes() for p in root.iterdir() if p.is_file()}
    assert runner.main(['--step',str(step)])==0
    output=capsys.readouterr().out
    assert f'kp=1, ki={ki:g}' in output
    assert '±0.8 mm' in output and '积分单独限幅 ±0.2 mm' in output
    assert '09_短平台Ki参数扫描' in output
    assert '未连接硬件' in output
    assert not (tmp_path/'runs').exists()
    assert before=={p.name:p.read_bytes() for p in root.iterdir() if p.is_file()}


def test_execute_requires_run_and_declining_creates_no_run(tmp_path,monkeypatch):
    runner,_=prepare(tmp_path,monkeypatch)
    prompts=[]
    def decline(prompt):
        prompts.append(prompt)
        return 'NO'
    monkeypatch.setattr('builtins.input',decline)
    assert runner.main(['--step','3','--execute'])==0
    assert len(prompts)==1 and 'RUN' in prompts[0]
    assert not (tmp_path/'runs').exists()


@pytest.mark.parametrize('args',[['--step','0'],['--step','7']])
def test_invalid_step_rejected(tmp_path,monkeypatch,args):
    runner,_=prepare(tmp_path,monkeypatch)
    with pytest.raises(SystemExit,match='2'):runner.main(args)
    assert not (tmp_path/'runs').exists()


def test_edited_scan_step_runs_without_command_line_arguments(tmp_path, monkeypatch, capsys):
    runner,_=prepare(tmp_path,monkeypatch)
    monkeypatch.setattr(runner,'KI_STEP',3)
    assert runner.main([])==0
    output=capsys.readouterr().out
    assert '第 3/6 笔' in output and 'kp=1, ki=0.1' in output
    assert '未连接硬件' in output
    assert not (tmp_path/'runs').exists()


@pytest.mark.parametrize('step',[0,7])
def test_edited_scan_step_outside_protocol_is_rejected(tmp_path,monkeypatch,step):
    runner,_=prepare(tmp_path,monkeypatch)
    monkeypatch.setattr(runner,'KI_STEP',step)
    with pytest.raises(SystemExit,match='2'):
        runner.main([])
    assert not (tmp_path/'runs').exists()


@pytest.mark.parametrize('change',[{'ki':.2},{'kp':2.},{'integral_limit_mm':.4},
                                  {'max_correction_mm':1.6}])
def test_profile_changes_cannot_silently_change_scan(tmp_path,monkeypatch,change):
    runner,root=prepare(tmp_path,monkeypatch)
    path=root/'pi_ki_0.05.json'
    profile=json.loads(path.read_text());profile.update(change);path.write_text(json.dumps(profile))
    with pytest.raises(SystemExit,match='2'):runner.main(['--step','1'])
    assert not (tmp_path/'runs').exists()
