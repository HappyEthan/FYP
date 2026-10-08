"""补 USB 插座剩余供电支路，限定长度，不改云端。"""
from refine_clone_usb_20260928 import *

configure();batch.STEP=.04
doc,p,c,h=parse(OUT);gs=batch.island_contacts(doc,c,'USB_5V')
if len(gs)==1:print('USB_5V 已接通');sys.exit(0)
assert len(gs)==2
for width in [.2,.15]:
    trial=copy.deepcopy(doc);_,od,drill=dimensions(doc,'USB_5V')
    ok,info=batch.route(trial,c,h,'USB_5V',gs[0],gs[1],width,od,drill)
    print('USB_POWER',width,ok,info,flush=True)
    if ok and info['长度']<10 and not local_check(trial,c,h):
        save(trial);r=json.loads(REPORT.read_text())
        r['USB插座供电脚补线']={'宽度':width,'详情':info,'原生验收':False}
        REPORT.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');break
