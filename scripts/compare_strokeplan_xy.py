#!/usr/bin/env python3
"""Extract an image reference and compare V3 target XY; offline geometry only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageOps

from brushbot.xy_comparison.image_reference import extract_reference
from brushbot.xy_comparison.report import compare_plans


def _candidate(value):
    label, separator, path = value.partition('=')
    if not separator or not label.strip() or not path:
        raise argparse.ArgumentTypeError('use LABEL=PATH for each --plan')
    return label, Path(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    extract = sub.add_parser('extract', help='freeze a single-stroke image reference; inspect its preview')
    extract.add_argument('--image', type=Path, required=True)
    scale = extract.add_mutually_exclusive_group(required=True)
    scale.add_argument('--mm-per-pixel', type=float)
    scale.add_argument('--image-width-mm', type=float, help='physical/assigned width of the entire image, including padding')
    extract.add_argument('--origin-px', nargs=2, type=float, help='pixel origin; default is image centre after EXIF rotation')
    extract.add_argument('--origin-mm', nargs=2, type=float, default=(0., 0.))
    extract.add_argument('--rotation-deg', type=float, default=0.)
    extract.add_argument('--threshold', type=int, help='manual dark-foreground threshold 0..254; default Otsu')
    extract.add_argument('--invert', action='store_true', help='invert luminance before thresholding for light-on-dark input')
    extract.add_argument('--min-component-pixels', type=int, default=8)
    extract.add_argument('--simplify-px', type=float, default=.75,
                         help='reference polyline simplification tolerance in pixels; default .75, zero keeps raw pixels')
    extract.add_argument('--component-index', type=int, help='explicit component, sorted by decreasing pixel count, starting at 0')
    extract.add_argument('--start-px', nargs=2, type=float)
    extract.add_argument('--end-px', nargs=2, type=float)
    extract.add_argument('--reverse', action='store_true', help='explicitly reverse the reference direction')
    extract.add_argument('--source-url', help='provenance only; this tool does not fetch URLs')
    extract.add_argument('--output-dir', type=Path, required=True)
    compare = sub.add_parser('compare', help='compare named V3 targets against one frozen reference')
    compare.add_argument('--reference-dir', type=Path, required=True)
    compare.add_argument('--plan', action='append', type=_candidate, required=True, metavar='LABEL=PATH')
    compare.add_argument('--stroke-index', type=int, default=0, help='zero-based stroke index in every candidate; default 0')
    compare.add_argument('--samples', type=int, default=501)
    compare.add_argument('--reference-reviewed', action='store_true', help='record that the caller checked reference extraction and direction')
    compare.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'extract':
            values = vars(args).copy()
            values.pop('command')
            image_path = values.pop('image')
            width_mm = values.pop('image_width_mm')
            if width_mm is not None:
                with Image.open(image_path) as image:
                    values['mm_per_pixel'] = width_mm/ImageOps.exif_transpose(image).width
            report = extract_reference(image_path, **values)
        else:
            report = compare_plans(args.reference_dir, args.plan, args.output_dir,
                                   stroke_index=args.stroke_index, samples=args.samples,
                                   reference_reviewed=args.reference_reviewed)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 2 if report.get('status') == 'needs_review' else 0


if __name__ == '__main__':
    raise SystemExit(main())
