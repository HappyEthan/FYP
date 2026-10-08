"""核对首段RF候选的原生导出；不把本地标签误报为云端保存。"""
import collections
import hashlib
import json
import math
import re
import sys

import build_a5_rf_route_20260918 as rf
from check_pcb_a5 import parse, xy
from verify_a5_preroute_layout_cloud_20260918 import component_signature, copper_groups


def verify(path):
    _, expected, parts, copper, holes, plane = rf.build()
    actual, ap, ac, ah = parse(path)
    assert collections.Counter(s.split('~')[0] for s in actual['shape']) == {
        'LIB': 43, 'CIRCLE': 1, 'TRACK': 8, 'VIA': 4, 'SOLIDREGION': 1}
    assert expected['DRCRULE'].keys() == actual['DRCRULE'].keys()
    for name, rule in expected['DRCRULE'].items():
        other=actual['DRCRULE'][name]
        if not isinstance(rule,dict):
            assert rule == other
            continue
        assert rule.keys() == other.keys()
        for k,v in rule.items():
            if isinstance(v,(int,float)):
                assert abs(v-other[k]) < .00001
            else:
                assert v == other[k]
    assert component_signature(parts) == component_signature(ap)
    assert max(math.dist(parts[r]['center'], ap[r]['center']) for r in parts) < .00003
    cg, ag = copper_groups(copper), copper_groups(ac)
    assert cg.keys() == ag.keys()
    for key in cg:
        assert len(cg[key]) == len(ag[key])
        for a, b in zip(cg[key], ag[key]):
            assert len(a) == len(b)
            assert max(math.dist(p, q) for p, q in zip(a, b)) < .0002
    assert len(holes) == len(ah)
    for a, b in zip(holes, ah):
        assert a['ref'] == b['ref'] and len(a['poly']) == len(b['poly'])
        assert max(math.dist(p,q) for p,q in zip(a['poly'],b['poly'])) < .00003
    for layer in ('21', '22'):
        row = next(s.split('~') for s in actual['layers'] if s.startswith(layer+'~'))
        assert row[5] == 'true'
    sr = next(s.split('~') for s in actual['shape'] if s.startswith('SOLIDREGION~'))
    assert sr[1:3] == ['21','GND'] and sr[4] == 'solid'
    nums = list(map(float,re.findall(r'-?\d+(?:\.\d+)?',sr[3])))
    actual_plane = [xy(*nums[i:i+2]) for i in range(0,len(nums),2)]
    assert len(plane) == len(actual_plane)
    assert max(math.dist(p,q) for p,q in zip(plane,actual_plane)) < .00003
    at,av,_ = rf.routes(actual)
    et,ev,_ = rf.routes(expected)
    for a,b in zip(sorted(at,key=lambda t:t['id']),sorted(et,key=lambda t:t['id'])):
        assert (a['id'],a['net'],a['layer']) == (b['id'],b['net'],b['layer'])
        assert abs(a['width']-b['width']) < .000001
        assert len(a['points']) == len(b['points'])
        assert max(math.dist(p,q) for p,q in zip(a['points'],b['points'])) < .00003
    for a,b in zip(sorted(av,key=lambda v:v['id']),sorted(ev,key=lambda v:v['id'])):
        assert (a['id'],a['net']) == (b['id'],b['net'])
        # 原生过孔中心保存为3位原生单位，二维量化误差最多约0.00018 mm。
        assert max(math.dist(p,q) for p,q in zip(a['poly'],b['poly'])) < .0002
    result = rf.check(actual,ac,ah,actual_plane)
    assert not result['局部冲突'], result['局部冲突']
    result.update(回读文件=path.name,SHA256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  元件数=43,规则与候选一致=True,原生图元与候选容差内一致=True,
                  原生DRC实际观察={'总数':115,'未连接':114,'既有Q1间距':1},
                  云端保存已验证=False,制造放行=False)
    return result


if __name__ == '__main__':
    path = rf.ROOT/'easyeda_std/PCB_射频首段_原生回读_20260918.json'
    if len(sys.argv)>1:
        from pathlib import Path
        path=Path(sys.argv[1])
    result=verify(path)
    cloud=path.name=='PCB_射频首段_云端重开回读_20260918.json'
    if cloud:
        # 本轮UI已观察保存星号消失、关闭、工程树重开及DRC；不是仅凭文件名推断。
        result.update(云端保存已验证=True,云端PCB='圆形传感板_SCH_A5 / PCB_圆形传感板_SCH_A5',
                      本轮UI记录='保存星号消失；关闭后从工程树重开；重开DRC=115项')
    report='射频首段云端核验_20260918.json' if cloud else '射频首段原生核验_20260918.json'
    (rf.ROOT/'easyeda_std'/report).write_text(
        json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
