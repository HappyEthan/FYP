"""Reproduce the fixed-window analysis without hardware or calibration refitting."""
from __future__ import annotations

from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).resolve().parent
ROOT = next(p for p in OUT.parents if (p/'pyproject.toml').is_file())
RAW = OUT.parent.parent/'raw'
BATCH_ROOT = OUT.parents[3]
PACKAGE = ROOT/'runs/brush2/plans/feedforward_calibration_handoff_v2'
ORDER = [('right', 32, 1), ('up', 32, 1), ('right', 28, 1), ('up', 28, 1),
         ('up', 28, 2), ('right', 28, 2), ('up', 32, 2), ('right', 32, 2)]
INPUTS = ('manifest.json', 'validation.json', 'control.jsonl', 'sensor.csv',
          'actual_tcp.csv', 'actual_tcp_meta.json', 'directional_calibration.json',
          'common_reference.json', 'validation_metrics.json', 'setup.json',
          'resolved.json', 'segments.json', 'timeline.npz', 'compiled_plan.npz',
          'settings_source.json', 'motion_metrics.json', 'events.jsonl')


def read_json(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(name, value):
    (OUT/name).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                  allow_nan=False)+'\n')


def median(values):
    return float(np.median(values)) if len(values) else None


def rms(values):
    return float(np.sqrt(np.mean(np.square(values)))) if len(values) else None


