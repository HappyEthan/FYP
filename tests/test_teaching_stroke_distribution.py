"""The default recipe collection must work outside the repository checkout."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


def test_built_wheel_can_load_all_recipes_without_the_source_checkout(tmp_path):
    root=Path(__file__).resolve().parents[1]
    project=tmp_path/'project';project.mkdir()
    shutil.copyfile(root/'pyproject.toml',project/'pyproject.toml')
    shutil.copytree(root/'src/brushbot',project/'src/brushbot',ignore=shutil.ignore_patterns('__pycache__'))
    result=subprocess.run([sys.executable,'-m','pip','wheel','--no-deps','--no-build-isolation',
        '--no-index','--wheel-dir',str(tmp_path/'dist'),str(project)],capture_output=True,text=True,timeout=90)
    assert result.returncode==0,result.stdout+result.stderr
    installed=tmp_path/'installed'
    with zipfile.ZipFile(next((tmp_path/'dist').glob('brushbot-*.whl'))) as wheel:
        wheel.extractall(installed)
    environment=dict(os.environ,PYTHONPATH=str(installed))
    result=subprocess.run([sys.executable,'-c',
        'from brushbot.stroke_templates.teaching_recipes import default_config; c=default_config(); '
        'print(len(c["strokes"]),len({r["type"] for r in c["strokes"]}))'],
        cwd=tmp_path,env=environment,capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
    assert result.stdout.strip()=='38 28'
