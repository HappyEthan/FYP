"""Image extraction fixtures pin coordinates and expose ambiguous references."""
import json

import numpy as np
from PIL import Image, ImageDraw
import pytest


def line_image(tmp_path, *, transparent=False):
    path = tmp_path/'line.png'
    image = Image.new('RGBA' if transparent else 'L', (41, 21),
                      (255, 255, 255, 0) if transparent else 255)
    draw = ImageDraw.Draw(image)
    draw.line([(5, 10), (35, 10)], fill=(0, 0, 0, 255) if transparent else 0)
    image.save(path)
    return path


def test_reference_pixel_mapping_preserves_explicit_scale_rotation_and_direction(tmp_path):
    from brushbot.xy_comparison.image_reference import extract_reference, load_reference

    source = line_image(tmp_path)
    report = extract_reference(source, tmp_path/'ref', mm_per_pixel=.5,
                               origin_px=(5, 10), origin_mm=(100, 200), rotation_deg=90)
    reference = load_reference(tmp_path/'ref')
    assert report['status'] == 'ready'
    assert reference['xy_mm'][[0, -1]] == pytest.approx(np.array([[100, 200], [100, 215]]))
    assert reference['metadata']['direction_source'] == 'geometric_heuristic_requires_review'
    assert reference['metadata']['image_sha256']
    assert (tmp_path/'ref'/'reference_preview.png').exists()


def test_transparent_background_is_white_and_reverse_is_explicit(tmp_path):
    from brushbot.xy_comparison.image_reference import extract_reference, load_reference

    source = line_image(tmp_path, transparent=True)
    extract_reference(source, tmp_path/'ref', mm_per_pixel=1, origin_px=(0, 0), reverse=True)
    ref = load_reference(tmp_path/'ref')
    assert ref['xy_mm'][[0, -1]] == pytest.approx(np.array([[35, -10], [5, -10]]))
    assert ref['metadata']['reverse'] is True


@pytest.mark.parametrize('value', [0, 255])
def test_constant_images_fail_before_output_is_created(tmp_path, value):
    from brushbot.xy_comparison.image_reference import extract_reference

    image = tmp_path/'empty.png'
    Image.new('L', (20, 20), value).save(image)
    with pytest.raises(ValueError, match='contrast|foreground|constant'):
        extract_reference(image, tmp_path/'ref', mm_per_pixel=1)
    assert not (tmp_path/'ref').exists()


def test_multiple_strokes_produce_diagnostics_instead_of_a_silent_largest_component(tmp_path):
    from brushbot.xy_comparison.image_reference import extract_reference, load_reference

    image = Image.new('L', (41, 21), 255)
    draw = ImageDraw.Draw(image)
    draw.line([(5, 5), (35, 5)], fill=0)
    draw.line([(5, 15), (35, 15)], fill=0)
    path = tmp_path/'two.png'
    image.save(path)
    result = extract_reference(path, tmp_path/'ref', mm_per_pixel=1)
    assert result['status'] == 'needs_review'
    assert len(result['components']) == 2
    assert not (tmp_path/'ref'/'reference.csv').exists()
    assert (tmp_path/'ref'/'reference_preview.png').exists()
    with pytest.raises(ValueError, match='review|ready'):
        load_reference(tmp_path/'ref')


def test_branched_skeleton_requires_annotation_and_reports_omitted_branches(tmp_path):
    from brushbot.xy_comparison.image_reference import extract_reference, load_reference

    image = Image.new('L', (41, 41), 255)
    draw = ImageDraw.Draw(image)
    draw.line([(20, 5), (20, 35)], fill=0)
    draw.line([(5, 20), (35, 20)], fill=0)
    path = tmp_path/'cross.png'
    image.save(path)
    result = extract_reference(path, tmp_path/'unresolved', mm_per_pixel=1)
    assert result['status'] == 'needs_review'
    result = extract_reference(path, tmp_path/'selected', mm_per_pixel=1,
                               origin_px=(0, 0), start_px=(5, 20), end_px=(35, 20))
    ref = load_reference(tmp_path/'selected')
    assert ref['xy_mm'][[0, -1]] == pytest.approx(np.array([[5, -20], [35, -20]]))
    assert result['omitted_skeleton_pixels'] == 30
    assert result['direction_source'] == 'explicit_endpoints'


