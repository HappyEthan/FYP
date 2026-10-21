"""Image-to-geometry fixtures pin coordinate meaning and future attachment IDs."""
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
import pytest


def line_image(tmp_path, name='line.png'):
    path = tmp_path/name
    image = Image.new('L', (41, 21), 255)
    ImageDraw.Draw(image).line([(5, 10), (35, 10)], fill=0)
    image.save(path)
    return path


def test_default_output_is_cartesian_pixels_with_no_invented_timing_or_magnetic_fields(tmp_path):
    from brushbot.character_xy.pipeline import analyze_character, sample_path

    analysis = analyze_character(line_image(tmp_path))
    geometry = analysis['geometry']
    assert geometry['role'] == 'character_xy_geometry'
    assert geometry['units'] == 'px'
    assert geometry['coordinate_frame'] == 'image_cartesian'
    assert len(geometry['paths']) == 1
    path = geometry['paths'][0]
    assert path['xy'] == [[-15., 0.], [15., 0.]]
    assert path['s'] == [0., 1.]
    assert path['arc_length'] == [0., 30.]
    assert not {'t', 'g_target', 'z', 'z_ff', 'orientation'} & path.keys()
    assert sample_path(geometry, path['id'], [0, .5, 1]) == pytest.approx(np.array([[-15, 0], [0, 0], [15, 0]]))


def test_explicit_mm_mapping_agrees_with_source_pixel_coordinates(tmp_path):
    from brushbot.character_xy.pipeline import analyze_character

    geometry = analyze_character(line_image(tmp_path), mm_per_pixel=.5, origin_px=(5, 10),
                                  origin_xy=(100, 200), rotation_deg=90)['geometry']
    assert geometry['units'] == 'mm'
    assert geometry['coordinate_frame'] == 'paper'
    assert geometry['paths'][0]['xy'] == pytest.approx(np.array([[100, 200], [100, 215]]))


def test_resize_and_crop_map_pixel_centres_back_to_the_exif_corrected_source(tmp_path):
    from brushbot.character_xy.pipeline import analyze_character, processed_to_original

    image = Image.new('L', (400, 200), 255)
    ImageDraw.Draw(image).line([(30, 50), (210, 50)], width=7, fill=0)
    source = tmp_path/'large.png'
    image.save(source)
    analysis = analyze_character(source, crop=(20, 10, 220, 110), max_side_px=100,
                                 image_width_mm=40, origin_px=(0, 0))
    geometry = analysis['geometry']
    assert analysis['image'].size == (100, 50)
    mapped = processed_to_original([[0, 0], [99, 49]], geometry['preprocessing'])
    assert mapped == pytest.approx(np.array([[20.5, 10.5], [218.5, 108.5]]))
    for path in geometry['paths']:
        source_xy = np.asarray(path['original_pixel_xy'])
        expected = source_xy*np.array([.1, -.1])
        assert path['xy'] == pytest.approx(expected)


def test_all_disconnected_parts_and_dot_are_kept_without_joining_them(tmp_path):
    from brushbot.character_xy.pipeline import analyze_character

    image = Image.new('L', (61, 61), 255)
    draw = ImageDraw.Draw(image)
    draw.line([(5, 10), (30, 10)], fill=0)
    draw.line([(30, 50), (55, 50)], fill=0)
    draw.rectangle((10, 30, 13, 33), fill=0)
    source = tmp_path/'parts.png'
    image.save(source)
    geometry = analyze_character(source)['geometry']
    assert len(geometry['paths']) == 2
    assert sum(n['kind'] == 'isolated' for n in geometry['nodes']) == 1
    assert geometry['statistics']['ink_component_count'] == 3
    assert geometry['coverage']['untraced_edges'] == 0


def test_identical_inputs_have_identical_ids_but_scale_or_threshold_changes_version(tmp_path):
    from brushbot.character_xy.pipeline import analyze_character

    source = line_image(tmp_path)
    first = analyze_character(source)['geometry']
    copied = tmp_path/'copied.png'
    copied.write_bytes(source.read_bytes())
    second = analyze_character(copied)['geometry']
    assert first['geometry_id'] == second['geometry_id']
    assert first['paths'] == second['paths']
    assert first['geometry_id'] != analyze_character(source, mm_per_pixel=1)['geometry']['geometry_id']
    assert first['geometry_id'] != analyze_character(source, threshold=127)['geometry']['geometry_id']


def test_transparency_and_light_on_dark_input_preserve_shape(tmp_path):
    from brushbot.character_xy.pipeline import analyze_character

    transparent = Image.new('RGBA', (41, 21), (0, 0, 0, 0))
    ImageDraw.Draw(transparent).line([(5, 10), (35, 10)], fill=(0, 0, 0, 255))
    dark = Image.new('L', (41, 21), 0)
    ImageDraw.Draw(dark).line([(5, 10), (35, 10)], fill=255)
    a, b = tmp_path/'transparent.png', tmp_path/'dark.png'
    transparent.save(a)
    dark.save(b)
    assert analyze_character(a)['geometry']['paths'][0]['xy'] == [[-15., 0.], [15., 0.]]
    assert analyze_character(b, invert=True)['geometry']['paths'][0]['xy'] == [[-15., 0.], [15., 0.]]


