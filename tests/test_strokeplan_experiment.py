"""Single target execution must produce the existing run contract, without hardware."""
import copy
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from brushbot.experiments.fake import FakeArm, FakeClock, FakeMagneticSource
from scripts.generate_strokeplan import generate
from tests.test_target_feedforward import settings, table


def inputs(tmp_path):
    setup = settings()
    setup.update(approach_speed_mm_s=10., return_speed_mm_s=10.,
                 pose_tolerance_mm=.5, orientation_tolerance_rad=.017,
                 baseline_window_s=.04, baseline_timeout_s=.2,
                 baseline_min_samples=3, baseline_max_std_uT=[.1]*3,
                 baseline_max_drift_uT_s=.1, sensor_max_age_s=.1,
                 max_tick_lateness_s=.05, stop_timeout_s=1.,
                 gripper_width_mm=14., gripper_speed=30, gripper_force=30)
    plan = generate(targets_uT=[30.], length_mm=20.)
    target_path = tmp_path / 'target.npz'
    plan.save(target_path)
    artifacts = {'strokeplan.npz': target_path.read_bytes(),
                 'feedforward.json': json.dumps(table()).encode(),
                 'settings.json': json.dumps(setup).encode()}
    return plan, table(), setup, artifacts


def stack(tmp_path, source_type=FakeMagneticSource, control_mode='feedforward',
          experiment_folder=None, run_folder_label=None, input_dir=None):
    from scripts.run_strokeplan_experiment import build_stack
    plan, calibration, setup, artifacts = inputs(input_dir or tmp_path)
    clock = FakeClock()
    arm = FakeArm((-.2, .5, .13, *setup['vertical_rpy_rad']), clock=clock)
    arm.realtime_state_reads = False
    source = source_type(arm, clock, contact_z_mm=37.)
    engine, hub = build_stack(plan=plan, table=calibration, setup=setup,
                             artifacts=artifacts, label='strokeplan_01_test',
                             root=tmp_path/'runs'/'brush2', arm=arm,
                             source=source, clock=clock, control_mode=control_mode,
                             experiment_folder=experiment_folder,
                             run_folder_label=run_folder_label)
    return engine, hub, arm, source, clock, artifacts


def auto_position_stack(tmp_path, monkeypatch, *, pose=(-.18, .52, .05, 0., -.26, 0.),
                        fsm=33):
    from functools import partial
    from scripts import run_strokeplan_experiment as runner
    from scripts import run_four_direction_sweep as positioning

    plan, calibration, setup, artifacts = inputs(tmp_path)
    clock = FakeClock()
    arm = FakeArm(pose, fsm=fsm, clock=clock)
    arm.realtime_state_reads = False

    class BufferedSource(FakeMagneticSource):
        discarded = False

        def discard_pending(self):
            assert self.arm.pose == pytest.approx((-.2, .5, .13, 0., .2617993877991494, 0.))
            self.discarded = True
            return {'discarded_bytes': 4096}

        def read_frames(self):
            assert self.discarded, 'baseline must not use data buffered during positioning'
            return super().read_frames()

    source = BufferedSource(arm, clock, contact_z_mm=37.)
    monkeypatch.setattr(positioning, 'position_at_wait', partial(positioning.position_at_wait,
        sleep=clock.advance, monotonic=lambda: clock.now_ns()/1e9))
    engine, hub = runner.build_stack(
        plan=plan, table=calibration, setup=setup, artifacts=artifacts,
        label='automatic_wait_test', root=tmp_path/'runs'/'brush2',
        arm=arm, source=source, clock=clock, auto_position=True)
    return engine, hub, arm, source, clock


