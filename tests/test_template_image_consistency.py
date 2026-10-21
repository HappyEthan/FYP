"""A complete in-canvas path must still reveal when it leaves the reference ink."""
import hashlib

import numpy as np
from PIL import Image,ImageDraw
import pytest

from brushbot.stroke_templates.bundle import fit_character,publish,write_json
from brushbot.stroke_templates.composition import compose_character
from brushbot.stroke_templates.geometry import build_template
from brushbot.stroke_templates.schema import validate_annotation


def geometry_for_mask(mask, *, tail_x=70):
    reference = dict(reference_id='reference', source_sha256='a'*64, type='heng', variant='standard',
        review_status='confirmed', source_kind='synthetic_fixture', width_px=2.,
        xy_px=[[0,10],[2,10],[20,10],[tail_x,10]], anchors=[0,1,2,3])
    model = build_template([reference],stroke_type='heng')
    annotation = dict(schema_version=1,role='stroke_annotation',source_sha256='b'*64,
        image_size_px=[140,40],character='一',provenance=dict(source_kind='synthetic_fixture'),
        strokes=[dict(id='s01',type='heng',variant='standard',review_status='unreviewed',
            width_hint_px=2.,xy_px=[[20,20],[22,20],[58,20],[60,20]],anchors=[0,1,2,3])])
    return fit_character(annotation,dict(mask=mask),[model])


def test_path_inside_canvas_but_outside_ink_gets_a_separate_geometry_flag():
    mask = np.zeros((40,140),bool); mask[15:26,19:62] = True
    geometry = geometry_for_mask(mask)
    stroke = geometry['strokes'][0]
    assert geometry['complete'] is True
    assert 'generated_path_outside_image' not in stroke['review_flags']
    assert 'generated_path_outside_reference_ink' in stroke['review_flags']
    consistency = stroke['image_consistency']
    # The generated line ends at x=108; reference ink plus the 1 px allowance ends at 62.5.
    assert consistency['outside_length_px'] == pytest.approx(45.5,abs=.3)
    assert consistency['outside_fraction'] > .5
    assert consistency['tolerance_px'] == 1
    assert consistency['role'] == 'reference_ink_consistency_not_calligraphy_quality'


def test_mask_check_uses_original_image_coordinates_after_mask_downsampling():
    mask = np.zeros((20,70),bool); mask[6:14,9:31] = True
    consistency = geometry_for_mask(mask)['strokes'][0]['image_consistency']
    assert consistency['outside_length_px'] == pytest.approx(45.5,abs=.3)


def test_path_wholly_inside_ink_has_no_reference_ink_warning():
    mask = np.zeros((40,140),bool); mask[15:26,19:62] = True
    stroke = geometry_for_mask(mask,tail_x=22)['strokes'][0]
    assert stroke['image_consistency']['outside_fraction'] == 0
    assert 'generated_path_outside_reference_ink' not in stroke['review_flags']


def test_ink_check_catches_excursions_between_vertices():
    mask = np.zeros((40,140),bool); mask[15:26,19:31] = True; mask[15:26,49:62] = True
    stroke = geometry_for_mask(mask,tail_x=22)['strokes'][0]
    # Every generated phase endpoint is in ink; the line crosses the 18 px interior gap.
    assert stroke['image_consistency']['outside_length_px'] == pytest.approx(16.,abs=.3)


def test_zero_threshold_rejects_a_short_outside_vertex_between_midpoint_samples(tmp_path):
    image_path = tmp_path/'input.png'
    image = Image.new('RGB',(100,100),'white')
    ImageDraw.Draw(image).rectangle((0,0,19,99),fill='black'); image.save(image_path)
    digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
    # The tolerated ink boundary is x=20.5. The tiny x=20.51 excursion falls between samples.
    xy = [[10.,50.],[20.4,50.],[20.51,50.],[10.,51.]]
    model = build_template([dict(reference_id='tiny_excursion',source_sha256=digest,
        type='heng',variant='standard',review_status='confirmed',source_kind='synthetic_fixture',
        xy_px=xy,anchors=[0,1,2,3],width_px=2.)],stroke_type='heng')
    def write_template(stage):
        write_json(stage/'template.json',model)
        (stage/'report.html').write_text('<!doctype html><title>test</title>')
        return dict(template_id=model['template_id'])
    publish(tmp_path/'model','stroke_template_bundle',write_template)
    annotation = validate_annotation(dict(schema_version=1,role='stroke_annotation',
        source_sha256=digest,image_size_px=[100,100],character='一',
        provenance=dict(source_kind='synthetic_fixture'),strokes=[dict(id='s01',type='heng',
            variant='standard',xy_px=xy,anchors=[0,1,2,3],width_hint_px=2.,review_status='unreviewed')]))
    write_json(tmp_path/'annotation.json',annotation)
    recipe = dict(schema_version=1,role='template_character_recipe',character='一',
        layout=dict(annotation='annotation.json',image='input.png',annotation_id=annotation['annotation_id'],
            source_sha256=digest),strokes=[dict(stroke_id='s01',template='model',template_id=model['template_id'])],
        image_constraint=dict(max_outside_fraction=0.))
    with pytest.raises(ValueError,match='reference ink'):
        compose_character(recipe,tmp_path,tmp_path/'output')
    assert not (tmp_path/'output').exists()
