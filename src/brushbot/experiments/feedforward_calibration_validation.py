"""Shared-reference validation; measurement inference never accepts command Z."""
from __future__ import annotations

from collections import Counter
import copy
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from brushbot.experiments.acquisition import SampleHub
from brushbot.experiments.cartesian_return import build_return_route
from brushbot.experiments.engine import height_deadline_policy
from brushbot.experiments.four_direction_sweep import FourDirectionSweepEngine, compile_sweep
from brushbot.experiments.z_identification import DT, _check_trajectory, _ease
from brushbot.strokeplan import Stroke, StrokePlan

COMMON_WAIT = np.array([-.15, .5, .07, 0., math.radians(15), 0.])


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    temporary.replace(path)


def nodes(depth, response):
    x, y = np.asarray(depth, float), np.asarray(response, float)
    if (x.ndim != 1 or y.shape != x.shape or len(x) < 2
            or not np.isfinite(x).all() or not np.isfinite(y).all()
            or np.any(np.diff(x) <= 0) or np.any(np.diff(y) <= 0)
            or x[0] <= 0 or y[0] <= 0):
        raise ValueError('calibration nodes must be finite, positive and strictly monotone')
    return x, y


def strict_interp(value, x, y):
    if not math.isfinite(value) or not x[0] <= value <= x[-1]:
        raise ValueError('value outside calibrated range')
    return float(np.interp(value, x, y))


class DirectionalCalibration:
    def __init__(self, model, reference):
        self.model, self.reference = copy.deepcopy(model), copy.deepcopy(reference)
        self.depths, self.common = nodes(reference['depth_nodes_mm'], reference['calibrated_response_nodes_uT'])
        if not reference.get('reference_id'):
            raise ValueError('reference identifier missing')
        self.curves = {}
        for direction in ('right', 'up', 'left', 'down'):
            curve = model['direction_curves'][direction]
            x, y = nodes(curve['depth_nodes_mm'], curve['response_nodes_uT'])
            if not np.array_equal(x, self.depths):
                raise ValueError('direction depths differ from reference')
            self.curves[direction] = y
        if not np.allclose(np.mean(list(self.curves.values()), axis=0), self.common, rtol=1e-12, atol=1e-12):
            raise ValueError('common reference is not the equal-direction mean')
        self.model_bytes = self.reference_bytes = None
        self.model_sha256 = self.reference_sha256 = None

    def forward(self, depth):
        return strict_interp(float(depth), self.depths, self.common)

    def inverse(self, target):
        return strict_interp(float(target), self.common, self.depths)

    def normalize(self, bx, by, direction, phase):
        out = dict(calibration_status=None, depth_est_mm=None, z_est_mm=None,
                   bx_cal_uT=None, by_cal_uT=None, g_cal_uT=None, g_control_uT=None,
                   x_noise_scale=bool(math.isfinite(bx) and abs(bx) <= 20),
                   common_reference_id=self.reference['reference_id'])
        if not math.isfinite(bx) or not math.isfinite(by):
            out['calibration_status'] = 'non_finite'
        elif direction not in self.curves:
            out['calibration_status'] = 'unknown_direction'
        elif phase in {'hold', 'post_lift_hold', 'baseline_settle'} or phase.startswith('return_origin'):
            out.update(calibration_status='no_contact', g_control_uT=0.)
        elif phase != 'straight_hold':
            out['calibration_status'] = 'transient'
        else:
            r = math.hypot(bx, by)
            curve = self.curves[direction]
            if r == 0:
                out['calibration_status'] = 'zero_amplitude'
            elif r < curve[0]:
                out['calibration_status'] = 'below_range'
            elif r > curve[-1]:
                out['calibration_status'] = 'above_range'
            else:
                depth = strict_interp(r, curve, self.depths)
                q = self.forward(depth)
                scale = q/r
                out.update(calibration_status='ok', depth_est_mm=depth, z_est_mm=40-depth,
                           bx_cal_uT=scale*bx, by_cal_uT=scale*by, g_cal_uT=q, g_control_uT=q)
        return out


