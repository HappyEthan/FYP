"""Explicit recipe for the authorized single-path FF versus P comparison."""
from pathlib import Path
import csv, hashlib, json, shutil
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from brushbot.target_strokeplan import Stroke, StrokePlan, FEATURE
from brushbot.experiments.strokeplan_entry import DEFAULT_ENTRY
from brushbot.experiments.strokeplan_execution import compile_recorded_plan
from brushbot.feedforward import lookup_depth_m, require_execution_approval

ROOT=Path('/home/ethan/FYP')
SOURCE=ROOT/'runs/brush2/plans/05_慢扫非线性前馈表'
OUT=ROOT/'runs/brush2/plans/06_难曲线160到240_FF与P'
P_PROFILE=dict(kp=2.,ki=0.,max_correction_mm=.4,max_correction_speed_mm_s=5.,
               max_correction_accel_mm_s2=70.,taper_ticks=25)
entry=dict(DEFAULT_ENTRY)
settings=json.loads((SOURCE/'settings.json').read_text())
settings['provenance']='Runtime fields copied from completed 2026-09-25 16:12:58 run; this comparison explicitly uses separate entry_profile.json for Z36 rotational contact. No new site measurement claimed.'
table=json.loads((SOURCE/'feedforward.json').read_text())
# The user explicitly requested this FF/P hardware comparison. Adoption approval
# is scoped to this copied trial table, not a claim that tracking was validated.
table.update(approved=True,transient_approved=True,
    approval_note='User requested the nonlinear FF versus FF+P experimental comparison, one difficult 160..240 uT path. Trial adoption only, not tracking-performance validation.',
    approval_scope='06_难曲线160到240_FF与P; rotational Z36 entry; single run after operator RUN',
    candidate_source_sha256=hashlib.sha256((SOURCE/'feedforward.json').read_bytes()).hexdigest())
require_execution_approval(table,settings)
t=np.arange(2001)*.02
anchors_t=np.array([0,3,7,9,11,12,14,15,18,19,20.5,21.5,24.5,26,28,29,31,32,35,37,40.])
anchors_g=np.array([160,160,240,240,180,180,230,230,160,160,240,240,175,175,220,220,160,160,240,160,160.])
g=np.full(len(t),float(anchors_g[-1]))
for begin,end,low,high in zip(anchors_t[:-1],anchors_t[1:],anchors_g[:-1],anchors_g[1:]):
    use=(t>=begin)&(t<=end)
    u=(t[use]-begin)/(end-begin)
    g[use]=low+(high-low)*u**3*(10-15*u+6*u*u)
# Measurement starts at paper X39 mm after 1 s sliding + 3 s loading.
xy=np.c_[.039+.01*t,np.zeros(len(t))]
plan=StrokePlan([Stroke(t/40,xy,t,g)],dict(source='synthetic',coordinate_frame='paper',
    feature=FEATURE,filter_definition={'kind':'ema','alpha':.3},
    description='Single difficult 160..240 uT smooth multilevel path; +X400 mm in 40 s at 10 mm/s; starts at paper X39 mm after separate preparation',
    anchor_time_s=anchors_t.tolist(),anchor_target_uT=anchors_g.tolist(),
    interpolation='quintic smoothstep per adjacent anchor',cruise_speed_mm_s=10.))
plan.validate()
results={}
for mode in ['feedforward','p']:
    c=compile_recorded_plan(plan,table,settings,label='hard_'+mode,control_mode=mode,
        feedback_profile=P_PROFILE if mode=='p' else None,entry_profile=entry)
    results[mode]=c
