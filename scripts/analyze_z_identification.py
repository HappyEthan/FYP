#!/usr/bin/env python3
"""Analyze one or more recorded Z-identification runs, without modifying raw data."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from brushbot.experiments.identification_analysis import summarize_run


def analyze(folders, output):
    # Read and verify all inputs before creating an output directory.
    loaded = [summarize_run(folder) for folder in folders]
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    metrics = []
    curves = []
    for summary, rows in loaded:
        sid = summary['run_id']
        (output/(sid+'.json')).write_text(json.dumps(summary, indent=2, ensure_ascii=False)+'\n')
        t = (np.array([r['host_ns'] for r in rows])-rows[0]['host_ns'])/1e9
        fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True, layout='constrained')
        axes[0].plot(t, [r['z_cmd_m']*1000 for r in rows], label='command Z')
        axes[1].plot(t, np.rad2deg([r['ry_cmd_rad'] for r in rows]), label='command Ry')
        axes[2].plot(t, [r['a_control_uT'] for r in rows], label='measured EMA |dBxy|')
        folder = Path(summary['run_directory'])
        if (folder/'actual_tcp.csv').exists():
            with (folder/'actual_tcp.csv').open() as stream:
                tcp = [p for p in csv.DictReader(stream) if p['valid'] == 'true']
            if tcp:
                times = np.array([(int(p['request_start_ns'])+int(p['request_end_ns']))/2 for p in tcp])
                times = (times-rows[0]['host_ns'])/1e9
                axes[0].scatter(times, [float(p['z_m'])*1000 for p in tcp], s=4, label='async actual Z')
                axes[1].scatter(times, np.rad2deg([float(p['ry_rad']) for p in tcp]), s=4, label='async actual Ry')
        for p in summary['plateaus']:
            left, right = t[p['start_index']], t[p['end_index']]
            for ax in axes:
                ax.axvspan(left, right, alpha=.08, color='green' if p['stable'] else 'red')
        for ax, label in zip(axes, ['TCP Z (mm)', 'Ry (deg)', 'Magnetic response (uT)']):
            ax.set_ylabel(label)
            ax.grid(alpha=.2)
            ax.legend()
        axes[-1].set_xlabel('Host monotonic time since first command (s)')
        profile = summary['profile']
        description = profile['mode'] if 'mode' in profile else f"nominal depth {profile['depth_mm']:g} mm"
        fig.suptitle(f"{sid} | {description}")
        fig.savefig(output/(sid+'.png'), dpi=150)
        plt.close(fig)
        for row in summary['sweep_curves']:
            curves.append(dict(run_id=sid, mode=profile['mode'], **row))
        for step in summary['transitions']:
            metrics.append(dict(run_id=sid, depth_mm=summary['profile']['depth_mm'],
                                order=summary['profile']['order'], transition=step['to_plateau'],
                                direction=step['direction'], delta_depth_mm=step['delta_depth_mm'],
                                static_gain_uT_per_mm=step['static_gain_uT_per_mm'],
                                fitted_gain_uT_per_mm=step['model']['gain_uT_per_mm'],
                                delay_s=step['model']['delay_s'], tau_s=step['model']['tau_s'],
                                rmse_uT=step['model']['rmse_uT'],
                                usable_for_initial_tuning=step['usable_for_initial_tuning'],
                                quality_flags=';'.join(step['quality_flags'])))
    for name, data in [('transition_metrics.csv', metrics), ('sweep_curves.csv', curves)]:
        if data:
            with (output/name).open('x', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(data[0]))
                writer.writeheader()
                writer.writerows(data)
    # Preserve individual runs (including flagged ones) instead of hiding variation in a mean.
    index = {'runs': [s for s, _ in loaded], 'interpretation':
             'Compare only matching profiles and installation conditions; order is an explicit condition. '
             'Per-run estimates retain quality flags. Synthetic runs are not hardware evidence.'}
    (output/'comparison.json').write_text(json.dumps(index, indent=2, ensure_ascii=False)+'\n')
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dirs', type=Path, nargs='+')
    parser.add_argument('--output', type=Path, help='new directory only; existing output is never overwritten')
    args = parser.parse_args(argv)
    output = args.output or (args.run_dirs[0].parent.parent/'analysis'/datetime.now().strftime('%Y%m%d_%H%M%S'))
    print(analyze(args.run_dirs, output))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
