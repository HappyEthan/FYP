"""保留 USB-C 的局部改版；源自已核验云端备份，不修改云端或 PCB。"""
import copy
import hashlib
import json
from pathlib import Path
import build_sch_a5 as g
from build_a5_uart_candidate import SOURCE, SOURCE_SHA, button, ref
from check_a5_uart_candidate import check

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'easyeda_std/usb_keep_min_candidate'
CLOUD_LINK_SOURCE=ROOT/'easyeda_std/cloud_presync_20260918/原理图_云端同步前备份.json'
CLOUD_LINK_SHA='d743541b21f40b6b93f865881ce020e44a67e43fd240c65deb40f89e297c548f'


def preserve_cloud_pcb_links(doc):
    """保留现有 PCB 的元件实例关联 ID。

    元件位号和封装即使不变，如果 LIB 头的字段 10 被云端重新生成，
    标准版“导入变更”仍会将已布局元件判为“替换”。只对同名保留元件
    恢复同步前云端 ID；J4/SW2/SW3 等新元件保持空 ID，交由云端首次分配。
    """
    raw=CLOUD_LINK_SOURCE.read_bytes()
    assert hashlib.sha256(raw).hexdigest()==CLOUD_LINK_SHA
    cloud=json.loads(raw)
    old={}
    for page in cloud['schematics']:
        for s in page['dataStr']['shape']:
            if not s.startswith('LIB~'):continue
            h=s.split('#@$')[0].split('~')
            assert len(h)>10 and h[10]
            old[ref(s)]=h[10]
    assert len(old)==41 and 'J3' in old
    kept=0
    for page in doc['schematics']:
        for i,s in enumerate(page['dataStr']['shape']):
            if not s.startswith('LIB~') or ref(s) not in old:continue
            h,*body=s.split('#@$');v=h.split('~')
            v.extend(['']*max(0,16-len(v)))
            v[10]=old[ref(s)]
            page['dataStr']['shape'][i]='#@$'.join(['~'.join(v)]+body)
            kept+=1
    assert kept==40


