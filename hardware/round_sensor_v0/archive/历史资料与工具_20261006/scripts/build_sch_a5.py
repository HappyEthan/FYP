"""SCH-A5：显式手工布局和导线；不使用自动布线或逐引脚标签兜底。"""
from pathlib import Path
from collections import defaultdict
import json
import html
import uuid

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'easyeda_std'
REV = 'SCH-A5'
PAGES = []
COMPONENTS = []
POSITIONS = {}
SHAPES = []
PAGE = ''
UID = 0

def gid():
    global UID
    UID += 1
    return f'ggeA5{UID}'

def text(x,y,s,size=12,mark='L',color='#164B67',anchor='start'):
    return f'T~{mark}~{x}~{y}~0~{color}~Arial~{size}pt~~~~comment~{s}~1~{anchor}~{gid()}~0~'

def line(points,cmd='PL',color='#993333'):
    return f"{cmd}~{' '.join(str(z) for p in points for z in p)}~{color}~1~0~none~{gid()}~0"

def rect(x,y,w,h):
    return f'R~{x}~{y}~~~{w}~{h}~#993333~1~0~none~{gid()}~0'

def note(x,y,*strings):
    for i,s in enumerate(strings): SHAPES.append(text(x,y+i*25,s,11))

def wire(*points):
    assert len(points)>1
    assert all(a[0]==b[0] or a[1]==b[1] for a,b in zip(points,points[1:]))
    SHAPES.append(line(points,'W','#008800'))

def label(net,x,y,side='R'):
    SHAPES.append(f'N~{x}~{y}~0~#006A49~{net}~{gid()}~'+('end' if side=='L' else 'start')+f'~{x}~{y-5}~Arial~9pt~0')

def ground(x,y):
    label('GND',x,y)
    SHAPES.extend([line([(x,y),(x,y+8)],color='#008800'),line([(x-10,y+8),(x+10,y+8)]),line([(x-6,y+12),(x+6,y+12)]),line([(x-2,y+16),(x+2,y+16)])])

def nc(x,y):
    SHAPES.append(f'O~{x}~{y}~{gid()}~M{x-3},{y-3} L{x+3},{y+3} M{x+3},{y-3} L{x-3},{y+3}~#CC0000~0')

def pin(num,name,x,y,side,etype=0,show=True):
    dx,dy={'L':(20,0),'R':(-20,0),'T':(0,20),'B':(0,-20)}[side]
    angle={'L':180,'R':0,'T':270,'B':90}[side]
    anchor='end' if side=='R' else 'start'
    tx=x+dx+(-5 if side=='R' else 5); ty=y+dy+4
    nx=x+dx/2-5 if dy else x+dx/2; ny=y+dy/2-4
    return (f'P~show~{etype}~{num}~{x}~{y}~{angle}~{gid()}~0'
            f'^^{x}~{y}^^M {x} {y} l {dx} {dy}~#880000'
            f'^^{int(show)}~{tx}~{ty}~0~{name}~{anchor}~Arial~9pt~#000000'
            f'^^1~{nx}~{ny}~0~{num}~middle~Arial~7pt~#000000^^0~0~0^^0~M 0 0')

def emit(ref,value,package,x,y,pins,graphics,notes='',fitted=True):
    attrs={'package':'','nameAlias':'Value','Value':value,'spicePre':ref.rstrip('0123456789'),
           'spiceSymbolName':value,'Manufacturer Part':value,'Package candidate':package,
           '审查备注':notes,'装配状态':'装配' if fitted else '不装配'}
    para='`'.join(str(z) for pair in attrs.items() for z in pair)+'`'
    header=f'LIB~{x}~{y}~{para}~0~0~{gid()}~{uuid.uuid5(uuid.NAMESPACE_URL,REV+ref).hex}~~0~~yes~yes'
    SHAPES.append('#@$'.join([header]+graphics+[pin(p['number'],p['name'],p['x'],p['y'],p['side'],p['electrical'],p.get('show',True)) for p in pins]))
    COMPONENTS.append(dict(ref=ref,value=value,package_candidate=package,footprint_bound=False,fitted=fitted,notes=notes,sheet=PAGE,pins=pins))
    for p in pins:
        POSITIONS[f"{ref}.{p['number']}"]=(p['x'],p['y'])
        if p['net'] is None: nc(p['x'],p['y'])

