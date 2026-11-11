#!/usr/bin/env python3
"""Launch the live stroke recognizer using existing classifier model artifacts."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))


def main(argv=None):
    parser = argparse.ArgumentParser(description='磁响应实时笔画识别：共享训练工作台的模型历史')
    parser.add_argument('--store',type=Path,help='训练工作台使用的模型历史目录')
    parser.add_argument('--output',type=Path,default=ROOT/'outputs/stroke_recognition/sessions',help='会话保存目录')
    parser.add_argument('--screenshot',type=Path,help='保存窗口截图并退出，不连接传感器')
    parser.add_argument('--replay-session',type=Path,help='只读复判已保存会话并检查最终结果')
    args = parser.parse_args(argv)
    if args.replay_session:
        from brushbot.stroke_recognition.replay import replay_final
        results = replay_final(args.replay_session)
        print(json.dumps(results,ensure_ascii=False,indent=2))
        return 0 if results and all(r['matches'] for r in results) else 1
    if sys.platform.startswith('linux') and os.environ.get('WAYLAND_DISPLAY') and not os.environ.get('QT_QPA_PLATFORM'):
        os.environ['QT_QPA_PLATFORM'] = 'wayland'
    try:
        from PyQt5 import QtCore as C, QtWidgets as W
        from brushbot.stroke_recognition.ui import RecognizerWindow
    except ImportError as exc:
        print(f'缺少实时识别依赖：{exc}\n请使用 {sys.executable} 安装 requirements-stroke-recognition.txt',file=sys.stderr)
        return 2
    W.QApplication.setAttribute(C.Qt.AA_EnableHighDpiScaling,True)
    W.QApplication.setAttribute(C.Qt.AA_UseHighDpiPixmaps,True)
    app = W.QApplication(sys.argv[:1])
    app.setApplicationName('磁响应实时笔画识别')
    app.setStyle('Fusion')
    settings = C.QSettings('Brushbot','LiveStrokeRecognizer')
    store = args.store or Path(settings.value('store',str(ROOT/'outputs/stroke_classifier')))
    window = RecognizerWindow(store,args.output,settings=settings)
    window.show()
    if args.screenshot:
        def capture():
            args.screenshot.parent.mkdir(parents=True,exist_ok=True)
            window.grab().save(str(args.screenshot))
            window.close()
        C.QTimer.singleShot(650,capture)
    return app.exec_()


if __name__=='__main__':
    raise SystemExit(main())