assert np.array_equal(results['feedforward']['pose_m_rad'],results['p']['pose_m_rad'])
OUT.mkdir(parents=True,exist_ok=False)
plan.save(OUT/'hard_160_240.npz')
for name,value in [('feedforward.json',table),('settings.json',settings),
                   ('entry_profile.json',entry),('p_profile.json',P_PROFILE)]:
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
loaded=StrokePlan.load(OUT/'hard_160_240.npz');loaded.validate()
c=results['feedforward'];poses=c['pose_m_rad'];measure=c['phase']=='measure_00'
v=np.diff(np.vstack([poses[0,:3],poses[:,:3],poses[-1,:3]]),axis=0)/.02
acc=np.linalg.norm(np.diff(v,axis=0)/.02,axis=1)*1000
writing=poses[measure]
v_w=np.diff(writing[:,:3],axis=0)/.02
scal=(table['depth_mm'][-1]-table['depth_mm'][0])/(table['amplitude_uT'][-1]-table['amplitude_uT'][0])
summary=dict(target_range_uT=[float(g.min()),float(g.max())],measurement_duration_s=40.,
    measurement_length_mm=400.,total_paper_travel_mm=450.,cruise_speed_mm_s=10.,
    measurement_x_mm=[float(writing[0,0]*1000),float(writing[-1,0]*1000)],
    paper_x_mm=[float(poses[:,0].min()*1000),float(poses[:,0].max()*1000)],
    nominal_measurement_z_mm=[float(writing[:,2].min()*1000),float(writing[:,2].max()*1000)],
    p_worst_amplitude_z_mm=[float(writing[:,2].min()*1000-.4),float(writing[:,2].max()*1000+.4)],
    full_duration_s=float(c['t_s'][-1]),max_nominal_z_speed_mm_s=float(abs(v_w[:,2]).max()*1000),
    max_nominal_accel_mm_s2=float(acc.max()),max_target_rate_uT_s=float(abs(np.diff(g)).max()/.02),
    ff_p_nominal_paths_identical=True,p_profile=P_PROFILE,
    p_global_scaling_mm_per_uT=float(scal),p_effective_mm_per_uT=float(2*scal),
    p_static_amplitude_cap_error_uT=float(.4/(2*scal)),
    full_target_sha256=hashlib.sha256((OUT/'hard_160_240.npz').read_bytes()).hexdigest(),
    calibration_id=table['calibration_id'],hardware_executed=False,
    run_order=['feedforward repeat1','p repeat1','p repeat2','feedforward repeat2'],
    note='ABBA order reduces linear order drift; two repeats do not remove wetting/contact variation. Dynamic P commands are bounded online, not predicted by this nominal compile.')
(OUT/'validation.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
with (OUT/'compiled_nominal.csv').open('x',newline='') as f:
    w=csv.writer(f);w.writerow(['t_s','phase','x_mm','y_mm','z_ff_mm','ry_deg','target_uT'])
    for ti,phase,pose,ref in zip(c['t_s'],c['phase'],poses,c['g_ref_uT']):
        w.writerow([ti,phase,*(pose[:3]*1000),np.rad2deg(pose[4]),ref if np.isfinite(ref) else ''])
plt.rcParams.update({'font.family':'Noto Sans CJK JP','axes.unicode_minus':False,'font.size':11})
fig,axes=plt.subplots(3,1,figsize=(13,9),layout='constrained')
axes[0].plot(t,g,color='#2563eb');axes[0].set(ylabel='磁目标 / µT',title='唯一测试曲线：160–240 µT，多次反转、快慢升降与短平台')
z=writing[:,2]*1000
axes[1].plot(t,z,color='#7c3aed',label='两种模式共同的名义前馈 Z')
axes[1].fill_between(t,z-.4,z+.4,color='#f59e0b',alpha=.18,label='P 修正幅值上限 ±0.4 mm（实际还受速度/加速度与首尾渐消约束）')
axes[1].set(ylabel='TCP Z / mm');axes[1].legend(fontsize=9)
axes[2].plot(c['t_s'],poses[:,2]*1000,label='Z',color='#7c3aed')
ar=axes[2].twinx();ar.plot(c['t_s'],np.rad2deg(poses[:,4]),color='#059669',label='Ry')
ar.set_ylabel('Ry / deg');axes[2].set(xlabel='时间 / s（上两图为测量时间，下图为完整轨迹时间）',ylabel='TCP Z / mm',title='共同进笔：Ry30 → Z36 → 固定 XYZ 转 Ry15 → +X 滑动加载')
axes[2].axvspan(c['t_s'][measure][0],c['t_s'][measure][-1],color='#2563eb',alpha=.07,label='measure_00')
axes[2].legend(fontsize=9)
for ax in axes:ax.grid(alpha=.2)
fig.savefig(OUT/'对比实验预览.png',dpi=180,bbox_inches='tight')
fig.savefig(OUT/'对比实验预览.pdf',bbox_inches='tight')
plt.close(fig)
shutil.copy2(__file__,OUT/'reproduce_trial.py')
print(json.dumps(summary,ensure_ascii=False,indent=2))
