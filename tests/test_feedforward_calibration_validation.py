"""Signed normalization, independent commands, and recorded sample provenance."""
import copy
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]


def implementation():
    return importlib.import_module('brushbot.experiments.feedforward_calibration_validation')


def analytic():
    m = implementation()
    curves = {k: {'depth_nodes_mm': [5, 10, 13], 'response_nodes_uT': a}
              for k, a in {'right': [100, 200, 260], 'up': [200, 400, 520],
                           'left': [50, 100, 130], 'down': [150, 300, 390]}.items()}
    model = {'direction_curves': curves, 'scope': {'speed_mm_s': 10, 'writing_tilt_deg': 15,
              'travel_mm': 150, 'window_mm': [30, 120], 'command_z_mm': [27, 35]},
             'signal': 'control.jsonl:a_control_uT = norm of EMA baseline-subtracted Bxy, alpha 0.3'}
    ref = {'reference_id': 'analytic', 'depth_nodes_mm': [5, 10, 13],
           'calibrated_response_nodes_uT': [125, 250, 325]}
    return m.DirectionalCalibration(model, ref)


def test_negative_components_keep_sign_and_direction_does_not_follow_sign():
    cal = analytic()
    r = cal.normalize(-120, 160, 'right', 'straight_hold')
    assert r['calibration_status'] == 'ok'
    assert r['depth_est_mm'] == pytest.approx(10)
    assert [r['bx_cal_uT'], r['by_cal_uT'], r['g_cal_uT']] == pytest.approx([-150, 200, 250])
    left = cal.normalize(100, 0, 'left', 'straight_hold')
    assert left['depth_est_mm'] == pytest.approx(10)
    assert left['g_cal_uT'] == pytest.approx(250)


@pytest.mark.parametrize('bx,by,status', [(0, 0, 'zero_amplitude'), (-12, 10, 'below_range'),
                                        (261, 0, 'above_range')])
def test_weak_or_out_of_range_signal_never_becomes_a_depth(bx, by, status):
    result = analytic().normalize(bx, by, 'right', 'straight_hold')
    assert result['calibration_status'] == status
    assert result['g_cal_uT'] is None and result['depth_est_mm'] is None
    assert result['bx_cal_uT'] is None


def test_small_x_does_not_discard_strong_y_or_rezero_static_contact():
    result = analytic().normalize(0, 200, 'right', 'straight_hold')
    assert result['x_noise_scale']
    assert result['g_cal_uT'] == pytest.approx(250)
    assert result['depth_est_mm'] == pytest.approx(10)


@pytest.mark.parametrize('phase,status', [('post_lift_hold', 'no_contact'),
                                         ('rotate_contact', 'transient')])
def test_phase_validity_is_distinct_from_amplitude(phase, status):
    result = analytic().normalize(-120, 160, 'right', phase)
    assert result['calibration_status'] == status
    assert result['g_cal_uT'] is None and result['depth_est_mm'] is None
    assert result['g_control_uT'] == (0 if status == 'no_contact' else None)


def test_unknown_direction_and_nonfinite_components_are_invalid():
    cal = analytic()
    assert cal.normalize(200, 0, 'diagonal', 'straight_hold')['calibration_status'] == 'unknown_direction'
    assert cal.normalize(float('nan'), 0, 'right', 'straight_hold')['calibration_status'] == 'non_finite'


def test_nonmonotone_curves_and_mismatched_reference_are_rejected():
    cal = analytic()
    model = copy.deepcopy(cal.model)
    model['direction_curves']['left']['response_nodes_uT'] = [50, 40, 130]
    with pytest.raises(ValueError):
        type(cal)(model, cal.reference)
    reference = copy.deepcopy(cal.reference)
    reference['calibrated_response_nodes_uT'] = [125, 251, 325]
    with pytest.raises(ValueError, match='reference'):
        type(cal)(cal.model, reference)


def frozen():
    m = implementation()
    p = ROOT/'runs/brush2/plans/feedforward_calibration_handoff_v2'
    return m.load_calibration(p/'directional_calibration.json', p/'common_reference.json')


def test_source_hash_mismatch_is_rejected(tmp_path):
    m = implementation()
    cal = frozen()
    model = tmp_path/'model.json'
    model.write_text(json.dumps(cal.model))
    ref = tmp_path/'reference.json'
    ref.write_text(json.dumps(cal.reference))
    with pytest.raises(ValueError, match='hash'):
        m.load_calibration(model, ref)


def test_eight_trials_lookup_common_table_and_return_to_shared_wait():
    m = implementation()
    from scripts.run_feedforward_calibration_validation import prepare_trials, SETTINGS
    trials = prepare_trials(json.loads(SETTINGS.read_text()), frozen())
    assert len(trials) == 8
    assert {(t['direction'], t['command_z_mm'], t['repeat']) for t in trials} == {
        (d, z, rep) for d in ['right', 'up'] for z in [32, 28] for rep in [1, 2]}
    for trial in trials:
        compiled = m.compile_trial(trial, trial['setup'])
        line = compiled['pose_m_rad'][compiled['phase'] == 'straight_hold']
        assert line[:, 2] == pytest.approx(np.full(len(line), trial['command_z_mm']/1000))
        end = [0, .5, trial['command_z_mm']/1000] if trial['direction'] == 'right' else [-.15, .6, trial['command_z_mm']/1000]
        assert line[-1, :3] == pytest.approx(end)
        assert compiled['pose_m_rad'][-1] == pytest.approx([-.15, .5, .07, 0, np.deg2rad(15), 0])
        assert not compiled['spec_snapshot']['control']['enabled']


