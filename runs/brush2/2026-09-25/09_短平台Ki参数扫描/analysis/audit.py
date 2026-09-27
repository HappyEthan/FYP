"""Frozen short-platform data audit, adapted to the three declared Ki values.

Same calculations as the preceding P/PI analysis; does not modify source data.
"""
import csv
import hashlib
import json
from collections import Counter
import numpy as np

SOURCE_ANALYZER_SHA256 = '045986c3e43953609ba00ed98d46f676ec2ebaf62f9d42e7c840075a6709297a'

def read(path):
    return json.loads(path.read_text())


def metrics(e, t):
    a = abs(e)
    return dict(n=len(e), mae_uT=float(a.mean()), bias_uT=float(e.mean()),
        p95_abs_uT=float(np.percentile(a,95)), max_abs_uT=float(a.max()),
        within20_pct=float(np.mean(a<=20)*100), std_uT=float(e.std()),
        severe50_s=float(np.sum(np.diff(t)*(a[:-1]>50))))


def mask(t, interval):
    return (t >= interval[0]-1e-8) & (t <= interval[1]+1e-8)


def load(folder, label, windows):
    manifest, resolved = read(folder/'manifest.json'), read(folder/'resolved.json')
    assert manifest['status']=='completed' and manifest['execution_environment']=='hardware'
    for name, sha in manifest['sha256'].items():
        assert hashlib.sha256((folder/name).read_bytes()).hexdigest()==sha, (folder,name)
    allrows=[json.loads(s) for s in (folder/'control.jsonl').read_text().splitlines()]
    rows=[r for r in allrows if r['phase']=='measure_00']
    t=np.array([r['t_s'] for r in rows]); t-=t[0]
    assert len(t)==1501 and np.allclose(t,np.arange(1501)*.02,atol=1e-8,rtol=0)
    g=np.array([r['a_ref_uT'] for r in rows]); y=np.array([r['a_control_uT'] for r in rows]);e=g-y
    assert np.isfinite(np.r_[t,g,y]).all()
    assert np.allclose(e,[r['e_center_uT'] for r in rows],atol=1e-10,rtol=0)
    with np.load(folder/'timeline.npz',allow_pickle=False) as timeline:
        use=timeline['phase']=='measure_00'
        assert np.allclose(g,timeline['g_ref_uT'][use],atol=1e-9,rtol=0)
        assert np.allclose([[r['x_cmd_m'],r['y_cmd_m']] for r in rows],timeline['pose_m_rad'][use,:2],atol=1e-9,rtol=0)
    with (folder/'sensor.csv').open() as f:
        sensor={int(r['seq']):r for r in csv.DictReader(f)}
    assert all(sensor[r['sample_seq']]['valid'].lower()=='true' for r in rows)
    c=resolved['control'];mode=c['mode']
    assert (c['kp'],c['max_correction_mm'],c['max_correction_speed_mm_s'],
            c['max_correction_accel_mm_s2'],c['taper_ticks'])==(1.,.8,2.,30.,50)
    assert mode=='pi' and c['ki'] in (.025, .05, .1)
    corr=np.array([r['depth_fb_m'] for r in rows])*1000
    integral=np.array([r.get('i_correction_m',0.) for r in rows])*1000
    blocked=np.array([r.get('integral_blocked',False) for r in rows])
    cap=abs(corr)>=.8-1e-6
    window_stats={}
    for key,interval in windows.items():
        use=mask(t,interval)
        m=metrics(e[use],t[use]);m.update(mean_correction_mm=float(corr[use].mean()),
            cap_pct=float(cap[use].mean()*100), mean_integral_mm=float(integral[use].mean()),
            integral_start_mm=float(integral[use][0]), integral_end_mm=float(integral[use][-1]),
            integral_blocked_pct=float(blocked[use].mean()*100))
        window_stats[key]=m
    m=metrics(e,t);m.update(cap_pct=float(cap.mean()*100),
        press_cap_pct=float(np.mean(corr>=.8-1e-6)*100),lift_cap_pct=float(np.mean(corr<=-.8+1e-6)*100))
    integral_audit=None
    if mode=='pi':
        assert c['integral_limit_mm']==.2 and c['anti_windup']=='conditional'
        table=read(folder/'feedforward.json')
        scale=(table['depth_mm'][-1]-table['depth_mm'][0])/1000/(table['amplitude_uT'][-1]-table['amplitude_uT'][0])
        previous=0.
        for r in rows:
            p=c['kp']*scale*r['e_center_uT']; delta=c['ki']*scale*r['e_center_uT']*.02
            candidate=float(np.clip(previous+delta,-.0002,.0002));raw=p+candidate
            freeze=((raw>r['feedback_upper_m']+1e-12 and candidate>previous)
                    or (raw<r['feedback_lower_m']-1e-12 and candidate<previous))
            accepted=previous if freeze else candidate
            assert bool(r['integral_blocked'])==freeze
            assert abs(accepted-r['i_correction_m'])<1e-12
            assert abs(p-r['p_request_m'])<1e-12 and abs(raw-r['pi_candidate_m'])<1e-12
            assert abs(np.clip(p+accepted,r['feedback_lower_m'],r['feedback_upper_m'])-r['depth_fb_m'])<1e-12
            previous=accepted
        assert all(r['i_correction_m']==0 for r in allrows if r['phase']!='measure_00')
        counts=Counter(reason for r in rows if r['integral_blocked'] for reason in r['limit_reasons'])
        deep_i=window_stats['deep_240']['mean_integral_mm']
        d=float(np.interp(240,table['amplitude_uT'],table['depth_mm']))
        static_effect=float(np.interp(d+deep_i,table['depth_mm'],table['amplitude_uT'])-240)
        integral_audit=dict(recurrence_verified=True, max_abs_integral_mm=float(abs(integral).max()),
            integral_blocked_pct=float(blocked.mean()*100),
            stored_integral_at_cap_pct=float(np.mean(abs(integral)>=.2-1e-6)*100),
            integral_limit_flag_pct=float(np.mean([r['integral_limit_active'] for r in rows])*100),
            blocked_away_from_full_amplitude_pct=float(np.sum(blocked & ~cap)/blocked.sum()*100),
            reasons_among_blocked_counts=dict(counts), blocked_samples=int(blocked.sum()),
            table_only_deep_integral_effect_uT=static_effect,
            end_of_measurement_integral_mm=float(integral[-1]),outside_measurement_integral_zero=True)
    with (folder/'actual_tcp.csv').open() as f:
        actual=[r for r in csv.DictReader(f) if r['valid'].lower()=='true']
    origin=rows[0]['host_ns'];host=np.array([(r['host_ns']-origin)/1e9 for r in rows])
    actual_t=np.array([((int(r['request_start_ns'])+int(r['request_end_ns']))/2-origin)/1e9 for r in actual])
    use=(actual_t>=0)&(actual_t<=host[-1]);actual_t=actual_t[use]
    actual_z=np.array([float(r['z_m'])*1000 for r in actual])[use]
    zerror=actual_z-np.interp(actual_t,host,[r['z_cmd_m']*1000 for r in rows])
    allcorr=np.array([r['depth_fb_m'] for r in allrows])*1000
    assert np.max(abs(allcorr))<=.8+1e-8
    assert np.max(abs(np.diff(allcorr)))/.02<=2+1e-7
    assert np.max(abs(np.diff(allcorr,n=2)))/.02**2<=30+1e-6
    tcp=dict(z_mae_mm=float(abs(zerror).mean()),z_p95_mm=float(np.percentile(abs(zerror),95)),
        max_control_gap_ms=float(np.diff(host).max()*1000),max_sample_age_ms=max(r['sample_age_s'] for r in rows)*1000,
        metadata=read(folder/'actual_tcp_meta.json'))
    audit=dict(id=label,folder=folder.name,mode=mode,status=manifest['status'],control=c,
        baseline=manifest['baseline'],metrics=m,windows=window_stats,integral=integral_audit,tcp=tcp,
        snapshot_hashes_verified=True,measurement_sensor_references_valid=True,
        source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()})
    return dict(id=label,folder=folder,mode=mode,t=t,g=g,y=y,e=e,corr=corr,integral=integral,
        blocked=blocked,actual_t=actual_t,zerror=zerror,audit=audit)

