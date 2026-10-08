"""从 M 回读生成左侧回流试排；旧地孔替换须经原生地网检查，不能仅凭DRC接受。"""
import copy
import hashlib
import json
from pathlib import Path

from check_pcb_a5 import ROOT, parse, distance
from refine_clone_usb_20260928 import configure, batch, old_losses
from repair_clone_inner_layer_20260928 import path_text

SOURCE = ROOT / 'easyeda_std/PCB_克隆板USB局部重布_原生回读_20260929.json'
SHA = '7fc15f2b1a61949ca46f6dfedd23bde929286fab0f35aa89cf55bc23c10f3917'
OUT = Path('/Users/liuchunyu/Downloads/PCBUSBreturnNTrial20260929.json')
REMOVED = {'ggeUSB0928V318', 'ggeUSB0928V285', 'ggeUSB0928T422', 'ggeUSB0928T284'}


def main():
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == SHA
    d, p, c, h = parse(SOURCE)
    configure()
    t = copy.deepcopy(d)
    t['shape'] = [s for s in t['shape'] if not any('~' + i + '~' in s for i in REMOVED)]
    control_via = (21.94, -74.46)
    ground_via = (22.75, -75.15)
    paths = {
        'ggeUSB0928T352': [(22.406102, -74.64204), (22.12204, -74.64204), control_via],
        'ggeUSB0928T353': [control_via, (22.35, -74.05), (22.35, -73.965949),
                          (21.916111, -73.53206), (21.586114, -73.53206),
                          (19.956094, -75.162054), (19.956094, -75.462054)],
        'ggeUSB0928T348': [(22.406102, -74.2419902), (22.2, -74.2419902),
                          (21.3640352, -73.4060254), (21.1210144, -73.4060254)],
    }
    changed = []
    for i, s in enumerate(t['shape']):
        f = s.split('~')
        if f[0] == 'VIA' and f[6] == 'ggeUSB0928V324':
            f[1:3] = path_text([control_via]).split()
        elif f[0] == 'TRACK' and f[5] in paths:
            f[4] = path_text(paths[f[5]])
        else:
            continue
        t['shape'][i] = '~'.join(f)
        changed.append(t['shape'][i])
    # 使用稳定且在源中不存在的ID，避免删图元后递减计数引起含混。
    assert not any('~ggeUSB0928VLeftN~' in s for s in d['shape'])
    batch.add_via(t, 'GND', ground_via, .25, .15)
    f = t['shape'][-1].split('~'); f[6] = 'ggeUSB0928VLeftN'; t['shape'][-1] = '~'.join(f)
    changed.append(t['shape'][-1])
    issues = batch.check_new(t, c, h, changed)
    assert not issues, issues
    assert not old_losses(d, c, t, c, 'U4_C1')
    pad_gaps = [(point, pad['ref'] + '.' + pad['pin'], distance([point], pad['poly']) - .075)
                for point in (control_via, ground_via) for pad in c
                if pad['kind'] == 'pad' and pad['layer'] in ('1', '2')]
    assert min(x[2] for x in pad_gaps) >= .1
    assert [s for s in d['shape'] if s.startswith('LIB~')] == [s for s in t['shape'] if s.startswith('LIB~')]
    assert [s for s in d['shape'] if '~USB_D' in s] == [s for s in t['shape'] if '~USB_D' in s]
    for i, s in enumerate(t['shape']):
        if s.startswith('COPPERAREA~'):
            f = s.split('~'); f[10] = ''; t['shape'][i] = '~'.join(f)
    OUT.write_text(json.dumps(t, ensure_ascii=False, indent=2) + '\n')
    report = {
        '来源SHA256': SHA, '候选SHA256': hashlib.sha256(OUT.read_bytes()).hexdigest(),
        '移除旧局部地孔及其短线': sorted(REMOVED), '修改图元': sorted(paths) + ['ggeUSB0928V324'],
        '新增地孔': 'ggeUSB0928VLeftN', '新增地孔坐标_mm': ground_via,
        '充电控制孔新坐标_mm': control_via, '最小孔钻边至SMT焊盘_mm': min(pad_gaps, key=lambda x:x[2]),
        '本地增量间距错误': issues, '元件_USB线路_规则不变': True,
        '原生地网检查通过': False, '原生DRC检查通过': False, '已保存云端': False, '允许生产': False,
        '必要验收': '原生重铺后所有GND端点须保持单一连通组，左右新地孔均接通L2/L3，USB参考地不退化',
    }
    OUT.with_suffix('.report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(changed, ensure_ascii=False))


if __name__ == '__main__':
    main()
