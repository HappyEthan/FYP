"""Independent contact trials must couple rotation and depth without a later load."""
import json
from pathlib import Path
import time
from contextlib import contextmanager

import numpy as np
import pytest

from brushbot.experiments.fake import FakeArm, FakeClock, FakeMagneticSource

ROOT = Path(__file__).resolve().parents[1]


def settings():
    s = json.loads((ROOT/'runs/brush2/plans/12_中字朝负Y_正X为右/settings.json').read_text())
    s.update(origin_x_mm=-150., origin_y_mm=450., wait_z_mm=70.,
             baseline_window_s=.04, baseline_timeout_s=.2, baseline_min_samples=3,
             baseline_max_std_uT=[.1]*3, baseline_max_drift_uT_s=.1)
    s['workspace_min_mm'][1], s['workspace_max_mm'][1] = 300., 700.
    return s


@pytest.mark.parametrize('direction,unit,rpy', [
    ('right', [1, 0], [0, 15, 0]), ('up', [0, 1], [-15, 0, 0]),
    ('left', [-1, 0], [0, -15, 0]), ('down', [0, -1], [15, 0, 0]),
])
@pytest.mark.parametrize('start,duration', [(32., 4.), (34., 6.), (36., 8.)])
def test_coupled_rotation_reaches_workpoint_before_sliding(direction, unit, rpy, start, duration):
    from brushbot.experiments.contact_entry_test import compile_contact_test
    from scripts.run_contact_entry_test import PROFILE
    p = dict(PROFILE, direction=direction, rotate_s=duration)
    c = compile_contact_test(p, settings(), dict(rotate_start_z_mm=start, preload_speed_mm_s=2.))
    poses, phases = c['pose_m_rad'], c['phase']
    indices = np.flatnonzero(phases == 'rotate_load')
    rot = poses[indices]
    before = poses[indices[0]-1]
    origin = np.array([-.15, .45])
    assert before[:2] == pytest.approx(origin+.005*np.asarray(unit))
    assert before[2] == pytest.approx(start/1000)
    assert rot[-1, :3] == pytest.approx([-.15, .45, .028])
    assert np.rad2deg(rot[-1, 3:]) == pytest.approx(rpy)
    assert np.all(np.diff(np.r_[before[2], rot[:, 2]]) < 0)
    assert len(rot)*.02 == pytest.approx(duration)
    # Halfway through a symmetric ease, both height and tilt are halfway.
    middle = rot[len(rot)//2-1]
    assert middle[2]*1000 == pytest.approx((start+28)/2)
    assert np.linalg.norm(np.rad2deg(middle[3:])) == pytest.approx(22.5)
    assert phases[indices[-1]+1] == 'straight_hold'
    assert 'load_start' not in phases
    assert 'rotate_contact' not in phases
    assert poses[phases == 'straight_hold', 2] == pytest.approx(.028)
    if start < 36:
        pre = poses[phases == 'entry_preload']
        assert pre[-1, 2] == pytest.approx(start/1000)
        assert np.linalg.norm(np.rad2deg(pre[-1, 3:])) == pytest.approx(30.)
        assert np.max(abs(np.diff(pre[:, 2])/.02))*1000 <= 2.+1e-6
    assert np.diff(c['t_s']) == pytest.approx(.02)
    assert poses[-1] == pytest.approx(poses[0])
    for segment in c['segments']:
        assert np.all(phases[segment['start_tick']:segment['end_tick']] == segment['id'])
    baseline = c['automatic_rebaseline_after_indices'][0]
    assert phases[baseline] == 'baseline_settle'
    assert not c['spec_snapshot']['control']['enabled']
    assert np.isnan(c['g_ref_uT']).all()
    # Check full trajectory seams independently, including the return.
    v = np.diff(np.vstack([poses[0], poses, poses[-1]]), axis=0)/.02
    a = np.diff(v, axis=0)/.02
    assert np.max(abs(v[:, 2]))*1000 <= settings()['max_z_speed_mm_s']+1e-6
    assert np.max(np.linalg.norm(a[:, :3], axis=1))*1000 <= settings()['max_accel_mm_s2']+1e-6
    assert np.max(np.linalg.norm(np.rad2deg(v[:, 3:]), axis=1)) <= p['angular_speed_deg_s']+1e-6


@pytest.mark.parametrize('options,profile', [
    ({'rotate_start_z_mm':28.}, {}), ({'rotate_start_z_mm':27.}, {}),
    ({'rotate_start_z_mm':37.}, {}), ({'rotate_start_z_mm':float('nan')}, {}),
    ({'rotate_start_z_mm':True}, {}), ({'preload_speed_mm_s':0.}, {}),
    ({}, {'rotate_s':.03}), ({}, {'rotate_s':.02}),
    ({}, {'end_z_mm':27.}),
])
def test_rejects_invalid_or_infeasible_contact_path(options, profile):
    from brushbot.experiments.contact_entry_test import compile_contact_test
    from scripts.run_contact_entry_test import PROFILE
    with pytest.raises(ValueError):
        compile_contact_test(dict(PROFILE, **profile), settings(),
                             {'rotate_start_z_mm':32., 'preload_speed_mm_s':2., **options})


def test_height_matrix_keeps_conditions_and_repeats_in_reverse_order():
    from scripts.run_contact_entry_test import prepare_trials
    trials = prepare_trials(settings(), suite='heights', repeats=2)
    assert [(t['entry']['rotate_start_z_mm'], t['profile']['rotate_s'], t['repeat']) for t in trials] == [
        (32., 6., 1), (34., 6., 1), (36., 6., 1),
        (36., 6., 2), (34., 6., 2), (32., 6., 2)]
    assert len({t['trial_id'] for t in trials}) == 6
    time_trials = prepare_trials(settings(), suite='times', rotate_start_z_mm=34., repeats=1)
    assert [(t['entry']['rotate_start_z_mm'], t['profile']['rotate_s']) for t in time_trials] == [
        (34., 4.), (34., 6.), (34., 8.)]


def test_dry_run_exports_reviewable_plan_without_runs_or_devices(tmp_path):
    from scripts.run_contact_entry_test import main
    root, preview = tmp_path/'runs', tmp_path/'preview'
    assert main(['--suite','single','--run-root',str(root),'--preview-dir',str(preview)]) == 0
    assert not root.exists()
    planned = json.loads((preview/'planned_trials.json').read_text())
    assert planned['hardware_connected'] is False
    with np.load(next(preview.glob('*_timeline.npz'))) as a:
        assert 'rotate_load' in a['phase']
        assert 'load_start' not in a['phase']
    assert (preview/'trajectory_preview.png').is_file()


def test_completed_fake_run_records_vectors_and_metrics(tmp_path):
    from scripts.run_contact_entry_test import build_stack, prepare_trials
    trial = prepare_trials(settings(), suite='single', repeats=1)[0]
    clock = FakeClock()
    arm = FakeArm((-.15, .45, .07, *trial['setup']['vertical_rpy_rad']), clock=clock)
    arm.realtime_state_reads = False
    engine, hub = build_stack(profile=trial['profile'], setup=trial['setup'], root=tmp_path,
        arm=arm, source=FakeMagneticSource(arm, clock), clock=clock, trial=trial, auto_position=False)
    engine.start(require_wait_position=True)
    for _ in range(10000):
        hub.poll_once()
        engine.step()
        if engine.state in {'END_WAIT','FAULT','ABORTED'}:
            break
        clock.advance(.02)
        time.sleep(0)  # Yield to the real asynchronous recorder while fake time advances.
    assert engine.state == 'END_WAIT', engine.snapshot()
    folder = Path(engine.run_dir)
    rows = [json.loads(x) for x in (folder/'control.jsonl').read_text().splitlines()]
    assert all(abs(np.hypot(r['bx_filtered_uT'],r['by_filtered_uT'])-r['a_control_uT']) < 1e-8 for r in rows)
    assert all(r['depth_fb_m'] == 0 for r in rows)
    metrics = json.loads((folder/'contact_metrics.json').read_text())
    assert metrics['run_status'] == 'completed'
    assert metrics['primary']['frames'] > 0
    assert metrics['phases']['rotate_load']['frames'] > 0
    assert (folder/'contact_test.json').is_file()
    assert (folder/'segments.json').is_file()


def test_servo_restart_latency_is_excluded_from_contact_timeline(tmp_path):
    from scripts.run_contact_entry_test import build_stack, prepare_trials
    from scripts.run_strokeplan_experiment import run_recorded
    trial = prepare_trials(settings())[0]
    clock = FakeClock()

    class SlowRestartArm(FakeArm):
        def start_servo(self):
            super().start_servo()
            if sum(c['action'] == 'start_servo' for c in self.calls) == 2:
                clock.advance(.16)

    arm = SlowRestartArm((-.15, .45, .07, *trial['setup']['vertical_rpy_rad']), clock=clock)
    arm.realtime_state_reads = False
    engine, hub = build_stack(profile=trial['profile'], setup=trial['setup'], root=tmp_path,
        arm=arm, source=FakeMagneticSource(arm, clock), clock=clock, trial=trial, auto_position=False)
    result = run_recorded(engine, hub, clock=clock, sleep=time.sleep)
    assert result['state'] == 'END_WAIT', result['last_error']
    rows = [json.loads(s) for s in (Path(result['run_dir'])/'control.jsonl').read_text().splitlines()]
    assert len(rows) == 2107
    assert all(r['lateness_s'] <= .1 for r in rows)


@pytest.mark.parametrize('preparation_s', [0., .002])
def test_recorded_contact_driver_does_not_catch_up_in_a_command_burst(tmp_path, preparation_s):
    from scripts.run_contact_entry_test import build_stack, prepare_trials
    from scripts.run_strokeplan_experiment import run_recorded
    trial = prepare_trials(settings())[0]
    virtual = FakeClock()

    class Clock:
        def now_ns(self):
            return virtual.now_ns()

    clock = Clock()  # Exercise the production wall-clock pacing branch.
    starts = []

    class SlowPushArm(FakeArm):
        def push_pose(self, pose):
            starts.append(clock.now_ns())
            super().push_pose(pose)
            if len(starts) == 20:
                virtual.advance(.06)

    arm = SlowPushArm((-.15, .45, .07, *trial['setup']['vertical_rpy_rad']), clock=clock)
    arm.realtime_state_reads = False

    class PreparationSource(FakeMagneticSource):
        def read_frames(self):
            virtual.advance(preparation_s)
            return super().read_frames()

    engine, hub = build_stack(profile=trial['profile'], setup=trial['setup'], root=tmp_path,
        arm=arm, source=PreparationSource(arm, clock), clock=clock, trial=trial, auto_position=False)

    def sleep(seconds):
        virtual.advance(seconds)
        time.sleep(0)

    result = run_recorded(engine, hub, clock=clock, sleep=sleep)
    assert result['state'] == 'END_WAIT', result['last_error']
    assert np.min(np.diff(starts)) >= 20_000_000
    rows = [json.loads(s) for s in (Path(result['run_dir'])/'control.jsonl').read_text().splitlines()]
    assert len(rows) == 2107
    assert np.diff([r['t_s'] for r in rows]) == pytest.approx(.02)


def test_contact_continues_after_160_ms_stall_above_z20(tmp_path):
    from scripts.run_contact_entry_test import build_stack, prepare_trials
    from scripts.run_strokeplan_experiment import run_recorded
    trial = prepare_trials(settings())[0]
    virtual = FakeClock()

    class Clock:
        def now_ns(self):
            return virtual.now_ns()

    clock = Clock()
    starts = []

    class SlowContactArm(FakeArm):
        stalled = False
        def push_pose(self, pose):
            starts.append(clock.now_ns())
            super().push_pose(pose)
            if not self.stalled and pose[2] == .028 and pose[1] > .451:
                self.stalled = True
                virtual.advance(.16)

    arm = SlowContactArm((-.15, .45, .07, *trial['setup']['vertical_rpy_rad']), clock=clock)
    arm.realtime_state_reads = False
    engine, hub = build_stack(profile=trial['profile'], setup=trial['setup'], root=tmp_path,
        arm=arm, source=FakeMagneticSource(arm, clock), clock=clock, trial=trial, auto_position=False)

    def sleep(seconds):
        virtual.advance(seconds)
        time.sleep(0)

    result = run_recorded(engine, hub, clock=clock, sleep=sleep)
    assert result['state'] == 'END_WAIT', result['last_error']
    assert result['deadline_recovery_count'] == 1
    assert result['last_deadline_recovery']['min_z_mm'] == 20.
    assert result['last_deadline_recovery']['current_z_mm'] == 28.
    assert result['last_deadline_recovery']['command_duration_s'] == pytest.approx(.16)
    rows = [json.loads(s) for s in (Path(result['run_dir'])/'control.jsonl').read_text().splitlines()]
    assert len(rows) == 2107
    assert np.diff([r['t_s'] for r in rows]) == pytest.approx(.02)
    assert np.min(np.diff(starts)) >= 20_000_000
    events = [json.loads(s) for s in (Path(result['run_dir'])/'events.jsonl').read_text().splitlines()]
    assert any(e['event'] == 'deadline_recovered' for e in events)


def test_unfinished_run_is_not_a_completed_repetition():
    from brushbot.experiments.contact_entry_test import summarize_rows, summarize_repeats
    trial = dict(trial_id='x',direction='up',command_z_mm=28.,rotate_start_z_mm=32.,rotate_s=6.,travel_mm=150.)
    metrics = summarize_rows([], trial, status='aborted')
    assert metrics['primary']['raw_median_uT'] is None
    assert summarize_repeats([dict(trial=trial,metrics=metrics)]) == []


def test_repeat_summary_uses_completed_runs_with_identical_parameters_only():
    from brushbot.experiments.contact_entry_test import summarize_repeats
    trial = dict(condition_sha256='a',direction='up',command_z_mm=28.,rotate_start_z_mm=32.,rotate_s=6.)
    records = [dict(trial=trial,metrics=dict(run_status=status,primary=dict(frames=100,raw_median_uT=value)))
               for status,value in [('completed',100.),('completed',120.),('aborted',500.)]]
    records.append(dict(trial=dict(trial,condition_sha256='b',rotate_s=8.),
                        metrics=dict(run_status='completed',primary=dict(frames=100,raw_median_uT=250.))))
    result = summarize_repeats(records)
    assert result[0]['completed_repeats'] == 2
    assert result[0]['between_run_range_over_median'] == pytest.approx(20/110)
    assert result[1]['completed_repeats'] == 1
    assert result[1]['between_run_range_over_median'] is None


def test_invalid_execution_settings_fail_before_prompt_or_run_creation(tmp_path,monkeypatch):
    from scripts.run_contact_entry_test import main
    def unexpected_prompt(*args):
        raise AssertionError('invalid motion must not reach confirmation')
    monkeypatch.setattr('builtins.input',unexpected_prompt)
    with pytest.raises(SystemExit) as exc:
        main(['--execute','--rotate-start-z-mm','26','--run-root',str(tmp_path/'runs')])
    assert exc.value.code == 2
    assert not (tmp_path/'runs').exists()


@pytest.mark.parametrize('raise_after_run',[False,True])
def test_operator_abort_stops_batch_and_preserves_failed_trial(tmp_path,monkeypatch,raise_after_run):
    from scripts import run_contact_entry_test as runner
    @contextmanager
    def session(*args,**kwargs):
        yield object()
    def execute(profile,setup,source_bytes,root,**kwargs):
        clock = FakeClock()
        arm = FakeArm((setup['origin_x_mm']/1000,setup['origin_y_mm']/1000,.07,*setup['vertical_rpy_rad']),clock=clock)
        arm.realtime_state_reads = False
        engine,hub = kwargs['stack_factory'](profile=profile,setup=setup,root=root,arm=arm,
            source=FakeMagneticSource(arm,clock),clock=clock,settings_source_bytes=source_bytes,auto_position=False)
        engine.start(require_wait_position=True)
        stopped = False
        for _ in range(10000):
            hub.poll_once(); engine.step()
            if engine.state == 'RUN' and engine.phase == 'rotate_load' and not stopped:
                engine.request_stop('operator_stop')
                stopped = True
            if engine.state in {'END_WAIT','FAULT','ABORTED'}:
                break
            clock.advance(.02); time.sleep(0)
        assert engine.state == 'ABORTED',engine.snapshot()
        if raise_after_run:
            raise RuntimeError('post-run transport failed')
        return 2
    monkeypatch.setattr(runner,'hardware_session',session)
    monkeypatch.setattr(runner,'execute_hardware',execute)
    monkeypatch.setattr('builtins.input',lambda *args:'')
    assert runner.main(['--execute','--suite','heights','--run-root',str(tmp_path)]) == 2
    path = next(tmp_path.glob('**/batch_*.json'))
    batch = json.loads(path.read_text())
    assert batch['status'] == 'failed'
    assert len(batch['records']) == 1
    assert batch['records'][0]['metrics']['run_status'] == 'aborted'
    assert batch['comparison'] == []
    assert len(list(tmp_path.glob('**/manifest.json'))) == 1


def test_deadline_failure_stops_batch_with_actionable_diagnostic(tmp_path, monkeypatch, capsys):
    from scripts import run_contact_entry_test as runner
    from scripts.run_strokeplan_experiment import run_recorded

    @contextmanager
    def session(*args, **kwargs):
        yield object()

    def execute(profile, setup, source_bytes, root, **kwargs):
        clock = FakeClock()

        class BlockedArm(FakeArm):
            stalled = False
            def push_pose(self, pose):
                super().push_pose(pose)
                if not self.stalled and pose[2] == .020 and pose[1] > .4501:
                    self.stalled = True
                    clock.advance(.16)

        arm = BlockedArm((-.15, .45, .07, *setup['vertical_rpy_rad']), clock=clock)
        arm.realtime_state_reads = False
        engine, hub = kwargs['stack_factory'](profile=profile, setup=setup, root=root,
            arm=arm, source=FakeMagneticSource(arm, clock), clock=clock,
            settings_source_bytes=source_bytes, auto_position=False)
        result = run_recorded(engine, hub, clock=clock, sleep=time.sleep)
        assert result['state'] == 'ABORTED'
        assert arm.pose[2] == pytest.approx(.07)
        return 2

    monkeypatch.setattr(runner, 'hardware_session', session)
    monkeypatch.setattr(runner, 'execute_hardware', execute)
    monkeypatch.setattr('builtins.input', lambda *args: '')
    source_path = tmp_path/'settings.json'
    source_path.write_text(json.dumps(settings()))
    assert runner.main(['--execute', '--target-z-mm', '20', '--repeats', '2', '--settings', str(source_path),
                        '--run-root', str(tmp_path)]) == 2
    batch = json.loads(next(tmp_path.glob('**/batch_*.json')).read_text())
    assert batch['reason'] == 'deadline_miss'
    assert batch['failed_trial'] == 1
    assert len(batch['records']) == 1
    diagnostic = batch['records'][0]['deadline_diagnostic']
    assert diagnostic['timeline_policy'] == 'sequential_20ms'
    assert diagnostic['command_duration_s'] == pytest.approx(.16)
    assert diagnostic['lateness_s'] > .1
    assert '超时诊断' in capsys.readouterr().out


def test_offline_analysis_skips_failed_run_with_missing_metrics(tmp_path):
    from scripts.run_contact_entry_test import main
    from brushbot.experiments.contact_entry_test import ENTRY_POLICY
    folder = tmp_path/'failed_run'
    folder.mkdir()
    batch = tmp_path/'batch_missing_metrics.json'
    batch.write_text(json.dumps(dict(batch_id='failed',entry_policy=ENTRY_POLICY,records=[dict(
        trial=dict(trial_id='failed'),run_dir=str(folder),execution_ok=False,
        metrics=None,metrics_error='missing metrics',state='FAULT')])))
    assert main(['--analyze-batch',str(batch)]) == 0
    summary = json.loads((tmp_path/'batch_missing_metrics_summary.json').read_text())
    assert summary['conditions'] == []


@pytest.mark.parametrize('direction', ['up', 'right', 'down', 'left'])
def test_manual_entry_parameters_reach_requested_angle_height_and_offset(direction):
    from scripts.run_contact_entry_test import prepare_trials
    from brushbot.experiments.contact_entry_test import compile_contact_test
    from brushbot.experiments.four_direction_sweep import DIRECTIONS

    trial = prepare_trials(settings(), direction=direction, target_z_mm=29.,
        entry_contact_z_mm=35., rotate_start_z_mm=33., rotate_s=2.,
        entry_tilt_deg=22., writing_tilt_deg=12., entry_reverse_mm=3.,
        preload_speed_mm_s=4., air_rotate_s=1.5, airborne_settle_s=.4,
        post_lift_hold_s=.6, travel_mm=60., return_to_origin=False)[0]
    c = compile_contact_test(trial['profile'], trial['setup'], trial['entry'])
    poses, phases = c['pose_m_rad'], c['phase']
    indices = np.flatnonzero(phases == 'rotate_load')
    before, end = poses[indices[0]-1], poses[indices[-1]]
    origin = np.array([trial['setup']['origin_x_mm'], trial['setup']['origin_y_mm']])/1000
    assert before[:2] == pytest.approx(origin+.003*np.array(DIRECTIONS[direction]))
    assert before[2] == pytest.approx(.033)
    assert np.linalg.norm(np.rad2deg(before[3:])) == pytest.approx(22.)
    assert end[:2] == pytest.approx(origin)
    assert end[2] == pytest.approx(.029)
    assert np.linalg.norm(np.rad2deg(end[3:])) == pytest.approx(12.)
    assert trial['timing']['phase_durations_s']['entry_preload'] == pytest.approx(.94)
    assert trial['timing']['phase_durations_s']['rotate_load'] == pytest.approx(2.)
    assert 'return_high' not in phases
    assert trial['entry_tilt_deg'] == 22.
    assert trial['writing_tilt_deg'] == 12.


def test_config_parameters_apply_and_explicit_cli_values_take_precedence(tmp_path):
    from scripts.run_contact_entry_test import main
    config = tmp_path/'candidate.json'
    config.write_text(json.dumps(dict(version=1, name='short trial', parameters=dict(
        entry_tilt_deg=20., rotate_start_z_mm=34., rotate_s=2.,
        preload_speed_mm_s=4., travel_mm=50., return_to_origin=False))))
    preview, run_root = tmp_path/'preview', tmp_path/'runs'
    assert main(['--config', str(config), '--entry-tilt-deg', '22', '--rotate-s', '3',
                 '--preview-dir', str(preview), '--run-root', str(run_root)]) == 0
    data = json.loads((preview/'planned_trials.json').read_text())['trials'][0]
    assert data['profile']['entry_tilt_deg'] == 22.
    assert data['profile']['rotate_s'] == 3.
    assert data['entry']['rotate_start_z_mm'] == 34.
    assert data['profile']['travel_mm'] == 50.
    timing = data['trial']['timing']
    assert timing['phase_durations_s']['entry_preload'] == pytest.approx(.94)
    assert timing['phase_durations_s']['straight_hold'] == pytest.approx(5.2)
    assert timing['baseline_windows_s'] == pytest.approx(4.)
    assert timing['reference_run_s'] == pytest.approx(timing['trajectory_s']+4.)
    assert data['trial']['config_source']['content']['parameters']['entry_tilt_deg'] == 20.
    assert not run_root.exists()


@pytest.mark.parametrize('parameters', [
    {'execute': True}, {'entry_tilt_deg': True}, {'rotate_s': '2'},
    {'rotate_s': None}, {'repeats': 1.5}, {'direction': []},
])
def test_bad_parameter_config_is_rejected_before_hardware_prompt(tmp_path, monkeypatch, parameters):
    from scripts.run_contact_entry_test import main
    config = tmp_path/'bad.json'
    config.write_text(json.dumps(dict(version=1, parameters=parameters)))
    def unexpected_prompt(*args):
        raise AssertionError('bad config must not reach confirmation')
    monkeypatch.setattr('builtins.input', unexpected_prompt)
    with pytest.raises(SystemExit) as exc:
        main(['--config', str(config), '--execute', '--run-root', str(tmp_path/'runs')])
    assert exc.value.code == 2
    assert not (tmp_path/'runs').exists()


def test_legacy_contact_batch_can_still_be_analyzed(tmp_path):
    from scripts.run_contact_entry_test import main
    batch = tmp_path/'legacy.json'
    batch.write_text(json.dumps(dict(batch_id='legacy',
        entry_policy='preload30_then_rotate_and_press_v1', records=[])))
    assert main(['--analyze-batch', str(batch)]) == 0
    assert json.loads((tmp_path/'legacy_summary.json').read_text())['conditions'] == []
