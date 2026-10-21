"""Freeze a single-stroke bitmap as an inspectable, ordered geometric reference.

Skeletons describe image geometry, not measured brush/TCP trajectories.
Zhang-Suen thinning is implemented with NumPy to keep existing dependencies.
"""
from __future__ import annotations

import csv
import hashlib
import heapq
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from .geometry import clean_path
from brushbot.image_geometry import (
    otsu_threshold as _otsu, connected_components as _components,
    thin_mask as _thin, pixel_graph as _graph, simplify_path,
)


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    allow_nan=False)+'\n', encoding='utf-8')


def _pair(value, name):
    pair = np.asarray(value, float)
    if pair.shape != (2,) or not np.isfinite(pair).all():
        raise ValueError(f'{name} must be two finite numbers')
    return pair


def pixels_to_mm(points, transform):
    local = (np.asarray(points, float)-transform['origin_px'])*[1., -1.]
    angle = np.deg2rad(transform['rotation_deg'])
    rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    return local*transform['mm_per_pixel'] @ rotation.T + transform['origin_mm']


def _snap(point, nodes):
    point = _pair(point, 'endpoint pixel')
    pixels = np.asarray(nodes)
    distances = np.hypot(*(pixels[:, ::-1]-point).T)
    best = int(np.argmin(distances))
    if distances[best] > 5.:
        raise ValueError('endpoint is more than 5 pixels from the skeleton; inspect the preview')
    return tuple(pixels[best])


def _route(graph, start, end):
    queue, distance, parent = [(0., start)], {start: 0.}, {}
    while queue:
        cost, node = heapq.heappop(queue)
        if cost > distance[node]:
            continue
        if node == end:
            path = [end]
            while path[-1] != start:
                path.append(parent[path[-1]])
            return path[::-1]
        for other, step in graph[node]:
            new = cost+step
            if new < distance.get(other, np.inf):
                distance[other] = new
                parent[other] = node
                heapq.heappush(queue, (new, other))
    raise ValueError('selected endpoints are not connected')


def _preview(image, mask, skeleton, path_px, metadata, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(14, 4.8))
    axes[0].imshow(image)
    axes[0].set_title('1  Input image')
    axes[1].imshow(mask, cmap='gray_r', vmin=0, vmax=1)
    yy, xx = np.nonzero(skeleton)
    axes[1].scatter(xx, yy, s=2, color='#2563eb', label='skeleton')
    for points, color, label in [(metadata['endpoints_px'], '#059669', 'endpoints'),
                                  (metadata['junctions_px'], '#dc2626', 'branches')]:
        if points:
            pts = np.asarray(points)
            axes[1].scatter(*pts.T, color=color, s=22, label=label)
    axes[1].set_title('2  Segmentation and skeleton')
    if len(xx):
        axes[1].legend(fontsize=8)
    axes[2].imshow(image)
    if path_px is not None:
        axes[2].plot(*path_px.T, color='#d97706', linewidth=1.8)
        axes[2].scatter(*path_px[0], color='#059669', label='start', zorder=4)
        axes[2].scatter(*path_px[-1], color='#dc2626', marker='x', label='end', zorder=4)
        axes[2].legend(fontsize=8)
    axes[2].set_title('3  Selected ordered reference' if path_px is not None else '3  Annotation required')
    for ax in axes:
        ax.set(xlabel='Image x (px)', ylabel='Image y (px)')
    fig.suptitle('Reference extraction | '+metadata['status']+' | inspect before evaluation')
    fig.tight_layout()
    fig.savefig(output, dpi=150)
    plt.close(fig)


