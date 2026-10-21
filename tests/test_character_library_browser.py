"""Curated character browsing must order real compositions and retain old examples."""
from pathlib import Path

from brushbot.stroke_templates.annotations import load_font_record,prepare_annotation
from brushbot.stroke_templates.bundle import build_bundle,fit_bundle,read_json,write_json
from brushbot.stroke_templates.composition import compose_character
from brushbot.stroke_templates.examples import _render_font
from brushbot.stroke_templates.schema import validate_annotation
from tests.quick_browser_helper import browser_page
from tests.test_stroke_template_cli import command,fixture
from tests.test_template_character_composition import composition_fixture


ROOT=Path(__file__).resolve().parents[1]


def test_character_library_defaults_to_compositions_in_practice_order_without_removing_history(tmp_path):
    root,path,recipe,legacy=composition_fixture(tmp_path)
    line_input=tmp_path/'line';line_input.mkdir()
    image,ann_path,annotation=fixture(line_input)
    annotation=validate_annotation(annotation)
    write_json(ann_path,annotation)
    model=build_bundle([(annotation,image,'s01')],root/'strokes/line',style_id='test_line')['template']
    line_recipe=dict(schema_version=1,role='template_character_recipe',character='一',
        layout=dict(annotation=str(ann_path),image=str(image),annotation_id=annotation['annotation_id'],
                    source_sha256=annotation['source_sha256']),
        strokes=[dict(stroke_id='s01',template=str(root/'strokes/line'),template_id=model['template_id'])])
    # Publish Yong last: modification time alone would put it before the simpler character.
    compose_character(line_recipe,tmp_path,root/'characters/line')
    compose_character(recipe,path.parent,root/'characters/yong')
    soil=tmp_path/'soil.png';record=load_font_record('土',ROOT/'data/makemeahanzi/graphics.txt')
    transform=_render_font(record,soil,300)
    prior=prepare_annotation(soil,'土',font_record=record,font_transform=transform,image_kind='font_fixture')
    for stroke in prior['strokes']:stroke['path_mode']='preserve'
    fit_bundle(prior,soil,[],root/'characters/old_soil')
    history=(legacy/'manifest.json').read_bytes()
    write_json(root/'catalog_settings.json',dict(schema_version=1,role='stroke_template_catalog_settings',
        character_order=['一','永']))
    result=command('catalog','--root',root)
    assert result.returncode==0,result.stderr
    with browser_page(tmp_path/'browser',root/'index.html',ready_selector='#catalogGrid polyline') as(_,js,_):
        assert js("document.querySelector('[data-tab].active').dataset.tab")=='templates'
        js("document.querySelector('[data-tab=characters]').click()")
        assert js("[...document.querySelectorAll('.assetCard h2')].map(n=>n.textContent)")==['一','永']
        assert js("document.getElementById('characterSource').value")=='composition'
        assert js("document.querySelector('.assetCard').textContent.includes('练习 1')")
        js("document.getElementById('characterSource').value='all';document.getElementById('characterSource').dispatchEvent(new Event('change'))")
        assert js("[...document.querySelectorAll('.assetCard h2')].map(n=>n.textContent)")==['一','永','土']
        js("document.getElementById('allVersions').click()")
        assert js("document.querySelectorAll('.assetCard').length")==4
        js("document.querySelector('[data-tab=templates]').click()")
        assert js("document.getElementById('characterSource').hidden") is True
    assert (legacy/'manifest.json').read_bytes()==history
