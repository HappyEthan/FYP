"""局部布局候选；读取本轮原生备份，不写源文件或云端。"""
import collections
import hashlib
import itertools
import json
import math
from pathlib import Path

from check_pcb_a5 import ROOT, parse, xy, distance, shared_layer
from build_a5_usb_zone_placement import shift_lib_safe
from build_a5_rf_clearance_layout import ref, fmt, pairs

SOURCE = ROOT / 'easyeda_std/PCB_局部重排前备份_20260918.json'
SHA = '86b8873bda296c1af7dba83a6808e389ddc50203899594760dbc7536653f5385'
OUT = ROOT / 'easyeda_std/PCB_局部重排候选_20260918.json'
TARGETS = {'J1': (23.0, 74.8), 'SW3': (28.9, 75.05), 'C9': (30.0, 77.15),
           'C10': (26.5, 78.7), 'R11': (30.75, 80.2), 'SW1': (20.0, 84.8),
           'D3': (21.4, 76.15)}


def shift_with_holes(shape, delta):
    chunks = shape.split('#@$')
    for i, chunk in enumerate(chunks):
        fields = chunk.split('~')
        if fields[0] == 'PAD' and len(fields) > 14 and fields[14].strip():
            # 长槽孔端点独立于铜轮廓，必须一同刚体平移。
            fields[14] = pairs(fields[14], delta[0]/.254, delta[1]/.254)
            chunks[i] = '~'.join(fields)
    hole_indices = [i for i,s in enumerate(chunks) if s.startswith('HOLE~')]
    # 平移只改变孔中心；圆和孔的x/y字段位置相同，其余字段保持原样。
    for i in hole_indices:
        chunks[i] = 'CIRCLE~'+chunks[i][5:]
    moved = shift_lib_safe('#@$'.join(chunks), delta).split('#@$')
    for i in hole_indices:
        moved[i] = 'HOLE~'+moved[i][7:]
    return '#@$'.join(moved)


def audit(path):
    doc, parts, copper, holes = parse(path)
    circle = next(s.split('~') for s in doc['shape']
                  if s.startswith('CIRCLE~') and s.split('~')[5] == '10')
    center = xy(circle[1], circle[2]); radius = float(circle[3]) * .254
    gaps = []
    for a, b in itertools.combinations(copper, 2):
        if a['ref'] == b['ref'] or not shared_layer(a, b):
            continue
        gap = distance(a['poly'], b['poly'])
        if gap < .1524 - .0001:
            gaps.append([a['ref']+'.'+a['pin'], b['ref']+'.'+b['pin'], round(gap, 4)])
    edges = [(radius-max(math.dist(v, center) for v in a['poly']),
              a['ref']+'.'+a['pin']) for a in copper]
    hole_gaps = []
    for h in holes:
        for a in copper:
            if a['ref'] != h['ref']:
                gap = distance(h['poly'], a['poly'])
                if gap < .2:
                    hole_gaps.append([h['ref'], a['ref']+'.'+a['pin'], round(gap, 4)])
    return {'元件数': len(parts), '铜间隙小于0.1524mm': gaps,
            '铜到板边小于0.2mm': [[r, round(g,4)] for g,r in edges if g < .2],
            '定位孔到其他铜小于0.2mm': hole_gaps,
            '最小铜到板边mm': round(min(edges)[0], 4),
            '生产放行': False}, parts, copper, holes, center, radius


def main():
    raw = SOURCE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SHA, '原生来源变化，停止'
    doc = json.loads(raw)
    assert collections.Counter(s.split('~')[0] for s in doc['shape']) == {'LIB':43,'CIRCLE':1}
    before, parts, copper, _, _, _ = audit(SOURCE)
    changed = []
    for i, shape in enumerate(doc['shape']):
        if not shape.startswith('LIB~'):
            continue
        name = ref(shape)
        if name not in TARGETS:
            continue
        origin = parts[name]['center']
        if name == 'SW1':
            # 原生实例锚点脱离焊盘约100mm，先将锚点恢复至2脚，不改铜。
            chunks = shape.split('#@$'); head = chunks[0].split('~')
            pad = next(s.split('~') for s in chunks[1:]
                       if s.startswith('PAD~') and s.split('~')[8] == '2')
            head[1:3] = pad[2:4]
            chunks[0] = '~'.join(head); shape = '#@$'.join(chunks)
            origin = xy(pad[2], pad[3])
        x, y = TARGETS[name]
        doc['shape'][i] = shift_with_holes(shape, (x-origin[0], -y-origin[1]))
        changed.append(name)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2)+'\n')
    after, new_parts, new_copper, holes, center, radius = audit(OUT)
    sig = lambda cs: sorted((p['ref'],p['pin'],p['net'],p['kind'],p['layer']) for p in cs)
    assert sig(copper) == sig(new_copper), '网络或层变更'
    for part in new_parts.values():
        for pad in part['items']:
            if pad[0] == 'PAD' and len(pad) > 14 and pad[14].strip():
                points = list(map(float, pad[14].split()))
                assert abs(sum(points[::2])/len(points[::2])-float(pad[2])) < .001
                assert abs(sum(points[1::2])/len(points[1::2])-float(pad[3])) < .001
    assert len(new_parts) == 43
    assert all(a == b for a,b in zip(json.loads(raw)['shape'],doc['shape'])
               if not a.startswith('LIB~') or ref(a) not in TARGETS)
    report = {'来源SHA256': SHA, '仅调整': sorted(changed), '调整前':before, '调整后':after,
              '网络脚号与层保持':True, 'USB朝向及板框保持':True,
              '范围':'铜与定位孔几何初筛；非原生DRC、射频、热、钢网或装配放行'}
    (OUT.parent/'局部重排检查_20260918.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    assert not after['铜间隙小于0.1524mm']
    assert not after['铜到板边小于0.2mm']
    assert not after['定位孔到其他铜小于0.2mm']


if __name__ == '__main__':
    main()
