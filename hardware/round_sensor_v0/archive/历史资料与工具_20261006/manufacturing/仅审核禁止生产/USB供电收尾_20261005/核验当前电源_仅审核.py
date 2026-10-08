"""只解析指定的当前源，生成USB供电审核JSON；不调用生成器或修改CAD。"""
from pathlib import Path
import csv
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'scripts'))
from check_pcb_a5 import parse  # 仅调用无写入的parse，不调用audit/main

INPUTS = {
    'PCB': ('easyeda_std/C9替料_20261005/PCB_C9替料_重铺保存重开_20261005.json',
            '9bf591e459d91d93a55d6c76143323030acbc7299e75c267a41acebdb0801e84'),
    'SCH': ('easyeda_std/C9替料_20261005/SCH_C9替料_五页保存重开_20261005.json',
            'f12df6b7c3b48995aeb676819535489141a1fa7e1d8c71d9f2a18f62c824a4c1'),
    'Gerber': ('manufacturing/仅审核禁止生产/C9替料_20261005/Gerber_C9替料_仅审核_20261005.zip',
               '405203473d8226ca9bf638fafe6d3e5d8cc44decabd9ece37f46ff417a5050a0'),
}
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

for path, expected in INPUTS.values():
    assert sha(ROOT / path) == expected, f'来源变化：{path}'

d, parts, copper, holes = parse(ROOT / INPUTS['PCB'][0])
assert len(parts) == 41 and 'U4' not in parts and 'R10' not in parts
nets = sorted({p['net'] for p in copper if p['net']})
assert len(nets) == 20
pinmap = {}
for p in copper:
    if p['kind'] == 'pad':
        old = pinmap.setdefault(p['ref'], {}).setdefault(p['pin'], p['net'])
        assert old == p['net']

expected_pins = {
    'Q1': {'1': 'BAT_P', '2': 'USB_5V', '3': 'VSYS'},
    'D4': {'1': 'VSYS', '2': 'USB_5V'},
    'U5': {'1': '3V3', '2': '', '3': 'GND', '4': 'REG_EN', '5': '', '6': 'VSYS', '7': 'GND'},
    'R9': {'1': 'USB_5V', '2': 'GND'},
    'R11': {'1': 'REG_EN', '2': 'GND'},
    'R1': {'1': 'J1_A5', '2': 'GND'},
    'R2': {'1': 'J1_B5', '2': 'GND'},
    'C6': {'1': 'USB_5V', '2': 'GND'},
    'C7': {'1': 'BAT_P', '2': 'GND'},
    'C9': {'1': 'VSYS', '2': 'GND'},
    'C10': {'1': '3V3', '2': 'GND'},
    'SW1': {'1': 'GND', '2': 'REG_EN', '3': 'VSYS'},
    'J2': {'1': 'BAT_P', '2': 'GND'},
}
for ref, pins in expected_pins.items():
    assert pinmap[ref] == pins, ref
assert 'USB_5V' not in pinmap['U1'].values()
assert 'J1_A5' not in pinmap['U1'].values() and 'J1_B5' not in pinmap['U1'].values()
assert pinmap['U1']['25'] == 'USB_DM_SOC' and pinmap['U1']['26'] == 'USB_DP_SOC'

attributes = {}
for s in d['shape']:
    if not s.startswith('LIB~'):
        continue
    rows = [v.split('~') for v in s.split('#@$')]
    ref = next(v[10] for v in rows[1:] if v[:2] == ['TEXT', 'P'])
    words = rows[0][3].split('`')
    attributes[ref] = dict(zip(words[::2], words[1::2]))

assert attributes['C9']['Manufacturer Part'] == 'GRM155R61A475MEAAD'
for ref in ['R9', 'R11']:
    assert attributes[ref]['Value'] == '100k'

bompath = ROOT / 'manufacturing/仅审核禁止生产/C9替料_20261005/BOM_36件准确料号_C9替料_仅审核_20261005.csv'
with bompath.open(encoding='utf-8-sig', newline='') as f:
    bom = list(csv.DictReader(f))
assert len(bom) == 36 and sum(int(x['单板数量']) for x in bom) == 36
assert len({x['完整料号'] for x in bom}) == 22

oldpath = ROOT / 'manufacturing/仅审核禁止生产/电源定量复核_20261005/电源与电容定量审核_仅审核.json'
old = json.loads(oldpath.read_text())
scenarios = []
for current in [100, 200, 300, 400, 500]:
    amperes = current / 1000
    scenarios.append({
        'system_output_mA_assumed_not_measured': current,
        'USB_main_path_mA_approx_excluding_aux': current,
        'LDO_loss_W_at_USB5_D4drop0p3': round((5 - .3 - 3.3) * amperes, 3),
        'D4_loss_W_at_assumed0p3V': round(.3 * amperes, 3),
        'power_path_loss_W_at_USB5': round((5 - 3.3) * amperes, 3),
        'power_path_loss_W_at_USB5p5': round((5.5 - 3.3) * amperes, 3),
        'Q1_drop_V_25C_at_0p67ohm_model': round(.67 * amperes, 3),
        'battery_V_for3p3_approx_not_cutoff': round(3.3 + (.67 + .215 / .5) * amperes, 2),
    })

