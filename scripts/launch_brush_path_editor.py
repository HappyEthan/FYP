#!/usr/bin/env python3
"""Open the saved path editor without keeping a terminal attached."""
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def main():
    log_path = ROOT / 'outputs/brush_path_editor/window_v3.log'
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open('a') as log:
        subprocess.Popen(
            [str(ROOT / '.venv/bin/python'),
             str(ROOT / 'scripts/edit_brush_path.py'), '--resume'],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            start_new_session=True,
        )


if __name__ == '__main__':
    main()
