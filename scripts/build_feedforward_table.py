#!/usr/bin/env python3
"""Build independent candidate Ry15 feedforward and suggested site settings. Offline."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from brushbot.feedforward import CONTEXT_KEYS, validate_table
if __package__:
    from .generate_measured_strokeplan import DEFAULT_RUNS, ROOT, extract_reference
else:
    from generate_measured_strokeplan import DEFAULT_RUNS, ROOT, extract_reference

OUTPUT_DIR=ROOT/'runs/plans/ry15_feedforward_v1'


def build(run_dirs):
    dirs=[Path(p) for p in run_dirs]
    if len(set(p.resolve() for p in dirs))!=len(dirs):
        raise ValueError('duplicate source runs')
    setup,passes,zs,amplitudes=extract_reference(dirs)
    # Legacy extraction remains usable for old fixtures; the new builder is strict.
    try:
        context={k:setup[k] for k in CONTEXT_KEYS}
        for folder in dirs:
            current=json.loads((folder/'setup.json').read_text())
            for key in CONTEXT_KEYS:
                if key=='vertical_rpy_rad':
                    match=np.allclose(context[key],current[key],atol=np.deg2rad(.1),rtol=0)
                else:
                    match=context[key]==current[key]
                if not match:
                    raise ValueError(f'incompatible source context: {key}')
    except KeyError as exc:
        raise ValueError(f'missing calibration context: {exc}') from exc
    table=dict(version=1,feature='filtered_dBxy_norm_uT',approved=False,
        transient_approved=False,context=context,directions=['+x'],speed_mm_s=10.,
        amplitude_uT=amplitudes.tolist(),depth_mm=(setup['contact_z_mm']-np.array(zs)).tolist(),
        passes=passes,stable_window_mm=[30,170],source_runs=[str(p.resolve()) for p in dirs])
    table['calibration_id']='ladder-'+hashlib.sha256(json.dumps(table,sort_keys=True).encode()).hexdigest()[:16]
    validate_table(table)
    settings=dict(setup,verified=False,
        provenance='Suggested from historical run; verify current installation and clearance before execution')
    return table,settings


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs',nargs='+',type=Path,default=DEFAULT_RUNS)
    parser.add_argument('--output-dir',type=Path,default=OUTPUT_DIR)
    args=parser.parse_args()
    table,settings=build(args.runs)
    args.output_dir.mkdir(parents=True,exist_ok=False)
    for name,value in [('feedforward.json',table),('settings.json',settings)]:
        with (args.output_dir/name).open('x') as f:
            json.dump(value,f,indent=2,ensure_ascii=False,allow_nan=False)
            f.write('\n')
    print('Saved independent candidate table and UNVERIFIED settings:',args.output_dir)
    print('No robot connected. Calibration approval and site verification remain required.')


if __name__=='__main__': main()
