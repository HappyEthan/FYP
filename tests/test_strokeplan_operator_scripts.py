"""The two operator entrypoints require only a target StrokePlan path."""
import json

import pytest

from tests.test_strokeplan_experiment import inputs


@pytest.mark.parametrize('module_name,mode_text', [
    ('run_strokeplan_feedforward', '纯前馈'),
    ('run_strokeplan_p', '受限 P'),
])
def test_single_plan_argument_previews_fixed_mode_without_hardware(
        tmp_path, monkeypatch, capsys, module_name, mode_text):
    from importlib import import_module
    module = import_module('scripts.' + module_name)
    _, _, _, artifacts = inputs(tmp_path)
    for name, data in artifacts.items():
        (tmp_path/name).write_bytes(data)
    monkeypatch.setattr(module, 'FEEDFORWARD', tmp_path/'feedforward.json')
    monkeypatch.setattr(module, 'SETTINGS', tmp_path/'settings.json')
    monkeypatch.setattr(module, 'RUN_ROOT', tmp_path/'runs')

    assert module.main([str(tmp_path/'target.npz'), '--dry-run']) == 0
    output = capsys.readouterr().out
    assert mode_text in output
    assert str(tmp_path/'feedforward.json') in output
    assert str(tmp_path/'settings.json') in output
    assert '未连接硬件' in output
    assert not (tmp_path/'runs').exists()


@pytest.mark.parametrize('module_name', [
    'run_strokeplan_feedforward', 'run_strokeplan_p',
])
def test_single_plan_argument_requires_run_confirmation_before_hardware(
        tmp_path, monkeypatch, module_name):
    from importlib import import_module
    module = import_module('scripts.' + module_name)
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
    assert module.main([str(tmp_path/'target.npz')]) == 0
    assert len(prompts) == 1 and 'RUN' in prompts[0]
    assert not (tmp_path/'runs').exists()


@pytest.mark.parametrize('module_name', [
    'run_strokeplan_feedforward', 'run_strokeplan_p',
])
def test_operator_scripts_do_not_accept_site_options_from_command_line(module_name):
    from importlib import import_module
    module = import_module('scripts.' + module_name)
    with pytest.raises(SystemExit, match='2'):
        module.main(['plan.npz', '--settings', 'other.json'])


def test_p_script_uses_its_edited_gain_and_limits_in_preview(tmp_path, monkeypatch, capsys):
    from scripts import run_strokeplan_p as module
    _, _, _, artifacts = inputs(tmp_path)
    for name, data in artifacts.items():
        (tmp_path/name).write_bytes(data)
    monkeypatch.setattr(module, 'FEEDFORWARD', tmp_path/'feedforward.json')
    monkeypatch.setattr(module, 'SETTINGS', tmp_path/'settings.json')
    profile = dict(module.PROFILE, kp=.04, max_correction_mm=.12)
    monkeypatch.setattr(module, 'PROFILE', profile)

    assert module.main([str(tmp_path/'target.npz'), '--dry-run']) == 0
    output = capsys.readouterr().out
    assert 'kp=0.04' in output
    assert '±0.12 mm' in output


def test_p_script_previews_optional_actual_tcp_recording_without_hardware(
        tmp_path, monkeypatch, capsys):
    from scripts import run_strokeplan_p as module
    _, _, _, artifacts = inputs(tmp_path)
    for name, data in artifacts.items():
        (tmp_path/name).write_bytes(data)
    monkeypatch.setattr(module, 'FEEDFORWARD', tmp_path/'feedforward.json')
    monkeypatch.setattr(module, 'SETTINGS', tmp_path/'settings.json')
    monkeypatch.setattr(module, 'RUN_ROOT', tmp_path/'runs')

    assert module.main([
        str(tmp_path/'target.npz'), '--record-actual-tcp', '--dry-run']) == 0
    output = capsys.readouterr().out
    assert '实际 TCP 独立采集: 10 Hz' in output
    assert '未连接硬件' in output
    assert not (tmp_path/'runs').exists()


def test_actual_tcp_option_still_requires_run_before_connections(tmp_path, monkeypatch):
    from scripts import run_strokeplan_p as module
    _, calibration, setup, artifacts = inputs(tmp_path)
    calibration['approved'] = calibration['transient_approved'] = True
    setup['verified'] = True
    (tmp_path/'strokeplan.npz').write_bytes(artifacts['strokeplan.npz'])
    (tmp_path/'feedforward.json').write_text(json.dumps(calibration))
    (tmp_path/'settings.json').write_text(json.dumps(setup))
    monkeypatch.setattr(module, 'FEEDFORWARD', tmp_path/'feedforward.json')
    monkeypatch.setattr(module, 'SETTINGS', tmp_path/'settings.json')
    monkeypatch.setattr(module, 'RUN_ROOT', tmp_path/'runs')
    monkeypatch.setattr('builtins.input', lambda prompt: 'NO')

    assert module.main([
        str(tmp_path/'strokeplan.npz'), '--record-actual-tcp']) == 0
    assert not (tmp_path/'runs').exists()
