"""USB 五个信号过孔局部缩孔候选，原生检查前不覆盖主候选。"""
from pathlib import Path
from refine_clone_usb_20260928 import *
from check_pcb_a5 import U

src=Path('/Users/liuchunyu/Downloads/PCBUSBnativeH20260929.json')
d,p,c,h=parse(src);log=[]
for i,s in enumerate(d['shape']):
    a=s.split('~')
    if a[0]=='VIA' and a[4].startswith('USB_D'):
        log.append({'孔':a[6],'原外径孔径_mm':[float(a[3])*U,float(a[5])*2*U],'新外径孔径_mm':[.25,.15]})
        a[3]=f'{.25/U:.8f}';a[5]=f'{.075/U:.8f}';d['shape'][i]='~'.join(a)
assert len(log)==5
d['DRCRULE']['usb']['viaHoleDiameter']=.25/U;d['DRCRULE']['usb']['viaHoleD']=.15/U
for n in d.get('routerRule',{}).get('specialNets',[]):
    if n['net'].startswith('USB_D'):n['viaHoleDiameter']=f'{.25/U}px';n['viaHoleD']=f'{.15/U}px'
for i,s in enumerate(d['shape']):
    if s.startswith('COPPERAREA~'):
        a=s.split('~');a[10]='';d['shape'][i]='~'.join(a)
dest=Path('/Users/liuchunyu/Downloads/PCBUSBsmallViaTrial20260929.json')
dest.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
dest.with_suffix('.report.json').write_text(json.dumps({'来源SHA256':hashlib.sha256(src.read_bytes()).hexdigest(),'日志':log,'线宽间距不变':True,'原生复查':False},ensure_ascii=False,indent=2)+'\n')
print(json.dumps(log,ensure_ascii=False,indent=2))
