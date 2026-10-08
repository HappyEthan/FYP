"""从原生 L 检查点生成右侧 USB 回流试排；不覆盖当前工作板。"""
import copy
import hashlib
import json
from pathlib import Path

from check_pcb_a5 import ROOT, parse, distance
from refine_clone_usb_20260928 import configure, batch, old_losses
from audit_a5_routed_snapshot import routes
from repair_clone_inner_layer_20260928 import path_text

SOURCE = ROOT / 'easyeda_std/PCB_克隆板USB局部重布_原生回读_20260929.json'
SOURCE_SHA = '66bd2734de881f1fe879cff9712950e9c07a5f7689cf25396034a722a69544c8'
OUT = Path('/Users/liuchunyu/Downloads/PCBUSBreturnMTrial20260929.json')


def main():
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == SOURCE_SHA
    doc, parts, copper, holes = parse(SOURCE)
    configure()
    trial = copy.deepcopy(doc)
    track = next(t for t in routes(doc)[0] if t['id'] == 'ggeUSB0928T279')
    # 仅把阻挡右侧回流孔的一段 L3 CC 线绕向外侧，两端及其他网络不动。
    points = track['points'][:4] + [
        (23.514, -75.1), (24.4, -75.1), (24.65, -75.35),
        (24.65, -75.65), (24.3860066, -75.9139934),
    ] + track['points'][7:]
    index = next(i for i, s in enumerate(trial['shape']) if '~ggeUSB0928T279~' in s)
    fields = trial['shape'][index].split('~')
    fields[4] = path_text(points)
    trial['shape'][index] = '~'.join(fields)
    point = (24.13, -75.66)
    batch.add_via(trial, 'GND', point, .25, .15)
    new_via = trial['shape'][-1]
    changed = [trial['shape'][index], new_via]
    issues = batch.check_new(trial, copper, holes, changed)
    assert not issues, issues
    assert not old_losses(doc, copper, trial, copper, 'J1_B5')
    pad_gaps = [(p['ref'] + '.' + p['pin'], distance([point], p['poly']) - .075)
                for p in copper if p['kind'] == 'pad' and p['layer'] in ('1', '2')]
    assert min(g for _, g in pad_gaps) >= .1
    assert doc['DRCRULE'] == trial['DRCRULE']
    assert [s for s in doc['shape'] if s.startswith('LIB~')] == [s for s in trial['shape'] if s.startswith('LIB~')]
    assert [s for s in doc['shape'] if '~USB_D' in s] == [s for s in trial['shape'] if '~USB_D' in s]
    # 清空缓存以要求编辑器重铺，绝不沿用修改前的实际铜面作验收依据。
    for i, s in enumerate(trial['shape']):
        if s.startswith('COPPERAREA~'):
            fields = s.split('~'); fields[10] = ''; trial['shape'][i] = '~'.join(fields)
    OUT.write_text(json.dumps(trial, ensure_ascii=False, indent=2) + '\n')
    report = {
        '来源SHA256': SOURCE_SHA, '候选SHA256': hashlib.sha256(OUT.read_bytes()).hexdigest(),
        '修改图元': ['ggeUSB0928T279'], '新增图元': new_via.split('~')[6],
        '新增地孔坐标_mm': point, '孔外径_钻孔_mm': [.25, .15],
        '右侧USB信号孔至新增地孔距离_mm': ((point[0]-23.737062)**2+(point[1]+75.900026)**2)**.5,
        '最小新孔钻边至SMT焊盘_mm': min(pad_gaps, key=lambda x:x[1]),
        '本地增量间距错误': issues, '元件数量': len(parts),
        'USB线路和元件规则不变': True,
        '原生铺铜及DRC已验证': False, '已覆盖云端': False, '允许生产': False,
    }
    OUT.with_suffix('.report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(changed, ensure_ascii=False))


if __name__ == '__main__':
    main()
