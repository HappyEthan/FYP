"""独立几何初筛；不代替原生 DRC、器件禁布区、Gerber 或装配审核。"""
import collections
import html
import itertools
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'easyeda_std/PCB_A5_18mm_trial_20260916.json'
U = .254
ORIGIN = (4020, 3404)


def xy(x, y):
    return ((float(x)-ORIGIN[0])*U, (float(y)-ORIGIN[1])*U)


def rect(cx, cy, w, h, angle=0):
    a = math.radians(angle)
    return [(cx+x*math.cos(a)-y*math.sin(a), cy+x*math.sin(a)+y*math.cos(a))
            for x, y in [(-w/2, -h/2), (w/2, -h/2), (w/2, h/2), (-w/2, h/2)]]


def ellipse(cx, cy, w, h):
    return [(cx+w/2*math.cos(i*math.pi/32), cy+h/2*math.sin(i*math.pi/32)) for i in range(64)]


def oval(cx, cy, w, h, rotation):
    # 长圆焊盘 pointArr 只有中心线的两个端点，不能当成铜多边形。
    r, offset = min(w, h)/2, abs(w-h)/2
    a = math.radians(-rotation + (90 if h > w else 0))
    pts = []
    for sign, start in ((1, -math.pi/2), (-1, math.pi/2)):
        for i in range(33):
            t = start + i*math.pi/32
            x, y = sign*offset+r*math.cos(t), r*math.sin(t)
            pts.append((cx+x*math.cos(a)-y*math.sin(a), cy+x*math.sin(a)+y*math.cos(a)))
    return pts


def parse(path):
    d = path if isinstance(path, dict) else json.loads(path.read_text())
    parts, copper, holes = {}, [], []
    for shape in d['shape']:
        if not shape.startswith('LIB~'):
            continue
        items = [s.split('~') for s in shape.split('#@$')]
        h = items[0]
        ref = next(v[10] for v in items[1:] if v[:2] == ['TEXT', 'P'])
        parts[ref] = {'id': h[6], 'layer': h[7], 'center': xy(h[1], h[2]), 'rotation': h[4], 'items': items[1:]}
        for v in items[1:]:
            if v[0] == 'PAD':
                x, y = xy(v[2], v[3])
                if v[1] == 'ELLIPSE':
                    poly = ellipse(x, y, float(v[4])*U, float(v[5])*U)
                elif v[1] == 'OVAL':
                    poly = oval(x, y, float(v[4])*U, float(v[5])*U, float(v[11] or 0))
                elif v[10].strip():
                    a = list(map(float, v[10].split()))
                    poly = [xy(a[i], a[i+1]) for i in range(0, len(a), 2)]
                else:
                    poly = rect(x, y, float(v[4])*U, float(v[5])*U, -float(v[11] or 0))
                copper.append({'ref': ref, 'pin': v[8], 'net': v[7], 'layer': v[6], 'poly': poly, 'kind': 'pad'})
            elif v[0] == 'VIA':
                x, y = xy(v[1], v[2])
                copper.append({'ref': ref, 'pin': v[6], 'net': v[4], 'layer': '11', 'poly': ellipse(x, y, float(v[3])*U, float(v[3])*U), 'kind': 'via'})
            elif v[0] == 'HOLE':
                x, y = xy(v[1], v[2])
                holes.append({'ref': ref, 'poly': ellipse(x, y, 2*float(v[3])*U, 2*float(v[3])*U)})
    return d, parts, copper, holes


def point_seg(p, a, b):
    vx, vy = b[0]-a[0], b[1]-a[1]
    t = max(0, min(1, ((p[0]-a[0])*vx+(p[1]-a[1])*vy)/(vx*vx+vy*vy))) if vx or vy else 0
    return math.hypot(p[0]-a[0]-t*vx, p[1]-a[1]-t*vy)


def inside(p, poly):
    hit = False
    for a, b in zip(poly, poly[1:]+poly[:1]):
        if (a[1] > p[1]) != (b[1] > p[1]) and p[0] < (b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0]:
            hit = not hit
    return hit


