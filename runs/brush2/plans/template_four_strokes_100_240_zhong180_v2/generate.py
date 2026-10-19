#!/usr/bin/env python3
"""Preserve the four V3 targets and dilate time for the existing executor."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

from brushbot.target_strokeplan import StrokePlan
from brushbot.experiments.strokeplan_execution import compile_recorded_plan
from brushbot.experiments.z_identification import _check_trajectory

SOURCE = ROOT / 'runs/brush2/plans/template_four_strokes_100_240_zhong180_v1'
CONTEXT = ROOT / 'runs/brush2/plans/11_中字底横延长30mm_实测第9次'
PREVIEW = Path('/home/ethan/.codex/skills/brushbot-strokeplan/scripts/preview_target.py')
NAMES = dict(heng='长横', shu='悬针竖', pie='斜撇', na='斜捺')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def main():
    output = Path(__file__).resolve().parent
    if any(p.name != 'generate.py' for p in output.iterdir()):
        raise FileExistsError('refusing to replace an existing output bundle')
    table, setup, entry = [json.loads((CONTEXT / name).read_text()) for name in
                           ['feedforward.json', 'settings.json', 'entry_profile.json']]
    context_hashes = {name: sha256(CONTEXT / name) for name in
                     ['feedforward.json', 'settings.json', 'entry_profile.json']}
    prepared, report = [], dict(
        validation='offline V3 reload and existing directional executor compilation; no hardware',
        execution_context=str(CONTEXT.relative_to(ROOT)),
        execution_context_sha256=context_hashes,
        context_note='Historical brush2 settings must match the currently installed brush, TCP, paper and contact reference.',
        table_assumption='Original +X, fixed Ry15 calibration reused for other directions and tilt azimuths; experimentally unvalidated.',
        strokes=[])
    for name, label in NAMES.items():
        source_path = SOURCE / name / 'strokeplan.npz'
        original = StrokePlan.load(source_path)
        plan = copy.deepcopy(original)
        st, old = plan.strokes[0], original.strokes[0]
        assert np.allclose(np.diff(old.t), .02, atol=1e-12, rtol=0)
        padded = np.vstack([old.orientation[0], old.orientation, old.orientation[-1]])
        source_peak = float(np.linalg.norm(
            np.rad2deg(np.diff(padded, n=2, axis=0) / .02**2), axis=1).max())
        # The compiler linearly resamples orientations at 20 ms. Integer time
        # dilation reduces the velocity jumps at support points without changing
        # any geometric, magnetic or orientation support value. Validate the full
        # compiled trajectory below rather than relying on this estimate alone.
        factor = max(1, math.ceil(1.1 * source_peak / entry['angular_accel_deg_s2']))
        st.t = old.t * factor
        plan.meta.update(
            source_target_sha256=sha256(source_path),
            source_target=str(source_path.relative_to(ROOT)),
            time_source='integer time dilation of the original 20 ms supports; executor samples at 20 ms',
            postprocess_time_dilation=dict(factor=factor, original_duration_s=float(old.t[-1]),
                preserved_arrays=['s', 'xy', 'g_target', 'orientation'],
                source_recipe_describes_pre_dilation_target=True),
            validation='V3 target reload plus separate offline directional execution preflight; no hardware or width validation')
        plan.validate()
        for field in ['s', 'xy', 'g_target', 'orientation']:
            assert np.array_equal(getattr(st, field), getattr(old, field))
        compiled = compile_recorded_plan(plan, table, setup,
            label=f'template_{name}_100_240_v2', entry_profile=entry, control_mode='feedforward')
        limits = _check_trajectory(compiled['pose_m_rad'], setup, entry)
        summary = dict(id=name, name=label, time_scale=factor,
            source_plan=str(source_path.relative_to(ROOT)), source_sha256=sha256(source_path),
            source_peak_angular_acceleration_deg_s2=source_peak,
            writing_duration_s=float(st.t[-1]), full_motion_duration_s=float(compiled['t_s'][-1]),
            target_max_xy_speed_mm_s=float((np.linalg.norm(np.diff(st.xy, axis=0), axis=1)
                                            / np.diff(st.t)).max() * 1000),
            compiled_limits=limits,
            compiled_xyz_min_mm=(compiled['pose_m_rad'][:, :3].min(axis=0) * 1000).tolist(),
            compiled_xyz_max_mm=(compiled['pose_m_rad'][:, :3].max(axis=0) * 1000).tolist(),
            preserved_arrays_exactly=True,
            plan=f'{name}/strokeplan.npz')
        prepared.append((name, plan, compiled, summary))
        report['strokes'].append(summary)
    preflight = output / 'preflight'
    preflight.mkdir()
    for name, plan, compiled, summary in prepared:
        folder = output / name
        folder.mkdir()
        plan.save(folder / 'strokeplan.npz')
        loaded = StrokePlan.load(folder / 'strokeplan.npz')
        assert np.array_equal(loaded.strokes[0].t, plan.strokes[0].t)
        np.savez_compressed(preflight / f'compiled_{name}.npz',
            **{key: compiled[key] for key in
               ['t_s', 's', 'phase', 'pose_m_rad', 'g_ref_uT', 'depth_ff_m']},
            artifact_role='derived_nominal_trajectory_not_robot_commands')
        write_json(folder / 'summary.json', summary)
        subprocess.run([sys.executable, str(PREVIEW), str(folder / 'strokeplan.npz'),
                        '--repo', str(ROOT), '--output-dir', str(folder / 'preview')],
                       check=True, capture_output=True, text=True)
    assert context_hashes == {name: sha256(CONTEXT / name) for name in context_hashes}
    write_json(output / 'preflight.json', report)
    write_json(output / 'manifest.json', {str(p.relative_to(output)): sha256(p)
               for p in sorted(output.rglob('*')) if p.is_file()})
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
