"""BOOT 短出口候选：只撤回冲突的旧复位线，保留其安全段。"""
import json
from refine_clone_usb_20260928 import *
from build_clone_usb_local_20260928 import salvage
configure();doc,parts,c,h=parse(OUT);report=json.loads(REPORT.read_text())
size=len(doc['shape'])
batch.add_via(doc,'BOOT_N',(25.9,-81.0),*dimensions(doc,'BOOT_N')[1:])
batch.add_track(doc,'BOOT_N','2',[(24.8168287,-81.534),(25.3508287,-81.0),(25.9,-81.0)],dimensions(doc,'BOOT_N')[0])
old={s.split('~')[5 if s.startswith('TRACK~') else 6]:s for s in doc['shape'][:size] if s.startswith(('TRACK~','VIA~'))}
issues=batch.check_new(doc,c,h,doc['shape'][size:]);ids={x for row in issues for x in row[1:3] if x in old}
removed=[old[i] for i in ids]
assert all(s.startswith('TRACK~') and s.split('~')[3]=='MCU_EN' for s in removed),issues
doc['shape']=[s for s in doc['shape'] if s not in removed]
assert not local_check(doc,c,h),local_check(doc,c,h)
count=salvage(doc,c,h,removed)
report.setdefault('BOOT局部出口',[]).append({'撤回图元':removed,'安全段数':count,'过孔':[25.9,-81.0]})
save(doc);REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print('BOOT_ESCAPE',len(removed),count,flush=True)
