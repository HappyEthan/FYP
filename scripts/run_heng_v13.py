#!/usr/bin/env python3
"""Preflight and execute one v13 trial after an explicit terminal run."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'src'), str(Path.home()/'桌面/elfin-dhag-adapter')]
from scripts.run_strokeplan_experiment import main as run_experiment
PLAN = ROOT/'runs/brush2/plans/heng_horizontal_retract_v13'

def confirm(prompt):
    print('\n本次只写一笔v13；自动回等待位、采集基线，然后书写。')
    print('请先蘸水、铺好空白纸面，确认机械臂路径净空；关闭占用传感器的录制/可视化窗口。')
    answer = input('准备好请输入 run 开始，其他输入取消：').strip().lower()
    if answer != 'run':
        return ''
    port = '/dev/ttyACM0'
    if not os.access(port, os.R_OK | os.W_OK):
        raise RuntimeError('串口不存在或没有读写权限。请检查连接，必要时执行：sudo setfacl -m u:$USER:rw /dev/ttyACM0；然后重新运行本脚本。')
    busy = subprocess.run(['fuser', port], capture_output=True, text=True)
    if busy.returncode == 0:
        raise RuntimeError('传感器已被其他进程占用，请关闭录制/监控后重试。占用PID：'+busy.stdout.strip())
    return 'RUN'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if not args.dry_run and not os.access('/dev/ttyACM0', os.R_OK | os.W_OK):
        print('提示：当前串口缺少读写权限；输入run后若报权限错误，请在终端执行 sudo setfacl -m u:$USER:rw /dev/ttyACM0，再重启本脚本。')
    print('v13：原微顿保持，末端改为水平向内收0.5mm；磁目标130→140→100μT。')
    argv = [str(PLAN/'strokeplan.npz'), '--feedforward', str(PLAN/'feedforward.json'),
        '--settings', str(PLAN/'settings.json'), '--entry-profile', str(PLAN/'entry_profile.json'),
        '--control-mode', 'pi', '--record-actual-tcp', '--run-label', 'heng_horizontal_retract_v13_pi',
        '--run-root', str(ROOT/'runs/brush2'), '--dry-run' if args.dry_run else '--execute']
    return run_experiment(argv, feedback_profile=json.loads((PLAN/'pi_profile.json').read_text()), confirm_execution=confirm)

if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\n已取消。')
        sys.exit(130)
    except Exception as exc:
        print('\n实验未正常完成：'+str(exc), file=sys.stderr)
        sys.exit(2)
