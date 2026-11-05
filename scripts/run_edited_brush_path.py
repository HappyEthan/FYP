#!/usr/bin/env python3
"""Execute one exported editor version after operator run; default is dry-run."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'src'), str(Path.home()/'桌面/elfin-dhag-adapter')]
from scripts.run_strokeplan_experiment import main as run_experiment
from brushbot.experiments.archive import DEFAULT_ARCHIVE_ROOT, PLAN_FILES, ExperimentArchive
PLAN = None

def confirm(prompt):
    print('\n本次按导出顺序执行笔画；自动回等待位、采集基线，逐笔书写，笔间抬笔悬空转移，全部完成后回等待位。')
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

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan_dir',type=Path)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--run-root',type=Path,default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument('--consume-stage',type=Path,help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    store = ExperimentArchive(args.run_root) if args.consume_stage or args.execute else None
    capture_inputs = store is not None and args.consume_stage is None
    if capture_inputs:args.consume_stage = store.new_stage(kind='launch')
    if store is not None:store.claim_stage(args.consume_stage,kind='launch')
    if store is None:
        return run_plan(args)
    with store.capture_console(args.consume_stage):
        try:
            if capture_inputs:
                inputs = args.consume_stage / 'inputs'
                inputs.mkdir()
                for name in PLAN_FILES:
                    source = args.plan_dir / name
                    if source.is_file():shutil.copyfile(source, inputs / name)
            code = run_plan(args)
        except BaseException as exc:
            traceback.print_exc()
            if args.consume_stage.exists():
                store.retain_stage(args.consume_stage, reason='launcher_exception', exception=exc)
            raise
        if args.consume_stage.exists():
            store.retain_stage(args.consume_stage, reason='launch_cancelled_or_not_executed' if code == 0 else 'launch_failed')
        return code


def run_plan(args):
    PLAN=args.plan_dir.resolve()
    args.dry_run=not args.execute
    if not args.dry_run and not os.access('/dev/ttyACM0', os.R_OK | os.W_OK):
        print('提示：当前串口缺少读写权限；输入run后若报权限错误，请在终端执行 sudo setfacl -m u:$USER:rw /dev/ttyACM0，再重启本脚本。')
    print('编辑路径版本：',PLAN)
    preflight_path=PLAN/'preflight.json'
    if preflight_path.exists():
        preflight=json.loads(preflight_path.read_text())
        if preflight.get('execution_scope')=='all_strokes_in_order':
            for i,row in enumerate(preflight['execution_order']):
                print(f'第{i+1}笔：{row["stroke_name"]}，点 {row["point_range"][0]} → {row["point_range"][1]}')
            print(f'笔间悬空平移：转场绝对 Z={preflight.get("transfer_z_mm")} mm；下一笔从最小有效点序号落笔。')
        elif 'stroke_name' in preflight:
            print(f'当前试写：{preflight["stroke_name"]}；工作区共 {preflight.get("workspace_stroke_count",1)} 笔，本次仅执行当前笔画。')
        if 'test_node_range' in preflight and preflight.get('execution_scope')!='all_strokes_in_order':
            first,last=preflight['test_node_range']
            print(f'本次测试点 {first} → {last}；隐藏 {len(preflight.get("hidden_nodes",[]))} 个点，隐藏段不执行。')
    report_path=PLAN/'speed_adaptation.json'
    if report_path.exists():
        speed_report=json.loads(report_path.read_text())
        print(f'自动适速版本：局部调整 {speed_report["iterations"]} 次，预计书写 {speed_report["writing_duration_s"]:.2f} 秒，最高规划运笔速度 {speed_report["planned_max_writing_speed_mm_s"]:.2f} mm/s。')
    table=json.loads((PLAN/'feedforward.json').read_text())
    if table.get('high_speed_trial'):
        print('高速试验：速度上限20 mm/s，磁响应—压深仍来自10 mm/s原表；20 mm/s响应未重新标定。')
    if table.get('low_response_trial'):
        print('低响应试验已启用：0..标定下限采用未实测线性映射；0μT对应零名义压深，不保证触纸。')
    argv = [str(PLAN/'strokeplan.npz'), '--feedforward', str(PLAN/'feedforward.json'),
        '--settings', str(PLAN/'settings.json'), '--entry-profile', str(PLAN/'entry_profile.json'),
        '--control-mode', 'pi', '--record-actual-tcp', '--run-label', 'edited_brush_path_pi',
        '--bundle-dir', str(PLAN), '--run-root', str(args.run_root), '--dry-run' if args.dry_run else '--execute']
    if args.consume_stage is not None:
        argv += ['--session-stage', str(args.consume_stage)]
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
