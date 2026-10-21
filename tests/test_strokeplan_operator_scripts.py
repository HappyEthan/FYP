"""The shared launcher reads editable experiment settings and stays offline by default."""
import json

import pytest

from tests.test_strokeplan_experiment import inputs


@pytest.mark.parametrize('experiment,mode_text', [
    ('strokeplan_ff', '纯前馈'),
    ('strokeplan_p', '受限 P'),
])
def test_edited_settings_preview_without_command_line_arguments(
        tmp_path, monkeypatch, capsys, experiment, mode_text):
    from scripts import run_strokeplan_trial as module
    _, _, _, artifacts = inputs(tmp_path)
    for name, data in artifacts.items():
        (tmp_path/name).write_bytes(data)
    monkeypatch.setattr(module, 'FEEDFORWARD', tmp_path/'feedforward.json')
    monkeypatch.setattr(module, 'SETTINGS', tmp_path/'settings.json')
    monkeypatch.setattr(module, 'RUN_ROOT', tmp_path/'runs')
    monkeypatch.setattr(module, 'EXPERIMENT', experiment)
    monkeypatch.setattr(module, 'TRIAL', tmp_path)
    monkeypatch.setattr(module, 'STROKEPLAN', 'target.npz')

    assert module.main([]) == 0
    output = capsys.readouterr().out
    assert mode_text in output
    assert str(tmp_path/'feedforward.json') in output
    assert str(tmp_path/'settings.json') in output
    assert '未连接硬件' in output
    assert not (tmp_path/'runs').exists()


@pytest.mark.parametrize('experiment', [
    'strokeplan_ff', 'strokeplan_p',
])
def test_single_plan_argument_requires_run_confirmation_before_hardware(
        tmp_path, monkeypatch, experiment):
    from scripts import run_strokeplan_trial as module
    _, table, setup, artifacts = inputs(tmp_path)
    table['approved'] = table['transient_approved'] = True
    setup['verified'] = True
    (tmp_path/'feedforward.json').write_text(json.dumps(table))
    (tmp_path/'settings.json').write_text(json.dumps(setup))
    monkeypatch.setattr(module, 'FEEDFORWARD', tmp_path/'feedforward.json')
    monkeypatch.setattr(module, 'SETTINGS', tmp_path/'settings.json')
    monkeypatch.setattr(module, 'RUN_ROOT', tmp_path/'runs')
    prompts = []

    def decline(prompt):
        prompts.append(prompt)
        return 'NO'

    monkeypatch.setattr('builtins.input', decline)
    assert module.main(['--experiment', experiment, str(tmp_path/'target.npz'), '--execute']) == 0
    assert len(prompts) == 1 and 'RUN' in prompts[0]
    assert not (tmp_path/'runs').exists()


def test_launcher_keeps_site_options_in_the_editable_settings():
    from scripts import run_strokeplan_trial as module
    with pytest.raises(SystemExit, match='2'):
        module.main(['plan.npz', '--settings', 'other.json'])


def test_positional_plan_path_remains_relative_to_the_working_directory(
        tmp_path, monkeypatch, capsys):
    from scripts import run_strokeplan_trial as module
    _, _, _, artifacts = inputs(tmp_path)
    for name, data in artifacts.items():
        (tmp_path/name).write_bytes(data)
    monkeypatch.setattr(module, 'FEEDFORWARD', tmp_path/'feedforward.json')
    monkeypatch.setattr(module, 'SETTINGS', tmp_path/'settings.json')
    monkeypatch.setattr(module, 'RUN_ROOT', tmp_path/'runs')
    monkeypatch.chdir(tmp_path)
    assert module.main(['--experiment', 'strokeplan_ff', 'target.npz', '--dry-run']) == 0
    assert '未连接硬件' in capsys.readouterr().out
    assert not (tmp_path/'runs').exists()


@pytest.mark.parametrize('options',[['--stroke','4'],['--step','2']])
def test_single_plan_does_not_silently_ignore_other_experiments_options(
        tmp_path,monkeypatch,options):
    from scripts import run_strokeplan_trial as module
    _,_,_,artifacts=inputs(tmp_path)
    for name,data in artifacts.items():
        (tmp_path/name).write_bytes(data)
    monkeypatch.setattr(module,'TRIAL',tmp_path)
    monkeypatch.setattr(module,'STROKEPLAN','target.npz')
    monkeypatch.setattr(module,'RUN_ROOT',tmp_path/'runs')
    with pytest.raises(SystemExit,match='2'):
        module.main(['--experiment','strokeplan_ff',*options])
    assert not (tmp_path/'runs').exists()


