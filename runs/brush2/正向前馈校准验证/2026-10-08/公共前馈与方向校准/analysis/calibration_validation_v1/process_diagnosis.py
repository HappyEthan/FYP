"""Compare preparation and sliding responses; read-only with respect to raw runs."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).resolve().parent
ROOT = next(p for p in OUT.parents if (p/'pyproject.toml').is_file())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def median(rows, key):
    return float(np.median([r[key] for r in rows]))


def response(rows):
    return {key: median(rows, key) for key in
            ('a_control_uT', 'bx_filtered_uT', 'by_filtered_uT')}


def main():
    summary = json.loads((OUT/'summary.json').read_text())
    source_hashes = json.loads((OUT/'source_hashes.json').read_text())
    for relative, expected in source_hashes.items():
        assert sha(ROOT/relative) == expected, relative
    result = []
    data = {}
    window_rows = []
    colors = {(32, 1): '#2461a8', (32, 2): '#70a4d6',
              (28, 1): '#d37823', (28, 2): '#9e2346'}
    fig, axes = plt.subplots(2, 2, figsize=(12, 8.2))
    for run in summary['runs']:
        folder = ROOT/run['folder']
        rows = [json.loads(line) for line in (folder/'control.jsonl').read_text().splitlines()]
        direction = run['target']['direction']
        z = int(run['target']['command_z_mm'])
        repeat = run['target']['repeat']
        dominant = 'by_filtered_uT' if direction == 'right' else 'bx_filtered_uT'
        component = 'By' if direction == 'right' else 'Bx'
        load = [r for r in rows if r['phase'] == 'load_start']
        slide = [r for r in rows if r['phase'] == 'straight_hold']
        assert load and slide
        assert abs(load[-1]['z_cmd_m']*1000-z) < 1e-8
        assert all(abs(r['z_cmd_m']*1000-z) < 1e-8 for r in slide)
        assert all(r['depth_fb_m'] == 0 for r in rows)
        end = [r for r in load if r['t_s'] >= load[-1]['t_s']-.3]
        duration = load[-1]['t_s']-load[0]['t_s']+.02
        peak_speed = float(np.max(np.abs(np.diff([r['z_cmd_m']*1000 for r in load]) /
                                             np.diff([r['t_s'] for r in load]))))
        poses = [p for p in csv.DictReader((folder/'actual_tcp.csv').open())
                 if p['valid'] == 'true' and end[0]['host_ns'] <=
                 (int(p['request_start_ns'])+int(p['request_end_ns']))/2 <= end[-1]['host_ns']]
        end_z = [float(p['z_m'])*1000 for p in poses]
        entry = dict(trial_id=run['trial_id'], direction=direction, command_z_mm=z,
            repeat=repeat, dominant_component=component,
            load_duration_s=duration, load_peak_command_z_speed_mm_s=peak_speed,
            load_end_last_0_3s=response(end),
            load_end_actual_tcp_samples=len(poses),
            load_end_actual_z_median_mm=float(np.median(end_z)) if end_z else None,
            load_end_actual_z_max_abs_error_mm=float(np.max(np.abs(np.array(end_z)-z))) if end_z else None,
            primary_raw_median_uT=run['primary']['raw_median_uT'],
            primary_dominant_median_uT=median([r for r in slide if 30 <= r['distance_mm'] <= 120], dominant),
            baseline_dominant_uT=run['baseline']['B0_uT'][1 if direction == 'right' else 0])
        result.append(entry)
        data[direction, z, repeat] = entry
        for phase, selected in [('load_last_0.3s', end)] + [
                (f'slide_{lo}_{hi}mm', [r for r in slide if lo <= r['distance_mm'] < hi])
                for lo, hi in [(0, 5), (5, 10), (10, 20), (20, 30), (30, 60), (60, 90), (90, 120)]]:
            window_rows.append(dict(trial_id=run['trial_id'], window=phase,
                                    frames=len(selected), **response(selected)))
        col = 0 if direction == 'right' else 1
        color = colors[z, repeat]
        style = '-' if repeat == 1 else '--'
        label = f'Z{z} R{repeat}'
        axes[0, col].plot([r['z_cmd_m']*1000 for r in load],
                          [r[dominant] for r in load], style, color=color, label=label, lw=1.6)
        axes[1, col].plot([r['distance_mm'] for r in slide],
                          [r[dominant] for r in slide], style, color=color, label=label, lw=1.4)
    comparisons = []
    for direction in ('right', 'up'):
        for z in (32, 28):
            a, b = data[direction, z, 1], data[direction, z, 2]
            comparisons.append(dict(direction=direction, command_z_mm=z,
                repeat_raw_median_difference_uT=b['primary_raw_median_uT']-a['primary_raw_median_uT'],
                repeat_raw_median_difference_relative_R1=(b['primary_raw_median_uT']/a['primary_raw_median_uT']-1),
                repeat_dominant_median_difference_uT=b['primary_dominant_median_uT']-a['primary_dominant_median_uT'],
                baseline_dominant_difference_uT=b['baseline_dominant_uT']-a['baseline_dominant_uT']))
    up_deep = [ROOT/r['folder'] for r in summary['runs']
               if r['target']['direction'] == 'up' and r['target']['command_z_mm'] == 28]
    with np.load(up_deep[0]/'timeline.npz') as a, np.load(up_deep[1]/'timeline.npz') as b:
        identical = {name: bool(np.array_equal(a[name], b[name]))
                     for name in ('t_s', 'phase', 'pose_m_rad', 'depth_ff_m')}
        assert all(identical.values())
        straight = a['pose_m_rad'][a['phase'] == 'straight_hold']
        path = dict(start_xyz_mm=(straight[0, :3]*1000).tolist(),
                    end_xyz_mm=(straight[-1, :3]*1000).tolist())
    for col, (direction, component) in enumerate([('+X', 'By'), ('+Y', 'Bx')]):
        axes[0, col].set_title(f'{direction}: stationary XY loading')
        axes[0, col].set_xlim(36.1, 27.8)
        axes[0, col].set_xlabel('Command TCP Z (mm), loading downward →')
        axes[1, col].set_title(f'{direction}: constant-Z sliding, 10 mm/s')
        axes[1, col].set_xlim(0, 150)
        axes[1, col].axvspan(30, 120, color='#c9d1d8', alpha=.18, zorder=0)
        axes[1, col].set_xlabel('Command distance along stroke (mm)')
        for row in (0, 1):
            ax = axes[row, col]
            ax.set_ylabel(f'Filtered Δ{component} (µT)')
            ax.set_ylim(-290, 350)
            ax.axhline(0, color='#555', lw=.8)
            ax.grid(alpha=.2)
            ax.legend(fontsize=9, loc='upper left' if row == 1 else 'upper right')
    fig.suptitle('Signed magnetic response: loading history and sliding\n'
                 'No calibration applied; shaded interval is the existing primary window', fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, .93))
    fig.savefig(OUT/'process_response.png', dpi=180)
    plt.close(fig)
    output = dict(source_summary_sha256=sha(OUT/'summary.json'),
        analysis_script_sha256=sha(Path(__file__)),
        original_source_files_hash_verified=len(source_hashes),
        load_end_window_s=.3, primary_window_mm=[30, 120], runs=result,
        comparisons=comparisons,
        up_Z28_pair=dict(identical_compiled_arrays=identical, command_path=path,
            operator_report='Assembly normal; paper and brush not adjusted between trial 4 and trial 5.',
            interpretation='Given the operator report, R2 retraced the R1 path on the same paper. '
                           'Contact history changed; its contribution is not isolated from brush state.'),
        limitations=['Signed magnetic components are not direct force measurements.',
                     'Preparation signals are diagnostic only; the frozen inverse applies to straight_hold.',
                     'Two repeats do not isolate wetting, paper, contact history, or background changes.',
                     'Loading depth and loading rate differ together; their causal effects are not separable here.',
                     '10 Hz TCP sampling does not observe every preparation transient.'])
    (OUT/'process_diagnosis.json').write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    with (OUT/'process_windows.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(window_rows[0]))
        writer.writeheader()
        writer.writerows(window_rows)
    print(json.dumps(dict(verified_source_files=len(source_hashes),
        compared_runs=len(result), up_Z28_identical_trajectory=all(identical.values()),
        comparisons=comparisons), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
