#!/usr/bin/env python3
"""独立接触测试：保持指定倾角预压，再同步转到工作倾角并到达目标Z。

默认离线；--execute 才连接设备，每笔 Enter 确认。正式写字流程未接入本策略。
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime
from functools import partial
import hashlib
import json
import math
from pathlib import Path
import uuid
from zoneinfo import ZoneInfo

import numpy as np

from brushbot.experiments.contact_entry_test import (
    ENTRY_POLICY, LEGACY_ENTRY_POLICY, ContactHub, ContactTestEngine, compile_contact_test,
    summarize_repeats, summarize_rows,
)
from brushbot.experiments.four_direction_sweep import DIRECTIONS
from brushbot.experiments.strokeplan_execution import runtime_settings

if __package__:
    from .run_four_direction_sweep import PROFILE as SWEEP_PROFILE, DIRECTION_ORIGINS_MM, SETTINGS, position_at_wait
    from .run_ladder_experiment import DatedLadderRecorder
    from .run_z_identification import execute_hardware, hardware_session
else:
    from run_four_direction_sweep import PROFILE as SWEEP_PROFILE, DIRECTION_ORIGINS_MM, SETTINGS, position_at_wait
    from run_ladder_experiment import DatedLadderRecorder
    from run_z_identification import execute_hardware, hardware_session

ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT/'runs/brush2'
EXPERIMENT_FOLDER = '独立接触参数测试'
PROFILE = dict(SWEEP_PROFILE, mode='four-direction-hold', direction='up',
               start_z_mm=28., end_z_mm=28., rotate_s=6., return_to_origin=True)
PARAMETER_DEFAULTS = dict(suite='single', direction='up', target_z_mm=28.,
    rotate_start_z_mm=32., rotate_s=6., preload_speed_mm_s=2.,
    entry_tilt_deg=30., writing_tilt_deg=15., entry_contact_z_mm=36.,
    entry_reverse_mm=5., air_rotate_s=1.5, airborne_settle_s=1.,
    post_lift_hold_s=2., return_to_origin=True, repeats=None,
    travel_mm=150., speed_mm_s=10., origin_x_mm=None, origin_y_mm=None, prep_note='')


def load_parameter_config(path):
    source = Path(path).read_bytes()
    config = json.loads(source)
    if (not isinstance(config, dict) or type(config.get('version')) is not int
            or config['version'] != 1 or not isinstance(config.get('parameters'), dict)):
        raise ValueError('require version=1 and a parameters object')
    if config.keys() - {'version', 'name', 'note', 'parameters'}:
        raise ValueError('unknown top-level fields')
    if any(not isinstance(config[key], str) for key in ('name', 'note') if key in config):
        raise ValueError('name/note must be strings')
    parameters = config['parameters']
    unknown = parameters.keys() - PARAMETER_DEFAULTS.keys()
    if unknown:
        raise ValueError('unknown parameters: '+', '.join(sorted(unknown)))
    for key, value in parameters.items():
        if value is None and key in {'repeats', 'origin_x_mm', 'origin_y_mm'}:
            continue
        if key in {'suite', 'direction', 'prep_note'}:
            valid = isinstance(value, str)
        elif key == 'return_to_origin':
            valid = type(value) is bool
        elif key == 'repeats':
            valid = type(value) is int
        else:
            valid = type(value) in {int, float} and math.isfinite(value)
        if not valid:
            raise ValueError('invalid parameter type: '+key)
    return parameters, dict(path=str(Path(path).resolve()),
        sha256=hashlib.sha256(source).hexdigest(), content=config)


def planned_timing(compiled, setup):
    intervals = np.diff(compiled['t_s'], prepend=compiled['t_s'][0])
    durations = {str(phase): round(float(intervals[compiled['phase'] == phase].sum()), 6)
                 for phase in dict.fromkeys(compiled['phase'])}
    trajectory_s = float(compiled['t_s'][-1])
    windows_s = float(setup['baseline_window_s'])*(1+len(compiled['automatic_rebaseline_after_indices']))
    return dict(trajectory_s=trajectory_s, phase_durations_s=durations,
        contact_loading_s=durations.get('entry_preload', 0.)+durations['rotate_load'],
        baseline_windows_s=windows_s, reference_run_s=trajectory_s+windows_s,
        exclusions='Operator preparation, connection, automatic positioning, extra baseline waiting, '
                   'Servo startup and communication stalls are not included; not a wall-clock guarantee.')


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    temporary.replace(path)


def trial_metadata(trial):
    return {k:copy.deepcopy(v) for k,v in trial.items() if k not in {'setup','profile','entry'}}


def prepare_trials(settings, *, suite='single', direction='up', target_z_mm=28.,
                   rotate_start_z_mm=32., rotate_s=6., preload_speed_mm_s=2.,
                   entry_tilt_deg=30., writing_tilt_deg=15., entry_contact_z_mm=36.,
                   entry_reverse_mm=5., air_rotate_s=1.5, airborne_settle_s=1.,
                   post_lift_hold_s=2., return_to_origin=True,
                   repeats=1, travel_mm=150., speed_mm_s=10., origin_x_mm=None,
                   origin_y_mm=None, prep_note='', hardware=False):
    if direction not in DIRECTIONS or suite not in {'single','heights','times','grid'}:
        raise ValueError('unknown contact suite or direction')
    if isinstance(repeats,bool) or not isinstance(repeats,int) or repeats < 1:
        raise ValueError('repeats must be an integer >= 1')
    if settings['filter'] != {'kind':'ema','alpha':.3}:
        raise ValueError('contact comparison requires EMA alpha=0.3')
    if suite in {'heights','grid'} and target_z_mm != 28.:
        raise ValueError('height/grid presets are for Z28; use single/times for another target')
    heights = (32.,34.,36.) if suite in {'heights','grid'} else (rotate_start_z_mm,)
    times = (4.,6.,8.) if suite in {'times','grid'} else (rotate_s,)
    conditions = [(z,t) for z in heights for t in times]
    origin = DIRECTION_ORIGINS_MM[direction]
    current = copy.deepcopy(settings)
    current['workspace_min_mm'][1],current['workspace_max_mm'][1] = 300.,700.
    current.update(wait_z_mm=70.,origin_x_mm=origin[0] if origin_x_mm is None else origin_x_mm,
                   origin_y_mm=origin[1] if origin_y_mm is None else origin_y_mm)
    setup = runtime_settings(current,hardware=hardware)
    trials = []
    for repeat in range(1,repeats+1):
        order = conditions if repeat % 2 else list(reversed(conditions))
        for start,seconds in order:
            profile = dict(PROFILE,direction=direction,start_z_mm=target_z_mm,end_z_mm=target_z_mm,
                           rotate_s=seconds,travel_mm=travel_mm,speed_mm_s=speed_mm_s,
                           entry_tilt_deg=entry_tilt_deg,writing_tilt_deg=writing_tilt_deg,
                           entry_contact_z_mm=entry_contact_z_mm,entry_reverse_mm=entry_reverse_mm,
                           air_rotate_s=air_rotate_s,airborne_settle_s=airborne_settle_s,
                           post_lift_hold_s=post_lift_hold_s,return_to_origin=return_to_origin)
            entry = dict(rotate_start_z_mm=start,preload_speed_mm_s=preload_speed_mm_s)
            # Every condition passes the full path check before any connection.
            compiled = compile_contact_test(profile,setup,entry)
            timing = compiled['spec_snapshot']['deadline_policy']
            signature = hashlib.sha256(json.dumps(dict(profile=profile,entry=entry,setup=setup,deadline_policy=timing),
                sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
            trials.append(dict(trial_id=f'Z{target_z_mm:g}_{direction}_A{entry_tilt_deg:g}_W{writing_tilt_deg:g}_S{start:g}_T{seconds:g}_R{repeat}',
                direction=direction,command_z_mm=target_z_mm,rotate_start_z_mm=start,rotate_s=seconds,
                entry_tilt_deg=entry_tilt_deg,writing_tilt_deg=writing_tilt_deg,
                entry_contact_z_mm=entry_contact_z_mm,entry_reverse_mm=entry_reverse_mm,
                air_rotate_s=air_rotate_s,airborne_settle_s=airborne_settle_s,
                post_lift_hold_s=post_lift_hold_s,return_to_origin=return_to_origin,
                preload_speed_mm_s=preload_speed_mm_s,travel_mm=travel_mm,speed_mm_s=speed_mm_s,
                repeat=repeat,entry_policy=ENTRY_POLICY,condition_sha256=signature,prep_note=prep_note,
                deadline_policy=timing,timing=planned_timing(compiled,setup),
                profile=profile,entry=entry,setup=copy.deepcopy(setup)))
    return trials


class ContactRecorder(DatedLadderRecorder):
    def __init__(self,root,snapshots):
        self._trial = snapshots['experiment']['contact_trial']
        super().__init__(root,snapshots,experiment_folder=EXPERIMENT_FOLDER,
                         folder_label=self._trial['trial_id'])

    def _write_snapshots(self,snapshots):
        super()._write_snapshots(snapshots)
        spec = snapshots['experiment']
        self._save_json('contact_test.json',dict(trial=spec['contact_trial'],entry=spec['contact_test'],
                                               profile=spec['identification'],entry_policy=ENTRY_POLICY))
        self._save_json('segments.json',snapshots['compiled']['segments'])
        self._save_json('motion_metrics.json',snapshots['compiled']['motion_metrics'])
        if snapshots.get('settings_source_bytes') is not None:
            self._save_bytes('settings_source.json',snapshots['settings_source_bytes'])

    def finish(self,status,reason=''):
        result = super().finish(status,reason)
        path = self.run_dir/'contact_metrics.json'
        if not path.exists():
            source = self.run_dir/'control.jsonl'
            rows = [json.loads(line) for line in source.read_text().splitlines()]
            metrics = summarize_rows(rows,self._trial,status=self._manifest['status'])
            metrics.update(run_id=self.run_id,source_control_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
            write_json(path,metrics)
        return result


def build_stack(*,profile,setup,root,arm,source,clock,trial,settings_source_bytes=None,
                batch_id=None,auto_position=True,engines=None):
    if profile != trial['profile'] or setup != trial['setup']:
        raise ValueError('execution differs from prechecked contact trial')
    positioning = None
    def record(snapshots):
        snapshots = dict(snapshots,settings_source_bytes=settings_source_bytes)
        snapshots['experiment'] = dict(snapshots['experiment'],batch_id=batch_id,positioning=positioning,
            settings_source_sha256=hashlib.sha256(settings_source_bytes).hexdigest() if settings_source_bytes else None)
        return ContactRecorder(root,snapshots)
    hub = ContactHub(source,clock.now_ns,abort_on_invalid_running_sample=True,baseline_quality_axes=(0,1))
    engine = ContactTestEngine(arm,hub,record,clock,dt_s=.02)
    engine.prepare_contact(profile,setup,trial['entry'],trial_metadata(trial))
    if engines is not None:
        engines.append(engine)
    if auto_position:
        date = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')
        path = Path(root)/date/EXPERIMENT_FOLDER/'positioning'/f'{batch_id}_{trial["trial_id"]}_{uuid.uuid4().hex}.json'
        positioning = position_at_wait(arm,setup,record_path=path,
            continue_above_z_mm=trial['deadline_policy']['min_z_mm'],
            context=dict(batch_id=batch_id,trial=trial_metadata(trial)))
        positioning['sensor_buffer_reset'] = source.discard_pending()
    return engine,hub


def export_preview(folder,trials,source_bytes):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    folder = Path(folder)
    folder.mkdir(parents=True,exist_ok=False)
    planned = []
    fig,axes = plt.subplots(2,1,figsize=(10,7),sharex=True)
    for trial in trials:
        c = compile_contact_test(trial['profile'],trial['setup'],trial['entry'])
        np.savez(folder/f'{trial["trial_id"]}_timeline.npz',**{
            k:c[k] for k in ('t_s','phase','pose_m_rad','depth_ff_m')})
        planned.append(dict(trial=trial_metadata(trial),profile=trial['profile'],entry=trial['entry'],
                            setup=trial['setup'],motion_metrics=c['motion_metrics'],segments=c['segments']))
        if trial['repeat'] != 1:
            continue
        selected = np.isin(c['phase'],['entry_preload','rotate_load','straight_hold'])
        times = c['t_s'][selected]
        times = times-times[0]
        poses = c['pose_m_rad'][selected]
        label = f'A{trial["entry_tilt_deg"]:g}→W{trial["writing_tilt_deg"]:g}, S{trial["rotate_start_z_mm"]:g}, T{trial["rotate_s"]:g}s'
        axes[0].plot(times,poses[:,2]*1000,label=label)
        axes[1].plot(times,np.linalg.norm(np.rad2deg(poses[:,3:]),axis=1),label=label)
    axes[0].set_ylabel('Command TCP Z (mm)')
    axes[1].set_ylabel('Command tilt (deg)')
    axes[1].set_xlabel('Time from preparation/loading start (s)')
    for ax in axes:
        ax.legend(); ax.grid(alpha=.25)
    fig.suptitle('Contact test preview: preparation → coupled rotation/loading → sliding')
    fig.tight_layout()
    fig.savefig(folder/'trajectory_preview.png',dpi=160)
    plt.close(fig)
    (folder/'settings_source.json').write_bytes(source_bytes)
    write_json(folder/'planned_trials.json',dict(role='planned_not_execution_log',hardware_connected=False,
        entry_policy=ENTRY_POLICY,trials=planned))


def report_repeats(records):
    summary = summarize_repeats(records)
    for group in summary:
        fraction = group['between_run_range_over_median']
        variation = '待重复' if fraction is None else f'{fraction:.1%}'
        print(f'A{group["entry_tilt_deg"]:g}→W{group["writing_tilt_deg"]:g}/'
              f'S{group["rotate_start_z_mm"]:g}/T{group["rotate_s"]:g}s: '
              f'完成重复={group["completed_repeats"]}，中段未归一化滤波中位数={group["per_run_medians_uT"]}，极差/中位数={variation}')
    return summary


def result_record(trial,engine=None,*,execution_ok=False,reason=''):
    snapshot = engine.snapshot() if engine is not None else {'state':'not_started'}
    folder = Path(snapshot['run_dir']).resolve() if snapshot.get('run_dir') else None
    record = dict(trial=trial_metadata(trial),run_dir=str(folder) if folder else None,
        run_id=snapshot.get('run_id'),state=snapshot['state'],
        reason=reason or snapshot.get('last_error'),metrics=None,execution_ok=execution_ok,
        deadline_diagnostic=snapshot.get('deadline_diagnostic'),
        deadline_recovery_count=snapshot.get('deadline_recovery_count', 0),
        last_deadline_recovery=snapshot.get('last_deadline_recovery'))
    if folder:
        try:
            record['metrics'] = json.loads((folder/'contact_metrics.json').read_text())
        except (OSError,ValueError) as exc:
            record.update(metrics_error=f'{type(exc).__name__}: {exc}',execution_ok=False)
    return record


def analyze_batch(path):
    path = Path(path)
    batch = json.loads(path.read_text())
    if batch.get('entry_policy') not in {ENTRY_POLICY, LEGACY_ENTRY_POLICY}:
        raise ValueError('not a contact-entry-test batch')
    records = []
    for record in batch['records']:
        record = copy.deepcopy(record)
        if record.get('run_dir') and record.get('execution_ok',True):
            folder = Path(record['run_dir'])
            metrics = json.loads((folder/'contact_metrics.json').read_text())
            if hashlib.sha256((folder/'control.jsonl').read_bytes()).hexdigest() != metrics['source_control_sha256']:
                raise ValueError('control source changed: '+str(folder))
            record['metrics'] = metrics
        elif not record.get('execution_ok',True):
            print('跳过失败尝试:',record['trial']['trial_id'],record.get('run_dir'),record.get('metrics_error') or record.get('reason'))
        records.append(record)
    summary = report_repeats(records)
    output = path.with_name(path.stem+'_summary.json')
    write_json(output,dict(batch_id=batch['batch_id'],source_batch=str(path),conditions=summary,
        note='Within-batch engineering comparison; assess observed contact shape and TCP before selecting parameters.'))
    print('对照汇总:',output)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--execute',action='store_true')
    mode.add_argument('--dry-run',action='store_true')
    parser.add_argument('--config',type=Path,help='可编辑的接触参数 JSON；显式 CLI 参数优先')
    parser.add_argument('--suite',choices=['single','heights','times','grid'],default='single')
    parser.add_argument('--direction',choices=list(DIRECTIONS),default='up')
    parser.add_argument('--target-z-mm',type=float,default=28.)
    parser.add_argument('--rotate-start-z-mm',type=float,default=32.)
    parser.add_argument('--rotate-s',type=float,default=6.)
    parser.add_argument('--preload-speed-mm-s',type=float,default=2.)
    parser.add_argument('--entry-tilt-deg',type=float,default=30.,help='起始倾角；工作倾角 < 起始倾角 <= 30')
    parser.add_argument('--writing-tilt-deg',type=float,default=15.)
    parser.add_argument('--entry-contact-z-mm',type=float,default=36.)
    parser.add_argument('--entry-reverse-mm',type=float,default=5.)
    parser.add_argument('--air-rotate-s',type=float,default=1.5)
    parser.add_argument('--airborne-settle-s',type=float,default=1.)
    parser.add_argument('--post-lift-hold-s',type=float,default=2.)
    parser.add_argument('--return-to-origin',action=argparse.BooleanOptionalAction,default=True)
    parser.add_argument('--repeats',type=int)
    parser.add_argument('--travel-mm',type=float,default=150.)
    parser.add_argument('--speed-mm-s',type=float,default=10.)
    parser.add_argument('--origin-x-mm',type=float)
    parser.add_argument('--origin-y-mm',type=float)
    parser.add_argument('--settings',type=Path,default=SETTINGS)
    parser.add_argument('--run-root',type=Path,default=RUN_ROOT)
    parser.add_argument('--preview-dir',type=Path)
    parser.add_argument('--start-trial',type=int,default=1)
    parser.add_argument('--prep-note',default='',help='操作者提供的毛笔准备/纸面操作记录，随每笔保存')
    parser.add_argument('--no-record-actual-tcp',action='store_true')
    parser.add_argument('--analyze-batch',type=Path)
    args = parser.parse_args(argv)
    if args.analyze_batch:
        if args.execute:
            parser.error('--analyze-batch cannot execute hardware')
        return analyze_batch(args.analyze_batch)
    config_source = None
    if args.config:
        try:
            parameters, config_source = load_parameter_config(args.config)
        except (OSError,ValueError) as exc:
            parser.error('配置文件: '+str(exc))
        parser.set_defaults(**parameters)
        args = parser.parse_args(argv)
    if args.execute and args.preview_dir:
        parser.error('--preview-dir is for offline review only')
    source_bytes = args.settings.read_bytes()
    try:
        trials = prepare_trials(json.loads(source_bytes),suite=args.suite,direction=args.direction,
            target_z_mm=args.target_z_mm,rotate_start_z_mm=args.rotate_start_z_mm,rotate_s=args.rotate_s,
            preload_speed_mm_s=args.preload_speed_mm_s,
            entry_tilt_deg=args.entry_tilt_deg,writing_tilt_deg=args.writing_tilt_deg,
            entry_contact_z_mm=args.entry_contact_z_mm,entry_reverse_mm=args.entry_reverse_mm,
            air_rotate_s=args.air_rotate_s,airborne_settle_s=args.airborne_settle_s,
            post_lift_hold_s=args.post_lift_hold_s,return_to_origin=args.return_to_origin,
            repeats=args.repeats if args.repeats is not None else (1 if args.suite == 'single' else 2),
            travel_mm=args.travel_mm,speed_mm_s=args.speed_mm_s,origin_x_mm=args.origin_x_mm,
            origin_y_mm=args.origin_y_mm,prep_note=args.prep_note,hardware=args.execute)
    except ValueError as exc:
        parser.error(str(exc))
    if config_source:
        for trial in trials:
            trial['config_source'] = copy.deepcopy(config_source)
        print('参数配置:',args.config)
    if not 1 <= args.start_trial <= len(trials):
        parser.error('--start-trial outside selected matrix')
    print(f'独立接触测试：{len(trials)} 笔计划；反馈关闭；目标 Z{args.target_z_mm:g}。')
    print('计时策略：当前及下一命令 Z > 20 mm 时，延迟记录后按顺序继续；失联及运动越界仍停止。')
    for i,trial in enumerate(trials,1):
        print(f'{i}/{len(trials)} {trial["trial_id"]}: {trial["entry_tilt_deg"]:g}°预压至Z{trial["rotate_start_z_mm"]:g} '
              f'→ {trial["rotate_s"]:g}s边转边压到{trial["writing_tilt_deg"]:g}°/Z{trial["command_z_mm"]:g} → '
              f'{trial["travel_mm"]:g}mm直线/{trial["speed_mm_s"]:g}mm/s')
        timing = trial['timing']
        print(f'  用时：预压 {timing["phase_durations_s"].get("entry_preload",0):.2f}s，'
              f'联动 {trial["rotate_s"]:.2f}s，行笔 {timing["phase_durations_s"]["straight_hold"]:.2f}s；'
              f'完整轨迹 {timing["trajectory_s"]:.2f}s，含基线窗口参考 {timing["reference_run_s"]:.2f}s。')
    print('参考总时长不含人工准备、连接、自动定位、额外基线等待、Servo启动及通信阻塞。')
    if not args.execute:
        if args.preview_dir:
            export_preview(args.preview_dir,trials,source_bytes)
            print('预检包:',args.preview_dir)
        print('完整轨迹离线预检通过；未连接设备，未创建实验 run。')
        return 0

    def confirm(index):
        return input(f'请移纸至未写区域，保持一致的毛笔准备；确认后 Enter 开始 '
                     f'{index}/{len(trials)} {trials[index-1]["trial_id"]}（其他输入结束）: ').strip() == ''

    if not confirm(args.start_trial):
        return 0
    date = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')
    parent = args.run_root/date/EXPERIMENT_FOLDER
    parent.mkdir(parents=True,exist_ok=True)
    batch_id = uuid.uuid4().hex
    batch_path = parent/f'batch_{batch_id}.json'
    batch = dict(batch_id=batch_id,entry_policy=ENTRY_POLICY,status='running',
        selected_start_trial=args.start_trial,planned=[trial_metadata(t) for t in trials],records=[])
    write_json(batch_path,batch)
    print('批次记录:',batch_path)
    index = args.start_trial
    engines = []
    code = 0

    def remember_failure(reason):
        trial = trials[index-1]
        if batch['records'] and batch['records'][-1]['trial']['trial_id'] == trial['trial_id']:
            batch['records'][-1].update(reason=reason,execution_ok=False)
        else:
            engine = engines[-1] if engines and engines[-1]._spec['contact_trial']['trial_id'] == trial['trial_id'] else None
            batch['records'].append(result_record(trial,engine,reason=reason))

    try:
        with hardware_session(trials[index-1]['setup'],record_tcp=not args.no_record_actual_tcp) as session:
            for index in range(args.start_trial,len(trials)+1):
                if index > args.start_trial and not confirm(index):
                    batch['status'] = 'stopped_by_operator'
                    break
                trial = trials[index-1]
                print('开始:',trial['trial_id'])
                code = execute_hardware(trial['profile'],trial['setup'],source_bytes,args.run_root,
                    record_tcp=not args.no_record_actual_tcp,session=session,
                    stack_factory=partial(build_stack,trial=trial,batch_id=batch_id,engines=engines),
                    display_name='接触参数测试')
                record = result_record(trial,engines[-1],execution_ok=code == 0)
                batch['records'].append(record)
                write_json(batch_path,batch)
                if record.get('metrics_error') or record['metrics'] is None:
                    raise RuntimeError('contact metrics unavailable; run reference retained')
                metrics = record['metrics']
                if code:
                    batch.update(status='failed', reason=record['reason'] or 'execution_failed',
                                 failed_trial=index)
                    print('批次停止:', batch['reason'])
                    if record['deadline_diagnostic']:
                        print('超时诊断:', json.dumps(record['deadline_diagnostic'], ensure_ascii=False))
                    break
                print('本笔中段:',json.dumps({k:v for k,v in metrics['primary'].items() if k != 'bins'},ensure_ascii=False))
            else:
                batch['status'] = 'completed' if args.start_trial == 1 else 'completed_selected_suffix'
    except KeyboardInterrupt:
        remember_failure('operator_stop')
        batch.update(status='interrupted',reason='operator_stop')
        code = 130
    except Exception as exc:
        reason = f'{type(exc).__name__}: {exc}'
        remember_failure(reason)
        batch.update(status='failed',reason=reason,failed_trial=index)
        print('批次停止:',batch['reason'])
        code = 2
    finally:
        batch['comparison'] = report_repeats(batch['records'])
        write_json(batch_path,batch)
        print('批次记录:',batch_path)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
