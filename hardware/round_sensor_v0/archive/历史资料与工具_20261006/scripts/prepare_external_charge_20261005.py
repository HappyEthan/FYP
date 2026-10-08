#!/usr/bin/env python3
"""Bounded edit of fresh recovery sources. Creates local candidates only."""
from pathlib import Path
import copy
import hashlib
import importlib.util
import json
import re

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'easyeda_std/板外充电_20261005'
REPORT = ROOT / 'manufacturing/仅审核禁止生产/板外充电_20261005'

def read(name, digest):
    p = OUT / name
    assert hashlib.sha256(p.read_bytes()).hexdigest() == digest, 'Recovery source changed'
    return json.loads(p.read_text())

def sid(s):
    return re.search(r'(?:~)(gge[^~#^]+)', s).group(1)

def save(name, doc):
    (OUT / name).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n')

sch = read('SCH_板外充电改动前_20261005.json', 'd6826870709d53badc63451d3aa62441b7ea7c40cc26ef31e67c8f1c8be205d6')
pcb = read('PCB_板外充电改动前_20261005.json', '2e0d929363ae3aedd6cba3ed2f054e4dfec2dcc4f4c2163a172b2ec17fac1684')
old_sch, old_pcb = copy.deepcopy(sch), copy.deepcopy(pcb)
page = sch['schematics'][3]
assert page['dataStr']['head']['uuid'] == 'ab32832a4bf64a268a3a58aad92022e3'
page['title'] = '04  供电切换、稳压与开关'
removed_sch = {'ggeA5669', 'ggeA5697', 'ggeA5676'} | {f'ggeA{i}' for i in range(5700, 5719)}
replace_text = {
    'ggeA5536': '04  供电切换、稳压与开关',
    'ggeA5537': 'USB 由电脑供电；拔 USB 后由电池供电。电池拆下后板外充电，板上不充电。',
    'ggeA5663': '本板不对电池充电。',
    'ggeA5744': 'J2 仅为电池供电输入；可拆连接器安装在板外引线上，充电前从板子断开电池。',
    'ggeA5745': '使用带过充、过放及短路保护的 4.2 V 单节电池；外置充电器须匹配电池规格，接线须核对极性。',
    'ggeA5751': '圆形传感板 · SCH-A5 · 板外充电 · 2026-10-05',
}
new_shapes = []
for s in page['dataStr']['shape']:
    k = sid(s)
    if k in removed_sch:
        continue
    if k in replace_text:
        f = s.split('~'); assert f[0] == 'T'; f[12] = replace_text[k]; s = '~'.join(f)
    elif k == 'ggeA5686':
        assert s.startswith('W~190 820 190 800 480 800~')
        s = s.replace('190 820 190 800 480 800', '190 820 190 800')
    elif k == 'ggeA5728':
        assert s.startswith('W~830 800 990 800 990 820~')
        s = s.replace('830 800 990 800 990 820', '990 800 990 820')
    elif k == 'ggeA5739':
        s = s.replace('审查备注`外接带过充、过放及短路保护的4.2V单节电池`', '审查备注`电池供电输入；板外充电；外接带过充、过放及短路保护的4.2V单节电池；可拆连接器在板外引线上`')
    new_shapes.append(s)
page['dataStr']['shape'] = new_shapes
assert len(old_sch['schematics'][3]['dataStr']['shape']) - len(new_shapes) == len(removed_sch)
assert all(sch['schematics'][i] == old_sch['schematics'][i] for i in (0, 1, 2, 4))

# T348/349 terminate at U4 ground pads and existing C6/C7 ground pads.
# T350/351 terminate at U4 BAT/VIN pads and retained shared power junctions.
# No other component or shared power trunk is removed.
removed_pcb = {'ggeA5669', 'ggeA5697'} | {f'ggeUSB0928T{i}' for i in range(348, 355)} | {'ggeUSB0928V324', 'ggeUSB0928V325'}
new_shapes = []
for s in pcb['shape']:
    if sid(s) in removed_pcb:
        continue
    if sid(s) == 'ggeA5739':
        s = s.replace('审查备注`外接带过充、过放及短路保护的4.2V单节电池`', '审查备注`电池供电输入；板外充电；外接带过充、过放及短路保护的4.2V单节电池；可拆连接器在板外引线上`')
    new_shapes.append(s)
pcb['shape'] = new_shapes
assert len(old_pcb['shape']) - len(new_shapes) == len(removed_pcb)
# Drop the obsolete net class only; all retained rules remain byte-for-byte equal.
assert pcb['DRCRULE']['充电设定小孔_025_015']['nets'] == ['U4_C1']
del pcb['DRCRULE']['充电设定小孔_025_015']
pcb['routerRule']['specialNets'] = [n for n in pcb['routerRule']['specialNets'] if n['net'] != 'U4_C1']
pcb['routerRule']['nets'].remove('U4_C1')
pcb['routerRule']['padsCount'] -= 8
assert 'U4_C1' not in json.dumps(pcb, ensure_ascii=False)

spec = importlib.util.spec_from_file_location('net_audit', ROOT / 'scripts/audit_current_netlist.py')
net_audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(net_audit)
def geometry_nets(doc):
    pins, refs, nc, groups, names, find = net_audit.schematic_geometry(doc)
    result = {}
    for k, p in pins.items():
        ns = names[find(p)]
        assert len(ns) <= 1
        result[k] = '' if p in nc else next(iter(ns)) if ns else tuple(sorted(groups[find(p)]))
    return refs, result
old_refs, old_nets = geometry_nets(old_sch)
refs, nets = geometry_nets(sch)
assert set(old_refs) - set(refs) == {'U4', 'R10'}
assert len(refs) == 41
assert all(nets[k] == old_nets[k] for k in nets), 'Retained schematic pin changed net'
old_map = {sid(s): s for s in old_pcb['shape']}
changed = [sid(s) for s in pcb['shape'] if s != old_map[sid(s)]]
assert changed == ['ggeA5739'], changed
assert len([s for s in pcb['shape'] if s.startswith('LIB~')]) == 41
save('SCH_板外充电候选_仅审核_20261005.json', sch)
single_page = copy.deepcopy(sch)
single_page['schematics'] = [single_page['schematics'][3]]
save('SCH_第4页_板外充电候选_仅审核_20261005.json', single_page)
save('PCB_板外充电候选_仅审核_20261005.json', pcb)
report = {
    'date': '2026-10-05', 'scope': 'Local candidates only, not yet applied or native checked',
    'schematic_removed_ids': sorted(removed_sch), 'schematic_modified_ids': sorted(set(replace_text) | {'ggeA5686','ggeA5728','ggeA5739'}),
    'pcb_removed_shapes': [s for s in old_pcb['shape'] if sid(s) in removed_pcb],
    'pcb_modified_ids': changed, 'retained_schematic_pin_networks_unchanged': True,
    'retained_pcb_shapes_exact_except_J2_note': True,
    'obsolete_rules_removed': ['充电设定小孔_025_015', 'routerRule U4_C1 if present'],
    'native_repour_required': True, 'native_DRC_required': True, 'production_released': False,
    'native_application': 'For an existing schematic page, apply only the single-page file. Full five-page source is for independent preview/recovery; applying it to an existing page can overwrite that page with the last page.',
}
(REPORT / '局部候选差异_仅审核.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'refs': len(refs), 'removed_pcb_shapes': len(removed_pcb), 'changed_pcb': changed, 'retained_pin_networks_unchanged': True}, ensure_ascii=False))
