"""主控分窗钢网的本地候选；不调用原生编辑器、不覆盖已验证入口。"""
import copy
import hashlib
import itertools
import json
import math
import re
from pathlib import Path

from check_pcb_a5 import ROOT, U

BASE = ROOT / 'easyeda_std/PCB_A5_production_silk_verified_20260916.json'
EXPECTED_SHA = '91a51ef1cac83dc450a7c64d87d2fbf01e4533c5d2a11f0f601fdbba7e6ccbbe'
OUT = ROOT / 'easyeda_std/PCB_A5_PICO分窗_仅候选禁止生产_20260917.json'
REPORT = ROOT / 'easyeda_std/pcb_a5_pico_stencil_candidate_check.json'
DRAWING = ROOT / 'easyeda_std/PCB_A5_PICO钢网对照.svg'
OLD_ID = 'gge3261'
NEW_IDS = tuple('gge99170' + str(i) for i in range(1, 5))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def u1_index(doc):
    found = [i for i, s in enumerate(doc['shape']) if s.startswith('LIB~') and
             any(v.startswith('TEXT~P~') and v.split('~')[10] == 'U1' for v in s.split('#@$'))]
    assert len(found) == 1, '主控实例不唯一'
    return found[0]


def bounds(points):
    return min(x for x, y in points), min(y for x, y in points), max(x for x, y in points), max(y for x, y in points)


def polygon(v):
    values = list(map(float, re.findall(r'-?\d+(?:\.\d+)?', v[3])))
    return list(zip(values[::2], values[1::2]))


