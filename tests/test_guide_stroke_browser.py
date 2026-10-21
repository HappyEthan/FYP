"""Latest traced strokes must be discoverable and inspectable from the fixed home."""
import csv
import time

from brushbot.stroke_templates.teaching import generate_library
from tests.quick_browser_helper import browser_page
from tests.test_guide_stroke_templates import review_fixture
from tests.test_teaching_stroke_library import source_fixture
from tests.test_stroke_template_cli import command


def test_import_replaces_latest_heng_cards_and_preserves_common_preview_scale(tmp_path):
    config, sources = source_fixture(tmp_path)
    config['strokes'] = [s for s in config['strokes'] if s['type']=='heng']
    root = tmp_path/'library'
    generate_library(config, sources, root/'strokes/authored')
    review = review_fixture(tmp_path)
    result = command('import-guides', '--review-dir', review, '--output-dir', root/'strokes/traced',
                     '--catalog-root', root)
    assert result.returncode == 0, result.stderr
    with browser_page(tmp_path/'browser', root/'index.html', ready_selector='#catalogGrid polyline') as (cdp, js, downloads):
        assert js("[...document.querySelectorAll('.assetCard h2')].map(e=>e.textContent)") == ['长横','短横']
        assert js("[...document.querySelectorAll('.openAsset')].every(e=>e.href.includes('/traced/'))")
        spans = js("[...document.querySelectorAll('.preview')].map(e=>e.getBBox().width/e.viewBox.baseVal.width)")
        assert spans[0] > spans[1]*1.4
        js("document.getElementById('allVersions').click()")
        assert js("document.querySelectorAll('.assetCard').length") == 4
        js("document.getElementById('allVersions').click();document.querySelector('.openAsset').click()")
        for _ in range(100):
            if js("document.getElementById('progress')!==null"):
                break
            time.sleep(.02)
        assert js("document.title.includes('长横')")
        assert js("document.querySelectorAll('#canvas .phase').length") == 3
        assert js("document.querySelectorAll('#head .phase').length") == 3
        assert js("document.querySelector('#canvas').getAttribute('viewBox')") == '10 20 100 55'
        js("document.getElementById('showSource').click()")
        assert js("document.querySelector('#canvas image').getAttribute('visibility')") == 'hidden'
        js("document.getElementById('showRaw').click()")
        assert js("document.querySelector('#canvas .raw').getAttribute('visibility')") == 'visible'
        js("document.getElementById('progress').value='1';document.getElementById('progress').dispatchEvent(new Event('input'))")
        assert js("document.getElementById('readout').textContent.includes('s=1.000')")
        js("document.getElementById('downloadCsv').click()")
        for _ in range(100):
            csv_paths = list(downloads.glob('*.csv'))
            if csv_paths:
                break
            time.sleep(.03)
        assert csv_paths
        assert csv_paths[0].name == 'heng_long_xy.csv'
        rows = list(csv.DictReader(csv_paths[0].read_text().splitlines()))
        assert float(rows[-1]['x_px']) == 97
        assert float(rows[-1]['y_px']) == 54.9
        cdp('Page.navigate', dict(url=(root/'strokes/traced/templates/heng_short/report.html').as_uri()))
        for _ in range(100):
            if js("document.title.includes('短横')"):
                break
            time.sleep(.02)
        js("document.getElementById('downloadCsv').click()")
        for _ in range(100):
            if (downloads/'heng_short_xy.csv').exists():
                break
            time.sleep(.03)
        assert sorted(p.name for p in downloads.glob('*.csv')) == ['heng_long_xy.csv', 'heng_short_xy.csv']
        assert js("document.documentElement.scrollWidth<=innerWidth")


def test_outline_guide_explains_that_its_width_is_a_manual_normalization_hint(tmp_path):
    from tests.test_guide_stroke_library import compound_review
    directory = compound_review(tmp_path)
    output = tmp_path/'imported'
    result = command('import-guides', '--review-dir', directory, '--output-dir', output)
    assert result.returncode == 0, result.stderr
    with browser_page(tmp_path/'browser', output/'templates/hengpie/report.html') as (_, js, _):
        assert js("document.getElementById('widthDetail').textContent.includes('人工参考宽度')")
        assert js("document.getElementById('widthDetail').textContent.includes('归一化')")