def pd(num,name,net,x,y,side,etype=0,show=True):
    return dict(number=str(num),name=name,net=net,x=x,y=y,side=side,electrical=etype,show=show)

def ic(ref,value,package,x,y,w,h,left,right,notes=''):
    # Entries: (pin number, pin name, net, vertical offset [, electrical type]).
    ps=[]
    for side,entries,px in [('L',left,x-20),('R',right,x+w+20)]:
        for entry in entries:
            n,name,net,dy,*et=entry
            ps.append(pd(n,name,net,px,y+dy,side,et[0] if et else 0))
    emit(ref,value,package,x,y,ps,[rect(x,y,w,h),text(x,y-32,ref,12,'P'),text(x,y-12,value,10,'N')],notes)

def passive(ref,value,net1,net2,x,y,kind='R',vertical=False,package=None,fitted=True):
    # Electrical endpoints are 40 units from centre; pin stubs lead into the symbol.
    def t(a,b): return (x+b,y+a) if vertical else (x+a,y+b)
    def l(points): return line([t(a,b) for a,b in points])
    if kind=='R': g=[l([(-20,-7),(20,-7),(20,7),(-20,7),(-20,-7)])]
    elif kind=='C': g=[l([(-20,0),(-4,0)]),l([(4,0),(20,0)]),l([(-4,-13),(-4,13)]),l([(4,-13),(4,13)])]
    elif kind=='D':
        # pin 1 = cathode at negative axis; pin 2 = anode at positive axis.
        g=[l([(-20,0),(-10,0)]),l([(10,0),(20,0)]),l([(-10,-12),(-10,12)]),l([(-10,0),(10,-12),(10,12),(-10,0)])]
    else: raise ValueError(kind)
    tx,ty=(x+22,y-10) if vertical else (x-28,y-32)
    g += [text(tx,ty,ref,11,'P'),text(tx,ty+19,value,9,'N')]
    a,b=t(-40,0),t(40,0)
    emit(ref,value,package or ('0402' if kind!='D' else '待核对'),x,y,
         [pd(1,'',net1,*a,'T' if vertical else 'L',show=False),pd(2,'',net2,*b,'B' if vertical else 'R',show=False)],g,fitted=fitted)

def at(endpoint): return POSITIONS[endpoint]

def port(endpoint,net=None,distance=55):
    comp=next(c for c in COMPONENTS if c['ref']==endpoint.split('.')[0])
    p=next(p for p in comp['pins'] if p['number']==endpoint.split('.')[1])
    net=net or p['net']; x,y=at(endpoint)
    dx,dy={'L':(-distance,0),'R':(distance,0),'T':(0,-distance),'B':(0,distance)}[p['side']]
    wire((x,y),(x+dx,y+dy))
    if net=='GND': ground(x+dx,y+dy)
    else: label(net,x+dx,y+dy,p['side'])

def rail(endpoints,x,net):
    points=[at(p) for p in endpoints]
    for px,py in points: wire((px,py),(x,py))
    ys=[p[1] for p in points]
    if len(set(ys))>1: wire((x,min(ys)),(x,max(ys)))
    if net=='GND': ground(x,max(ys)+25);wire((x,max(ys)),(x,max(ys)+25))
    else: label(net,x,min(ys))

def start(name,title,subtitle):
    global PAGE,SHAPES
    PAGE=name;SHAPES=[]
    SHAPES.extend([text(50,55,title,23),text(50,85,subtitle,11),rect(25,20,1550,1110)])

