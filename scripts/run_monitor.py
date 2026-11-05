#!/usr/bin/env python3
"""启动 Monitor 主界面，无需手动设置 PYTHONPATH。"""

from pathlib import Path
import os
import sys


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))
    os.chdir(root)

    from brushbot.monitor.window import main as monitor_main

    return monitor_main(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
