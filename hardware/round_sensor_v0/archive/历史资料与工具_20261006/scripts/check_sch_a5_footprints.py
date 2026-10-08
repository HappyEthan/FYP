"""独立复核五个A5封装原生PAD回读；不等于制造放行。"""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'easyeda_std/footprints'
# 独立录入厂家推荐铜焊盘顶视图，不导入生成器SPECS。
EXPECTED = {
    'U4': {'A1': (-.2, -.4, .2, .2), 'A2': (.2, -.4, .2, .2),
           'B1': (-.2, 0, .2, .2), 'B2': (.2, 0, .2, .2),
           'C1': (-.2, .4, .2, .2), 'C2': (.2, .4, .2, .2)},
    'Q1': {'1': (.35, 0, .4, .55), '2': (-.35, -.17, .4, .2), '3': (-.35, .17, .4, .2)},
    'D4': {'1': (-.35, 0, .4, .7), '2': (.35, 0, .4, .7)},
    'J2': {'1': (-.9, 0, 1.5, 2), '2': (.9, 0, 1.5, 2)},
    'ANT1': {'1': (0, 1.525, 1, 1.05), '2': (-1.475, 0, 1.05, 2.2), '3': (1.475, 0, 1.05, 2.2)}
}
SOURCES = {'U4': 'sgm40567.pdf', 'Q1': 'lp0404n3t5g.pdf',
           'D4': 'lmbr4010bst5g.pdf', 'ANT1': 'Hirose_U.FL_catalog.pdf'}


def check(ref, pads, native=False):
    actual = {}
    for pad in pads:
        p = pad.split('~')
        assert p[0] == 'PAD' and p[6] == '1' and float(p[9]) == 0
        assert p[1] == ('ELLIPSE' if ref == 'U4' else 'RECT')
        assert p[8] not in actual
        values = ((float(p[2])-400)*.254, (float(p[3])-300)*.254,
                  float(p[4])*.254, float(p[5])*.254)
        expected = EXPECTED[ref][p[8]]
        assert all(abs(a-b) < .001 for a, b in zip(values, expected)), (ref, p[8], values)
        if native and p[1] == 'RECT':
            coords = list(map(float, p[10].split()))
            assert len(coords) == 8
            assert abs((max(coords[::2])-min(coords[::2]))*.254-values[2]) < .001
            assert abs((max(coords[1::2])-min(coords[1::2]))*.254-values[3]) < .001
        actual[p[8]] = [round(v, 6) for v in values]
    assert actual.keys() == EXPECTED[ref].keys()
    return actual


def main():
    source = OUT / '原生焊盘回读.json'
    native = json.loads(source.read_text())
    manifest = json.loads((OUT/'封装几何清单.json').read_text())
    results = {}
    for ref in EXPECTED:
        doc = json.loads((OUT/manifest[ref]['file']).read_text())
        check(ref, [s for s in doc['shape'] if s.startswith('PAD~')])
        results[ref] = check(ref, native['焊盘'][ref], native=True)
    assert sum(map(len, results.values())) == 16
    report = {
        '状态': '五个封装共16个原生铜焊盘几何回读通过',
        '日期': native['日期'], '容差毫米': .001,
        '来源SHA256': hashlib.sha256(source.read_bytes()).hexdigest(),
        '厂家图纸SHA256': {ref: hashlib.sha256((ROOT/'references'/file).read_bytes()).hexdigest()
                          for ref, file in SOURCES.items()},
        '坐标格式': '顶视图[x毫米,y毫米,宽毫米,高毫米]，y向下',
        '焊盘': results,
        '更正': ['U4本体0.922×1.155毫米，不是0.9×1.3毫米',
                 'ANT1信号铜焊盘中心y=1.525毫米；旧KiCad参考1.625毫米作废'],
        '制造审核通过': False,
        '限制': ['未设置独立阻焊/钢网扩展，原生默认值尚未审核',
                 'U4的WLCSP工艺能力、Q1的0.14毫米焊盘间隙待板厂确认',
                 'J2手焊电线焊盘须在PCB中禁开钢网并验证应力释放',
                 'ANT1中心禁走线、钢网开口及扣合净空须在PCB落实',
                 '尚无贴装方向、全部41项厂家封装终审、整板电气放行、PCB DRC或实物验证']
    }
    (OUT/'封装原生核验报告.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(report['状态'])
    return report


if __name__ == '__main__':
    main()
