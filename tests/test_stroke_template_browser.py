"""Optional real-Chrome regression for edits, stale results and JSON round trips."""
import json
import shutil
import subprocess
import time
import urllib.request

import numpy as np
from PIL import Image
import pytest

from brushbot.stroke_templates.annotations import prepare_annotation
from brushbot.stroke_templates.bundle import build_bundle, fit_bundle, load_fitted_geometry


def test_report_inserts_on_existing_path_and_exports_refittable_edits(tmp_path):
    chrome = shutil.which('google-chrome') or shutil.which('chromium')
    if not chrome:
        pytest.skip('optional Chrome report verification: no browser installed')
    websocket = pytest.importorskip('websocket')
    image = tmp_path/'input.png'
    mask = np.zeros((80, 120), bool); mask[35:45, 10:110] = True
    Image.fromarray(np.where(mask, 0, 255).astype('uint8')).save(image)
    ann = prepare_annotation(image, '一', no_prior=True)
    ann['provenance']['source_kind'] = 'synthetic_fixture'
    ann['strokes'][0]['type'] = 'heng'
    template = build_bundle([(ann, image, 's01')], tmp_path/'model', style_id='synthetic_test',
                            allow_unreviewed=True)['template']
    fit_bundle(ann, image, [template], tmp_path/'fit')
    downloads = tmp_path/'downloads'; downloads.mkdir()
    profile = tmp_path/'chrome-profile'
    ws = None
    with (tmp_path/'chrome.log').open('w') as log:
        process = subprocess.Popen([chrome, '--headless=new', '--no-sandbox', '--disable-gpu',
            '--disable-dev-shm-usage', '--remote-debugging-port=0', '--remote-allow-origins=*',
            '--user-data-dir='+str(profile), 'about:blank'], stdout=log, stderr=log)
        try:
            port_file = profile/'DevToolsActivePort'
            for _ in range(200):
                if port_file.exists():
                    break
                if process.poll() is not None:
                    pytest.fail('Chrome exited before starting the report test')
                time.sleep(.05)
            assert port_file.exists(), 'Chrome did not start within 10 seconds'
            port = int(port_file.read_text().splitlines()[0])
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/json', timeout=5) as response:
                tabs = json.load(response)
            page = next(t for t in tabs if t['type'] == 'page')
            ws = websocket.create_connection(page['webSocketDebuggerUrl'], timeout=10, suppress_origin=True)
            sequence, exceptions = 0, []
            def cdp(method, params=None):
                nonlocal sequence
                sequence += 1
                request = sequence
                ws.send(json.dumps(dict(id=request, method=method, params=params or {})))
                while True:
                    reply = json.loads(ws.recv())
                    if reply.get('method') == 'Runtime.exceptionThrown':
                        exceptions.append(reply)
                    if reply.get('id') == request:
                        assert 'error' not in reply, reply
                        return reply.get('result', {})
            def js(expression):
                result = cdp('Runtime.evaluate', dict(expression=expression, returnByValue=True, awaitPromise=True))
                assert 'exceptionDetails' not in result, result
                return result['result'].get('value')
            def click(x, y):
                cdp('Input.dispatchMouseEvent', dict(type='mousePressed', x=x, y=y, button='left', clickCount=1))
                cdp('Input.dispatchMouseEvent', dict(type='mouseReleased', x=x, y=y, button='left', clickCount=1))
            cdp('Page.enable'); cdp('Runtime.enable')
            cdp('Emulation.setDeviceMetricsOverride', dict(width=1280, height=1024, deviceScaleFactor=1, mobile=False))
            cdp('Browser.setDownloadBehavior', dict(behavior='allow', downloadPath=str(downloads)))
            cdp('Page.navigate', dict(url=(tmp_path/'fit/report.html').as_uri()))
            for _ in range(100):
                if js("document.querySelectorAll('#canvas circle[data-point]').length>0"):
                    break
                time.sleep(.05)
            original_count = js("document.querySelectorAll('#canvas circle[data-point]').length")
            assert original_count == 21
            js("document.getElementById('insertPoint').click()")
            point = js("(()=>{const l=document.querySelector('#canvas polyline[stroke=\"#a95375\"]');const p=l.getPointAtLength(l.getTotalLength()*.5273).matrixTransform(l.getScreenCTM());return {x:p.x,y:p.y}})()")
            click(point['x'], point['y'])
            assert js("document.querySelectorAll('#canvas circle[data-point]').length") == 22
            assert js("document.getElementById('summary').textContent.includes('旧拟合已隐藏')")
            assert js("document.getElementById('metrics').textContent.includes('旧指标')")
            point = js("(()=>{const r=document.querySelector('circle[data-point=\"1\"]').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()")
            cdp('Input.dispatchMouseEvent', dict(type='mousePressed', **point, button='left', clickCount=1))
            cdp('Input.dispatchMouseEvent', dict(type='mouseMoved', x=point['x']+3, y=point['y']+2, buttons=1))
            cdp('Input.dispatchMouseEvent', dict(type='mouseReleased', x=point['x']+3, y=point['y']+2, button='left', clickCount=1))
            js("document.getElementById('notesInput').value='browser edit';document.getElementById('notesInput').dispatchEvent(new Event('change'));document.getElementById('confirmed').click();document.getElementById('download').click()")
            for _ in range(100):
                files = list(downloads.glob('*.json'))
                if files:
                    break
                time.sleep(.05)
            assert files, 'annotation download did not finish'
            edited = json.loads(files[0].read_text(encoding='utf-8'))
            assert len(edited['strokes'][0]['xy_px']) == 22
            assert edited['strokes'][0]['xy_px'][1] != ann['strokes'][0]['xy_px'][1]
            assert edited['strokes'][0]['review_status'] == 'confirmed'
            assert edited['strokes'][0]['notes'] == 'browser edit'
            assert 'annotation_id' not in edited
            fit_bundle(edited, image, [template], tmp_path/'refit')
            assert load_fitted_geometry(tmp_path/'refit')['annotation_id'] != load_fitted_geometry(tmp_path/'fit')['annotation_id']
            assert exceptions == []
        finally:
            if ws is not None:
                ws.close()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
