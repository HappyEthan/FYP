"""Generate independent synthetic targets and offline execution previews."""
from pathlib import Path
import csv, hashlib, json, shutil
import numpy as np
from scripts.generate_strokeplan import generate
from brushbot.target_strokeplan import StrokePlan
from brushbot.experiments.strokeplan_execution import compile_recorded_plan

ROOT=Path('/home/ethan/FYP')
OUT=ROOT/'runs/brush2/plans/05_慢扫非线性前馈表'
SETTINGS_SOURCE=ROOT/'runs/brush2/2026-09-25/05_Z动态辨识/raw/16-12-58_压深5mm_扰动1mm_先下压_第4次/settings.json'
table=json.loads((OUT/'feedforward.json').read_text())
settings=json.loads(SETTINGS_SOURCE.read_text())
settings['provenance']='Copied without changing runtime fields from completed 2026-09-25 16:12:58 run; used for offline previews. Runtime entry remains fixed-Ry lowering in existing generic executor.'
settings['source_path']=str(SETTINGS_SOURCE)
settings['source_sha256']=hashlib.sha256(SETTINGS_SOURCE.read_bytes()).hexdigest()
(OUT/'settings.json').write_text(json.dumps(settings,ensure_ascii=False,indent=2)+'\n')

def smooth(x):
    x=np.clip(x,0,1)
    return x**3*(10-15*x+6*x*x)

x=np.linspace(0,400,4001)
profiles=[('01_gradual_160_240',160+80*smooth((x-30)/300),
           'Synthetic +X 400 mm; 160 uT first 30 mm, quintic rise over 30..330 mm, 240 uT to end'),
          ('02_arch_160_240_160',160+80*(smooth((x-30)/170)-smooth((x-200)/170)),
           'Synthetic +X 400 mm; hold 160 uT to 30 mm, quintic rise to 240 uT at 200 mm, return to 160 uT at 370 mm, hold to end')]
results=[]
for name,g,description in profiles:
    plan=generate(targets_uT=g,length_mm=400.,speed_mm_s=10.)
    plan.meta['description']=description
    plan.save(OUT/(name+'.npz'))
    loaded=StrokePlan.load(OUT/(name+'.npz'))
    st=loaded.strokes[0]
    assert np.isclose(st.g_target.min(),160) and np.isclose(st.g_target.max(),240,atol=1e-3)
    assert np.isclose(st.xy[-1,0],.4)
    compiled=compile_recorded_plan(loaded,table,settings,label='nonlinear_ff_'+name,control_mode='feedforward')
    poses=compiled['pose_m_rad'];phases=compiled['phase'];measure=phases=='measure_00'
    v=np.diff(np.vstack([poses[0,:3],poses[:,:3],poses[-1,:3]]),axis=0)/.02
    acc=np.linalg.norm(np.diff(v,axis=0)/.02,axis=1)*1000
    with (OUT/(name+'_compiled.csv')).open('x',newline='') as f:
        w=csv.writer(f);w.writerow(['time_s','phase','x_cmd_mm','y_cmd_mm','z_cmd_mm','g_target_uT'])
        for t,phase,pose,target in zip(compiled['t_s'],phases,poses,compiled['g_ref_uT']):
            w.writerow([t,phase,*(pose[:3]*1000),target if np.isfinite(target) else ''])
    results.append(dict(name=name,plan=str(OUT/(name+'.npz')),target_range_uT=[160.,240.],
                        length_mm=400.,cruise_speed_mm_s=10.,measurement_duration_s=float(st.t[-1]),
                        full_duration_s=float(compiled['t_s'][-1]),
                        commanded_z_range_mm=[float(poses[measure,2].min()*1000),float(poses[measure,2].max()*1000)],
                        x_range_mm=[float(poses[measure,0].min()*1000),float(poses[measure,0].max()*1000)],
                        max_z_speed_mm_s=float(abs(v[:,2]).max()*1000),
                        max_acceleration_mm_s2=float(acc.max()),
                        offline_compile='passed',entry_mode='existing executor: fixed Ry15 vertical lowering; not Z36 rotational entry',
                        sha256=hashlib.sha256((OUT/(name+'.npz')).read_bytes()).hexdigest()))
(OUT/'trial_validation.json').write_text(json.dumps(dict(plans=results,hardware_executed=False,
     table_execution_approved=table['approved'],transients_execution_approved=table['transient_approved']),ensure_ascii=False,indent=2)+'\n')
shutil.copy2(__file__,OUT/'reproduce_targets.py')
print(json.dumps(results,ensure_ascii=False,indent=2))