def extract_reference(image_path, output_dir, *, mm_per_pixel, origin_px=None,
                      origin_mm=(0., 0.), rotation_deg=0., threshold=None, invert=False,
                      min_component_pixels=8, component_index=None, start_px=None,
                      end_px=None, reverse=False, source_url=None, simplify_px=.75):
    """Write a new reference bundle, or diagnostic-only bundle for ambiguity.

    Explicit anchors choose a shortest skeleton route; all omitted pixels are
    recorded. Otherwise only an unbranched open curve is accepted, with a
    clearly labelled left-to-right / top-to-bottom direction assumption.
    """
    output = Path(output_dir)
    if output.exists():
        raise FileExistsError(f'refusing to replace output: {output}')
    if (isinstance(mm_per_pixel, bool) or not np.isfinite(mm_per_pixel) or mm_per_pixel <= 0
            or not np.isfinite(rotation_deg)):
        raise ValueError('image scale must be positive and rotation finite')
    if type(min_component_pixels) is not int or min_component_pixels < 1:
        raise ValueError('min_component_pixels must be a positive integer')
    if threshold is not None and (type(threshold) is not int or not 0 <= threshold <= 254):
        raise ValueError('threshold must be an integer from 0 to 254')
    if (start_px is None) != (end_px is None):
        raise ValueError('specify both start_px and end_px')
    if isinstance(simplify_px, bool) or not np.isfinite(simplify_px) or simplify_px < 0:
        raise ValueError('simplify_px must be finite and nonnegative')
    raw = Path(image_path).read_bytes()
    with Image.open(io.BytesIO(raw)) as source:
        if source.width*source.height > 2_000_000 or min(source.size) < 3:
            raise ValueError('use a cropped image of at most 2000000 pixels and at least 3x3')
        if getattr(source, 'n_frames', 1) != 1:
            raise ValueError('select one still image from animated/multipage input')
        rgba = ImageOps.exif_transpose(source).convert('RGBA')
        image = Image.alpha_composite(Image.new('RGBA', rgba.size, 'white'), rgba).convert('RGB')
    gray = np.asarray(image.convert('L'))
    if gray.min() == gray.max():
        raise ValueError('constant image has no foreground/background contrast')
    work = 255-gray if invert else gray
    used_threshold = _otsu(work) if threshold is None else threshold
    components = _components(work <= used_threshold)
    removed = sum(len(p) for p in components if len(p) < min_component_pixels)
    components = [p for p in components if len(p) >= min_component_pixels]
    if not components:
        raise ValueError('no foreground stroke after small-component removal')
    if component_index is not None and (type(component_index) is not int
                                        or not 0 <= component_index < len(components)):
        raise ValueError('component_index is outside the retained component list')
    transform = dict(mm_per_pixel=float(mm_per_pixel), rotation_deg=float(rotation_deg),
                     origin_px=_pair(((image.width-1)/2, (image.height-1)/2)
                                     if origin_px is None else origin_px, 'origin_px').tolist(),
                     origin_mm=_pair(origin_mm, 'origin_mm').tolist())
    component_info = [dict(index=i, pixels=len(p), bbox_px=[int(p[:, 1].min()), int(p[:, 0].min()),
                                                          int(p[:, 1].max()), int(p[:, 0].max())])
                      for i, p in enumerate(components)]
    chosen = components if component_index is None else [components[component_index]]
    mask = np.zeros_like(work, dtype=bool)
    for pixels in chosen:
        mask[tuple(pixels.T)] = True
    skeleton = _thin(mask)
    if skeleton.sum() > 20000:
        raise ValueError('skeleton has more than 20000 pixels; crop or downsample the input')
    graph = _graph(skeleton)
    endpoints = [node for node, edges in graph.items() if len(edges) == 1]
    junctions = [node for node, edges in graph.items() if len(edges) > 2]
    metadata = dict(schema_version=1, status='needs_review',
                    role='image_geometric_reference_not_measured_brush_trajectory',
                    algorithm='otsu_or_manual_threshold_8connected_components_zhang_suen_rdp_v1',
                    simplify_tolerance_px=float(simplify_px), raw_route_pixels=0,
                    source_image_path=str(Path(image_path).resolve()), source_url=source_url,
                    source_file_sha256=hashlib.sha256(raw).hexdigest(),
                    image_size_px=list(image.size), coordinate_frame='paper', transform=transform,
                    threshold=used_threshold, threshold_mode='otsu' if threshold is None else 'manual',
                    invert=bool(invert), min_component_pixels=min_component_pixels,
                    removed_small_component_pixels=removed, components=component_info,
                    selected_component_index=component_index,
                    ignored_component_pixels=sum(len(p) for p in components)-int(mask.sum()),
                    skeleton_pixels=len(graph), endpoints_px=[list(p[::-1]) for p in endpoints],
                    junctions_px=[list(p[::-1]) for p in junctions], reverse=bool(reverse),
                    requested_start_px=None, requested_end_px=None, direction_source=None,
                    omitted_skeleton_pixels=0, files={})
    path_px = raw_path_px = None
    if len(components) != 1 and component_index is None:
        metadata['reason'] = 'multiple components; crop a single stroke or explicitly select component_index'
    elif len(graph) < 2:
        metadata['reason'] = 'skeleton has fewer than two pixels'
    elif start_px is None and (len(endpoints) != 2 or junctions):
        metadata['reason'] = 'branched/closed skeleton; inspect preview and annotate both start_px and end_px'
    else:
        if start_px is not None:
            start, end = _snap(start_px, list(graph)), _snap(end_px, list(graph))
            metadata.update(requested_start_px=_pair(start_px, 'start_px').tolist(),
                            requested_end_px=_pair(end_px, 'end_px').tolist(),
                            direction_source='explicit_endpoints')
        else:
            dy, dx = np.abs(np.subtract(*endpoints))
            start, end = sorted(endpoints, key=(lambda p: (p[1], p[0])) if dx >= dy else (lambda p: p))
            metadata['direction_source'] = 'geometric_heuristic_requires_review'
        if start == end:
            raise ValueError('start and end snap to the same skeleton point')
        route = _route(graph, start, end)
        if reverse:
            route.reverse()
        raw_path_px = np.asarray(route, float)[:, ::-1]
        path_px = simplify_path(raw_path_px, simplify_px)
        clean_path(pixels_to_mm(path_px, transform))
        metadata.update(status='ready', path_selection='explicit_endpoint_shortest_path' if start_px is not None else 'unbranched_path',
                        omitted_skeleton_pixels=len(graph)-len(route),
                        raw_route_pixels=len(route), reference_vertices=len(path_px),
                        selected_start_px=path_px[0].tolist(), selected_end_px=path_px[-1].tolist())
    output.mkdir(parents=True, exist_ok=False)
    (output/'source_image.bin').write_bytes(raw)
    image.save(output/'image.png')
    Image.fromarray(mask.astype(np.uint8)*255).save(output/'mask.png')
    Image.fromarray(skeleton.astype(np.uint8)*255).save(output/'skeleton.png')
    if path_px is not None:
        for filename, pixels in [('reference.csv', path_px), ('skeleton_path.csv', raw_path_px)]:
            xy = pixels_to_mm(pixels, transform)
            with (output/filename).open('x', newline='', encoding='utf-8') as stream:
                writer = csv.writer(stream)
                writer.writerow(['x_px', 'y_px', 'x_mm', 'y_mm'])
                writer.writerows(np.column_stack([pixels, xy]))
    _preview(image, mask, skeleton, path_px, metadata, output/'reference_preview.png')
    for name in ['source_image.bin', 'image.png', 'mask.png', 'skeleton.png', 'reference.csv',
                 'skeleton_path.csv', 'reference_preview.png']:
        if (output/name).exists():
            metadata['files'][name] = sha256_file(output/name)
    metadata['image_sha256'] = metadata['files']['image.png']
    write_json(output/'reference.json', metadata)
    return metadata


