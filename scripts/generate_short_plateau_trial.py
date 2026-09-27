#!/usr/bin/env python3
"""Generate the authorized 30 s P/slow-PI trial offline; never connect hardware."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from brushbot.target_strokeplan import Stroke, StrokePlan, FEATURE
from brushbot.experiments.strokeplan_execution import compile_recorded_plan

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'runs/brush2/plans/06_难曲线160到240_FF与P'
OUTPUT = ROOT/'runs/brush2/plans/08_短平台160到240回160_P与PI'


def generate(output: Path, *, source_dir: Path = SOURCE):
    output, source_dir = Path(output), Path(source_dir)
    if output.exists():
        raise FileExistsError(f'refusing to replace trial: {output}')
    payloads = {name: (source_dir/name).read_bytes() for name in
                ('feedforward.json', 'settings.json', 'entry_profile.json')}
    table, setup, entry = [json.loads(payloads[name]) for name in payloads]
    # This is a copy for the user-authorized P/PI trial. Preserve the calibration
    # and its experimental limitations; the source candidate is never rewritten.
    table.update(approved=True, transient_approved=True,
        approval_note='User authorized short plateau existing-P versus slow PI with anti-windup. '
                      'Trial adoption only, not tracking-performance validation.',
        approval_scope='08_短平台160到240回160_P与PI; Z36 rotational entry; operator RUN per trial',
        trial_source_sha256=hashlib.sha256(payloads['feedforward.json']).hexdigest())
    entry['travel_mm'] = 350.
    t = np.arange(1501)*.02
    def smooth(u):
        u = np.clip(u, 0., 1.)
        return u**3*(10.-15.*u+6.*u*u)
    g = 160.+80.*(smooth((t-8.)/3.)-smooth((t-19.)/3.))
    plan = StrokePlan([Stroke(t/30., np.c_[.039+.01*t, np.zeros(len(t))], t, g)],
        dict(source='synthetic', coordinate_frame='paper', feature=FEATURE,
             filter_definition=dict(kind='ema', alpha=.3),
             description='160 hold 8 s, rise 3 s, 240 hold 8 s, fall 3 s, 160 hold 8 s'))
    p = dict(kp=1., ki=0., max_correction_mm=.8,
             max_correction_speed_mm_s=2., max_correction_accel_mm_s2=30., taper_ticks=50)
    pi = dict(p, ki=.05, integral_limit_mm=.2, anti_windup='conditional')
    compiled = [compile_recorded_plan(plan, table, setup, label='short_plateau_'+mode,
                control_mode=mode, feedback_profile=profile, entry_profile=entry)
                for mode, profile in [('p', p), ('pi', pi)]]
    summary = dict(measurement_s=30., measurement_mm=300., paper_travel_mm=350.,
        trajectory_duration_s=float(compiled[0]['t_s'][-1]),
        sequence=['P1', 'PI1', 'PI2', 'P2'],
        metric_time_origin='first measure_00 sample; seconds; window endpoints inclusive',
        plateau_windows_s={'first_160': [5., 7.], 'deep_240': [16., 18.],
                           'return_160': [27., 29.]},
        transition_windows_s={'rise': [8., 16.], 'return': [19., 27.]},
        metrics=['signed mean error target-minus-measurement', 'MAE',
                 'fraction abs(error)<=20 uT', 'P95 abs(error)',
                 'P/I correction and output limiting fractions'],
        source_dir=str(source_dir), source_sha256={
            n: hashlib.sha256(b).hexdigest() for n, b in payloads.items()})
    output.mkdir(parents=True)
    plan.save(output/'plateau_160_240_160.npz')
    for name, value in [('feedforward.json', table), ('settings.json', setup),
                        ('entry_profile.json', entry), ('p_profile.json', p),
                        ('pi_profile.json', pi), ('protocol.json', summary)]:
        (output/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=OUTPUT)
    args = parser.parse_args()
    print(json.dumps(generate(args.output_dir), ensure_ascii=False, indent=2))
