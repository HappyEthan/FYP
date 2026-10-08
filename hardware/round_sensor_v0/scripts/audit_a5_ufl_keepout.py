"""U.FL 局部几何核查；输出工程候选，不修改 PCB，不代替原生禁布/DRC。"""
import hashlib
import html
import json
import math
from check_pcb_a5 import ROOT, ORIGIN, U, parse, rect, distance

PCB = ROOT/'easyeda_std/PCB_A5_production_silk_verified_20260916.json'
OUT = ROOT/'easyeda_std/pcb_a5_ufl_keepout_audit.json'
SVG = ROOT/'easyeda_std/PCB_A5_天线禁布审核.svg'


def center(poly):
    return tuple(sum(p[i] for p in poly)/len(poly) for i in (0, 1))


def audit(path=PCB):
    data, parts, copper, _ = parse(path)
    pads = {p['pin']: p for p in copper if p['ref'] == 'ANT1'}
    assert set(pads) == {'1', '2', '3'}
    assert pads['1']['net'] == 'R30_2'
    assert pads['2']['net'] == pads['3']['net'] == 'GND'
    g2, g3, sig = (center(pads[i]['poly']) for i in ('2', '3', '1'))
    origin = tuple((g2[i]+g3[i])/2 for i in (0, 1))
    pitch = math.dist(g2, g3)
    ex = tuple((g3[i]-g2[i])/pitch for i in (0, 1))
    offset = math.dist(sig, origin)
    ey = tuple((sig[i]-origin[i])/offset for i in (0, 1))
    assert abs(sum(ex[i]*ey[i] for i in (0, 1))) < .001

    def local(p):
        v = [p[i]-origin[i] for i in (0, 1)]
        return [sum(v[i]*axis[i] for i in (0, 1)) for axis in (ex, ey)]

    def board(p):
        return [origin[i]+p[0]*ex[i]+p[1]*ey[i] for i in (0, 1)]

    # Hirose 目录第12页：两地铜焊盘内距1.9、外距4.0、高2.2；SIG宽1、高1.05。
    expected = {'1': (0, 1.525, 1, 1.05), '2': (-1.475, 0, 1.05, 2.2),
                '3': (1.475, 0, 1.05, 2.2)}
    geometry = {}
    for pin, p in pads.items():
        q = [local(v) for v in p['poly']]
        dims = [sum(v[i] for v in q)/len(q) for i in (0, 1)]
        dims += [max(v[i] for v in q)-min(v[i] for v in q) for i in (0, 1)]
        assert all(abs(a-b) < .001 for a, b in zip(dims, expected[pin])), (pin, dims)
        geometry[pin] = [round(x, 5) for x in dims]

    # 中心区域按图中地焊盘内边界构造；信号焊盘自身必须排除，不能误禁铜。
    central = [rect(0, -.05, 1.9, 2.1), rect(-.725, 1.05, .45, .1),
               rect(.725, 1.05, .45, .1)]
    # 这是工程审查包络，不是原厂给出的有公差禁布尺寸；最终边界须原生验证。
    envelope = rect(0, 0, 3, 3.1)
    regions = {'中心禁走线区': central, '本体全层净空候选': [envelope]}
    checks = {}
    for name, polys in regions.items():
        world = [[board(v) for v in poly] for poly in polys]
        offenders = []
        for p in copper:
            # 唯一例外是连接器自身顶层的三只必要焊盘；不豁免底层地铜。
            if p['ref'] == 'ANT1' and p['layer'] == '1':
                continue
            if min(distance(p['poly'], poly) for poly in world) < 1e-6:
                offenders.append({'位号': p['ref'], '焊盘': p['pin'], '网络': p['net'],
                                  '层': p['layer'], '类型': p['kind']})
        checks[name] = {'局部多边形_mm': polys, '板心坐标多边形_mm': world,
                        'EDA坐标多边形': [[[v[0]/U+ORIGIN[0], v[1]/U+ORIGIN[1]]
                                           for v in poly] for poly in world],
                        '范围': '所有铜层，顶层仅保留ANT1自身必要焊盘与从信号焊盘外端进入的馈线',
                        '现有焊盘过孔相交': offenders}
    # 本解析器仅核验未布线版的焊盘/嵌入过孔，遇到新铜图形必须显式拒绝通过。
    copper_layers = {'1', '2', '11', *map(str, range(21, 53))}
    unparsed = []
    for scope, shapes in [('板级', [s.split('~') for s in data['shape'] if not s.startswith('LIB~')])]+[
            (ref, p['items']) for ref, p in parts.items()]:
        for v in shapes:
            if (v[0] in {'COPPERAREA', 'PLANE', 'RECT'} or
                (v[0] == 'TRACK' and v[2] in copper_layers) or
                (v[0] == 'SOLIDREGION' and v[1] in copper_layers) or
                (v[0] == 'CIRCLE' and v[5] in copper_layers) or
                (v[0] == 'ARC' and v[2] in copper_layers) or
                (scope == '板级' and v[0] in {'PAD', 'VIA'})):
                unparsed.append({'位置': scope, '类型': v[0]})
    report = {'源文件': path.name, '源SHA256': hashlib.sha256(path.read_bytes()).hexdigest(),
              '状态': '需要布局调整；不是生产放行', '连接器': 'U.FL-R-SMT-1(80)',
              '信号焊盘局部方向': '正Y', '板心坐标系': '毫米；X向右、Y向下；底面为顶视投影',
              '连接器中心_mm': origin, '焊盘局部中心与尺寸_mm': geometry,
              '铜焊盘几何核对': '通过，允许序列化舍入误差0.001mm', '区域': checks,
              '未解析铜图形': unparsed, '局部检查覆盖完整': not unparsed,
              '原生禁布已设置': False, '原生DRC已验证': False, '在线布局已修改': False,
              '适用边界': '两组区域并非同等原厂强制尺寸；本体范围为乐鑫全层净空建议的工程候选。'
                          '只检查铜焊盘/嵌入过孔；不验证本体、插拔、线缆、实际阻抗或射频性能。'}
    return report, copper, checks