def test_dust_is_counted_and_does_not_move_the_reference(tmp_path):
    from brushbot.xy_comparison.image_reference import extract_reference, load_reference

    source = line_image(tmp_path)
    image = Image.open(source)
    image.putpixel((1, 1), 0)
    image.save(source)
    result = extract_reference(source, tmp_path/'ref', mm_per_pixel=1)
    assert result['removed_small_component_pixels'] == 1
    assert result['raw_route_pixels'] == 31
    assert load_reference(tmp_path/'ref')['xy_mm'][[0, -1]] == pytest.approx(np.array([[-15, 0], [15, 0]]))


def test_reference_snapshots_are_checked_and_original_can_be_removed(tmp_path):
    from brushbot.xy_comparison.image_reference import extract_reference, load_reference

    source = line_image(tmp_path)
    extract_reference(source, tmp_path/'ref', mm_per_pixel=1)
    source.unlink()
    load_reference(tmp_path/'ref')
    (tmp_path/'ref'/'reference.csv').write_text('x_mm,y_mm\n0,0\n100,0\n')
    with pytest.raises(ValueError, match='hash|changed'):
        load_reference(tmp_path/'ref')


def test_invalid_geometry_options_and_distant_anchors_are_rejected(tmp_path):
    from brushbot.xy_comparison.image_reference import extract_reference

    source = line_image(tmp_path)
    for options in [dict(mm_per_pixel=0), dict(mm_per_pixel=float('nan')),
                    dict(mm_per_pixel=1, start_px=(5, 10)),
                    dict(mm_per_pixel=1, start_px=(-500, 10), end_px=(35, 10))]:
        with pytest.raises(ValueError):
            extract_reference(source, tmp_path/'ref', **options)
    assert not (tmp_path/'ref').exists()


@pytest.mark.parametrize('change', ['scale', 'nonfinite_origin', 'source_hash', 'image_hash', 'image_size'])
def test_reference_metadata_cannot_contradict_frozen_pixels_and_coordinates(tmp_path, change):
    from brushbot.xy_comparison.image_reference import extract_reference, load_reference

    source = line_image(tmp_path)
    extract_reference(source, tmp_path/'ref', mm_per_pixel=1)
    file = tmp_path/'ref'/'reference.json'
    metadata = json.loads(file.read_text())
    if change == 'scale':
        metadata['transform']['mm_per_pixel'] = 2
    elif change == 'nonfinite_origin':
        metadata['transform']['origin_mm'][0] = float('nan')
    elif change == 'source_hash':
        metadata['source_file_sha256'] = 'wrong'
    elif change == 'image_hash':
        metadata['image_sha256'] = 'wrong'
    else:
        metadata['image_size_px'] = [99, 99]
    file.write_text(json.dumps(metadata))
    with pytest.raises(ValueError):
        load_reference(tmp_path/'ref')


def test_pixel_staircase_simplification_has_a_bounded_geometric_tolerance():
    from brushbot.xy_comparison.image_reference import simplify_path

    points = [(5, 35)]
    for x in range(6, 36):
        points.extend([(x, 41-x), (x, 40-x)])
    simplified = simplify_path(points, .75)
    assert simplified == pytest.approx(np.array([[5, 35], [35, 5]]))
    assert np.linalg.norm(np.diff(simplified, axis=0), axis=1).sum() == pytest.approx(30*np.sqrt(2))
    assert len(simplify_path(points, 0)) == 61


def test_reference_simplification_is_recorded_and_raw_route_is_frozen(tmp_path):
    from brushbot.xy_comparison.image_reference import extract_reference, load_reference

    source = line_image(tmp_path)
    report = extract_reference(source, tmp_path/'simplified', mm_per_pixel=1, origin_px=(0, 0))
    ref = load_reference(tmp_path/'simplified')
    assert report['simplify_tolerance_px'] == .75
    assert report['raw_route_pixels'] == 31
    assert len(ref['xy_mm']) == 2
    assert (tmp_path/'simplified'/'skeleton_path.csv').exists()
    extract_reference(source, tmp_path/'raw', mm_per_pixel=1, simplify_px=0)
    assert len(load_reference(tmp_path/'raw')['xy_mm']) == 31
