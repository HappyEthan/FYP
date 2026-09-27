"""Offline target recipe; run from the repository root with PYTHONPATH=src:."""
import hashlib
from pathlib import Path

import numpy as np

from scripts.generate_strokeplan import generate
from brushbot.target_strokeplan import StrokePlan


folder = Path(__file__).resolve().parent
parent = folder / '04_smooth_levels.npz'
output = folder / '04_smooth_levels_wide_transitions.npz'
if output.exists():
    raise SystemExit(f'Refusing to overwrite {output}')

x_mm = np.linspace(0., 200., 401)
target = np.full_like(x_mm, 60.)
for delta, start in zip((70., 70., -105.), (15., 75., 135.)):
    u = np.clip((x_mm - start) / 45., 0., 1.)
    target += delta * u**3 * (10. - 15.*u + 6.*u*u)

plan = generate(targets_uT=target, length_mm=200., speed_mm_s=10.)
plan.meta.update(
    stability_profile='04_smooth_levels_wide_transitions',
    description='Four holds 60/130/200/95 uT; quintic transitions over '
                '15-60, 75-120, 135-180 mm; +X 200 mm at 10 mm/s cruise.',
    parent_filename=parent.name,
    parent_sha256=hashlib.sha256(parent.read_bytes()).hexdigest(),
    transition_intervals_mm=[[15., 60.], [75., 120.], [135., 180.]],
    plateau_targets_uT=[60., 130., 200., 95.],
    validation='Target schema only; machine validation is a separate artifact.',
)
plan.validate()
old = StrokePlan.load(parent).strokes[0]
for field in ('s', 'xy', 't'):
    np.testing.assert_array_equal(getattr(plan.strokes[0], field), getattr(old, field))
plan.save(output)
loaded = StrokePlan.load(output)
loaded.validate()
st = loaded.strokes[0]
for start, end, value in ((0, 15, 60), (60, 75, 130),
                          (120, 135, 200), (180, 200, 95)):
    mask = (st.s*200 >= start) & (st.s*200 <= end)
    np.testing.assert_allclose(st.g_target[mask], value, atol=1e-10)
print(output)
