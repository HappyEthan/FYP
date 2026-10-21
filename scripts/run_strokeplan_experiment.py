#!/usr/bin/env python3
"""Execute ONE StrokePlan with magnetic recording in the existing runs format.

Default is offline. Hardware requires --execute, approved inputs, and RUN.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
import sys
import time
import uuid
from zoneinfo import ZoneInfo

import numpy as np

from brushbot.experiments.acquisition import SampleHub
from brushbot.experiments.adapter import ElfinExperimentArm, RobotResourceLock
from brushbot.experiments.strokeplan_execution import (
    StrokePlanExperimentEngine, compile_recorded_plan, runtime_settings,
)
from brushbot.experiments.tcp_pose_capture import TCPPoseSampler
from brushbot.feedforward import require_execution_approval
from brushbot.monitor.sources import SerialSource
from brushbot.target_strokeplan import StrokePlan

if __package__:
    from .run_ladder_experiment import (
        ADAPTER_ROOT, DatedLadderRecorder, LiveStatusPanel, MonotonicClock,
        TERMINAL, _pace, _read_named_coordinate, _report, _vendor_coord_to_si,
    )
else:
    from run_ladder_experiment import (
        ADAPTER_ROOT, DatedLadderRecorder, LiveStatusPanel, MonotonicClock,
        TERMINAL, _pace, _read_named_coordinate, _report, _vendor_coord_to_si,
    )

ROOT = Path(__file__).resolve().parents[1]


class StrokePlanRecorder(DatedLadderRecorder):
    def __init__(self, root, snapshots, *, experiment_folder=None,
                 folder_label=None):
        super().__init__(root, snapshots, experiment_folder=experiment_folder,
                         folder_label=folder_label)

    def _write_snapshots(self, snapshots):
        super()._write_snapshots(snapshots)
        for name, payload in snapshots['strokeplan_inputs'].items():
            if name not in {'strokeplan.npz', 'feedforward.json', 'settings.json', 'entry_profile.json'}:
                raise ValueError('unsupported StrokePlan snapshot filename')
            self._save_bytes(name, payload)


def build_stack(*, plan, table, setup, artifacts, label, root, arm, source, clock,
                control_mode='feedforward', feedback_profile=None,
                experiment_folder=None, run_folder_label=None, entry_profile=None,
                auto_position=False):
    # Bind immutable, already-loaded input bytes to this run (no later file reread).
    captured = dict(artifacts)
    positioning = None

    def record(snapshots):
        snapshots = dict(snapshots, strokeplan_inputs=captured, calibration=table)
        snapshots['experiment'] = dict(snapshots['experiment'], inputs={
            name: {'sha256': hashlib.sha256(payload).hexdigest()}
            for name, payload in captured.items()})
        if positioning is not None:
            snapshots['experiment']['positioning'] = positioning
        return StrokePlanRecorder(root, snapshots,
                                  experiment_folder=experiment_folder,
                                  folder_label=run_folder_label)

    hub = SampleHub(source, clock.now_ns,
                    abort_on_invalid_running_sample=control_mode in {'p', 'pi'} or entry_profile is not None)
    engine = StrokePlanExperimentEngine(arm, hub, record, clock, dt_s=.02)
    engine.prepare_target(plan, table, setup, label=label,
                          control_mode=control_mode,
                          feedback_profile=feedback_profile, entry_profile=entry_profile)
    if auto_position:
        # Import after the entry module is initialized: the sweep driver also
        # imports run_recorded through run_z_identification.
        if __package__:
            from .run_four_direction_sweep import position_at_wait
        else:
            from run_four_direction_sweep import position_at_wait
        date = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')
        path = Path(root)/date/'positioning'/f'strokeplan_{uuid.uuid4().hex}.json'
        print('自动回等待位：先竖直抬笔，再高位移动并对齐姿态。定位记录:', path)
        positioning = position_at_wait(arm, setup, record_path=path,
            context=dict(run_label=label, installation_id=setup['installation_id']))
        positioning.update(record_path=str(path), sensor_buffer_reset=source.discard_pending())
        path.write_text(json.dumps(positioning, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
        print('自动定位完成；开始核验等待位并重新采集基线。')
    return engine, hub


def run_recorded(engine, hub, *, clock, sleep=time.sleep, live_output_fn=None,
                 pose_sampler=None):
    """Run once; even acquisition failures and Ctrl+C must finalize the run."""
    try:
        engine.start(require_wait_position=True)
        print('run 目录:', engine.run_dir)
        if pose_sampler is not None:
            pose_sampler.start(engine.run_dir)
        _drive_recorded(engine, hub, clock=clock, sleep=sleep,
                        live_output_fn=live_output_fn)
    except KeyboardInterrupt:
        engine.fail('operator_stop')
    except Exception as exc:
        if engine.run_id is None:
            raise
        engine.fail(f'driver_fault: {type(exc).__name__}: {exc}')
    finally:
        try:
            pose_summary = pose_sampler.stop() if pose_sampler is not None else None
        finally:
            engine.finalize_pending_recording()
    result = engine.snapshot()
    if pose_summary is not None:
        result['pose_capture'] = pose_summary
    return result


def _drive_recorded(engine, hub, *, clock, sleep, live_output_fn):
    started = clock.now_ns()
    tick = 0
    last_live = None
    interrupted = False
    while engine.state not in TERMINAL:
        try:
            hub.poll_once()
            snapshot = engine.step()
            now = clock.now_ns()
            telemetry = snapshot.get('telemetry')
            if (live_output_fn is not None and telemetry is not None
                    and engine.state == 'RUN'
                    and (last_live is None or now-last_live >= 200_000_000)):
                live_output_fn((
                    'StrokePlan  {:.1f}%  {}'.format(
                        100*float(snapshot['progress']), telemetry['phase']),
                    'Zcmd={:.3f} mm  |ΔBxy|filtered={:.2f} uT  baseline={}'.format(
                        telemetry['z_cmd_mm'], telemetry['dBxy_filtered_uT'],
                        telemetry['baseline_id']),
                ))
                last_live = now
            tick += 1
            if not hasattr(clock, 'advance'):
                period_ns = int(round(engine.dt_s*1e9))
                now = clock.now_ns()
                if now >= started+tick*period_ns:
                    # A blocking call consumed the next driver tick. Resume a
                    # regular stream instead of racing through overdue samples.
                    # Only this driver's polling grid moves here; the engine
                    # applies its own strict or height-gated deadline policy.
                    started = now+period_ns-tick*period_ns
            _pace(clock, started, tick, engine.dt_s, sleep)
        except KeyboardInterrupt:
            if interrupted:
                engine.fail('operator_stop_during_abort')
            else:
                interrupted = True
                engine.request_stop('operator_stop')
                engine.step()
        except Exception as exc:
            if (engine.state == 'RUN'
                    and (engine._spec['control'].get('mode') in {'p', 'pi'} or 'entry_profile' in engine._spec)
                    and hub.fault == 'source_disconnected'):
                engine.request_stop('source_disconnected')
                engine.step()
            else:
                engine.fail(hub.fault or f'driver_fault: {type(exc).__name__}: {exc}')


def main(argv=None, *, feedback_profile=None, confirm_execution=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan', type=Path)
    parser.add_argument('--feedforward', type=Path, required=True)
    parser.add_argument('--settings', type=Path, required=True)
    parser.add_argument('--entry-profile', type=Path,
                        help='optional rotational contact with continuous-slide or stationary loading')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--execute', action='store_true')
    mode.add_argument('--dry-run', action='store_true')
    parser.add_argument('--serial-port', default='/dev/ttyACM0')
    parser.add_argument('--baud', type=int, default=115200)
    parser.add_argument('--ip', default='192.168.0.10')
    parser.add_argument('--run-root', type=Path, default=ROOT/'runs'/'brush2')
    parser.add_argument('--run-label')
    parser.add_argument('--experiment-folder',
                        help='directory under Shanghai date for this experiment')
    parser.add_argument('--run-folder-label',
                        help='meaningful run name without time, repeat or random ID')
    parser.add_argument('--control-mode', choices=('feedforward', 'p', 'pi'),
                        default='feedforward',
                        help='select bounded P/PI feedback; PI requires an explicit supplied profile')
    parser.add_argument('--record-actual-tcp', action='store_true',
                        help='record 10 Hz actual TCP poses over a separate connection')
    args = parser.parse_args(argv)
    if bool(args.experiment_folder) != bool(args.run_folder_label):
        parser.error('--experiment-folder and --run-folder-label must be supplied together')
    try:
        artifacts = {'strokeplan.npz': args.plan.read_bytes(),
                     'feedforward.json': args.feedforward.read_bytes(),
                     'settings.json': args.settings.read_bytes()}
        plan = StrokePlan.load(io.BytesIO(artifacts['strokeplan.npz']))
        table = json.loads(artifacts['feedforward.json'])
        setup = json.loads(artifacts['settings.json'])
        entry_profile = None
        if args.entry_profile is not None:
            artifacts['entry_profile.json'] = args.entry_profile.read_bytes()
            entry_profile = json.loads(artifacts['entry_profile.json'])
        label = args.run_label or 'strokeplan_'+args.plan.stem
        compiled = compile_recorded_plan(plan, table, setup, label=label,
                                         control_mode=args.control_mode,
                                         feedback_profile=feedback_profile,
                                         entry_profile=entry_profile)
        if args.execute:
            require_execution_approval(table, setup)
            runtime_settings(setup, hardware=True)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    poses = compiled['pose_m_rad']
    if args.control_mode in {'p', 'pi'}:
        profile = compiled['spec_snapshot']['control']
        measurement_phases = profile.get('measurement_phases', ['measure_00'])
        print('单条 StrokePlan；{} 受限 {} 反馈（kp={:g}, ki={:g}）；其余阶段纯前馈。'.format(
            ', '.join(measurement_phases), args.control_mode.upper(), profile['kp'], profile['ki']))
        print('反馈深度限幅 ±{:g} mm；修正速度 {:g} mm/s、加速度 {:g} mm/s²。'.format(
            profile['max_correction_mm'], profile['max_correction_speed_mm_s'],
            profile['max_correction_accel_mm_s2']))
        if args.control_mode == 'pi':
            print('积分单独限幅 ±{:g} mm；最终输出约束下条件积分抗饱和；每笔清零。'.format(
                profile['integral_limit_mm']))
    else:
        print('单条 StrokePlan；纯前馈；运行时同步记录磁数据（无反馈修正）。')
    print('Wait XYZ [mm], RPY [deg]:', poses[0, :3]*1000, np.rad2deg(poses[0, 3:]))
    print('启动定位：确认 RUN 后自动抬笔并回到上述等待位，到位后重新采集基线。')
    print('Z range [mm]:', poses[:, 2].min()*1000, poses[:, 2].max()*1000)
    print('轨迹时长 {:.2f} s；另需启动基线采集。'.format(compiled['t_s'][-1]))
    print('前馈表:', args.feedforward)
    print('现场设置:', args.settings)
    if entry_profile is not None and entry_profile.get('mode') == 'directional_character':
        print('连续 {} 笔：仅启动时采集基线；笔间高位直接转移；末笔完成后回等待位。'.format(len(plan.strokes)))
        print('方向姿态：进笔倾角 {:g}°，书写倾角 {:g}°；Rx/Ry/Rz 随平滑行笔方向联动。'.format(
            entry_profile['entry_tilt_deg'], entry_profile['writing_tilt_deg']))
        reverse_mm = entry_profile.get('entry_reverse_mm', 0.)
        if reverse_mm:
            print('旋转落笔：先沿首段方向前置 {:g} mm，再于接触旋转时同步反向移动 {:g} mm；Z 保持不变，结束于原笔画起点。'.format(
                reverse_mm, reverse_mm))
        else:
            print('旋转落笔：保持 XYZ。')
        print('高位转移上限 {:g} mm/s；快速升降 {:g} mm/s；下笔 Z < {:g} mm 时上限 {:g} mm/s。'.format(
            entry_profile['transfer_speed_mm_s'], entry_profile['fast_z_speed_mm_s'],
            entry_profile['slow_below_z_mm'], entry_profile['slow_z_speed_mm_s']))
        print('书写速度上限 {:g} mm/s，转弯按姿态变化减速；角速度/角加速度上限 {:g}°/s、{:g}°/s²。'.format(
            table['speed_mm_s'], entry_profile['angular_speed_deg_s'], entry_profile['angular_accel_deg_s2']))
        print('试验假设：不同方向及倾斜方位沿用同一磁响应—压深表；动态姿态尚未标定。')
    elif entry_profile is not None:
        loading = ('原地加载后按目标 XY 书写' if entry_profile.get('mode') == 'stationary'
                   else '+X 滑动加载')
        print('旋转进笔: 高位 Ry{:g} -> Z{:g} -> 固定 XYZ 转 Ry15 -> {}；反馈仅 measure_00 生效。'.format(
            entry_profile['entry_ry_deg'], entry_profile['entry_contact_z_mm'], loading))
        if entry_profile.get('assume_direction_invariant'):
            print('本次试验假设：同一磁目标在不同 XY 方向对应相同压深；原表标定范围仍为 +X。')
        if entry_profile.get('mode') == 'stationary':
            print('转移/升降速度上限 {:g} mm/s；高位回程 {:g} mm/s；空中旋转 {:g} s，接触旋转 {:g} s，原地加载 {:g} s。'.format(
                entry_profile.get('transit_speed_mm_s', 10.), setup['return_speed_mm_s'],
                entry_profile.get('air_rotate_s', entry_profile['rotate_s']),
                entry_profile['rotate_s'], entry_profile['load_s']))
    print('传感器串口:', args.serial_port)
    print('输出父目录:', args.run_root)
    print('实验标签:', label)
    if args.experiment_folder:
        print('实验目录:', args.experiment_folder)
        print('原始数据名称:', args.run_folder_label)
    if args.record_actual_tcp:
        print('实际 TCP 独立采集: 10 Hz；仅记录，不参与反馈；RUN 后连接第二路。')
    if not args.execute:
        print('离线预检通过；未连接硬件，未创建实验 run。')
        return 0
    confirm = input if confirm_execution is None else confirm_execution
    if confirm('确认已手动沾水、自动回位与书写路径净空足够；输入 RUN: ').strip() != 'RUN':
        return 0

    sys.path.insert(0, str(ADAPTER_ROOT))
    from huayan_robot import HuayanRobot
    clock = MonotonicClock()
    source = SerialSource(args.serial_port, args.baud)
    lock = RobotResourceLock(Path('/tmp/brushbot-feedforward.lock'), args.ip)
    panel = LiveStatusPanel(sys.stdout)
    robot = None
    pose_client = None
    lock.acquire()
    try:
        robot = HuayanRobot(args.ip, tcp_name=setup['tcp_name'],
                            ucs_name=setup['ucs_name'], servo_dt=.02, lookahead=.1)
        robot.client.raw_client.tcp.settimeout(.5)
        for method, name, attr, key in (
            ('HRIF_ReadTCPByName', setup['tcp_name'], 'tool_coord', 'tool_coord_si'),
            ('HRIF_ReadUCSByName', setup['ucs_name'], 'user_coord', 'user_coord_si'),
        ):
            coord = _read_named_coordinate(robot.client, method, name)
            if not np.allclose(_vendor_coord_to_si(coord), setup[key], atol=1e-9, rtol=0):
                raise ValueError('controller coordinates differ from calibration: '+key)
            setattr(robot.arm, attr, list(coord))
        arm = ElfinExperimentArm(robot, setup, transport_timeout_s=.5, clock_ns=clock.now_ns)
        pose_sampler = None
        if args.record_actual_tcp:
            from huayan_robot.vendor import CPSClient
            from brushbot.backends.huayan import HuayanBackend
            pose_client = CPSClient(args.ip)
            pose_client.tcp.settimeout(.5)
            pose_backend = HuayanBackend(pose_client, servo_dt=.02)
            pose_sampler = TCPPoseSampler(
                lambda: pose_backend.read().tcp_pose, clock_ns=clock.now_ns)
        # Opening the serial port may reset its device. Start the baseline only
        # after opening; do not consume the source from another monitor process.
        source.start()
        engine, hub = build_stack(plan=plan, table=table, setup=setup,
                                  artifacts=artifacts, label=label, root=args.run_root,
                                  arm=arm, source=source, clock=clock,
                                  control_mode=args.control_mode,
                                  feedback_profile=feedback_profile,
                                  experiment_folder=args.experiment_folder,
                                  run_folder_label=args.run_folder_label,
                                  entry_profile=entry_profile,
                                  auto_position=True)
        result = run_recorded(engine, hub, clock=clock,
                              live_output_fn=panel.update,
                              pose_sampler=pose_sampler)
        panel.close()
        _report(result)
        if result.get('pose_capture') is not None:
            capture = result['pose_capture']
            print('实际 TCP 采集: {}/{} 有效，{} 无效；最大读取耗时 {:.1f} ms；{}'.format(
                capture['valid_samples'], capture['samples'],
                capture['invalid_samples'],
                capture['max_read_duration_ms'],
                '已停止' if capture['worker_stopped'] else '线程未停止'))
            if (capture['valid_samples'] < 2 or capture['worker_error']
                    or not capture['worker_stopped']):
                print('实际 TCP 采集不完整；不能据此评价运行阶段位姿。'
                      '详情见 actual_tcp_meta.json。')
        return 0 if result['state'] == 'END_WAIT' else 2
    finally:
        try:
            panel.close()
        finally:
            try:
                source.stop()
            finally:
                try:
                    if pose_client is not None:
                        pose_client.tcp.close()
                finally:
                    try:
                        if robot is not None:
                            robot.client.raw_client.tcp.close()
                    finally:
                        lock.release()


if __name__ == '__main__':
    raise SystemExit(main())
