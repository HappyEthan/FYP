#!/usr/bin/env python3
"""Map a read-only snapshot audit to existing procurement candidates.

Writes review Markdown/JSON only. No source edits, native BOM/CPL generation,
inventory claims, alternative component selections, or ordering operations.
"""
import argparse
import collections
import hashlib
import json
import re
from pathlib import Path


PASSIVE_CANDIDATES = [
    ('C1 C7 C9 C10', 'Murata', 'GRM155R61A105KE15D', 'C76999', '生命周期及工作偏压依据待核；不自动换料'),
    ('C2 C3 C4 C5 C21', 'Murata', 'GRM155R71A104KA01D', 'C71687', '有效容量及供应待核'),
    ('C6', 'Murata', 'GRM155R61C105KA12D', 'C77006', 'USB输入工作偏压下有效容量待核'),
    ('C20', 'Murata', 'GRM21BR61A226ME44L', 'C441864', '现铜/凹口锡膏保留；工厂锡量确认及负载瞬态待核'),
    ('R1 R2', 'YAGEO', 'RC0402FR-075K1L', 'C105872', '候选功率/温漂/装配核准'),
    ('R3 R4', 'YAGEO', 'RC0402FR-0722RL', 'C114765', '候选功率/装配核准；USB路径审核另列'),
    ('R5 R6', 'YAGEO', 'RC0402FR-074K7L', 'C105871', '候选功率/温漂/装配核准；整条I2C上拉另验'),
    ('R7 R8', 'YAGEO', 'RC0402FR-0710KL', 'C60490', '候选功率/温漂/装配核准；R7启动RC另审'),
    ('R9 R11', 'YAGEO', 'RC0402FR-07100KL', 'C60491', '候选功率/温漂/装配核准'),
    ('R10', 'YAGEO', 'RC0402FR-07220KL', 'C138030', '充电电流设定容差/温漂及供应待核'),
    ('R30', 'YAGEO', 'RC0402JR-070RL', 'C60485', 'RF串联零欧姆；寄生及实装匹配待核'),
]
KEY_CANDIDATES = [
    ('U1', 'Espressif', 'ESP32-S3-PICO-1-N8R8', 'C7545129', '已定型号；客供路径；10盘中孔与单次回流待工厂确认'),
    ('U2', 'Melexis', 'MLX90393SLQ-ABA-011-RE', 'C1856300', '已定SLQ/UTDFN-8型号；EP分窗与脚序待装配闭环'),
    ('U3', 'ST', 'LSM6DSOXTR', 'C481766', '已定型号；1脚及原生贴装角度待闭环'),
    ('U4', 'SGMICRO', 'SGM40567-4.2XG/TR', 'C5141336', '已定4.2V型号；客供路径；WLCSP A1与钢网待闭环'),
    ('U5', 'TI', 'TLV75533PDRVR', 'C2861750', '已定PDRVR/WSON型号；EP与贴装方向待闭环'),
    ('U6', 'TI', 'TPD2EUSB30ADRTR', 'C94934', '已定DRT型号；不可按模型角度直接填机器角度'),
    ('D1 D2 D3', 'TI', 'TPD1E10B06DPYR', 'C48260', '已定TI DPY型号；1脚/可双向保护与装配图核对'),
    ('D4', 'LRC', 'LMBR4010BST5G', 'C2912031', '已定型号；1=阴极/VSYS，2=阳极/USB_5V，机器方向待核'),
    ('Q1', 'LRC', 'LP0404N3T5G', 'C172433', '保留原厂焊盘；Q1 DRC及实际阻焊/锡膏工艺待确认'),
    ('J1', 'GCT', 'USB4105-GF-A-060', 'C3025063', '保持T实例修正；-060为壳脚长度；真实装配/板厚待核'),
    ('ANT1', 'Hirose', 'U.FL-R-SMT-1(80)', 'C88374', '沿用既有工程采购候选；原生混写天线且未落实后缀'),
    ('SW2 SW3', 'Panasonic', 'EVPBB2A9B000', '', '原生准确型号已提取；国内准确条目及接贴待确认，不用同系列静默替代'),
]


