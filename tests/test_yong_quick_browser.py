"""Local curve correction must leave every other Yong stroke byte-for-byte intact."""
import json
from pathlib import Path
import time

import numpy as np
from PIL import Image, ImageDraw

from tests.quick_browser_helper import browser_page
from brushbot.stroke_templates.bundle import fit_bundle, load_fitted_geometry, read_json
from brushbot.stroke_templates.examples import generate_yong_example


ROOT = Path(__file__).resolve().parents[1]


def test_local_drag_undo_and_direct_exports_preserve_the_other_four_strokes(tmp_path):
    generate_yong_example(ROOT/'data/makemeahanzi/graphics.txt', tmp_path/'yong', image_size=300)
    with browser_page(tmp_path/'browser', tmp_path/'yong/fit/review.html') as (cdp, js, downloads):
        assert js("document.querySelectorAll('.strokeButton').length") == 5
        assert js("document.getElementById('imageConsistency').textContent.includes('轮廓内行程')")
        before = js("JSON.parse(document.getElementById('quick-review-data').textContent).annotation")
        assert '阶段' not in js("document.querySelector('aside').textContent")
        js("document.querySelectorAll('.strokeButton')[1].click()")
        p = js("(()=>{const l=document.querySelector('polyline[data-stroke=\"1\"]');const p=l.getPointAtLength(l.getTotalLength()*.6).matrixTransform(l.getScreenCTM());return {x:p.x,y:p.y}})()")
        cdp('Input.dispatchMouseEvent', dict(type='mousePressed', **p, button='left', clickCount=1))
        cdp('Input.dispatchMouseEvent', dict(type='mouseMoved', x=p['x']+7, y=p['y']+3, buttons=1))
        cdp('Input.dispatchMouseEvent', dict(type='mouseReleased', x=p['x']+7, y=p['y']+3, button='left', clickCount=1))
        assert js("document.getElementById('summary').textContent.includes('1 笔已修改')")
        assert js("document.getElementById('imageConsistency').textContent.includes('修改后需重新核对')")
        js("document.getElementById('undo').click()")
        assert js("document.getElementById('summary').textContent.includes('0 笔已修改')")
        assert js("document.getElementById('imageConsistency').textContent.includes('轮廓内行程')")
        js("document.getElementById('redo').click();document.getElementById('save').click()")
        for _ in range(100):
            files = list(downloads.glob('*.json'))
            if files:
                break
            time.sleep(.05)
        assert files
        saved = json.loads(files[0].read_text())
        assert saved['provenance']['edited_stroke_ids'] == ['s02']
        for i in (0, 2, 3, 4):
            assert saved['strokes'][i]['xy_px'] == before['strokes'][i]['xy_px']
        a, b = np.asarray(saved['strokes'][1]['xy_px']), np.asarray(before['strokes'][1]['xy_px'])
        moved = np.linalg.norm(a-b, axis=1) > 1e-10
        assert 0 < moved.sum() < len(moved)/2
        assert all(s['review_status'] == 'confirmed' and s['path_mode'] == 'preserve' for s in saved['strokes'])
        js("document.getElementById('csv').click()")
        for _ in range(100):
            csv = list(downloads.glob('*.csv'))
            if csv:
                break
            time.sleep(.05)
        assert csv and len(csv[0].read_text().splitlines()) == 1+sum(len(s['xy_px']) for s in saved['strokes'])
        templates = read_json(tmp_path/'yong/fit/templates.json')
        fit_bundle(saved, tmp_path/'yong/input.png', templates, tmp_path/'reload')
        geometry = load_fitted_geometry(tmp_path/'reload')
        for expected, actual in zip(saved['strokes'], geometry['strokes']):
            assert actual['xy_px'] == expected['xy_px']


