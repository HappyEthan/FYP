#!/usr/bin/env python3
"""Read-only V3 plan inspection; outputs target CSV/PNG, never robot commands."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan', type=Path)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    if not (repo/'src/brushbot/target_strokeplan.py').is_file():
        parser.error('--repo must contain brushbot.target_strokeplan')
    sys.path.insert(0, str(repo/'src'))
    import numpy as np
    from brushbot.target_strokeplan import StrokePlan
    plan = StrokePlan.load(args.plan)
    if args.output_dir.exists():
        parser.error('output directory already exists; choose a new path')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    report = dict(plan=str(args.plan.resolve()),
        sha256=hashlib.sha256(args.plan.read_bytes()).hexdigest(),
        source=plan.meta['source'], coordinate_frame=plan.meta['coordinate_frame'],
        feature=plan.meta['feature'], filter_definition=plan.meta['filter_definition'],
        validation='target-only; not execution approval', strokes=[])
    args.output_dir.mkdir(parents=True, exist_ok=False)
    for i, st in enumerate(plan.strokes):
        xy = np.asarray(st.xy)*1000
        arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
        speed = np.linalg.norm(np.diff(xy, axis=0), axis=1)/np.diff(st.t)
        name = f'stroke_{i:02}'
        with (args.output_dir/f'{name}.csv').open('x', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['t_s','s','x_mm','y_mm','g_target_uT'])
            for t, s, point, g in zip(st.t, st.s, xy, st.g_target):
                writer.writerow([t, s, *point, g])
        fig, axes = plt.subplots(1, 3, figsize=(14, 4))
        axes[0].plot(xy[:,0], xy[:,1])
        axes[0].scatter(xy[0,0], xy[0,1], label='start', color='green')
        axes[0].scatter(xy[-1,0], xy[-1,1], label='end', color='red', marker='x')
        axes[0].set(xlabel='X (mm)', ylabel='Y (mm)', title=f'XY | {plan.meta["coordinate_frame"]}')
        axes[0].set_aspect('equal', adjustable='datalim')
        axes[0].legend()
        axes[1].plot(arc, st.g_target)
        axes[1].set(xlabel='Arclength (mm)', ylabel='Target (uT)', title='Response along path')
        axes[2].plot(st.t, st.g_target)
        axes[2].set(xlabel='Time (s)', ylabel='Target (uT)', title='Response in time')
        for ax in axes:
            ax.grid(alpha=.3)
        fig.suptitle(f'Stroke {i} | {plan.meta["source"]} | Target-only V3; no execution approval')
        fig.tight_layout()
        fig.savefig(args.output_dir/f'{name}.png', dpi=150)
        plt.close(fig)
        report['strokes'].append(dict(index=i, samples=len(st.s), length_mm=float(arc[-1]),
            duration_s=float(st.t[-1]), peak_xy_speed_mm_s=float(speed.max()),
            target_range_uT=[float(np.min(st.g_target)),float(np.max(st.g_target))],
            csv=f'{name}.csv', png=f'{name}.png'))
    with (args.output_dir/'summary.json').open('x') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