def finish():
    # Dots at same-net T junctions; bare wire crossings without endpoints stay unjoined.
    wires=[]
    nodes=set()
    for s in SHAPES:
        v=s.split('~')
        if v[0]=='W':
            coords=list(map(float,v[1].split()));pts=list(zip(coords[::2],coords[1::2]))
            wires.extend(zip(pts,pts[1:]));nodes.update(pts)
    for x,y in sorted(nodes):
        degree=0
        for (ax,ay),(bx,by) in wires:
            if (ax==bx==x and min(ay,by)<=y<=max(ay,by)) or (ay==by==y and min(ax,bx)<=x<=max(ax,bx)):
                degree+=1 if (x,y) in [(ax,ay),(bx,by)] else 2
        if degree>=3: SHAPES.append(f'J~{x}~{y}~2.5~#CC0000~{gid()}~0')
    note(50,1100,'圆形传感板 · SCH-A5 · 2026-09-16', ' ')
    PAGES.append((PAGE,list(SHAPES)))

def mcu():
    start('01_MCU','01  主控最小系统','ESP32-S3-PICO-1：封装内含 Flash、PSRAM 和 40 MHz 晶振；不再外接重复器件。')
    names={1:'LNA_IN',2:'VDD3P3',3:'VDD3P3',4:'CHIP_PU',5:'GPIO0',20:'VDD3P3_RTC',21:'GPIO15',22:'GPIO16',28:'SPICS1 / PSRAM',29:'VDD_SPI_OUT',36:'GPIO48',37:'GPIO47',43:'GPIO38',44:'GPIO39',45:'GPIO40',46:'VDD3P3_CPU',47:'GPIO41',48:'GPIO42',49:'U0TXD / GPIO43',50:'U0RXD / GPIO44',51:'GPIO45',52:'GPIO46',55:'VDDA',56:'VDDA',57:'GND_EP'}
    names.update({i:f'GPIO{i-5}' for i in range(6,20)})
    names.update({i:f'GPIO{i-6}' for i in range(23,28)})
    names.update({i:f'GPIO{i-5} / PSRAM' for i in range(38,43)})
    names.update({i:'NC' for i in [30,31,32,33,34,35,53,54]})
    nets={1:'RF_SOC',4:'MCU_EN',5:'BOOT_N',6:'I2C_SDA',7:'I2C_SCL',9:'MLX_INT',10:'IMU_INT',25:'USB_DM_SOC',26:'USB_DP_SOC',49:'UART_TX',50:'UART_RX',57:'GND'}
    powers=[2,3,20,46,55,56];nets.update({i:'3V3' for i in powers})
    leftnums=powers+[4,5,57,1]+[21,22,8,11,12,13,14,15,16,17,18,19,23,24,27,36,37]
    rightnums=[25,26,6,7,9,10,49,50]+[i for i in range(1,58) if i not in leftnums and i not in [25,26,6,7,9,10,49,50]]
    ic('U1','ESP32-S3-PICO-1-N8R8','LGA-56 + EP / 7x7 mm',610,180,380,900,
       [(i,names[i],nets.get(i),30+j*29,4 if i in powers+[57] else 0) for j,i in enumerate(leftnums)],
       [(i,names[i],nets.get(i),30+j*29) for j,i in enumerate(rightnums)],'保留所有57个端子；PSRAM内部引脚及VDD_SPI输出不外接')
    rail([f'U1.{i}' for i in powers],550,'3V3')
    passive('C20','22uF / 10V','3V3','GND',250,275,'C',True,'0805')
    passive('C21','100nF / 10V','3V3','GND',400,275,'C',True)
    wire((250,235),(250,210),(550,210));wire((400,235),(400,210))
    wire((250,315),(250,350),(400,350),(400,315));ground(325,350)
    # Reset RC adjacent to CHIP_PU; boot pull-up immediately below it.
    eny=at('U1.4')[1];by=at('U1.5')[1]
    passive('R7','10k','3V3','MCU_EN',220,eny)
    passive('C1','1uF / 10V','MCU_EN','GND',380,eny+85,'C',True)
    wire(at('R7.2'),(590,eny));wire((380,eny),(380,eny+45));port('R7.1');port('C1.2',distance=25);label('MCU_EN',290,eny)
    passive('R8','10k','3V3','BOOT_N',220,by+185)
    port('R8.1');wire(at('R8.2'),(480,by+185),(480,by),(590,by));label('BOOT_N',290,by+185)
    port('U1.57',distance=55);port('U1.1',distance=55)
    for i in rightnums:
        if nets.get(i): port(f'U1.{i}',distance=100)
    note(80,780,'启动与下载：', 'J3 引出 EN、BOOT、串口和电源测试焊盘。', '正常启动 BOOT 保持上拉；下载时先拉低 BOOT，再复位。', '未用引脚画不连接标记，不安装扩展排针。', 'C20/C21 紧靠主控电源；裸露焊盘接完整地平面。')
    finish()

