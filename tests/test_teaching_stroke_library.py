"""Teaching reconstruction must keep its authored rules and provisional evidence."""
import copy
import hashlib
import json
from pathlib import Path
import re

import numpy as np
from PIL import Image
import pytest

from brushbot.stroke_templates.schema import identity, validate_template
from tests.test_stroke_template_cli import command


BASIC_TYPES = {'heng','shu','pie','na','dian','ti','shugou','wangou','xiegou','wogou',
    'shuwan','shuwangou','shuti','henggou','hengzhe','hengzhegou','hengpie','piezhe','piedian',
    'hengzhewangou','shuzhe','shuzhezhegou','hengzheti','hengzhezhepie','hengpiewangou',
    'hengzhezhezhegou','hengzhewan','shuzhepie'}


def source_fixture(tmp_path):
    from brushbot.stroke_templates.teaching_recipes import default_config
    config = default_config()
    directory = tmp_path/'sources'; directory.mkdir()
    for recipe in config['strokes']:
        path = directory/(recipe['id']+'.png')
        Image.new('RGB', (120, 40), 'white').save(path)
        recipe['illustration'].update(filename=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    return config, directory


def test_independent_compound_spans_keep_entry_exit_geometry_and_named_features():
    from brushbot.stroke_templates.teaching import generate_stroke
    from brushbot.stroke_templates.teaching_recipes import default_config
    recipe = next(r for r in default_config()['strokes'] if r['type']=='hengzhegou')
    original = generate_stroke(recipe)
    changed = generate_stroke(recipe, body_scales={'horizontal': 1.4, 'vertical': .7})
    a, b = original['anchors'], changed['anchors']
    first, second = np.asarray(original['xy']), np.asarray(changed['xy'])
    assert np.diff(first[:a[1]+1], axis=0) == pytest.approx(np.diff(second[:b[1]+1], axis=0))
    assert np.diff(first[a[2]:], axis=0) == pytest.approx(np.diff(second[b[2]:], axis=0))
    assert np.linalg.norm(second[b[1]:b[2]+1]-first[a[1]:a[2]+1]) > 1
    assert [p['name'] for p in changed['landmarks']] == ['turn', 'hook']
    assert np.all(np.linalg.norm(np.diff(second, axis=0), axis=1)>1e-10)
    assert len(changed['relative_width']) == len(second)
    assert len(changed['events']) >= 5
    for event in changed['events']:
        assert event['xy'] == pytest.approx(second[event['index']])
        assert 0 <= event['s'] <= 1


def test_phase_boundaries_are_defined_by_recipe_parts_and_width_remains_an_intent():
    from brushbot.stroke_templates.teaching import generate_stroke
    from brushbot.stroke_templates.teaching_recipes import default_config
    for recipe in default_config()['strokes']:
        stroke = generate_stroke(recipe)
        assert 0 < stroke['anchors'][1] < stroke['anchors'][2] < len(stroke['xy'])-1
        assert all(v >= 0 for v in stroke['relative_width'])
        assert max(stroke['relative_width']) > 0
        assert stroke['width_definition'] == 'authored_relative_width_intent_not_measured_ink_or_force'
        assert set(stroke['phase_id']) == {'entry', 'body', 'exit'}
        assert 'g_target' not in stroke and 'time' not in stroke
    with pytest.raises(ValueError, match='scale'):
        generate_stroke(default_config()['strokes'][0], body_scales={'missing_segment': 1.2})


def test_cli_rebuilds_every_basic_type_and_distinct_writing_variants_with_source_snapshots(tmp_path):
    config, sources = source_fixture(tmp_path)
    recipes_path = tmp_path/'recipes.json'; recipes_path.write_text(json.dumps(config, ensure_ascii=False))
    output = tmp_path/'library/strokes/teaching_v1'
    result = command('teaching', '--recipes', recipes_path, '--source-dir', sources, '--output-dir', output,
                     '--catalog-root', tmp_path/'library')
    assert result.returncode == 0, result.stderr
    manifest = json.loads((output/'manifest.json').read_text())
    assert manifest['template_count'] == 38
    for name, digest in manifest['files'].items():
        assert hashlib.sha256((output/name).read_bytes()).hexdigest() == digest
    models = list(output.glob('templates/*/template.json'))
    assert len(models) == 38
    assert {json.loads(p.read_text())['type'] for p in models} == BASIC_TYPES
    for path in models:
        model = validate_template(json.loads(path.read_text()))
        assert model['evidence']['level'] == 'teaching_rule_candidate'
        assert model['evidence']['physical_validation'] is False
        assert model['teaching']['review_status'] == 'unreviewed'
        assert model['teaching']['coordinate_source'] == 'manually_authored_rule_based_curves'
        assert model['teaching']['events']
        assert all(d['visible_width_samples']==0 for d in model['prototype']['descriptors'])
        assert (path.parent/'source_illustration.bin').read_bytes() == (sources/model['teaching']['recipe']['illustration']['filename']).read_bytes()
        from brushbot.stroke_templates import adapt_stroke
        reference=model['references'][0]
        adapted=adapt_stroke(model,reference['xy_px'],reference['anchors'],width_px=reference['width_px'],landmarks=reference['landmarks'])
        assert adapted['s'][0] == 0 and adapted['s'][-1] == 1
    assert (tmp_path/'library/index.html').is_file()
    before = (output/'manifest.json').read_bytes()
    assert command('teaching', '--recipes', recipes_path, '--source-dir', sources, '--output-dir', output).returncode != 0
    assert (output/'manifest.json').read_bytes() == before


def test_bad_source_checksum_is_rejected_before_any_library_is_published(tmp_path):
    from brushbot.stroke_templates.teaching import generate_library
    config, sources = source_fixture(tmp_path)
    (sources/config['strokes'][0]['illustration']['filename']).write_bytes(b'changed')
    with pytest.raises(ValueError, match='checksum'):
        generate_library(config, sources, tmp_path/'output')
    assert not (tmp_path/'output').exists()


@pytest.mark.parametrize('current,expected', [(1.2,[.96,1.44]), (1.6,[1.28]), (.5,[.6])])
def test_length_comparisons_are_relative_to_the_current_recipe_and_stay_in_range(tmp_path,current,expected):
    from brushbot.stroke_templates.teaching import generate_library
    config,sources=source_fixture(tmp_path)
    recipe=next(r for r in config['strokes'] if r['type']=='hengzhegou')
    recipe['parameters']={'body_scales':{'horizontal':current}}
    config['strokes']=[recipe]
    generate_library(config,sources,tmp_path/'library')
    report=next((tmp_path/'library').glob('templates/*/report.html')).read_text()
    payload=json.loads(re.search(r'<script id="teaching-data" type="application/json">(.*?)</script>',report,re.S)[1])
    horizontal=[v for v in payload['variants'] if v['id'].startswith('horizontal_')]
    assert [v['recipe']['parameters']['body_scales']['horizontal'] for v in horizontal] == pytest.approx(expected)
    assert payload['variants'][0]['recipe']['parameters']['body_scales']['horizontal'] == current
    assert '1 类基本笔画' in (tmp_path/'library/index.html').read_text()


def test_new_writing_variants_keep_their_distinct_direction_and_finish():
    from brushbot.stroke_templates.teaching import generate_stroke
    from brushbot.stroke_templates.teaching_recipes import default_config
    strokes={r['id']:generate_stroke(r) for r in default_config()['strokes']}
    assert strokes['heng_long']['xy'][-1][0]>strokes['heng_short']['xy'][-1][0]
    assert strokes['shu_chuilu']['relative_width'][-1]>.5
    assert strokes['shu_xuanzhen']['relative_width'][-1]==0
    assert strokes['dian_left']['xy'][-1][0]<0
    assert strokes['dian_right']['xy'][-1][0]>0
    flat,slant=strokes['pie_short_flat']['xy'][-1],strokes['pie_short_slant']['xy'][-1]
    assert abs(flat[1]/flat[0])<abs(slant[1]/slant[0])
    compound=strokes['hengzhezhezhegou']
    assert [p['name'] for p in compound['landmarks']]==['turn_1','turn_2','turn_3','hook']


def test_multiturn_stroke_can_change_its_second_horizontal_without_deforming_turns():
    from brushbot.stroke_templates.teaching import generate_stroke
    from brushbot.stroke_templates.teaching_recipes import default_config
    recipe=next(r for r in default_config()['strokes'] if r['type']=='hengzhezhezhegou')
    original=generate_stroke(recipe)
    changed=generate_stroke(recipe,body_scales={'horizontal_2':1.4})
    for first,second in zip(original['parts'],changed['parts']):
        a=np.asarray(original['xy'])[first['first']:first['last']+1]
        b=np.asarray(changed['xy'])[second['first']:second['last']+1]
        if first['id']=='horizontal_2':
            assert np.linalg.norm(b[-1]-b[0])==pytest.approx(1.4*np.linalg.norm(a[-1]-a[0]))
        else:
            assert b-b[0]==pytest.approx(a-a[0])


def test_unit_mistake_in_editable_controls_is_rejected_before_raster_allocation(tmp_path,monkeypatch):
    from brushbot.stroke_templates.teaching import generate_library
    config,sources=source_fixture(tmp_path)
    config['strokes']=config['strokes'][:1]
    for part in config['strokes'][0]['parts']:
        part['controls']=(np.asarray(part['controls'])*1000).tolist()
    original=Image.new
    def bounded_image(mode,size,*args,**kwargs):
        assert int(size[0])*int(size[1])<=40_000_000,'unsafe raster allocation attempted'
        return original(mode,size,*args,**kwargs)
    monkeypatch.setattr(Image,'new',bounded_image)
    with pytest.raises(ValueError,match='render.*size'):
        generate_library(config,sources,tmp_path/'library')
    assert not (tmp_path/'library').exists()


def test_confirming_reconstruction_does_not_upgrade_it_to_observed_calligraphy(tmp_path):
    from brushbot.stroke_templates import build_template
    from brushbot.stroke_templates.teaching import generate_library
    config, sources = source_fixture(tmp_path)
    generate_library(config, sources, tmp_path/'library')
    model = json.loads(next((tmp_path/'library').glob('templates/*/template.json')).read_text())
    reference = copy.deepcopy(model['references'][0]); reference['review_status']='confirmed'
    rebuilt = build_template([reference], stroke_type=model['type'], variant=model['variant'])
    assert rebuilt['evidence']['level'] == 'teaching_rule_candidate'
    broken = copy.deepcopy(model); broken['teaching']['relative_width'][0] = -1
    broken['template_id'] = identity(broken, 'template_id')
    with pytest.raises(ValueError, match='width'):
        validate_template(broken)


@pytest.mark.parametrize('change', ['negative_index','wrong_progress','scalar_xy'])
def test_invalid_teaching_event_mapping_is_rejected(tmp_path, change):
    from brushbot.stroke_templates.teaching import generate_library
    config, sources=source_fixture(tmp_path)
    config['strokes']=config['strokes'][:1]
    generate_library(config,sources,tmp_path/'library')
    model=json.loads(next((tmp_path/'library').glob('templates/*/template.json')).read_text())
    event=model['teaching']['events'][0]
    if change=='negative_index':
        event.update(index=-1,xy=model['prototype']['xy'][-1])
    elif change=='wrong_progress':
        event['s']=.5
    else:
        event['xy']=event['xy'][0]
    model['template_id']=identity(model,'template_id')
    with pytest.raises(ValueError,match='event'):
        validate_template(model)
