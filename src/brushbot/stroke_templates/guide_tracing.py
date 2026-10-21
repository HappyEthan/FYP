"""Ordered guide pixel tracking from explicit, image-bound manual seeds."""
from __future__ import annotations

import copy
import hashlib
import heapq
import html
from io import BytesIO
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from .bundle import publish, write_json
from .schema import anchors, identifier, landmarks, number, points, source_hash


def trace_source(spec, raw, article_url):
    spec = copy.deepcopy(spec)
    for key in ('id', 'type', 'variant'):
        identifier(spec.get(key), 'guide '+key)
    source_hash(spec['source'].get('sha256'))
    if hashlib.sha256(raw).hexdigest() != spec['source']['sha256']:
        raise ValueError('guide source checksum mismatch: '+spec['id'])
    with Image.open(BytesIO(raw)) as image:
        if image.width*image.height>40_000_000:
            raise ValueError('guide image exceeds 40 million pixels')
        grey = np.asarray(image.convert('L'))
    crop = spec.get('box')
    if not isinstance(crop, list) or len(crop)!=4 or any(type(v) is not int for v in crop):
        raise ValueError('guide ROI needs four integer pixel boundaries')
    x0, y0, x1, y1 = crop
    if not 0<=x0<x1<=grey.shape[1] or not 0<=y0<y1<=grey.shape[0]:
        raise ValueError('guide ROI outside source image')
    seeds = points(spec.get('waypoints'))
    if np.any(seeds<[x0,y0]) or np.any(seeds>[x1-1,y1-1]):
        raise ValueError('guide waypoint outside ROI')
    boundary = anchors([0, spec.get('body_start'), spec.get('body_end'), len(seeds)-1], len(seeds))
    features = landmarks(spec.get('landmarks'), boundary)
    roi = grey[y0:y1, x0:x1]
    mode = spec.get('guide_mode', 'ink_white')
    if mode == 'ink_white':
        closed = Image.fromarray((roi<100).astype('uint8')*255).filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.MinFilter(9))
        inside = np.asarray(closed)>0
        guide = (roi>110)&inside
    elif mode == 'outline_white':
        inside = np.ones(roi.shape, bool)
        guide = roi>160
        number(spec.get('width_hint_px'), 'outline reference width', positive=True)
    else:
        raise ValueError('unsupported guide mode')
    candidates = np.column_stack(np.nonzero(guide))[:, ::-1]+[x0,y0]
    if not len(candidates):
        raise ValueError('no visible guide pixels in ROI')
    snapped = []
    for point in seeds:
        distance = np.linalg.norm(candidates-point, axis=1); best = int(np.argmin(distance))
        if distance[best]>9:
            raise ValueError(f'{spec["id"]}: no guide pixel within 9 px of {point.tolist()}')
        snapped.append(tuple(map(int, candidates[best])))
    if any(a==b for a,b in zip(snapped[:-1],snapped[1:])):
        raise ValueError('adjacent guide seeds snap to the same pixel')

    def segment(start, end):
        a, b = np.array(start, float), np.array(end, float); delta = b-a; length2 = delta@delta
        queue = [(math.dist(start,end), 0., start)]; cost = {start:0.}; parent = {}
        while queue:
            _, value, point = heapq.heappop(queue)
            if value != cost[point]:
                continue
            if point == end:
                result = [point]
                while point != start:
                    point = parent[point]; result.append(point)
                return result[::-1]
            for dx,dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
                q = (point[0]+dx, point[1]+dy)
                if not x0<=q[0]<x1 or not y0<=q[1]<y1:
                    continue
                progress = np.clip((np.array(q)-a)@delta/length2, 0., 1.)
                if np.linalg.norm(np.array(q)-(a+progress*delta))>10:
                    continue
                iy, ix = q[1]-y0, q[0]-x0
                penalty = 1. if guide[iy,ix] else 30. if inside[iy,ix] else 200.
                candidate = value+math.hypot(dx,dy)*penalty
                if candidate<cost.get(q, math.inf):
                    cost[q] = candidate; parent[q] = point
                    heapq.heappush(queue,(candidate+math.dist(q,end),candidate,q))
        raise ValueError('unconnected guide segment')

    pixels, indices = [], [0]
    for a,b in zip(snapped[:-1], snapped[1:]):
        chunk = segment(a,b); pixels.extend(chunk if not pixels else chunk[1:]); indices.append(len(pixels)-1)
    pixels = points(pixels)
    xy = pixels.copy(); xy[:,1] = grey.shape[0]-1-pixels[:,1]
    result = dict(id=spec['id'], type=spec['type'], variant=spec['variant'], name=spec['name'],
        box=crop, waypoints=seeds.tolist(), ordered_waypoints_image_px=snapped,
        source_points_image_px=pixels.tolist(), xy_px=xy.tolist(), image_size_px=[grey.shape[1],grey.shape[0]],
        anchors=[indices[i] for i in boundary],
        landmarks=[dict(name=f['name'],index=indices[f['index']]) for f in features],
        source_sha256=spec['source']['sha256'], source_url=spec['source']['url'], article_url=article_url,
        review_status='unreviewed', role='teaching_guide_trace_candidate_not_measured_motion',
        method='manually_ordered_waypoints_with_white_guide_pixel_tracking', guide_mode=mode,
        stage_boundary_basis='manual_interpretation_not_measured_phase', writing_hint=spec.get('writing_hint',''),
        tracking_settings=dict(white_threshold=110 if mode=='ink_white' else 160, dark_threshold=100,
            close_filter_size_px=9, waypoint_snap_limit_px=9, segment_corridor_px=10))
    for key in ('width_hint_px', 'width_hint_basis'):
        if key in spec:
            result[key] = spec[key]
    return result


