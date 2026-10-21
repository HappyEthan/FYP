"""A composed character must really use the selected library models and be reproducible."""
import copy
import hashlib
from pathlib import Path

import numpy as np
import pytest

from brushbot.stroke_templates.bundle import load_fitted_geometry, read_json, write_json
from brushbot.stroke_templates.examples import generate_yong_example
from brushbot.stroke_templates.schema import validate_annotation
from brushbot.stroke_templates.teaching import generate_library
from tests.test_stroke_template_catalog import catalog_data
from tests.test_stroke_template_cli import command
from tests.test_teaching_stroke_library import source_fixture


ROOT = Path(__file__).resolve().parents[1]
TYPES = ['dian_right','hengzhegou','hengpie','pie_slant','na_slant']


def composition_fixture(tmp_path):
    root = tmp_path/'library'
    legacy = root/'characters/yong_old'
    generate_yong_example(ROOT/'data/makemeahanzi/graphics.txt', legacy, image_size=360)
    config, sources = source_fixture(tmp_path)
    config['strokes'] = [s for s in config['strokes'] if s['id'] in TYPES]
    generate_library(config, sources, root/'strokes/teaching')
    layout = legacy/'fit'
    annotation = validate_annotation(read_json(layout/'annotation.json'))
    recipe = dict(schema_version=1, role='template_character_recipe', character='永',
        layout=dict(annotation=str(layout/'annotation.json'), image=str(layout/'source_image.bin'),
            annotation_id=annotation['annotation_id'], source_sha256=annotation['source_sha256']), strokes=[])
    for stroke, tid in zip(annotation['strokes'], TYPES):
        folder = root/'strokes/teaching/templates'/tid
        model = read_json(folder/'template.json')
        recipe['strokes'].append(dict(stroke_id=stroke['id'], template=str(folder), template_id=model['template_id'],
            parameters=dict(body_scale=1., width_scale=1., rotation_deg=0., offset_xy_px=[0.,0.], span_scales={})))
    path = tmp_path/'recipe.json'; write_json(path, recipe)
    return root, path, recipe, legacy


def test_cli_composes_yong_from_library_and_rebuilds_from_its_self_contained_recipe(tmp_path):
    root, path, recipe, legacy = composition_fixture(tmp_path)
    original = (legacy/'manifest.json').read_bytes()
    output = root/'characters/yong_composed'
    result = command('compose', '--recipe', path, '--output-dir', output, '--catalog-root', root)
    assert result.returncode == 0, result.stderr
    geometry = load_fitted_geometry(output/'fit')
    assert geometry['complete'] is True and len(geometry['strokes']) == 5
    expected = [s['template_id'] for s in recipe['strokes']]
    assert geometry['template_ids'] == expected
    assert [s['template_id'] for s in geometry['strokes']] == expected
    assert geometry['provenance']['source_kind'] == 'template_composition'
    assert geometry['physical_validation'] is False
    old = read_json(legacy/'fit/geometry.json')
    assert all(s['xy_px'] != a['xy_px'] for s,a in zip(geometry['strokes'], old['strokes']))
    saved = read_json(output/'recipe.json')
    assert all(not Path(s['template']).is_absolute() for s in saved['strokes'])
    assert (output/'layout/source_image.bin').read_bytes() == (legacy/'fit/source_image.bin').read_bytes()
    for stroke in saved['strokes']:
        assert (output/stroke['template']/'template.json').is_file()
    rebuilt = command('compose', '--recipe', output/'recipe.json', '--output-dir', tmp_path/'rebuilt')
    assert rebuilt.returncode == 0, rebuilt.stderr
    assert load_fitted_geometry(tmp_path/'rebuilt/fit')['geometry_id'] == geometry['geometry_id']
    latest = next(e for e in catalog_data(root/'index.html')['characters'] if e['character']=='永')
    assert latest['id'] == geometry['geometry_id'] and latest['composition'] is True
    assert (legacy/'manifest.json').read_bytes() == original


def test_parameter_changes_affect_only_the_chosen_stroke(tmp_path):
    _, path, recipe, _ = composition_fixture(tmp_path)
    original = tmp_path/'original'
    assert command('compose', '--recipe', path, '--output-dir', original).returncode == 0
    recipe['strokes'][3]['parameters']['body_scale'] = 1.1
    write_json(path, recipe)
    changed = tmp_path/'changed'
    result = command('compose', '--recipe', path, '--output-dir', changed)
    assert result.returncode == 0, result.stderr
    a, b = load_fitted_geometry(original/'fit'), load_fitted_geometry(changed/'fit')
    for i in [0,1,2,4]:
        assert a['strokes'][i]['xy_px'] == b['strokes'][i]['xy_px']
    assert a['strokes'][3]['xy_px'] != b['strokes'][3]['xy_px']


