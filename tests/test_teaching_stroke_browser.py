"""Real offline checks of the new library, event navigation and recipe reuse."""
import csv
import json
import time

import pytest

from brushbot.stroke_templates.bundle import build_bundle
from tests.quick_browser_helper import browser_page
from tests.test_teaching_stroke_library import source_fixture
from tests.test_stroke_template_cli import command, fixture


def test_new_library_filter_and_inspection_export_form_a_reusable_recipe(tmp_path):
    config,sources=source_fixture(tmp_path)
    recipes=tmp_path/'recipes.json';recipes.write_text(json.dumps(config,ensure_ascii=False))
    root=tmp_path/'library'
    image,_,annotation=fixture(tmp_path)
    build_bundle([(annotation,image,'s01')],root/'old_heng',style_id='old_style')
    output=root/'strokes/new'
    result=command('teaching','--recipes',recipes,'--source-dir',sources,'--output-dir',output,'--catalog-root',root)
    assert result.returncode==0,result.stderr
    with browser_page(tmp_path/'browser',root/'index.html',ready_selector='#catalogGrid polyline') as (cdp,js,downloads):
        js("document.querySelector('[data-tab=\"templates\"]').click()")
        assert js("document.getElementById('templateSource').value")=='teaching'
        assert js("document.querySelectorAll('.assetCard').length")==38
        js("document.getElementById('templateSource').value='all';document.getElementById('templateSource').dispatchEvent(new Event('change'))")
        assert js("document.querySelectorAll('.assetCard').length")==39
        cdp('Page.navigate',dict(url=(output/'templates/hengzhegou/report.html').as_uri()))
        for _ in range(100):
            if js("document.getElementById('variation')!==null"):
                break
            time.sleep(.02)
        assert js("document.querySelectorAll('#eventList button').length")>=5
        js("document.querySelectorAll('#eventList button')[2].click()")
        assert '折转' in js("document.getElementById('readout').textContent")
        js("document.getElementById('reviewed').click()")
        assert js("document.getElementById('reviewed').checked")
        js("document.getElementById('variation').value='2';document.getElementById('variation').dispatchEvent(new Event('change'))")
        assert not js("document.getElementById('reviewed').checked")
        js("document.getElementById('reviewed').click();document.getElementById('exportRecipe').click();document.getElementById('exportCsv').click()")
        for _ in range(100):
            exported=list(downloads.glob('*.json'));csv_paths=list(downloads.glob('*.csv'))
            if exported and csv_paths:
                break
            time.sleep(.03)
        assert exported and csv_paths
        saved=json.loads(exported[0].read_text())
        assert saved['strokes'][0]['parameters']['body_scales']=={'horizontal':1.2}
        assert saved['strokes'][0]['review_status']=='confirmed'
        rows=list(csv.DictReader(csv_paths[0].read_text().splitlines()))
        assert float(rows[-1]['x_reference_width'])==pytest.approx(4.6)
        assert float(rows[-1]['y_reference_width'])==pytest.approx(-10.18)
        result=command('teaching','--recipes',exported[0],'--source-dir',sources,'--output-dir',tmp_path/'rebuilt')
        assert result.returncode==0,result.stderr
        model=json.loads((tmp_path/'rebuilt/templates/hengzhegou/template.json').read_text())
        assert model['teaching']['review_status']=='confirmed'
        assert model['evidence']['level']=='teaching_rule_candidate'
