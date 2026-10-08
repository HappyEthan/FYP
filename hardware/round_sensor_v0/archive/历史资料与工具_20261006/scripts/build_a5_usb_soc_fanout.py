"""仅重布 USB 串联电阻至主控的局部扇出；不覆盖源板或宣称阻抗通过。"""
import copy
import hashlib
import json
import math
from pathlib import Path

from check_pcb_a5 import ROOT, U, ORIGIN, parse, distance, ellipse, shared_layer
from audit_a5_routed_snapshot import routes, track_gap

SOURCE = ROOT / 'easyeda_std/PCB_A5_保留自动布线_局部重布候选_20260917.json'
SOURCE_SHA = 'b7b0bf5efbf214aaede52f4a3a111c9c4e031873f956f613158f03cb6880a02c'
OUT = ROOT / 'easyeda_std/PCB_A5_USB主控侧重布候选_20260917.json'
REPORT = ROOT / 'easyeda_std/pcb_a5_usb_soc_fanout_check.json'
NETS = {'USB_DP_SOC', 'USB_DM_SOC'}
PREFIX = 'ggeA5UsbSoc'
WIDTH = .155
VIA_DIA = .6096
VIA_HOLE = .3048
CLEARANCE = .1524
REPLACED_IDS = {'gge1020957', 'gge1020975', 'gge1020540'}


def coord(p):
    return ' '.join(f'{p[i]/U+ORIGIN[i]:.8f}' for i in (0, 1))


def track(net, layer, points, index, width=WIDTH):
    return f'TRACK~{width/U:.8f}~{layer}~{net}~' + ' '.join(map(coord, points)) + f'~{PREFIX}T{index}~0'


def via(net, point, index):
    x, y = coord(point).split()
    return f'VIA~{x}~{y}~{VIA_DIA/U:.8f}~{net}~{VIA_HOLE/U/2:.8f}~{PREFIX}V{index}~0'


def pad_center(copper, ref, pin):
    p = next(p for p in copper if p['ref'] == ref and p['pin'] == pin)
    xs, ys = zip(*p['poly'])
    return (min(xs)+max(xs))/2, (min(ys)+max(ys))/2


def build():
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == SOURCE_SHA, '源板已变化，禁止套用旧候选'
    source, parts, copper, _ = parse(SOURCE)
    doc = copy.deepcopy(source)
    removed = []
    kept = []
    for s in source['shape']:
        v = s.split('~')
        if (v[0] == 'TRACK' and (v[3] in NETS or v[5] in REPLACED_IDS)
                or v[0] == 'VIA' and (v[4] in NETS or v[6] in REPLACED_IDS)):
            removed.append(s)
        else:
            kept.append(s)
    # 元件和焊盘不移动。实际焊盘中心为端点，避免写入四舍五入后偏离的坐标。
    dp_r = pad_center(copper, 'R3', '2')
    dm_r = pad_center(copper, 'R4', '2')
    dp_u = pad_center(copper, 'U1', '26')
    dm_u = pad_center(copper, 'U1', '25')
    vp, vm = (-3.10, .20), (-2.30, .20)
    specs = [
        ('USB_DP_SOC', '2', [dp_r, (dp_r[0], .05), vp]),
        ('USB_DM_SOC', '2', [dm_r, (dm_r[0], -.10), vm]),
        ('USB_DP_SOC', '1', [dp_u, (dp_u[0], .043), vp]),
        ('USB_DM_SOC', '1', [dm_u, (dm_u[0], -.043), vm]),
    ]
    additions = [track(*s, i) for i, s in enumerate(specs)]
    additions += [via('USB_DP_SOC', vp, 0), via('USB_DM_SOC', vm, 1)]
    # 两个地孔经顶层短线接入主控地焊盘；内层连续参考地仍须后续铺铜。
    ground_points = [(-1.35, .20), (-.55, .20)]
    for i, p in enumerate(ground_points):
        additions.append(via('GND', p, i+2))
        additions.append(track('GND', '1', [p, (p[0], 1.05)], i+4, .254))
    # 原 BOOT_N 单端未接出的孔/支线占用 D+ 孔位；只撤回该悬空支线。
    # 原内层 GND 线与 D- 孔相交，保留两端点，绕开孔；不把线等同于地平面。
    old_ground = next(t for t in routes(source)[0] if t['id'] == 'gge1020540')
    a, b = old_ground['points'][0], old_ground['points'][-1]
    additions.append(track('GND', '22', [a, (-1.35, .9468512), (-1.35, -.7),
                                         (-2.85, -2.2), (b[0], -2.2), b], 6, .254))
    doc['shape'] = kept + additions
    # 分组结构由原生规则界面创建并导出核验；保留源全局精度，避免界面
    # 将24mil孔径0.6096mm取整成0.610mm后使原有孔产生伪小孔径报错。
    usb_rule = copy.deepcopy(source['DRCRULE']['Default'])
    usb_rule['trackWidth'] = .15/U
    usb_rule['nets'] = sorted(NETS)
    doc['DRCRULE']['USB主控扇出'] = usb_rule
    return source, doc, copper, removed, additions