def test_auto_position_lifts_before_transfer_then_starts_fresh_recorded_baseline(tmp_path, monkeypatch):
    from scripts.run_strokeplan_experiment import run_recorded
    engine, hub, arm, source, clock = auto_position_stack(tmp_path, monkeypatch)
    assert engine.state == 'READY'
    assert engine.run_id is None
    assert source.discarded
    assert not hub.baseline_ready
    moves = np.array([call['pose'] for call in arm.calls if call['action'] == 'push_pose'])
    below_wait = moves[:, 2] < .13 - 1e-9
    assert moves[below_wait, :2] == pytest.approx(np.tile([-.18, .52], (below_wait.sum(), 1)))
    turning = abs(moves[:, 4] + .26) > 1e-9
    assert moves[turning, :3] == pytest.approx(np.tile([-.2, .5, .13], (turning.sum(), 1)))
    assert arm.pose == pytest.approx((-.2, .5, .13, 0., .2617993877991494, 0.))

    result = run_recorded(engine, hub, clock=clock, sleep=lambda _: None)
    assert result['state'] == 'END_WAIT', result['last_error']
    folder = Path(result['run_dir'])
    resolved = json.loads((folder/'resolved.json').read_text())
    positioning = resolved['positioning']
    assert positioning['status'] == 'completed'
    assert positioning['initial_pose_m_rad'] == pytest.approx([-.18, .52, .05, 0., -.26, 0.])
    assert positioning['sensor_buffer_reset'] == {'discarded_bytes': 4096}
    independent_record = json.loads(Path(positioning['record_path']).read_text())
    assert independent_record['status'] == 'completed'
    assert independent_record['sensor_buffer_reset'] == {'discarded_bytes': 4096}
    manifest = json.loads((folder/'manifest.json').read_text())
    assert manifest['status'] == 'completed'
    assert len(manifest['baselines']) == 1


@pytest.mark.parametrize('pose,fsm', [
    ((-.5, .52, .05, 0., -.26, 0.), 33),
    ((-.18, .52, .05, 0., -.26, 0.), 0),
])
def test_auto_position_failure_is_retained_without_starting_experiment(tmp_path, monkeypatch, pose, fsm):
    with pytest.raises(RuntimeError):
        auto_position_stack(tmp_path, monkeypatch, pose=pose, fsm=fsm)
    records = list((tmp_path/'runs'/'brush2').rglob('positioning/*.json'))
    assert len(records) == 1
    attempt = json.loads(records[0].read_text())
    assert attempt['status'] == 'failed'
    assert attempt['completed_waypoints'] == 0
    assert attempt['timing']['commands_sent'] == 0
    assert not list((tmp_path/'runs'/'brush2').rglob('manifest.json'))


def test_auto_position_at_wait_does_not_send_motion_commands(tmp_path, monkeypatch):
    engine, _, arm, source, _ = auto_position_stack(
        tmp_path, monkeypatch, pose=(-.2, .5, .13, 0., .2617993877991494, 0.))
    assert engine.state == 'READY'
    assert source.discarded
    assert not arm.calls


def test_grouped_run_names_use_experiment_and_repeat_without_visible_id(tmp_path):
    from scripts.run_strokeplan_experiment import run_recorded
    folders = []
    for index in range(2):
        input_dir = tmp_path/f'input_{index}'
        input_dir.mkdir()
        engine, hub, _, _, clock, _ = stack(
            tmp_path, experiment_folder='01_四目标纯前馈',
            run_folder_label='渐进压笔', input_dir=input_dir)
        result = run_recorded(engine, hub, clock=clock, sleep=lambda _: None)
        assert result['state'] == 'END_WAIT'
        folders.append(Path(result['run_dir']))
    assert folders[0].parent == folders[1].parent
    assert folders[0].parent.parent.name == '01_四目标纯前馈'
    assert folders[0].parent.name == 'raw'
    assert folders[0].name.endswith('_渐进压笔_第1次')
    assert folders[1].name.endswith('_渐进压笔_第2次')
    for folder in folders:
        manifest = json.loads((folder/'manifest.json').read_text())
        assert manifest['run_id'].split('-')[-1] not in folder.name
        assert manifest['status'] == 'completed'