def test_default_cli_is_dry_run_and_writes_only_explicit_preview(tmp_path):
    implementation()
    script = ROOT/'scripts/run_feedforward_calibration_validation.py'
    result = subprocess.run([sys.executable, str(script), '--run-root', str(tmp_path/'runs'),
                             '--preview-dir', str(tmp_path/'preview')],
                            env=dict(os.environ, PYTHONPATH=str(ROOT/'src')),
                            text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    plan = json.loads((tmp_path/'preview/planned_trials.json').read_text())
    assert len(plan['trials']) == 8
    assert not (tmp_path/'runs').exists()


def test_summary_keeps_invalid_coverage_and_equal_stroke_records():
    m = implementation()
    rows = [dict(phase='straight_hold', distance_mm=40., a_control_uT=200.,
                 g_cal_uT=250., depth_est_mm=10., calibration_status='ok'),
            dict(phase='straight_hold', distance_mm=45., a_control_uT=300.,
                 g_cal_uT=None, depth_est_mm=None, calibration_status='above_range')]
    metric = m.summarize_rows(rows, {'common_target_uT': 240., 'command_z_mm': 30.})
    assert metric['primary']['valid_frames'] == 1
    assert metric['primary']['total_frames'] == 2
    assert metric['primary']['coverage'] == .5
    assert metric['primary']['calibrated_rmse_uT_valid_only'] == pytest.approx(10)
    assert metric['primary']['z_rmse_mm_valid_only'] == pytest.approx(0)


def build_engine(tmp_path, trial_index=0):
    m = implementation()
    from scripts.run_feedforward_calibration_validation import build_stack, prepare_trials, SETTINGS
    from scripts.run_strokeplan_experiment import run_recorded
    from brushbot.experiments.fake import FakeArm, FakeClock, FakeMagneticSource
    settings = json.loads(SETTINGS.read_text())
    settings.update(baseline_window_s=.04, baseline_timeout_s=.2, baseline_min_samples=3,
                    baseline_max_std_uT=[.1]*3, baseline_max_drift_uT_s=.1)
    cal = frozen()
    trial = prepare_trials(settings, cal)[trial_index]
    clock = FakeClock()
    arm = FakeArm((trial['setup']['origin_x_mm']/1000,
                   trial['setup']['origin_y_mm']/1000, .07, 0, np.deg2rad(15), 0), clock=clock)
    arm.realtime_state_reads = False
    source = FakeMagneticSource(arm, clock)
    read = source.read_frames
    def frames():
        data = read()
        for frame in data:
            frame['B_uT'] = [-120., 100., 0.] if arm.pose[2] < .04 else [0., 0., 0.]
        return data
    source.read_frames = frames
    engine, hub = build_stack(profile=trial['profile'], setup=trial['setup'], root=tmp_path,
                              arm=arm, source=source, clock=clock, calibration=cal, trial=trial,
                              auto_position=False)
    return engine, hub, arm, source, clock, cal


@pytest.mark.parametrize('trial_index', range(4))
def test_validation_keeps_every_point_after_repeated_delays_above_z20(tmp_path, trial_index):
    from scripts.run_strokeplan_experiment import run_recorded
    engine, hub, arm, source, clock, _ = build_engine(tmp_path, trial_index)
    original = arm.push_pose
    starts = []
    line_ticks = 0

    def delayed_push(pose):
        nonlocal line_ticks
        starts.append(clock.now_ns())
        original(pose)
        if engine._compiled['phase'][engine._last_plan_index+1] == 'straight_hold':
            line_ticks += 1
            if line_ticks == 20:
                clock.advance(.16)
            elif line_ticks == 60:
                clock.advance(1.2)

    arm.push_pose = delayed_push
    result = run_recorded(engine, hub, clock=clock)
    assert result['state'] == 'END_WAIT', result['last_error']
    assert result['deadline_recovery_count'] == 2
    assert result['last_deadline_recovery']['command_duration_s'] == pytest.approx(1.2)
    rows = [json.loads(line) for line in (Path(result['run_dir'])/'control.jsonl').read_text().splitlines()]
    assert len(rows) == len(engine._compiled['t_s'])
    assert [r['t_s'] for r in rows] == pytest.approx(engine._compiled['t_s'])
    assert np.array([[r['x_cmd_m'], r['y_cmd_m'], r['z_cmd_m']] for r in rows]) == pytest.approx(
        engine._compiled['pose_m_rad'][:, :3])
    assert np.min(np.diff(starts)) >= 20_000_000
    events = [json.loads(line) for line in (Path(result['run_dir'])/'events.jsonl').read_text().splitlines()]
    recovered = [e for e in events if e['event'] == 'deadline_recovered']
    assert len(recovered) == 2
    assert all(e['current_z_mm'] > 20 and e['next_z_mm'] > 20 for e in recovered)


def test_real_engine_logs_aligned_vectors_model_inputs_and_no_feedback(tmp_path):
    from scripts.run_strokeplan_experiment import run_recorded
    engine, hub, arm, source, clock, cal = build_engine(tmp_path)
    result = run_recorded(engine, hub, clock=clock)
    assert result['state'] == 'END_WAIT', result
    folder = Path(result['run_dir'])
    rows = [json.loads(line) for line in (folder/'control.jsonl').read_text().splitlines()]
    held = [r for r in rows if r['phase'] == 'straight_hold']
    assert held and all(r['depth_fb_m'] == 0 for r in held)
    for row in held:
        assert np.hypot(row['bx_filtered_uT'], row['by_filtered_uT']) == pytest.approx(row['a_control_uT'])
        assert row['common_reference_id'] == cal.reference['reference_id']
        assert row['calibration_sample_seq'] == row['sample_seq']
    good = [r for r in held if r['calibration_status'] == 'ok']
    assert good and all(r['bx_cal_uT'] < 0 for r in good)
    manifest = json.loads((folder/'manifest.json').read_text())
    assert 'directional_calibration.json' in manifest['sha256']
    assert 'common_reference.json' in manifest['sha256']
    assert (folder/'validation_metrics.json').exists()
    assert arm.pose == pytest.approx((-.15, .5, .07, 0, np.deg2rad(15), 0))


def test_contact_disconnect_still_uses_recorded_abort_lift(tmp_path):
    from scripts.run_strokeplan_experiment import run_recorded
    engine, hub, arm, source, clock, _ = build_engine(tmp_path)
    read = source.read_frames
    stopped_pose = None
    def disconnect():
        nonlocal stopped_pose
        if stopped_pose is None and engine._telemetry and engine._telemetry['phase'] == 'straight_hold':
            stopped_pose = arm.pose
            raise OSError('disconnected')
        return read()
    source.read_frames = disconnect
    result = run_recorded(engine, hub, clock=clock)
    assert result['state'] == 'ABORTED', result
    assert arm.pose[2] == pytest.approx(.07)
    assert arm.pose[3:] == pytest.approx(stopped_pose[3:])
    manifest = json.loads((Path(result['run_dir'])/'manifest.json').read_text())
    assert manifest['status'] == 'aborted'


def test_filter_change_is_rejected_before_path_execution():
    from scripts.run_feedforward_calibration_validation import prepare_trials, SETTINGS
    settings = json.loads(SETTINGS.read_text())
    settings['filter']['alpha'] = .1
    with pytest.raises(ValueError, match='EMA'):
        prepare_trials(settings, frozen())


def test_execute_selected_suffix_records_real_engine_and_batch(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from scripts import run_feedforward_calibration_validation as runner
    from scripts.run_strokeplan_experiment import run_recorded
    from brushbot.experiments.fake import FakeArm, FakeClock, FakeMagneticSource
    settings = json.loads(runner.SETTINGS.read_text())
    settings.update(baseline_window_s=.04, baseline_timeout_s=.2, baseline_min_samples=3,
                    baseline_max_std_uT=[.1]*3, baseline_max_drift_uT_s=.1)
    setting_path = tmp_path/'settings.json'
    setting_path.write_text(json.dumps(settings))
    @contextmanager
    def hardware(setup, *, record_tcp):
        def execute(profile, current, source_bytes, root, *, stack_factory, display_name):
            clock = FakeClock()
            pose = (current['origin_x_mm']/1000, current['origin_y_mm']/1000, .07,
                    *current['vertical_rpy_rad'])
            arm = FakeArm(pose, clock=clock)
            arm.realtime_state_reads = False
            source = FakeMagneticSource(arm, clock)
            engine, hub = stack_factory(profile=profile, setup=current, root=root, arm=arm,
                                        source=source, clock=clock, settings_source_bytes=source_bytes,
                                        auto_position=False)
            result = run_recorded(engine, hub, clock=clock)
            return 0 if result['state'] == 'END_WAIT' else 2
        yield execute
    monkeypatch.setattr(runner, 'hardware_session', hardware)
    monkeypatch.setattr('builtins.input', lambda _: '')
    assert runner.main(['--execute', '--settings', str(setting_path), '--direction', 'up',
                        '--start-trial', '4', '--run-root', str(tmp_path/'runs')]) == 0
    batch_path, = (tmp_path/'runs').glob('batch_*.json')
    batch = json.loads(batch_path.read_text())
    assert batch['recorded_trial_count'] == 1
    assert batch['selected_start_trial'] == 4
    assert batch['completed'][0]['trial_id'] == 'Z32_up_R2'
    assert batch['completed'][0]['state'] == 'END_WAIT'
    assert batch['completed'][0]['deadline_recovery_count'] == 0
    assert batch['completed'][0]['deadline_diagnostic'] is None
    folder = Path(batch['completed'][0]['run_dir'])
    assert json.loads((folder/'manifest.json').read_text())['status'] == 'completed'