def load_calibration(model_path, reference_path):
    raw, ref = Path(model_path).read_bytes(), Path(reference_path).read_bytes()
    reference = json.loads(ref)
    sha = hashlib.sha256(raw).hexdigest()
    if reference.get('source_model_sha256') != sha:
        raise ValueError('reference source model hash mismatch')
    cal = DirectionalCalibration(json.loads(raw), reference)
    cal.model_bytes, cal.reference_bytes = raw, ref
    cal.model_sha256, cal.reference_sha256 = sha, hashlib.sha256(ref).hexdigest()
    scope = cal.model['scope']
    if (scope['speed_mm_s'] != 10 or scope['writing_tilt_deg'] != 15
            or scope['travel_mm'] != 150 or scope['command_z_mm'] != [27, 35]
            or cal.model['signal'] != 'control.jsonl:a_control_uT = norm of EMA baseline-subtracted Bxy, alpha 0.3'):
        raise ValueError('model context differs from this validation protocol')
    return cal


def compile_trial(trial, setup):
    profile = trial['profile']
    compiled = compile_sweep(profile, setup)
    poses = list(compiled['pose_m_rad'])
    phases = list(compiled['phase'])
    old = np.asarray(poses[-1])
    route = build_return_route(old, COMMON_WAIT, setup)
    for i, waypoint in enumerate(route):
        target = np.asarray(waypoint)
        delta = target-old
        angle = np.linalg.norm(np.rad2deg(delta[3:]))
        duration = max(DT,
            1.875*np.linalg.norm(delta[:2])*1000/min(profile['transfer_speed_mm_s'], setup['return_speed_mm_s'], setup['max_xy_speed_mm_s']),
            1.875*abs(delta[2])*1000/min(profile['fast_z_speed_mm_s'], setup['max_z_speed_mm_s']),
            math.sqrt(5.774*np.linalg.norm(delta[:3])*1000/min(profile['transit_accel_mm_s2'], setup['max_accel_mm_s2'])),
            1.875*angle/profile['angular_speed_deg_s'],
            math.sqrt(5.774*angle/profile['angular_accel_deg_s2']))
        count = math.ceil(duration/DT)
        values = old+delta*_ease(np.arange(1, count+1)/count)[:, None]
        values = np.vstack([values, np.tile(target, (10, 1))])
        name = f'return_origin_{i}'
        begin = len(poses)
        poses.extend(values)
        phases.extend([name]*len(values))
        compiled['segments'].append(dict(id=name, kind='airborne', start_tick=begin,
                                        end_tick=len(poses), start_t_s=begin*DT, end_t_s=len(poses)*DT))
        old = target
    poses = np.asarray(poses)
    unit = np.array([1, 0] if trial['direction'] == 'right' else [0, 1])
    origin = np.array([setup['origin_x_mm'], setup['origin_y_mm']])/1000
    progress = np.clip(((poses[:, :2]-origin) @ unit)/.15, 0, 1)
    depth = np.maximum(.04-poses[:, 2], 0)
    ref = np.full(len(poses), np.nan)
    compiled.update(pose_m_rad=poses, phase=np.asarray(phases), s=progress,
                    t_s=np.arange(len(poses))*DT, depth_ff_m=depth, g_ref_uT=ref,
                    motion_metrics=_check_trajectory(poses, setup, profile))
    compiled['spec_snapshot'].update(validation=trial_metadata(trial),
        deadline_policy=height_deadline_policy(setup),
        validation_feature='calibrated_dBxy_norm_uT',
        validation_goal='same common target and command height in +X/+Y; no feedback',
        return_origin_pose_m_rad=COMMON_WAIT.tolist())
    compiled['plan'] = StrokePlan([Stroke(s=progress, xy=poses[:, :2], g_press=ref, z_ff=depth)], meta={
        'artifact_role': 'derived_calibration_validation_timeline',
        'depth_source': 'inverse of common calibrated reference, fixed target',
        'stroke_durations_s': [float(compiled['t_s'][-1])]})
    return compiled


def trial_metadata(trial):
    return {k: copy.deepcopy(v) for k, v in trial.items() if k not in {'setup', 'profile'}}


