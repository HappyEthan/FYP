"""Reproducible font and analytic fixtures; not calligraphic ground truth."""
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.patches import PathPatch
import numpy as np
from PIL import Image, ImageDraw

from brushbot.vector_paths import vector_path
from .annotations import load_font_record, prepare_annotation
from .bundle import build_bundle, fit_bundle, load_fitted_geometry, prepare_bundle, publish, read_json, write_json
from .report import CSS


REFERENCE_CHARACTERS = '一二三十工'
TEST_CHARACTERS = '土王干士永'


def _yong_models(annotation, image, directory):
    return [build_bundle([(annotation, image, s['id'])], directory/s['type'],
        style_id='yong_font_prototype', allow_unreviewed=True)['template'] for s in annotation['strokes']]


def generate_yong_example(graphics_path, output_dir, *, image_size=480):
    if type(image_size) is not int or not 128 <= image_size <= 1400:
        raise ValueError('image_size must be 128..1400')
    record = load_font_record('永', graphics_path)
    def write(stage):
        image = stage/'input.png'
        transform = _render_font(record, image, image_size)
        annotation = prepare_annotation(image, '永', font_record=record, font_transform=transform,
                                        image_kind='font_fixture')
        templates = _yong_models(annotation, image, stage/'templates')
        fit_bundle(annotation, image, templates, stage/'fit')
        geometry = load_fitted_geometry(stage/'fit')
        write_json(stage/'source.json', dict(source_url='https://github.com/skishore/makemeahanzi',
            record=record, transform=transform, same_glyph_prototype=True, independent_ground_truth=False,
            note='Five font-derived geometric prototypes. This is a workflow test, not held-out quality evidence.'))
        return dict(character='永', complete=geometry['complete'], same_glyph_prototype=True,
                    independent_ground_truth=False, physical_validation=False)
    result = publish(output_dir, 'yong_template_example', write)
    result['report_html'] = str(Path(result['output_dir'])/'fit/review.html')
    return result


def _render_font(record, destination, image_size):
    paths = [vector_path(s) for s in record['strokes']]
    boxes = [p.get_extents() for p in paths]
    low = np.min([[b.x0, b.y0] for b in boxes], axis=0)
    high = np.max([[b.x1, b.y1] for b in boxes], axis=0)
    centre = (low+high)/2
    extent = max(high-low)*1.18
    figure = Figure(figsize=(image_size/100, image_size/100), dpi=100, facecolor='white')
    canvas = FigureCanvasAgg(figure)
    axis = figure.add_axes([0, 0, 1, 1])
    for path in paths:
        axis.add_patch(PathPatch(path, facecolor='black', edgecolor='none'))
    axis.set(xlim=(centre[0]-extent/2, centre[0]+extent/2), ylim=(centre[1]-extent/2, centre[1]+extent/2))
    axis.set_axis_off()
    canvas.draw()
    Image.fromarray(np.asarray(canvas.buffer_rgba())).convert('RGB').save(destination)
    figure.clear()
    scale = image_size/extent
    # Pixel-centre coordinates, consistent with the rasterized viewport.
    return dict(scale=scale, offset_xy_px=((image_size-1)/2-centre*scale).tolist())


def _analytic_case(directory, body_span):
    directory.mkdir(parents=True)
    xy = [[20, 25], [25, 30], [30, 30], [30+body_span, 30], [35+body_span, 25], [30+body_span, 20]]
    image = Image.new('RGB', (220, 70), 'white')
    ImageDraw.Draw(image).line([(x, 69-y) for x, y in xy], fill='black', width=6)
    image.save(directory/'input.png')
    annotation = dict(schema_version=1, role='stroke_annotation', character='一', image_size_px=[220, 70],
        source_sha256=hashlib.sha256((directory/'input.png').read_bytes()).hexdigest(),
        provenance=dict(source_kind='synthetic_fixture', note='Hand-defined analytic geometry, not calligraphy.'),
        strokes=[dict(id='s01', type='heng', variant='standard', xy_px=xy, anchors=[0, 2, 3, 5],
            width_hint_px=6., review_status='unreviewed', notes='解析夹具：主体跨度变化，头尾坐标规则独立固定。')])
    write_json(directory/'annotation.json', annotation)
    return annotation, directory/'input.png'


