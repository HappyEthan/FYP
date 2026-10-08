"""局部调整 USB5 旧斜线，给 BAT 扇出空间；不允许整体连通退化。"""
from refine_clone_usb_20260928 import *
from complete_clone_remaining_20260929 import finish

configure();doc,parts,c,h=parse(OUT);report=json.loads(REPORT.read_text())
trial=copy.deepcopy(doc)
trial['shape']=[s for s in trial['shape'] if not(s.startswith('TRACK~') and s.split('~')[5]=='gge5173039')]
assert len(trial['shape'])==len(doc['shape'])-1
gs=batch.island_contacts(trial,c,'BAT_P');assert len(gs)==2
_,od,drill=dimensions(trial,'BAT_P')
for width in [.2,.15,.1]:
    size=len(trial['shape']);ok,info=batch.route(trial,c,h,'BAT_P',gs[0],gs[1],width,od,drill)
    if ok and info['长度']>3:ok=False
    if not ok:trial['shape']=trial['shape'][:size]
    print('BAT_UNCROSS',width,ok,info,flush=True)
    if ok:break
if ok:
    batch.STEP=.04
    log=finish(trial,c,h,'USB_5V')
    good=len(connected_groups(trial,c,'BAT_P'))==1 and len(connected_groups(trial,c,'USB_5V'))<=len(connected_groups(doc,c,'USB_5V')) and not local_check(trial,c,h)
    print('ACCEPT',good,flush=True)
    if good:
        save(trial)
        report['充电电源局部交叉修复']={'移除旧线':'gge5173039','电池路线':info,'USB5修复':log,'原生验收':False}
        REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
