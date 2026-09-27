"""Adapt one target-only StrokePlan to the existing recorded experiment engine."""
from __future__ import annotations

import copy

import numpy as np

from brushbot.experiments.config import _INSTALLATION_FIELDS, validate_installation
from brushbot.experiments.engine import ExperimentEngine
from brushbot.experiments.strokeplan_feedback import (
    StrokePlanPFeedback, resolve_p_profile,
)
from brushbot.experiments.strokeplan_pi_feedback import StrokePlanPIFeedback, resolve_pi_profile
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
                          feedback_profile=None, entry_profile=None):
    character = entry_profile is not None and entry_profile.get('mode') == 'directional_character'
    if len(plan.strokes) != 1 and not character:
        raise ValueError('recorded execution requires exactly one stroke per invocation')
    if not isinstance(label, str) or not label.strip():
        raise ValueError('run label must be nonempty')
    setup = runtime_settings(setup)
    if control_mode not in {'feedforward', 'p', 'pi'}:
        raise ValueError('control_mode must be feedforward, p or pi')
    if control_mode == 'feedforward' and feedback_profile is not None:
        raise ValueError('feedforward mode cannot accept a feedback profile')
    if control_mode in {'p', 'pi'} and setup['filter'] != {'kind': 'ema', 'alpha': 0.3}:
        raise ValueError('P/PI trial requires the calibrated EMA alpha=0.3 signal')
    profile = (resolve_pi_profile(feedback_profile, setup) if control_mode == 'pi' else
               resolve_p_profile(feedback_profile, setup) if control_mode == 'p' else None)
    if entry_profile is None:
        poses, phases = compile_target_plan(plan, table, setup, dt_s=dt_s)
    else:
        if dt_s != .02:
            raise ValueError('rotational entry requires 20 ms')
        if character:
            from brushbot.experiments.strokeplan_character import compile_character_target
            poses, phases = compile_character_target(plan, table, setup, entry_profile)
        else:
            from brushbot.experiments.strokeplan_entry import compile_rotational_target
            poses, phases = compile_rotational_target(plan, table, setup, entry_profile)
    # Match the existing runner's final 0.2 s Servo hold before stopping.
    poses = np.vstack([poses, np.repeat(poses[-1:], 10, axis=0)])
    phases = np.asarray([*phases, *(['hold'] * 10)])
    g_ref = np.full(len(poses), np.nan)
    progress = np.full(len(poses), np.nan)
    derived_strokes = []
    for i, stroke in enumerate(plan.strokes):
        measure = phases == f'measure_{i:02}'
        ticks, _, target, depth = sample_stroke(stroke, table, dt_s)
        if measure.sum() != len(ticks):
            raise ValueError('compiled measurement timeline differs from target samples')
        g_ref[measure] = target
        progress[measure] = np.interp(ticks, stroke.t, stroke.s)
        derived_strokes.append(Stroke(s=progress[measure].copy(),xy=poses[measure,:2].copy(),
                                      g_press=target.copy(),z_ff=depth.copy()))
    depth_ff = np.maximum(setup['contact_z_mm']/1000. - poses[:, 2], 0.)
    spec = {
        'version': 1, 'name': 'strokeplan', 'run_label': label,
        'path': {'kind': 'strokeplan', 'axis': '+x', 'stroke_count': len(plan.strokes)},
        'control': ({'enabled': False} if control_mode == 'feedforward'
                    else {'enabled': True, 'mode': control_mode, 'phase': 'measure_00',
                          **profile}),
        'calibration_id': table['calibration_id'],
        'wetting': 'manual_before_run', 'baseline_quality_enforced': True,
        'target_format_version': 3,
    }
    if entry_profile is not None:
        spec['entry_profile'] = copy.deepcopy(entry_profile)
        spec['timeline_policy'] = 'sequential_20ms'
        if entry_profile.get('mode') == 'stationary':
            spec['path'].update(axis='xy', assume_direction_invariant=entry_profile['assume_direction_invariant'])
        if character:
            spec['path'].update(axis='xy',assume_pose_invariant=True,dynamic_orientation=True)
            if control_mode != 'feedforward':
                spec['control'].update(phase='per_stroke',measurement_phases=[f'measure_{i:02}' for i in range(len(plan.strokes))])
    derived = CompiledPlan(derived_strokes, meta={
            'artifact_role': 'derived_execution_plan',
            'control_mode': control_mode,
            'stroke_durations_s': [float(st.t[-1]) for st in plan.strokes],
            'calibration_id': table['calibration_id'],
        })
    return dict(plan=derived, t_s=np.arange(len(poses))*dt_s, s=progress,
                phase=phases, pose_m_rad=poses, g_ref_uT=g_ref,
                depth_ff_m=depth_ff, spec_snapshot=spec,
                setup_snapshot=copy.deepcopy(setup))


