"""Compose a character from image-bound layout and explicitly versioned library models."""
from __future__ import annotations

import copy
import hashlib
import html
from pathlib import Path

import numpy as np

from .annotations import load_bound_image, measure_annotation
from .bundle import fit_bundle, fit_character, publish, read_json, write_json
from .catalog import _local_file, _verify
from .schema import identity, number, validate_annotation, validate_template


def _parameters(value, stroke):
    allowed = {'body_scale','width_scale','rotation_deg','offset_xy_px','span_scales'}
    if not isinstance(value,dict) or set(value)-allowed:
        raise ValueError('unknown composition parameter')
    p = dict(body_scale=1.,width_scale=1.,rotation_deg=0.,offset_xy_px=[0.,0.],span_scales={}) | value
    for key in ('body_scale','width_scale'):
        p[key] = number(p[key],key,positive=True)
        if not .5<=p[key]<=1.6:
            raise ValueError('composition scales must be within [.5, 1.6]')
    p['rotation_deg'] = number(p['rotation_deg'],'rotation')
    offset = p['offset_xy_px']
    if not isinstance(offset,list) or len(offset)!=2:
        raise ValueError('composition offset needs two pixels')
    p['offset_xy_px'] = [number(v,'offset') for v in offset]
    features = stroke.get('landmarks',[])
    names = ['to_'+f['name'] for f in features]+(['to_body_end'] if features else ['body'])
    if not isinstance(p['span_scales'],dict) or set(p['span_scales'])-set(names):
        raise ValueError('unknown composition body span')
    p['span_scales'] = {k:number(v,'span scale',positive=True) for k,v in p['span_scales'].items()}
    if any(not .5<=v<=1.6 for v in p['span_scales'].values()):
        raise ValueError('composition span scales must be within [.5, 1.6]')
    return p


def _deform(stroke, p):
    xy = np.array(stroke['xy_px']); a = stroke['anchors']; features = stroke.get('landmarks',[])
    knots = [a[1],*[f['index'] for f in features],a[2]]
    names = ['to_'+f['name'] for f in features]+(['to_body_end'] if features else ['body'])
    result = xy.copy(); shift = np.zeros(2)
    for first,last,name in zip(knots[:-1],knots[1:],names):
        part = xy[first:last+1]; delta = part[-1]-part[0]; span = np.linalg.norm(delta)
        if span<=1e-8:
            raise ValueError('composition body span is zero')
        axis = delta/span; factor = p['body_scale']*p['span_scales'].get(name,1.)
        moved = part+shift+(factor-1)*((part-part[0])@axis)[:,None]*axis
        result[first:last+1] = moved; shift = moved[-1]-part[-1]
    result[a[2]+1:] += shift
    angle = np.deg2rad(p['rotation_deg']); c,s = np.cos(angle),np.sin(angle)
    pivot = result[a[1]].copy()
    return ((result-pivot)@np.array([[c,s],[-s,c]])+pivot+p['offset_xy_px']).tolist()


def _template_snapshot(directory, expected):
    directory = Path(directory).resolve(); manifest = read_json(directory/'manifest.json')
    if manifest.get('role')!='stroke_template_bundle':
        raise ValueError('composition requires a published template bundle')
    _verify(directory,manifest)
    if not {'template.json','report.html'} <= manifest['files'].keys():
        raise ValueError('composition template and report must both be manifested')
    model = validate_template(read_json(directory/'template.json'))
    if model['template_id']!=expected or manifest.get('template_id')!=expected:
        raise ValueError('composition template version mismatch')
    frozen = {name:_local_file(directory,name).read_bytes() for name in manifest['files']}
    if any(hashlib.sha256(raw).hexdigest()!=manifest['files'][name] for name,raw in frozen.items()):
        raise ValueError('composition template source changed during snapshot')
    return model,manifest,frozen


