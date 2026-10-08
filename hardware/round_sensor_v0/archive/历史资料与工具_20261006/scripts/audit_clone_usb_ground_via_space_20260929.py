"""L版 USB 换层孔附近地孔空间扫描；只读PCB，输出本地诊断报告。"""
import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from refine_clone_usb_20260928 import batch, configure, parse
from audit_clone_native_ground_20260929 import contains, regions
from check_pcb_a5 import ROOT

SOURCE = Path('/Users/liuchunyu/Downloads/PCBUSBnativeL20260929.json')
SHA256 = '66bd2734de881f1fe879cff9712950e9c07a5f7689cf25396034a722a69544c8'
OUTPUT = ROOT / 'easyeda_std/克隆板USB回流地孔可放置性_20260929.json'
TARGETS = {
    'USB_DP左孔V308': (22.737064, -75.900026),
    'USB_DP右孔V310': (23.737062, -75.900026),
    'USB_DM孔V314': (22.059900, -75.140058),
}
ROI = (21.0, 24.8, -76.5, -74.3)


def audit():
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == SHA256, '当前PCB已变，停止使用旧坐标'
    doc, _, copper, holes = parse(SOURCE)
    configure()
    ground = regions(doc)
    result = {
        '来源': str(SOURCE), 'SHA256': SHA256,
        '扫描范围_mm': ROI, '网格步距_mm': .04,
        '筛选': '现有DRC异网间距、机械孔与U.FL净空候选；候选中心须落在原生L2/L3实际GND铜内',
        '限制': '离散网格与既有布线下的诊断；未重铺新增地孔后的铜，也未证明其他局部重布不可行',
        '当前方案': {}, '目标孔': TARGETS,
        '方案': {}, '障碍示例': {},
        'USB回流已验收': False, '可以生产': False,
    }
    current_return = json.loads(SOURCE.with_suffix('.reference.json').read_text())
    assert current_return['SHA256'] == SHA256
    for item in current_return['换层回流']:
        if item['信号孔'] in ('ggeUSB0928V308', 'ggeUSB0928V310', 'ggeUSB0928V314'):
            result['当前方案'][item['信号孔']] = {
                '最近同时接入两层实际地铜的地孔': item['最近同时接L2L3地孔'][0],
            }
    for od, drill in ((.25, .15), (.20, .10)):
        xs, ys, _, via_free = batch.obstacles(doc, copper, holes, 'GND', .15, od, drill, (22.7, -75.9))
        yi, xi = np.where(via_free & (xs[None, :] > ROI[0]) & (xs[None, :] < ROI[1]) &
                          (ys[:, None] > ROI[2]) & (ys[:, None] < ROI[3]))
        points = np.stack((xs[xi], ys[yi]), axis=1)
        mask = np.ones(len(points), bool)
        for layer in ('21', '22'):
            covered = np.zeros(len(points), bool)
            for local_layer, rings in ground:
                if local_layer == layer:
                    covered |= contains(rings, points)
            mask &= covered
        points = points[mask]
        per_target = {}
        for name, target in TARGETS.items():
            distances = np.linalg.norm(points - np.array(target), axis=1)
            if len(distances):
                best = int(np.argmin(distances))
                per_target[name] = {
                    '最近候选距离_mm': round(float(distances[best]), 4),
                    '最近候选坐标_mm': [round(float(x), 4) for x in points[best]],
                    '一毫米内候选网格数': int(np.count_nonzero(distances < 1.0)),
                }
        result['方案'][f'{od:.2f}/{drill:.2f}mm'] = {
            '双地层覆盖且局部避让通过的网格数': len(points), '各换层孔': per_target,
        }
    for point in ((23.2, -75.5), (23.2, -75.8), (23.2, -76.0), (22.55, -75.3)):
        trial = copy.deepcopy(doc)
        batch.add_via(trial, 'GND', point, .25, .15)
        result['障碍示例'][str(point)] = batch.check_new(trial, copper, holes, trial['shape'][-1:])[:6]
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result


if __name__ == '__main__':
    report = audit()
    print(json.dumps({'SHA256': report['SHA256'], '方案': report['方案'],
                      '障碍示例': report['障碍示例']}, ensure_ascii=False, indent=2))
