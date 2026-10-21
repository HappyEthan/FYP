"""Whole-character XY geometry, with no invented motion or magnetic targets."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from brushbot.image_geometry import simplify_path
from .processing import finite_number, finite_pair, prepare_image, processed_to_original
from .topology import cycle_path_ids, trace_skeleton


def original_to_xy(points, transform):
    local = (np.asarray(points, float)-transform['origin_px'])*[1., -1.]
    angle = np.deg2rad(transform['rotation_deg'])
    rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    with np.errstate(over='ignore', invalid='ignore'):
        xy = local*transform['scale'] @ rotation.T+transform['origin_xy']
    if not np.isfinite(xy).all():
        raise ValueError('coordinate transform produced nonfinite XY')
    return xy


def geometry_identity(geometry):
    """IDs depend on geometry and processing, not the file's location or a URL."""
    identity = {key: value for key, value in geometry.items()
                if key not in {'geometry_id', 'source_path', 'source_url'}}
    payload = json.dumps(identity, sort_keys=True, ensure_ascii=False, allow_nan=False).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def analyze_character(image_path, *, mm_per_pixel=None, image_width_mm=None, origin_px=None,
                      origin_xy=(0., 0.), rotation_deg=0., threshold=None, adaptive=False,
                      adaptive_window=31, adaptive_offset=10, invert=False, min_component_pixels=8,
                      simplify_px=.75, max_side_px=1400, crop=None, source_url=None):
    if mm_per_pixel is not None and image_width_mm is not None:
        raise ValueError('choose either mm_per_pixel or image_width_mm')
    scale = None if mm_per_pixel is None else finite_number(mm_per_pixel, 'mm_per_pixel', positive=True)
    width_mm = None if image_width_mm is None else finite_number(image_width_mm, 'image_width_mm', positive=True)
    angle = finite_number(rotation_deg, 'rotation_deg')
    tolerance = finite_number(simplify_px, 'simplify_px')
    if tolerance < 0:
        raise ValueError('simplify_px must be nonnegative')
    origin_xy = finite_pair(origin_xy, 'origin_xy').tolist()
    if source_url is not None and not isinstance(source_url, str):
        raise ValueError('source_url must be text')
    prepared = prepare_image(image_path, threshold=threshold, adaptive=adaptive,
        adaptive_window=adaptive_window, adaptive_offset=adaptive_offset, invert=invert,
        min_component_pixels=min_component_pixels, max_side_px=max_side_px, crop=crop)
    processing = prepared['preprocessing']
    width, height = processing['exif_image_size_px']
    if width_mm is not None:
        scale = width_mm/width
    units = 'px' if scale is None else 'mm'
    transform = dict(scale=1. if scale is None else scale,
                     origin_px=finite_pair(((width-1)/2, (height-1)/2) if origin_px is None else origin_px,
                                           'origin_px').tolist(),
                     origin_xy=origin_xy, rotation_deg=angle)
    traced = trace_skeleton(prepared['skeleton'])
    nodes = []
    for node in traced['nodes']:
        pixel = np.asarray(node['representative_yx'][::-1], float)
        original = processed_to_original(pixel, processing)
        nodes.append(dict(id=node['id'], kind=node['kind'], component_id=node['component_id'],
            processed_pixel=pixel.tolist(), original_pixel=original.tolist(),
            xy=original_to_xy(original, transform).tolist(),
            region_pixels=[p[::-1] for p in node['region_pixels']],
            ink_component_index=int(prepared['labels'][tuple(node['representative_yx'])])))
    paths, raw_paths = [], {}
    cyclic_paths = cycle_path_ids(traced['paths'])
    for path in traced['paths']:
        raw = path['pixels_yx'][:, ::-1].astype(float)
        in_cycle = path['id'] in cyclic_paths
        simplified = raw.copy() if in_cycle else simplify_path(raw, tolerance)
        topological_loop = path['start_node_id'] == path['end_node_id']
        original = processed_to_original(simplified, processing)
        xy = original_to_xy(original, transform)
        arc = np.r_[0., np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]
        if not np.isfinite(arc).all() or arc[-1] <= 0:
            raise ValueError('extracted path has invalid length')
        paths.append(dict(id=path['id'], component_id=path['component_id'],
            start_node_id=path['start_node_id'], end_node_id=path['end_node_id'],
            closed=path['closed'], topological_loop=topological_loop, in_graph_cycle=in_cycle,
            ink_component_index=int(prepared['labels'][tuple(path['pixels_yx'][0])]),
            processed_pixel_xy=simplified.tolist(), original_pixel_xy=original.tolist(),
            xy=xy.tolist(), s=(arc/arc[-1]).tolist(), arc_length=arc.tolist(),
            length=float(arc[-1]), raw_point_count=len(raw)))
        raw_paths[path['id']] = raw
    junctions = sum(n['kind'] == 'junction' for n in nodes)
    isolated = sum(n['kind'] == 'isolated' for n in nodes)
    loops = sum(p['topological_loop'] for p in paths)
    cycle_rank = traced['coverage']['total_edges']-traced['skeleton_pixels']+traced['component_count']
    flags = []
    if junctions:
        flags.append('junctions_require_stroke_resolution')
    if isolated:
        flags.append('point_features_require_process_definition')
    if cycle_rank:
        flags.append('loop_direction_is_not_inferred')
    if processing['removed_component_pixels']:
        flags.append('small_components_removed')
    if processing['point_fallback_components']:
        flags.append('thinning_empty_components_retained_as_points')
    if processing['foreground_fraction'] > .85:
        flags.append('foreground_dominant_check_inversion_or_threshold')
    for component in processing['ink_components']:
        box = component['bbox_px']
        if max(box[2]-box[0], box[3]-box[1]) > 8:
            selected = [n for n in nodes if n['ink_component_index'] == component['index']]
            if selected and all(n['kind'] == 'isolated' for n in selected):
                flags.append('elongated_component_collapsed_check_source')
                break
    geometry = dict(schema_version=1, role='character_xy_geometry',
        algorithm_version='skeleton_region_graph_v1', units=units,
        coordinate_frame='image_cartesian' if units == 'px' else 'paper',
        source_path=str(Path(image_path).resolve()), source_url=source_url,
        source_sha256=prepared['source_sha256'], preprocessing=processing, transform=transform,
        simplify_tolerance_px=tolerance, path_order='deterministic_graph_order_not_stroke_order',
        attachment_key=['geometry_id', 'path_id', 's'], nodes=nodes, paths=paths,
        attachment_parameterization='canonical_s_in_geometry_json_paths_csv_xy_paths_npz',
        raw_parameterization='diagnostic_raw_s_not_attachment_s',
        statistics=dict(ink_component_count=len(processing['ink_components']),
            skeleton_component_count=traced['component_count'], skeleton_pixels=traced['skeleton_pixels'],
            path_segment_count=len(paths), junction_region_count=junctions,
            isolated_point_count=isolated, loop_count=loops, cycle_rank=cycle_rank),
        coverage=traced['coverage'], review_flags=flags)
    geometry['geometry_id'] = geometry_identity(geometry)
    return dict(geometry=geometry, raw_paths=raw_paths, **prepared)


def sample_path(geometry, path_id, s):
    """Lookup XY for a future geometry_id/path_id/s attachment, without time."""
    paths = [path for path in geometry['paths'] if path['id'] == path_id]
    if len(paths) != 1:
        raise ValueError('path_id is absent or ambiguous')
    values = np.asarray(s, float)
    if not np.isfinite(values).all() or np.any(values < 0) or np.any(values > 1):
        raise ValueError('s must be finite and within 0..1')
    path = paths[0]
    xy = np.asarray(path['xy'])
    flat = np.column_stack([np.interp(values.ravel(), path['s'], xy[:, i]) for i in range(2)])
    return flat.reshape(values.shape+(2,))