def bind_saved_buttons(doc):
    raw=(OUT/'原生回读_按键绑定.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='fc802e1723ebece675925cead6b54030f55ad8e7ab91287965751ae708290448'
    native=json.loads(raw)
    native_buttons={ref(s):s.split('#@$')[0].split('~') for p in native['schematics'] for s in p['dataStr']['shape'] if s.startswith('LIB~') and ref(s) in {'SW2','SW3'}}
    evidence=json.loads((OUT/'footprints/按键_原生核验.json').read_text())
    assert evidence['已云端保存'] and evidence['已从个人库重开回读']
    uuid=evidence['云端封装UUID']
    assert uuid=='e7abd9d2c1264c45b3d5eb49e7f359e5'
    pads={s.split('~')[8] for s in evidence['原生PAD摘录']}
    count=0
    for pg in doc['schematics']:
        for i,s in enumerate(pg['dataStr']['shape']):
            if not s.startswith('LIB~') or ref(s) not in {'SW2','SW3'}:continue
            h,*body=s.split('#@$');v=h.split('~')
            assert {p.split('^^')[0].split('~')[3] for p in body if p.startswith('P~')}==pads
            a=v[3].split('`');attrs=dict(zip(a[::2],a[1::2]))
            assert not attrs.get('package')
            attrs['package']='按键_EVPBB_官方铜焊盘'
            attrs['封装来源']='个人库保存重开回读；原理图原生封装管理器已验证'
            v[3]='`'.join(str(z) for pair in attrs.items() for z in pair)+'`'
            # 原生管理器回读：库文档 UUID 在字段7，实际封装 UUID 在字段15，二者不可混用。
            v.extend(['']*max(0,16-len(v)))
            nh=native_buttons[ref(s)]
            assert nh[7]==uuid and nh[15]=='08b07527ca8b41d891fac02ca34a03d1'
            v[7]=nh[7];v[15]=nh[15]
            pg['dataStr']['shape'][i]='#@$'.join(['~'.join(v)]+body);count+=1
    assert count==2


def bind_saved_pen_pads(doc):
    raw=(OUT/'原生回读_全部封装绑定.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='0f59ca7f783b71e3960a888bd03df6a802ee880eaf73133de7f2530a92fd1e15'
    native=json.loads(raw)
    headers=[s.split('#@$')[0] for p in native['schematics'] for s in p['dataStr']['shape'] if s.startswith('LIB~') and ref(s)=='J4']
    assert len(headers)==1
    h=headers[0].split('~')
    assert h[7]=='5f8a0d750c9949b7becfa7bb5e070229' and h[15]=='fbf5a25068d7429988f18f56283e2018'
    count=0
    for page in doc['schematics']:
        for i,s in enumerate(page['dataStr']['shape']):
            if s.startswith('LIB~') and ref(s)=='J4':
                _,*body=s.split('#@$')
                assert {p.split('^^')[0].split('~')[3] for p in body if p.startswith('P~')}=={'1','2','3','4'}
                page['dataStr']['shape'][i]='#@$'.join([headers[0]]+body)
                count+=1
    assert count==1


def make():
    raw=SOURCE.read_bytes()
    assert hashlib.sha256(raw).hexdigest()==SOURCE_SHA
    original=json.loads(raw);d=copy.deepcopy(original)
    g.REV='SCH-A5-USB-KEEP';g.UID=120000;g.COMPONENTS=[];g.POSITIONS={};g.PAGES=[]
    # 去掉专用 UART 引出，原生 USB 两脚及其外围保持原样。
    shapes=d['schematics'][0]['dataStr']['shape'];result=[]
    uart_xy=[]
    for s in shapes:
        if s.startswith('LIB~') and ref(s)=='U1':
            for p in s.split('#@$')[1:]:
                if p.startswith('P~') and p.split('~')[3] in ['49','50']:
                    v=p.split('^^')[0].split('~');uart_xy.append((float(v[4]),float(v[5])))
    assert len(uart_xy)==2
    for s in shapes:
        v=s.split('~')
        if v[0]=='N' and v[5] in ['UART_TX','UART_RX']:continue
        if v[0]=='W':
            p=list(map(float,v[1].split()))
            if (p[0],p[1]) in uart_xy:
                assert len(p)==4
                continue
        result.append(s.replace('J3 引出 EN、BOOT、串口和电源测试焊盘。',
                                'BOOT/RESET 使用实体按键；保留原生 USB 下载，不另设测试焊盘。'))
    g.SHAPES=result
    for x,y in uart_xy:g.nc(x,y)
    shapes[:]=g.SHAPES
    # 在传感器页空白区增加功能接口，板载传感器和原有总线图元保持。
    pg=d['schematics'][1];g.PAGE='02_SENSORS';g.SHAPES=pg['dataStr']['shape']
    g.ic('J4','笔头 MLX90393 飞线焊盘','笔头四线_焊线焊盘候选_待绑定',1160,500,275,175,
         [(1,'3.3V','3V3',30),(2,'GND','GND',70),
          (3,'SDA','I2C_SDA',110),(4,'SCL','I2C_SCL',150)],[],
         '用户确认3.3V及直接飞线；本板1=3V3、2=GND、3=SDA、4=SCL，非模块物理针序推断；上拉、线长和实物验证待完成；禁止生产')
    for n in range(1,5):g.port('J4.'+str(n),distance=95)
    g.note(70,1070,'J4：3.3V/GND/SDA/SCL；笔头实测地址0x0E，板载U2固定0x10，共用R5/R6上拉。模块自带上拉与线长待实测。')
    # 保留射频部分，撤 J3 区域，加入实体启动按键。
    pg=d['schematics'][4];pg['title']='05 外接天线与启动按键';keep=[]
    for s in pg['dataStr']['shape']:
        v=s.split('~')
        if v[0]=='LIB' and ref(s)=='J3':continue
        if v[0] in ['W','PL'] and min(map(float,v[1].split()[1::2]))>=700:continue
        if v[0] in ['T','N','O','J'] and float(v[3] if v[0]=='T' else v[2])>=700:continue
        keep.append(s.replace('05  外接天线与调试焊盘','05  外接天线与启动按键'))
    g.PAGE='05_RF_BUTTONS';g.SHAPES=keep
    button('SW2','BOOT','BOOT_N',410,795);button('SW3','RESET','MCU_EN',1070,795)
    g.note(100,975,'按住 BOOT → 按下并释放 RESET → 释放 BOOT；下载仍走现有 USB-C。',
           '删除独立下载/测试焊盘；保留启动上拉与 EN RC。按键封装和机械可达性待验证。')
    pg['dataStr']['shape']=g.SHAPES
    bind_saved_buttons(d)
    bind_saved_pen_pads(d)
    d['title']='圆形传感板_A5_保留USB小型化_本地候选';d['name']=d['title']
    netlist=json.loads((ROOT/'easyeda_std/design_netlist.json').read_text())
    expected={c['ref']+'.'+p['number']:p['net'] for c in netlist['components'] if c['ref']!='J3' for p in c['pins']}
    expected.update({'U1.49':None,'U1.50':None})
    for c in g.COMPONENTS:
        for p in c['pins']:expected[c['ref']+'.'+p['number']]=p['net']
    assert d['schematics'][2]==original['schematics'][2], 'USB 页不得改动'
    assert d['schematics'][3]==original['schematics'][3], '电源页不得改动'
    preserve_cloud_pcb_links(d)
    return d,expected,original


def renderable(s):
    if s.startswith('LIB~'):
        h,*body=s.split('#@$');return '#@$'.join([h]+[renderable(t) for t in body])
    if s.startswith('P~'):
        b=s.split('^^')
        for i in [3,4]:
            q=b[i].split('~');q[7]=q[7] or '9pt';q[6]=q[6] or 'Arial';b[i]='~'.join(q)
        return '^^'.join(b)
    return s


def main():
    d,expected,_=make();report=check(d,expected,'usb_keep');OUT.mkdir(exist_ok=True)
    path=OUT/'原理图_保留USB小型化候选.json'
    path.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
    (OUT/'预期接线.json').write_text(json.dumps(expected,ensure_ascii=False,indent=2)+'\n')
    report['来源SHA256']=SOURCE_SHA;report['SHA256']=hashlib.sha256(path.read_bytes()).hexdigest()
    (OUT/'接线检查.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    for i,pg in enumerate(d['schematics'],1):
        (OUT/f'{i:02d}.svg').write_text(g.svg([renderable(s) for s in pg['dataStr']['shape']]))
    (OUT/'预览.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>保留 USB 小型化候选</title><style>body{font-family:system-ui;background:#edf2f5;margin:24px}img{width:100%;max-width:1600px;background:white}</style><h1>保留 USB-C · 小型化局部改版</h1><p>本地候选；原生封装管理器43/43匹配；J4.1已接3V3；网络21/21，完整回读接线另行检查。未覆盖云端原理图、未同步 PCB，禁止生产。</p>'+''.join(f'<h2>{p["title"]}</h2><img src="{i:02d}.svg">' for i,p in enumerate(d['schematics'],1))+'</html>')
    print(json.dumps({k:v for k,v in report.items() if k!='网络'},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
