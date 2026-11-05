"""Failure evidence survives normal aborts, process death and recovery failures."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from brushbot.experiments.archive import ExperimentArchive, read_json, write_json


def test_deadline_failure_preserves_raw_bytes_result_log_and_settings(tmp_path):
    store = ExperimentArchive(tmp_path/'records')
    raw = b'seq,Bx_uT,By_uT,Bz_uT\n1,1,2,3\n2,4,5,6\n'
    diagnostic = dict(checkpoint='before_push', lateness_s=.13, allowed_lateness_s=.1,
                      trajectory_phase='measure_01', command_duration_s=.12)
    with store.session() as stage:
        inputs = stage/'plan'
        inputs.mkdir()
        (inputs/'settings.json').write_text('{"max_tick_lateness_s": 0.1}')
        folder = stage/'raw/day/run'
        folder.mkdir(parents=True)
        (folder/'sensor.csv').write_bytes(raw)
        write_json(folder/'manifest.json', dict(status='aborted', reason='deadline_miss', run_id='r1'))
        store.record_result(stage, dict(state='ABORTED', progress=.451, run_id='r1',
            last_error='deadline_miss', deadline_diagnostic=diagnostic))
        print('captured console: deadline_miss')
    failed = next(store.failures.iterdir())
    assert (failed/'raw/day/run/sensor.csv').read_bytes() == raw
    assert (failed/'plan/settings.json').exists()
    result = read_json(failed/'failure.json')
    assert result['reason'] == 'deadline_miss'
    assert result['result']['deadline_diagnostic'] == diagnostic
    assert result['recordings'][0]['status'] == 'aborted'
    assert not result['automatically_deleted']
    assert 'captured console: deadline_miss' in (failed/'console.log').read_text()
    assert store.records() == []
    assert store.preview_name() == '毛笔试写_001'
    # Later startups do not sweep retained failures or consume success numbers.
    assert ExperimentArchive(store.root).cleanup_stale() == []
    assert (failed/'raw/day/run/sensor.csv').read_bytes() == raw


def test_sigkill_session_is_retained_on_next_start_without_touching_raw_manifest(tmp_path):
    root = tmp_path/'records'
    source = '''
import sys, time
from brushbot.experiments.archive import ExperimentArchive, write_json
store=ExperimentArchive(sys.argv[1])
with store.session() as stage:
    raw=stage/'raw/run'
    raw.mkdir(parents=True)
    (raw/'sensor.csv').write_bytes(b'last raw frame\\n')
    write_json(raw/'manifest.json', dict(status='running', run_id='killed'))
    print('READY', flush=True)
    time.sleep(60)
'''
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    child = subprocess.Popen([sys.executable, '-u', '-c', source, str(root)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    try:
        assert child.stdout.readline().strip() == 'READY'
        child.kill()
        child.wait(timeout=5)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        child.stdout.close()
        child.stderr.close()
    store = ExperimentArchive(root)
    assert store.cleanup_stale() == []
    failed = next(store.failures.iterdir())
    assert (failed/'raw/run/sensor.csv').read_bytes() == b'last raw frame\n'
    assert read_json(failed/'raw/run/manifest.json')['status'] == 'running'
    assert read_json(failed/'failure.json')['reason'] == 'recovered_after_unclean_shutdown'
    assert 'READY' in (failed/'console.log').read_text()
    assert not list(store.temporary.iterdir())


def test_retention_move_failure_leaves_original_data_and_diagnostics(tmp_path, monkeypatch):
    store = ExperimentArchive(tmp_path/'records')
    stage = store.new_stage()
    (stage/'sensor.csv').write_bytes(b'partial frame')
    original = Path.rename
    def rename(path, target):
        if path == stage:
            raise OSError('read-only target')
        return original(path, target)
    monkeypatch.setattr(Path, 'rename', rename)
    assert store.retain_stage(stage) == stage
    assert (stage/'sensor.csv').read_bytes() == b'partial frame'
    assert (stage/'failure.json').is_file()




@pytest.mark.parametrize('outcome', ['error', 'interrupt', 'abort', 'cancel'])
def test_direct_editor_trial_retains_inputs_and_startup_failures(tmp_path, monkeypatch, outcome):
    from scripts import run_edited_brush_path as runner
    inputs = tmp_path/'original_plan'
    inputs.mkdir()
    settings = b'{"example_setting": 1}\n'
    (inputs/'settings.json').write_bytes(settings)
    root = tmp_path/'records'
    def execute(args):
        assert args.plan_dir == inputs  # Execution still reads the selected plan.
        assert args.consume_stage.is_dir()
        print('startup diagnostic')
        if outcome == 'error':
            raise RuntimeError('startup failed')
        if outcome == 'interrupt':
            raise KeyboardInterrupt
        return 2 if outcome == 'abort' else 0
    monkeypatch.setattr(runner, 'run_plan', execute)
    argv = [str(inputs), '--execute', '--run-root', str(root)]
    if outcome in ('error', 'interrupt'):
        with pytest.raises(RuntimeError if outcome == 'error' else KeyboardInterrupt):
            runner.main(argv)
    else:
        assert runner.main(argv) == (2 if outcome == 'abort' else 0)
    store = ExperimentArchive(root)
    failed = list(store.failures.iterdir())
    assert len(failed) == 1
    assert (failed[0]/'inputs/settings.json').read_bytes() == settings
    assert (inputs/'settings.json').read_bytes() == settings
    assert 'startup diagnostic' in (failed[0]/'console.log').read_text()
    failure = read_json(failed[0]/'failure.json')
    if outcome in ('error', 'interrupt'):
        assert failure['exception']['type'] == ('RuntimeError' if outcome == 'error' else 'KeyboardInterrupt')
    assert not list(store.temporary.iterdir())
    assert not store.records()
    assert store.preview_name() == '毛笔试写_001'
    store.cleanup_stale()
    assert failed[0].is_dir()


def test_direct_preview_does_not_create_retained_experiment(tmp_path, monkeypatch):
    from scripts import run_edited_brush_path as runner
    root = tmp_path/'records'
    monkeypatch.setattr(runner, 'run_plan', lambda args: 0)
    assert runner.main([str(tmp_path/'plan'), '--run-root', str(root)]) == 0
    assert not root.exists()


@pytest.mark.parametrize('interrupt', [False, True])
def test_execution_uses_original_streams_without_archive_log_io(tmp_path, monkeypatch, interrupt):
    from brushbot.experiments.archive import _ConsoleTee, terminal_stream, without_console_capture
    from scripts.run_ladder_experiment import LiveStatusPanel
    store = ExperimentArchive(tmp_path/'records')
    stage = store.new_stage()
    original_stdout, original_stderr = sys.stdout, sys.stderr
    with store.capture_console(stage):
        wrapped_stdout, wrapped_stderr = sys.stdout, sys.stderr
        print('before hardware')
        # Any accidental use of even a cached archive stream must fail here.
        def forbidden(*args):
            raise AssertionError('Archive console I/O during hardware execution')
        with monkeypatch.context() as patch:
            patch.setattr(_ConsoleTee, 'write', forbidden)
            patch.setattr(_ConsoleTee, 'flush', forbidden)
            panel = LiveStatusPanel(terminal_stream(wrapped_stdout))
            try:
                with without_console_capture():
                    assert sys.stdout is original_stdout
                    assert sys.stderr is original_stderr
                    print('hardware stdout')
                    print('hardware stderr', file=sys.stderr)
                    panel.update(('original live display',))
                    if interrupt:
                        raise KeyboardInterrupt
            except KeyboardInterrupt:
                assert interrupt
            finally:
                panel.close()
        assert sys.stdout is wrapped_stdout and sys.stderr is wrapped_stderr
        print('after hardware')
    log = (stage/'console.log').read_text()
    assert 'before hardware' in log and 'after hardware' in log
    assert 'hardware stdout' not in log and 'hardware stderr' not in log
    assert 'original live display' not in log
    assert sys.stdout is original_stdout and sys.stderr is original_stderr
    store.discard_stage(stage)
