#!/usr/bin/env python3
"""Offline synthetic V3 suite: four target profiles, no Z and no runs dependency."""
import argparse
import csv
import json
from pathlib import Path

import numpy as np

if __package__:
    from .generate_strokeplan import ROOT, generate
else:
    from generate_strokeplan import ROOT, generate

OUTPUT_DIR = ROOT / 'runs/plans/target_v3_suite'
LOW_UT = 30.0
HIGH_UT = 110.0


def profiles():
    s = np.linspace(0, 1, 401)
    smooth = lambda u: u*u*u*(10-15*u+6*u*u)
    ramp = smooth(s)
    arch = np.sin(np.pi*s)**2
    double = np.sin(2*np.pi*s)**2
    # Three transitions with constant-target holds, each transition 30 mm long.
    levels = np.array([0., .5, 1., .25])
    stairs = np.full_like(s, levels[0])
    for i, start in enumerate((.15, .4, .65)):
        stairs += (levels[i+1]-levels[i])*smooth(np.clip((s-start)/.15, 0, 1))
    return [
        ('01_gradual_press', 'Gradual target rise', ramp),
        ('02_single_arch', 'One target arch', arch),
        ('03_double_wave', 'Two target cycles', double),
        ('04_smooth_levels', 'Four target holds', stairs),
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error('output directory exists; choose a new --output-dir')
    prepared = []
    for name, title, shape in profiles():
        plan = generate(targets_uT=LOW_UT + (HIGH_UT-LOW_UT)*shape)
        plan.meta.update(stability_profile=name, description=title,
                         validation='target schema only; no machine/calibration validation')
        plan.validate()
        st=plan.strokes[0]
        report = dict(name=name,title=title,source='synthetic',support_points=len(st.s),
                      stroke_duration_s=float(st.t[-1]),
                      target_range_uT=[float(st.g_target.min()),float(st.g_target.max())])
        prepared.append((name,title,plan,report))
    # Validate targets before creating output. Machine validation is a separate step.
    args.output_dir.mkdir(parents=True)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(4, 2, figsize=(13, 12), sharex=True)
    for i,(name,title,plan,report) in enumerate(prepared):
        plan.save(args.output_dir / f'{name}.npz')
        (args.output_dir / f'{name}.json').write_text(
            json.dumps(dict(metadata=plan.meta, target_check=report),ensure_ascii=False,indent=2)+'\n')
        st=plan.strokes[0]
        with (args.output_dir / f'{name}_targets.csv').open('w',newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['t_s','s','x_mm','y_mm','g_target_uT'])
            for t,s,xy,g in zip(st.t,st.s,st.xy,st.g_target):
                writer.writerow([t,s,*xy*1000,g])
        axes[i,0].plot(st.xy[:,0]*1000, st.g_target, color='#277da8')
        axes[i,1].plot(st.xy[:,0]*1000, st.xy[:,1]*1000,color='#7c3f98')
        axes[i,0].set_title(f'{i+1}. {title}')
        axes[i,1].set_title(f'XY path | {report["stroke_duration_s"]:.2f} s stroke only')
        axes[i,0].set_ylabel('Target response (uT)')
        axes[i,1].set_ylabel('Paper Y (mm)')
        axes[i,0].set_ylim(20,120)
        axes[i,1].set_ylim(-10,10)
        for ax in axes[i]:
            ax.grid(alpha=.25)
            ax.set_xlim(0,200)
    for ax in axes[-1]:
        ax.set_xlabel('Travel along +X (mm)')
    fig.suptitle('Synthetic target-only StrokePlan V3 | 10 mm/s cruise\n'
                 'No measured labels, Z or embedded calibration; execution validation is separate')
    fig.tight_layout(rect=[0,0,1,.95])
    fig.savefig(args.output_dir/'profiles.png',dpi=150)
    plt.close(fig)
    (args.output_dir/'summary.json').write_text(json.dumps([p[-1] for p in prepared],indent=2)+'\n')
    for entry in prepared:
        print(json.dumps(entry[-1]))
    print('Saved:', args.output_dir)


if __name__ == '__main__':
    main()
