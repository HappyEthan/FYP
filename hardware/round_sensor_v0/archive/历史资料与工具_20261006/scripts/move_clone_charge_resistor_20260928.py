"""把 R10 移出 USB 针脚拥挤区，放到充电芯片与电池焊盘之间。"""
from refine_clone_usb_20260928 import *
from build_a5_usb_zone_placement import shift_lib_safe
from build_a5_rf_clearance_layout import ref
configure();doc,parts,oldc,h=parse(OUT);before=copy.deepcopy(doc);report=json.loads(REPORT.read_text())
target=(23.0,-72.9);delta=tuple(target[k]-parts['R10']['center'][k] for k in (0,1))
assert math.dist(parts['R10']['center'],(21.25,-76.9))<.001
for i,s in enumerate(doc['shape']):
    if s.startswith('LIB~') and ref(s)=='R10':doc['shape'][i]=shift_lib_safe(s,delta)
ts,_,_=routes(before)
ids={t['id'] for t in ts for p in oldc if p['ref']=='R10' and shared_layer(t,p) and t['net']==p['net'] and track_gap(t,p['poly'])<=1e-4}
removed=[s for s in doc['shape'] if s.startswith('TRACK~') and s.split('~')[5] in ids]
doc['shape']=[s for s in doc['shape'] if s not in removed]
_,_,c,h=save(doc);issues=local_check(doc,c,h)
if issues:save(before);raise AssertionError(issues)
report.setdefault('充电设置电阻移位',[]).append({'原位置':parts['R10']['center'],'新位置':target,'撤回图元':removed})
report['移动元件']['R10']=target
REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print('R10_MOVED',target,len(removed),flush=True)