def sensors():
    start('02_SENSORS','02  传感器与总线','MLX90393 三轴磁传感器 + LSM6DSOX 六轴 IMU；同页总线直接连线。')
    ic('U2','MLX90393SLQ-ABA-011-RE','UTDFN-8 + EP / 2.5x2 mm',550,220,320,250,
       [(1,'SCL','I2C_SCL',50),(2,'SDA','I2C_SDA',90),(8,'INT','MLX_INT',160),(3,'MISO',None,210)],
       [(4,'VDD_IO','3V3',40),(6,'VDD','3V3',80),(7,'MS/CS','3V3',120),(5,'VSS','GND',180),(9,'EP','GND',220)])
    ic('U3','LSM6DSOXTR','LGA-14 / 2.5x3 mm',550,650,320,340,
       [(13,'SCL','I2C_SCL',50),(14,'SDA','I2C_SDA',90),(4,'INT1','IMU_INT',150),(9,'INT2',None,200),(10,'OCS_Aux',None,240),(11,'SDO_Aux',None,280)],
       [(5,'VDDIO','3V3',40),(8,'VDD','3V3',80),(12,'CS','3V3',120),(1,'SDO/SA0','GND',180),(2,'SDx','GND',210),(3,'SCx','GND',240),(6,'GND','GND',270),(7,'GND','GND',300)])
    passive('R6','4.7k','3V3','I2C_SCL',300,185,vertical=True)
    passive('R5','4.7k','3V3','I2C_SDA',420,185,vertical=True)
    wire((300,145),(300,125),(420,125),(420,145));label('3V3',360,125)
    wire((300,225),(300,700),(530,700));wire((300,270),(530,270));label('I2C_SCL',300,550,'L')
    wire((420,225),(420,740),(530,740));wire((420,310),(530,310));label('I2C_SDA',420,590,'L')
    port('U2.8',distance=25);port('U3.4',distance=60)
    for ref,base,caps,powerpins,gndpins in [('U2',220,['C2','C3'],[4,6,7],[5,9]),('U3',650,['C4','C5'],[5,8,12],[1,2,3,6,7])]:
        rail([f'{ref}.{n}' for n in powerpins],960,'3V3')
        rail([f'{ref}.{n}' for n in gndpins],930,'GND')
        gy=max(at(f'{ref}.{n}')[1] for n in gndpins)
        for cr,x in zip(caps,[1100,1310]):
            passive(cr,'100nF / 10V','3V3','GND',x,base+130,'C',True)
            wire((x,base+90),(x,base+40),(960,base+40))
            wire((x,base+170),(x,gy),(930,gy))
    note(80,1000,'I2C 地址：MLX90393 = 0x10；LSM6DSOX = 0x6A。', '两颗传感器分别保留电源去耦和中断；磁传感器远离充电回路、电池导线和铁磁件。')
    finish()

