"""仅平移三个实例的本地布局候选；严禁覆盖云端或制造放行。"""
import copy
import hashlib
import json
import math
import re
from pathlib import Path
from check_pcb_a5 import ROOT, U, parse, rect, distance
from optimize_pcb_a5_layout import geometry, metrics
from audit_a5_ufl_keepout import audit, center

BASE = ROOT/'easyeda_std/PCB_A5_production_silk_verified_20260916.json'
SHA = '91a51ef1cac83dc450a7c64d87d2fbf01e4533c5d2a11f0f601fdbba7e6ccbbe'
OUT = ROOT/'easyeda_std/PCB_A5_天线净空布局候选_未原生验证_20260917.json'
REPORT = ROOT/'easyeda_std/pcb_a5_rf_clearance_layout_check.json'
SVG = ROOT/'easyeda_std/PCB_A5_天线净空调整对照.svg'
DELTAS = {'U5': (.30, -.35), 'C10': (.30, -.35), 'R11': (-.50, 0)}
NUM = r'-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?'


def fmt(v):
    return format(v, '.8f').rstrip('0').rstrip('.') or '0'


def pairs(s, dx, dy, comma=False):
    values = list(map(float, re.findall(NUM, s)))
    assert len(values) % 2 == 0
    return (',' if comma else ' ').join(fmt(n+(dx if i % 2 == 0 else dy)) for i, n in enumerate(values))


def svg_path(s, dx, dy):
    if not s.strip():
        return s
    # 只处理现有的绝对路径，不把圆弧的半径/标记误当坐标。
    tokens = re.findall(r'[A-Za-z]|'+NUM, s)
    out, i = [], 0
    counts = {'M': 2, 'L': 2, 'A': 7, 'Z': 0}
    while i < len(tokens):
        cmd = tokens[i]; i += 1
        assert cmd in counts, ('未知SVG命令', cmd)
        n = counts[cmd]
        values = list(map(float, tokens[i:i+n])); i += n
        assert len(values) == n
        if n:
            values[-2] += dx; values[-1] += dy
        out += [cmd, *map(fmt, values)]
    return ' '.join(out)


def translate_node(node, dx, dy):
    a = node.get('attrs', {})
    assert a.get('transform', 'scale(1) translate(0, 0)') == 'scale(1) translate(0, 0)'
    if 'c_origin' in a:
        a['c_origin'] = pairs(a['c_origin'], dx, dy, True)
    if 'points' in a:
        a['points'] = pairs(a['points'], dx, dy)
    for child in node.get('childNodes', []):
        translate_node(child, dx, dy)


def shift_lib(shape, delta):
    dx, dy = (d/U for d in delta)
    chunks = [s.split('~') for s in shape.split('#@$')]
    head = chunks[0]
    head[1], head[2] = fmt(float(head[1])+dx), fmt(float(head[2])+dy)
    for v in chunks[1:]:
        kind = v[0]
        if kind in {'TEXT', 'PAD'}:
            v[2], v[3] = fmt(float(v[2])+dx), fmt(float(v[3])+dy)
            if kind == 'TEXT':
                v[11] = svg_path(v[11], dx, dy)
            else:
                if v[10].strip(): v[10] = pairs(v[10], dx, dy)
                if len(v) > 19 and v[19].strip(): v[19] = pairs(v[19], dx, dy, True)
        elif kind == 'TRACK': v[4] = pairs(v[4], dx, dy)
        elif kind == 'SOLIDREGION': v[3] = svg_path(v[3], dx, dy)
        elif kind == 'ARC': v[4] = svg_path(v[4], dx, dy)
        elif kind == 'CIRCLE':
            v[1], v[2] = fmt(float(v[1])+dx), fmt(float(v[2])+dy)
        elif kind == 'SVGNODE':
            node = json.loads(v[1]); translate_node(node, dx, dy)
            v[1] = json.dumps(node, ensure_ascii=False, separators=(',', ':'))
        else: raise ValueError(('未允许的实例图形', kind))
    return '#@$'.join('~'.join(v) for v in chunks)


def ref(shape):
    return next(s.split('~')[10] for s in shape.split('#@$') if s.startswith('TEXT~P~'))


def make_candidate(base):
    doc = copy.deepcopy(base)
    for i, shape in enumerate(base['shape']):
        if shape.startswith('LIB~') and ref(shape) in DELTAS:
            doc['shape'][i] = shift_lib(shape, DELTAS[ref(shape)])
    return doc


