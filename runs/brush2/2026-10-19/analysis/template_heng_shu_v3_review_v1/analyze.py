#!/usr/bin/env python3
"""Read-only review of the two hardware trials; no robot or target mutation."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / 'src'))
from brushbot.target_strokeplan import StrokePlan

RUNS = [
    ('heng', '18-50-27__template_heng_100_240_v3__8ebd17'),
    ('shu', '18-53-19__template_shu_100_240_v3__845db2'),
]
DATE = ROOT / 'runs/brush2/2026-10-19'


def load_run(kind, name):
    folder = DATE / name
    manifest = json.loads((folder / 'manifest.json').read_text())
    resolved = json.loads((folder / 'resolved.json').read_text())
    setup = json.loads((folder / 'settings.json').read_text())
    assert manifest['status'] == 'completed'
    assert manifest['execution_environment'] == 'hardware'
    assert resolved['control'] == {'enabled': False}
    for filename in ['strokeplan.npz', 'feedforward.json', 'settings.json', 'entry_profile.json']:
        expected = resolved['inputs'][filename]['sha256']
        assert hashlib.sha256((folder / filename).read_bytes()).hexdigest() == expected
    control = [json.loads(line) for line in (folder / 'control.jsonl').read_text().splitlines()]
    st = StrokePlan.load(folder / 'strokeplan.npz').strokes[0]
    phase = np.array([r['phase'] for r in control])
    measure = phase == 'measure_00'
    origin_ns = control[0]['host_ns']
    ct = (np.array([r.get('command_started_ns') or r['host_ns'] for r in control], float) - origin_ns) / 1e9
    m0, m1 = ct[measure][[0, -1]]
    xyz = np.array([[r[k] for k in ['x_cmd_m', 'y_cmd_m', 'z_cmd_m']] for r in control]) * 1000
    g = np.array([r['a_control_uT'] for r in control])
    ref = np.array([np.nan if r['a_ref_uT'] is None else r['a_ref_uT'] for r in control])
    with (folder / 'actual_tcp.csv').open() as stream:
        actual = [r for r in csv.DictReader(stream) if r['valid'].lower() in {'true', '1'}]
    at = (np.array([(int(r['request_start_ns']) + int(r['request_end_ns'])) / 2 for r in actual]) - origin_ns) / 1e9
    axyz = np.array([[float(r[k]) for k in ['x_m', 'y_m', 'z_m']] for r in actual]) * 1000
    am = (at >= m0) & (at <= m1)
    error = g[measure] - ref[measure]
    vertices = xyz[measure, :2]
    vectors = np.diff(vertices, axis=0)
    relative = axyz[am, None, :2] - vertices[None, :-1, :]
    along = np.clip((relative * vectors[None, :, :]).sum(axis=2) /
                    np.maximum((vectors * vectors).sum(axis=1), 1e-30), 0, 1)
    spatial = np.linalg.norm(relative - along[:, :, None] * vectors[None, :, :], axis=2).min(axis=1)

    def tcp_error(lag):
        expected = np.column_stack([np.interp(at[am] - lag, ct, xyz[:, j]) for j in range(3)])
        return np.linalg.norm(axyz[am] - expected, axis=1)

    lag = min(np.linspace(0, .4, 81), key=lambda value: np.mean(tcp_error(value) ** 2))
    phase_summary = {}
    for p in dict.fromkeys(phase):
        mask = phase == p
        phase_summary[str(p)] = dict(duration_between_first_last_command_s=float(ct[mask][-1] - ct[mask][0]),
            measured_g_min_median_max_uT=np.percentile(g[mask], [0, 50, 100]).tolist(),
            final_measured_g_uT=float(g[mask][-1]), final_command_z_mm=float(xyz[mask][-1, 2]))
    landmarks = []
    plan = StrokePlan.load(folder / 'strokeplan.npz')
    for knot in plan.meta['phase_control_points']:
        t = float(np.interp(knot['s'], st.s, st.t))
        idx = np.flatnonzero(measure)[np.argmin(abs(np.array([r['t_s'] for r in control])[measure]
                                                   - control[np.flatnonzero(measure)[0]]['t_s'] - t))]
        landmarks.append(dict(action=knot['action'], s=knot['s'], writing_time_s=t,
            target_g_uT=float(ref[idx]), measured_g_uT=float(g[idx]), command_z_mm=float(xyz[idx, 2]),
            plan_xy_mm=[float(np.interp(knot['s'], st.s, st.xy[:, j]) * 1000) for j in range(2)]))
    tail = st.s >= .8
    tail_xy = st.xy[tail] * 1000
    metrics = dict(kind=kind, run_path=str(folder.relative_to(ROOT)), run_id=manifest['run_id'],
        status=manifest['status'], control_mode='feedforward', writing_duration_s=float(st.t[-1]),
        target_xy_bbox_mm=np.ptp(st.xy * 1000, axis=0).tolist(),
        measured_g_rmse_uT=float(np.sqrt(np.mean(error ** 2))), measured_g_mae_uT=float(abs(error).mean()),
        measured_g_mean_bias_uT=float(error.mean()), fraction_within_20_uT=float((abs(error) <= 20).mean()),
        xy_distance_to_command_path_p95_mm=float(np.percentile(spatial, 95)), actual_tcp_writing_samples=int(am.sum()),
        unshifted_tcp_xyz_rmse_mm=float(np.sqrt(np.mean(tcp_error(0) ** 2))),
        diagnostic_estimated_tcp_lag_s=float(lag),
        diagnostic_lag_adjusted_tcp_xyz_rmse_mm=float(np.sqrt(np.mean(tcp_error(lag) ** 2))),
        lag_note='Diagnostic constant shift estimated on this run, not an independent tracking performance claim.',
        endpoint_target_g_uT=float(st.g_target[-1]), endpoint_measured_g_uT=float(g[measure][-1]),
        endpoint_command_z_mm=float(xyz[measure][-1, 2]),
        endpoint_nominal_depth_mm=float(setup['contact_z_mm'] - xyz[measure][-1, 2]),
        tail_last_20_percent=dict(path_length_mm=float(np.linalg.norm(np.diff(tail_xy, axis=0), axis=1).sum()),
            duration_s=float(st.t[-1] - st.t[np.flatnonzero(tail)[0]]), bbox_mm=np.ptp(tail_xy, axis=0).tolist(),
            x_reverse_from_rightmost_to_end_mm=float(tail_xy[:, 0].max() - tail_xy[-1, 0])),
        phases=phase_summary, landmarks=landmarks,
        source_sha256={name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in
            ['manifest.json', 'resolved.json', 'strokeplan.npz', 'control.jsonl', 'actual_tcp.csv',
             'actual_tcp_meta.json', 'entry_profile.json', 'settings.json', 'feedforward.json']})
    return dict(kind=kind, folder=folder, st=st, phase=phase, ct=ct-m0, xyz=xyz,
                g=g, ref=ref, at=at-m0, axyz=axyz, am=am, measure=measure,
                metrics=metrics, setup=setup)


def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    out = Path(__file__).resolve().parent
    owned = {'analyze.py', 'metrics.json', 'two_trials_overview.png', 'heng_tail_detail.png'}
    if any(p.name not in owned for p in out.iterdir()):
        raise FileExistsError('review directory contains files outside this analysis')
    runs = [load_run(*item) for item in RUNS]
    report = dict(evidence='two completed hardware runs; original recordings preserved',
        measured_force_available=False, ink_image_available=False,
        ink_observation_source='user: conspicuous horizontal-tail bend, poor entry/exit control, excessive size',
        requested_next_size_mm=dict(heng_width=80, shu_height=120),
        next_plan_status='discussion only; no target or execution configuration changed',
        limitations=['one run per stroke', 'magnetic response is not calibrated force or ink width',
                     'actual TCP is sampled at about 10 Hz and is not the moving brush-fiber contact point',
                     'no paper image to quantify visible outline, width or taper'],
        runs=[r['metrics'] for r in runs])
    with (out / 'metrics.json').open('w', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    fig, grid = plt.subplots(2, 3, figsize=(16, 8.5))
    for axes, run in zip(grid, runs):
        m = run['measure']; am = run['am']; ct = run['ct']; at = run['at']
        origin = np.array([run['setup']['origin_x_mm'], run['setup']['origin_y_mm']])
        xy = run['xyz'][m, :2] - origin
        actual = run['axyz'][am, :2] - origin
        axes[0].plot(xy[:, 0], xy[:, 1], label='commanded TCP', lw=2)
        axes[0].plot(actual[:, 0], actual[:, 1], '.', ms=2.5, label='measured TCP ~10 Hz')
        axes[0].scatter(*xy[0], c='green', s=25, zorder=5)
        axes[0].scatter(*xy[-1], c='red', marker='x', s=30, zorder=5)
        axes[0].set(xlabel='Paper X (mm)', ylabel='Paper Y (mm)', aspect='equal',
                    xlim=(60, 220), ylim=(-100, 100),
                    title=run['kind'] + ' | TCP path, not ink outline')
        axes[1].plot(ct, run['ref'], label='target G', lw=2)
        axes[1].plot(ct, run['g'], label='measured filtered G', lw=1, alpha=.9)
        axes[1].axvspan(-6, 0, color='gray', alpha=.12, label='rotation + stationary loading')
        axes[1].axvline(0, color='k', ls=':', lw=.8)
        axes[1].set(xlim=(-6.2, float(ct[m][-1])+.6), xlabel='Time from writing start (s)',
                    ylabel='Magnetic response (uT)', title=f"G error RMSE {run['metrics']['measured_g_rmse_uT']:.1f} uT")
        axes[2].plot(ct, run['xyz'][:, 2], label='commanded Z', lw=2)
        axes[2].plot(at, run['axyz'][:, 2], '.', ms=2, label='measured TCP Z')
        axes[2].axvline(0, color='k', ls=':', lw=.8)
        axes[2].set(xlim=(-6.2, float(ct[m][-1])+.6), ylim=(27, 38),
                    xlabel='Time from writing start (s)', ylabel='TCP Z (mm)',
                    title='Z during entry / writing / initial lift')
        for ax in axes:
            ax.grid(alpha=.2); ax.legend(fontsize=7, loc='best')
    fig.suptitle('Brush2 | 2026-10-19 | feedforward only | no measured force or ink-width calibration')
    fig.tight_layout(rect=(0, 0, 1, .96))
    fig.savefig(out / 'two_trials_overview.png', dpi=160)
    plt.close(fig)

    run = runs[0]; st = run['st']; tail = st.s >= .8
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.8))
    start = float(st.t[np.flatnonzero(tail)[0]])
    origin = np.array([run['setup']['origin_x_mm'], run['setup']['origin_y_mm']])
    am = (run['at'] >= start) & (run['at'] <= st.t[-1] + .1)
    actual = run['axyz'][am, :2] - origin
    axes[0].plot(st.xy[tail, 0]*1000, st.xy[tail, 1]*1000, label='planned TCP', lw=2)
    axes[0].plot(actual[:, 0], actual[:, 1], '.', ms=3, label='measured TCP')
    for index, label in [(34, 'press'), (38, 'lift intent'), (41, 'reload'), (45, 'end')]:
        point = next(k for k in run['metrics']['landmarks'] if
                     abs(k['s'] - {34:.8065020064963865, 38:.8584506603878274, 41:.9366049444260507, 45:1.}[index]) < 1e-8)
        xy = point['plan_xy_mm']
        axes[0].scatter(*xy, s=18)
        axes[0].annotate(label, xy, xytext=(-46, 6) if label == 'reload' else (3, 6),
                         textcoords='offset points', fontsize=8)
    axes[0].set(xlabel='Paper X (mm)', ylabel='Paper Y (mm)', aspect='equal', title='Heng tail: visible-scale TCP reversal')
    axes[1].plot(run['ct'], run['ref'], label='target G', lw=2)
    axes[1].plot(run['ct'], run['g'], label='measured filtered G', lw=1.3)
    axes[1].set(xlim=(start-.2, st.t[-1]+.2), xlabel='Writing time (s)', ylabel='G (uT)', title='Lift intent did not produce its target G')
    axes[2].plot(run['ct'], run['xyz'][:, 2], label='commanded Z', lw=2)
    axes[2].plot(run['at'], run['axyz'][:, 2], '.', label='measured TCP Z', ms=3)
    axes[2].set(xlim=(start-.2, st.t[-1]+.2), ylim=(27.5, 34), xlabel='Writing time (s)', ylabel='TCP Z (mm)',
                title='Endpoint still at nominal depth 6.75 mm')
    for ax in axes:
        ax.grid(alpha=.2); ax.legend(fontsize=8)
    fig.suptitle('Heng tail | last ~20% of path takes 5.46 s | horizontal reversal ~8.36 mm')
    fig.tight_layout(rect=(0, 0, 1, .94))
    fig.savefig(out / 'heng_tail_detail.png', dpi=170)
    plt.close(fig)
    print(json.dumps({r['kind']: {k: r['metrics'][k] for k in
          ['writing_duration_s', 'measured_g_rmse_uT', 'xy_distance_to_command_path_p95_mm',
           'endpoint_nominal_depth_mm', 'endpoint_measured_g_uT', 'tail_last_20_percent']} for r in runs},
          ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
