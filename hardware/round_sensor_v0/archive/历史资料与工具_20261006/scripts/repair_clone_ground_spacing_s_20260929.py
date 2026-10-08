"""S局部试排：只移动V313并延长T333；原生验收之前禁止纳入云端。"""
import copy
import hashlib
import json
import math
from pathlib import Path

from check_pcb_a5 import ROOT, U, xy, parse, distance
from refine_clone_usb_20260928 import configure, batch, old_losses
from repair_clone_inner_layer_20260928 import path_text

ARCHIVE = ROOT / 'archive/S孔距核验与R恢复_20260929'
SOURCE = ARCHIVE / 'PCB_GND间距修正前_20260929.json'
SHA = '455fbafc11054187b3b1ac91a3d30f51374d35c1965463b4bd919355660b0a20'
OUT = ARCHIVE / 'PCB_GND孔距S_未原生验收_20260929.json'


def via_gaps(doc):
    vs = []
    for s in doc['shape']:
        for raw in s.split('#@$'):
            f = raw.split('~')
            if f[0] == 'VIA':
                vs.append((f[6], xy(f[1], f[2]), 2*float(f[5])*U))
    return sorted((math.dist(a[1], b[1])-(a[2]+b[2])/2, a[0], b[0])
                  for i,a in enumerate(vs) for b in vs[:i])


def main():
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == SHA
    d,p,c,h = parse(SOURCE)
    configure()
    t = copy.deepcopy(d)
    changed = []
    target = (18.793196, -86.16315)
    for i,s in enumerate(t['shape']):
        f = s.split('~')
        if f[0] == 'VIA' and f[6] == 'ggeUSB0928V313':
            f[1:3] = path_text([target]).split()
        elif f[0] == 'TRACK' and f[5] == 'ggeUSB0928T333':
            # 起点保留原值，不引入无关坐标舍入。
            f[4] = ' '.join(f[4].split()[:2]) + ' ' + path_text([target])
        else:
            continue
        t['shape'][i] = '~'.join(f)
        changed.append(t['shape'][i])
    assert len(changed) == 2
    issues = batch.check_new(t,c,h,changed)
    assert not issues, issues
    losses = {n:old_losses(d,c,t,c,n) for n in {x['net'] for x in c} if n}
    assert not any(losses.values()), losses
    gaps = via_gaps(t)
    assert gaps[0][0] >= .2, gaps[:5]
    smt = min((distance([target],v['poly'])-.0750062,v['ref'],v['pin'])
              for v in c if v['kind']=='pad' and v['layer'] in ('1','2'))
    assert smt[0] >= .1, smt
    assert [s for s in d['shape'] if s.startswith('LIB~')] == [s for s in t['shape'] if s.startswith('LIB~')]
    for i,s in enumerate(t['shape']):
        if s.startswith('COPPERAREA~'):
            f=s.split('~'); f[10]=''; t['shape'][i]='~'.join(f)
    OUT.write_text(json.dumps(t,ensure_ascii=False,indent=2)+'\n')
    report = {'来源SHA256':SHA,'候选SHA256':hashlib.sha256(OUT.read_bytes()).hexdigest(),
              '移动GND孔':'ggeUSB0928V313','位移_mm':[.08,0], '新坐标_mm':target,
              '仅联动导线':'ggeUSB0928T333','最小十组过孔孔边距_mm':gaps[:10],
              '移动孔钻边至最近SMT焊盘_mm':smt,'本地新增铜距错误':issues,
              '端点连通退化':False,'元件规则_USB_RF几何不变':True,
              '原生检查通过':False,'云端保存':False,'允许生产':False}
    OUT.with_suffix('.report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