def corrected_geometry(path):
    d, p, c, h, bodies = geometry(path)
    # 旧机械脚本把所有小阻容当水平，导致旋转的R3/R4等产生假碰撞。
    # 此处用两焊盘连线确定已知0402/0805本体长轴，不改变原生任何封装。
    for r, b in bodies.items():
        if r[0] not in 'RC': continue
        pp = [a for a in c if a['ref'] == r]
        if len(pp) != 2: continue
        a, z = map(lambda q: center(q['poly']), pp)
        if abs(z[1]-a[1]) > abs(z[0]-a[0]):
            b['nominal_mm'][:2] = reversed(b['nominal_mm'][:2])
            b['maximum_mm'][:2] = reversed(b['maximum_mm'][:2])
        b['polygon'] = rect(*b['center'], *b['nominal_mm'][:2])
    return d, p, c, h, bodies


def check(base, candidate):
    assert {k:v for k,v in base.items() if k!='shape'} == {k:v for k,v in candidate.items() if k!='shape'}
    assert len(base['shape']) == len(candidate['shape'])
    changed = []
    for a,b in zip(base['shape'], candidate['shape']):
        if a == b: continue
        assert a.startswith('LIB~') and b.startswith('LIB~')
        r = ref(a); assert r in DELTAS and ref(b) == r
        assert b == shift_lib(a, DELTAS[r])
        changed.append(r)
    assert set(changed) == set(DELTAS)
    old, new = corrected_geometry(BASE), corrected_geometry(OUT)
    oc, nc = old[2], new[2]
    signature = lambda c: [(p['ref'],p['pin'],p['net'],p['layer'],p['kind']) for p in c]
    assert signature(oc) == signature(nc)
    error = 0
    for a,b in zip(oc,nc):
        delta = DELTAS.get(a['ref'], (0,0))
        assert len(a['poly']) == len(b['poly'])
        for pa,pb in zip(a['poly'], b['poly']):
            error = max(error, math.dist((pa[0]+delta[0],pa[1]+delta[1]), pb))
    assert error < 1e-7
    audit_before, _, _ = audit(BASE)
    audit_after, _, _ = audit(OUT)
    keep = audit_after['区域']['本体全层净空候选']['板心坐标多边形_mm'][0]
    closest = sorted((distance(keep,p['poly']), p['ref']+'.'+p['pin']) for p in nc if p['ref']!='ANT1')
    before, after = metrics(*old[1:]), metrics(*new[1:])
    assert not any(v for k,v in after.items() if k != '关键焊盘直线距离_mm_不是走线长度')
    assert closest[0][0] > .15
    assert not audit_after['未解析铜图形']
    for area in audit_after['区域'].values(): assert not area['现有焊盘过孔相交']
    assert len(new[1]) == 41
    result = {'源文件':BASE.name, '源SHA256':SHA, '候选文件':OUT.name,
              '状态':'局部几何预检通过；未导入原生、未布线、禁止生产',
              '平移量_mm_X向右Y向下':DELTAS, '改动实例':changed,
              '改动范围':'仅U5/C10/R11实例刚体平移，包括其铜、阻焊、钢网、位号、标记和3D轮廓',
              '元件数':41,'铜焊盘数':sum(p['kind']=='pad' for p in nc),
              '嵌入过孔数':sum(p['kind']=='via' for p in nc),
              '网络脚号层与其余图元不变':True,'最大铜平移残差_mm':error,
              '净空候选至其他铜最小距离_mm':round(closest[0][0],6), '最近铜':closest[0][1],
              '原始净空冲突':audit_before['区域']['本体全层净空候选']['现有焊盘过孔相交'],
              '候选净空冲突':[], '原布局正确朝向几何':before, '候选正确朝向几何':after,
              '机械模型修正':'小阻容长轴按真实焊盘确定；此前机械脚本忽略旋转造成假碰撞',
              '限制':['原生DRC及保存重开回读未做','禁布规则未应用或验证',
                      '小阻容本体仍使用标称尺寸；不证明装配公差或线缆空间合格',
                      '独立功能丝印未移动；仍须原生视觉检查','没有合并另一份PICO钢网候选',
                      'Q1制造间距、层叠/阻抗及其他既有未决项保持未解决']}
    return result, old, new