def check(doc, copper):
    ts, vs, unsupported = routes(doc)
    assert not unsupported
    fresh_t = [t for t in ts if t['id'].startswith(PREFIX)]
    fresh_v = [v for v in vs if v['id'].startswith(PREFIX)]
    conflicts = []
    _, _, _, holes = parse(SOURCE)
    def add(kind, a, b, gap):
        if gap < CLEARANCE - 1e-5:
            conflicts.append([kind, a, b, round(gap, 6)])
    for t in fresh_t:
        for i, h in enumerate(holes):
            add('线-机械孔', t['id'], h['ref']+':'+str(i), track_gap(t,h['poly']))
        for p in copper:
            if shared_layer(t, p) and t['net'] != p['net']:
                add('线-焊盘', t['id'], p['ref']+'.'+p['pin'], track_gap(t, p['poly']))
        for b in ts:
            if t['layer'] == b['layer'] and t['net'] != b['net']:
                gap = min(distance([a1,a2], [b1,b2]) for a1,a2 in zip(t['points'],t['points'][1:])
                          for b1,b2 in zip(b['points'],b['points'][1:])) - (t['width']+b['width'])/2
                add('线-线', t['id'], b['id'], gap)
        for v in vs:
            if t['net'] != v['net']:
                add('线-孔', t['id'], v['id'], track_gap(t, v['poly']))
    for v in fresh_v:
        for i, h in enumerate(holes):
            add('孔-机械孔', v['id'], h['ref']+':'+str(i), distance(v['poly'],h['poly']))
        for p in copper:
            if v['net'] != p['net']:
                add('孔-焊盘', v['id'], p['ref']+'.'+p['pin'], distance(v['poly'],p['poly']))
        for t in ts:
            if v['net'] != t['net']:
                add('孔-线', v['id'], t['id'], track_gap(t,v['poly']))
        for b in vs:
            if v['net'] != b['net']:
                add('孔-孔', v['id'], b['id'], distance(v['poly'],b['poly']))
    lengths = {n: sum(math.dist(a,b) for t in fresh_t if t['net']==n for a,b in zip(t['points'],t['points'][1:])) for n in sorted(NETS)}
    return conflicts, lengths


def main():
    source, doc, copper, removed, additions = build()
    conflicts, lengths = check(doc,copper)
    if conflicts:
        print(json.dumps({'新增冲突':conflicts},ensure_ascii=False,indent=2))
        raise SystemExit('局部几何筛查未通过，没有写出候选')
    assert [s for s in source['shape'] if s.startswith('LIB~')] == [s for s in doc['shape'] if s.startswith('LIB~')]
    OUT.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n')
    report = {'源文件': SOURCE.name, '源SHA256':SOURCE_SHA, '候选':OUT.name,
              '候选SHA256':hashlib.sha256(OUT.read_bytes()).hexdigest(),
              '状态':'本地几何筛查通过；待原生规则、DRC、回读和参考地验证，禁止生产',
              '删除图元':removed,'新增图元':additions,'元件实例逐字保留':True,
              '其他改动':'移除BOOT_N未接出的局部孔/支线；内层GND线保留原端点绕开USB孔',
              '新增异网间距冲突':conflicts,'最小间距筛查_mm':CLEARANCE,
              '扇出线宽_mm':WIDTH,'过孔外径_mm':VIA_DIA,'过孔钻径_mm':VIA_HOLE,
              '两网平面中心线长度_mm':lengths,
              '两网平面长度差_mm':abs(lengths['USB_DP_SOC']-lengths['USB_DM_SOC']),
              '限制':['只完成R3/R4至U1段；接口、ESD和前段差分尚未完成',
                      '过孔换层数量对称；本长度不计焊盘内传播、器件和垂直过孔传播',
                      '0.155mm为局部扇出线宽，不宣称全程90欧姆；L4模型与参考地须落实',
                      '保留源全局规则精确数值，仅两个USB_SOC网络采用0.150mm最小线宽；不改变全板孔径/间距',
                      '新增地孔已接主控地焊盘，尚无连续L2/L3地平面',
                      '本地筛查不替代原生DRC或制造审核']}
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['候选','两网平面中心线长度_mm','两网平面长度差_mm','新增异网间距冲突']},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