def key(ref):
    return (re.sub(r'\d+', '', ref), int(re.search(r'\d+', ref)[0]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    audit = json.loads(args.audit.read_text())
    source = Path(audit['snapshot']['path'])
    if hashlib.sha256(source.read_bytes()).hexdigest() != audit['snapshot']['sha256']:
        raise ValueError('Snapshot changed since audit')
    catalogue = {}
    for refs, maker, mpn, code, pending in PASSIVE_CANDIDATES + KEY_CANDIDATES:
        for ref in refs.split():
            if ref in catalogue:
                raise ValueError('Duplicate candidate reference')
            catalogue[ref] = {'manufacturer': maker, 'candidate_mpn': mpn,
                              'historical_domestic_code': code or None, 'pending': pending,
                              'source_record': 'PCB_A5_嘉立创物料与层叠准备.md；电源审核_R_20260929.md；当前PCB原生属性',
                              'procurement_approved': False, 'stock_checked_this_run': False}
    parts = []
    for part in sorted(audit['parts'], key=lambda p: key(p['ref'])):
        ref = part['ref']
        row = {k: part[k] for k in ['ref', 'kind', 'side', 'source_xy_mm',
                                   'native_rotation_deg', 'source_lib_id', 'pads']}
        row['native_value'] = part['source_attributes'].get('Value')
        row['native_mpn'] = part['source_attributes'].get('Manufacturer Part')
        row['native_footprint'] = part['source_attributes'].get('package')
        row['candidate'] = catalogue.get(ref)
        row['machine_placement_verified'] = False
        if part['kind'] == '拟贴装' and row['candidate'] is None:
            raise ValueError('Missing candidate mapping: ' + ref)
        parts.append(row)
    if set(catalogue) != {p['ref'] for p in parts if p['kind'] == '拟贴装'}:
        raise ValueError('Catalogue includes removed or non-fitted positions')
    report = {'status': '仅审核；采购/贴装未放行；禁止生产', 'date_hk': '2026-10-01',
              'snapshot': audit['snapshot'], 'counts': audit['counts'], 'parts': parts,
              'unique_fitted_candidate_mpns': len({p['candidate']['candidate_mpn']
                                                  for p in parts if p['candidate']}),
              'coordinate_convention': audit['coordinate_convention'],
              'native_CPL': '未收到；本文件源坐标不是机器坐标文件',
              'external_items': [{'item': 'FPC天线', 'candidate_mpn': 'FXP75.07.0045B',
                                  'on_PCB_SMT': False, 'status': '既有候选；扣合/转弯/装壳及无线实测待核'},
                                 {'item': '电池/保护、外接开关、导线及笔头模块',
                                  'on_PCB_SMT': False, 'status': '实物/连接及工况待核；电池本轮暂不选'}],
              'supplier_code_policy': '编号沿用历史国内资料，未刷新库存、价格或锁料，不构成接贴批准。'}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir/'BOM与源坐标_仅审核.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    lines = ['# 当前BOM与贴装审核（仅审核，禁止生产）', '',
             '2026-10-01。当前保存重开源码SHA256：`'+audit['snapshot']['sha256']+'`。', '',
             '43位置：38拟贴装（顶层6、底层32）、C30/C31两处DNP、J2/J4/SW1三组纯飞线焊盘；38拟贴装映射为23种完整采购候选。原生23个拟装阻容位置仍为标称值，候选尚未写回工程。', '',
             '国内编号来自既有审核资料；本轮未刷新库存、价格或可分配量，全部尚未批准采购/贴装。SW2/SW3国内准确条目待核。ANT1的原生混写值拆为板上Hirose插座候选及外接FPC天线；没有修改PCB。', '',
             '| 位号 | 数量 | 当前值/型号 | 完整采购候选 | 历史国内编号 | 层/原生角度 | 待闭环 |',
             '|---|---:|---|---|---|---|---|']
    for p in parts:
        c = p['candidate']
        candidate = c['candidate_mpn'] if c else 'DNP，不采购' if p['kind']=='DNP' else '纯焊盘，非SMT采购项'
        pending = c['pending'] if c else 'C30/C31保持不装' if p['kind']=='DNP' else '禁开钢网最终输出、手焊/应力释放及接线待验'
        lines.append(f"| {p['ref']} | {1 if c else 0} | {p['native_value']} | {candidate} | {c['historical_domestic_code'] or '待核' if c else '—'} | {p['side']} / {p['native_rotation_deg']:g}° | {pending} |")
    lines += ['', '角度为原生LIB旋转值，不是已核准的机器角度；底层源坐标未镜像。J1原生0°与模型180°、U6原生90°与模型0°属于不同模型轴定义，不能直接据此改贴装角度。原生CPL的Ref/Mid/Pad坐标及底层约定需另核。', '',
              '外部FPC天线FXP75.07.0045B不计入38个板上SMT数量；电池/保护、外接开关、导线和笔头模块另管。J4=1/3V3、2/GND、3/SDA、4/SCL；J2=1/BAT_P、2/GND；SW1=1/GND、2/REG_EN、3/VSYS。', '',
              '依据：既有物料专题、电源审核、封装差异审核及同源PCB；原厂图纸脚序的有限复核见CAD_HANDOFF。当前原理图↔PCB/ERC、原生BOM/CPL、完整装配图及工厂工艺仍未闭环。', '']
    (args.output_dir/'BOM与贴装审核_仅审核.md').write_text('\n'.join(lines))
    print(json.dumps({'positions': len(parts), 'counts': report['counts'],
                      'unique_candidate_mpns': report['unique_fitted_candidate_mpns'],
                      'outputs': ['BOM与源坐标_仅审核.json', 'BOM与贴装审核_仅审核.md']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
