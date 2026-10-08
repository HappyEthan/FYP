"""纳入左侧回流 N 本地检查点；不保存云端，不授予生产资格。"""
import hashlib
import json
from collections import Counter
from pathlib import Path

from refine_clone_usb_20260928 import OUT, REPORT, parse, batch, configure, old_losses, save
from audit_clone_native_ground_20260929 import ground_groups

native = Path('/Users/liuchunyu/Downloads/PCBUSBnativeN20260929.json')
source = Path('/Users/liuchunyu/Downloads/PCBUSBnativeM20260929.json')
assert hashlib.sha256(OUT.read_bytes()).hexdigest() == '305a32f2982f685e7dfdd35ebc04e33821c6b00957356c07de4bd0e3071e88c4'
assert hashlib.sha256(native.read_bytes()).hexdigest() == 'f998ec51c0e39f8677129d6a72361ed6ccfdadbf1a4a4367d3309032408a1c45'
a, pa, ca, ha = parse(source)
b, pb, cb, hb = parse(native)
assert len(pb) == 43 and ca == cb and ha == hb
assert a['DRCRULE'] == b['DRCRULE']
allowed = {'ggeUSB0928V318', 'ggeUSB0928V285', 'ggeUSB0928V324', 'ggeUSB0928VLeftN',
           'ggeUSB0928T422', 'ggeUSB0928T284', 'ggeUSB0928T348', 'ggeUSB0928T352', 'ggeUSB0928T353'}


def retained(d):
    items = []
    for s in d['shape']:
        f = s.split('~')
        if f[0] == 'TRACK' and f[5] in allowed:
            continue
        if f[0] == 'VIA' and f[6] in allowed:
            continue
        if f[0] == 'COPPERAREA':
            f[10] = ''; s = '~'.join(f)
        items.append(s)
    return Counter(items)


assert retained(a) == retained(b), '存在非目标修改'
assert len(ground_groups(b, cb)) == 1
detail = json.loads(native.with_suffix('.reference.json').read_text())
old_detail = json.loads(source.with_suffix('.reference.json').read_text())
assert detail['SHA256'] == hashlib.sha256(native.read_bytes()).hexdigest()
for net, layers in detail['网络'].items():
    for layer, item in layers.items():
        counts = item['缺铜分类']
        assert not any(k.startswith('中心线/') and k != '中心线/USB信号孔避空' for k in counts)
        previous = old_detail['网络'][net][layer]['缺铜分类']
        assert all(n <= previous.get(k, 0) for k, n in counts.items()), (net, layer, counts, previous)
left = next(x for x in detail['换层回流'] if x['信号孔'] == 'ggeUSB0928V308')
right = next(x for x in detail['换层回流'] if x['信号孔'] == 'ggeUSB0928V310')
assert left['最近同时接L2L3地孔'][0][1] == 'ggeUSB0928VLeftN'
assert right['最近同时接L2L3地孔'][0][1] == 'ggeUSB0928V329'
configure()
changed = [s for s in b['shape'] if s not in a['shape'] and not s.startswith('COPPERAREA~')]
assert not batch.check_new(b, cb, hb, changed)
assert not old_losses(a, ca, b, cb, 'U4_C1')
save(b)
(OUT.parent / 'PCB_克隆板USB局部重布_原生回读_20260929.json').write_bytes(native.read_bytes())
(OUT.parent / '克隆板USB换层回流细查_20260929.json').write_bytes(native.with_suffix('.reference.json').read_bytes())
report = json.loads(REPORT.read_text())
report['USB左侧回流原生N复查'] = {
    '原生SHA256': detail['SHA256'], '原生DRC': 1, '原生未连接': 0,
    '实际地铜连通组': 1, '目标图元': sorted(allowed),
    '说明': '外绕U4_C1支路，移除两旧地孔及两段地短线，调整U4.B1接地短线，新增左侧回流孔；地网仍完整',
    '左侧回流距离_mm_前后': [1.4134656349, left['最近同时接L2L3地孔'][0][0]],
    '右侧回流距离_mm': right['最近同时接L2L3地孔'][0][0],
    '其他图元规则铺铜边界不变': True, 'USB线路与元件不变': True,
    'USB_DM邻域未解释缺铜采样_前后': {'L2': [105, 53], 'L3': [65, 29]},
    'USB_DM邻域其他网络孔附近缺铜采样_前后': {'L2': [260, 1], 'L3': [18, 1]},
    '其他缺铜分类未增加': True, '中心线除USB孔避空外缺铜采样': 0,
    'USB总体已验收': False, '云端保存': False, '允许生产': False,
    '待办': ['USB侧向参考面和反焊盘过渡', '90欧姆阻抗及厂家层叠', '电源压降去耦', 'Q1沉金与PICO钢网制造审核'],
}
report['当前本地检查点'] = 'N'
report['当前候选SHA256'] = hashlib.sha256(OUT.read_bytes()).hexdigest()
REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(report['USB左侧回流原生N复查'], ensure_ascii=False, indent=2))
print('候选SHA256', report['当前候选SHA256'])
