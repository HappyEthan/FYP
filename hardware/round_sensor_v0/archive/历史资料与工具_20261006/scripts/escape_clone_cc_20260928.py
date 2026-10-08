"""CC 局部出口：微调 R2 并改放一个回流地孔，不改变规则或封装。"""
from refine_clone_usb_20260928 import *
from build_clone_usb_local_20260928 import salvage
from build_a5_usb_zone_placement import shift_lib_safe
from build_a5_rf_clearance_layout import ref
from check_pcb_a5 import U,ORIGIN
configure();doc,parts,oldc,h=parse(OUT);before=copy.deepcopy(doc);report=json.loads(REPORT.read_text());moved_vias=set()
delta=(0,-74.35-parts['R2']['center'][1])
assert abs(delta[1]-.199)<.001
for i,s in enumerate(doc['shape']):
    if s.startswith('LIB~') and ref(s)=='R2':doc['shape'][i]=shift_lib_safe(s,delta)
    elif s.startswith('VIA~') and PREFIX in s:
        v=s.split('~')
        if v[4]=='GND' and math.dist(batch.center(next(x for x in routes({'shape':[s]})[1])),(21.35,-75.12))<.001:
            v[1]=str(21.9/U+ORIGIN[0]);v[2]=str(-74.25/U+ORIGIN[1]);doc['shape'][i]='~'.join(v);moved_vias.add(v[6])
ts,_,_=routes(before)
touch={t['id'] for t in ts for p in oldc if p['ref']=='R2' and shared_layer(t,p) and t['net']==p['net'] and track_gap(t,p['poly'])<=1e-4}
removed=[s for s in doc['shape'] if s.startswith('TRACK~') and s.split('~')[5] in touch]
doc['shape']=[s for s in doc['shape'] if s not in removed]
_,_,c,h=save(doc)
size=len(doc['shape']);w,od,di=dimensions(doc,'J1_A5')
batch.add_via(doc,'J1_A5',(21.0,-75.05),od,di)
batch.add_track(doc,'J1_A5','1',[(21.736939,-77.18044),(21.736939,-75.80),(21,-75.063061),(21,-75.05)],w)
issues=local_check(doc,c,h)
old={s.split('~')[5 if s.startswith('TRACK~') else 6]:s for s in doc['shape'][:size] if s.startswith(('TRACK~','VIA~'))}
ids={x for row in issues for x in row[1:3] if x in old and x not in moved_vias}
extra=[old[i] for i in ids]
if not all(s.split('~')[3 if s.startswith('TRACK~') else 4] in ('GND','J1_B5','I2C_SCL') for s in extra):
    save(before);raise AssertionError(issues)
removed+=extra;doc['shape']=[s for s in doc['shape'] if s not in extra]
issues=local_check(doc,c,h)
if issues:save(before);raise AssertionError(issues)
count=salvage(doc,c,h,removed)
report.setdefault('CC局部出口',[]).append({'R2新中心':[20.701,-74.35],'地孔新中心':[21.9,-74.25],'CC孔':[21,-75.05],'撤回图元':removed,'安全段':count})
save(doc);REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print('CC_ESCAPE',len(removed),count)