def usb():
    start('03_USB','03  USB-C 数据与保护','板载接口，从笔杆侧面插线；D+/D− 接 ESP32-S3 原生 USB，无 USB 转串口芯片。')
    entries=[]
    for nums,name,net,starty in [(['A6','B6'],'D+','USB_DP',60),(['A7','B7'],'D−','USB_DM',180),(['A5'],'CC1','CC1',300),(['B5'],'CC2','CC2',390),(['A4','A9','B4','B9'],'VBUS','USB_5V',510),(['A1','A12','B1','B12','SH'],'GND','GND',670)]:
        entries.extend((n,name,net,starty+i*30) for i,n in enumerate(nums))
    ic('J1','USB4105-GF-A-060','USB-C 16 contacts + SH',190,170,235,830,[('A8','SBU1',None,300),('B8','SBU2',None,350)],entries)
    rail(['J1.A6','J1.B6'],500,'USB_DP');rail(['J1.A7','J1.B7'],540,'USB_DM')
    passive('R3','22Ω','USB_DP','USB_DP_SOC',1130,230)
    passive('R4','22Ω','USB_DM','USB_DM_SOC',1130,350)
    wire((500,230),(1090,230));wire((540,350),(1090,350));port('R3.2',distance=140);port('R4.2',distance=140)
    ic('U6','TPD2EUSB30ADRTR','SOT-DRT-3 / 1.0x0.8 mm',760,450,265,160,[(1,'IO1','USB_DP',40),(2,'IO2','USB_DM',80)],[(3,'GND','GND',120)])
    wire((640,230),(640,490),(740,490));wire((690,350),(690,530),(740,530));port('U6.3',distance=55)
    for rr,dr,net,piny,xx in [('R1','D2','CC1',470,550),('R2','D3','CC2',560,610)]:
        # separate compact local branch below the connector; protectors are shown beside CC resistors.
        cy=730 if rr=='R1' else 930
        passive(rr,'5.1k / 1%',net,'GND',xx+140,cy,vertical=True)
        ic(dr,'TPD1E10B06DPYR','X1SON-2 / 1.0x0.6 mm',xx+420,cy-35,190,70,[(1,'IO',net,35)],[(2,'GND','GND',35)])
        wire((445,piny),(xx,piny),(xx,cy-70),(xx+140,cy-70),(xx+140,cy-40))
        wire((xx+140,cy-70),(xx+380,cy-70),(xx+380,cy),(xx+400,cy));port(f'{rr}.2',distance=25);port(f'{dr}.2',distance=40)
    rail([f'J1.{i}' for i in ['A4','A9','B4','B9']],475,'USB_5V')
    rail([f'J1.{i}' for i in ['A1','A12','B1','B12','SH']],495,'GND')
    ic('D1','TPD1E10B06DPYR','X1SON-2 / 1.0x0.6 mm',1230,500,220,80,[(1,'IO','USB_5V',40)],[(2,'GND','GND',40)])
    port('D1.1',distance=55);port('D1.2',distance=35)
    note(1090,990,'CC1、CC2 各自 5.1 kΩ 下拉。', '保护器靠近接口，回地尽量短。', 'USB 2.0 设备；不支持 USB-PD。')
    finish()

