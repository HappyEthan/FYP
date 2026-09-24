import json
import os
from pathlib import Path
import subprocess
import sys
import numpy as np
import pytest
from tests.test_target_feedforward import settings, table

ROOT=Path(__file__).resolve().parents[1]


def cli(script,*args):
    return subprocess.run([sys.executable,str(ROOT/'scripts'/script),*map(str,args)],
        cwd=ROOT,env=dict(os.environ,PYTHONPATH=str(ROOT/'src'),MPLCONFIGDIR='/tmp/fyp-mpl'),
        capture_output=True,text=True)


def test_builder_equal_weights_and_separate_settings(tmp_path):
    from scripts.build_feedforward_table import build
    folders=[]
    for run,offset in [('a',0),('b',10)]:
        folder=tmp_path/run; folder.mkdir(); folders.append(folder)
        for name,obj in [('setup',settings()),('manifest',dict(run_id=run,status='completed')),
                         ('resolved',dict(path=dict(axis='+x',travel_mm=200),motion=dict(speed_mm_s=10)))]:
            (folder/f'{name}.json').write_text(json.dumps(obj))
        rows=[dict(phase=f'measure_{i:02}',x_cmd_m=float(x),z_cmd_m=z,a_control_uT=a+offset,sample_age_s=.01)
              for i,z,a in [(0,.0295,20),(1,.027125,40),(2,.02475,80)]
              for x in np.linspace(-.2,0,201 if run=='a' else 401)]
        (folder/'control.jsonl').write_text('\n'.join(map(json.dumps,rows)))
    t,s=build(folders)
    assert t['amplitude_uT']==[25.,45.,85.]
    assert t['approved'] is False and s['verified'] is False
    assert 'setup' not in t and 'reference_table' not in s
    with pytest.raises(ValueError): build(folders+folders[:1])
    wrong=settings(); wrong['installation_id']='wrong'
    (folders[1]/'setup.json').write_text(json.dumps(wrong))
    with pytest.raises(ValueError): build(folders)


def test_v3_cli_requires_independent_inputs_and_blocks_candidate_execute(tmp_path):
    from scripts.generate_strokeplan import generate
    p=tmp_path/'p.npz'; generate(targets_uT=[30.]).save(p)
    no=cli('run_feedforward_strokeplan.py',p)
    assert no.returncode != 0 and '--feedforward' in no.stderr
    tf=tmp_path/'ff.json'; tf.write_text(json.dumps(table()))
    sf=tmp_path/'settings.json'; sf.write_text(json.dumps(settings()))
    preview=tmp_path/'trajectory.csv'
    ok=cli('run_feedforward_strokeplan.py',p,'--feedforward',tf,'--settings',sf,'--preview',preview)
    assert ok.returncode==0,ok.stderr
    report=json.loads(preview.with_suffix('.json').read_text())
    assert report['inputs']['plan']['sha256'] and report['calibration_id']=='fixture'
    assert report['execution_approved'] is False
    no=cli('run_feedforward_strokeplan.py',p,'--feedforward',tf,'--settings',sf,'--execute')
    assert no.returncode!=0 and 'approval' in no.stderr
    # Must reject BEFORE confirmation/input/hardware imports, even with --execute.
    assert 'EOFError' not in no.stderr and 'huayan_robot' not in no.stderr


def test_suite_produces_only_v3_targets(tmp_path):
    from brushbot.target_strokeplan import StrokePlan
    out=tmp_path/'suite'
    r=cli('generate_strokeplan_suite.py','--output-dir',out)
    assert r.returncode==0,r.stderr
    files=list(out.glob('*.npz'))
    assert len(files)==4
    for file in files:
        p=StrokePlan.load(file)
        assert p.meta['source']=='synthetic'
        assert not hasattr(p.strokes[0],'z_ff')
    assert (out/'profiles.png').exists()
    again=cli('generate_strokeplan_suite.py','--output-dir',out)
    assert again.returncode!=0