def test_selected_stroke_wins_at_a_crossing(tmp_path):
    import hashlib
    image = tmp_path/'cross.png'
    im = Image.new('RGB', (100, 100), 'white')
    draw = ImageDraw.Draw(im); draw.line([(15, 49), (85, 49)], fill='black', width=9)
    draw.line([(50, 15), (50, 85)], fill='black', width=9); im.save(image)
    annotation = dict(schema_version=1, role='stroke_annotation', character='十', image_size_px=[100, 100],
        source_sha256=hashlib.sha256(image.read_bytes()).hexdigest(), provenance={'source_kind': 'synthetic_fixture'},
        strokes=[dict(id='s01', type='heng', variant='standard', xy_px=[[15, 50], [25, 50], [75, 50], [85, 50]],
            anchors=[0, 1, 2, 3], path_mode='preserve', review_status='unreviewed'),
            dict(id='s02', type='shu', variant='standard', xy_px=[[50, 15], [50, 25], [50, 75], [50, 85]],
            anchors=[0, 1, 2, 3], path_mode='preserve', review_status='unreviewed')])
    fit_bundle(annotation, image, [], tmp_path/'fit')
    with browser_page(tmp_path/'browser', tmp_path/'fit/review.html') as (cdp, js, downloads):
        js("document.querySelectorAll('.strokeButton')[0].click()")
        before = js('annotation.strokes.map(s=>s.xy_px)')
        p = js("(()=>{const svg=document.getElementById('canvas'),p=svg.createSVGPoint();p.x=50;p.y=49;const q=p.matrixTransform(svg.getScreenCTM());return{x:q.x,y:q.y}})()")
        cdp('Input.dispatchMouseEvent', dict(type='mousePressed', **p, button='left', clickCount=1))
        cdp('Input.dispatchMouseEvent', dict(type='mouseMoved', x=p['x']+4, y=p['y']+2, buttons=1))
        cdp('Input.dispatchMouseEvent', dict(type='mouseReleased', x=p['x']+4, y=p['y']+2, button='left', clickCount=1))
        assert js("document.querySelector('.strokeButton.active').textContent.startsWith('1.')")
        assert js('annotation.strokes.map(s=>s.xy_px)') == before
        assert '稀疏' in js("document.getElementById('status').textContent")


def test_advanced_yong_edits_keep_named_features_on_the_same_points(tmp_path):
    from brushbot.stroke_templates.schema import validate_annotation
    generate_yong_example(ROOT/'data/makemeahanzi/graphics.txt', tmp_path/'yong', image_size=300)
    with browser_page(tmp_path/'browser', tmp_path/'yong/fit/report.html') as (cdp, js, downloads):
        js("document.getElementById('selection').value='1';document.getElementById('selection').dispatchEvent(new Event('change'))")
        original = js('structuredClone(annotation.strokes[1])')
        js("document.getElementById('insertPoint').click()")
        p = js("(()=>{const s=annotation.strokes[1],p=document.getElementById('canvas').createSVGPoint();p.x=(s.xy_px[0][0]+s.xy_px[1][0])/2;p.y=H-1-(s.xy_px[0][1]+s.xy_px[1][1])/2;const q=p.matrixTransform(svg.getScreenCTM());return{x:q.x,y:q.y}})()")
        cdp('Input.dispatchMouseEvent', dict(type='mousePressed', **p, button='left', clickCount=1))
        cdp('Input.dispatchMouseEvent', dict(type='mouseReleased', **p, button='left', clickCount=1))
        inserted = js('structuredClone(annotation.strokes[1])')
        assert len(inserted['xy_px']) == len(original['xy_px'])+1
        for old, new in zip(original['landmarks'], inserted['landmarks']):
            assert new['index'] == old['index']+1
            assert inserted['xy_px'][new['index']] == original['xy_px'][old['index']]
        js("document.getElementById('deletePoint').click()")
        assert js('annotation.strokes[1].landmarks') == original['landmarks']
        js("pointIndex=annotation.strokes[1].landmarks[0].index;draw();document.getElementById('deletePoint').click()")
        assert len(js('annotation.strokes[1].xy_px')) == len(original['xy_px'])
        assert '特征点' in js("document.getElementById('message').textContent")
        js("document.getElementById('bodyStart').click()")
        assert js('annotation.strokes[1].anchors') == original['anchors']
        js("document.getElementById('reversePath').click()")
        reversed_stroke = js('structuredClone(annotation.strokes[1])')
        for old, new in zip(reversed(original['landmarks']), reversed_stroke['landmarks']):
            assert new['index'] == len(original['xy_px'])-1-old['index']
            assert reversed_stroke['xy_px'][new['index']] == original['xy_px'][old['index']]
        js("document.getElementById('download').click()")
        for _ in range(100):
            files = list(downloads.glob('*.json'))
            if files:
                break
            time.sleep(.05)
        assert files
        validate_annotation(json.loads(files[0].read_text()))