def generate_examples(graphics_path, output_dir, *, image_size=480):
    if type(image_size) is not int or not 128 <= image_size <= 1400:
        raise ValueError('image_size must be 128..1400')
    records = {}
    for line in Path(graphics_path).read_text(encoding='utf-8').splitlines():
        record = json.loads(line)
        if record['character'] in REFERENCE_CHARACTERS+TEST_CHARACTERS:
            records[record['character']] = record
    missing = set(REFERENCE_CHARACTERS+TEST_CHARACTERS)-records.keys()
    if missing:
        raise ValueError('demo dictionary is missing characters: '+''.join(sorted(missing)))

    def write(stage):
        references = {'heng': [], 'shu': []}
        for character in REFERENCE_CHARACTERS:
            folder = stage/'references'/f'u{ord(character):04x}'
            folder.mkdir(parents=True)
            image_path = folder/'input.png'
            transform = _render_font(records[character], image_path, image_size)
            prepared = prepare_bundle(image_path, character, folder/'annotation',
                font_record=records[character], font_transform=transform, image_kind='font_fixture')
            annotation = read_json(Path(prepared['output_dir'])/'annotation.json')
            for stroke in annotation['strokes']:
                if stroke['type'] in references:
                    references[stroke['type']].append((annotation, image_path, stroke['id']))
        templates = []
        for kind in ('heng', 'shu'):
            model = build_bundle(references[kind], stage/'templates'/kind,
                                 style_id='makemeahanzi_font_fixture', allow_unreviewed=True)
            templates.append(model['template'])
        cases = []
        for character in TEST_CHARACTERS:
            directory = Path('characters')/f'u{ord(character):04x}'
            folder = stage/directory
            folder.mkdir(parents=True)
            transform = _render_font(records[character], folder/'input.png', image_size)
            annotation = prepare_annotation(folder/'input.png', character,
                font_record=records[character], font_transform=transform, image_kind='font_fixture')
            selected_templates = _yong_models(annotation, folder/'input.png', stage/'templates'/'yong') if character == '永' else templates
            fit_bundle(annotation, folder/'input.png', selected_templates, folder/'fit')
            geometry = load_fitted_geometry(folder/'fit')
            supported = sum(s['status'] == 'candidate' for s in geometry['strokes'])
            cases.append(dict(character=character, directory=(directory/'fit').as_posix(),
                complete=geometry['complete'], fitted_count=supported,
                unsupported_count=len(geometry['strokes'])-supported))
        ref, image = _analytic_case(stage/'analytic_reference', 80)
        model = build_bundle([(ref, image, 's01')], stage/'templates'/'analytic_heng',
                             style_id='analytic_fixture', allow_unreviewed=True)['template']
        length_cases = []
        for name, span in [('short', 40), ('medium', 80), ('long', 140)]:
            directory = Path('length_transfer')/name
            annotation, image = _analytic_case(stage/directory, span)
            fit_bundle(annotation, image, [model], stage/directory/'fit')
            length_cases.append(dict(name=name, directory=(directory/'fit').as_posix(), stretch_ratio=span/80))
        summary = dict(reference_characters=list(REFERENCE_CHARACTERS+'永'), test_characters=list(TEST_CHARACTERS.replace('永', '')),
            demonstration_characters=['永'],
            independent_ground_truth=False, physical_validation=False,
            evidence='Font medians provide both initial candidates and reference geometry. Engineering fixtures only.',
            character_cases=cases, length_cases=length_cases)
        write_json(stage/'cases.json', summary)
        _index(stage/'index.html', summary)
        return dict(reference_characters=list(REFERENCE_CHARACTERS+'永'), test_characters=list(TEST_CHARACTERS.replace('永', '')),
                    physical_validation=False, independent_ground_truth=False)
    result = publish(output_dir, 'stroke_template_examples', write)
    result['report_html'] = str(Path(result['output_dir'])/'index.html')
    return result


def _index(destination, summary):
    text = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
    text += f'<title>分段笔画模板 · 离线示例</title><style>{CSS}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:16px}}.cards .card{{margin:0}}img{{width:100%;max-height:260px;object-fit:contain}}a.card{{text-decoration:none;color:inherit}}</style>'
    text += '<h1>分段笔画模板 · 离线示例</h1><p>检查一种模板如何适配不同长度，以及哪些整字笔画仍需人工处理。</p>'
    text += '<section class="card"><span class="badge warn">字体与解析几何夹具</span><p>此批用于验证软件流程。横、竖参考来自“一二三十工”；保留测试字为“土王干士”。“永”使用自身字库五笔建立初始原型，属于功能演示。字体中线同时参与候选和参考，评价不独立，不能据此认定书法质量、真实笔锋轨迹或磁响应迁移。</p><div class="toolbar"><a href="templates/heng/report.html">横模板与来源</a><a href="templates/shu/report.html">竖模板与来源</a><a href="templates/analytic_heng/report.html">解析横模板</a></div></section>'
    text += '<h2>主体伸缩，保护起收笔</h2><p>解析路径的头尾由固定坐标规则定义，主体跨度分别为 40、80、140 px。打开后勾选“整体缩放”比较；它们不是书法样本。</p><div class="cards">'
    for case in summary['length_cases']:
        text += '<a class="card" href="'+case['directory']+'/report.html"><h2>'+html.escape(case['name'])+'</h2><p>主体伸缩 × '+str(case['stretch_ratio'])+'</p><img src="'+case['directory']+'/image.png"></a>'
    text += '</div><h2>保留字符的有序 XY 候选</h2><div class="cards">'
    for case in summary['character_cases']:
        text += '<a class="card" href="'+case['directory']+'/review.html"><h2>'+html.escape(case['character'])+'</h2><span class="badge '+('' if case['complete'] else 'warn')+'">'+('完整几何候选' if case['complete'] else '部分候选')+'</span><p>'+str(case['fitted_count'])+' 笔已适配；'+str(case['unsupported_count'])+' 笔未支持</p><img src="'+case['directory']+'/image.png"></a>'
    text += '</div><p class="muted">每页均可编辑并下载标注。缺模板和受限形变会逐笔保留原因；没有时间、磁目标或 Z。</p></html>'
    Path(destination).write_text(text, encoding='utf-8')