def power():
    start('04_POWER','04  充电、供电切换与开关','充电和自动切换参考 XIAO；3.3 V 暂保留小尺寸 LDO，实际续航、压降和温升待样板验证。')
    # XIAO reverse PMOS: D=BAT, S=VSYS, G=VBUS. Explicit D/G/S prevents symbol ambiguity.
    # Conventional horizontal P-MOS symbol: D on left, S on right, gate below.
    emit('Q1','LP0404N3T5G','SOT-883-3 / 1.0x0.6 mm',490,220,
         [pd(1,'D','BAT_P',350,220,'L'),pd(2,'G','USB_5V',350,280,'L'),pd(3,'S','VSYS',630,220,'R')],
         [text(450,132,'Q1',12,'P'),text(450,152,'LP0404N3T5G',10,'N'),
          line([(370,220),(450,220)]),line([(550,220),(610,220)]),
          line([(450,220),(450,240)]),line([(550,240),(550,220)]),
          line([(450,255),(550,255)]),line([(370,280),(500,280),(500,255)]),
          line([(450,240),(460,240)]),line([(485,240),(515,240)]),line([(540,240),(550,240)]),
          line([(500,240),(500,218),(550,218),(550,220)]),
          line([(493,228),(500,218),(507,228)]),
          line([(450,220),(450,180),(480,180)]),line([(510,180),(550,180),(550,220)]),
          line([(480,170),(480,190),(500,180),(480,170)]),line([(500,168),(500,192)]),line([(500,180),(510,180)])],
         'D=1接电池，G=2接USB，S=3接系统；体二极管BAT_P至VSYS；按XIAO焊盘编号核对封装')
    port('Q1.1',distance=130)
    passive('D4','LMBR4010BST5G','VSYS','USB_5V',500,400,'D',package='SOD-882 / 1.0x0.6 mm')
    wire(at('Q1.3'),(700,220),(700,340),(420,340),(420,400),(460,400))
    wire((540,400),(650,400),(650,520),(270,520),(270,280),(350,280));label('USB_5V',270,400,'L')
    passive('R9','100k','USB_5V','GND',270,600,vertical=True)
    wire((270,520),(270,560));port('R9.2',distance=25)
    ic('U5','TLV75533PDRVR','WSON-6 + EP / 2x2 mm',1030,180,240,200,[(6,'IN','VSYS',40),(4,'EN','REG_EN',110),(2,'NC',None,160)],[(1,'OUT','3V3',40),(3,'GND','GND',100),(7,'EP','GND',130),(5,'NC',None,170)])
    wire((700,220),(1010,220));label('VSYS',750,220)
    passive('C9','1uF / 10V','VSYS','GND',850,300,'C',True)
    wire((850,220),(850,260));port('C9.2',distance=25)
    passive('C10','1uF / 10V','3V3','GND',1430,300,'C',True)
    wire((1290,220),(1430,220),(1430,260));label('3V3',1430,220);port('C10.2',distance=25)
    rail(['U5.3','U5.7'],1340,'GND')
    ic('SW1','电源开关焊盘','SWITCH_WIRE_3PAD_COMPACT',890,480,220,150,[(3,'开 / VSYS','VSYS',40),(1,'关 / GND','GND',110)],[(2,'公共端 / EN','REG_EN',70)])
    port('SW1.3',distance=55);port('SW1.1',distance=55)
    wire(at('SW1.2'),(1180,550),(1180,430),(970,430),(970,290),(1010,290));label('REG_EN',1180,430)
    note(1190,515,'拨到“关”：关闭 3.3 V。','USB 充电仍可工作。','开关可安装在笔杆上，','板上只保留三个焊盘。')
    ic('U4','SGM40567-4.2XG/TR','WLCSP-0.92x1.16-6B / 0.4 mm',500,760,310,220,[('A2','VIN','USB_5V',40),('C1','IREF','IREF_SET',120),('B1','F','GND',180)],[('A1','BAT','BAT_P',40),('B2','nCHG',None,110),('C2','GND','GND',180)],'F必须接地以选择4.2V；电池必须自带保护；无电芯温度检测')
    passive('C6','1uF / 16V','USB_5V','GND',190,860,'C',True)
    wire((190,820),(190,800),(480,800));label('USB_5V',190,800);port('C6.2',distance=30)
    passive('R10','220k / 1%','IREF_SET','GND',365,940,vertical=True)
    wire((480,880),(365,880),(365,900));port('R10.2',distance=30)
    wire((480,940),(450,940),(450,995));ground(450,995);port('U4.C2',distance=45)
    passive('C7','1uF / 10V','BAT_P','GND',990,860,'C',True)
    wire((830,800),(990,800),(990,820));label('BAT_P',990,800);port('C7.2',distance=30)
    ic('J2','单节锂电池焊盘','BATTERY_WIRE_2PAD_COMPACT',1220,770,220,160,[(1,'电池正极','BAT_P',30),(2,'电池负极','GND',130)],[],'外接带过充、过放及短路保护的4.2V单节电池')
    wire((990,800),(1200,800));wire((990,900),(1200,900))
    note(60,1040,'R10 = 220 kΩ，标称充电电流约 109 mA；须与最终电芯允许充电电流匹配。', '不安装充电指示灯；充电由芯片自动管理。保留保护电池要求，但不增加原复杂 USB 唤醒控制。')
    finish()

