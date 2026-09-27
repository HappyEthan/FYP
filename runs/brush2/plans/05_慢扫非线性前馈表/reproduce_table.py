"""Build a measured nonlinear candidate table; offline, no robot I/O."""
from pathlib import Path
import csv
import hashlib
import json
import shutil
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from brushbot.feedforward import CONTEXT_KEYS, lookup_depth_m, validate_table

ROOT = Path('/home/ethan/FYP')
RAW = ROOT/'runs/brush2/2026-09-25/05_Z动态辨识/raw'
OUT = ROOT/'runs/brush2/plans/05_慢扫非线性前馈表'
NAMES = ['14-28-57_连续下压_Z38到24mm_单程30s_第2次',
         '15-02-32_连续下压_Z38到24mm_单程30s_第3次']
DEPTH = np.arange(5., 15.001, .25)

def dump(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+'\n')

def csv_write(path, rows):
    with path.open('x', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

curves, sources, bin_rows = [], [], []
for name in NAMES:
    p = RAW/name
    manifest = json.loads((p/'manifest.json').read_text())
    profile = json.loads((p/'identification.json').read_text())
    settings = json.loads((p/'settings.json').read_text())
    assert manifest['status'] == 'completed' and manifest['execution_environment'] == 'hardware'
    assert profile['mode'] == 'sweep-down' and profile['sweep_s'] == 30.
    assert profile['entry_contact_z_mm'] == 38. and profile['speed_mm_s'] == 10.
    for filename, digest in manifest['sha256'].items():
        assert hashlib.sha256((p/filename).read_bytes()).hexdigest() == digest
    records = [json.loads(line) for line in (p/'control.jsonl').read_text().splitlines()]
    rows = [r for r in records if r['phase'] == 'sweep_down']
    segments = json.loads((p/'segments.json').read_text())
    segment = next(s for s in segments if s['id'] == 'sweep_down')
    ticks = np.rint(np.array([r['t_s'] for r in rows])/.02).astype(int)
    assert np.array_equal(ticks, np.arange(segment['start_tick'], segment['end_tick']))
    assert all(r['valid'] == 'true' for r in csv.DictReader((p/'sensor.csv').open()))
    d = np.array([r['prescribed_depth_m']*1000 for r in rows])
    a = np.array([r['a_control_uT'] for r in rows])
    assert np.isfinite(np.r_[d, a]).all() and np.all(np.diff(d) >= -1e-9)
    points = []
    for lo in np.arange(2, 16, .25):
        mask = (d >= lo) & (d < lo+.25)
        if mask.sum() < 5:
            continue
        point = dict(run=name, bin_lower_mm=float(lo), depth_mm=float(d[mask].mean()),
                     amplitude_uT=float(a[mask].mean()), std_uT=float(a[mask].std()),
                     samples=int(mask.sum()))
        bin_rows.append(point)
        points.append([point['depth_mm'], point['amplitude_uT']])
    points = np.asarray(points)
    assert points[0, 0] < DEPTH[0] and points[-1, 0] > DEPTH[-1]
    # Only retain the well-repeated deeper portion of the descending-Z sweep.
    curve = np.interp(DEPTH, points[:, 0], points[:, 1])
    assert np.all(np.diff(curve) > 0), 'Source curve is not monotonic; do not silently sort it.'
    curves.append(curve)
    source = dict(folder=name, run_id=manifest['run_id'], profile=profile,
                  source_sha256={f: hashlib.sha256((p/f).read_bytes()).hexdigest()
                                 for f in ['manifest.json', 'settings.json', 'identification.json',
                                           'segments.json', 'control.jsonl', 'sensor.csv']})
    sources.append(source)
    if len(sources) == 1:
        first_settings, first_profile = settings, profile
    else:
        assert settings == first_settings and profile == first_profile

curves = np.array(curves)
mean = curves.mean(axis=0)
assert np.all(np.diff(mean) > 0)
table = dict(version=1, feature='filtered_dBxy_norm_uT', approved=False,
             transient_approved=False, context={k:first_settings[k] for k in CONTEXT_KEYS},
             directions=['+x'], speed_mm_s=10., amplitude_uT=mean.tolist(),
             depth_mm=DEPTH.tolist(), source_runs=[str(RAW/n) for n in NAMES],
             fit_method='0.25 mm command-depth bins; each run interpolated on 5..15 mm; equal-run mean; monotone piecewise-linear inverse',
             artifact_role='experimental_candidate_not_tracking_validated',
             source_condition=dict(z_entry_mm=38., ry_entry_deg=30., ry_write_deg=15.,
                                   sweep_z_mm=[38.,24.], sweep_duration_s=30.,
                                   x_speed_mm_s=10., branch='increasing_depth_only'),
             source_provenance=sources,
             limitations=['No extrapolation; 60 uT is unsupported.',
                          'No reverse-branch or delay compensation.',
                          'Z36 rotational entry and arbitrary target histories are not validated by Z38 source sweeps.',
                          'The six local perturbation runs diagnose dynamics; they are not mixed into this continuous sweep table.',
                          'Existing generic StrokePlan executor lowers at fixed Ry15; it does not reproduce rotational entry.'])
table['calibration_id'] = 'slow-sweep-nonlinear-'+hashlib.sha256(json.dumps(table, sort_keys=True).encode()).hexdigest()[:16]
validate_table(table)
assert np.allclose(lookup_depth_m(table, mean)*1000, DEPTH, atol=1e-12, rtol=0)
for target in [60., float(mean[0]-.01), float(mean[-1]+.01)]:
    try:
        lookup_depth_m(table, [target])
    except ValueError:
        pass
    else:
        raise AssertionError('Out-of-range lookup should fail')

delta = curves[1]-curves[0]
metrics = dict(calibration_id=table['calibration_id'], source_folders=NAMES,
               knots=len(DEPTH), depth_support_mm=[float(DEPTH[0]), float(DEPTH[-1])],
               z_support_mm=[float(40-DEPTH[-1]), float(40-DEPTH[0])],
               amplitude_support_uT=[float(mean[0]), float(mean[-1])],
               source_repeat_mae_uT=float(abs(delta).mean()),
               source_repeat_p95_uT=float(np.percentile(abs(delta),95)),
               source_repeat_max_uT=float(abs(delta).max()),
               pooled_fit_mae_uT=float(abs(curves-mean).mean()),
               pooled_fit_note='In-sample deviation from the two-run mean; not target tracking error.',
               knot_gain_range_uT_per_mm=[float(np.min(np.diff(mean)/np.diff(DEPTH))),
                                        float(np.max(np.diff(mean)/np.diff(DEPTH)))],
               validation='Schema, strict monotonicity, units, endpoint round-trip and out-of-range rejection checked offline. No hardware validation.')
OUT.mkdir(parents=True, exist_ok=False)
dump(OUT/'feedforward.json', table)
dump(OUT/'fit_metrics.json', metrics)
csv_write(OUT/'source_bins.csv', bin_rows)
csv_write(OUT/'forward_knots.csv', [dict(depth_mm=float(d), z_mm=float(40-d),
             slow2_uT=float(c1), rerecord_uT=float(c2), amplitude_uT=float(a),
             difference_uT=float(c2-c1)) for d,c1,c2,a in zip(DEPTH,*curves,mean)])
targets = np.unique(np.r_[mean[0], np.arange(80.,321.,10.), mean[-1]])
lookup = [dict(target_uT=float(g), depth_mm=float(d*1000), z_mm=float(40-d*1000))
          for g,d in zip(targets, lookup_depth_m(table, targets))]
csv_write(OUT/'lookup_target_to_z.csv', lookup)
plt.rcParams.update({'font.family':'Noto Sans CJK JP','axes.unicode_minus':False,
                     'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
fig, axes = plt.subplots(2,2,figsize=(13,9),layout='constrained')
ax=axes[0,0]
ax.plot(DEPTH,curves[0],label='正常慢扫 14:28',color='#2563eb')
ax.plot(DEPTH,curves[1],label='复录慢扫 15:02',color='#dc2626')
ax.plot(DEPTH,mean,'k--',label='两笔均值：前馈正向曲线')
ax.set(xlabel='名义压深 d=40−Z / mm',ylabel='EMA |ΔBxy| / µT',title='实测非线性关系：仅取下压分支')
ax.legend(fontsize=8)
ax=axes[0,1]
g=np.linspace(mean[0],mean[-1],1501)
ax.plot(g,40-lookup_depth_m(table,g)*1000,color='#7c3aed',label='当前表：目标 → Z')
old=json.loads((ROOT/'runs/brush2/plans/ry15_rz0_suite_60_200_v1/feedforward.json').read_text())
ax.plot(g,40-lookup_depth_m(old,g)*1000,color='#64748b',ls='--',label='原梯子实验表（历史比较）')
ax.axhline(30,color='#d97706',ls=':',label='Z30 mm')
ax.set(xlabel='目标磁响应 / µT',ylabel='前馈 TCP Z / mm',title='执行器实际使用的反查曲线')
ax.legend(fontsize=8)
ax=axes[1,0]
ax.axhspan(-20,20,color='#16a34a',alpha=.08)
ax.plot(DEPTH,delta,color='#2563eb',label='复录−正常慢扫')
ax.axhline(0,color='gray',lw=.7)
ax.set(xlabel='名义压深 / mm',ylabel='同深度响应差 / µT',title=f'源数据重复差 MAE {metrics["source_repeat_mae_uT"]:.2f} µT；不是跟踪误差')
ax.legend(fontsize=8)
ax=axes[1,1]
ax.step((DEPTH[1:]+DEPTH[:-1])/2,np.diff(mean)/np.diff(DEPTH),where='mid',color='#059669')
ax.set(xlabel='名义压深 / mm',ylabel='表内斜率 / (µT/mm)',title='表内 K 随深度变化；不是已验证的动态增益')
for ax in axes.flat:ax.grid(alpha=.2)
fig.suptitle('首版非线性前馈｜+X 10 mm/s，Ry15，EMA α=0.3｜实测下压曲线，不外推',fontsize=15)
fig.savefig(OUT/'非线性前馈表.png',dpi=180,bbox_inches='tight')
fig.savefig(OUT/'非线性前馈表.pdf',bbox_inches='tight')
plt.close(fig)
if Path(__file__).resolve() != (OUT/'reproduce_table.py').resolve():
    shutil.copy2(__file__,OUT/'reproduce_table.py')
print(json.dumps(dict(output=str(OUT),metrics=metrics,lookup=lookup),ensure_ascii=False,indent=2))
