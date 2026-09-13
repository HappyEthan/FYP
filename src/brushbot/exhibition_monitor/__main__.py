"""Launch the manual exhibition monitor."""

import argparse
import sys

from PyQt5 import QtWidgets

from .window import ExhibitionWindow


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Brushbot manual exhibition monitor")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8765")
    parser.add_argument("--offline", action="store_true", help="show empty data panels without serial imports")
    args = parser.parse_args(argv)
    app = QtWidgets.QApplication(sys.argv if argv is None else [sys.argv[0], *argv])
    window = ExhibitionWindow(backend_url=args.backend_url, offline=args.offline)
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
