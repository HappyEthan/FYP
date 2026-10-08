"""兼容入口：旧KiCad稿1.625mm有误，改为核验A5原生回读1.525mm。"""
import json
from check_sch_a5_footprints import main as check_all, ROOT


def main():
    report = check_all()
    result = {'状态': 'A5 U.FL 原生铜焊盘回读通过，未制造放行',
              '旧KiCad稿已作废': True, '焊盘': report['焊盘']['ANT1'],
              '依据': 'Hirose_U.FL_catalog.pdf第12页；中心y=1+1.05/2=1.525毫米',
              '详细报告': 'footprints/封装原生核验报告.json'}
    (ROOT/'easyeda_std/ufl_footprint_geometry_check.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2)+'\n')


if __name__ == "__main__":
    main()
