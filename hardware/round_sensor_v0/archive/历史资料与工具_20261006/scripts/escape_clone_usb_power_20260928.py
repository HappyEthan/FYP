"""局部电源出口实验：缩紧参考地区域，保留 USB 邻域；不写云端。"""
import json
from refine_clone_usb_20260928 import *
from check_pcb_a5 import U,ORIGIN

configure();doc,parts,c,h=parse(OUT)
report=json.loads(REPORT.read_text())
for i,s in enumerate(doc['shape']):
    if s.startswith('COPPERAREA~') and PREFIX+'GNDL3' in s:
        v=s.split('~');v[10]=''
        v[4]='M '+' L '.join(f'{x/U+ORIGIN[0]:.8f} {y/U+ORIGIN[1]:.8f}' for x,y in GROUND_ZONE)+' Z'
        doc['shape'][i]='~'.join(v)
size=len(doc['shape'])
batch.add_via(doc,'3V3',(24.28,-80.96),.4,.2)
batch.add_track(doc,'3V3','2',[(23.9511713,-80.391),(23.9511713,-80.6311713),(24.28,-80.96)],.2500122)
issues=batch.check_new(doc,c,h,doc['shape'][size:])
old={s.split('~')[5 if s.startswith('TRACK~') else 6]:s for s in doc['shape'][:size] if s.startswith(('TRACK~','VIA~'))}
ids={item for row in issues for item in row[1:3] if item in old}
removed=[old[i] for i in ids]
assert all(s.split('~')[3 if s.startswith('TRACK~') else 4] in ('BOOT_N','MCU_EN') for s in removed),issues
doc['shape']=[s for s in doc['shape'] if s not in removed]
errors=local_check(doc,c,h)
assert not errors,errors
report.setdefault('局部电源出口修复',[]).append({'过孔':[24.28,-80.96],'撤回图元':removed,'参考地区域':GROUND_ZONE})
save(doc);REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print('POWER_ESCAPE',len(removed),errors)