def load_reference(directory):
    """Load a frozen ready bundle and detect missing/changed reference inputs."""
    directory = Path(directory)
    manifest_bytes = (directory/'reference.json').read_bytes()
    metadata = json.loads(manifest_bytes)
    if metadata.get('schema_version') != 1 or metadata.get('status') != 'ready':
        raise ValueError('reference is not ready; inspect the needs_review diagnostics')
    required = {'source_image.bin', 'image.png', 'mask.png', 'skeleton.png', 'reference.csv',
                'skeleton_path.csv', 'reference_preview.png'}
    if set(metadata.get('files', {})) != required:
        raise ValueError('reference hash manifest is incomplete')
    snapshots = {'reference.json': manifest_bytes}
    for name in required:
        path = directory/name
        payload = path.read_bytes() if path.is_file() else b''
        if not payload or hashlib.sha256(payload).hexdigest() != metadata['files'][name]:
            raise ValueError(f'reference input changed or hash mismatch: {name}')
        snapshots[name] = payload
    if (metadata.get('source_file_sha256') != metadata['files']['source_image.bin']
            or metadata.get('image_sha256') != metadata['files']['image.png']):
        raise ValueError('source/image hash metadata contradicts the frozen files')
    transform = metadata.get('transform')
    if not isinstance(transform, dict) or set(transform) != {'mm_per_pixel', 'rotation_deg', 'origin_px', 'origin_mm'}:
        raise ValueError('invalid reference coordinate transform')
    scalar = transform['mm_per_pixel']
    if (not isinstance(scalar, (int, float)) or isinstance(scalar, bool)
            or not np.isfinite(scalar) or scalar <= 0 or not np.isfinite(transform['rotation_deg'])):
        raise ValueError('reference scale must be positive and rotation finite')
    _pair(transform['origin_px'], 'reference origin_px')
    _pair(transform['origin_mm'], 'reference origin_mm')
    data = np.atleast_1d(np.genfromtxt(io.BytesIO(snapshots['reference.csv']), delimiter=',', names=True))
    if data.dtype.names != ('x_px', 'y_px', 'x_mm', 'y_mm'):
        raise ValueError('reference CSV must contain x_px,y_px,x_mm,y_mm')
    xy = clean_path(np.column_stack([data['x_mm'], data['y_mm']]))
    pixel_xy = np.column_stack([data['x_px'], data['y_px']])
    if (not np.isfinite(pixel_xy).all() or len(pixel_xy) != len(xy)
            or not np.allclose(xy, pixels_to_mm(pixel_xy, transform), atol=1e-7, rtol=1e-10)):
        raise ValueError('reference pixel coordinates contradict transform or stored millimetres')
    with Image.open(io.BytesIO(snapshots['image.png'])) as image:
        if metadata.get('image_size_px') != list(image.size):
            raise ValueError('reference image_size_px contradicts frozen image')
        if (np.any(pixel_xy < 0) or np.any(pixel_xy[:, 0] > image.width-1)
                or np.any(pixel_xy[:, 1] > image.height-1)):
            raise ValueError('reference pixels outside image')
        image_array = np.array(image.convert('RGB'))
    return dict(metadata=metadata, xy_mm=xy, image=image_array,
                snapshots=snapshots, directory=directory,
                manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest())