def match(a, b):
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, dict):
        return isinstance(b, dict) and set(a) == set(b) and all(match(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return isinstance(b, list) and len(a) == len(b) and all(match(x, y) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and not isinstance(a, bool):
        return math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-9)
    return a == b


def window(rows, target, lo, hi, predicted_raw):
    selected = [r for r in rows if r['phase'] == 'straight_hold' and lo <= r['distance_mm'] <= hi]
    good = [r for r in selected if r['calibration_status'] == 'ok']
    g = target['common_target_uT']
    z = target['command_z_mm']
    bins = []
    for begin in np.arange(lo, hi, 5):
        members = [r for r in selected if begin <= r['distance_mm'] < begin+5]
        valid = [r for r in members if r['calibration_status'] == 'ok']
        cal = median([r['g_cal_uT'] for r in valid])
        bins.append(dict(start_mm=float(begin), total_frames=len(members), valid_frames=len(valid),
                         median_cal_uT=cal, error_uT=None if cal is None else cal-g))
    errors = [r['g_cal_uT']-g for r in good]
    zerrors = [40-r['depth_est_mm']-z for r in good]
    result = dict(total_frames=len(selected), valid_frames=len(good),
        coverage=len(good)/len(selected) if selected else 0.,
        status_counts=dict(Counter(r['calibration_status'] for r in selected)),
        raw_median_uT=median([r['a_control_uT'] for r in selected]),
        calibrated_median_uT=median([r['g_cal_uT'] for r in good]),
        calibrated_rmse_uT_valid_only=rms(errors), z_rmse_mm_valid_only=rms(zerrors),
        bin_rmse_uT_valid_only=rms([b['error_uT'] for b in bins if b['error_uT'] is not None]),
        valid_bins=sum(b['error_uT'] is not None for b in bins), total_bins=len(bins), bins=bins)
    extra = dict(raw_min_uT=min(r['a_control_uT'] for r in selected),
        raw_max_uT=max(r['a_control_uT'] for r in selected),
        raw_target_prediction_uT=predicted_raw,
        raw_median_prediction_error_uT=result['raw_median_uT']-predicted_raw,
        raw_rmse_uT_all=rms([r['a_control_uT']-predicted_raw for r in selected]),
        calibrated_target_bias_uT=None if not good else result['calibrated_median_uT']-g,
        z_error_median_mm=median(zerrors),
        full_valid_bins=sum(b['total_frames'] > 0 and b['valid_frames'] == b['total_frames'] for b in bins),
        bin_coverage=result['valid_bins']/len(bins),
        mean_abs_z_error_mm_valid_only=float(np.mean(np.abs(zerrors))) if good else None)
    detailed = []
    for b in bins:
        members = [r for r in selected if b['start_mm'] <= r['distance_mm'] < b['start_mm']+5]
        valid = [r for r in members if r['calibration_status'] == 'ok']
        detailed.append(dict(b, raw_median_uT=median([r['a_control_uT'] for r in members]),
            valid_fraction=b['valid_frames']/b['total_frames'] if b['total_frames'] else 0.,
            z_error_median_mm=median([r['z_est_mm']-z for r in valid])))
    return result, extra, detailed, selected


def audit_signal(folder, manifest, rows, curve, reference):
    sensors = list(csv.DictReader((folder/'sensor.csv').open()))
    filtered = {}
    max_delta_error = 0.
    for base in manifest['baselines']:
        b0 = np.asarray(base['B0_uT'], float)
        initial = [s for s in sensors if base['first_seq'] <= int(s['seq']) <= base['last_seq'] and s['valid'] == 'true']
        state = None
        for s in initial:
            value = np.array([float(s[k]) for k in ('Bx_uT', 'By_uT', 'Bz_uT')])-b0
            state = value if state is None else .3*value+.7*state
        for s in sensors:
            if s['baseline_id'] != str(base['baseline_id']) or int(s['seq']) <= base['last_seq'] or s['valid'] != 'true':
                continue
            value = np.array([float(s[k]) for k in ('Bx_uT', 'By_uT', 'Bz_uT')])-b0
            logged = np.array([float(s[k]) for k in ('dBx_uT', 'dBy_uT', 'dBz_uT')])
            max_delta_error = max(max_delta_error, float(np.max(np.abs(value-logged))))
            state = .3*value+.7*state
            filtered[int(s['seq'])] = state.copy()
    max_ema_error = max_norm_error = max_cal_error = 0.
    checked = valid_checked = 0
    for r in rows:
        assert r['sample_seq'] == r['calibration_sample_seq']
        estimate = filtered[r['sample_seq']]
        logged = np.array([r['bx_filtered_uT'], r['by_filtered_uT']])
        max_ema_error = max(max_ema_error, float(np.max(np.abs(estimate[:2]-logged))))
        raw = math.hypot(*logged)
        max_norm_error = max(max_norm_error, abs(raw-r['a_control_uT']))
        if r['phase'] != 'straight_hold':
            continue
        checked += 1
        status = 'below_range' if raw < curve['response_nodes_uT'][0] else 'above_range' if raw > curve['response_nodes_uT'][-1] else 'ok'
        assert status == r['calibration_status']
        if status == 'ok':
            depth = float(np.interp(raw, curve['response_nodes_uT'], curve['depth_nodes_mm']))
            cal = float(np.interp(depth, reference['depth_nodes_mm'], reference['calibrated_response_nodes_uT']))
            max_cal_error = max(max_cal_error, abs(cal-r['g_cal_uT']), abs(depth-r['depth_est_mm']),
                                abs(math.hypot(r['bx_cal_uT'], r['by_cal_uT'])-cal))
            assert np.allclose([r['bx_cal_uT'], r['by_cal_uT']], logged*cal/raw)
            valid_checked += 1
        else:
            assert all(r[k] is None for k in ('g_cal_uT', 'depth_est_mm', 'z_est_mm', 'bx_cal_uT', 'by_cal_uT'))
    assert max(max_delta_error, max_ema_error, max_norm_error, max_cal_error) < 1e-8
    assert all(r['depth_fb_m'] == 0 for r in rows)
    assert all(r['a_ref_uT'] is None and r['e_center_uT'] is None for r in rows)
    return dict(baseline_delta_max_abs_error_uT=max_delta_error,
        ema_vector_max_abs_error_uT=max_ema_error, raw_norm_max_abs_error_uT=max_norm_error,
        calibration_max_abs_error=max_cal_error, checked_control_frames=len(rows),
        checked_straight_frames=checked, checked_valid_straight_frames=valid_checked,
        source_samples=len(sensors), invalid_source_samples=sum(s['valid'] != 'true' for s in sensors),
        feedback_zero=True, raw_target_fields_null=True,
        note='Independent numerical replay checks implementation consistency, not physical validity.')


def tcp_metrics(folder, selected, target):
    poses = [r for r in csv.DictReader((folder/'actual_tcp.csv').open()) if r['valid'] == 'true']
    poses = [r for r in poses if selected[0]['host_ns'] <= (int(r['request_start_ns'])+int(r['request_end_ns']))/2 <= selected[-1]['host_ns']]
    xyz = np.array([[float(r[k]) for k in ('x_m', 'y_m', 'z_m')] for r in poses])*1000
    timestamps = np.array([(int(r['request_start_ns'])+int(r['request_end_ns']))/2 for r in poses])/1e9
    speed = np.linalg.norm(np.diff(xyz[:, :2], axis=0), axis=1)/np.diff(timestamps)
    cmd_rpy = np.array([selected[0][k] for k in ('rx_cmd_rad', 'ry_cmd_rad', 'rz_cmd_rad')])
    rpy = np.array([[float(r[k]) for k in ('rx_rad', 'ry_rad', 'rz_rad')] for r in poses])
    deviation = np.rad2deg((rpy-cmd_rpy+np.pi) % (2*np.pi)-np.pi)
    zerr = xyz[:, 2]-target['command_z_mm']
    return dict(samples=len(poses), z_min_mm=float(xyz[:, 2].min()), z_median_mm=median(xyz[:, 2]),
        z_max_mm=float(xyz[:, 2].max()), z_command_rmse_mm=rms(zerr),
        z_command_max_abs_error_mm=float(np.max(np.abs(zerr))), xy_speed_median_mm_s=median(speed),
        rpy_command_max_abs_component_error_deg=float(np.max(np.abs(deviation))),
        note='Independent 10 Hz TCP samples use request midpoint within command-defined window; not magnetic Z estimates.')


def write_csv(name, rows):
    with (OUT/name).open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    snapshot_hashes = {name: sha(PACKAGE/name) for name in ('directional_calibration.json', 'common_reference.json')}
    source_hashes = {}
    found = {}
    for path in RAW.glob('*/manifest.json'):
        manifest = read_json(path)
        if manifest['status'] != 'completed':
            continue
        target = read_json(path.parent/'validation.json')
        key = target['direction'], int(target['command_z_mm']), target['repeat']
        assert key not in found, f'duplicate completed condition: {key}'
        found[key] = path.parent
    assert set(found) == set(ORDER), 'completed matrix differs from frozen eight-trial protocol'
    runs = []
    plot_data = []
    for number, key in enumerate(ORDER, 1):
        folder = found[key]
        manifest, target = read_json(folder/'manifest.json'), read_json(folder/'validation.json')
        model, reference = read_json(folder/'directional_calibration.json'), read_json(folder/'common_reference.json')
        for name, expected in snapshot_hashes.items():
            assert sha(folder/name) == expected
            assert manifest['sha256'][name] == expected
        for name in INPUTS:
            source_hashes[str((folder/name).relative_to(ROOT))] = sha(folder/name)
        for name, expected in manifest['sha256'].items():
            assert sha(folder/name) == expected
        rows = [json.loads(line) for line in (folder/'control.jsonl').read_text().splitlines()]
        curve = model['direction_curves'][target['direction']]
        nominal_depth = 40-target['command_z_mm']
        assert math.isclose(float(np.interp(target['common_target_uT'], reference['calibrated_response_nodes_uT'], reference['depth_nodes_mm'])), nominal_depth)
        predicted_raw = float(np.interp(nominal_depth, curve['depth_nodes_mm'], curve['response_nodes_uT']))
        calculated = {}
        for name, bounds in [('primary', (30, 120)), ('sensitivity', (50, 100))]:
            original, extra, detailed, selected = window(rows, target, *bounds, predicted_raw)
            assert match(original, read_json(folder/'validation_metrics.json')[name]), f'online metric mismatch: {target["trial_id"]}/{name}'
            calculated[name] = dict(original, **extra, detailed_bins=detailed,
                                    actual_tcp=tcp_metrics(folder, selected, target))
        audit = audit_signal(folder, manifest, rows, curve, reference)
        run = dict(plan_number=number, trial_id=target['trial_id'], run_id=manifest['run_id'],
            folder=str(folder.relative_to(ROOT)), target=target, status=manifest['status'],
            primary=calculated['primary'], sensitivity=calculated['sensitivity'], audit=audit,
            baseline=manifest['baselines'][-1], source_response_range_uT=[curve['response_nodes_uT'][0], curve['response_nodes_uT'][-1]])
        runs.append(run)
        plot_data.append((run, rows))
    batches = []
    missing_attempts = []
    for path in sorted(BATCH_ROOT.glob('batch_*.json')):
        b = read_json(path)
        source_hashes[str(path.relative_to(ROOT))] = sha(path)
        batches.append(dict(path=str(path.relative_to(ROOT)), batch_id=b['batch_id'], status=b['status'],
                            start_trial=b.get('selected_start_trial'), reason=b.get('reason'),
                            recorded=[{k:x[k] for k in ('trial_id', 'run_id', 'state')} for x in b.get('completed', [])]))
        for x in b.get('completed', []):
            if not Path(x['run_dir']).exists():
                missing_attempts.append(dict(trial_id=x['trial_id'], run_id=x['run_id'], state=x['state'],
                    batch=str(path.relative_to(ROOT)), missing_path=x['run_dir'], reason_available=False))
    comparisons = []
    for z in (32, 28):
        by_direction = {}
        for direction in ('right', 'up'):
            current = [r for r in runs if r['target']['command_z_mm'] == z and r['target']['direction'] == direction]
            raw_medians = [r['primary']['raw_median_uT'] for r in current]
            cal_medians = [r['primary']['calibrated_median_uT'] for r in current]
            complete_cal = all(x is not None for x in cal_medians)
            by_direction[direction] = dict(raw_representative_uT=float(np.mean(raw_medians)),
                raw_repeat_difference_uT=abs(raw_medians[0]-raw_medians[1]),
                calibrated_representative_uT=float(np.mean(cal_medians)) if complete_cal else None,
                calibrated_repeat_difference_uT=abs(cal_medians[0]-cal_medians[1]) if complete_cal else None,
                coverages=[r['primary']['coverage'] for r in current],
                note='Calibrated representatives may be conditional on partial coverage; missing repeats are not imputed.')
        right, up = by_direction['right'], by_direction['up']
        difference = None if right['calibrated_representative_uT'] is None or up['calibrated_representative_uT'] is None else right['calibrated_representative_uT']-up['calibrated_representative_uT']
        comparisons.append(dict(command_z_mm=z, target_uT=next(r['target']['common_target_uT'] for r in runs if r['target']['command_z_mm']==z),
                                directions=by_direction, calibrated_right_minus_up_uT=difference))
    aggregate = {}
    for name in ('primary', 'sensitivity'):
        windows = [r[name] for r in runs]
        supported = [w for w in windows if w['valid_frames']]
        total, valid = sum(w['total_frames'] for w in windows), sum(w['valid_frames'] for w in windows)
        counts = Counter()
        for w in windows:
            counts.update(w['status_counts'])
        aggregate[name] = dict(total_frames=total, valid_frames=valid, frame_coverage=valid/total,
            equal_run_mean_coverage=float(np.mean([w['coverage'] for w in windows])),
            status_counts=dict(counts), valid_bins=sum(w['valid_bins'] for w in windows),
            total_bins=sum(w['total_bins'] for w in windows),
            full_valid_bins=sum(w['full_valid_bins'] for w in windows),
            runs_with_estimates=len(supported), fully_supported_runs=sum(w['coverage']==1 for w in windows),
            equal_run_cal_rmse_uT_valid_only=rms([w['calibrated_rmse_uT_valid_only'] for w in supported]),
            equal_run_bin_rmse_uT_valid_only=rms([w['bin_rmse_uT_valid_only'] for w in supported]),
            equal_run_z_rmse_mm_valid_only=rms([w['z_rmse_mm_valid_only'] for w in supported]),
            note='Error summaries give equal weight to supported runs only; no all-eight-run accuracy is available.')
    summary = dict(role='independent_fixed_protocol_analysis_not_refit', date='2026-10-08',
        analysis_script_sha256=sha(Path(__file__)),
        windows_mm={'primary':[30,120], 'sensitivity':[50,100]}, model_hashes=snapshot_hashes,
        completed_conditions=8, runs=runs, comparisons=comparisons, aggregate=aggregate,
        batches=batches, missing_raw_attempts=missing_attempts,
        conclusion='Frozen calibration did not produce consistent, repeatable common features in this experiment. Implementation replay and actual command Z checks pass; physical calibration validity does not follow.',
        limitations=['Only +X/+Y, 10 mm/s, two repeats per condition.',
                     'Retries and pauses changed elapsed acquisition order.',
                     'Three aborted raw directories are missing; batch entries remain.',
                     'Partial valid subsets bias representative values; never clip or extrapolate.',
                     'A/B share the same data; no new fit or independent C stroke evidence.'])
    dump('summary.json', summary)
    dump('source_hashes.json', source_hashes)
    dump('selection.json', [dict(plan_number=r['plan_number'], trial_id=r['trial_id'], run_id=r['run_id'], folder=r['folder']) for r in runs])
    per_run = []
    per_bin = []
    for r in runs:
        for name in ('primary', 'sensitivity'):
            w = r[name]
            per_run.append(dict(trial_id=r['trial_id'], run_id=r['run_id'], window=name,
                command_z_mm=r['target']['command_z_mm'], target_uT=r['target']['common_target_uT'],
                **{k:w[k] for k in ('total_frames','valid_frames','coverage','raw_median_uT',
                    'calibrated_median_uT','calibrated_target_bias_uT','bin_rmse_uT_valid_only',
                    'z_rmse_mm_valid_only','valid_bins','full_valid_bins','raw_target_prediction_uT')},
                actual_z_median_mm=w['actual_tcp']['z_median_mm'], actual_z_rmse_mm=w['actual_tcp']['z_command_rmse_mm']))
            for b in w['detailed_bins']:
                per_bin.append(dict(trial_id=r['trial_id'], window=name, **b))
    write_csv('per_run_metrics.csv', per_run)
    write_csv('bin_metrics.csv', per_bin)
    plot(plot_data)
    assert all(sha(ROOT/name) == value for name,value in source_hashes.items()), 'raw input changed during analysis'
    print(json.dumps(dict(completed_conditions=8, aggregate=aggregate, comparisons=comparisons,
        missing_raw_attempts=len(missing_attempts), max_actual_z_error_mm=max(r['primary']['actual_tcp']['z_command_max_abs_error_mm'] for r in runs),
        max_ema_replay_error_uT=max(r['audit']['ema_vector_max_abs_error_uT'] for r in runs)),ensure_ascii=False,indent=2))


def plot(data):
    plt.rcParams.update({'font.family':'Microsoft YaHei', 'axes.unicode_minus':False,
                         'font.size':10, 'axes.spines.top':False, 'axes.spines.right':False})
    groups = [('right',32),('up',32),('right',28),('up',28)]
    colors = {1:'#2468a0',2:'#cf6c21'}
    for kind, filename, title, ylabel in (
        ('raw','raw_response.png','原始响应与冻结模型预测','原始滤波幅值 / µT'),
        ('cal','calibrated_response.png','统一校准响应与公共目标','校准等效幅值 / µT'),
        ('z','estimated_z_error.png','磁反查高度误差与实际 TCP 高度误差','Z估计 − Z命令 / mm')):
        fig, axes = plt.subplots(2,2,figsize=(12,8),sharex=True,layout='constrained')
        for ax,(direction,z) in zip(axes.flat,groups):
            selected = [(r,rows) for r,rows in data if r['target']['direction']==direction and r['target']['command_z_mm']==z]
            for r,rows in selected:
                w = r['primary']; bins=w['detailed_bins']; x=[b['start_mm']+2.5 for b in bins]
                field = 'raw_median_uT' if kind=='raw' else 'median_cal_uT' if kind=='cal' else 'z_error_median_mm'
                y = [np.nan if b[field] is None else b[field] for b in bins]
                label=f"R{r['target']['repeat']}  有效帧 {w['coverage']:.1%}"
                ax.plot(x,y,'o-',color=colors[r['target']['repeat']],label=label,markersize=4)
                if kind in ('cal','z'):
                    partial = [(px,py) for px,py,b in zip(x,y,bins) if 0 < b['valid_fraction'] < 1]
                    if partial:
                        ax.scatter(*zip(*partial),facecolors='white',edgecolors=colors[r['target']['repeat']],s=24,zorder=5)
                if kind=='z':
                    actual = w['actual_tcp']['z_median_mm']-z
                    ax.axhline(actual,color=colors[r['target']['repeat']],linestyle=':',alpha=.75,
                               label=f"R{r['target']['repeat']} 实际TCP中位误差")
            r=selected[0][0]
            target = r['primary']['raw_target_prediction_uT'] if kind=='raw' else r['target']['common_target_uT'] if kind=='cal' else 0.
            ax.axhline(target,color='#254831',linestyle='--',label='冻结预测' if kind=='raw' else '公共目标' if kind=='cal' else '零误差')
            if kind=='raw':
                ax.axhspan(*r['source_response_range_uT'],color='#72927e',alpha=.1,label='严格反查幅值范围')
                ax.axhline(r['source_response_range_uT'][1],color='#72927e',linewidth=.7)
            if kind=='z':
                ax.axhspan(-1,1,color='#72927e',alpha=.1,label='暂定 ±1 mm 工程参考')
            if kind in ('cal','z') and direction=='right' and z==28:
                ax.text(.48,.15,'R2 全窗口越界\n未绘制校准估计',transform=ax.transAxes,va='top',fontsize=9,color='#9e4a12')
            ax.set_title(f"{' +X' if direction=='right' else '+Y'}  Z{z}")
            ax.set_ylabel(ylabel); ax.set_xlabel('命令沿程 / mm'); ax.set_xlim(30,120)
            ax.grid(alpha=.18); ax.legend(fontsize=8,loc='best')
        # Identical limits within each height make the directional comparison readable.
        for row in axes:
            low=min(ax.get_ylim()[0] for ax in row)
            high=max(ax.get_ylim()[1] for ax in row)
            for ax in row:
                ax.set_ylim(low,high)
        fig.suptitle(title,fontsize=15)
        fig.savefig(OUT/filename,dpi=170)
        plt.close(fig)


if __name__ == '__main__':
    main()
