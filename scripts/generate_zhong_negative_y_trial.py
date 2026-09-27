#!/usr/bin/env python3
"""Point glyph up along -Y, optionally also mirroring X about the glyph centre."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np

from brushbot.target_strokeplan import StrokePlan
from brushbot.experiments.strokeplan_execution import compile_recorded_plan
from brushbot.experiments.z_identification import _check_trajectory

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'runs/brush2/plans/11_中字底横延长30mm_实测第9次'
OUTPUT = ROOT/'runs/brush2/plans/12_中字朝负Y_正X为右'
MIRRORED_OUTPUT = ROOT/'runs/brush2/plans/12_中字朝负Y_负X为右'


def generate(output=OUTPUT, *, source=SOURCE, mirror_x=False):
    source, output = Path(source), Path(output)
    if output.exists():
        raise FileExistsError(f'refusing to replace trial: {output}')
    original = StrokePlan.load(source/'character.npz')
    if original.meta.get('coordinate_frame') != 'paper' or original.meta.get('glyph_y_axis') != 'up':
        raise ValueError('expected a paper-coordinate source with positive Y pointing up')
    plan = copy.deepcopy(original)
    center_x_m = float(original.meta['glyph_center_paper_mm'][0])/1000.
    for st in plan.strokes:
        if st.orientation is None:
            raise ValueError('direction-following orientation is required')
        st.xy[:, 1] *= -1.
        # For Rz(h) Ry(tilt) Rz(-h), h -> -h gives (-roll, pitch, -yaw).
        # This exact reflection preserves the source smoothing and timing.
        st.orientation[:, [0, 2]] *= -1.
        if mirror_x:
            st.xy[:, 0] = 2.*center_x_m-st.xy[:, 0]
            # Reflecting X changes heading h -> pi-h: (Rx, -Ry, -Rz).
            st.orientation[:, [1, 2]] *= -1.
    plan.meta.update(
        source_target_sha256=hashlib.sha256((source/'character.npz').read_bytes()).hexdigest(),
        glyph_y_axis='down',
        xy_source=('V11 rotated 180 degrees about the glyph centre; glyph up points to base -Y; glyph right points to base -X'
                   if mirror_x else 'V11 reflected about paper Y=0; X unchanged; glyph up points to base -Y'),
        orientation_source=('V11 tangent-following tilt with heading h -> h+pi; RPY -> (-Rx, -Ry, Rz)'
                            if mirror_x else 'V11 tangent-following tilt reflected with heading h -> -h; RPY -> (-Rx, Ry, -Rz)'),
        coordinate_transform={'paper_xy_matrix': [[-1. if mirror_x else 1., 0.], [0., -1.]],
                              'paper_xy_translation_m': [2.*center_x_m if mirror_x else 0., 0.],
                              'glyph_up_base_xy': [0., -1.],
                              'glyph_right_base_xy': [-1. if mirror_x else 1., 0.]},
    )
    names = ('feedforward.json', 'settings.json', 'pi_profile.json', 'entry_profile.json')
    table, setup, pi, entry = [json.loads((source/name).read_text()) for name in names]
    compiled = compile_recorded_plan(plan, table, setup, label='zhong_negative_y_up_pi',
                                    control_mode='pi', feedback_profile=pi, entry_profile=entry)
    limits = _check_trajectory(compiled['pose_m_rad'], setup, entry)
    offset = np.array([setup['origin_x_mm'], setup['origin_y_mm']])
    report = dict(
        character='中', source_dir=str(source), source_target_sha256=plan.meta['source_target_sha256'],
        transformation=('reflect both X and Y about glyph centre' if mirror_x else
                        'base X unchanged; base Y new = 2 * origin_y_mm - base Y old'),
        reflection_base_y_mm=setup['origin_y_mm'],
        reflection_base_x_mm=setup['origin_x_mm']+center_x_m*1000. if mirror_x else None,
        glyph_up='-Y', glyph_right='-X' if mirror_x else '+X',
        control=pi, entry_policy=entry, config_files_copied_unchanged=list(names),
        validation='offline compilation only; no hardware execution; inherited pose-invariant table assumption',
        duration_s=float(compiled['t_s'][-1]), compiled_limits=limits,
        strokes=[dict(index=i+1, duration_s=float(st.t[-1]),
                      start_base_xy_mm=(st.xy[0]*1000+offset).tolist(),
                      end_base_xy_mm=(st.xy[-1]*1000+offset).tolist(),
                      target_range_uT=[float(st.g_target.min()), float(st.g_target.max())])
                 for i, st in enumerate(plan.strokes)],
    )
    output.mkdir(parents=True)
    plan.save(output/'character.npz')
    StrokePlan.load(output/'character.npz')
    for i, st in enumerate(plan.strokes, 1):
        StrokePlan([st], dict(plan.meta, character_stroke_index=i)).save(output/f'stroke_{i:02}.npz')
    for name in names:
        shutil.copyfile(source/name, output/name)
    np.savez(output/'compiled_character.npz', **{k: compiled[k] for k in
             ('t_s', 's', 'phase', 'pose_m_rad', 'g_ref_uT', 'depth_ff_m')},
             artifact_role='derived_nominal_trajectory_not_feedback_commands')
    (output/'protocol.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mirror-x', action='store_true', help='also mirror X about the glyph centre')
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    output = args.output_dir or (MIRRORED_OUTPUT if args.mirror_x else OUTPUT)
    print(json.dumps(generate(output, mirror_x=args.mirror_x), ensure_ascii=False, indent=2))