def test_exif_orientation_is_applied_before_coordinate_definition(tmp_path):
    from brushbot.character_xy.pipeline import analyze_character

    image = Image.new('RGB', (41, 21), 'white')
    ImageDraw.Draw(image).line([(5, 10), (35, 10)], fill='black')
    exif = Image.Exif()
    exif[274] = 6
    source = tmp_path/'orientation.png'
    image.save(source, exif=exif)
    analysis = analyze_character(source)
    assert analysis['geometry']['preprocessing']['exif_image_size_px'] == [21, 41]
    assert analysis['image'].size == (21, 41)


@pytest.mark.parametrize('options', [dict(mm_per_pixel=0), dict(mm_per_pixel=1, image_width_mm=100),
    dict(rotation_deg=float('nan')), dict(min_component_pixels=0), dict(simplify_px=-1),
    dict(max_side_px=0), dict(crop=(0, 0, 100, 100)), dict(adaptive=True, threshold=100),
    dict(adaptive=True, adaptive_window=4)])
def test_invalid_options_are_rejected(options, tmp_path):
    from brushbot.character_xy.pipeline import analyze_character

    with pytest.raises(ValueError):
        analyze_character(line_image(tmp_path), **options)


def test_constant_or_empty_images_fail_clearly(tmp_path):
    from brushbot.character_xy.pipeline import analyze_character

    source = tmp_path/'blank.png'
    Image.new('L', (50, 50), 255).save(source)
    with pytest.raises(ValueError, match='contrast|foreground|constant'):
        analyze_character(source)


def test_sample_queries_reject_missing_paths_and_out_of_range_positions(tmp_path):
    from brushbot.character_xy.pipeline import analyze_character, sample_path

    geometry = analyze_character(line_image(tmp_path))['geometry']
    for path, s in [('absent', .5), ('p0000', -1), ('p0000', 1.1), ('p0000', float('nan'))]:
        with pytest.raises(ValueError):
            sample_path(geometry, path, s)


def test_closed_cycle_survives_large_simplification_and_graph_cycle_is_recorded(tmp_path):
    from brushbot.character_xy.pipeline import analyze_character

    image = Image.new('L', (61, 61), 255)
    ImageDraw.Draw(image).rectangle((10, 10, 50, 50), outline=0)
    source = tmp_path/'cycle.png'
    image.save(source)
    geometry = analyze_character(source, simplify_px=1000)['geometry']
    path = geometry['paths'][0]
    assert path['closed'] and len(path['xy']) >= 4
    assert path['xy'][0] == path['xy'][-1]
    assert geometry['statistics']['cycle_rank'] == 1
    assert 'loop_direction_is_not_inferred' in geometry['review_flags']
    # A spur splits this cycle into multiple segments without destroying the cycle.
    ImageDraw.Draw(image).line([(10, 10), (10, 3)], fill=0)
    image.save(source)
    geometry = analyze_character(source)['geometry']
    assert geometry['statistics']['cycle_rank'] == 1
    assert geometry['coverage']['untraced_edges'] == 0


def test_local_threshold_handles_shaded_background_and_tiny_component_fallback(tmp_path):
    from brushbot.character_xy.pipeline import analyze_character

    gradient = np.tile(np.linspace(100, 250, 121).astype('uint8'), (61, 1))
    gradient[27:32, 12:109] = 10
    source = tmp_path/'shaded.png'
    Image.fromarray(gradient).save(source)
    geometry = analyze_character(source, adaptive=True)['geometry']
    assert geometry['statistics']['ink_component_count'] == 1
    assert len(geometry['paths']) == 1
    assert max(p[0] for p in geometry['paths'][0]['original_pixel_xy']) > 100
    tiny = Image.new('L', (21, 21), 255)
    ImageDraw.Draw(tiny).rectangle((9, 9, 10, 10), fill=0)
    tiny.save(source)
    geometry = analyze_character(source, min_component_pixels=1)['geometry']
    assert geometry['statistics']['isolated_point_count'] == 1
    assert geometry['preprocessing']['point_fallback_components'] == [0]


def test_returning_loop_keeps_external_route_between_two_junction_boundary_pixels(tmp_path):
    from brushbot.character_xy.pipeline import analyze_character

    image = Image.new('L', (61, 61), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 10, 50, 50), outline=0)
    draw.line([(20, 10), (20, 3)], fill=0)
    draw.line([(21, 10), (21, 16)], fill=0)
    source = tmp_path/'junction-loop.png'
    image.save(source)
    geometry = analyze_character(source, simplify_px=1000)['geometry']
    loop = next(p for p in geometry['paths'] if p['topological_loop'])
    assert not loop['closed']  # its two ends meet different pixels of one node region
    assert loop['length'] > 100
    assert len(loop['xy']) >= 4
    assert loop['xy'][0] != loop['xy'][-1]  # no invented link through the node region


def test_cycle_split_between_two_nodes_does_not_collapse_into_overlapping_chords(tmp_path):
    from brushbot.character_xy.pipeline import analyze_character

    image = Image.new('L', (61, 61), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 10, 50, 50), outline=0)
    draw.line([(10, 10), (10, 3)], fill=0)
    draw.line([(50, 50), (50, 57)], fill=0)
    source = tmp_path/'split-cycle.png'
    image.save(source)
    geometry = analyze_character(source, simplify_px=1000)['geometry']
    cycle_paths = [p for p in geometry['paths'] if p['length'] > 50]
    assert len(cycle_paths) == 2
    assert all(len(p['xy']) >= 3 for p in cycle_paths)
    assert cycle_paths[0]['xy'] != cycle_paths[1]['xy']
    assert all(p['in_graph_cycle'] for p in cycle_paths)
