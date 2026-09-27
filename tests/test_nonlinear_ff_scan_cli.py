"""Scan options must reach the real preview and remain offline by default."""
import json

import pytest

from tests.test_strokeplan_rotational_entry import fixture


def trial(tmp_path, monkeypatch):
    from scripts import run_nonlinear_ff_comparison as runner
    plan, table, setup, entry = fixture(tmp_path)
    plan.save(tmp_path/'hard_160_240.npz')
    profile = dict(kp=2., ki=0., max_correction_mm=.4,
                   max_correction_speed_mm_s=5., max_correction_accel_mm_s2=70.,
                   taper_ticks=25)
    for name, value in [('feedforward.json',table), ('settings.json',setup),
                        ('entry_profile.json',entry), ('p_profile.json',profile)]:
        (tmp_path/name).write_text(json.dumps(value))
    monkeypatch.setattr(runner, 'TRIAL', tmp_path)
    monkeypatch.setattr(runner, 'RUN_ROOT', tmp_path/'runs')
    return runner


@pytest.mark.parametrize('kp', [.25, .5, 1.])
@pytest.mark.parametrize('cap', [.4, .8])
def test_scan_preview_resolves_parameters_and_identifies_saved_condition(
        tmp_path, monkeypatch, capsys, kp, cap):
    runner = trial(tmp_path, monkeypatch)
    before = (tmp_path/'p_profile.json').read_bytes()
    assert runner.main(['--mode','p','--kp',str(kp),'--max-correction-mm',str(cap),
                        '--p-dynamics','smooth']) == 0
    out = capsys.readouterr().out
    assert f'kp={kp:g}, ki=0' in out
    assert f'±{cap:g} mm' in out
    assert '修正速度 2 mm/s、加速度 30 mm/s²' in out
    assert '07_非线性前馈P参数扫描' in out
    assert f'前馈加P{kp:g}_修正{cap:g}mm_平滑_渐变1s' in out
    assert '未连接硬件' in out
    assert not (tmp_path/'runs').exists()
    assert (tmp_path/'p_profile.json').read_bytes() == before


def test_legacy_invocation_keeps_original_profile_and_folder(tmp_path, monkeypatch, capsys):
    runner = trial(tmp_path, monkeypatch)
    assert runner.main(['--mode','p']) == 0
    out = capsys.readouterr().out
    assert 'kp=2, ki=0' in out and '±0.4 mm' in out
    assert '修正速度 5 mm/s、加速度 70 mm/s²' in out
    assert '06_非线性前馈难曲线对比' in out


@pytest.mark.parametrize('args', [
    ['--mode','ff','--kp','.5'],
    ['--mode','ff','--max-correction-mm','.8'],
    ['--mode','ff','--p-dynamics','smooth'],
    ['--mode','p','--kp','nan'],
    ['--mode','p','--kp','-1'],
    ['--mode','p','--max-correction-mm','0'],
    ['--mode','p','--max-correction-mm','30'],
])
def test_invalid_scan_options_fail_before_creating_a_run(tmp_path, monkeypatch, args):
    runner = trial(tmp_path, monkeypatch)
    with pytest.raises(SystemExit, match='2'):
        runner.main(args)
    assert not (tmp_path/'runs').exists()


def test_scan_execute_still_requires_operator_run_before_hardware(tmp_path, monkeypatch):
    runner = trial(tmp_path, monkeypatch)
    table = json.loads((tmp_path/'feedforward.json').read_text())
    table.update(approved=True, transient_approved=True)
    (tmp_path/'feedforward.json').write_text(json.dumps(table))
    setup = json.loads((tmp_path/'settings.json').read_text())
    setup['verified'] = True
    (tmp_path/'settings.json').write_text(json.dumps(setup))
    prompts = []

    def decline(prompt):
        prompts.append(prompt)
        return 'NO'

    monkeypatch.setattr('builtins.input', decline)
    assert runner.main(['--mode','p','--kp','.5','--max-correction-mm','.8',
                        '--p-dynamics','smooth','--execute']) == 0
    assert len(prompts) == 1 and 'RUN' in prompts[0]
    assert not (tmp_path/'runs').exists()
