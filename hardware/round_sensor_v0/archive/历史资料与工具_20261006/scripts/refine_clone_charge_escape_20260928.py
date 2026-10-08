"""从传感器信号全通候选恢复，把充电电阻移到圆板内侧空白区。"""
from refine_clone_usb_20260928 import *
from build_a5_usb_zone_placement import shift_lib_safe
from build_a5_rf_clearance_layout import ref
from pathlib import Path
configure()
gold=Path('/var/folders/6b/_qmhvjlj1dj0tqz5lb5pfzf40000gn/T/edausb-signal-ml3za3yg/before.json')
base=Path('/var/folders/6b/_qmhvjlj1dj0tqz5lb5pfzf40000gn/T/edausb-signal-waumibfv/before.json')
doc,parts,c,h=parse(gold);original,op,oc,oh=parse(base)
backup=OUT.read_bytes();report=json.loads(REPORT.read_text())
r10=next(s for s in original['shape'] if s.startswith('LIB~') and ref(s)=='R10')
r10=shift_lib_safe(r10,(-3.25,2.10))  # (21.25,-76.9) -> (18.0,-74.8)
oldground={s for s in original['shape'] if s.startswith(('TRACK~','VIA~')) and s.split('~')[3 if s.startswith('TRACK~') else 4]=='GND'}
doc['shape']=[r10 if s.startswith('LIB~') and ref(s)=='R10' else s for s in doc['shape']]
doc['shape']=[s for s in doc['shape'] if not(s.startswith(('TRACK~','VIA~')) and s.split('~')[3 if s.startswith('TRACK~') else 4]=='GND' and PREFIX in s and s not in oldground)]
removed=[]
_,parts,c,h=save(doc)
size=len(doc['shape']);w,od,di=dimensions(doc,'U4_C1')
errors=local_check(doc,c,h)
if errors:OUT.write_bytes(backup);raise AssertionError(errors)
groups=batch.island_contacts(doc,c,'U4_C1')
start=next(g for g in groups if any(p['id'].startswith('U4.C1:') for p in g))
end=next(g for g in groups if any(p['id'].startswith('R10.1:') for p in g))
ok,info=batch.route(doc,c,h,'U4_C1',start,end,w,od,di)
print('CHARGE_ESCAPE',ok,info,flush=True)
if not ok:OUT.write_bytes(backup);raise AssertionError(info)
report['充电设置出口修复']={'恢复来源':str(gold),'R10新位置':parts['R10']['center'],'D3保持':parts['D3']['center'],'路径':info}
report['移动元件']['D3']=parts['D3']['center'];report['移动元件']['R10']=parts['R10']['center']
save(doc);REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
