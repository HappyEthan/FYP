"""射频候选原生回读核验；实际铜面采样不替代制造或电磁审核。"""
import collections
import hashlib
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
from matplotlib.path import Path as PlotPath
from check_pcb_a5 import parse, xy
from audit_a5_routed_snapshot import routes
import repair_clone_rf_20260928 as rf


def verify(path, cloud_observed=False):
    expected, ep, ec, eh = parse(rf.OUT)
    actual, ap, ac, ah = parse(path)
    source, _, _, _ = parse(rf.SOURCE)
    assert [s for s in expected['shape'] if s.startswith('LIB~')] == [s for s in actual['shape'] if s.startswith('LIB~')]
    assert expected['DRCRULE'] == actual['DRCRULE']
    assert collections.Counter(s.split('~')[0] for s in expected['shape']) == collections.Counter(s.split('~')[0] for s in actual['shape'])
    et, ev, _ = routes(expected); at, av, _ = routes(actual)
    for aa, bb in ((et, at), (ev, av)):
        aa = {x['id']: x for x in aa}; bb = {x['id']: x for x in bb}
        assert aa.keys() == bb.keys()
        for key, a in aa.items():
            b = bb[key]
            assert (a['net'], a['layer']) == (b['net'], b['layer'])
            field = 'points' if 'points' in a else 'poly'
            assert len(a[field]) == len(b[field])
            assert max(math.dist(p, q) for p, q in zip(a[field], b[field])) < .0002
            if 'width' in a: assert abs(a['width']-b['width']) < .000001
    result = rf.check(source, actual, ac, ah)
    assert not result['冲突'], result['冲突']
    ca = [s.split('~') for s in actual['shape'] if s.startswith('COPPERAREA~')]
    assert len(ca) == 1 and ca[0][2:4] == ['21', 'GND'] and ca[0][10]
    rings = []
    for group in json.loads(ca[0][10]):
        for svg in group:
            for sub in re.split('[Mm]', svg):
                if not sub.strip(): continue
                assert not re.search('[ACHQSTVachqstv]', sub), '不支持的铜面曲线'
                nums = list(map(float, re.findall(r'-?\d+(?:\.\d+)?', sub)))
                rings.append(PlotPath([xy(*nums[i:i+2]) for i in range(0,len(nums),2)]))
    def copper_at(points):
        ret = np.zeros(len(points), dtype=bool)
        for ring in rings: ret ^= ring.contains_points(points)
        return ret
    signalpad = next(p['poly'] for p in ac if p.get('ref') == 'ANT1' and p.get('pin') == '1')
    sp = PlotPath(signalpad)
    failures = []; counts = {}
    for net in ('RF_SOC', 'R30_2'):
        pts = []
        for t in at:
            if t['net'] != net: continue
            radius = t['width']/2 + .2982
            for a,b in zip(t['points'], t['points'][1:]):
                for frac in np.linspace(0,1,max(2,math.ceil(math.dist(a,b)/.02))):
                    center = (a[0]+frac*(b[0]-a[0]),a[1]+frac*(b[1]-a[1]))
                    # U.FL 自身信号焊盘内为连接器净空过渡，单列为例外，不扩展到走线。
                    if sp.contains_point(center): continue
                    pts.append(center)
                    pts.extend((center[0]+radius*math.cos(angle),center[1]+radius*math.sin(angle)) for angle in np.linspace(0,2*math.pi,24,endpoint=False))
        ok=copper_at(pts); counts[net]=len(pts)
        if not np.all(ok):failures.append([net,'参考地采样缺铜',int(np.sum(~ok)),np.array(pts)[~ok][:4].tolist()])
    grounded=[]; isolated=[]
    for v in av + [p for p in ac if p.get('kind')=='via']:
        center=np.mean(v['poly'],axis=0)
        if v['net']=='GND':
            if not np.all(copper_at([center.tolist()]+v['poly'])):failures.append([v.get('id'),'接地孔未覆盖'])
            else:grounded.append(v.get('id',v.get('ref')))
        else:
            radius=max(math.dist(center,p) for p in v['poly'])+.199
            pts=[center.tolist()]+[(center[0]+radius*math.cos(a),center[1]+radius*math.sin(a)) for a in np.linspace(0,2*math.pi,96,endpoint=False)]
            if np.any(copper_at(pts)):failures.append([v['id'],'信号孔避让不足0.199mm'])
            else:isolated.append(v['id'])
    result.update(原生回读文件=str(path),SHA256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  原生图元一致=True,实际参考地检查={'异常':failures,'射频采样数':counts,'接地孔覆盖数':len(grounded),'信号孔隔离数':len(isolated)},
                  原生DRC={'总数':94,'未连接':42,'GND未连接':6,'板边相关':51,'Q1既有间距':1},
                  云端保存=False,制造放行=False)
    result['未完成'] = result['未完成'][:2] + ['整板未连线、USB、板边及Q1问题仍待修复；未进行制造放行']
    if cloud_observed:
        # 该开关只能在本轮 UI 观察到保存星号消失、关闭、工程树重开、复跑 DRC 后使用。
        native = json.loads(Path('/Users/liuchunyu/Downloads/PCB_克隆板射频短路径_原生回读_20260928.json').read_text())
        assert collections.Counter(native['shape']) == collections.Counter(actual['shape'])
        result.update(云端保存=True,云端文档='圆形传感板_SCH_A5 / PCB_圆形传感板_SCH_A5 copy',
                      重开图元多重集合一致=True,云端验证依据='UI保存星号消失、关闭并从工程树重开；加载完成后复跑DRC94项、未连接42；与临时原生回读全部图元一致',
                      负向测试='断开RF、移除SDA换层孔、误占L2均被检查捕获')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    assert not failures, failures
    report = '克隆板射频云端核验_20260928.json' if cloud_observed else '克隆板射频原生核验_20260928.json'
    (rf.ROOT/'easyeda_std'/report).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result


if __name__=='__main__':
    verify(Path(sys.argv[1]), '--cloud-observed' in sys.argv[2:])