def test_explicit_reference_ink_constraint_rejects_in_canvas_but_misaligned_paths(tmp_path):
    _,path,recipe,_ = composition_fixture(tmp_path)
    recipe['image_constraint'] = dict(max_outside_fraction=0.)
    write_json(path,recipe)
    output = tmp_path/'output'
    result = command('compose','--recipe',path,'--output-dir',output)
    assert result.returncode != 0
    assert 'reference ink' in result.stderr
    assert not output.exists()


def test_rebuilding_an_old_character_cannot_promote_its_template_snapshots_over_newer_library_models(tmp_path):
    from brushbot.stroke_templates.catalog import collect_catalog
    root, path, recipe, _ = composition_fixture(tmp_path)
    config = read_json(root/'strokes/teaching/recipes.json')
    config['strokes'] = [s for s in config['strokes'] if s['id']=='dian_right']
    config['strokes'][0]['parameters'] = dict(body_scales=dict(dot_body=1.1))
    generate_library(config,tmp_path/'sources',root/'strokes/newer_dot')
    newer = read_json(root/'strokes/newer_dot/templates/dian_right/template.json')['template_id']
    assert newer != recipe['strokes'][0]['template_id']
    output = root/'characters/old_recipe_rebuilt'
    result = command('compose','--recipe',path,'--output-dir',output,'--catalog-root',root)
    assert result.returncode == 0,result.stderr
    variants = [e for e in collect_catalog(root)['templates'] if e['type']=='dian' and e['variant']=='right_dot']
    assert variants[0]['id'] == newer


@pytest.mark.parametrize('missing', ['template.json', 'report.html'])
def test_composition_rejects_template_files_not_bound_by_the_manifest(tmp_path, missing):
    _, path, recipe, _ = composition_fixture(tmp_path)
    directory = Path(recipe['strokes'][0]['template'])
    manifest = read_json(directory/'manifest.json')
    del manifest['files'][missing]
    write_json(directory/'manifest.json', manifest)
    output = tmp_path/'output'
    result = command('compose', '--recipe', path, '--output-dir', output)
    assert result.returncode != 0
    assert not output.exists()


def test_composition_can_reuse_one_versioned_model_for_two_strokes(tmp_path):
    _, path, recipe, _ = composition_fixture(tmp_path)
    layout_path = Path(recipe['layout']['annotation'])
    annotation = read_json(layout_path)
    annotation['strokes'][4] = dict(copy.deepcopy(annotation['strokes'][3]), id='s05')
    for index in (3,4):
        annotation['strokes'][index]['width_hint_px'] = 22.
    annotation = validate_annotation(annotation)
    write_json(layout_path, annotation)
    recipe['layout']['annotation_id'] = annotation['annotation_id']
    recipe['strokes'][4] = dict(copy.deepcopy(recipe['strokes'][3]), stroke_id='s05')
    write_json(path, recipe)
    output = tmp_path/'output'
    result = command('compose', '--recipe', path, '--output-dir', output)
    assert result.returncode == 0, result.stderr
    geometry = load_fitted_geometry(output/'fit')
    assert geometry['complete'] is True
    assert geometry['strokes'][3]['template_id'] == geometry['strokes'][4]['template_id']
    assert geometry['strokes'][3]['xy_px'] == geometry['strokes'][4]['xy_px']


@pytest.mark.parametrize('bad', ['template_id', 'layout_id', 'missing_stroke', 'unknown_parameter'])
def test_bad_composition_inputs_cannot_publish_an_incomplete_character(tmp_path, bad):
    _, path, recipe, _ = composition_fixture(tmp_path)
    if bad == 'template_id': recipe['strokes'][0]['template_id'] = '0'*64
    elif bad == 'layout_id': recipe['layout']['annotation_id'] = '0'*64
    elif bad == 'missing_stroke': recipe['strokes'].pop()
    else: recipe['strokes'][0]['parameters']['mystery_scale'] = 2
    write_json(path, recipe)
    output = tmp_path/'output'
    result = command('compose', '--recipe', path, '--output-dir', output)
    assert result.returncode != 0
    assert not output.exists()