def compose_character(recipe, base_dir, output_dir):
    if (not isinstance(recipe,dict) or recipe.get('schema_version')!=1 or
            recipe.get('role')!='template_character_recipe'):
        raise ValueError('unsupported character composition recipe')
    base = Path(base_dir); layout = recipe['layout']
    constraint = recipe.get('image_constraint')
    if constraint is not None:
        if not isinstance(constraint,dict) or set(constraint) != {'max_outside_fraction'}:
            raise ValueError('image constraint needs max_outside_fraction')
        fraction = number(constraint['max_outside_fraction'],'max outside fraction')
        if not 0<=fraction<=1:
            raise ValueError('max outside fraction must be within [0, 1]')
        constraint = dict(max_outside_fraction=fraction)
    original, prepared = load_bound_image(read_json(base/layout['annotation']),base/layout['image'])
    if (original['character']!=recipe.get('character') or original['annotation_id']!=layout.get('annotation_id') or
            original['source_sha256']!=layout.get('source_sha256')):
        raise ValueError('composition layout version mismatch')
    entries = recipe.get('strokes')
    if not isinstance(entries,list) or [e.get('stroke_id') for e in entries]!=[s['id'] for s in original['strokes']]:
        raise ValueError('composition needs one ordered template per layout stroke')
    measured = measure_annotation(original,prepared)
    annotation = copy.deepcopy(original); snapshots = []; bindings = []
    saved = copy.deepcopy(recipe)
    saved['layout'] = dict(layout,annotation='layout/annotation.json',image='layout/source_image.bin')
    for stroke, entry, recorded in zip(annotation['strokes'],entries,saved['strokes']):
        model,manifest,files = _template_snapshot(base/entry['template'],entry['template_id'])
        if stroke['type']!=model['type']:
            raise ValueError('composition template type differs from layout stroke '+stroke['id'])
        p = _parameters(entry.get('parameters',{}),stroke)
        width = measured[stroke['id']]['width_px']
        if width is None:
            raise ValueError('composition needs a nominal layout width for '+stroke['id'])
        stroke.update(variant=model['variant'],xy_px=_deform(stroke,p),width_hint_px=width*p['width_scale'],
                      review_status='unreviewed',path_mode='template')
        name = model.get('guide_trace',model.get('teaching',{})).get('name',model['type'])
        stroke['display_name'] = name
        binding = dict(stroke_id=stroke['id'],template_id=model['template_id'],type=model['type'],
                       variant=model['variant'],name=name,parameters=p)
        bindings.append(binding); snapshots.append((model,manifest,files))
        recorded.update(template='.template_sources/'+stroke['id'],parameters=p)
    semantic = dict(character=original['character'],layout_annotation_id=original['annotation_id'],
                    layout_source_sha256=original['source_sha256'],strokes=bindings)
    if constraint is not None:
        semantic['image_constraint'] = constraint
    recipe_id = identity(semantic,'recipe_id')
    annotation['provenance'] = dict(source_kind='template_composition',
        image_kind='teaching_reconstruction' if any(m['evidence']['level']=='teaching_rule_candidate' for m,_,_ in snapshots)
            else original['provenance'].get('image_kind','unspecified'),
        original_provenance=original['provenance'],layout_annotation_id=original['annotation_id'],
        layout_source_kind=original['provenance']['source_kind'],recipe_id=recipe_id,
        composition_strokes=bindings,physical_validation=False)
    if constraint is not None:
        annotation['provenance']['image_constraint'] = constraint
    annotation = validate_annotation(annotation)
    models = list({m['template_id']:m for m,_,_ in snapshots}.values())
    geometry = fit_character(annotation,prepared,models)
    rejected = [s['id']+': '+s.get('reason','generated path outside layout image') for s in geometry['strokes']
                if s['status']!='candidate' or 'generated_path_outside_image' in s.get('review_flags',[])]
    if rejected:
        raise ValueError('composition rejected: '+'; '.join(rejected))
    if constraint is not None:
        rejected = [s['id'] for s in geometry['strokes']
            if s['image_consistency']['outside_fraction'] > constraint['max_outside_fraction']+1e-12
            or (constraint['max_outside_fraction']==0 and s['image_consistency']['outside_vertex_count'])]
        if rejected:
            raise ValueError('composition outside reference ink: '+', '.join(rejected))
    def write(stage):
        (stage/'layout').mkdir()
        write_json(stage/'layout/annotation.json',original)
        (stage/'layout/source_image.bin').write_bytes(prepared['source_bytes'])
        write_json(stage/'recipe.json',saved)
        write_json(stage/'composition.json',dict(semantic,recipe_id=recipe_id,geometry_id=geometry['geometry_id'],
            layout_role='layout_prior_not_generated_ink_ground_truth',physical_validation=False))
        for binding,(_,manifest,files) in zip(bindings,snapshots):
            # Character reference snapshots must not participate in library version selection.
            target = stage/'.template_sources'/binding['stroke_id']; target.mkdir(parents=True)
            for name,raw in files.items():
                path = target/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(raw)
            write_json(target/'manifest.json',manifest)
        fit_bundle(annotation,stage/'layout/source_image.bin',models,stage/'fit')
        _write_report(stage,geometry,bindings)
        return dict(character=original['character'],recipe_id=recipe_id,geometry_id=geometry['geometry_id'],
                    complete=True,stroke_count=len(bindings),physical_validation=False)
    result = publish(output_dir,'template_character_composition',write)
    result['review_html'] = str(Path(result['output_dir'])/'fit/review.html')
    return result


