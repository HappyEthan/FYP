#!/usr/bin/env python3
"""Compare two recorded character trials on time and common arclength domains."""
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

from brushbot.target_strokeplan import StrokePlan


def error_metrics(e):
    return dict(mean_error_uT=float(e.mean()),mae_uT=float(abs(e).mean()),
                rmse_uT=float(np.sqrt(np.mean(e**2))),p90_abs_error_uT=float(np.percentile(abs(e),90)))


def load_run(path):
    path=Path(path)
    manifest=json.loads((path/'manifest.json').read_text())
    for name,digest in manifest['sha256'].items():
        if hashlib.sha256((path/name).read_bytes()).hexdigest()!=digest:
            raise ValueError(f'snapshot hash mismatch: {path/name}')
    rows=[json.loads(s) for s in (path/'control.jsonl').read_text().splitlines()]
    base=rows[0]['host_ns']
    t=(np.array([r['host_ns'] for r in rows])-base)/1e9
    pose=np.array([[r[k] for k in ('x_cmd_m','y_cmd_m','z_cmd_m','rx_cmd_rad','ry_cmd_rad','rz_cmd_rad')] for r in rows])
    with (path/'actual_tcp.csv').open() as stream:
        actual=[r for r in csv.DictReader(stream) if r['valid']=='true']
    at=(np.array([(int(r['request_start_ns'])+int(r['request_end_ns']))/2 for r in actual])-base)/1e9
    ap=np.array([[float(r[k]) for k in ('x_m','y_m','z_m','rx_rad','ry_rad','rz_rad')] for r in actual])
    with (path/'sensor.csv').open() as stream:
        sensor=list(csv.DictReader(stream))
    phase=np.array([r['phase'] for r in rows])
    measured=np.array([r['a_control_uT'] for r in rows])
    plan=StrokePlan.load(path/'strokeplan.npz')
    resolved=json.loads((path/'resolved.json').read_text())
    limit=resolved['control']['max_correction_mm']
    segments=[]
    metrics=[]
    for i,st in enumerate(plan.strokes):
        ids=np.flatnonzero(phase==f'measure_{i:02}')
        if len(ids)!=len(st.t):
            raise ValueError('incomplete writing timeline')
        selected=[rows[j] for j in ids]
        g=measured[ids]
        ref=np.array([r['a_ref_uT'] for r in selected])
        if not np.allclose(ref,st.g_target,atol=1e-6,rtol=0):
            raise ValueError('logged target differs from snapshot')
        arc=np.r_[0.,np.cumsum(np.linalg.norm(np.diff(st.xy,axis=0),axis=1))]*1000
        fb=np.array([r['depth_fb_m'] for r in selected])*1000
        integ=np.array([r['i_correction_m'] for r in selected])*1000
        dep=np.array([r['depth_cmd_m'] for r in selected])*1000
        am=(at>t[ids[0]]+.3)&(at<t[ids[-1]]-.3)
        candidates=[]
        for lag in np.arange(0.,.151,.001):
            expected=np.column_stack([np.interp(at[am]-lag,t,pose[:,j]) for j in range(6)])
            d=ap[am]-expected
            candidates.append((float(np.sqrt(np.mean(np.sum(d[:,:2]**2,axis=1)))*1000),float(lag),d))
        rms,lag,d=min(candidates,key=lambda a:a[0])
        zero=np.column_stack([np.interp(at[am],t,pose[:,j]) for j in range(3)])
        unaligned=(ap[am,:3]-zero)*1000
        local=dict(index=i+1,samples=len(ids),length_mm=float(arc[-1]),duration_s=float(st.t[-1]),
            full_writing=error_metrics(g-ref),positive_correction_cap_fraction=float(np.mean(fb>=limit-.01)),
            negative_correction_cap_fraction=float(np.mean(fb<=-limit+.01)),
            integral_cap_fraction=float(np.mean(abs(integ)>=resolved['control']['integral_limit_mm']-.001)),
            mean_correction_mm=float(fb.mean()),integral_first_mm=float(integ[0]),integral_last_mm=float(integ[-1]),
            anti_windup_blocked_fraction=float(np.mean([r['integral_blocked'] for r in selected])),
            fitted_tcp_lag_ms=lag*1000,aligned_xy_rms_mm=rms,
            aligned_z_abs_p95_mm=float(np.percentile(abs(d[:,2])*1000,95)),
            aligned_rpy_error_p95_deg=float(np.percentile(np.linalg.norm(np.rad2deg(d[:,3:]),axis=1),95)),
            unaligned_xy_error_p95_mm=float(np.percentile(np.linalg.norm(unaligned[:,:2],axis=1),95)),phases={})
        for pre in ('rotate_air','rotate_contact','load_workpoint'):
            m=phase==f'{pre}_{i:02}'
            local['phases'][pre]=dict(mean_uT=float(measured[m].mean()),last_uT=float(measured[m][-1]),max_uT=float(measured[m].max()))
        local['tail_10mm']=dict(target_mean_uT=float(ref[arc>=arc[-1]-10].mean()),
                               observed_mean_uT=float(g[arc>=arc[-1]-10].mean()))
        segments.append(dict(arc=arc,g=g,ref=ref,fb=fb,integ=integ,depth=dep,indices=ids))
        metrics.append(local)
    valid_labels={v:sum(r['valid']==v for r in sensor) for v in set(r['valid'] for r in sensor)}
    report=dict(run_dir=str(path.resolve()),run_id=manifest['run_id'],status=manifest['status'],
        snapshot_hashes_verified=True,control=resolved['control'],
        sensor_rows=len(sensor),sensor_valid_counts=valid_labels,
        tcp_capture=json.loads((path/'actual_tcp_meta.json').read_text()),
        baseline=manifest['baseline'],nominal_duration_s=float(rows[-1]['t_s']),
        max_tick_lateness_ms=float(max(r['lateness_s'] for r in rows)*1000),
        p99_tick_lateness_ms=float(np.percentile([r['lateness_s'] for r in rows],99)*1000),
        max_sensor_age_ms=float(max(r['sample_age_s'] for r in rows)*1000),
        control_interval_ms_percentiles=np.percentile(np.diff(t)*1000,[50,95,100]).tolist(),
        final_hold_response_mean_uT=float(measured[phase=='hold'].mean()),
        all_writing=error_metrics(np.concatenate([s['g']-s['ref'] for s in segments])),strokes=metrics)
    return dict(path=path,plan=plan,report=report,segments=segments,t=t,phase=phase,g=measured,
                ff=json.loads((path/'feedforward.json').read_text()),
                setup=json.loads((path/'settings.json').read_text()),
                entry=json.loads((path/'entry_profile.json').read_text()))


