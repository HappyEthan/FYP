#!/usr/bin/env python3
"""Extract whole-character XY geometry and a self-contained interactive report."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from brushbot.character_xy import extract_character


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, required=True, help='one cropped character image; no OCR required')
    parser.add_argument('--output-dir', type=Path, required=True, help='new directory; existing paths are refused')
    scale = parser.add_mutually_exclusive_group()
    scale.add_argument('--mm-per-pixel', type=float, help='explicit physical scale; otherwise XY stays in original-image px')
    scale.add_argument('--image-width-mm', type=float, help='width of the entire EXIF-corrected source, including padding')
    parser.add_argument('--origin-px', nargs=2, type=float, help='origin in full EXIF-corrected image; default image centre')
    parser.add_argument('--origin-xy', nargs=2, type=float, default=(0., 0.), help='XY origin in the selected units')
    parser.add_argument('--rotation-deg', type=float, default=0., help='counterclockwise rotation after converting to x right/y up')
    threshold = parser.add_mutually_exclusive_group()
    threshold.add_argument('--threshold', type=int, help='fixed dark-ink threshold 0..254; default Otsu')
    threshold.add_argument('--adaptive', action='store_true', help='local Gaussian threshold for uneven illumination')
    parser.add_argument('--adaptive-window', type=int, default=31)
    parser.add_argument('--adaptive-offset', type=float, default=10.)
    parser.add_argument('--invert', action='store_true', help='light lettering on a dark background')
    parser.add_argument('--min-component-pixels', type=int, default=8, help='minimum ink area after resize; use 1 to keep tiny dots')
    parser.add_argument('--simplify-px', type=float, default=.75, help='tolerance in processed-image px; 0 keeps raw path vertices')
    parser.add_argument('--max-side-px', type=int, default=1400, help='processed image side limit, 64..4096; also limited to 2M pixels')
    parser.add_argument('--crop', nargs=4, type=int, metavar=('LEFT', 'TOP', 'RIGHT', 'BOTTOM'), help='ROI in EXIF-corrected original pixels')
    parser.add_argument('--source-url', help='optional provenance text; does not fetch the URL')
    values = vars(parser.parse_args(argv))
    image, output = values.pop('image'), values.pop('output_dir')
    try:
        result = extract_character(image, output, **values)
    except (ValueError, OSError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
