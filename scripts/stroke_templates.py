#!/usr/bin/env python3
"""Prepare, review, build and adapt phase-aware XY templates, entirely offline."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from brushbot.stroke_templates.annotations import load_font_record
from brushbot.stroke_templates.bundle import build_bundle, fit_bundle, prepare_bundle, read_json
from brushbot.stroke_templates.catalog import DEFAULT_ROOT, write_catalog


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prepare = sub.add_parser('prepare', help='Create editable annotation and offline HTML')
    prepare.add_argument('--image', type=Path, required=True)
    prepare.add_argument('--character', required=True)
    prepare.add_argument('--graphics', type=Path, default=Path('data/makemeahanzi/graphics.txt'))
    prepare.add_argument('--no-prior', action='store_true', help='Initialize manual tracing without dictionary')
    prepare.add_argument('--output-dir', type=Path, required=True)
    build = sub.add_parser('build', help='Build one type/variant from reviewed image annotations')
    source = build.add_mutually_exclusive_group(required=True)
    source.add_argument('--annotation', type=Path)
    source.add_argument('--references', type=Path, help='JSON list: annotation, image, stroke_id; paths relative to this file')
    build.add_argument('--image', type=Path)
    build.add_argument('--stroke-id')
    build.add_argument('--style-id', required=True)
    build.add_argument('--allow-unreviewed', action='store_true')
    build.add_argument('--body-aspect-range', type=float, nargs=2)
    build.add_argument('--max-bend-widths', type=float, default=2.)
    build.add_argument('--output-dir', type=Path, required=True)
    fit = sub.add_parser('fit', help='Adapt templates; report unsupported strokes explicitly')
    fit.add_argument('--annotation', type=Path, required=True)
    fit.add_argument('--image', type=Path, required=True)
    fit.add_argument('--templates', type=Path, nargs='+', required=True)
    fit.add_argument('--image-width-mm', type=float)
    fit.add_argument('--output-dir', type=Path, required=True)
    demo = sub.add_parser('demo', help='Generate disclosed font fixtures and analytic length-transfer cases')
    demo.add_argument('--graphics', type=Path, default=Path('data/makemeahanzi/graphics.txt'))
    demo.add_argument('--image-size', type=int, default=480)
    demo.add_argument('--output-dir', type=Path, required=True)
    yong = sub.add_parser('yong', help='Generate all five Yong prototypes and a direct local XY correction page')
    yong.add_argument('--graphics', type=Path, default=Path('data/makemeahanzi/graphics.txt'))
    yong.add_argument('--image-size', type=int, default=480)
    yong.add_argument('--output-dir', type=Path, required=True)
    teaching = sub.add_parser('teaching', help='Rebuild provisional templates from disclosed teaching rules and cached illustrations')
    teaching.add_argument('--recipes', type=Path, help='Exported recipe collection JSON; default covers 28 basic types in 38 writing variants')
    from brushbot.stroke_templates.teaching import DEFAULT_SOURCE_DIR
    teaching.add_argument('--source-dir', type=Path, default=DEFAULT_SOURCE_DIR)
    teaching.add_argument('--output-dir', type=Path, required=True)
    guides = sub.add_parser('import-guides', help='Publish frozen teaching guide traces as templates')
    guides.add_argument('--review-dir', type=Path, required=True)
    guides.add_argument('--output-dir', type=Path, required=True)
    tracing = sub.add_parser('trace-guides', help='Track ordered teaching guide seeds against hash-bound cached source images')
    tracing.add_argument('--specs', type=Path, required=True)
    tracing.add_argument('--source-dir', type=Path, required=True)
    tracing.add_argument('--output-dir', type=Path, required=True)
    composition = sub.add_parser('compose', help='Compose a character from explicit library models and a versioned layout recipe')
    composition.add_argument('--recipe', type=Path, required=True)
    composition.add_argument('--output-dir', type=Path, required=True)
    for generate in (prepare, build, fit, demo, yong, teaching, guides, tracing, composition):
        generate.add_argument('--catalog-root', type=Path, help='Refresh this library home after generation; output must be below it')
    catalog = sub.add_parser('catalog', help='Refresh one offline home over template and character directories')
    catalog.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    try:
        catalog_root = None
        if args.command != 'catalog':
            root = (args.catalog_root or DEFAULT_ROOT).resolve()
            output = args.output_dir.resolve()
            if args.catalog_root is not None and (not output.is_relative_to(root) or output == root):
                raise ValueError('--output-dir must be below --catalog-root in its own bundle directory')
            if output.is_relative_to(root) and output != root:
                catalog_root = root
        if args.command == 'catalog':
            result = write_catalog(args.root)
        elif args.command == 'prepare':
            record = None if args.no_prior else load_font_record(args.character, args.graphics)
            result = prepare_bundle(args.image, args.character, args.output_dir,
                                    font_record=record, no_prior=args.no_prior)
        elif args.command == 'build':
            if args.annotation is not None:
                if args.image is None or args.stroke_id is None:
                    raise ValueError('--annotation requires --image and --stroke-id')
                references = [(read_json(args.annotation), args.image, args.stroke_id)]
            else:
                entries = read_json(args.references)
                if not isinstance(entries, list) or not 1 <= len(entries) <= 128:
                    raise ValueError('--references needs a list of 1..128 entries')
                references = []
                for entry in entries:
                    if not isinstance(entry, dict) or set(entry) != {'annotation', 'image', 'stroke_id'}:
                        raise ValueError('each reference requires exactly annotation, image, stroke_id')
                    base = args.references.parent
                    references.append((read_json(base/entry['annotation']), base/entry['image'], entry['stroke_id']))
            limits = dict(max_bend_widths=args.max_bend_widths)
            if args.body_aspect_range is not None:
                limits['body_aspect_range'] = args.body_aspect_range
            result = build_bundle(references, args.output_dir, style_id=args.style_id,
                                  limits=limits, allow_unreviewed=args.allow_unreviewed)
            result.pop('template', None)
        elif args.command == 'fit':
            models = [read_json(p/'template.json' if p.is_dir() else p) for p in args.templates]
            result = fit_bundle(read_json(args.annotation), args.image, models, args.output_dir,
                                image_width_mm=args.image_width_mm)
        elif args.command == 'yong':
            from brushbot.stroke_templates.examples import generate_yong_example
            result = generate_yong_example(args.graphics, args.output_dir, image_size=args.image_size)
        elif args.command == 'teaching':
            from brushbot.stroke_templates.teaching import generate_library
            from brushbot.stroke_templates.teaching_recipes import default_config
            result = generate_library(read_json(args.recipes) if args.recipes else default_config(),args.source_dir,args.output_dir)
        elif args.command == 'import-guides':
            from brushbot.stroke_templates.guide_templates import import_guides
            result = import_guides(args.review_dir, args.output_dir)
        elif args.command == 'trace-guides':
            from brushbot.stroke_templates.guide_tracing import trace_guides
            result = trace_guides(read_json(args.specs), args.source_dir, args.output_dir)
        elif args.command == 'compose':
            from brushbot.stroke_templates.composition import compose_character
            result = compose_character(read_json(args.recipe), args.recipe.parent, args.output_dir)
        else:
            from brushbot.stroke_templates.examples import generate_examples
            result = generate_examples(args.graphics, args.output_dir, image_size=args.image_size)
        if catalog_root is not None:
            try:
                result['catalog_html'] = write_catalog(catalog_root)['catalog_html']
            except (ValueError, OSError) as exc:
                result['catalog_warning'] = 'Result saved, but library home could not be refreshed: '+str(exc)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    result.pop('files', None)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