refs = [
    ('references/esp32-s3_TRM_USB审核_20261005.pdf', 'https://documentation.espressif.com/esp32-s3_technical_reference_manual_en.pdf', '本轮渲染查看第1257页寄存器及提取第33章；v1.8'),
    ('references/lp0404n3t5g.pdf', 'https://www.lrc.cn/Upload/PDF/Product/MOS/LP0404N3T5G.pdf', '本轮渲染查看第1页方向、额定；Rev.G Aug2024；图无数字脚号'),
    ('references/lmbr4010bst5g.pdf', 'https://www.lrc.cn/Upload/PDF/Product/SBD/LMBR4010BST5G.pdf', '复用此前阴阳极及功率资料；不写本轮新机械验收'),
    ('references/tlv755p.pdf', 'https://www.ti.com/lit/ds/symlink/tlv755p.pdf', '复用电流/压差依据；功耗为计算场景，非热验收'),
]
report = {
    'date': '2026-10-05',
    'status': '仅审核；USB供电纸面复核完成，USB电流/暂停/无VBUS连接未证明满足；生产未放行',
    'scope': '当前41元件/C9替料保存源只读核验、删除充电后的预算和使用条件；本轮未操作在线EDA，未运行新原生ERC/DRC',
    'project_id': '3c2f1824ae2d4fd391ecd83abc2b3411',
    'PCB_doc_id': 'cca094630ebf453c98ae64b900f0d7f0',
    'inputs': {k: {'path': v[0], 'sha256': v[1]} for k, v in INPUTS.items()},
    'components': len(parts), 'nets': len(nets),
    'SMT_count': 36, 'MPN_count': 22,
    'current_power_parts': {ref: {'source_Value': attributes[ref].get('Value'), 'pins': pins} for ref, pins in expected_pins.items()},
    'USB_connector_pins': pinmap['J1'],
    'MCU_pins': pinmap['U1'],
    'board_charging_branch_present': False,
    'MCU_VBUS_sense_present': False,
    'MCU_CC_current_sense_present': False,
    'native_checks_reused': {'date': '2026-10-05上一轮C9替料', 'connected_nets': '20/20', 'unconnected': 0, 'DRC': '唯一Q1：gge2100到gge2115，0.1398524 < 0.1500124 mm；未忽略/放宽；本轮未新跑'},
    'historical_budget_superseded': {'path': str(oldpath.relative_to(ROOT)), 'sha256': sha(oldpath), 'why': '旧表含已删除U4/R10和约109.09mA充电，旧USB总流与热表不能套用当前板；只复用注明假设的器件/负载资料'},
    'power_scenarios': scenarios,
    'auxiliary_currents': {'R9_at5V_uA': 50, 'R9_at5p5V_uA': 55, 'R11_at4p7V_switch_on_uA': 47, 'excluded': 'U5静态、CC、保护漏电、瞬态及外部模块未汇总保证'},
    'loads_reused_with_conditions': old['loads'],
    'budget_limits': [
        'USB电流近似为系统负载+辅助；LDO500mA是输出能力，既非USB端口授权也非整板实测峰值。',
        'D4压降0.3V只是场景；总路径损耗=(VBUS-3.3)*I，未含铜/静态/主控/传感器损耗。',
        'Q1压降及低电量模型复用25C/-2.5V下0.67ohm和LDO215mV@500mA线性近似，不是全温保证/固件关机阈值。',
        '没有充电器，不代表USB电流规范自动通过；300mA是复核场景，尚无固件限幅。',
        'C9名义从1到4.7uF，5.5V下增加约20.35uC只是标称差值；不能据此或只统计C6/C9证明整个USB接入冲击通过。',
    ],
    'USB_requirements': {
        'USB2_default_before_configuration_mA': 100,
        'USB2_configured_max_mA_with_host_allocation': 500,
        'USB_suspend_bus_current_max_mA': 2.5,
        'scope_note': '普通USB2.0主机供电条件；电池自身供电电流不计入VBUS暂停电流。USB-C/BC特殊授权不凭两个Rd自动假定。实际描述符/主机配置未读取，非合规认证。',
        'source': 'https://www.usb.org/sites/default/files/3.2%20Interoperability%20Testing%20v0.99%20w%20USB%20Type-C.pdf',
        'suspend_source': 'https://compliance.usb.org/index.asp?UpdateFile=Electrical',
    },
    'firmware_not_implemented': [
        'USB采集启动前的默认轻载、配置/主机请求后启用高负载；测枚举前实际VBUS电流。',
        '暂停/恢复的电流和状态处理；SOF连接检测不等于配置或供电授权。',
        '电池运行时USB PHY策略；软件控制PAD可用，但无VBUS检测无法可靠区分暂停和拔插/主机关机。',
    ],
    'references': [{'path': p, 'sha256': sha(ROOT / p), 'url': u, 'use': use} for p, u, use in refs],
    'web_sources': [
        'https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-guides/usb-serial-jtag-console.html',
        'https://github.com/espressif/esp-idf/blob/master/components/esp_driver_usb_serial_jtag/include/driver/usb_serial_jtag.h',
        'https://docs.espressif.com/projects/esp-usb/en/latest/esp32s3/usb_device.html#self-powered-device',
        'https://compliance.usb.org/index.asp?UpdateFile=Electrical',
    ],
    'sources_changed': False, 'manufacturing_geometry_changed': False,
    'native_DRC_rerun': False, 'production_released': False,
}
for path, expected in INPUTS.values():
    assert sha(ROOT / path) == expected
destination = OUT / '当前USB供电与无充电预算_仅审核.json'
destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'report': str(destination), 'parts': 41, 'nets': 20, 'charged_branch_removed': True, 'VBUS_sense': False, 'source_hashes_unchanged': True, 'USB5V_300mA_path_loss_W': scenarios[2]['power_path_loss_W_at_USB5']}, ensure_ascii=False))
