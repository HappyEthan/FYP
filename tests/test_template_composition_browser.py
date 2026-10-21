"""The library's composed Yong must show generated paths and reveal its five sources."""
import csv
import time

from tests.quick_browser_helper import browser_page
from tests.test_stroke_template_cli import command
from tests.test_template_character_composition import composition_fixture


def test_latest_yong_opens_as_template_composition_with_layout_toggle_and_source_links(tmp_path):
    root, recipe, _, _ = composition_fixture(tmp_path)
    output = root/'characters/composed'
    result = command('compose', '--recipe', recipe, '--output-dir', output, '--catalog-root', root)
    assert result.returncode == 0, result.stderr
    with browser_page(tmp_path/'browser', root/'index.html', ready_selector='#catalogGrid polyline') as (cdp, js, downloads):
        js("document.querySelector('[data-tab=\"characters\"]').click()")
        assert js("document.querySelectorAll('.assetCard').length") == 1
        assert js("document.querySelector('.assetCard').textContent.includes('笔画模板合成')")
        assert js("document.querySelectorAll('.assetCard image').length") == 0
        js("document.querySelector('.openAsset').click()")
        for _ in range(100):
            if js("document.querySelectorAll('.strokeButton').length===5"):
                break
            time.sleep(.02)
        assert js("document.getElementById('compositionInfo').hidden") is False
        assert js("document.getElementById('imageLayer').checked") is False
        assert js("document.querySelectorAll('#canvas image').length") == 0
        js("document.getElementById('imageLayer').click()")
        assert js("document.querySelectorAll('#canvas image').length") == 1
        js("document.getElementById('csv').click()")
        for _ in range(100):
            files = list(downloads.glob('*.csv'))
            if files:
                break
            time.sleep(.03)
        assert files
        rows = list(csv.DictReader(files[0].read_text().splitlines()))
        assert sorted({r['stroke_id'] for r in rows}) == ['s01','s02','s03','s04','s05']
        js("document.getElementById('compositionDetails').click()")
        for _ in range(100):
            if js("document.querySelectorAll('.templateSource').length===5"):
                break
            time.sleep(.02)
        assert js("document.querySelectorAll('.templateSource').length") == 5
        assert js("[...document.querySelectorAll('.templateSource')].every(a=>a.href.includes('/composed/')&&a.href.endsWith('/report.html'))")
        assert js("document.documentElement.scrollWidth<=innerWidth")
