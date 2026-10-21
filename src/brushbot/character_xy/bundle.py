"""Portable geometry bundles; render in staging and refuse existing destinations."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

import numpy as np
from PIL import Image

from .pipeline import analyze_character, geometry_identity, original_to_xy
from .processing import processed_to_original
from . import preview


ARTIFACTS = frozenset({'geometry.json', 'paths.csv', 'raw_paths.csv', 'nodes.csv',
    'xy_paths.npz', 'image.png', 'mask.png', 'skeleton.png', 'source_image.bin',
    'preview.png', 'report.html'})


def _json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def _csv(path, header, rows):
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)


def _write_geometry(analysis, directory):
    geometry = analysis['geometry']
    _json(directory/'geometry.json', geometry)
    (directory/'source_image.bin').write_bytes(analysis['source_bytes'])
    analysis['image'].save(directory/'image.png')
    Image.fromarray(np.where(analysis['mask'], 0, 255).astype('uint8')).save(directory/'mask.png')
    Image.fromarray(np.where(analysis['skeleton'], 0, 255).astype('uint8')).save(directory/'skeleton.png')
    header = ['path_id', 'point_index', 'u_px', 'v_px', 'x', 'y', 'arc_length', 's']
    rows, raw_rows = [], []
    for path in geometry['paths']:
        for i, (pixel, xy, arc, s) in enumerate(zip(path['original_pixel_xy'], path['xy'],
                                                   path['arc_length'], path['s'])):
            rows.append([path['id'], i, *pixel, *xy, arc, s])
        raw_pixel = processed_to_original(analysis['raw_paths'][path['id']], geometry['preprocessing'])
        raw_xy = original_to_xy(raw_pixel, geometry['transform'])
        arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(raw_xy, axis=0), axis=1))]
        raw_rows.extend([path['id'], i, *pixel, *xy, length, length/arc[-1]]
                        for i, (pixel, xy, length) in enumerate(zip(raw_pixel, raw_xy, arc)))
    _csv(directory/'paths.csv', header, rows)
    _csv(directory/'raw_paths.csv', header[:-2]+['raw_arc_length', 'raw_s'], raw_rows)
    _csv(directory/'nodes.csv', ['node_id', 'kind', 'component_id', 'u_px', 'v_px', 'x', 'y'],
         ([n['id'], n['kind'], n['component_id'], *n['original_pixel'], *n['xy']] for n in geometry['nodes']))
    paths = geometry['paths']
    offsets = np.r_[0, np.cumsum([len(p['xy']) for p in paths])].astype(np.int64)
    arrays = {}
    for name in ('xy', 'original_pixel_xy', 's', 'arc_length'):
        arrays[name] = (np.concatenate([p[name] for p in paths], axis=0) if paths else
                        np.empty((0, 2) if name.endswith('xy') else (0,), dtype=float))
    np.savez_compressed(directory/'xy_paths.npz', **arrays, offsets=offsets,
        path_ids=np.asarray([p['id'] for p in paths], dtype=str),
        geometry_id=geometry['geometry_id'], units=geometry['units'],
        role=geometry['role'], schema_version=geometry['schema_version'])


def extract_character(image_path, output_dir, **options):
    """Extract and publish a new bundle. Existing directories are never reused."""
    output = Path(output_dir).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError(f'output directory already exists: {output}')
    analysis = analyze_character(image_path, **options)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f'.{output.name}-', dir=output.parent) as temporary:
        staging = Path(temporary)
        _write_geometry(analysis, staging)
        preview.write_previews(analysis, staging)
        geometry = analysis['geometry']
        manifest = dict(schema_version=1, role='character_xy_bundle', geometry_id=geometry['geometry_id'],
            units=geometry['units'], statistics=geometry['statistics'], review_flags=geometry['review_flags'],
            files={name: hashlib.sha256((staging/name).read_bytes()).hexdigest() for name in sorted(ARTIFACTS)})
        _json(staging/'manifest.json', manifest)
        # Exclusive mkdir is the publication lock. Manifest moves last, so readers
        # cannot accept an incomplete bundle. Roll back only the directory we own.
        try:
            output.mkdir()
        except FileExistsError as exc:
            raise ValueError(f'output directory already exists: {output}') from exc
        try:
            for name in sorted(ARTIFACTS):
                (staging/name).rename(output/name)
            (staging/'manifest.json').rename(output/'manifest.json')
        except BaseException:
            shutil.rmtree(output)
            raise
    return dict(manifest, output_dir=str(output), report_html=str(output/'report.html'),
                preview_png=str(output/'preview.png'))


def load_geometry(bundle_dir):
    """Verify all frozen artifacts and the geometry version before returning XY."""
    directory = Path(bundle_dir)
    try:
        manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
        if manifest['role'] != 'character_xy_bundle' or manifest['schema_version'] != 1:
            raise ValueError('unsupported character XY bundle schema')
        if set(manifest['files']) != ARTIFACTS:
            raise ValueError('bundle integrity: unexpected or missing artifact list')
        for name, expected in manifest['files'].items():
            if hashlib.sha256((directory/name).read_bytes()).hexdigest() != expected:
                raise ValueError(f'bundle checksum integrity error: {name}')
        geometry = json.loads((directory/'geometry.json').read_text(encoding='utf-8'))
        if geometry['role'] != 'character_xy_geometry' or geometry['schema_version'] != 1:
            raise ValueError('unsupported character XY geometry schema')
        if geometry['geometry_id'] != manifest['geometry_id'] or geometry_identity(geometry) != geometry['geometry_id']:
            raise ValueError('geometry identity hash mismatch')
        if geometry['source_sha256'] != manifest['files']['source_image.bin']:
            raise ValueError('source identity hash mismatch')
        if geometry['units'] not in ('px', 'mm') or geometry['units'] != manifest['units']:
            raise ValueError('geometry units mismatch')
        return geometry
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f'bundle integrity error: {exc}') from exc