class StrokePlanExperimentEngine(ExperimentEngine):
    """Reuse baseline, Servo, streaming recording and abort handling unchanged."""

    def _select_run_index(self, elapsed):
        if self._spec.get('timeline_policy') != 'sequential_20ms':
            return super()._select_run_index(elapsed)
        # The compiled path and P limiter both describe a fixed 20 ms command
        # stream. Wall-clock lookup can skip/repeat points under small scheduling
        # jitter, introducing an XY acceleration that P cannot correct in Z.
        # Emit each sample once; the inherited lateness guard still aborts when
        # the next unsent sample is too old. Early/repeated polls send nothing.
        index = 0 if self._telemetry is None else self._last_plan_index + 1
        if elapsed + 1e-9 < self._compiled['t_s'][index]:
            return None
        return index

    def prepare_target(self, plan, table, setup, *, label, control_mode='feedforward',
                       feedback_profile=None, entry_profile=None):
        if self.state not in {'UNPREPARED', 'READY'}:
            raise RuntimeError('cannot prepare while an operation is active')
        compiled = compile_recorded_plan(
            plan, table, setup, label=label, dt_s=self.dt_s,
            control_mode=control_mode, feedback_profile=feedback_profile,
            entry_profile=entry_profile)
        self._compiled = compiled
        self._spec = copy.deepcopy(compiled['spec_snapshot'])
        self._setup = copy.deepcopy(compiled['setup_snapshot'])
        self.state, self.phase, self.last_error = 'READY', 'ready', ''
        self._telemetry = None
        self.feedback = None
        self._measurement_ranges = {}
        for i in range(len(plan.strokes)):
            phase = f'measure_{i:02}'
            indices = np.flatnonzero(compiled['phase'] == phase)
            self._measurement_ranges[phase] = (int(indices[0]),len(indices))
        if control_mode in {'p', 'pi'}:
            feedback_class = StrokePlanPIFeedback if control_mode == 'pi' else StrokePlanPFeedback
            self.feedback = feedback_class(
                table, self._setup, self.dt_s,
                measure_ticks=int(np.count_nonzero(compiled['phase'] == 'measure_00')),
                profile=feedback_profile)
            self._measure_start = int(np.flatnonzero(compiled['phase'] == 'measure_00')[0])
        return self.snapshot()

    def _reset_feedback_state(self, pose):
        if self.feedback is not None:
            self.feedback.reset(pose)

    def _control_diagnostics(self):
        return getattr(self.feedback, 'diagnostics', {})

    def _command_for_tick(self, index, phase, pose, depth_ff, a_control, a_ref):
        if self.feedback is None:
            return super()._command_for_tick(
                index, phase, pose, depth_ff, a_control, a_ref)
        if not np.isfinite(a_control):
            raise RuntimeError('sensor_invalid')
        segment = self._measurement_ranges.get(phase)
        target = a_ref if segment is not None else None
        if segment is not None and not np.isfinite(target):
            raise RuntimeError('sensor_invalid')
        if segment is not None:
            self._measure_start,self.feedback.measure_ticks = segment
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
