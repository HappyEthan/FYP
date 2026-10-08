"""从已核验云端备份生成 UART 小型化原理图候选，不覆盖在线或当前 PCB。"""
import copy
import hashlib
import json
from pathlib import Path
import build_sch_a5 as g

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'archive/pcb_cloud_cleanup_20260918/1-Schematic_圆形传感板_SCH_A5.json'
OUT = ROOT / 'easyeda_std/uart_min_candidate'
SOURCE_SHA = '0aad2c9cc8d1cf75d858bee1279ff4b2d5f38c5e10afccded837f7037464e3b4'


def ref(shape):
    return next(x.split('~')[12] for x in shape.split('#@$')[1:] if x.startswith('T~P~'))


def button(r, function, net, x, y):
    # 自定义焊盘映射：1=A，2=A'，3=B，4=B'；物理封装须依此绑定。
    g.emit(r, 'EVPBB2A9B000', 'EVPBB_3.2x1.3_LAND_待绑定', x, y,
           [g.pd(1, 'A', net, x-100, y-25, 'L'),
            g.pd(2, "A'", net, x-100, y+25, 'L'),
            g.pd(3, 'B', 'GND', x+100, y-25, 'R'),
            g.pd(4, "B'", 'GND', x+100, y+25, 'R')],
           [g.text(x-65, y-85, r+'  '+function, 12),
            g.text(x-65, y-65, r, 11, 'P'),
            g.text(x-65, y-45, 'EVPBB2A9B000', 10, 'N'),
            g.line([(x-80,y-25),(x-55,y-25),(x-55,y+25),(x-80,y+25)]),
            g.line([(x+80,y-25),(x+55,y-25),(x+55,y+25),(x+80,y+25)]),
            g.line([(x-55,y),(x-25,y),(x+18,y-22)]),
            g.line([(x+30,y),(x+55,y)]),
            g.line([(x-10,y-33),(x-10,y-23),(x+10,y-23)])],
           '常开瞬时；1/2 同组，3/4 同组；禁止以旧 J3 焊盘冒充按钮')
    g.rail([r+'.1',r+'.2'],x-145,net)
    g.rail([r+'.3',r+'.4'],x+145,'GND')


def uart_page():
    g.start('03_UART','03  UART 数据与 5V 输入','四线小接口接外置 USB-UART；本板不放转换芯片。只接受 3.3V 逻辑，不是 USB D+/D- 或 RS-232。')
    g.ic('J1','SM04B-SURS-TF','JST_SURS_4P_P0.8_待绑定',170,190,260,280,[],
         [(1,'5V 输入','EXT_5V',50),(2,'地','GND',110),
          (3,'板端 TX','UART_TX_EXT',170),(4,'板端 RX','UART_RX_EXT',230)],
         '配 SUHR-04V-S 压接端和 AWG28 电源线，1A 条件；不是只标 0.5A 的 AWG32 SUR 线束')
    g.port('J1.1',distance=100);g.port('J1.2',distance=20)
    g.ic('U7','SN74LVC2G17DSFR','X2SON-6_DSF_1x1_P0.35_待绑定',780,235,250,240,
         [(6,'1Y','UART_TX_BUF',65,2),(3,'2A','UART_RX_EXT',185,1)],
         [(1,'1A','UART_TX',65,1),(4,'2Y','UART_RX',185,2),
          (5,'VCC','3V3',115,4),(2,'GND','GND',220,4)],
         '3V3 供电；Ioff 断电保护；不是自动下载控制；1->6 为 TX，3->4 为 RX')
    g.passive('R3','499Ω','UART_TX_EXT','UART_TX_BUF',640,300)
    g.wire((450,360),(520,360),(520,300),(600,300))
    g.wire((680,300),(760,300))
    g.wire((450,420),(760,420))
    for p in ['U7.1','U7.4','U7.5','U7.2']:g.port(p,distance=85)
    g.ic('U6','TPD2EUSB30ADRTR','SOT-DRT-3 / 1.0x0.8 mm',350,610,265,160,
         [(1,'TX 保护','UART_TX_EXT',40),(2,'RX 保护','UART_RX_EXT',85)],
         [(3,'GND','GND',130)])
    g.wire((500,360),(500,520),(280,520),(280,650),(330,650))
    g.wire((560,420),(560,545),(310,545),(310,695),(330,695))
    g.port('U6.3',distance=45)
    g.passive('R12','100k','UART_RX_EXT','GND',700,560,vertical=True)
    g.wire((700,420),(700,520));g.port('R12.2',distance=25)
    g.passive('C22','100nF / 10V','3V3','GND',1270,380,'C',True)
    g.port('C22.1',distance=35);g.port('C22.2',distance=35)
    g.ic('D1','TPD1E10B06DPYR','X1SON-2 / 1.0x0.6 mm',1020,640,250,80,
         [(1,'5V 保护','EXT_5V',40)],[(2,'GND','GND',40)])
    g.port('D1.1',distance=60);g.port('D1.2',distance=45)
    for x,y in [(500,360),(560,420),(700,420)]:
        g.SHAPES.append(f'J~{x}~{y}~2.5~#CC0000~{g.gid()}~0')
    g.note(100,885,'J1：1=5V，2=GND，3=本板 TX，4=本板 RX；转接板 TX/RX 需交叉连接。',
           'U7 随 3V3 断电，阻断转接板 UART 对关机主控的反向供电；不增加常供电控制系统。',
           'R12 将未接线 RX 固定为低；软件忽略未接线时的 break，不把串口噪声当作传感器指令。',
           'USB 电流协商/限流由外置转接端处理；5V 需满足运行与充电总负载，禁止接 3.3V 输出冒充 5V。',
           '尚未绑定新封装及验证整机通信/充电；此页为本地电气候选，不可投板。')
    return copy.deepcopy(g.SHAPES)


