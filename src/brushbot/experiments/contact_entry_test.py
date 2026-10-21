"""Independent rotational contact experiment; normal writing entry stays separate."""
from __future__ import annotations

import copy
import math
from collections import defaultdict

import numpy as np

from brushbot.experiments.acquisition import SampleHub
from brushbot.experiments.engine import height_deadline_policy
from brushbot.experiments.four_direction_sweep import DIRECTIONS, FourDirectionSweepEngine, compile_sweep
from brushbot.experiments.z_identification import DT, _check_trajectory, _ease, _ticks
from brushbot.strokeplan import Stroke, StrokePlan

LEGACY_ENTRY_POLICY = 'preload30_then_rotate_and_press_v1'
ENTRY_POLICY = 'preload_then_rotate_and_press_v2'


def compile_contact_test(profile, settings, entry):
    p, entry = copy.deepcopy(profile), copy.deepcopy(entry)
    if set(entry) != {'rotate_start_z_mm', 'preload_speed_mm_s'}:
        raise ValueError('contact entry fields differ from contract')
    for key, value in entry.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(key+' must be finite numeric')
    if p['mode'] != 'four-direction-hold' or p['start_z_mm'] != p['end_z_mm']:
        raise ValueError('contact test requires constant work Z')
    if not p['start_z_mm'] < entry['rotate_start_z_mm'] <= p['entry_contact_z_mm']:
        raise ValueError('require target Z < rotation start Z <= initial contact Z')
    if not 0 < entry['preload_speed_mm_s'] <= p['slow_z_speed_mm_s']:
        raise ValueError('preload speed must be positive and <= near-paper speed')
    count = _ticks(p['rotate_s'])
    # Reuse the verified airborne entry, baseline, sliding, lift and return.
    # Only this experiment replaces the old contact-rotation/loading interval.
    c = compile_sweep(p, settings)
    old, phases = c['pose_m_rad'], c['phase']
    begin = int(np.flatnonzero(phases == 'rotate_contact')[0])
    end = int(np.flatnonzero(phases == 'load_start')[-1])+1
    before = old[begin-1].copy()
    at_start = before.copy()
    at_start[2] = entry['rotate_start_z_mm']/1000
    chunks, names = [], []
    if entry['rotate_start_z_mm'] < p['entry_contact_z_mm']:
        span = (before[2]-at_start[2])*1000
        seconds = max(DT, 1.875*span/entry['preload_speed_mm_s'],
                      math.sqrt(5.774*span/min(p['transit_accel_mm_s2'], c['setup_snapshot']['max_accel_mm_s2'])))
        n = _ticks(math.ceil(seconds/DT)*DT)
        chunks.append(before+(at_start-before)*_ease(np.arange(1,n+1)/n)[:,None])
        names.extend(['entry_preload']*n)
    workpoint = old[end-1]
    chunks.append(at_start+(workpoint-at_start)*_ease(np.arange(1,count+1)/count)[:,None])
    names.extend(['rotate_load']*count)
    poses = np.vstack([old[:begin], *chunks, old[end:]])
    phases = np.asarray([*phases[:begin], *names, *phases[end:]])
    # The endpoint is shared with the original constant-Z slide; no later load.
    setup = c['setup_snapshot']
    unit = np.asarray(DIRECTIONS[p['direction']])
    origin = np.array([setup['origin_x_mm'],setup['origin_y_mm']])/1000
    progress = np.clip(((poses[:,:2]-origin) @ unit)/(p['travel_mm']/1000),0,1)
    depth = np.maximum(setup['contact_z_mm']/1000-poses[:,2],0)
    ref = np.full(len(poses),np.nan)
    segments = []
    starts = np.r_[0, np.flatnonzero(phases[1:] != phases[:-1])+1]
    ends = np.r_[starts[1:], len(phases)]
    for start, stop in zip(starts,ends):
        name = str(phases[start])
        kind = ('straight' if name == 'straight_hold' else 'airborne' if name in {
            'wait','baseline_settle','post_lift_hold','hold','return_high','restore_wait_orientation'} else 'preparation')
        segments.append(dict(id=name,kind=kind,start_tick=int(start),end_tick=int(stop),
                             start_t_s=float(start*DT),end_t_s=float(stop*DT)))
    c.update(pose_m_rad=poses,phase=phases,t_s=np.arange(len(poses))*DT,s=progress,
             depth_ff_m=depth,g_ref_uT=ref,segments=segments,
             motion_metrics=_check_trajectory(poses,setup,p))
    c['spec_snapshot'].update(name='contact_entry_test',entry_policy=ENTRY_POLICY,
        deadline_policy=height_deadline_policy(setup),
        contact_test=dict(entry,rotate_s=p['rotate_s'],target_z_mm=p['start_z_mm'],
                          entry_tilt_deg=p['entry_tilt_deg'],writing_tilt_deg=p['writing_tilt_deg'],
                          entry_reverse_mm=p['entry_reverse_mm'],legacy_load_s_unused=True))
    c['plan'] = StrokePlan([Stroke(s=progress,xy=poses[:,:2],g_press=ref,z_ff=depth)],meta={
        'artifact_role':'derived_contact_entry_test_timeline','entry_policy':ENTRY_POLICY,
        'depth_source':'prescribed TCP Z, no calibration lookup',
        'stroke_durations_s':[float(c['t_s'][-1])]})
    return c


