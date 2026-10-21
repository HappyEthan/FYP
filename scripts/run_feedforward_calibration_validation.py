#!/usr/bin/env python3
"""+X/+Y common-feedforward and directional-calibration test: 8 fixed-target strokes.

Default is offline. --execute runs the selected matrix with per-stroke confirmation.
No feedback correction. Every stroke returns to XYZ=(-150,500,70), RPY=(0,15,0).
"""
from __future__ import annotations

import argparse
import copy
from functools import partial
import hashlib
import json
from pathlib import Path
import uuid

import numpy as np

from brushbot.experiments.feedforward_calibration_validation import (
    COMMON_WAIT, ValidationEngine, ValidationHub, compile_trial, load_calibration,
    summarize_rows, trial_metadata, write_json,
)
from brushbot.experiments.strokeplan_execution import runtime_settings

if __package__:
    from .run_four_direction_sweep import PROFILE, position_at_wait
    from .run_ladder_experiment import DatedLadderRecorder
    from .run_z_identification import execute_hardware, hardware_session
else:
    from run_four_direction_sweep import PROFILE, position_at_wait
    from run_ladder_experiment import DatedLadderRecorder
    from run_z_identification import execute_hardware, hardware_session

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT/'runs/brush2/plans/feedforward_calibration_handoff_v2'
SETTINGS = ROOT/'runs/brush2/plans/12_中字朝负Y_正X为右/settings.json'
RUN_ROOT = ROOT/'runs/brush2/正向前馈校准验证'
EXPERIMENT_FOLDER = '公共前馈与方向校准'


def prepare_trials(settings, calibration, direction='all', *, hardware=False):
    if direction not in {'all', 'right', 'up'}:
        raise ValueError('only +X/right and +Y/up are supported by this protocol')
    if settings['filter'] != {'kind': 'ema', 'alpha': .3} or settings['contact_z_mm'] != 40:
        raise ValueError('protocol requires contact Z40 and EMA alpha=0.3')
    conditions = [('right', 8, 1), ('up', 8, 1), ('right', 12, 1), ('up', 12, 1),
                  ('up', 12, 2), ('right', 12, 2), ('up', 8, 2), ('right', 8, 2)]
    trials = []
    for heading, depth, repeat in conditions:
        if direction != 'all' and heading != direction:
            continue
        target = calibration.forward(depth)
        z = round(40-calibration.inverse(target), 9)
        current = copy.deepcopy(settings)
        current['workspace_min_mm'][1], current['workspace_max_mm'][1] = 300., 700.
        current.update(origin_x_mm=-150., origin_y_mm=500. if heading == 'right' else 450.,
                       wait_z_mm=70., vertical_rpy_rad=COMMON_WAIT[3:].tolist())
        setup = runtime_settings(current, hardware=hardware)
        profile = dict(PROFILE, mode='four-direction-hold', direction=heading,
                       speed_mm_s=10., travel_mm=150., start_z_mm=z, end_z_mm=z,
                       writing_tilt_deg=15., return_to_origin=False)
        trials.append(dict(trial_id=f'Z{z:g}_{heading}_R{repeat}', direction=heading,
            deadline_policy=dict(mode='continue_above_z', min_z_mm=20.),
            repeat=repeat, common_target_uT=target, command_z_mm=z, nominal_depth_mm=depth,
            common_reference_id=calibration.reference['reference_id'],
            model_sha256=calibration.model_sha256, reference_sha256=calibration.reference_sha256,
            setup=setup, profile=profile))
    # All paths, including the common return, pass before any connection is opened.
    for trial in trials:
        compile_trial(trial, trial['setup'])
    return trials


class ValidationRecorder(DatedLadderRecorder):
    def __init__(self, root, snapshots):
        self._trial = snapshots['experiment']['validation']
        super().__init__(root, snapshots, experiment_folder=EXPERIMENT_FOLDER,
                         folder_label=self._trial['trial_id'])

    def _write_snapshots(self, snapshots):
        super()._write_snapshots(snapshots)
        self._save_bytes('directional_calibration.json', snapshots['directional_model_bytes'])
        self._save_bytes('common_reference.json', snapshots['common_reference_bytes'])
        self._save_json('validation.json', snapshots['experiment']['validation'])
        self._save_json('segments.json', snapshots['compiled']['segments'])
        self._save_json('motion_metrics.json', snapshots['compiled']['motion_metrics'])
        if snapshots.get('settings_source_bytes') is not None:
            self._save_bytes('settings_source.json', snapshots['settings_source_bytes'])

    def finish(self, status, reason=''):
        result = super().finish(status, reason)
        metric_path = self.run_dir/'validation_metrics.json'
        if not metric_path.exists():
            rows = [json.loads(line) for line in (self.run_dir/'control.jsonl').read_text().splitlines()]
            metrics = summarize_rows(rows, self._trial)
            metrics.update(run_id=self.run_id, run_status=self._manifest['status'])
            write_json(metric_path, metrics)
        return result