def trace_guides(config, source_dir, output_dir):
    if not isinstance(config,dict) or config.get('schema_version')!=1 or config.get('role')!='teaching_guide_trace_specs':
        raise ValueError('unsupported guide tracing specification')
    specs = config.get('strokes')
    if not isinstance(specs,list) or not 1<=len(specs)<=64:
        raise ValueError('provide 1..64 guide specifications')
    prepared, ids, pairs = [], set(), set()
    for spec in specs:
        filename = spec['source']['filename']
        if not isinstance(filename,str) or Path(filename).name!=filename or filename in ('.','..'):
            raise ValueError('guide source filename must be local')
        source = Path(source_dir)/filename
        if source.is_symlink():
            raise ValueError('guide source must be a regular local file')
        raw = source.read_bytes(); trace = trace_source(spec,raw,config['article_url'])
        pair = (trace['type'],trace['variant'])
        if trace['id'] in ids or pair in pairs:
            raise ValueError('duplicate guide specification')
        ids.add(trace['id']); pairs.add(pair); prepared.append((trace,raw))
    def write(stage):
        entries = []
        write_json(stage/'trace_specs.json',config)
        for trace,raw in prepared:
            sid = trace['id']; source_name = sid+'_source.jpg'; trace_name = sid+'_trace.json'
            (stage/source_name).write_bytes(raw); write_json(stage/trace_name,trace)
            entries.append(dict(id=sid,type=trace['type'],variant=trace['variant'],name=trace['name'],
                source_file=source_name,trace_file=trace_name))
        links = ''.join('<li>'+html.escape(e['name'])+' · <a href="'+e['source_file']+'">原图</a> · '
            '<a href="'+e['trace_file']+'">有序追踪 JSON</a></li>' for e in entries)
        (stage/'report.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><title>教学引导线追踪</title>'
            '<h1>教学引导线追踪</h1><p>有序人工种子引导的白线像素追踪，阶段与转折待人工检查。</p><ul>'+
            links+'</ul></html>',encoding='utf-8')
        return dict(path_count=len(prepared),strokes=entries,review_status='unreviewed',physical_validation=False)
    return publish(output_dir,'teaching_guide_review',write)