def geometry(doc):
    items = [v.split('~') for v in doc['shape'][u1_index(doc)].split('#@$')]
    ep = next(v for v in items if v[0] == 'PAD' and v[8] == '57')
    p = list(map(float, ep[10].split()))
    bb = bounds(list(zip(p[::2], p[1::2])))
    center = ((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2)
    return items, ep, bb, center


def windows(doc):
    _, _, _, (cx, cy) = geometry(doc)
    result = []
    for uid, (dx, dy) in zip(NEW_IDS, itertools.product((-.95, .95), repeat=2)):
        x, y = cx + dx/U, cy + dy/U
        half = .8/U
        points = [(x-half, y-half), (x+half, y-half), (x+half, y+half), (x-half, y+half)]
        path = 'M ' + ' L '.join(f'{px:.6f} {py:.6f}' for px, py in points) + ' Z '
        result.append(f'SOLIDREGION~5~~{path}~solid~{uid}~~~~0')
    return result


def make_candidate(base):
    doc = copy.deepcopy(base)
    i = u1_index(base)
    parts = base['shape'][i].split('#@$')
    old = [v for v in parts if v.startswith('SOLIDREGION~') and v.split('~')[5] == OLD_ID]
    assert len(old) == 1 and old[0].split('~')[1] == '5'
    assert all(uid not in json.dumps(base) for uid in NEW_IDS), '新图元标识冲突'
    new = windows(base)
    doc['shape'][i] = '#@$'.join(w for v in parts for w in (new if v == old[0] else [v]))
    return doc


def verify(base, candidate):
    """完整文档白名单：唯一允许的变化为 U1 中一个钢网区域变为四个。"""
    assert set(base) == set(candidate), '文档字段改变'
    assert {k: v for k, v in base.items() if k != 'shape'} == {k: v for k, v in candidate.items() if k != 'shape'}, '元数据或规则改变'
    assert len(base['shape']) == len(candidate['shape']), '板级图元数量改变'
    i = u1_index(base)
    for j, (a, b) in enumerate(zip(base['shape'], candidate['shape'])):
        if j != i:
            assert a == b, f'主控之外的图元改变：{j}'
    a = base['shape'][i].split('#@$')
    b = candidate['shape'][i].split('#@$')
    def selected(s, ids):
        p = s.split('~')
        return p[0] == 'SOLIDREGION' and p[5] in ids
    assert [v for v in a if not selected(v, {OLD_ID})] == [v for v in b if not selected(v, set(NEW_IDS))], '主控非目标钢网图元改变'
    assert [v for v in b if selected(v, set(NEW_IDS))] == windows(base), '候选窗口不符'
    assert len(b) == len(a) + 3
    items, ep, bb, (cx, cy) = geometry(candidate)
    assert ep[7] == 'GND' and ep[17] == '-393.7'
    assert sum(v[0] == 'SOLIDREGION' and v[1] == '5' for v in items) == 60
    ws = [bounds(polygon(v)) for v in items if v[0] == 'SOLIDREGION' and v[5] in NEW_IDS]
    local = [tuple((v - (cx if k%2 == 0 else cy))*U for k, v in enumerate(w)) for w in ws]
    sizes = [((w[2]-w[0])*U, (w[3]-w[1])*U) for w in ws]
    assert all(abs(n-1.6) < 1e-6 for size in sizes for n in size)
    area = sum(w*h for w, h in sizes)
    copper_area = (bb[2]-bb[0])*(bb[3]-bb[1])*U*U
    assert abs(area/copper_area - .64) < 1e-5
    margin = min(min(w[0]-bb[0], w[1]-bb[1], bb[2]-w[2], bb[3]-w[3])*U for w in ws)
    assert margin > .2499
    def rect_gap(a, b):
        return math.hypot(max(a[0]-b[2], b[0]-a[2], 0), max(a[1]-b[3], b[1]-a[3], 0))
    web = min(rect_gap(x, y)*U for x, y in itertools.combinations(ws, 2))
    assert abs(web-.3) < 1e-6
    vias = [v for v in items if v[0] == 'VIA']
    assert len(vias) == 9
    center_hits, drill_intersections = [], []
    for v in vias:
        x, y, r = float(v[1]), float(v[2]), float(v[5])
        if any(w[0] < x < w[2] and w[1] < y < w[3] for w in ws):
            center_hits.append(v[6])
        if any(math.hypot(max(w[0]-x, x-w[2], 0), max(w[1]-y, y-w[3], 0)) < r for w in ws):
            drill_intersections.append(v[6])
    assert len(center_hits) == 4 and len(drill_intersections) == 8
    return {'状态': '仅本地工艺候选，未导入原生，禁止生产', '允许变更': 'U1 顶层中央钢网：一个区域替换为四个区域',
            '其余文档内容逐项严格相同': True, '窗口尺寸_mm': sizes, '窗口相对EP中心边界_mm': local,
            '总开口面积_mm2': area, '铜焊盘面积_mm2': copper_area, '面积覆盖率': area/copper_area,
            '最小窗口间钢网筋_mm': web, '最小铜边内缩_mm': margin,
            '过孔总数': len(vias), '窗口覆盖孔中心数量': len(center_hits), '窗口与名义孔口投影相交数量': len(drill_intersections),
            '注意': '钢网筋不是阻焊隔离；分窗没有消除盘中孔漏锡。九孔均按填孔盖帽前提询价，不只处理被窗口覆盖的孔。',
            '填孔盖帽已获工厂确认': False, '钢网厚度已选定': False, '原生保存回读验证': False,
            '原生DRC通过': False, '制造放行': False}


def drawing(base, candidate, report):
    items, _, bb, (cx, cy) = geometry(base)
    old = next(v for v in items if v[0] == 'SOLIDREGION' and v[5] == OLD_ID)
    via = [((float(v[1])-cx)*U, (float(v[2])-cy)*U, float(v[5])*U) for v in items if v[0] == 'VIA']
    orig = tuple((v-(cx if i%2 == 0 else cy))*U for i, v in enumerate(bounds(polygon(old))))
    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="1140" height="740" viewBox="0 0 1140 740">',
           '<rect width="1140" height="740" fill="#f4f7fa"/>',
           '<g font-family="PingFang SC,Noto Sans CJK SC,sans-serif" fill="#182b42">',
           '<text x="40" y="45" font-size="25" font-weight="600">主控中央焊盘：钢网分窗候选</text>',
           '<text x="40" y="78" font-size="16">仅调整锡膏图形，不改 4×4 mm 接地铜、九个过孔、布局或电路。</text>']
    for ox, title, rects, desc in [(290, '当前原生：单个开口', [orig], '3.2×3.2 mm · 覆盖全部九孔中心'),
                                  (850, '本地候选：四个开口', report['窗口相对EP中心边界_mm'], '每窗 1.6×1.6 mm · 覆盖率仍为 64%')]:
        out.append(f'<text x="{ox}" y="120" font-size="21" text-anchor="middle">{title}</text>')
        out.append(f'<g transform="translate({ox},320) scale(80)">')
        out.append('<rect x="-2" y="-2" width="4" height="4" fill="#f1d7a5" stroke="#9b7133" stroke-width=".025"/>')
        for x0, y0, x1, y1 in rects:
            out.append(f'<rect x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}" fill="#75bec6" fill-opacity=".82" stroke="#166979" stroke-width=".018"/>')
        for x, y, r in via:
            out.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="#fff" fill-opacity=".8" stroke="#b14436" stroke-width=".024"/>')
        out.append('</g>')
        out.append(f'<text x="{ox}" y="516" text-anchor="middle" font-size="17">{desc}</text>')
    out += ['<text x="850" y="548" text-anchor="middle" font-size="16">筋宽 0.30 mm；外缘距铜边约 0.25 mm</text>',
            '<rect x="40" y="575" width="1060" height="130" rx="10" fill="#fff0dc"/>',
            '<text x="60" y="604" font-size="18" font-weight="600">前提：九个过孔全部填孔、整平并电镀盖帽；工厂尚未确认。</text>',
            '<text x="60" y="633" font-size="16">红圈为未填孔时的名义孔口投影。候选仍覆盖 4 个孔中心，并与 8 个孔口投影相交。</text>',
            '<text x="60" y="660" font-size="16">分窗不是阻焊隔离；不能用普通盖油代替填孔盖帽，也不能凭本图判断可焊。</text>',
            '<text x="60" y="687" font-size="16">候选未导入原生编辑器、未布线、未取得钢网厚度及贴装批准，禁止生产。</text>', '</g></svg>']
    DRAWING.write_text('\n'.join(out)+'\n')


def build():
    assert digest(BASE) == EXPECTED_SHA, '基线已变化，必须先重新审核'
    base = json.loads(BASE.read_text())
    candidate = make_candidate(base)
    report = verify(base, candidate)
    OUT.write_text(json.dumps(candidate, ensure_ascii=False, indent=2)+'\n')
    verify(base, json.loads(OUT.read_text()))
    drawing(base, candidate, report)
    report['日期'] = '2026-09-17'
    report['SHA256'] = {p.name: digest(p) for p in (BASE, OUT)}
    assert digest(BASE) == EXPECTED_SHA
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    build()
