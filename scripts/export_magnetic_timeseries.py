#!/usr/bin/env python3
"""Export a recorded run's full-rate magnetic samples; no hardware access."""
import argparse
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from brushbot.experiments.magnetic_timeseries import export_magnetic_timeseries

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run_dir',type=Path)
    report=export_magnetic_timeseries(parser.parse_args().run_dir)
    print('连续磁响应数据：',report['output'])
    print(f'样本{report["sensor_samples"]}条；典型采样频率{report["nominal_sensor_rate_hz"]} Hz；时间间隔异常{len(report["gaps"])}处；未插值补点。')
