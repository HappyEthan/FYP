import numpy as np
import pytest


def test_zhong_preserves_stroke_order_shape_and_target_only_provenance():
    from scripts.generate_calligraphy_trial import generate_target
    plan = generate_target(size_mm=160.)
    plan.validate()
    assert len(plan.strokes) == 4
    assert plan.meta['source'] == 'mixed'
    assert plan.meta['character'] == '中'
    assert plan.meta['g_target_source'] == 'synthetic_calligraphy_heuristic'
    # Left vertical, top/right turn, bottom horizontal, long central vertical.
    a, b, c, d = [s.xy[-1] - s.xy[0] for s in plan.strokes]
    assert a[1] < 0 and b[0] > 0 and b[1] < 0 and c[0] > 0 and d[1] < -.15
    for st in plan.strokes:
        assert st.t[-1] > 5.
        assert np.max(np.linalg.norm(np.diff(st.xy, axis=0), axis=1) / np.diff(st.t)) <= .010001
        assert 100. <= min(st.g_target) <= max(st.g_target) <= 240.000001
    vertical = plan.strokes[-1]
    assert vertical.g_target[-1] < np.interp(.5, vertical.s, vertical.g_target)
    turning = plan.strokes[1]
    turn_s = turning.s[np.argmax(turning.xy[:, 0])]
    assert np.interp(turn_s, turning.s, turning.g_target) > np.interp(.4, turning.s, turning.g_target)


def test_trial_exports_same_paper_coordinates_for_each_independent_stroke(tmp_path):
    from scripts.generate_calligraphy_trial import generate
    from brushbot.target_strokeplan import StrokePlan
    import json
    folder = tmp_path/'trial'
    result = generate(folder)
    full = StrokePlan.load(folder/'character.npz')
    for i, st in enumerate(full.strokes, 1):
        part = StrokePlan.load(folder/f'stroke_{i:02}.npz')
        assert part.strokes[0].xy == pytest.approx(st.xy)
        assert part.strokes[0].g_target == pytest.approx(st.g_target)
    assert len(result['strokes']) == 4
    assert json.loads((folder/'entry_profile.json').read_text())['mode'] == 'stationary'
    with pytest.raises(FileExistsError):
        generate(folder)


def test_zhong_runner_defaults_to_offline_pi_for_selected_stroke(tmp_path, capsys):
    from scripts.generate_calligraphy_trial import generate
    from scripts.run_calligraphy_trial import main
    folder = tmp_path/'trial'
    generate(folder)
    assert main(['--trial-dir', str(folder), '--stroke', '4']) == 0
    output = capsys.readouterr().out
    assert '原地加载' in output and 'PI' in output and '离线预检通过' in output


def test_omitting_stroke_preflights_all_four_without_confirmation(tmp_path, monkeypatch, capsys):
    from scripts.generate_calligraphy_trial import generate
    from scripts.run_calligraphy_trial import main
    folder = tmp_path/'trial'
    generate(folder)
    monkeypatch.setattr('builtins.input', lambda _: pytest.fail('offline must not prompt'))
    assert main(['--trial-dir', str(folder), '--dry-run']) == 0
    output = capsys.readouterr().out
    assert output.count('离线预检通过') == 4
    for i in range(1, 5):
        assert f'zhong_{i:02}_pi' in output


@pytest.mark.parametrize('answer, failure, expected', [
    ('RUN', None, [1, 2, 3, 4]), ('RUN', 2, [1, 2]), ('cancel', None, []),
])
def test_character_confirmation_order_and_stop_on_failure(tmp_path, monkeypatch, answer, failure, expected):
    import json
    from pathlib import Path
    from scripts.generate_calligraphy_trial import generate
    from scripts import run_calligraphy_trial as runner
    folder = tmp_path/'trial'
    generate(folder)
    table_path = folder/'feedforward.json'
    table = json.loads(table_path.read_text())
    table.update(approved=True, transient_approved=True)
    table_path.write_text(json.dumps(table))
    actual = runner.run_experiment
    executed, prompts = [], []

    def run(args, **kwargs):
        if '--execute' not in args:
            return actual(args, **kwargs)
        index = int(Path(args[0]).stem.rsplit('_', 1)[1])
        assert kwargs['confirm_execution']('per-stroke confirmation') == 'RUN'
        executed.append(index)
        return 2 if index == failure else 0

    def confirm(prompt):
        prompts.append(prompt)
        return answer

    monkeypatch.setattr(runner, 'run_experiment', run)
    monkeypatch.setattr('builtins.input', confirm)
    status = runner.main(['--trial-dir', str(folder), '--execute'])
    assert executed == expected
    assert len(prompts) == 1
    assert status == (2 if failure else 0)


def test_invalid_last_stroke_blocks_whole_character_before_confirmation(tmp_path, monkeypatch):
    from scripts.generate_calligraphy_trial import generate
    from scripts.run_calligraphy_trial import main
    folder = tmp_path/'trial'
    generate(folder)
    (folder/'stroke_04.npz').write_bytes(b'invalid')
    monkeypatch.setattr('builtins.input', lambda _: pytest.fail('all strokes must preflight first'))
    with pytest.raises(SystemExit):
        main(['--trial-dir', str(folder), '--execute'])
