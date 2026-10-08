"""把右侧回流 M 纳入本地检查点；不操作云端，不授予生产资格。"""
import hashlib
import json
from collections import Counter
from pathlib import Path

from refine_clone_usb_20260928 import OUT, REPORT, parse, batch, configure, old_losses, save
from audit_clone_native_ground_20260929 import ground_groups

native = Path('/Users/liuchunyu/Downloads/PCBUSBnativeM20260929.json')
source = Path('/Users/liuchunyu/Downloads/PCBUSBnativeL20260929.json')
assert hashlib.sha256(OUT.read_bytes()).hexdigest() == '4751af144c215fdbd8898de9757d4a4d23b3bd6655917e8e57db521cf4a5a3ea'
assert hashlib.sha256(native.read_bytes()).hexdigest() == '7fc15f2b1a61949ca46f6dfedd23bde929286fab0f35aa89cf55bc23c10f3917'
a, pa, ca, ha = parse(source)
b, pb, cb, hb = parse(native)
assert len(pb) == 43 and ca == cb and ha == hb
assert a['DRCRULE'] == b['DRCRULE']


def retained(d):
    items = []
    for s in d['shape']:
        f = s.split('~')
        if f[0] == 'TRACK' and f[5] == 'ggeUSB0928T279':
            continue
        if f[0] == 'VIA' and f[6] == 'ggeUSB0928V329':
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
        old_counts = old_detail['网络'][net][layer]['缺铜分类']
        assert all(n <= old_counts.get(k, 0) for k, n in counts.items()), (net, layer, counts, old_counts)
right = next(x for x in detail['换层回流'] if x['信号孔'] == 'ggeUSB0928V310')
assert right['最近同时接L2L3地孔'][0][1] == 'ggeUSB0928V329'
configure()
changed = [s for s in b['shape'] if s not in a['shape'] and not s.startswith('COPPERAREA~')]
assert not batch.check_new(b, cb, hb, changed)
assert not old_losses(a, ca, b, cb, 'J1_B5')
save(b)
(OUT.parent / 'PCB_克隆板USB局部重布_原生回读_20260929.json').write_bytes(native.read_bytes())
(OUT.parent / '克隆板USB换层回流细查_20260929.json').write_bytes(native.with_suffix('.reference.json').read_bytes())
report = json.loads(REPORT.read_text())
report['USB右侧回流原生M复查'] = {
    '原生SHA256': detail['SHA256'], '原生DRC': 1, '原生未连接': 0,
    '实际地铜连通组': 1, '修改图元': ['ggeUSB0928T279'], '新增地孔': 'ggeUSB0928V329',
    '右侧回流距离_mm_前后': [1.6264706098, right['最近同时接L2L3地孔'][0][0]],
    '其他图元规则铺铜边界不变': True, 'USB线路与元件不变': True,
    'USB_DP底层邻域未解释缺铜采样_前后': [97, 50],
    '中心线除USB孔避空外缺铜采样': 0,
    '左侧后续局部试算': 'U4_C1孔移近后侵入USB_DM参考邻域；U6单独下移仍与交错扇出/地线冲突，均未采用',
    'USB总体已验收': False, '云端保存': False, '允许生产': False,
    '待办': ['左侧USB换层回流与侧向参考面', '90欧姆阻抗及厂家层叠', '电源压降去耦', 'Q1沉金与PICO钢网制造审核'],
}
report['当前本地检查点'] = 'M'
report['当前候选SHA256'] = hashlib.sha256(OUT.read_bytes()).hexdigest()
REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(report['USB右侧回流原生M复查'], ensure_ascii=False, indent=2))
print('候选SHA256', report['当前候选SHA256'])