def rf_debug():
    start('05_RF_DEBUG','05  外接天线与调试焊盘','FPC 天线贴在塑料笔杆内壁，通过短同轴线连接 U.FL；不使用板载 PCB 天线。')
    passive('R30','0Ω / 射频串联','RF_SOC','RF_ANT',660,300)
    passive('C30','匹配预留 / 不装','RF_SOC','GND',430,420,'C',True,fitted=False)
    passive('C31','匹配预留 / 不装','RF_ANT','GND',870,420,'C',True,fitted=False)
    wire((250,300),(620,300));label('RF_SOC',250,300,'L');wire((430,300),(430,380))
    ic('ANT1','U.FL-R-SMT-1 + FXP75.07.0045B','U.FL-R-SMT-1 / Hirose',1110,260,320,180,[(1,'射频信号','RF_ANT',40)],[(2,'外壳','GND',80),(3,'外壳','GND',130)])
    wire((700,300),(1090,300));wire((870,300),(870,380));wire((430,460),(430,510),(870,510),(870,460));ground(660,510);rail(['ANT1.2','ANT1.3'],1500,'GND')
    note(160,590,'π 型匹配网络默认只装 0 Ω，两个并联电容不装；最终按整机射频测试调谐。','信号线按板厂层叠做 50 Ω；连接器、天线和电池位置共同参与真实圆板布局。')
    ic('J3','下载与测试焊盘','DEBUG_POGO_6PAD_1MM',560,730,330,240,
       [(1,'GND','GND',40),(2,'3V3','3V3',75),(3,'EN','MCU_EN',110),(4,'BOOT','BOOT_N',145),(5,'TX','UART_TX',180),(6,'RX','UART_RX',215)],[])
    for n in range(1,7): port(f'J3.{n}',distance=120)
    note(1010,790,'无常驻排针，使用测试焊盘。','USB 下载可复用原有开发流程。','首次上电、故障恢复时使用','BOOT / EN 与串口测试点。')
    finish()

def svg(shapes):
    out=['<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1150" viewBox="0 0 1600 1150"><rect width="1600" height="1150" fill="white"/>']
    def tx(x,y,s,c,size,anchor='start'):
        out.append(f'<text x="{x}" y="{y}" fill="{c}" font-size="{size}" font-family="Arial,PingFang SC,sans-serif" text-anchor="{anchor}">{html.escape(s)}</text>')
    def shape(s):
        v=s.split('~');cmd=v[0]
        if cmd=='LIB':
            for child in s.split('#@$')[1:]:shape(child)
        elif cmd=='T':tx(v[2],v[3],v[12],v[5],float(v[7].replace('pt',''))*1.333,v[14])
        elif cmd=='R':out.append(f'<rect x="{v[1]}" y="{v[2]}" width="{v[5]}" height="{v[6]}" stroke="{v[7]}" fill="none"/>')
        elif cmd in ['PL','W']:out.append(f'<polyline points="{v[1]}" fill="none" stroke="{v[2]}" stroke-width="1.5"/>')
        elif cmd=='P':
            b=s.split('^^');q=b[2].split('~');out.append(f'<path d="{q[0]}" fill="none" stroke="{q[1]}"/>')
            for child in b[3:5]:
                q=child.split('~')
                if q[0]=='1':tx(q[1],q[2],q[4],q[8],float(q[7].replace('pt',''))*1.333,q[5])
        elif cmd=='N':tx(v[8],v[9],v[5],v[4],12,v[7])
        elif cmd=='O':out.append(f'<path d="{v[4]}" stroke="{v[5]}"/>')
        elif cmd=='J':out.append(f'<circle cx="{v[1]}" cy="{v[2]}" r="2.5" fill="{v[4]}"/>')
        else:raise ValueError(cmd)
    for s in shapes:shape(s)
    return '\n'.join(out+['</svg>'])