def render(copper, checks):
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1140" height="1140" viewBox="0 0 1140 1140">',
           '<rect width="1140" height="1140" fill="#f7f9fc"/>',
           '<style>text{font-family:"PingFang SC",Arial,sans-serif;fill:#1a2a40}</style>',
           '<text x="30" y="40" font-size="25">天线连接器下方净空审核｜局部候选，尚未写入原生规则</text>']
    for n, layer in enumerate(('1', '2')):
        def screen(p):
            return (75+n*560+(p[0]-2.8)*72, 120+(p[1]+.5)*72)
        def polygon(poly, attrs):
            pts = ' '.join(f'{x:.2f},{y:.2f}' for x, y in map(screen, poly))
            return f'<polygon points="{pts}" {attrs}/>'
        svg.append(f'<text x="{35+n*560}" y="83" font-size="21">{"顶面" if layer=="1" else "底面（顶视投影）"}</text>')
        env = checks['本体全层净空候选']['板心坐标多边形_mm'][0]
        svg.append(polygon(env, 'fill="#fff1d8" stroke="#d97706" stroke-width="2" stroke-dasharray="8 5"'))
        for poly in checks['中心禁走线区']['板心坐标多边形_mm']:
            svg.append(polygon(poly, 'fill="#dceafa" stroke="none"'))
        shown = {}
        bad = {(o['位号'], o['焊盘']) for o in checks['本体全层净空候选']['现有焊盘过孔相交']}
        for p in copper:
            cp = center(p['poly'])
            if p['layer'] not in (layer, '11') or not (3 < cp[0] < 8.3 and -.5 < cp[1] < 5.4):
                continue
            color = '#ce3749' if (p['ref'], p['pin']) in bad else '#478b77'
            svg.append(polygon(p['poly'], f'fill="{color}" fill-opacity=".78" stroke="{color}" stroke-width="1"'))
            shown.setdefault(p['ref'], []).append(cp)
        # 固定标签轨道加引线，避免小焊盘/位号互相遮挡。
        for j, (ref, pts) in enumerate(sorted(shown.items())):
            cp = center(pts); x, y = screen(cp)
            lx, ly = 35+n*560+(j%3)*170, 590+(j//3)*28
            svg.append(f'<path d="M {x:.2f} {y:.2f} L {lx+30} {ly-17}" fill="none" stroke="#8494a8" stroke-width=".7"/>')
            svg.append(f'<rect x="{lx-3}" y="{ly-17}" width="77" height="23" fill="#f7f9fc"/>')
            svg.append(f'<text x="{lx}" y="{ly}" font-size="16">{html.escape(ref)}</text>')
    svg += ['<text x="30" y="697" font-size="17">蓝：中心禁走线区　橙框：3.00 × 3.10 mm 本体净空工程候选　红：进入候选范围的背面焊盘</text>',
            '<text x="30" y="725" font-size="16">中心区未发现侵入；较大候选范围与 U5、R11 冲突。图不表示真实器件高度，也不是布线完成图。</text>',
            '<path d="M 30 765 H 1110" stroke="#bbc6d5"/>',
            '<text x="30" y="815" font-size="24">局部调整之前，先区分两种检查</text>',
            '<text x="30" y="858" font-size="20">① 中心区域：按原厂焊盘间隙构造，排除信号焊盘自身；当前未发现铜侵入。</text>',
            '<text x="30" y="899" font-size="20">② 本体范围：全层净空工程候选，并非厂家给出的有公差禁布尺寸。</text>',
            '<text x="30" y="940" font-size="20">冲突焊盘：底面 R11.1、U5.7、U5.3、U5.4；顶层连接器自身焊盘必须保留。</text>',
            '<text x="30" y="999" font-size="20">下一步：局部重排 → 原生禁布规则 → 走线／过孔／铺铜验证 → 射频布线。</text>',
            '<text x="30" y="1060" font-size="18">审核输入：生产字号回读版（2026-09-16）　核查日期：2026-09-17　在线工程未修改</text>', '</svg>']
    return '\n'.join(svg)+'\n'


if __name__ == '__main__':
    report, copper, checks = audit()
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    SVG.write_text(render(copper, checks))
    print(json.dumps({k: v['现有焊盘过孔相交'] for k, v in checks.items()}, ensure_ascii=False))
    assert not report['未解析铜图形'], '新增铜对象不在本脚本解析范围；不能沿用旧审核结论'
