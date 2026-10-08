"""底层地铜候选：3h 侧向距离级别，保留 U.FL 本体全层禁铜区。需原生重建。"""
from refine_clone_usb_20260928 import *
from check_pcb_a5 import U
import argparse
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--source',type=Path,default=OUT);p.add_argument('--output',type=Path,default=OUT);p.add_argument('--report',type=Path,default=REPORT)
args=p.parse_args()
configure();doc,parts,c,h=parse(args.source);report=json.loads(REPORT.read_text())
assert not any(s.startswith('COPPERAREA~') and s.split('~')[2]=='2' for s in doc['shape'])
plane=next(s.split('~') for s in doc['shape'] if s.startswith('COPPERAREA~') and s.split('~')[2]=='21')
plane[2]='2';plane[5]=f'{.3/U:.8f}';plane[7]=PREFIX+'GNDBottom';plane[10]='';plane[12]='底层回流地_待原生验收'
doc['shape'].append('~'.join(plane))
cutout=next(s.split('~') for s in doc['shape'] if s.startswith('SOLIDREGION~') and s.split('~')[1]=='21')
cutout[1]='2';cutout[5]=PREFIX+'UFLBottom';doc['shape'].append('~'.join(cutout))
for i,s in enumerate(doc['shape']):
    if s.startswith('COPPERAREA~'):
        v=s.split('~');v[10]='';doc['shape'][i]='~'.join(v)
report['底层地铜候选']={'异网避让_mm':.3,'UFL禁铜区':'复用已存在的内层1本体禁铜范围','原生重建':False,'回流验收':False}
args.output.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n');args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print('BOTTOM_GROUND_CANDIDATE',flush=True)
