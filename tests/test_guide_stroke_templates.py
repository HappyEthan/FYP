"""Publishing traced guides must preserve their image binding and phase turns."""
import copy
import csv
import hashlib
import json

import numpy as np
from PIL import Image, ImageDraw
import pytest

from brushbot.stroke_templates.bundle import read_json, write_json
from brushbot.stroke_templates.geometry import adapt_stroke
from brushbot.stroke_templates.schema import validate_template
from tests.test_stroke_template_cli import command


def review_fixture(tmp_path):
    directory = tmp_path/'guide review'; directory.mkdir()
    for variant, end in [('long', 95), ('short', 65)]:
        image = Image.new('RGB', (140, 100), 'white')
        draw = ImageDraw.Draw(image)
        draw.rectangle((12, 30, end+12, 65), fill='black')
        xy = [[20, 50], [23, 47], [26, 50]]
        xy += [[x, 50+(x-26)*.1] for x in range(27, end+1)]
        xy += [[end+3, xy[-1][1]+3], [end+7, xy[-1][1]], [end+2, xy[-1][1]-2]]
        source = [[x, 99-y] for x, y in xy]
        draw.line([tuple(p) for p in source], fill='white', width=2)
        image.save(directory/f'{variant}_source.jpg')
        write_json(directory/f'{variant}_trace.json', dict(
            id=variant, name='长横' if variant=='long' else '短横',
            source_sha256=hashlib.sha256((directory/f'{variant}_source.jpg').read_bytes()).hexdigest(),
            source_url='https://example.org/'+variant+'.jpg', article_url='https://example.org/article',
            image_size_px=[140, 100], source_points_image_px=source, xy_px=xy,
            anchors=[0, 2, len(xy)-4, len(xy)-1], box=[10, 20, end+15, 75],
            review_status='unreviewed', role='teaching_guide_trace_candidate_not_measured_motion',
            method='manually_ordered_waypoints_with_white_guide_pixel_tracking',
            writing_hint='教学示意线，阶段需复核。'))
    seal_review(directory)
    return directory


def seal_review(directory):
    write_json(directory/'manifest.json', dict(schema_version=1, role='teaching_guide_review',
        path_count=2, files={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.iterdir()) if p.name!='manifest.json'}))


def test_cli_promotes_bound_guides_to_adaptable_models_without_generic_end_substitution(tmp_path):
    source = review_fixture(tmp_path)
    root = tmp_path/'library'; output = root/'strokes/guides'
    result = command('import-guides', '--review-dir', source, '--output-dir', output, '--catalog-root', root)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['template_count'] == 2
    for variant in ('long', 'short'):
        folder = output/'templates'/('heng_'+variant)
        model = validate_template(read_json(folder/'template.json'))
        raw = read_json(source/f'{variant}_trace.json')
        reference = model['references'][0]; anchors = reference['anchors']
        xy = np.asarray(reference['xy_px']); original = np.asarray(raw['xy_px'])
        assert xy[anchors] == pytest.approx(original[raw['anchors']])
        assert len(xy) < len(original)
        assert xy[-1, 0] < xy[-2, 0]  # The real return turn survives import.
        assert model['evidence']['level'] == 'teaching_rule_candidate'
        assert model['evidence']['physical_validation'] is False
        assert model['guide_trace']['review_status'] == 'unreviewed'
        assert model['guide_trace']['max_raw_point_deviation_px'] <= .75+1e-8
        assert reference['width_source'] == 'diagram_body_normal_scan_after_guide_gap_closing'
        assert model['prototype']['width_profiles'] == {}
        assert (folder/'source.jpg').read_bytes() == (source/f'{variant}_source.jpg').read_bytes()
        assert read_json(folder/'raw_trace.json') == raw
        with (folder/('heng_'+variant+'_xy.csv')).open() as stream:
            rows = list(csv.DictReader(stream))
        assert len(rows) == len(xy)
        assert float(rows[-1]['x_px']) == xy[-1, 0]
        assert float(rows[-1]['y_px']) == xy[-1, 1]
        adapted = adapt_stroke(model, xy, anchors, width_px=reference['width_px'])
        assert adapted['s'][0] == 0 and adapted['s'][-1] == 1
    assert (root/'index.html').is_file()
    frozen = (output/'manifest.json').read_bytes()
    assert command('import-guides', '--review-dir', source, '--output-dir', output).returncode != 0
    assert (output/'manifest.json').read_bytes() == frozen


@pytest.mark.parametrize('corruption', ['source_checksum', 'xy_flip', 'trace_not_manifested', 'invalid_crop'])
def test_unbound_or_inconsistent_guides_cannot_publish_a_partial_library(tmp_path, corruption):
    source = review_fixture(tmp_path)
    if corruption == 'source_checksum':
        (source/'short_source.jpg').write_bytes(b'changed')
    elif corruption == 'xy_flip':
        trace = read_json(source/'short_trace.json'); trace['xy_px'][0][1] += 1
        write_json(source/'short_trace.json', trace); seal_review(source)
    elif corruption == 'trace_not_manifested':
        manifest = read_json(source/'manifest.json'); del manifest['files']['short_trace.json']
        write_json(source/'manifest.json', manifest)
    else:
        trace = read_json(source/'short_trace.json'); trace['box'] = [-10, 20, 400, 75]
        write_json(source/'short_trace.json', trace); seal_review(source)
    output = tmp_path/'output'
    result = command('import-guides', '--review-dir', source, '--output-dir', output)
    assert result.returncode != 0
    assert not output.exists()


def test_guide_models_cannot_silently_mismatch_their_image_coordinates(tmp_path):
    source = review_fixture(tmp_path); output = tmp_path/'output'
    result = command('import-guides', '--review-dir', source, '--output-dir', output)
    assert result.returncode == 0, result.stderr
    from brushbot.stroke_templates.schema import identity
    model = read_json(output/'templates/heng_long/template.json')
    changed = copy.deepcopy(model)
    changed['references'][0]['xy_px'][0][0] += 3
    changed['template_id'] = identity(changed, 'template_id')
    with pytest.raises(ValueError, match='guide'):
        validate_template(changed)