def test_p_script_uses_its_edited_gain_and_limits_in_preview(tmp_path, monkeypatch, capsys):
    from scripts import run_strokeplan_trial as module
    _, _, _, artifacts = inputs(tmp_path)
    for name, data in artifacts.items():
        (tmp_path/name).write_bytes(data)
    monkeypatch.setattr(module, 'FEEDFORWARD', tmp_path/'feedforward.json')
    monkeypatch.setattr(module, 'SETTINGS', tmp_path/'settings.json')
    monkeypatch.setattr(module, 'EXPERIMENT', 'strokeplan_p')
    profile = dict(module.P_PROFILE, kp=.04, max_correction_mm=.12)
    monkeypatch.setattr(module, 'P_PROFILE', profile)

    assert module.main([str(tmp_path/'target.npz'), '--dry-run']) == 0
    output = capsys.readouterr().out
    assert 'kp=0.04' in output
    assert '±0.12 mm' in output


def test_p_script_previews_optional_actual_tcp_recording_without_hardware(
        tmp_path, monkeypatch, capsys):
    from scripts import run_strokeplan_trial as module
    _, _, _, artifacts = inputs(tmp_path)
    for name, data in artifacts.items():
        (tmp_path/name).write_bytes(data)
    monkeypatch.setattr(module, 'FEEDFORWARD', tmp_path/'feedforward.json')
    monkeypatch.setattr(module, 'SETTINGS', tmp_path/'settings.json')
    monkeypatch.setattr(module, 'RUN_ROOT', tmp_path/'runs')
    monkeypatch.setattr(module, 'EXPERIMENT', 'strokeplan_p')

    assert module.main([
        str(tmp_path/'target.npz'), '--record-actual-tcp', '--dry-run']) == 0
    output = capsys.readouterr().out
    assert '实际 TCP 独立采集: 10 Hz' in output
    assert '未连接硬件' in output
    assert not (tmp_path/'runs').exists()


def test_actual_tcp_option_still_requires_run_before_connections(tmp_path, monkeypatch):
    from scripts import run_strokeplan_trial as module
    _, calibration, setup, artifacts = inputs(tmp_path)
    calibration['approved'] = calibration['transient_approved'] = True
    setup['verified'] = True
    (tmp_path/'strokeplan.npz').write_bytes(artifacts['strokeplan.npz'])
    (tmp_path/'feedforward.json').write_text(json.dumps(calibration))
    (tmp_path/'settings.json').write_text(json.dumps(setup))
    monkeypatch.setattr(module, 'FEEDFORWARD', tmp_path/'feedforward.json')
    monkeypatch.setattr(module, 'SETTINGS', tmp_path/'settings.json')
    monkeypatch.setattr(module, 'RUN_ROOT', tmp_path/'runs')
    monkeypatch.setattr(module, 'EXPERIMENT', 'strokeplan_p')
    monkeypatch.setattr('builtins.input', lambda prompt: 'NO')

    assert module.main([
        str(tmp_path/'strokeplan.npz'), '--record-actual-tcp', '--execute']) == 0
    assert not (tmp_path/'runs').exists()


def test_edited_execute_setting_still_requires_run_confirmation(tmp_path, monkeypatch):
    from scripts import run_strokeplan_trial as module
    _, table, setup, artifacts = inputs(tmp_path)
    table.update(approved=True, transient_approved=True)
    setup['verified'] = True
    (tmp_path/'feedforward.json').write_text(json.dumps(table))
    (tmp_path/'settings.json').write_text(json.dumps(setup))
    monkeypatch.setattr(module, 'EXPERIMENT', 'strokeplan_ff')
    monkeypatch.setattr(module, 'EXECUTE', True)
    monkeypatch.setattr(module, 'STROKEPLAN', tmp_path/'target.npz')
    monkeypatch.setattr(module, 'FEEDFORWARD', tmp_path/'feedforward.json')
    monkeypatch.setattr(module, 'SETTINGS', tmp_path/'settings.json')
    monkeypatch.setattr(module, 'RUN_ROOT', tmp_path/'runs')
    prompts = []

    def decline(prompt):
        prompts.append(prompt)
        return 'NO'

    monkeypatch.setattr('builtins.input', decline)
    assert module.main([]) == 0
    assert len(prompts) == 1 and 'RUN' in prompts[0]
    assert not (tmp_path/'runs').exists()


@pytest.mark.parametrize('experiment,options', [
    ('strokeplan_ff', ['--mode', 'pi']),
    ('strokeplan_p', ['--mode', 'feedforward']),
    ('short_plateau', ['--mode', 'ff']),
    ('ki_scan', ['--mode', 'p']),
    ('calligraphy', ['--mode', 'p']),
    ('strokeplan_ff', ['--kp', '.5']),
    ('short_plateau', ['--p-dynamics', 'smooth']),
])
def test_incompatible_experiment_options_are_rejected_before_loading_files(
        tmp_path, monkeypatch, experiment, options):
    from scripts import run_strokeplan_trial as module
    monkeypatch.setattr(module, 'TRIAL', tmp_path/'missing')
    monkeypatch.setattr(module, 'RUN_ROOT', tmp_path/'runs')
    with pytest.raises(SystemExit, match='2'):
        module.main(['--experiment', experiment, *options])
    assert not (tmp_path/'runs').exists()
