"""Owned temporary Chrome sessions for optional UI regression tests."""
from contextlib import contextmanager
import json
import shutil
import subprocess
import time
import urllib.request

import pytest


@contextmanager
def browser_page(directory, page_path, *, ready_selector='#canvas polyline'):
    chrome = shutil.which('google-chrome') or shutil.which('chromium')
    if not chrome:
        pytest.skip('optional browser regression requires Chrome')
    websocket = pytest.importorskip('websocket')
    profile = directory/'profile'
    downloads = directory/'downloads'; downloads.mkdir(parents=True)
    ws = None
    with (directory/'chrome.log').open('w') as log:
        process = subprocess.Popen([chrome, '--headless=new', '--no-sandbox', '--disable-gpu',
            '--disable-dev-shm-usage', '--remote-debugging-port=0', '--remote-allow-origins=*',
            '--user-data-dir='+str(profile), 'about:blank'], stdout=log, stderr=log)
        try:
            portfile = profile/'DevToolsActivePort'
            for _ in range(200):
                if portfile.exists():
                    break
                assert process.poll() is None, 'Chrome exited before initialization'
                time.sleep(.05)
            assert portfile.exists()
            port = int(portfile.read_text().splitlines()[0])
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/json', timeout=5) as response:
                tab = next(t for t in json.load(response) if t['type'] == 'page')
            ws = websocket.create_connection(tab['webSocketDebuggerUrl'], timeout=10, suppress_origin=True)
            sequence, errors = 0, []
            def cdp(method, params=None):
                nonlocal sequence
                sequence += 1; request = sequence
                ws.send(json.dumps(dict(id=request, method=method, params=params or {})))
                while True:
                    message = json.loads(ws.recv())
                    if message.get('method') == 'Runtime.exceptionThrown':
                        errors.append(message)
                    if message.get('id') == request:
                        assert 'error' not in message, message
                        return message.get('result', {})
            def js(expression):
                result = cdp('Runtime.evaluate', dict(expression=expression, returnByValue=True, awaitPromise=True))
                assert 'exceptionDetails' not in result, result
                return result['result'].get('value')
            cdp('Page.enable'); cdp('Runtime.enable')
            cdp('Browser.setDownloadBehavior', dict(behavior='allow', downloadPath=str(downloads)))
            cdp('Emulation.setDeviceMetricsOverride', dict(width=1280, height=1024, deviceScaleFactor=1, mobile=False))
            cdp('Page.navigate', dict(url=page_path.as_uri()))
            for _ in range(100):
                if js("document.readyState==='complete' && document.querySelectorAll("+json.dumps(ready_selector)+").length>0"):
                    break
                time.sleep(.05)
            yield cdp, js, downloads
            assert not errors, errors
        finally:
            if ws is not None:
                ws.close()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
