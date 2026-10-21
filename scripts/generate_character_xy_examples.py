#!/usr/bin/env python3
"""Rasterize whole local Make Me a Hanzi glyphs, then run generic XY extraction."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.patches import PathPatch
import numpy as np
from PIL import Image

from brushbot.character_xy import extract_character
from brushbot.vector_paths import vector_path


def generate(graphics_path, output_dir, characters='字中永人口', image_size=600):
    if not characters or not 128 <= image_size <= 1400:
        raise ValueError('characters must be nonempty and image_size must be 128..1400')
    graphics = Path(graphics_path)
    selected = {}
    for line in graphics.read_text(encoding='utf-8').splitlines():
        item = json.loads(line)
        if item['character'] in characters:
            selected[item['character']] = item
    if set(characters)-selected.keys():
        raise ValueError('characters absent from local graphics: '+''.join(set(characters)-selected.keys()))
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    source_hash = hashlib.sha256(graphics.read_bytes()).hexdigest()
    cases = []
    for character in dict.fromkeys(characters):
        case = output/f'u{ord(character):04x}'
        case.mkdir()
        outlines = selected[character]['strokes']
        shapes = [vector_path(outline) for outline in outlines]
        boxes = [shape.get_extents() for shape in shapes]
        low = np.min([[b.x0, b.y0] for b in boxes], axis=0)
        high = np.max([[b.x1, b.y1] for b in boxes], axis=0)
        centre = (low+high)/2
        extent = max(high-low)*1.18
        figure = Figure(figsize=(image_size/100, image_size/100), dpi=100, facecolor='white')
        canvas = FigureCanvasAgg(figure)
        axis = figure.add_axes([0, 0, 1, 1])
        for shape in shapes:
            axis.add_patch(PathPatch(shape, facecolor='black', edgecolor='none'))
        axis.set(xlim=(centre[0]-extent/2, centre[0]+extent/2),
                 ylim=(centre[1]-extent/2, centre[1]+extent/2))
        axis.set_axis_off()
        canvas.draw()
        Image.fromarray(np.asarray(canvas.buffer_rgba())).convert('RGB').save(case/'input.png')
        figure.clear()
        provenance = dict(character=character, graphics_path=str(graphics.resolve()), graphics_sha256=source_hash,
            source_url='https://github.com/skishore/makemeahanzi', outlines=outlines,
            note='All outlines rasterized together. Extraction sees only the bitmap; no medians or stroke labels.')
        (case/'font_source.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        result = extract_character(case/'input.png', case/'geometry', source_url=provenance['source_url'])
        cases.append(dict(character=character, directory=case.name, geometry_id=result['geometry_id'],
                          statistics=result['statistics'], review_flags=result['review_flags']))
    (output/'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    cards = ''.join('<a class="card" href="'+c['directory']+'/geometry/report.html"><h2>'+
                    html.escape(c['character'])+'</h2><img src="'+c['directory']+
                    '/geometry/preview.png"><p>'+str(c['statistics']['path_segment_count'])+' 条路径 · '+
                    str(c['statistics']['junction_region_count'])+' 个分叉区域 · 点击交互复核</p></a>' for c in cases)
    (output/'index.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><title>整字 XY 示例</title>'
        '<style>body{font-family:system-ui,sans-serif;background:#f4f6fa;color:#17243b;max-width:1200px;margin:30px auto;padding:16px}'
        '.card{display:block;background:white;border:1px solid #dce3ed;border-radius:12px;padding:20px;margin:20px 0;color:inherit;text-decoration:none}'
        'img{width:100%}h2{margin:0}p{line-height:1.7}</style><h1>整字 XY 提取示例</h1>'
        '<p>输入来自本地字库整字轮廓。提取过程只读取栅格图片，不读取笔顺和字库中心线。'
        '这些示例验证离线几何流程，不能据此推断任意书法照片的提取质量。</p>'+cards+'</html>', encoding='utf-8')
    return cases


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graphics', type=Path, default=Path('data/makemeahanzi/graphics.txt'))
    parser.add_argument('--characters', default='字中永人口')
    parser.add_argument('--image-size', type=int, default=600)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = generate(args.graphics, args.output_dir, args.characters, args.image_size)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