def test_single_run_records_sensor_targets_commands_and_exact_inputs(tmp_path):
    from scripts.run_strokeplan_experiment import run_recorded
    engine, hub, arm, source, clock, artifacts = stack(tmp_path)
    result = run_recorded(engine, hub, clock=clock, sleep=lambda _: None)
    assert result['state'] == 'END_WAIT'
    folder = Path(result['run_dir'])
    assert folder.parent.parent == tmp_path/'runs'/'brush2'
    assert '__strokeplan_01_test__' in folder.name
    manifest = json.loads((folder/'manifest.json').read_text())
    assert manifest['status'] == 'completed'
    assert json.loads((folder/'resolved.json').read_text())['control'] == {'enabled': False}
    assert manifest['execution_environment'] == 'synthetic'
    assert manifest['brush_id'] == 'brush2'
    assert len(manifest['baselines']) == 1
    for name in ('resolved.json', 'setup.json', 'timeline.npz', 'compiled_plan.npz',
                 'sensor.csv', 'control.jsonl', 'events.jsonl', *artifacts):
        assert (folder/name).exists()
    for name, payload in artifacts.items():
        assert (folder/name).read_bytes() == payload
        assert manifest['sha256'][name] == hashlib.sha256(payload).hexdigest()
    sensor = {int(r['seq']): r for r in csv.DictReader((folder/'sensor.csv').open())}
    rows = [json.loads(line) for line in (folder/'control.jsonl').read_text().splitlines()]
    measure = [r for r in rows if r['phase'].startswith('measure_')]
    assert len(measure) > 100
    assert {r['phase'] for r in measure} == {'measure_00'}
    for r in measure:
        assert r['a_ref_uT'] == 30.
        assert r['z_cmd_m'] == pytest.approx(.0295)
        assert r['depth_ff_m'] == pytest.approx(.0075)
        assert r['depth_fb_m'] == 0.
        assert r['e_center_uT'] == pytest.approx(30. - r['a_control_uT'])
        assert sensor[r['sample_seq']]['baseline_id'] == '0'
        assert r['actual_pose_available'] is False
    assert any(r['a_ref_uT'] is None for r in rows)
    assert arm.pose == pytest.approx((-.2, .5, .13, *settings()['vertical_rpy_rad']))
    assert sum(c['action'] == 'start_servo' for c in arm.calls) == 1
    assert engine.feedback_calls == 0


def test_target_timeline_preserves_varying_reference_and_20ms_spacing(tmp_path):
    from brushbot.experiments.strokeplan_execution import compile_recorded_plan
    _, calibration, setup, _ = inputs(tmp_path)
    plan = generate(targets_uT=[30., 70., 30.])
    result = compile_recorded_plan(plan, calibration, setup, label='variable')
    measure = np.array(result['phase']) == 'measure_00'
    assert result['g_ref_uT'][measure].min() == pytest.approx(30.)
    assert result['g_ref_uT'][measure].max() == pytest.approx(70.)
    assert np.diff(result['t_s']) == pytest.approx(np.full(len(result['t_s'])-1, .02))
    assert result['g_ref_uT'][~measure].tolist().count(None) == 0
    assert np.isnan(result['g_ref_uT'][~measure]).all()
    assert result['phase'][-1] == 'hold'


def test_more_than_one_stroke_is_rejected_before_recording(tmp_path):
    from brushbot.experiments.strokeplan_execution import compile_recorded_plan
    plan, calibration, setup, _ = inputs(tmp_path)
    plan.strokes.append(copy.deepcopy(plan.strokes[0]))
    with pytest.raises(ValueError, match='exactly one stroke'):
        compile_recorded_plan(plan, calibration, setup, label='two')


@pytest.mark.parametrize('failure', ['stale', 'disconnect', 'interrupt'])
def test_interrupted_run_is_finalized_with_reason(tmp_path, failure):
    from scripts.run_strokeplan_experiment import run_recorded
    engine, hub, arm, source, clock, _ = stack(tmp_path)
    original = source.read_frames
    fired = False

    def read_frames():
        nonlocal fired
        if engine.state == 'RUN' and not fired:
            fired = True
            if failure == 'disconnect':
                raise OSError('unplugged')
            if failure == 'interrupt':
                raise KeyboardInterrupt
            source.enabled = False
        return original()

    source.read_frames = read_frames
    result = run_recorded(engine, hub, clock=clock, sleep=lambda _: None)
    manifest = json.loads((Path(result['run_dir'])/'manifest.json').read_text())
    assert manifest['status'] in {'aborted', 'fault'}
    expected = {'stale': 'sensor_stale', 'disconnect': 'source_disconnected',
                'interrupt': 'operator_stop'}[failure]
    assert expected in manifest['reason']
    assert arm.calls[-1]['action'] == 'stop'
    if failure != 'disconnect':
        assert arm.pose[2] == pytest.approx(.13)


