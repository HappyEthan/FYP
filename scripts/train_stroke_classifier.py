#!/usr/bin/env python3
"""Launch the offline dark stroke-classifier desktop. Never connects to hardware."""
import argparse
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))


def main(argv=None):
    parser=argparse.ArgumentParser(description='磁响应七类笔画分类工作台')
    parser.add_argument('--store',type=Path,default=ROOT/'outputs/stroke_classifier',help='模型历史与训练成果目录')
    parser.add_argument('--worker',type=Path,help=argparse.SUPPRESS)
    parser.add_argument('--analysis-worker',type=Path,help=argparse.SUPPRESS)
    parser.add_argument('--screenshot',type=Path,help='保存暗色窗口截图并退出（不训练）')
    args=parser.parse_args(argv)
    if sys.platform.startswith('linux') and os.environ.get('WAYLAND_DISPLAY') and not os.environ.get('QT_QPA_PLATFORM'):
        os.environ['QT_QPA_PLATFORM']='wayland'
    try:
        from PyQt5 import QtWidgets as W,QtCore as C
        from brushbot.stroke_classification.ui import TrainerWindow
    except ImportError as exc:
        print(f'缺少训练界面依赖：{exc}\n请运行：{sys.executable} -m pip install -r {ROOT / "requirements-stroke-training.txt"}',file=sys.stderr)
        return 2
    if args.worker:
        from brushbot.stroke_classification.jobs import worker
        return worker(args.worker)
    if args.analysis_worker:
        from brushbot.stroke_classification.jobs import analysis_worker
        return analysis_worker(args.analysis_worker)
    W.QApplication.setAttribute(C.Qt.AA_EnableHighDpiScaling,True)
    W.QApplication.setAttribute(C.Qt.AA_UseHighDpiPixmaps,True)
    app=W.QApplication(sys.argv[:1]);app.setApplicationName('磁响应笔画分类工作台');app.setStyle('Fusion')
    window=TrainerWindow(args.store);window.show()
    if args.screenshot:
        def capture():
            args.screenshot.parent.mkdir(parents=True,exist_ok=True)
            window.grab().save(str(args.screenshot));window.close();app.quit()
        C.QTimer.singleShot(400,capture)
    return app.exec_()


if __name__=='__main__':raise SystemExit(main())