def make():
    raw=SOURCE.read_bytes()
    assert hashlib.sha256(raw).hexdigest()==SOURCE_SHA,'源文档变化，禁止套用'
    original=json.loads(raw);d=copy.deepcopy(original)
    old={ref(s):s for page in d['schematics'] for s in page['dataStr']['shape'] if s.startswith('LIB~')}
    assert len(old)==41
    g.REV='SCH-A5-UART-CANDIDATE';g.UID=90000;g.COMPONENTS=[];g.POSITIONS={};g.PAGES=[]
    page=d['schematics'][2]
    page['title']='03  UART 数据与 5V 输入';page['dataStr']['shape']=uart_page()
    # 复用既有封装绑定和对象身份，只重画接口局部；新元件使用独立身份。
    donors={'R3':'R3','D1':'D1','U6':'U6','R12':'R11','C22':'C21'}
    for i,s in enumerate(page['dataStr']['shape']):
        if not s.startswith('LIB~'):continue
        r=ref(s)
        if r not in donors:continue
        h,*body=s.split('#@$');new=h.split('~');oldh=old[donors[r]].split('#@$')[0].split('~')
        ah=oldh[3].split('`');attrs=dict(zip(ah[::2],ah[1::2]));a=new[3].split('`');na=dict(zip(a[::2],a[1::2]))
        for k in ['Value','spiceSymbolName','Manufacturer Part','审查备注']:attrs[k]=na[k]
        new[3]='`'.join(str(z) for kv in attrs.items() for z in kv)+'`'
        new[7:]=oldh[7:]
        if r==donors[r]:new[6]=oldh[6]
        page['dataStr']['shape'][i]='#@$'.join(['~'.join(new)]+body)
    # 主控未用原生 USB 两脚明确 NC，保留其余原生图元和绑定。
    shapes=d['schematics'][0]['dataStr']['shape'];result=[]
    for s in shapes:
        v=s.split('~')
        if v[0]=='N' and v[5] in ['USB_DM_SOC','USB_DP_SOC']:continue
        if v[0]=='W' and v[1] in ['1010 210 1110 210','1010 239 1110 239']:continue
        s=s.replace('J3 引出 EN、BOOT、串口和电源测试焊盘。','BOOT/RESET 为实体按键；UART 从 J1 四线接口下载。')
        result.append(s)
    g.SHAPES=result;g.nc(1010,210);g.nc(1010,239)
    shapes[:]=g.SHAPES
    # 第五页只撤 J3 区域，保留所有 RF 实体和连线。
    pg=d['schematics'][4];pg['title']='05  外接天线与启动按键';keep=[]
    for s in pg['dataStr']['shape']:
        v=s.split('~')
        if v[0]=='LIB' and ref(s)=='J3':continue
        if v[0] in ['W','PL'] and min(map(float,v[1].split()[1::2]))>=700:continue
        if v[0] in ['T','N','O','J'] and float(v[3] if v[0]=='T' else v[2])>=700:continue
        s=s.replace('05  外接天线与调试焊盘','05  外接天线与启动按键')
        keep.append(s)
    g.PAGE='05_RF_BUTTONS';g.SHAPES=keep
    button('SW2','BOOT','BOOT_N',410,795);button('SW3','RESET','MCU_EN',1070,795)
    g.note(100,975,'按住 BOOT → 按下并释放 RESET → 释放 BOOT → 经 J1 UART 下载。',
           '删除独立下载/测试焊盘；保留 BOOT 上拉与 EN 原有 RC；外壳须留按键操作空间。')
    pg['dataStr']['shape']=g.SHAPES
    # 将 5V 网统一改为中性的外部供电名称，仅改名称，不改电源拓扑。
    for pg in d['schematics']:
        pg['dataStr']['shape']=[s.replace('USB_5V','EXT_5V')
            .replace('G=2接USB','G=2接外部5V')
            .replace('USB 充电仍可工作。','外部 5V 充电仍可工作。')
            .replace('圆形传感板 · SCH-A5 · 2026-09-16','圆形传感板 · UART 小型化候选 · 2026-09-18')
            for s in pg['dataStr']['shape']]
    d['title']='圆形传感板_A5_UART小型化_本地候选';d['name']=d['title']
    # 原生成器只作为图形工具；验收由另一个脚本从电气图元反推。
    expected=json.loads((ROOT/'easyeda_std/design_netlist.json').read_text())
    pinmap={c['ref']+'.'+p['number']:p['net'] for c in expected['components'] for p in c['pins']}
    replaced={'J1','R1','R2','R3','R4','D1','D2','D3','U6','J3'}
    pinmap={k:('EXT_5V' if v=='USB_5V' else v) for k,v in pinmap.items() if k.split('.')[0] not in replaced}
    pinmap.update({'U1.25':None,'U1.26':None})
    for c in g.COMPONENTS:
        for p in c['pins']:pinmap[c['ref']+'.'+p['number']]=p['net']
    # 物理引脚和源几何只允许指定范围变化。
    assert d['schematics'][1]==original['schematics'][1] or all(
        a.replace('圆形传感板 · SCH-A5 · 2026-09-16','圆形传感板 · UART 小型化候选 · 2026-09-18')==b
        for a,b in zip(original['schematics'][1]['dataStr']['shape'],d['schematics'][1]['dataStr']['shape']))
    return d,pinmap,original