def build_stack(*, profile, setup, root, arm, source, clock, calibration, trial,
                settings_source_bytes=None, auto_position=True, batch_id=None, engines=None):
    if profile != trial['profile']:
        raise ValueError('execution profile differs from planned trial')
    positioning = None
    def record(snapshots):
        snapshots = dict(snapshots, settings_source_bytes=settings_source_bytes,
                         directional_model_bytes=calibration.model_bytes,
                         common_reference_bytes=calibration.reference_bytes)
        snapshots['experiment'] = dict(snapshots['experiment'], batch_id=batch_id,
            positioning=positioning, settings_source_sha256=(hashlib.sha256(settings_source_bytes).hexdigest()
                                                            if settings_source_bytes is not None else None))
        return ValidationRecorder(root, snapshots)
    hub = ValidationHub(source, clock.now_ns, abort_on_invalid_running_sample=True,
                        baseline_quality_axes=(0, 1))
    engine = ValidationEngine(arm, hub, record, clock, dt_s=.02)
    engine.prepare_validation(trial, setup, calibration)
    if engines is not None:
        engines.append(engine)
    if auto_position:
        folder = Path(root)/'positioning'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder/f'{batch_id}_{trial["trial_id"]}_{uuid.uuid4().hex}.json'
        positioning = position_at_wait(arm, setup, record_path=path,
            continue_above_z_mm=trial['deadline_policy']['min_z_mm'],
            context=dict(batch_id=batch_id, trial_id=trial['trial_id']))
        positioning['sensor_buffer_reset'] = source.discard_pending()
    return engine, hub