def render(old, new):
    s=['<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="1100" viewBox="0 0 1100 1100">',
       '<rect width="1100" height="1100" fill="#f6f8fc"/>',
       '<style>text{font-family:"PingFang SC",Arial,sans-serif;fill:#20314b}</style>',
       '<text x="30" y="42" font-size="26">18 mm 圆板｜天线净空局部调整候选</text>',
       '<text x="30" y="77" font-size="18">仅改 U5、C10、R11；主控、USB、天线与传感器均不动。底面为顶视投影。</text>']
    for n,g in enumerate((old,new)):
        d,p,c,h,b=g
        def sc(pt): return (35+n*550+(pt[0]-2.0)*63, 160+(pt[1]+2.1)*63)
        def poly(q,attrs):
            return '<polygon points="'+' '.join(f'{x:.3f},{y:.3f}' for x,y in map(sc,q))+'" '+attrs+'/>'
        k=rect(*p['ANT1']['center'],3,3.1)
        s.append(f'<text x="{35+n*550}" y="124" font-size="23">'+('当前基线' if n==0 else '局部调整后（仅候选）')+'</text>')
        s.append(poly(k,'fill="#ffefd7" stroke="#ce8a26" stroke-dasharray="6 5"'))
        for q in c:
            cp=center(q['poly'])
            if q['layer'] not in ('2','11') or not(2<cp[0]<8.5 and -2<cp[1]<4.7): continue
            bad=distance(k,q['poly'])<1e-6
            color='#d74050' if bad else '#287c69' if q['ref'] in DELTAS else '#a7b5c7'
            s.append(poly(q['poly'],f'fill="{color}" fill-opacity=".85"'))
        for j,r in enumerate(('U5','C10','R11')):
            x,y=sc(p[r]['center']); lx,ly=35+n*550+j*155,650
            s.append(f'<path d="M{x:.3f},{y:.3f} L{lx+20},{ly-22}" stroke="#6b8195" fill="none"/>')
            s.append(f'<text x="{lx}" y="{ly}" font-size="20">{r}</text>')
        # 相同的板边圆弧，取本图局部右半段，不将截断区域当成完整板形。
        q=[(9*math.cos(t),9*math.sin(t)) for t in [(-.23+i*.009) for i in range(83)]]
        s.append('<polyline points="'+' '.join(f'{x:.3f},{y:.3f}' for x,y in map(sc,q))+'" fill="none" stroke="#2c6688" stroke-width="2"/>')
    s += ['<text x="30" y="710" font-size="18">橙框：本体全层净空工程候选　红：侵入铜　绿：调整的元件铜　蓝色圆弧：18 mm 板边</text>',
          '<path d="M30 750 H1070" stroke="#c4cedb"/>',
          '<text x="30" y="800" font-size="23">调整量（板心坐标，毫米）</text>',
          '<text x="30" y="844" font-size="21">U5 与 C10：一起右移 0.30、上移 0.35；保持输出去耦的相对位置。</text>',
          '<text x="30" y="886" font-size="21">R11：左移 0.50；天线、USB、IMU、MLX90393 均保持原位。</text>',
          '<text x="30" y="938" font-size="20">净空至其他铜最小距离约 0.175 mm；原有 4 处侵入已在本地候选中消除。</text>',
          '<text x="30" y="992" font-size="19">几何筛查通过 ≠ 原生 DRC 通过 ≠ 生产放行。禁布、布线及装配验证仍须完成。</text>',
          '<text x="30" y="1040" font-size="18">未覆盖在线或本地主入口；未合并 PICO 钢网候选。最终移动前须读取在线最新版本。</text>', '</svg>']
    return '\n'.join(s)+'\n'


def main():
    assert hashlib.sha256(BASE.read_bytes()).hexdigest() == SHA, '基线已变，须重新评估'
    base=json.loads(BASE.read_text()); candidate=make_candidate(base)
    OUT.write_text(json.dumps(candidate,ensure_ascii=False,indent=2)+'\n')
    report,old,new=check(base,candidate)
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    SVG.write_text(render(old,new))
    assert hashlib.sha256(BASE.read_bytes()).hexdigest() == SHA
    print(json.dumps({k:report[k] for k in ('状态','改动实例','净空候选至其他铜最小距离_mm','最近铜')},ensure_ascii=False))


if __name__=='__main__': main()