def distance(a, b):
    # 两条线段是退化多边形：仅用边法向SAT无法区分共线但分离的线段。
    # 先判严格交叉，否则端点到另一线段的最短距离覆盖平行/共线/接触。
    if len(a)==2 and len(b)==2:
        cross=lambda p,q,r:(q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
        if cross(a[0],a[1],b[0])*cross(a[0],a[1],b[1])<0 and cross(b[0],b[1],a[0])*cross(b[0],b[1],a[1])<0:
            return 0.
        return min(
            *(point_seg(p,*b) for p in a),*(point_seg(p,*a) for p in b))
    # 凸多边形分离轴；有交叠返回 0，否则取顶点到边的最短距离。
    separated = False
    for poly in (a, b):
        for p, q in zip(poly, poly[1:]+poly[:1]):
            n = (q[1]-p[1], p[0]-q[0])
            if n == (0, 0):
                continue
            aa = [x*n[0]+y*n[1] for x, y in a]
            bb = [x*n[0]+y*n[1] for x, y in b]
            if max(aa) < min(bb) or max(bb) < min(aa):
                separated = True
                break
        if separated:
            break
    if not separated:
        return 0.
    return min(point_seg(p, v, w) for poly, other in ((a, b), (b, a)) for p in poly for v, w in zip(other, other[1:]+other[:1]))


def shared_layer(a, b):
    return a['layer'] == b['layer'] or '11' in (a['layer'], b['layer'])


def audit(path=SOURCE, proposed=False):
    d, parts, copper, holes = parse(path)
    if proposed:
        script = (ROOT/'scripts/place_pcb_a5.js').read_text()
        positions = {r: tuple(map(float, p.split(','))) for r, p in re.findall(r'(\w+):\[([.\d,-]+)\]', script)}
        for ref, pos in positions.items():
            delta = (pos[0]-parts[ref]['center'][0], pos[1]-parts[ref]['center'][1])
            for item in copper+holes:
                if item['ref'] == ref:
                    item['poly'] = [(x+delta[0], y+delta[1]) for x, y in item['poly']]
            parts[ref]['center'] = pos
    _, old, old_copper, _ = parse(ROOT/'easyeda_std/PCB_A5_native_unplaced_20260916.json')
    signature = lambda cs: sorted((p['ref'], p['pin'], p['net'], p['kind']) for p in cs)
    assert signature(copper) == signature(old_copper), '脚号或网络发生变化'
    assert len(parts) == 41 and set(parts) == set(old)
    circle = next(s.split('~') for s in d['shape'] if s.startswith('CIRCLE~'))
    radius = float(circle[3])*U
    assert abs(radius-9) < .001
    report = {'source': path.name, 'diameter_mm': round(radius*2, 4), 'parts': len(parts),
              'layers': dict(collections.Counter(p['layer'] for p in parts.values())),
              'pads': sum(p['kind']=='pad' for p in copper), 'embedded_vias': sum(p['kind']=='via' for p in copper),
              'nets': len(set(p['net'] for p in copper if p['net'])), 'net_mapping_unchanged': True,
              'cross_part_clearance_below_0_15mm': [], 'edge_clearance_below_0_2mm': [], 'holes_to_other_copper_below_0_2mm': []}
    for a, b in itertools.combinations(copper, 2):
        if a['ref'] == b['ref'] or not shared_layer(a, b):
            continue
        gap = distance(a['poly'], b['poly'])
        if gap < .15-.0001:
            report['cross_part_clearance_below_0_15mm'].append([a['ref']+'.'+a['pin'], b['ref']+'.'+b['pin'], round(gap, 4)])
    edges = [(radius-max(math.hypot(x, y) for x, y in a['poly']), a['ref']+'.'+a['pin']) for a in copper]
    report['min_copper_edge_clearance_mm'] = round(min(edges)[0], 4)
    report['min_copper_edge_item'] = min(edges)[1]
    report['edge_clearance_below_0_2mm'] = [[r, round(g, 4)] for g, r in edges if g < .2]
    for h in holes:
        for a in copper:
            if a['ref'] != h['ref']:
                gap = distance(h['poly'], a['poly'])
                if gap < .2:
                    report['holes_to_other_copper_below_0_2mm'].append([h['ref'], a['ref']+'.'+a['pin'], round(gap, 4)])
    report['scope'] = '仅现有铜焊盘/嵌入过孔/USB定位孔的几何初筛；不含布线可达性、器件本体/禁布区、丝印、钢网、热或整机机械验证，不是投板放行。'
    output = ROOT/'easyeda_std/pcb_a5_geometry_audit.json'
    if not proposed:
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    # 从实际导出铜生成分面预览，底面采用顶视投影，避免与安装面观察混淆。
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="700" viewBox="0 0 1200 700">', '<rect width="1200" height="700" fill="#f4f6fa"/>', '<style>text{font-family:Arial,"PingFang SC",sans-serif}</style>', '<text x="40" y="38" font-size="23" fill="#172336">A5 · 18 mm 双面试排｜未布线，不可投板</text>']
    for i, layer in enumerate(('1', '2')):
        ox, oy, scale = 305+590*i, 358, 27
        svg.append(f'<text x="{ox}" y="83" text-anchor="middle" font-size="18">'+('顶面' if layer=='1' else '底面（顶视投影，非翻板视图）')+'</text>')
        svg.append(f'<circle cx="{ox}" cy="{oy}" r="{radius*scale}" fill="#e3ebe6" stroke="#314f48" stroke-width="2"/>')
        for a in copper:
            if a['layer'] not in (layer, '11'):
                continue
            pts = ' '.join(f'{ox+x*scale:.2f},{oy+y*scale:.2f}' for x, y in a['poly'])
            color = '#bd873b' if a['layer']=='11' else ('#ce6253' if layer=='1' else '#4987b7')
            svg.append(f'<polygon points="{pts}" fill="{color}" stroke="#fff" stroke-width=".4"/>')
        for h in holes:
            pts = ' '.join(f'{ox+x*scale:.2f},{oy+y*scale:.2f}' for x, y in h['poly'])
            svg.append(f'<polygon points="{pts}" fill="#f4f6fa" stroke="#6c727b"/>')
        for ref, p in parts.items():
            if p['layer'] != layer:
                continue
            x, y = p['center']
            svg.append(f'<text x="{ox+x*scale:.2f}" y="{oy+y*scale-10:.2f}" font-size="11" text-anchor="middle" fill="#142433" stroke="#f4f6fa" stroke-width="2" paint-order="stroke">{html.escape(ref)}</text>')
    svg += ['<text x="40" y="658" font-size="15" fill="#475668">仅按真实铜焊盘显示；USB 壳体、线缆空间和元件本体净空仍须另行核验。</text>', '</svg>']
    if not proposed:
        (ROOT/'easyeda_std/PCB_A5_18mm_trial.svg').write_text('\n'.join(svg))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == '__main__':
    audit(proposed='--proposed' in sys.argv)