class ValidationHub(SampleHub):
    def latest_control(self, now_ns):
        control = super().latest_control(now_ns)
        self.validation_sample = copy.deepcopy(control)
        return control


class ValidationEngine(FourDirectionSweepEngine):
    def prepare_validation(self, trial, setup, calibration):
        self.prepare_sweep(trial['profile'], setup)
        self._compiled = compile_trial(trial, setup)
        self._spec = copy.deepcopy(self._compiled['spec_snapshot'])
        angles = self._compiled['pose_m_rad'][:, 3:]
        self._angle_min, self._angle_max = angles.min(axis=0), angles.max(axis=0)
        self.trial, self.calibration = trial, calibration
        self._validation_diagnostics = {}
        return self.snapshot()

    def _command_for_tick(self, index, phase, pose, depth_ff, a_control, a_ref):
        sample = self.hub.validation_sample
        bx, by = sample['dB_control_uT'][:2]
        if not math.isclose(math.hypot(bx, by), a_control, rel_tol=1e-12, abs_tol=1e-12):
            raise RuntimeError('calibration sample amplitude mismatch')
        target = self.trial['common_target_uT'] if phase == 'straight_hold' else None
        values = self.calibration.normalize(bx, by, self.trial['direction'], phase)
        error = target-values['g_cal_uT'] if target is not None and values['g_cal_uT'] is not None else None
        unit = np.array([1, 0] if self.trial['direction'] == 'right' else [0, 1])
        origin = np.array([self._setup['origin_x_mm'], self._setup['origin_y_mm']])/1000
        self._validation_diagnostics = dict(values, bx_filtered_uT=bx, by_filtered_uT=by,
            calibration_sample_seq=sample['sample_seq'], direction=self.trial['direction'],
            trial_id=self.trial['trial_id'], g_target_cal_uT=target, e_cal_uT=error,
            distance_mm=float((pose[:2]-origin) @ unit)*1000,
            model_sha256=self.calibration.model_sha256, reference_sha256=self.calibration.reference_sha256)
        return super()._command_for_tick(index, phase, pose, depth_ff, a_control, a_ref)

    def _control_diagnostics(self):
        return self._validation_diagnostics


def summarize_rows(rows, trial):
    def window(lo, hi):
        selected = [r for r in rows if r['phase'] == 'straight_hold' and lo <= r['distance_mm'] <= hi]
        good = [r for r in selected if r['calibration_status'] == 'ok']
        errors = [r['g_cal_uT']-trial['common_target_uT'] for r in good]
        zerrors = [40-r['depth_est_mm']-trial['command_z_mm'] for r in good]
        bins = []
        for begin in np.arange(lo, hi, 5):
            members = [r for r in selected if begin <= r['distance_mm'] < begin+5]
            valid = [r for r in members if r['calibration_status'] == 'ok']
            median = float(np.median([r['g_cal_uT'] for r in valid])) if valid else None
            bins.append(dict(start_mm=float(begin), total_frames=len(members), valid_frames=len(valid),
                             median_cal_uT=median, error_uT=None if median is None else median-trial['common_target_uT']))
        berrors = [b['error_uT'] for b in bins if b['error_uT'] is not None]
        rms = lambda values: float(np.sqrt(np.mean(np.square(values)))) if values else None
        return dict(total_frames=len(selected), valid_frames=len(good), coverage=len(good)/len(selected) if selected else 0.,
                    status_counts=dict(Counter(r['calibration_status'] for r in selected)),
                    raw_median_uT=float(np.median([r['a_control_uT'] for r in selected])) if selected else None,
                    calibrated_median_uT=float(np.median([r['g_cal_uT'] for r in good])) if good else None,
                    calibrated_rmse_uT_valid_only=rms(errors), z_rmse_mm_valid_only=rms(zerrors),
                    bin_rmse_uT_valid_only=rms(berrors), valid_bins=len(berrors), total_bins=len(bins), bins=bins)
    return dict(role='measured_run_metrics_not_pass_certificate', target=trial_metadata(trial),
                primary=window(30, 120), sensitivity=window(50, 100),
                note='Conditional errors require coverage; samples/bins are not independent repeats; 20 uT is not a calibrated pass threshold.')
