"""CLI fixtures exercise an actual portable report and actionable failures."""
import json
import os
from pathlib import Path
import subprocess
import sys

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args):
    return subprocess.run([sys.executable, str(ROOT/'scripts/extract_character_xy.py'), *map(str, args)],
        cwd=ROOT, env={**os.environ, 'PYTHONPATH': str(ROOT/'src'), 'MPLBACKEND': 'Agg'},
        text=True, capture_output=True)


def test_cli_creates_self_contained_report_with_selection_and_layers(tmp_path):
    source = tmp_path/'glyph <script>.png'
    image = Image.new('RGB', (61, 61), 'white')
    draw = ImageDraw.Draw(image)
    draw.line([(8, 30), (52, 30)], fill='black')
    draw.line([(30, 8), (30, 52)], fill='black')
    image.save(source)
    output = tmp_path/'geometry'
    result = run_cli('--image', source, '--output-dir', output,
                     '--source-url', 'https://example.org/</script><script>alert(1)</script>')
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary['units'] == 'px'
    assert summary['statistics']['path_segment_count'] == 4
    assert Path(summary['report_html']).is_file()
    report = (output/'report.html').read_text()
    assert 'data:image/png;base64,' in report
    assert 'data-path-id="p0000"' in report
    assert 'id="show-image"' in report and 'id="show-nodes"' in report
    assert 'wheel' in report and 'pointerdown' in report
    assert '<script>alert(1)</script>' not in report
    assert 'glyph <script>.png' not in report
    assert '<script src=' not in report and '<link rel="stylesheet"' not in report
    assert not {'t', 'g_target', 'z_ff'} & json.loads((output/'geometry.json').read_text()).keys()
    second = run_cli('--image', source, '--output-dir', output)
    assert second.returncode != 0 and 'exist' in second.stderr


def test_cli_rejects_invalid_scale_and_does_not_publish(tmp_path):
    source = tmp_path/'blank.png'
    Image.new('L', (30, 30), 255).save(source)
    output = tmp_path/'invalid'
    result = run_cli('--image', source, '--output-dir', output, '--mm-per-pixel', 'nan')
    assert result.returncode != 0
    assert 'finite' in result.stderr
    assert not output.exists()
