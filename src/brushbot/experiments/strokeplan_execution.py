"""Adapt one target-only StrokePlan to the existing recorded experiment engine."""
from __future__ import annotations

import copy

import numpy as np

from brushbot.experiments.config import _INSTALLATION_FIELDS, validate_installation
from brushbot.experiments.engine import ExperimentEngine
from brushbot.experiments.strokeplan_feedback import (
    StrokePlanPFeedback, resolve_p_profile,
)
from brushbot.strokeplan import Stroke, StrokePlan as CompiledPlan
from brushbot.strokeplan_compile import compile_target_plan, sample_stroke


def runtime_settings(settings: dict, *, hardware=False) -> dict:
    """Keep provenance in the input snapshot, validate the actual runtime fields."""
    missing = [key for key in _INSTALLATION_FIELDS if settings.get(key) is None]
    if missing:
        raise ValueError('missing runtime settings: ' + ', '.join(missing))
    return validate_installation(
        {key: settings[key] for key in _INSTALLATION_FIELDS}, hardware=hardware)


def compile_recorded_plan(plan, table: dict, setup: dict, *, label: str,
                          dt_s=.02, control_mode='feedforward',
                          feedback_profile=None):
    if len(plan.strokes) != 1:
        raise ValueError('recorded execution requires exactly one stroke per invocation')
    if not isinstance(label, str) or not label.strip():
        raise ValueError('run label must be nonempty')
    setup = runtime_settings(setup)
    if control_mode not in {'feedforward', 'p'}:
        raise ValueError('control_mode must be feedforward or p')
    if control_mode == 'feedforward' and feedback_profile is not None:
        raise ValueError('feedforward mode cannot accept a feedback profile')
    if control_mode == 'p' and setup['filter'] != {'kind': 'ema', 'alpha': 0.3}:
        raise ValueError('P trial requires the calibrated EMA alpha=0.3 signal')
    profile = resolve_p_profile(feedback_profile, setup) if control_mode == 'p' else None
    poses, phases = compile_target_plan(plan, table, setup, dt_s=dt_s)
    # Match the existing runner's final 0.2 s Servo hold before stopping.
    poses = np.vstack([poses, np.repeat(poses[-1:], 10, axis=0)])
    phases = np.asarray([*phases, *(['hold'] * 10)])
    measure = phases == 'measure_00'
    ticks, _, target, depth = sample_stroke(plan.strokes[0], table, dt_s)
    if measure.sum() != len(ticks):
        raise ValueError('compiled measurement timeline differs from target samples')
    g_ref = np.full(len(poses), np.nan)
    g_ref[measure] = target
    progress = np.full(len(poses), np.nan)
    progress[measure] = np.interp(ticks, plan.strokes[0].t, plan.strokes[0].s)
    depth_ff = np.maximum(setup['contact_z_mm']/1000. - poses[:, 2], 0.)
    spec = {
        'version': 1, 'name': 'strokeplan', 'run_label': label,
        'path': {'kind': 'strokeplan', 'axis': '+x', 'stroke_count': 1},
        'control': ({'enabled': False} if control_mode == 'feedforward'
                    else {'enabled': True, 'mode': 'p', 'phase': 'measure_00',
                          **profile}),
        'calibration_id': table['calibration_id'],
        'wetting': 'manual_before_run', 'baseline_quality_enforced': True,
        'target_format_version': 3,
    }
    derived = CompiledPlan([Stroke(
        s=progress[measure].copy(), xy=poses[measure, :2].copy(),
        g_press=target.copy(), z_ff=depth.copy())], meta={
            'artifact_role': 'derived_execution_plan',
            'control_mode': control_mode,
            'stroke_durations_s': [float(plan.strokes[0].t[-1])],
            'calibration_id': table['calibration_id'],
        })
    return dict(plan=derived, t_s=np.arange(len(poses))*dt_s, s=progress,
                phase=phases, pose_m_rad=poses, g_ref_uT=g_ref,
                depth_ff_m=depth_ff, spec_snapshot=spec,
                setup_snapshot=copy.deepcopy(setup))


class StrokePlanExperimentEngine(ExperimentEngine):
    """Reuse baseline, Servo, streaming recording and abort handling unchanged."""

    def prepare_target(self, plan, table, setup, *, label, control_mode='feedforward',
                       feedback_profile=None):
        if self.state not in {'UNPREPARED', 'READY'}:
            raise RuntimeError('cannot prepare while an operation is active')
        compiled = compile_recorded_plan(
            plan, table, setup, label=label, dt_s=self.dt_s,
            control_mode=control_mode, feedback_profile=feedback_profile)
        self._compiled = compiled
        self._spec = copy.deepcopy(compiled['spec_snapshot'])
        self._setup = copy.deepcopy(compiled['setup_snapshot'])
        self.state, self.phase, self.last_error = 'READY', 'ready', ''
        self._telemetry = None
        self.feedback = None
        if control_mode == 'p':
            self.feedback = StrokePlanPFeedback(
                table, self._setup, self.dt_s,
                measure_ticks=int(np.count_nonzero(compiled['phase'] == 'measure_00')),
                profile=feedback_profile)
            self._measure_start = int(np.flatnonzero(compiled['phase'] == 'measure_00')[0])
        return self.snapshot()

    def _reset_feedback_state(self, pose):
        if self.feedback is not None:
            self.feedback.reset(pose)

    def _command_for_tick(self, index, phase, pose, depth_ff, a_control, a_ref):
        if self.feedback is None:
            return super()._command_for_tick(
                index, phase, pose, depth_ff, a_control, a_ref)
        if not np.isfinite(a_control):
            raise RuntimeError('sensor_invalid')
        target = a_ref if phase == 'measure_00' else None
        if phase == 'measure_00' and not np.isfinite(target):
            raise RuntimeError('sensor_invalid')
        command, correction, limits = self.feedback.command(
            index - self._measure_start if target is not None else -1,
            pose, depth_ff_m=depth_ff, a_ref_uT=target,
            a_control_uT=a_control)
        if target is not None:
            self.feedback_calls += 1
        return command, correction, (None if target is None else target-a_control), limits

    def start(self, *, require_wait_position=True):
        state = self.arm.read_state()
        if not state.get('available') or state.get('fsm') != 33:
            raise RuntimeError('arm must already be in Standby (33)')
        super().start(require_wait_position=require_wait_position)

    def fail(self, reason):
        """Finalize external acquisition/driver failures through the engine."""
        self._fault(str(reason))

    def finalize_pending_recording(self):
        """Cover startup interruption and inherited stop-failure terminal paths."""
        if self._recorder is not None:
            self._fault(self.last_error or 'execution_interrupted')
            self._recorder = None
