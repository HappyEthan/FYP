"""先给充电芯片必要地脚引出，再重布充电设定网络；整体网络不得退化。"""
from refine_clone_usb_20260928 import *
from check_pcb_a5 import U

configure();batch.STEP=.02
doc,p,c,h=parse(OUT);trial=copy.deepcopy(doc);report=json.loads(REPORT.read_text())
rule=copy.deepcopy(trial['DRCRULE']['Default'])
rule.update(nets=['U4_C1'],viaHoleDiameter=.25/U,viaHoleD=.15/U)
trial['DRCRULE']['充电设定小孔_025_015']=rule
if '--local-only' in sys.argv:
    ids={'ggeUSB0928T271','ggeUSB0928V275'}
    trial['shape']=[s for s in trial['shape'] if not(s.startswith(('TRACK~','VIA~')) and s.split('~')[5 if s.startswith('TRACK~') else 6] in ids)]
else:
    trial['shape']=[s for s in trial['shape'] if not(s.startswith(('TRACK~','VIA~')) and s.split('~')[3 if s.startswith('TRACK~') else 4]=='U4_C1')]
gs=batch.island_contacts(trial,c,'GND')
g=next(g for g in gs if any(a['id'].startswith('U4.C2:') for a in g))
goals=[a for q in gs if any(b['id'].startswith(('U4.B1:','R9.2:','D2.2:')) for b in q) for a in q]
ok,info=batch.route(trial,c,h,'GND',g,goals,*dimensions(trial,'GND'));print('CHARGE_GND',ok,info,flush=True)
if not ok or info['长度']>2.5:sys.exit(0)
gs=batch.island_contacts(trial,c,'U4_C1');assert len(gs)==2
batch.STEP=.02;batch.MAX_SEARCH_NODES=1500000;batch.NEW_VIA_COST=.25
ok2,info2=batch.route(trial,c,h,'U4_C1',gs[0],gs[1],*dimensions(trial,'U4_C1'));print('CHARGE_SIGNAL',ok2,info2,flush=True)
if ok2 and info2['长度']<12 and info2['孔数']<=2 and not local_check(trial,c,h) and not any(old_losses(doc,c,trial,c,n) for n in {p['net'] for p in c if p['net']}):
    save(trial);report['充电芯片接地优先重布']={'接地':info,'设定电阻':info2,'原生复查':False}
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print('CHARGE_ACCEPTED',flush=True)
