#!/usr/bin/env python3
"""Offline-only magnetic scan summary; never imports a hardware adapter."""

import argparse
import json
from pathlib import Path

from brushbot.experiments.calibration import summarize_scan


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    summary = summarize_scan(args.run_dir)
    payload = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
