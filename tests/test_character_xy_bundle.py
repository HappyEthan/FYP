"""Exported geometry is portable, immutable and verifiable before later attachment."""
import csv
import json

import numpy as np
from PIL import Image, ImageDraw
import pytest


def fixture_image(tmp_path, *, dot=False):
    source = tmp_path/'character.png'
    image = Image.new('RGB', (61, 61), 'white')
    draw = ImageDraw.Draw(image)
    if dot:
        draw.rectangle((28, 28, 31, 31), fill='black')
    else:
        draw.line([(8, 30), (52, 30)], fill='black')
        draw.line([(30, 8), (30, 52)], fill='black')
    image.save(source)
    return source


def test_bundle_roundtrip_and_numpy_csv_exports_share_coordinate_semantics(tmp_path):
    from brushbot.character_xy import extract_character, load_geometry, sample_path

    source = fixture_image(tmp_path)
    output = tmp_path/'bundle'
    result = extract_character(source, output, mm_per_pixel=.2)
    geometry = load_geometry(output)
    assert result['geometry_id'] == geometry['geometry_id']
    assert geometry['units'] == 'mm'
    assert geometry['statistics']['path_segment_count'] == 4
    assert (output/'source_image.bin').read_bytes() == source.read_bytes()
    with np.load(output/'xy_paths.npz', allow_pickle=False) as pack:
        assert str(pack['geometry_id']) == geometry['geometry_id']
        assert str(pack['units']) == 'mm'
        assert pack['offsets'].tolist() == [0, 2, 4, 6, 8]
        for i, path in enumerate(geometry['paths']):
            lo, hi = pack['offsets'][i:i+2]
            assert pack['xy'][lo:hi] == pytest.approx(np.asarray(path['xy']))
            assert pack['path_ids'][i] == path['id']
    rows = list(csv.DictReader((output/'paths.csv').open()))
    assert len(rows) == 8
    for row in rows:
        expected = sample_path(geometry, row['path_id'], float(row['s']))
        assert [float(row['x']), float(row['y'])] == pytest.approx(expected)
    raw_reader = csv.DictReader((output/'raw_paths.csv').open())
    assert 's' not in raw_reader.fieldnames
    assert {'raw_s', 'raw_arc_length'} <= set(raw_reader.fieldnames)
    assert len(list(raw_reader)) > len(rows)
    assert {'report.html', 'preview.png', 'image.png', 'mask.png', 'skeleton.png'} <= set(result['files'])


def test_point_only_bundle_has_explicit_nodes_and_empty_path_arrays(tmp_path):
    from brushbot.character_xy import extract_character, load_geometry

    output = tmp_path/'point'
    extract_character(fixture_image(tmp_path, dot=True), output)
    geometry = load_geometry(output)
    assert geometry['statistics']['isolated_point_count'] == 1
    assert not geometry['paths']
    with np.load(output/'xy_paths.npz', allow_pickle=False) as pack:
        assert pack['xy'].shape == (0, 2)
        assert pack['offsets'].tolist() == [0]
    assert len(list(csv.DictReader((output/'nodes.csv').open()))) == 1


@pytest.mark.parametrize('name', ['geometry.json', 'paths.csv', 'source_image.bin', 'report.html'])
def test_loader_detects_corrupted_or_missing_bundle_files(tmp_path, name):
    from brushbot.character_xy import extract_character, load_geometry

    output = tmp_path/'bundle'
    extract_character(fixture_image(tmp_path), output)
    (output/name).write_bytes(b'corrupted')
    with pytest.raises(ValueError, match='integrity|checksum|hash'):
        load_geometry(output)


def test_existing_output_is_refused_and_failed_render_leaves_no_published_bundle(tmp_path, monkeypatch):
    from brushbot.character_xy import extract_character
    from brushbot.character_xy import preview

    source = fixture_image(tmp_path)
    existing = tmp_path/'existing'
    existing.mkdir()
    (existing/'keep').write_text('user file')
    with pytest.raises(ValueError, match='exist'):
        extract_character(source, existing)
    assert (existing/'keep').read_text() == 'user file'

    def fail(*args, **kwargs):
        raise ValueError('render failure fixture')
    monkeypatch.setattr(preview, 'write_previews', fail)
    with pytest.raises(ValueError, match='render failure'):
        extract_character(source, tmp_path/'failed')
    assert not (tmp_path/'failed').exists()
    assert not list(tmp_path.glob('.failed-*'))
