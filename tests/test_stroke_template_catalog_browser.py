"""The offline home must lead users to the correct template and character pages."""
from pathlib import Path
import shlex
import time

from brushbot.stroke_templates.bundle import build_bundle, fit_bundle, read_json
from brushbot.stroke_templates.examples import generate_yong_example
from tests.quick_browser_helper import browser_page
from tests.test_stroke_template_cli import command


ROOT = Path(__file__).resolve().parents[1]


def test_catalog_search_versions_and_links_work_offline(tmp_path):
    root = tmp_path/"library space ' $ literal"
    folder = root/'characters/永 # first'
    generate_yong_example(ROOT/'data/makemeahanzi/graphics.txt', folder, image_size=300)
    annotation = read_json(folder/'fit/annotation.json')
    for stroke in annotation['strokes']:
        stroke['path_mode'] = 'preserve'
    annotation['strokes'][0]['xy_px'][0][0] += 1
    fit_bundle(annotation, folder/'input.png', [], root/'characters/永 # revised')
    build_bundle([(annotation, folder/'input.png', 's01')], root/'strokes/unsafe text',
        style_id='<script>globalThis.catalogPwned=1</script>', allow_unreviewed=True)
    result = command('catalog', '--root', root)
    assert result.returncode == 0, result.stderr
    with browser_page(tmp_path/'browser', root/'index.html', ready_selector='#catalogGrid polyline') as (cdp, js, _):
        assert js("[...document.querySelectorAll('[data-tab]')].map(b=>b.dataset.tab)") == ['templates', 'characters']
        assert js("document.querySelector('[data-tab].active').dataset.tab") == 'templates'
        assert js("document.querySelector('#catalogGrid .assetCard h2').textContent") == '撇'
        js("document.querySelector('[data-tab=\"characters\"]').click()")
        assert js("document.querySelectorAll('#catalogGrid .assetCard').length") == 1
        assert js("document.querySelector('#catalogGrid .assetCard').textContent.includes('永')")
        assert js("typeof globalThis.catalogPwned") == 'undefined'
        assert shlex.split(js("document.getElementById('refreshCommand').textContent"))[-1] == str(root)
        js("document.getElementById('allVersions').click()")
        assert js("document.querySelectorAll('#catalogGrid .assetCard').length") == 2
        js("document.querySelector('[data-tab=\"templates\"]').click()")
        direction = js("(()=>{const card=[...document.querySelectorAll('.assetCard')].find(c=>c.querySelector('h2').textContent==='撇'),lines=card.querySelectorAll('polyline');return {first:[lines[0].points[0].x,lines[0].points[0].y],last:[lines[2].points[lines[2].points.length-1].x,lines[2].points[lines[2].points.length-1].y]}})()")
        assert direction['last'][0] < direction['first'][0]
        assert direction['last'][1] > direction['first'][1]
        js("document.getElementById('search').value='横折钩';document.getElementById('search').dispatchEvent(new Event('input'))")
        assert js("document.querySelectorAll('#catalogGrid .assetCard').length") == 1
        assert js("document.querySelectorAll('#catalogGrid polyline').length") >= 3
        js("document.querySelector('#catalogGrid .openAsset').click()")
        for _ in range(100):
            if js("document.title.includes('hengzhegou')"):
                break
            time.sleep(.02)
        assert js("document.title.includes('hengzhegou')")
        cdp('Page.navigate', dict(url=(root/'index.html').as_uri()))
        js("document.readyState")
        for _ in range(100):
            if js("document.querySelector('#catalogGrid .openAsset')!==null"):
                break
            time.sleep(.02)
        js("document.querySelector('[data-tab=\"characters\"]').click();document.querySelector('#catalogGrid .openAsset').click()")
        for _ in range(100):
            if js("document.title.includes('整字 XY')"):
                break
            time.sleep(.02)
        assert js("document.title.includes('整字 XY')")
        assert js("document.querySelectorAll('.strokeButton').length") == 5
