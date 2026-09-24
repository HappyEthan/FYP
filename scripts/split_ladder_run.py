#!/usr/bin/env python3
"""Offline-only: split one ladder run into one CSV per pass.

Never imports a hardware adapter and never connects to the robot.
"""

from __future__ import annotations

import argparse

from brushbot.experiments.calibration import split_ladder_passes


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", help="ladder run directory")
    parser.add_argument("--output", help="defaults to <run_dir>/passes")
    args = parser.parse_args(argv)
    for path in split_ladder_passes(args.run_dir, args.output):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())