class ContactHub(SampleHub):
    def latest_control(self, now_ns):
        control = super().latest_control(now_ns)
        self.contact_sample = control
        return control


class ContactTestEngine(FourDirectionSweepEngine):
    def prepare_contact(self, profile, setup, entry, trial):
        if self.state not in {'UNPREPARED','READY'}:
            raise RuntimeError('cannot prepare during a run')
        self._compiled = compile_contact_test(profile,setup,entry)
        self._compiled['spec_snapshot']['contact_trial'] = copy.deepcopy(trial)
        self._setup = copy.deepcopy(self._compiled['setup_snapshot'])
        self._spec = copy.deepcopy(self._compiled['spec_snapshot'])
        angles = self._compiled['pose_m_rad'][:,3:]
        self._angle_min,self._angle_max = angles.min(axis=0),angles.max(axis=0)
        self.feedback = None
        self._contact_diagnostics = {}
        self._telemetry = None
        self.state,self.phase,self.last_error = 'READY','ready',''
        return self.snapshot()

    def _command_for_tick(self,index,phase,pose,depth_ff,a_control,a_ref):
        sample = self.hub.contact_sample
        bx,by,bz = sample['dB_control_uT']
        if not math.isclose(math.hypot(bx,by),a_control,rel_tol=1e-12,abs_tol=1e-12):
            raise RuntimeError('contact sample amplitude mismatch')
        direction = self._spec['identification']['direction']
        origin = np.array([self._setup['origin_x_mm'],self._setup['origin_y_mm']])/1000
        self._contact_diagnostics = dict(bx_filtered_uT=bx,by_filtered_uT=by,bz_filtered_uT=bz,
            vector_sample_seq=sample['sample_seq'],direction=direction,
            trial_id=self._spec['contact_trial']['trial_id'],entry_policy=ENTRY_POLICY,
            distance_mm=float((pose[:2]-origin) @ np.asarray(DIRECTIONS[direction]))*1000)
        return super()._command_for_tick(index,phase,pose,depth_ff,a_control,a_ref)

    def _control_diagnostics(self):
        return self._contact_diagnostics


def summarize_rows(rows,trial,*,status):
    def stats(selected):
        values = np.array([r['a_control_uT'] for r in selected])
        center = float(np.median(values)) if len(values) else None
        return dict(frames=len(selected),raw_median_uT=center,
            raw_min_uT=float(values.min()) if len(values) else None,
            raw_max_uT=float(values.max()) if len(values) else None,
            raw_rmse_about_own_median_uT=float(np.sqrt(np.mean((values-center)**2))) if len(values) else None,
            bx_median_uT=float(np.median([r['bx_filtered_uT'] for r in selected])) if selected else None,
            by_median_uT=float(np.median([r['by_filtered_uT'] for r in selected])) if selected else None)
    by_phase = {}
    for name in dict.fromkeys(r['phase'] for r in rows):
        selected = [r for r in rows if r['phase'] == name]
        end = [r for r in selected if r['t_s'] >= selected[-1]['t_s']-.3]
        by_phase[name] = dict(stats(selected),last_0_3s=stats(end))
    lo,hi = .2*trial['travel_mm'],.8*trial['travel_mm']
    selected = [r for r in rows if r['phase'] == 'straight_hold' and lo <= r['distance_mm'] <= hi]
    bins = [dict(start_mm=float(start),end_mm=float(min(start+5,hi)),
                 **stats([r for r in selected if start <= r['distance_mm'] < min(start+5,hi)]))
            for start in np.arange(lo,hi,5)]
    return dict(run_status=status,trial_id=trial['trial_id'],phases=by_phase,
        primary=dict(stats(selected),window_mm=[lo,hi],bins=bins),
        signal='a_control_uT = norm of EMA(B-B0)xy, alpha=0.3; raw_* means unnormalized, not unfiltered',
        interpretation='Raw response consistency only; no force or magnetic-height accuracy claim.')


def summarize_repeats(records):
    groups = defaultdict(list)
    for record in records:
        metrics = record.get('metrics')
        if (not record.get('execution_ok',True) or not metrics
                or metrics['run_status'] != 'completed' or not metrics['primary']['frames']):
            continue
        trial = record['trial']
        groups[trial['condition_sha256']].append(record)
    out = []
    for key,members in groups.items():
        trial = members[0]['trial']
        values = [m['metrics']['primary']['raw_median_uT'] for m in members]
        center = float(np.median(values))
        span = max(values)-min(values) if len(values) >= 2 else None
        out.append(dict(condition_sha256=key,direction=trial['direction'],command_z_mm=trial['command_z_mm'],
            entry_tilt_deg=trial.get('entry_tilt_deg',30.),writing_tilt_deg=trial.get('writing_tilt_deg',15.),
            rotate_start_z_mm=trial['rotate_start_z_mm'],rotate_s=trial['rotate_s'],
            completed_repeats=len(values),per_run_medians_uT=values,
            between_run_range_uT=span,between_run_range_over_median=span/center if span is not None and center else None,
            sufficient_for_repeat_comparison=len(values) >= 2))
    return out