def main():
    d,pinmap,_=make();OUT.mkdir(exist_ok=True)
    (OUT/'原理图_UART小型化候选.json').write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
    (OUT/'预期接线.json').write_text(json.dumps(pinmap,ensure_ascii=False,indent=2)+'\n')
    def renderable(s):
        if s.startswith('LIB~'):
            h,*body=s.split('#@$');return '#@$'.join([h]+[renderable(x) for x in body])
        if s.startswith('P~'):
            b=s.split('^^')
            for i in [3,4]:
                q=b[i].split('~');q[7]=q[7] or '9pt';q[6]=q[6] or 'Arial';b[i]='~'.join(q)
            return '^^'.join(b)
        return s
    for n,p in enumerate(d['schematics'],1):
        (OUT/f'{n:02d}.svg').write_text(g.svg([renderable(s) for s in p['dataStr']['shape']]))
    html='<html lang="zh-CN"><meta charset="utf-8"><title>UART 小型化原理图候选</title><style>body{font-family:system-ui;background:#edf2f5;margin:24px}img{width:100%;background:white}section{max-width:1600px;margin:auto}h2{font-size:20px}</style><h1>UART 小型化原理图 · 本地候选</h1><p>非云端当前稿，未绑定全部封装，未完成原生 ERC/PCB 验证，不可生产。</p>'
    html+=''.join(f'<section><h2>{p["title"]}</h2><img src="{n:02d}.svg"></section>' for n,p in enumerate(d['schematics'],1))+'</html>'
    (OUT/'预览.html').write_text(html)
    print(OUT/'原理图_UART小型化候选.json')


if __name__=='__main__':main()