def export_preview(folder, trials, compiled, calibration, source_bytes):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    (folder/'directional_calibration.json').write_bytes(calibration.model_bytes)
    (folder/'common_reference.json').write_bytes(calibration.reference_bytes)
    (folder/'settings_source.json').write_bytes(source_bytes)
    write_json(folder/'planned_trials.json', dict(role='planned_not_execution_log',
        model_sha256=calibration.model_sha256, reference_sha256=calibration.reference_sha256,
        return_origin_pose_m_rad=COMMON_WAIT.tolist(), trials=[trial_metadata(t) for t in trials]))
    checks = []
    for trial, timeline in zip(trials, compiled):
        np.savez(folder/f'{trial["trial_id"]}_timeline.npz', **{
            k: timeline[k] for k in ('t_s', 'phase', 'pose_m_rad', 'depth_ff_m')})
        checks.append(dict(trial_id=trial['trial_id'], motion_metrics=timeline['motion_metrics']))
    write_json(folder/'preflight_report.json', dict(hardware_connected=False,
        actual_experiment_runs_created=False, planned_strokes=len(trials), checks=checks))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--execute', action='store_true')
    mode.add_argument('--dry-run', action='store_true', help='default; no devices opened')
    parser.add_argument('--direction', choices=['all', 'right', 'up'], default='all',
                        help='all means +X and +Y only, four strokes per direction')
    parser.add_argument('--start-trial', type=int, default=1)
    parser.add_argument('--settings', type=Path, default=SETTINGS)
    parser.add_argument('--model', type=Path, default=PACKAGE/'directional_calibration.json')
    parser.add_argument('--reference', type=Path, default=PACKAGE/'common_reference.json')
    parser.add_argument('--run-root', type=Path, default=RUN_ROOT)
    parser.add_argument('--preview-dir', type=Path, help='new directory for offline plans/timelines')
    parser.add_argument('--no-record-actual-tcp', action='store_true')
    args = parser.parse_args(argv)
    if args.execute and args.preview_dir is not None:
        parser.error('--preview-dir is only for offline mode')
    calibration = load_calibration(args.model, args.reference)
    source_bytes = args.settings.read_bytes()
    trials = prepare_trials(json.loads(source_bytes), calibration, args.direction, hardware=args.execute)
    if not 1 <= args.start_trial <= len(trials):
        parser.error(f'--start-trial must be between 1 and {len(trials)}')
    compiled = [compile_trial(t, t['setup']) for t in trials]
    print(f'公共前馈/方向校准：{len(trials)} 笔计划；只沿 +X/+Y；反馈修正关闭。')
    print('计时策略：当前及下一命令 Z > 20 mm 时，延迟记录后按顺序继续。')
    print('return origin XYZ (mm): [-150, 500, 70]; RPY (deg): [0, 15, 0]')
    print('参考:', calibration.reference['reference_id'])
    for i, trial in enumerate(trials, 1):
        print(f'{i}/{len(trials)} {trial["trial_id"]}: g_cal*={trial["common_target_uT"]:.6f} µT '
              f'→ Z{trial["command_z_mm"]:g}; 150 mm / 10 mm/s')
    print('Bx/By 保留符号；X ±20 µT 仅作噪声量级标记；越界不估计压深。')
    print(f'本次从第 {args.start_trial} 笔开始；原计划编号不变。')
    if not args.execute:
        if args.preview_dir is not None:
            export_preview(args.preview_dir, trials, compiled, calibration, source_bytes)
            print('预检包:', args.preview_dir)
        print('离线预检通过；未连接硬件，未创建实验 run。真机需 --execute。')
        return 0

    def confirmed(index):
        return input(f'准备纸面，按 Enter 开始 {index}/{len(trials)} '
                     f'{trials[index-1]["trial_id"]}（其他输入结束批次）: ').strip() == ''
    if not confirmed(args.start_trial):
        return 0
    args.run_root.mkdir(parents=True, exist_ok=True)
    batch_id = uuid.uuid4().hex
    manifest_path = args.run_root/f'batch_{batch_id}.json'
    batch = dict(role='physical_validation_batch', batch_id=batch_id, status='running',
        selected_start_trial=args.start_trial, trials=[trial_metadata(t) for t in trials], completed=[],
        model_sha256=calibration.model_sha256, reference_sha256=calibration.reference_sha256)
    write_json(manifest_path, batch)
    engines = []
    try:
        with hardware_session(trials[args.start_trial-1]['setup'],
                              record_tcp=not args.no_record_actual_tcp) as session:
            for index in range(args.start_trial, len(trials)+1):
                if index > args.start_trial and not confirmed(index):
                    batch['status'] = 'operator_ended'
                    return 0
                trial = trials[index-1]
                code = execute_hardware(trial['profile'], trial['setup'], source_bytes, args.run_root,
                    record_tcp=not args.no_record_actual_tcp, session=session,
                    stack_factory=partial(build_stack, calibration=calibration, trial=trial,
                                          batch_id=batch_id, engines=engines),
                    display_name='公共前馈/方向校准')
                engine = engines[-1]
                snapshot = engine.snapshot()
                result = dict(trial_id=trial['trial_id'], run_id=engine.run_id,
                              run_dir=engine.run_dir, state=engine.state,
                              reason=snapshot['last_error'],
                              deadline_diagnostic=snapshot.get('deadline_diagnostic'),
                              deadline_recovery_count=snapshot.get('deadline_recovery_count', 0),
                              last_deadline_recovery=snapshot.get('last_deadline_recovery'))
                if engine.run_dir:
                    metric_path = Path(engine.run_dir)/'validation_metrics.json'
                    if metric_path.exists():
                        result['metrics'] = json.loads(metric_path.read_text())
                        metric = result['metrics']['primary']
                        print('本笔中段:', json.dumps({k:metric[k] for k in (
                            'coverage', 'calibrated_median_uT', 'calibrated_rmse_uT_valid_only',
                            'z_rmse_mm_valid_only')}, ensure_ascii=False))
                batch['completed'].append(result)
                write_json(manifest_path, batch)
                if code != 0:
                    batch.update(status='failed', reason=result['reason'] or 'execution_failed',
                                 failed_trial=index)
                    print('批次停止:', batch['reason'])
                    if result['deadline_diagnostic']:
                        print('超时诊断:', json.dumps(result['deadline_diagnostic'], ensure_ascii=False))
                    return code
        batch['status'] = 'completed_selected_suffix'
        return 0
    except KeyboardInterrupt:
        batch.update(status='interrupted', reason='operator_interrupt')
        return 130
    except Exception as exc:
        batch.update(status='failed', reason=str(exc))
        print('批次停止:', exc)
        return 2
    finally:
        batch['recorded_trial_count'] = len(batch['completed'])
        write_json(manifest_path, batch)
        print('批次记录:', manifest_path)


if __name__ == '__main__':
    raise SystemExit(main())
