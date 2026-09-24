#!/usr/bin/env python3
"""Execute ONE StrokePlan with magnetic recording in the existing runs format.

Default is offline. Hardware requires --execute, approved inputs, and RUN.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
import time

import numpy as np

from brushbot.experiments.acquisition import SampleHub
from brushbot.experiments.adapter import ElfinExperimentArm, RobotResourceLock
from brushbot.experiments.strokeplan_execution import (
    StrokePlanExperimentEngine, compile_recorded_plan, runtime_settings,
)
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
    def _write_snapshots(self, snapshots):
        super()._write_snapshots(snapshots)
        for name, payload in snapshots['strokeplan_inputs'].items():
            if name not in {'strokeplan.npz', 'feedforward.json', 'settings.json'}:
                raise ValueError('unsupported StrokePlan snapshot filename')
            self._save_bytes(name, payload)


def build_stack(*, plan, table, setup, artifacts, label, root, arm, source, clock,
                control_mode='feedforward', feedback_profile=None):
    # Bind immutable, already-loaded input bytes to this run (no later file reread).
    captured = dict(artifacts)

    def record(snapshots):
        snapshots = dict(snapshots, strokeplan_inputs=captured, calibration=table)
        snapshots['experiment'] = dict(snapshots['experiment'], inputs={
            name: {'sha256': hashlib.sha256(payload).hexdigest()}
            for name, payload in captured.items()})
        return StrokePlanRecorder(root, snapshots)

    hub = SampleHub(source, clock.now_ns,
                    abort_on_invalid_running_sample=control_mode == 'p')
    engine = StrokePlanExperimentEngine(arm, hub, record, clock, dt_s=.02)
    engine.prepare_target(plan, table, setup, label=label,
                          control_mode=control_mode,
                          feedback_profile=feedback_profile)
    return engine, hub


def run_recorded(engine, hub, *, clock, sleep=time.sleep, live_output_fn=None):
    """Run once; even acquisition failures and Ctrl+C must finalize the run."""
    try:
        engine.start(require_wait_position=True)
        print('run 目录:', engine.run_dir)
        _drive_recorded(engine, hub, clock=clock, sleep=sleep,
                        live_output_fn=live_output_fn)
    except KeyboardInterrupt:
        engine.fail('operator_stop')
    except Exception as exc:
        if engine.run_id is None:
            raise
        engine.fail(f'driver_fault: {type(exc).__name__}: {exc}')
    finally:
        engine.finalize_pending_recording()
    return engine.snapshot()


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
            _pace(clock, started, tick, .02, sleep)
        except KeyboardInterrupt:
            if interrupted:
                engine.fail('operator_stop_during_abort')
            else:
                interrupted = True
                engine.request_stop('operator_stop')
                engine.step()
        except Exception as exc:
            if (engine.state == 'RUN' and engine._spec['control'].get('mode') == 'p'
                    and hub.fault == 'source_disconnected'):
                engine.request_stop('source_disconnected')
                engine.step()
            else:
                engine.fail(hub.fault or f'driver_fault: {type(exc).__name__}: {exc}')


def main(argv=None, *, feedback_profile=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan', type=Path)
    parser.add_argument('--feedforward', type=Path, required=True)
    parser.add_argument('--settings', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--execute', action='store_true')
    mode.add_argument('--dry-run', action='store_true')
    parser.add_argument('--serial-port', default='/dev/ttyACM0')
    parser.add_argument('--baud', type=int, default=115200)
    parser.add_argument('--ip', default='192.168.0.10')
    parser.add_argument('--run-root', type=Path, default=ROOT/'runs'/'brush2')
    parser.add_argument('--run-label')
    parser.add_argument('--control-mode', choices=('feedforward', 'p'),
                        default='feedforward',
                        help='explicitly select bounded P feedback; default is pure feedforward')
    args = parser.parse_args(argv)
    try:
        artifacts = {'strokeplan.npz': args.plan.read_bytes(),
                     'feedforward.json': args.feedforward.read_bytes(),
                     'settings.json': args.settings.read_bytes()}
        plan = StrokePlan.load(io.BytesIO(artifacts['strokeplan.npz']))
        table = json.loads(artifacts['feedforward.json'])
        setup = json.loads(artifacts['settings.json'])
        label = args.run_label or 'strokeplan_'+args.plan.stem
        compiled = compile_recorded_plan(plan, table, setup, label=label,
                                         control_mode=args.control_mode,
                                         feedback_profile=feedback_profile)
        if args.execute:
            require_execution_approval(table, setup)
            runtime_settings(setup, hardware=True)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    poses = compiled['pose_m_rad']
    if args.control_mode == 'p':
        profile = compiled['spec_snapshot']['control']
        print('单条 StrokePlan；measure_00 低增益 P 反馈（kp={:g}, ki=0）；其余阶段纯前馈。'.format(profile['kp']))
        print('反馈深度限幅 ±{:g} mm；修正速度 {:g} mm/s、加速度 {:g} mm/s²。'.format(
            profile['max_correction_mm'], profile['max_correction_speed_mm_s'],
            profile['max_correction_accel_mm_s2']))
    else:
        print('单条 StrokePlan；纯前馈；运行时同步记录磁数据（无反馈修正）。')
    print('Wait XYZ [mm], RPY [deg]:', poses[0, :3]*1000, np.rad2deg(poses[0, 3:]))
    print('Z range [mm]:', poses[:, 2].min()*1000, poses[:, 2].max()*1000)
    print('轨迹时长 {:.2f} s；另需启动基线采集。'.format(compiled['t_s'][-1]))
    print('前馈表:', args.feedforward)
    print('现场设置:', args.settings)
    print('传感器串口:', args.serial_port)
    print('输出父目录:', args.run_root)
    if not args.execute:
        print('离线预检通过；未连接硬件，未创建实验 run。')
        return 0
    if input('确认已手动沾水、处于上述等待位姿、路径净空足够；输入 RUN: ').strip() != 'RUN':
        return 0

    sys.path.insert(0, str(ADAPTER_ROOT))
    from huayan_robot import HuayanRobot
    clock = MonotonicClock()
    source = SerialSource(args.serial_port, args.baud)
    lock = RobotResourceLock(Path('/tmp/brushbot-feedforward.lock'), args.ip)
    panel = LiveStatusPanel(sys.stdout)
    robot = None
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
        # Opening the serial port may reset its device. Start the baseline only
        # after opening; do not consume the source from another monitor process.
        source.start()
        engine, hub = build_stack(plan=plan, table=table, setup=setup,
                                  artifacts=artifacts, label=label, root=args.run_root,
                                  arm=arm, source=source, clock=clock,
                                  control_mode=args.control_mode,
                                  feedback_profile=feedback_profile)
        result = run_recorded(engine, hub, clock=clock, live_output_fn=panel.update)
        panel.close()
        _report(result)
        return 0 if result['state'] == 'END_WAIT' else 2
    finally:
        try:
            panel.close()
        finally:
            try:
                source.stop()
            finally:
                try:
                    if robot is not None:
                        robot.client.raw_client.tcp.close()
                finally:
                    lock.release()


if __name__ == '__main__':
    raise SystemExit(main())