def enable_pulldown():
    # Append after generating all original pages, preserving their existing object IDs.
    # The external break-before-make switch may be absent or briefly open.
    global PAGE, SHAPES
    PAGE='04_POWER'
    SHAPES=next(shapes for name,shapes in PAGES if name==PAGE)
    passive('R11','100k','REG_EN','GND',1180,655,vertical=True)
    wire((1180,550),(1180,615))
    port('R11.2',distance=20)
    SHAPES.append(f'J~1180~550~2.5~#CC0000~{gid()}~0')
    note(1240,655,'R11：开关未接或切换时', 'EN 默认拉低，防止悬空。')

def main():
    for fn in [mcu,sensors,usb,power,rf_debug]:fn()
    enable_pulldown()
    OUT.mkdir(exist_ok=True)
    sheets=[];manifest=[]
    for name,shapes in PAGES:
        doc=dict(head={'docType':'1','editorVersion':'6.5.51','newgId':True,'c_para':{'Prefix Start':'1'},'c_spiceCmd':None},canvas='CA~1600~1150~#FFFFFF~yes~#CCCCCC~5~1600~1150~line~5~pixel~5~0~0',shape=shapes,BBox={'x':25,'y':20,'width':1550,'height':1110},colors={})
        fname=f'round_sensor_SCH_A5_{name}.json';sname=name.lower()+'.svg'
        (OUT/fname).write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n')
        (OUT/sname).write_text(svg(shapes))
        title=shapes[0].split('~')[12]
        sheets.append(dict(docType='1',title=title,description='',dataStr=doc))
        manifest.append(dict(name=name,display_title=title,file=fname,svg=sname,title=title,refs=[c['ref'] for c in COMPONENTS if c['sheet']==name]))
    project=dict(editorVersion='6.5.57',docType='5',title='圆形传感板_SCH_A5_XIAO精简版',description='五页直接连线原理图；检查状态见本版原生回读报告，尚未完成整板电气/制造及PCB放行',colors={},schematics=sheets)
    def write(name,data): (OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    write('round_sensor_SCH_A5_multi.json',project)
    nets=defaultdict(list)
    for c in COMPONENTS:
        for p in c['pins']:
            if p['net'] is not None:nets[p['net']].append(c['ref']+'.'+p['number'])
    write('design_netlist.json',dict(revision=REV,components=COMPONENTS,nets=dict(nets)))
    write('bom_draft.json',[{k:v for k,v in c.items() if k!='pins'} for c in COMPONENTS])
    write('sheets_manifest.json',dict(revision=REV,sheet_count=len(sheets),cross_page_rule='同名网络标签全局连接；局部元件显式导线连接',sheets=manifest))
    links=''.join(f'<a href="#{m["name"]}">{m["title"]}</a>' for m in manifest)
    sections=''.join(f'<section id="{m["name"]}"><h2>{m["title"]}</h2><img src="{m["svg"]}" alt="{m["title"]}"></section>' for m in manifest)
    (OUT/'preview.html').write_text(f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>圆形传感板 SCH-A5</title><style>body{{margin:0;background:#eef2f5;color:#203745;font:15px system-ui}}header{{padding:20px 30px;background:white}}nav{{display:flex;gap:25px;flex-wrap:wrap}}a{{color:#146782}}main{{padding:20px}}section{{margin:0 auto 24px;max-width:1600px}}h2{{font-size:18px}}img{{width:100%;background:white;border:1px solid #cbd4db}}</style><header><h1>SCH-A5 · XIAO 式精简原理图</h1><p>局部直接连线 · 五页中文 · PICO + IMU + MLX90393 · 仅为原理图审查版，非投板文件</p><nav>{links}</nav></header><main>{sections}</main></html>')
    print(json.dumps(dict(revision=REV,sheets=len(sheets),components=len(COMPONENTS),pins=sum(len(c['pins']) for c in COMPONENTS),nets=len(nets))))

if __name__=='__main__':main()
