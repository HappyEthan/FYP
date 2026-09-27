#!/usr/bin/env python3
"""Analyze recorded multi-stroke calligraphy without connecting to hardware."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def analyze(run, output):
    run, output = Path(run), Path(output)
    manifest = json.loads((run/'manifest.json').read_text())
    for name, digest in manifest['sha256'].items():
        if hashlib.sha256((run/name).read_bytes()).hexdigest() != digest:
            raise ValueError(f'snapshot hash mismatch: {name}')
    rows = [json.loads(line) for line in (run/'control.jsonl').read_text().splitlines()]
    origin_ns = rows[0]['host_ns']
    t = (np.array([r['host_ns'] for r in rows])-origin_ns)/1e9
    phase = np.array([r['phase'] for r in rows])
    xyz = np.array([[r[k] for k in ('x_cmd_m','y_cmd_m','z_cmd_m')] for r in rows])*1000
    response = np.array([r['a_control_uT'] for r in rows])
    target = np.array([np.nan if r['a_ref_uT'] is None else r['a_ref_uT'] for r in rows])
    depth = np.array([r['depth_cmd_m'] for r in rows])*1000
    feedback = np.array([r['depth_fb_m'] for r in rows])*1000
    with (run/'actual_tcp.csv').open() as stream:
        actual = [r for r in csv.DictReader(stream) if r['valid']=='true']
    ta = (np.array([(int(r['request_start_ns'])+int(r['request_end_ns']))/2 for r in actual])-origin_ns)/1e9
    actual_xyz = np.array([[float(r[k]) for k in ('x_m','y_m','z_m')] for r in actual])*1000
    measure_phases = list(dict.fromkeys(p for p in phase if p.startswith('measure_')))
    report = dict(run_dir=str(run.resolve()), run_id=manifest['run_id'],
                  status=manifest['status'], snapshot_hashes_verified=True,
                  tcp_capture=json.loads((run/'actual_tcp_meta.json').read_text()),
                  notes=[
                      'Depth is nominal contact Z minus TCP Z, not a measured brush indentation.',
                      'TCP uses asynchronous 10 Hz reads at request midpoint; lag is an empirical fit, not a controller latency measurement.',
                      'Centerline gaps do not measure ink boundaries or compliant brush-tip motion.',
                      'Magnetic response is not a calibrated force or line width.',
                  ], strokes=[])
    paths = []
    fig, axes = plt.subplots(len(measure_phases), 2, figsize=(14,3.1*len(measure_phases)), squeeze=False)
    colors = plt.get_cmap('tab10').colors
    for i, name in enumerate(measure_phases):
        mask = phase==name
        ids = np.flatnonzero(mask)
        path = xyz[mask,:2]
        paths.append(path)
        arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(path,axis=0),axis=1))]
        error = response[mask]-target[mask]
        segments = {}
        for pre in ('rotate_air','lower_slow','rotate_contact','load_workpoint','measure'):
            m = phase==f'{pre}_{i:02}'
            segments[pre] = dict(duration_s=float(m.sum()*.02),
                response_first_uT=float(response[m][0]), response_last_uT=float(response[m][-1]),
                response_max_uT=float(response[m].max()), response_mean_uT=float(response[m].mean()),
                command_depth_first_mm=float(depth[m][0]), command_depth_last_mm=float(depth[m][-1]))
        # Exclude near-stationary endpoints from the empirical delay fit.
        am = (ta>t[ids[0]]+.3)&(ta<t[ids[-1]]-.3)
        candidates = []
        for lag in np.arange(0.,.151,.001):
            expected = np.column_stack([np.interp(ta[am]-lag,t,xyz[:,j]) for j in range(3)])
            diff = actual_xyz[am]-expected
            candidates.append((float(np.sqrt(np.mean(np.sum(diff[:,:2]**2,axis=1)))),float(lag),diff))
        rms,lag,diff = min(candidates,key=lambda item:item[0])
        body = (arc>=15.)&(arc<arc[-1]-10.)
        report['strokes'].append(dict(index=i+1, samples=int(mask.sum()),
            phases=segments, mean_error_uT=float(error.mean()), mae_uT=float(abs(error).mean()),
            body_mean_error_uT=float(error[body].mean()), body_mean_command_depth_mm=float(depth[mask][body].mean()),
            body_definition='exclude first 15 mm and final 10 mm of arclength',
            body_mean_target_uT=float(target[mask][body].mean()),
            feedback_mean_mm=float(feedback[mask].mean()),
            positive_saturation_fraction=float(np.mean(feedback[mask]>.79)),
            negative_saturation_fraction=float(np.mean(feedback[mask]<-.79)),
            fitted_lag_s=lag, lag_aligned_xy_rms_mm=rms,
            lag_aligned_xy_p95_mm=float(np.percentile(np.linalg.norm(diff[:,:2],axis=1),95))))
        start = np.flatnonzero(phase==f'rotate_contact_{i:02}')[0]
        end = ids[-1]
        local_t = t[start:end+1]-t[ids[0]]
        ax = axes[i,0]
        ax.plot(local_t,response[start:end+1],label='Measured magnetic response')
        ax.plot(local_t,target[start:end+1],'k--',label='Writing target')
        ax.axvline(0.,color='0.5',ls=':')
        ax.set(title=f'Stroke {i+1}: rotation / static loading / writing',ylabel='Response (uT)',xlabel='Time relative to writing start (s)')
        ax.grid(alpha=.2)
        ax = axes[i,1]
        ax.plot(local_t,depth[start:end+1],label='Commanded depth (mm)')
        ax.axvline(0.,color='0.5',ls=':')
        ax.set(title=f'Body mean error {error[body].mean():+.1f} uT',ylabel='Nominal depth (mm)',xlabel='Time relative to writing start (s)')
        ax.grid(alpha=.2)
    axes[0,0].legend(fontsize=8)
    fig.suptitle(f'Zhong calligraphy | {manifest["run_id"]} | recorded data',fontsize=12)
    fig.tight_layout()
    output.mkdir(parents=True,exist_ok=True)
    fig.savefig(output/'response_and_depth.png',dpi=160)
    plt.close(fig)
    fig,ax = plt.subplots(figsize=(9,9))
    for i,path in enumerate(paths):
        ax.plot(*path.T,color=colors[i],label=f'Stroke {i+1} target/command',lw=2)
        ax.scatter(*path[0],color=colors[i],marker='o')
        ax.scatter(*path[-1],color=colors[i],marker='x')
        ids=np.flatnonzero(phase==measure_phases[i])
        am=(ta>=t[ids[0]])&(ta<=t[ids[-1]])
        ax.plot(*actual_xyz[am,:2].T,color=colors[i],ls=':',alpha=.6,lw=1)
        rmask=phase==f'rotate_contact_{i:02}'
        ax.plot(*xyz[rmask,:2].T,color=colors[i],ls='--',lw=1.5)
        ax.annotate(str(i+1),path[0],xytext=(6,6),textcoords='offset points',color=colors[i])
    gaps=[]
    if len(paths)==4:
        for other in (0,1):
            distance=np.linalg.norm(paths[2][:,None]-paths[other][None,:],axis=2)
            a,b=np.unravel_index(distance.argmin(),distance.shape)
            pair=np.array([paths[2][a],paths[other][b]])
            gap=float(distance[a,b]);gaps.append(dict(strokes=[3,other+1],
                sampled_centerline_gap_mm=gap,stroke3_xy_mm=pair[0].tolist(),other_xy_mm=pair[1].tolist()))
            ax.plot(*pair.T,'r-',lw=2)
            ax.annotate(f'{gap:.2f} mm',pair.mean(axis=0),xytext=(-65,-18),textcoords='offset points',color='red')
    report['connections']=gaps
    ax.set(xlabel='Base X (mm)',ylabel='Base Y (mm)',title='Commanded centerlines and measured TCP\nDashed: reverse entry; dotted: actual TCP; circle: start; cross: end')
    ax.set_aspect('equal');ax.grid(alpha=.2);ax.legend(fontsize=9)
    fig.tight_layout();fig.savefig(output/'xy_connections.png',dpi=160);plt.close(fig)
    (output/'analysis.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=analyze(args.run,args.output)
    print(json.dumps(dict(run_id=report['run_id'], status=report['status'],
                         output=str(args.output)),ensure_ascii=False,indent=2))
