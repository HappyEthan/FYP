#!/usr/bin/env python3
"""Write all four 中 strokes, or select one; offline unless --execute is given."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from brushbot.feedforward import require_execution_approval
from brushbot.experiments.strokeplan_execution import runtime_settings

if __package__:
    from .run_strokeplan_experiment import main as run_experiment
else:
    from run_strokeplan_experiment import main as run_experiment

ROOT = Path(__file__).resolve().parents[1]
TRIAL = ROOT/'runs/brush2/plans/12_中字朝负Y_负X为右'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial-dir', type=Path, default=TRIAL)
    parser.add_argument('--stroke', type=int, choices=range(1, 5),
                        help='write only this stroke; omit to write the complete character')
    parser.add_argument('--mode', choices=('feedforward', 'pi'), default='pi')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--dry-run', action='store_true')
    action.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    trial = args.trial_dir
    try:
        profile = json.loads((trial/'pi_profile.json').read_text()) if args.mode == 'pi' else None
        entry = json.loads((trial/'entry_profile.json').read_text())
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    if entry.get('mode') == 'directional_character':
        target = 'character.npz' if args.stroke is None else f'stroke_{args.stroke:02}.npz'
        label = '整字' if args.stroke is None else f'第{args.stroke}笔'
        print('连续运行：一次基线采集；笔间抬笔直接转移；全部完成后回等待位。')
        return run_experiment([
            str(trial/target), '--feedforward', str(trial/'feedforward.json'),
            '--settings', str(trial/'settings.json'),
            '--entry-profile', str(trial/'entry_profile.json'), '--control-mode', args.mode,
            '--run-root', str(ROOT/'runs/brush2'), '--run-label', f'zhong_{label}_{args.mode}',
            '--experiment-folder', '11_中字连续方向姿态',
            '--run-folder-label', f'中_{label}_方向姿态_{args.mode}',
            '--record-actual-tcp', '--execute' if args.execute else '--dry-run',
        ], feedback_profile=profile)

    def arguments(stroke, execute):
        return [
            str(trial/f'stroke_{stroke:02}.npz'),
            '--feedforward', str(trial/'feedforward.json'), '--settings', str(trial/'settings.json'),
            '--entry-profile', str(trial/'entry_profile.json'), '--control-mode', args.mode,
            '--run-root', str(ROOT/'runs/brush2'), '--run-label', f'zhong_{stroke:02}_{args.mode}',
            '--experiment-folder', '10_中字原地旋转进笔',
            '--run-folder-label', f'中_第{stroke}笔_{args.mode}',
            '--record-actual-tcp', '--execute' if execute else '--dry-run',
        ]

    if args.stroke is not None:
        return run_experiment(arguments(args.stroke, args.execute), feedback_profile=profile)

    print('整字模式：按 1 左竖 → 2 横折 → 3 下横 → 4 中竖执行；先预检全部四笔。')
    for stroke in range(1, 5):
        status = run_experiment(arguments(stroke, False), feedback_profile=profile)
        if status:
            return status
    if not args.execute:
        return 0
    try:
        table = json.loads((trial/'feedforward.json').read_text())
        setup = json.loads((trial/'settings.json').read_text())
        require_execution_approval(table, setup)
        runtime_settings(setup, hardware=True)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print('整字自动执行：每笔结束返回等待位，自动开始下一笔并重新采集基线；分别保存记录。')
    print('本轮一次手动沾水，笔间不暂停补水；保持纸张位置。任一笔异常将停止整字。')
    if input('确认已沾水、处于上述等待位姿且整字路径净空足够；输入 RUN 写完整个中: ').strip() != 'RUN':
        return 0
    for stroke in range(1, 5):
        print(f'开始第 {stroke}/4 笔。')
        status = run_experiment(arguments(stroke, True), feedback_profile=profile,
                                confirm_execution=lambda _: 'RUN')
        if status:
            print(f'第 {stroke} 笔未正常完成，整字停止。')
            return status
    print('四笔均正常完成。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