def test_failed_baseline_records_failure_without_moving(tmp_path):
    from scripts.run_strokeplan_experiment import run_recorded
    engine, hub, arm, source, clock, _ = stack(tmp_path)
    source.enabled = False
    result = run_recorded(engine, hub, clock=clock, sleep=lambda _: None)
    manifest = json.loads((Path(result['run_dir'])/'manifest.json').read_text())
    assert manifest['status'] == 'aborted'
    assert manifest['reason'] == 'baseline_failed'
    assert not any(c['action'] in {'move_pose', 'push_pose', 'start_servo'} for c in arm.calls)


def test_interrupt_during_startup_finalizes_allocated_run(tmp_path):
    from scripts.run_strokeplan_experiment import run_recorded
    engine, hub, arm, source, clock, _ = stack(tmp_path)
    original_event = engine._event

    def event(name, **fields):
        if name == 'baseline_started':
            raise KeyboardInterrupt
        original_event(name, **fields)

    engine._event = event
    result = run_recorded(engine, hub, clock=clock, sleep=lambda _: None)
    manifest = json.loads((Path(result['run_dir'])/'manifest.json').read_text())
    assert manifest['status'] in {'fault', 'aborted'}
    assert manifest['reason'] == 'operator_stop'
    assert not any(c['action'] in {'move_pose', 'push_pose', 'start_servo'} for c in arm.calls)


def test_baseline_and_stop_failure_still_close_manifest_and_writer(tmp_path):
    from scripts.run_strokeplan_experiment import run_recorded
    engine, hub, arm, source, clock, _ = stack(tmp_path)
    source.enabled = False

    def broken_stop():
        raise RuntimeError('stop transport failed')

    arm.stop = broken_stop
    result = run_recorded(engine, hub, clock=clock, sleep=lambda _: None)
    manifest = json.loads((Path(result['run_dir'])/'manifest.json').read_text())
    assert manifest['status'] == 'fault'
    assert 'baseline_failed' in manifest['reason']
    assert engine._recorder is None


def test_cli_preview_has_no_hardware_or_run_side_effects_and_blocks_candidates(tmp_path):
    _, _, _, artifacts = inputs(tmp_path)
    for name, payload in artifacts.items():
        (tmp_path/name).write_bytes(payload)
    root = Path(__file__).resolve().parents[1]
    cmd = [sys.executable, str(root/'scripts/run_strokeplan_experiment.py'),
           str(tmp_path/'strokeplan.npz'), '--feedforward', str(tmp_path/'feedforward.json'),
           '--settings', str(tmp_path/'settings.json'), '--run-root', str(tmp_path/'runs')]
    env = dict(os.environ, PYTHONPATH=str(root/'src'))
    preview = subprocess.run(cmd, env=env, capture_output=True, text=True)
    assert preview.returncode == 0, preview.stderr
    assert not (tmp_path/'runs').exists()
    denied = subprocess.run(cmd+['--execute'], env=env, capture_output=True, text=True)
    assert denied.returncode != 0
    assert 'approval' in denied.stderr
    assert 'EOFError' not in denied.stderr
    preview_p = subprocess.run(cmd+['--control-mode', 'p', '--dry-run'],
                               env=env, capture_output=True, text=True)
    assert preview_p.returncode == 0, preview_p.stderr
    denied_p = subprocess.run(cmd+['--control-mode', 'p', '--execute'],
                              env=env, capture_output=True, text=True)
    assert denied_p.returncode != 0
    assert 'approval' in denied_p.stderr
    assert not (tmp_path/'runs').exists()