def _write_report(stage, geometry, bindings):
    w,h = geometry['image_size_px']; colors = ['#2766c4','#c07817','#258565','#ae4f85','#6958b5']
    paths = ''.join('<polyline fill="none" stroke="'+colors[i%5]+'" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" points="'+
        ' '.join(f'{x:.6f},{h-1-y:.6f}' for x,y in s['xy_px'])+'"/>' for i,s in enumerate(geometry['strokes']))
    (stage/'preview.svg').write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-.5 -.5 {w} {h}">'+paths+'</svg>',encoding='utf-8')
    rows = ''.join('<tr><td>'+str(i+1)+'. '+html.escape(b['name'])+'</td><td><a class="templateSource" href=".template_sources/'+b['stroke_id']+'/report.html">'+
        html.escape(b['type']+' / '+b['variant'])+'</a><br><code>'+b['template_id']+'</code></td><td>'+
        f"{(1-s['image_consistency']['outside_fraction'])*100:.1f}%"+
        ('<br>有轮廓外点' if s['image_consistency']['outside_vertex_count'] else '')+'</td></tr>' for i,(b,s) in enumerate(zip(bindings,geometry['strokes'])))
    character = html.escape(geometry['character'])
    (stage/'report.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'+
        '<title>'+character+' · 笔画合成配方</title><style>body{font-family:system-ui,sans-serif;max-width:960px;margin:auto;padding:22px;color:#25364a;background:#f4f6f9}p{line-height:1.7}img{width:100%;max-height:500px;background:white;border:1px solid #dce3ec}table{width:100%;border-collapse:collapse;background:white}td,th{padding:12px;border:1px solid #dce3ec;text-align:left}code{font-size:11px;overflow-wrap:anywhere}a{color:#245db9}</style><h1>'+character+' · 笔画合成配方</h1>'+
        '<p>字形参考提供位置、笔顺和布局；下图'+str(len(bindings))+'笔路径由所选笔画模板适配生成。当前结果是教学写法几何候选。</p>'+
        '<p><a href="fit/review.html">打开整字 XY，查看或局部修正 →</a>　<a href="recipe.json" download>下载合成配方</a>　<a href="fit/paths.csv" download>下载整字 XY</a></p>'+
        '<img src="preview.svg" alt="笔画模板合成的整字路径"><h2>每笔实际采用的模板</h2><table><tr><th>笔顺／写法</th><th>来源与模板版本</th><th>整图轮廓内行程<br>1 px 容差</th></tr>'+rows+'</table>'+
        '<p>轮廓比例按路径弧长均匀采样计算，使用整图墨迹，不区分交叉位置属于哪一笔。它只检查 XY 与布局参考的叠加，不能评价书法质量或预测墨迹外形。</p>'+
        '<p>配方可调整每笔的主体长度、分段长度、宽度尺度、旋转和位移；尺寸调整后重新运行 compose 生成新版本。合成包保存布局与模板快照，可以离线重建。</p>'+
        '<p>布局原图仅用于定位和对照。模板尚未对应真实时间、Z 高度或磁响应。</p></html>',encoding='utf-8')
