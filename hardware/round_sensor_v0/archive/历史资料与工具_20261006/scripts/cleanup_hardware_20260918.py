"""一次性目录清理：先列清单，显式--apply才移动到专用废纸篓子目录。"""
import ast
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path('/Users/liuchunyu/Documents/fyp/hardware/round_sensor_v0')
TRASH = Path('/Users/liuchunyu/.Trash/fyp_round_sensor_cleanup_20260918')
PLAN = ROOT/'清理清单_20260918.json'
ROOTS = '''build_a5_rf_route_20260918 verify_a5_rf_native_20260918 test_a5_rf_route_20260918
build_a5_usb_keep_candidate test_a5_usb_keep_candidate build_a5_usb_keep_footprints
test_a5_usb_keep_footprints check_ufl_footprint
test_pcb_a5_pico_stencil'''.split()
REWRITE = {'README.md','CAD_HANDOFF.md','DESIGN_BASELINE_XIAO_PICO.md','AGENTS.md',
           '小型化调整方案.md','easyeda_std/README.md',
           'archive/eda_session_close_20260918/恢复说明.md'}
DOCS = '''PCB_A5_PICO钢网与填孔候选.md PCB_A5_嘉立创物料与层叠准备.md
PCB_A5_射频首段审核_20260918.md PCB_A5_布线前制造审核.md PCB_A5_机械审核.md
SCH_A5_电气与制造审核.md SCH_A5_续航放宽与电源取舍.md 双MLX90393_I2C审核_20260918.md'''.split()
REJECTED_REFS = '''2450AT18D0100001E_CIRCULAR_THIN_EDGE_4PAD.kicad_mod
2450AT18D0100001E_CIRCULAR_THIN_EDGE_4PAD_easyeda_import.kicad_pcb
BATTERY_WIRE_3PAD_COMPACT.kicad_mod DMC2400UV_SOT563_DIODES_LAND.kicad_pcb
POGO_RECOVERY_6PAD_COMPACT.kicad_mod POWER_SWITCH_WIRE_2PAD_COMPACT.kicad_mod
antenna-2450at18d.pdf bq24074.pdf bq25185.pdf bq25186.pdf dmc2400uv.pdf jst_suh.pdf sn74lvc2g17.pdf'''.split()


def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def plan():
    if PLAN.exists() and json.loads(PLAN.read_text()).get('已执行'):
        raise SystemExit('已执行的恢复清单不得覆盖；后续清理请另建计划。')
    files={p.stem:p for p in (ROOT/'scripts').glob('*.py')}
    todo=ROOTS[:]; modules=set(); literals=set()
    while todo:
        name=todo.pop()
        if name in modules:continue
        modules.add(name)
        for node in ast.walk(ast.parse(files[name].read_text())):
            if isinstance(node,ast.Constant) and isinstance(node.value,str):literals.add(node.value)
            mods=[a.name.split('.')[0] for a in node.names] if isinstance(node,ast.Import) else [node.module.split('.')[0]] if isinstance(node,ast.ImportFrom) and node.module else []
            todo.extend(m for m in mods if m in files and m not in modules)
    keep={files[n].relative_to(ROOT).as_posix() for n in modules}|set(DOCS)
    keep.add('scripts/cleanup_hardware_20260918.py')
    # 保留所有仍被当前工具依赖的历史输入，避免“清理”破坏可重现性。
    for p in ROOT.rglob('*'):
        if not p.is_file() or p.is_symlink():continue
        rel=p.relative_to(ROOT).as_posix()
        if rel in literals or p.name in literals:keep.add(rel)
        if rel.startswith(('easyeda_std/usb_keep_min_candidate/','easyeda_std/footprints/')):keep.add(rel)
        if rel.startswith('references/') and p.name not in REJECTED_REFS:keep.add(rel)
    keep.update({'easyeda_std/PCB_射频首段_云端重开回读_20260918.json',
                 'easyeda_std/射频首段云端核验_20260918.json',
                 'archive/eda_session_close_20260918/关机备份_01_旧工作板未保存.json'})
    # 以下仅是旧生成器的输出名，不是当前检查所需输入。
    keep -= {'archive/pre_SCH_A5_20260916/easyeda_std/'+name for name in
             ('bom_draft.json','design_netlist.json','preview.html','sheets_manifest.json')}
    keep -= {'easyeda_std/'+name for name in
             ('bom_draft.json','preview.html','sheets_manifest.json','round_sensor_SCH_A5_multi.json')}
    keep = {rel for rel in keep if not rel.startswith('easyeda_std/uart_min_candidate/')
            and not rel.endswith('.js')}
    keep-=REWRITE
    targets=[]
    for p in sorted(ROOT.rglob('*')):
        if not p.is_file() or p.is_symlink() or p==PLAN:continue
        rel=p.relative_to(ROOT).as_posix()
        if rel in keep:continue
        targets.append({'原路径':rel,'字节':p.stat().st_size,'SHA256':digest(p),
                        '原因':'旧说明原件留档，原位重写最新入口' if rel in REWRITE else '过时版本、独立旧工具、重复备份或缓存'})
    result={'范围':str(ROOT),'废纸篓目录':str(TRASH),'已执行':False,
            '保留脚本模块':sorted(modules),'保留文件':sorted(keep),
            '移出文件数':len(targets),'移出字节':sum(t['字节'] for t in targets),'清单':targets}
    PLAN.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in {'清单','保留文件','保留脚本模块'}},ensure_ascii=False,indent=2))


def apply():
    d=json.loads(PLAN.read_text())
    assert not d['已执行'] and d['范围']==str(ROOT) and d['废纸篓目录']==str(TRASH)
    assert ROOT.is_dir() and ROOT.name=='round_sensor_v0' and not ROOT.is_symlink()
    assert not TRASH.exists(), '目标存在，停止，禁止覆盖已有恢复资料'
    for item in d['清单']:
        p=ROOT/item['原路径']
        assert p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(ROOT)
        assert digest(p)==item['SHA256'], f'计划后文件变化：{p}'
    # 所有目标核实后才移动；绝不清空废纸篓，也不递归删除工程目录。
    TRASH.mkdir(parents=False)
    for item in d['清单']:
        p=ROOT/item['原路径']; dest=TRASH/item['原路径']; dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.move(str(p),str(dest))
        assert digest(dest)==item['SHA256']
    for p in sorted(ROOT.rglob('*'),key=lambda p:len(p.parts),reverse=True):
        if p.is_dir() and not p.is_symlink() and not any(p.iterdir()):p.rmdir()
    d['已执行']=True
    PLAN.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
    print('已逐文件移动并核验：',len(d['清单']),'；废纸篓：',TRASH)


if __name__=='__main__':
    if sys.argv[1:]==['--apply']:apply()
    elif not sys.argv[1:]:plan()
    else:raise SystemExit('仅支持默认列计划或--apply')