def test_p_limits_wrapper_preview_identifies_separate_experiment(tmp_path):
    root = Path(__file__).resolve().parents[1]
    plan = (root/'runs/brush2/plans/ry15_rz0_suite_60_200_v1'
            /'04_smooth_levels_wide_transitions.npz')
    env = dict(os.environ, PYTHONPATH=str(root/'src'))
    result = subprocess.run(
        [sys.executable, str(root/'scripts/run_strokeplan_trial.py'),
         '--experiment', 'strokeplan_p', str(plan), '--dry-run'],
        env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert ('实验标签: strokeplan_p_limits_04_smooth_levels_wide_transitions'
            in result.stdout)
    assert '离线预检通过；未连接硬件，未创建实验 run。' in result.stdout


def test_explicit_p_mode_only_corrects_measure_and_records_final_depth(tmp_path):
    from scripts.run_strokeplan_experiment import run_recorded
    engine, hub, arm, source, clock, _ = stack(tmp_path, control_mode='p')
    result = run_recorded(engine, hub, clock=clock, sleep=lambda _: None)
    assert result['state'] == 'END_WAIT', result['last_error']
    folder = Path(result['run_dir'])
    rows = [json.loads(line) for line in (folder/'control.jsonl').read_text().splitlines()]
    measure = [row for row in rows if row['phase'] == 'measure_00']
    other = [row for row in rows if row['phase'] != 'measure_00']
    assert engine.feedback_calls == len(measure) == engine.feedback.calls
    assert all(row['a_ref_uT'] is None and row['depth_fb_m'] == 0. for row in other)
    assert all(row['z_cmd_m'] == pytest.approx(
        engine._compiled['pose_m_rad'][round(row['t_s']/.02), 2]) for row in other)
    assert any(row['depth_fb_m'] < 0 for row in measure)
    assert all(row['z_cmd_m'] == pytest.approx(
        setup_z - row['depth_ff_m'] - row['depth_fb_m'])
        for row in measure for setup_z in [engine._setup['contact_z_mm']/1000.])
    assert all('limit_reasons' in row and isinstance(row['limit_reasons'], list)
               for row in rows)
    assert json.loads((folder/'resolved.json').read_text())['control']['mode'] == 'p'


def test_p_profile_is_recorded_and_changes_the_feedback_command(tmp_path):
    from scripts.run_strokeplan_experiment import build_stack, run_recorded
    plan, calibration, setup, artifacts = inputs(tmp_path)
    clock = FakeClock()
    arm = FakeArm((-.2, .5, .13, *setup['vertical_rpy_rad']), clock=clock)
    arm.realtime_state_reads = False
    source = FakeMagneticSource(arm, clock, contact_z_mm=37.)
    profile = {'kp': .04, 'ki': 0., 'max_correction_mm': .12,
               'max_correction_speed_mm_s': 2.,
               'max_correction_accel_mm_s2': 40., 'taper_ticks': 25}
    engine, hub = build_stack(
        plan=plan, table=calibration, setup=setup, artifacts=artifacts,
        label='profile_trial', root=tmp_path/'runs', arm=arm, source=source,
        clock=clock, control_mode='p', feedback_profile=profile)
    result = run_recorded(engine, hub, clock=clock, sleep=lambda _: None)
    assert result['state'] == 'END_WAIT'
    folder = Path(result['run_dir'])
    resolved = json.loads((folder/'resolved.json').read_text())
    assert resolved['control']['kp'] == .04
    assert resolved['control']['max_correction_mm'] == .12
    rows = [json.loads(line) for line in (folder/'control.jsonl').read_text().splitlines()]
    measure = [row for row in rows if row['phase'] == 'measure_00']
    assert any(row['depth_fb_m'] < 0 for row in measure)
    assert max(abs(row['depth_fb_m']) for row in measure) <= .00012 + 1e-12


def test_p_mode_malformed_sensor_aborts_and_lifts_without_new_writing_command(tmp_path):
    from scripts.run_strokeplan_experiment import run_recorded
    engine, hub, arm, source, clock, _ = stack(tmp_path, control_mode='p')
    original = source.read_frames
    fired = False

    def invalid_once():
        nonlocal fired
        rows = original()
        if engine.state == 'RUN' and not fired:
            fired = True
            rows[0]['B_uT'][0] = float('nan')
        return rows

    source.read_frames = invalid_once
    result = run_recorded(engine, hub, clock=clock, sleep=lambda _: None)
    manifest = json.loads((Path(result['run_dir'])/'manifest.json').read_text())
    assert manifest['status'] == 'aborted'
    assert manifest['reason'] == 'sensor_invalid'
    assert arm.pose[2] == pytest.approx(.13)
    assert arm.calls[-1]['action'] == 'stop'


def test_p_mode_sensor_disconnect_uses_abort_lift(tmp_path):
    from scripts.run_strokeplan_experiment import run_recorded
    engine, hub, arm, source, clock, _ = stack(tmp_path, control_mode='p')
    original = source.read_frames

    def disconnect():
        if engine.state == 'RUN':
            raise OSError('sensor unplugged')
        return original()

    source.read_frames = disconnect
    result = run_recorded(engine, hub, clock=clock, sleep=lambda _: None)
    manifest = json.loads((Path(result['run_dir'])/'manifest.json').read_text())
    assert manifest['status'] == 'aborted'
    assert manifest['reason'] == 'source_disconnected'
    assert arm.pose[2] == pytest.approx(.13)


def test_p_mode_stale_sensor_aborts_before_next_servo_command(tmp_path):
    from scripts.run_strokeplan_experiment import run_recorded
    engine, hub, arm, source, clock, _ = stack(tmp_path, control_mode='p')
    original = source.read_frames
    disabled = False

    def stop_samples():
        nonlocal disabled
        if engine.state == 'RUN' and not disabled:
            source.enabled = False
            disabled = True
        return original()

    source.read_frames = stop_samples
    result = run_recorded(engine, hub, clock=clock, sleep=lambda _: None)
    manifest = json.loads((Path(result['run_dir'])/'manifest.json').read_text())
    assert manifest['status'] == 'aborted'
    assert manifest['reason'] == 'sensor_stale'
    assert arm.pose[2] == pytest.approx(.13)


def test_p_mode_workspace_violation_aborts_before_unsafe_push(tmp_path):
    from scripts.run_strokeplan_experiment import run_recorded
    engine, hub, arm, source, clock, _ = stack(tmp_path, control_mode='p')
    measure = int(np.flatnonzero(engine._compiled['phase'] == 'measure_00')[0])
    engine._compiled['pose_m_rad'][measure, 2] = .016  # below fixture Z minimum 17 mm
    result = run_recorded(engine, hub, clock=clock, sleep=lambda _: None)
    manifest = json.loads((Path(result['run_dir'])/'manifest.json').read_text())
    assert manifest['status'] == 'aborted'
    assert manifest['reason'] == 'workspace_limit'
    assert not any(c['action'] == 'push_pose' and c['pose'][2] < .017
                   for c in arm.calls)
    assert arm.pose[2] == pytest.approx(.13)


def test_shadow_replay_uses_recorded_ema_and_checks_every_timeline_tick(tmp_path):
    from scripts.run_strokeplan_experiment import run_recorded
    from scripts.shadow_replay_strokeplan_feedback import replay_run
    engine, hub, arm, source, clock, _ = stack(tmp_path)
    result = run_recorded(engine, hub, clock=clock, sleep=lambda _: None)
    summary, rows = replay_run(Path(result['run_dir']))
    assert summary['status'] == 'boundary_valid'
    assert summary['control_ticks'] == len(engine._compiled['t_s'])
    assert summary['feedback_ticks'] == sum(r['phase'] == 'measure_00' for r in rows)
    assert summary['nonwriting_command_changes'] == 0
    assert summary['max_step_mm'] <= engine._setup['max_step_mm']
    assert summary['max_z_speed_mm_s'] <= engine._setup['max_z_speed_mm_s']
    assert summary['max_accel_mm_s2'] <= engine._setup['max_accel_mm_s2']
    assert summary['max_depth_mm'] <= engine._setup['max_depth_mm']
    assert any(r['depth_fb_m'] != 0 for r in rows if r['phase'] == 'measure_00')
    assert all(r['z_cmd_m'] == pytest.approx(r['z_ff_m'] - r['depth_fb_m'])
               for r in rows)


def test_shadow_replay_rejects_feedback_source_run(tmp_path):
    from scripts.run_strokeplan_experiment import run_recorded
    from scripts.shadow_replay_strokeplan_feedback import replay_run
    engine, hub, arm, source, clock, _ = stack(tmp_path, control_mode='p')
    result = run_recorded(engine, hub, clock=clock, sleep=lambda _: None)
    assert result['state'] == 'END_WAIT'
    with pytest.raises(ValueError, match='feedforward source'):
        replay_run(Path(result['run_dir']))