def compare(first,second,output):
    runs=[load_run(first),load_run(second)]
    a,b=runs
    comparison=dict(runs=[r['report'] for r in runs],
        control_equal=a['report']['control']==b['report']['control'],
        settings_equal=a['setup']==b['setup'],entry_equal=a['entry']==b['entry'],
        feedforward_changed_keys=sorted(k for k in a['ff'].keys()|b['ff'].keys() if a['ff'].get(k)!=b['ff'].get(k)),
        notes=[
            'Error = observed minus target; positive means higher magnetic response.',
            'Full-writing metrics are equally weighted by logged 20 ms command ticks.',
            'Common-body metrics use equal 0.1 mm spatial intervals, excluding the first 15 mm and final 10 mm of the shorter stroke.',
            'Fitted TCP lag uses XY and an asynchronous read midpoint; aligned residual is not absolute brush-tip accuracy.',
            'Airborne residual response can include baseline change, pose effects and brush relaxation; scalar subtraction is not a valid vector baseline correction.',
            'No paper photos are paired with these two run IDs in this analysis; ink closure and width are not evaluated.',
        ],strokes=[])
    fig,axes=plt.subplots(4,3,figsize=(16,13))
    entryfig,entryaxes=plt.subplots(2,2,figsize=(13,8))
    for i,(sa,sb) in enumerate(zip(a['segments'],b['segments'])):
        pa,pb=a['plan'].strokes[i],b['plan'].strokes[i]
        same={k:getattr(pa,k).shape==getattr(pb,k).shape and np.array_equal(getattr(pa,k),getattr(pb,k)) for k in ('xy','t','g_target','orientation')}
        common_end=min(sa['arc'][-1],sb['arc'][-1])
        grid=np.arange(15.,common_end-10.,.1)
        metrics=[]
        for s in (sa,sb):
            obs=np.interp(grid,s['arc'],s['g']);target=np.interp(grid,s['arc'],s['ref'])
            metrics.append(dict(**error_metrics(obs-target),observed_mean_uT=float(obs.mean()),target_mean_uT=float(target.mean()),
                                command_depth_mean_mm=float(np.interp(grid,s['arc'],s['depth']).mean())))
        allgrid=np.arange(0.,common_end,.1)
        common_target_diff=np.interp(allgrid,sb['arc'],sb['ref'])-np.interp(allgrid,sa['arc'],sa['ref'])
        comparison['strokes'].append(dict(index=i+1,identical_arrays=same,
            endpoint_shift_mm=((pb.xy[-1]-pa.xy[-1])*1000).tolist(),
            common_target_max_abs_difference_uT=float(abs(common_target_diff).max()),
            common_body_interval_mm=[15.,float(common_end-10.)],common_body=metrics))
        for j,r in enumerate(runs):
            s=r['segments'][i];label=f'Run {8+j}';color=['tab:blue','tab:orange'][j]
            axes[i,0].plot(s['arc'],s['g'],label=label,color=color)
            axes[i,1].plot(s['arc'],s['fb'],label=label,color=color)
            axes[i,1].plot(s['arc'],s['integ'],ls=':',color=color,alpha=.8,label=f'{label} integral')
            axes[i,2].plot(s['arc'],s['depth'],label=label,color=color)
            ids=s['indices'];start=np.flatnonzero(r['phase']==f'rotate_contact_{i:02}')[0]
            end=min(ids[-1]+1,ids[0]+151)
            local=r['t'][start:end]-r['t'][ids[0]]
            ea=entryaxes.flat[i];ea.plot(local,r['g'][start:end],label=label,color=color)
        axes[i,0].plot(sa['arc'],sa['ref'],'k--',lw=1,label='Target (run 8)')
        if sb['arc'][-1]>sa['arc'][-1]+.01:
            extra=sb['arc']>sa['arc'][-1];axes[i,0].plot(sb['arc'][extra],sb['ref'][extra],'k--',lw=1)
        for j,title in enumerate(('Magnetic response (uT)','PI / integral correction (mm)','Commanded nominal depth (mm)')):
            axes[i,j].set(title=f'Stroke {i+1}: {title}',xlabel='Travel from stroke start (mm)');axes[i,j].grid(alpha=.2)
        ea=entryaxes.flat[i];ea.axvline(0,color='0.5',ls=':');ea.axvline(-3,color='0.5',ls=':')
        ea.set(title=f'Stroke {i+1}: rotation, loading, initial writing',xlabel='Time relative to writing start (s)',ylabel='Response (uT)');ea.grid(alpha=.2)
    for ax in axes[0]:ax.legend(fontsize=8)
    entryaxes[0,0].legend()
    fig.suptitle('Run 8 vs Run 9 | same Kp=1, Ki=0.1 | stroke 3 extended by 5 mm')
    fig.tight_layout();entryfig.tight_layout()
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    fig.savefig(output/'tracking_comparison.png',dpi=160)
    entryfig.savefig(output/'entry_comparison.png',dpi=160)
    plt.close(fig);plt.close(entryfig)
    (output/'comparison.json').write_text(json.dumps(comparison,ensure_ascii=False,indent=2)+'\n')
    return comparison


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('first',type=Path);parser.add_argument('second',type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    report=compare(args.first,args.second,args.output)
    print(json.dumps(dict(output=str(args.output),common_body=[s['common_body'] for s in report['strokes']]),ensure_ascii=False,indent=2))
