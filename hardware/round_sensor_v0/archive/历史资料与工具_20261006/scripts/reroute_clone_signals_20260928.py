"""USB 候选的普通信号统一重排实验。锁定 USB/RF/电源，原生验收前不保存云端。"""
import tempfile
from pathlib import Path
from refine_clone_usb_20260928 import *
from check_pcb_a5 import U

def run():
    configure();batch.STEP=.04
    source,_,oldc,_=parse(SOURCE)
    input_path=Path(sys.argv[sys.argv.index('--base')+1]) if '--base' in sys.argv else OUT
    doc,parts,c,h=parse(input_path)
    backup=Path(tempfile.mkdtemp(prefix='edausb-signal-'))/'before.json'
    backup.write_bytes(OUT.read_bytes());print('BACKUP',backup,flush=True)
    report=json.loads(REPORT.read_text())
    nets=['J1_A5','J1_B5','BOOT_N','MCU_EN','U4_C1','REG_EN','I2C_SCL','I2C_SDA','MLX_INT','IMU_INT']
    if '--pin-first' in sys.argv:
        nets=['U4_C1','I2C_SDA','MLX_INT','IMU_INT','I2C_SCL','BOOT_N','MCU_EN','REG_EN','J1_A5','J1_B5']
    removed=[];keep=[]
    for s in doc['shape']:
        v=s.split('~');n=v[3] if v[0]=='TRACK' else v[4] if v[0]=='VIA' else None
        # RF 区地铜与 U6/R10 的新回流线保留。其余地连线重建为就近下地孔。
        drop=n in nets or (v[0]=='TRACK' and n=='GND' and not v[5].startswith(('ggeRF',PREFIX)))
        (removed if drop else keep).append(s)
    doc['shape']=keep
    # BGA 充电设置脚保留已逐项验算的焊盘外短出口，避免全局搜索忽略细小入口。
    batch.add_via(doc,'U4_C1',(23.27,-74.15),*dimensions(doc,'U4_C1')[1:])
    batch.add_track(doc,'U4_C1','2',[(22.406102,-74.82205),(22.406102,-74.93),(22.72,-75.243898),
                                  (22.98,-75.243898),(23.27,-74.953898),(23.27,-74.15)],dimensions(doc,'U4_C1')[0])
    report.setdefault('普通信号统一重排',[]).append({'恢复文件':str(backup),'撤回图元':removed,'日志':[]})
    log=report['普通信号统一重排'][-1]['日志']
    save(doc)
    for net in nets:
        for step in (.04,.02):
            batch.STEP=step
            blocked=set()
            for attempt in range(20):
                groups=batch.island_contacts(doc,c,net)
                if len(groups)<=1:break
                labels=[{a['id'].split(':')[0] for a in g if not a['id'].startswith('gge')} for g in groups]
                opts=[]
                for i,a in enumerate(groups):
                    for j,b in enumerate(groups[:i]):
                        key=tuple(sorted((tuple(sorted(labels[i])),tuple(sorted(labels[j])))))
                        if key in blocked:continue
                        opts.append((min(math.dist(batch.center(x),batch.center(y)) for x in a for y in b),key,a,b))
                if not opts:break
                _,key,a,b=min(opts,key=lambda x:(x[0],x[1]));size=len(doc['shape'])
                ok,info=batch.route(doc,c,h,net,a,b,*dimensions(doc,net))
                if ok:
                    # 禁止仅凭寻路返回值认定成功；验证实际物理连接组确实合并。
                    after=batch.island_contacts(doc,c,net)
                    if len(after)>=len(groups):
                        doc['shape']=doc['shape'][:size];ok=False;info={'物理连接组未减少':info}
                if not ok:blocked.add(key)
                print('REROUTE',step,net,ok,info,flush=True);log.append([step,net,key,ok,info]);save(doc)
            print('GROUPS',net,[sorted(g) for g in connected_groups(doc,c,net)],flush=True)
    if '--ground' in sys.argv:ground_islands(doc,c,h,report)
    report['原连接退化']={n:[sorted(g) for g in old_losses(source,oldc,doc,c,n)] for n in {p['net'] for p in c if p['net']}}
    report['原连接退化']={n:g for n,g in report['原连接退化'].items() if g}
    report['候选几何冲突']=local_check(doc,c,h)
    report['本地几何与连接准入']=not report['原连接退化'] and not report['候选几何冲突']
    for i,s in enumerate(doc['shape']):
        if s.startswith('COPPERAREA~'):
            v=s.split('~');v[10]='';doc['shape'][i]='~'.join(v)
    save(doc);REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('FINAL',report['原连接退化'],report['候选几何冲突'],flush=True)

if __name__=='__main__':run()
