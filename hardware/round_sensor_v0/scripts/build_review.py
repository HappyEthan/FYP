"""Engineering review only: not an EDA exporter or manufacturing release."""
from pathlib import Path
import json
import math
import hashlib
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor, Color
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'generated'
OUT.mkdir(exist_ok=True)
pdfmetrics.registerFont(TTFont('STSong-Light','/System/Library/Fonts/Supplemental/Arial Unicode.ttf'))
W, H = 842, 595
PDF_OUT = ROOT.parents[1] / 'output' / 'pdf' / 'round_sensor_v0_review.pdf'
PDF_OUT.parent.mkdir(parents=True, exist_ok=True)
C = canvas.Canvas(str(PDF_OUT), pagesize=(W, H))
C.setTitle('圆形磁触觉传感板 V0 - 工程审阅草案 / NOT FOR FABRICATION')
C.setAuthor('FYP engineering draft')
INK = HexColor('#193046')
BLUE = HexColor('#246ba6')
RED = HexColor('#aa3333')
GRID = HexColor('#bcc7ce')
page_no = 0


def text(x, y, value, size=11, color=INK):
    C.setFillColor(color)
    C.setFont('STSong-Light', size)
    C.drawString(x, H-y, str(value).replace('–','-').replace('—','-'))


def para(x, y, value, width=750, size=11, leading=17):
    line = ''
    for ch in value:
        if ch == '\n' or pdfmetrics.stringWidth(line+ch, 'STSong-Light', size) > width:
            text(x,y,line,size)
            y += leading
            line = '' if ch == '\n' else ch
        else:
            line += ch
    if line:
        text(x,y,line,size)
        y += leading
    return y


def start(title, sub):
    global page_no
    page_no += 1
    C.setFillColor(HexColor('#f8fafb'))
    C.rect(0,0,W,H,fill=1,stroke=0)
    text(30,35,title,21)
    text(30,59,sub,10)
    C.setStrokeColor(GRID)
    C.line(30,H-72,W-30,H-72)
    text(30,H-18,'DRAFT V0 | 未布线 / 未 ERC、DRC / 未硬件验证 / 禁止直接生产',10,RED)
    text(W-70,H-18,f'{page_no:02}',10)


def finish():
    C.showPage()


def table(headers, rows, x=30, y=90, widths=None, rowh=22):
    widths = widths or [100,150,510]
    for j,h in enumerate(headers):
        text(x+sum(widths[:j])+5,y+14,h,10,BLUE)
    y += rowh
    for row in rows:
        C.setStrokeColor(GRID)
        C.line(x,H-y,x+sum(widths),H-y)
        for j,v in enumerate(row):
            text(x+sum(widths[:j])+5,y+15,v,9.5)
        y += rowh
    return y


connections = {
    'U1 ESP32-S3-PICO-1-N8R8': [
        ('1','LNA_IN','RF matching → ANT1; values TBD'),
        ('2,3,20,46,55,56','Power inputs','3V3; local decoupling on all supply domains'),
        ('57','GND / exposed pad','GND; ground/thermal vias per EDA review'),
        ('4','CHIP_PU / EN','10k to 3V3; 1uF to GND; reset test point'),
        ('5','GPIO0','10k to 3V3; boot-to-GND test point'),
        ('6','GPIO1','I2C_SDA → U2.2, U3.14'),
        ('7','GPIO2','I2C_SCL → U2.1, U3.13'),
        ('9','GPIO4','MLX_INT ← U2.8'),
        ('10','GPIO5','IMU_INT1 ← U3.4'),
        ('11','GPIO6 / ADC1','BAT_SENSE via divider; isolation and values TBD'),
        ('15','GPIO10','CHARGE_CE → U4.4; active LOW'),
        ('16,17','GPIO11, GPIO12','CHG_EN1 → U4.6; CHG_EN2 → U4.5'),
        ('18,19','GPIO13, GPIO14','PGOOD ← U4.7; CHG ← U4.9; 3V3 pull-ups'),
        ('25','GPIO19 / USB_D-','22R initial → USB_D-; tune against signal integrity'),
        ('26','GPIO20 / USB_D+','22R initial → USB_D+; tune against signal integrity'),
        ('49,50','UART0 TX, RX','Recovery/debug test points; plus GND'),
        ('28,38–42','Internal PSRAM signals','DO NOT CONNECT for N8R8'),
        ('29','VDD_SPI','Do not connect to 3V3; follow SiP reference'),
        ('30–35,53,54','NC','No external connection'),
        ('Other pins','Unused GPIO','Unconnected in V0; verify strapping defaults')],
    'U2 MLX90393SLQ-ABA-011-RE': [
        ('1','SCL/SCLK','I2C_SCL'),('2','SDA/MOSI','I2C_SDA'),
        ('3','MISO','Unconnected in I2C mode'),('4','VDD_IO','3V3 + 100nF to GND'),
        ('5','VSS','GND'),('6','VDD','3V3 + 100nF to GND'),
        ('7','MS/CS','3V3 selects I2C'),('8','INT','U1 GPIO4'),
        ('EP','Exposed pad','GND; exact land/stencil design pending')],
    'U3 LSM6DSOXTR (Mode 1)': [
        ('1','SDO/SA0','GND; I2C address 0x6A'),('2,3','SDx, SCx','GND'),
        ('4','INT1','U1 GPIO5'),('5','VDDIO','3V3 + 100nF'),('6,7','GND','GND'),
        ('8','VDD','3V3 + 100nF'),('9','INT2','Unconnected / optional test point'),
        ('10','OCS_Aux','Unconnected; solder pad remains'),('11','SDO_Aux','Unconnected in Mode 1'),
        ('12','CS','3V3 selects I2C'),('13','SCL','I2C_SCL'),('14','SDA','I2C_SDA')],
    'U4 BQ24074RGTR': [
        ('1','TS','Battery NTC; network must match cell charge-temperature limits'),
        ('2,3','BAT','Protected 1S battery positive; 4.7–47uF, start with 10uF'),
        ('4','CE','GPIO10; active LOW; defined pull-up to 3V3; startup review required'),
        ('5,6','EN2, EN1','GPIO12, GPIO11; external pull-downs; default USB100'),
        ('7','PGOOD','GPIO13; open drain, pull up to 3V3'),
        ('8,EP','VSS, thermal pad','GND; both must connect'),
        ('9','CHG','GPIO14; open drain, pull up to 3V3'),
        ('10,11','OUT','VSYS → U5.6; start with 10uF to GND'),
        ('12','ILIM','3.24k candidate to GND; recheck worst-case current limit'),
        ('13','IN','USB VBUS; 1uF to GND, direct input capacitance <10uF'),
        ('14','TMR','Unconnected = default safety timers; DO NOT ground'),
        ('15','ITERM','Unconnected = default termination thresholds'),
        ('16','ISET','8.66k / 1% candidate to GND; ~103mA typical, cell approval pending')],
    'U5 TLV75533PDRVR': [
        ('1','OUT','3V3; >=1uF effective design check, plus SiP bulk capacitance'),
        ('2,5','NC','Unconnected'),('3,EP','GND, thermal pad','GND'),
        ('4','EN','Defined enable; user switch / undervoltage strategy TBD'),
        ('6','IN','VSYS; >=1uF at input; no boost capability')],
    'J1 GCT USB4105': [
        ('A4,A9,B4,B9','VBUS','U4 IN; VBUS protection review'),
        ('A1,A12,B1,B12','GND','GND'),('SH','Shell','Ground/ESD layout review; mechanical retention'),
        ('A5','CC1','Separate 5.1k / 1% to GND'),('B5','CC2','Separate 5.1k / 1% to GND'),
        ('A6,B6','D+','Tie at connector; USB ESD → series resistor → U1.26'),
        ('A7,B7','D-','Tie at connector; USB ESD → series resistor → U1.25'),
        ('A8,B8','SBU1,SBU2','Unconnected for USB 2.0 device')],
    'U6 TPD2EUSB30A': [('1','D+','USB_D+'),('2','D-','USB_D-'),('3','GND','Short ground return at J1')],
    'ANT1 2450AT18D0100001E': [
        ('1','Feed','50-ohm feed; shunt-series-shunt matching reserve, values TBD'),
        ('2,3','GND','Follow manufacturer land geometry, not a generic 2-pad antenna'),
        ('4','GND / tuning branch','Manufacturer tuning L/C option; final topology/value RF review')]
}
(OUT/'connections.json').write_text(json.dumps(connections,ensure_ascii=False,indent=2)+'\n')


def parts(radius):
    # Coordinates: mm, common top projection, +Y down. Actual chip bodies only.
    return [
        dict(ref='U1',label='S3-PICO',side='F',x=-3.5,y=.9,w=7,h=7),
        dict(ref='J1',label='USB-C',side='F',x=radius-.2-3.675,y=0,w=7.35,h=8.94),
        dict(ref='ANT1',label='ANT',side='F',x=-1,y=-radius+1.8,w=3.2,h=1.6),
        dict(ref='U2',label='MLX',side='B',x=0,y=0,w=2,h=2.5),
        dict(ref='U3',label='IMU',side='B',x=-4,y=0,w=3,h=2.5),
        dict(ref='U4',label='CHG',side='B',x=-1,y=4.2,w=3,h=3),
        dict(ref='U5',label='LDO',side='B',x=-5.3,y=3.6,w=2,h=2),
    ]


def bounds(p, margin=.25):
    return (p['x']-p['w']/2-margin,p['y']-p['h']/2-margin,
            p['x']+p['w']/2+margin,p['y']+p['h']/2+margin)


def overlap(a,b):
    return min(a[2],b[2]) > max(a[0],b[0])+1e-8 and min(a[3],b[3]) > max(a[1],b[1])+1e-8


def geom(diameter):
    r=diameter/2
    pp=parts(r)
    errors=[]
    zone=(-3,-r,1,-r+6)
    for p in pp:
        b=bounds(p)
        if p['ref']!='J1':
            if max(math.hypot(x,y) for x in (b[0],b[2]) for y in (b[1],b[3]))>r-.15:
                errors.append(f'{p["ref"]}: body + 0.25mm margin exceeds board inner clearance')
        if p['ref']!='ANT1' and overlap(b,zone):
            errors.append(f'{p["ref"]}: intersects provisional RF region')
    for i,a in enumerate(pp):
        for b in pp[i+1:]:
            if a['side']==b['side'] and overlap(bounds(a),bounds(b)):
                errors.append(f'{a["ref"]}/{b["ref"]}: same-side body envelopes overlap')
    # GCT / KiCad shell holes: local X=±4.32, local Y=-3.105,+1.075;
    # 90-degree rotation points mouth toward +X. Rotated pad rectangles below.
    holes=[]
    for yy,length in [(-3.105,2.1),(1.075,1.8)]:
        for xx in [-4.32,4.32]:
            x,y=r-.2-3.675+yy,-xx
            b=(x-length/2-.15,y-.5-.15,x+length/2+.15,y+.5+.15)
            holes.append(b)
            if max(math.hypot(u,v) for u in (b[0],b[2]) for v in (b[1],b[3]))>r-.15:
                errors.append('J1: shell pad envelope exceeds board edge clearance')
            for p in pp:
                if p['side']=='B' and overlap(bounds(p),b):
                    errors.append(f'J1/{p["ref"]}: shell pad/backside envelope overlap')
    return dict(pcb_diameter_mm=diameter,major_body_check_pass=not errors,errors=errors,
        usb_shell_radial_envelope_diameter_mm=round(2*math.hypot(r-.2,4.47),2),
        usb_edge_flat_x_mm=r-.2,
        scope='Major bodies + 0.25mm margin, provisional RF zone, USB shell pads ONLY. NOT full PCB/DRC.',
        parts=pp,rf_region_mm=zone,usb_shell_pad_bounds_mm=holes)


studies=[geom(d) for d in [16,18,20]]
(OUT/'geometry_checks.json').write_text(json.dumps(studies,ensure_ascii=False,indent=2)+'\n')


def board(g,side,cx,cy,scale=12):
    r=g['pcb_diameter_mm']/2
    def xy(x,y): return cx+x*scale,H-(cy+y*scale)
    def rect(b,color,alpha=.22):
        C.setFillColor(Color(color.red,color.green,color.blue,alpha))
        C.setStrokeColor(color)
        C.rect(cx+b[0]*scale,H-cy-b[3]*scale,(b[2]-b[0])*scale,(b[3]-b[1])*scale,fill=1,stroke=1)
    C.setLineWidth(.9);C.setStrokeColor(INK);C.setFillColor(HexColor('#f0f5f2'))
    C.circle(cx,H-cy,r*scale,fill=1,stroke=1)
    # Shallow flat at the USB mouth: remove the 0.2mm circular cap.
    flat=g['usb_edge_flat_x_mm']
    half=math.sqrt(r*r-flat*flat)
    C.setFillColor(HexColor('#f8fafb')); C.setStrokeColor(HexColor('#f8fafb'))
    C.rect(cx+flat*scale,H-cy-half*scale-.7,(r-flat)*scale+1,2*half*scale+1.4,fill=1,stroke=0)
    C.setStrokeColor(INK);C.line(*xy(flat,-half),*xy(flat,half))
    rect(g['rf_region_mm'],HexColor('#b58314'))
    for p in g['parts']:
        if p['side']==side:
            rect(bounds(p,0),BLUE if side=='F' else HexColor('#36826d'))
            C.setFillColor(INK);C.setFont('STSong-Light',9)
            C.drawCentredString(cx+p['x']*scale,H-cy-p['y']*scale+3,p['ref'])
            C.drawCentredString(cx+p['x']*scale,H-cy-p['y']*scale-9,p['label'])
    for b in g['usb_shell_pad_bounds_mm']:
        rect(b,RED,.22)
    C.setStrokeColor(GRID)
    C.line(*xy(-r,0),*xy(r,0));C.line(*xy(0,-r),*xy(0,r))
    C.setStrokeColor(INK)
    C.line(cx-r*scale,H-cy-r*scale-18,cx+r*scale,H-cy-r*scale-18)
    C.setFillColor(INK);C.setFont('STSong-Light',10)
    C.drawCentredString(cx,H-cy-r*scale-32,f'PCB diameter {2*r:.0f} mm')


start('圆形磁触觉传感板 V0','USB 侧插 + 板载 BLE 天线 + 电池工作约 2 小时 | 工程审阅稿')
para(30,100,'当前交付是电路连接定义和主要器件尺寸研究。不是已经布线的 PCB，也不是可下单的生产原理图。',size=14)
rows=[('主控','ESP32-S3-PICO-1-N8R8','保留 S3；晶振 / Flash / PSRAM 集成'),
      ('磁触觉','MLX90393SLQ-ABA-011','2×2.5 mm；I2C 地址 0x10，区别于旧板'),
      ('姿态','LSM6DSOXTR','六轴；I2C 地址 0x6A，预留 INT1'),
      ('通信','USB4105 + 2450AT18D','USB-C 在板边；陶瓷天线在另一侧'),
      ('电源','BQ24074 + TLV75533','电源路径 / 充电 + 3.3 V 线性稳压'),
      ('电池','单节受保护电池 + NTC','350–400 mAh 初步预算，尺寸和电芯待选')]
table(['功能','候选方案','关键边界'],rows,y=155,widths=[85,235,460],rowh=34)
para(30,400,'尚未完成：完整外围器件放置、原理图 ERC、PCB 布线/DRC、RF 匹配、电池温度网络、欠压关机、热和续航测试。',size=12)
para(30,458,'按官方尺寸保留必要供电、去耦、启动/复位和下载接口；不保留 XIAO 排针及摄像头扩展接口。',size=11)
finish()

start('主要器件尺寸研究：18 mm 圆板候选','两面均为同一顶视投影；不是制造镜像图；外围 RC / ESD / 开关等尚未全部放置')
g=studies[1]
text(135,99,'正面：主控 / USB / 天线',12);text(488,99,'背面：传感器 / 电源',12)
board(g,'F',230,260,12);board(g,'B',602,260,12)
para(30,430,'黄色区域：暂定 RF 净空。红色区域：USB 壳体固定脚及背面避让。矩形按封装名义外形绘制；几何检查另加 0.25 mm 余量。',size=11)
para(30,472,f'18 mm PCB 的 USB 壳体径向包络约 {g["usb_shell_radial_envelope_diameter_mm"]} mm；侧窗可做局部避让，不能直接按 18 mm 当作完整装配包络。',size=11)
para(30,514,'磁传感器暂放圆心；磁体位置、敏感点方向与距离还需结合触角结构确认。',size=11)
finish()

start('尺寸检查与 2 小时续航预算','可复算的工程假设，不是最小尺寸证明或实测续航')
table(['板框','本组主要器件检查','含 USB 壳体径向包络'],[
    (f'{g["pcb_diameter_mm"]} mm','通过有限几何检查' if g['major_body_check_pass'] else '当前摆法存在冲突',f'{g["usb_shell_radial_envelope_diameter_mm"]} mm') for g in studies],widths=[110,330,340],rowh=32)
para(30,242,'16 mm 当前摆法存在主控越界、天线区冲突和 USB 固定脚附近空间不足。完整检查结果可查看 geometry_checks.json；并未穷举其它摆法。',size=11)
para(30,300,'即使 18 mm 主要器件检查通过，也不能证明完整电路放得下。16 mm 只说明当前摆法有冲突，不证明其它布局不可行。',size=11)
table(['400 mAh 电池场景','假设可用容量 70%','估算工作时长'],[
    ('平均电流 60 mA','280 mAh','4.67 h'),('平均电流 90 mA','280 mAh','3.11 h'),('平均电流 120 mA','280 mAh','2.33 h')],y=350,widths=[240,260,280],rowh=27)
para(30,486,'计算：容量 ≥ 平均电流 × 2 h / 0.70。120 mA 场景约需 343 mAh。平均电流与低压提前停机损失未知，350–400 mAh 只是选型起点。',size=11)
finish()

start('电源结构与限制','线性供电避免开关电感，但不等于已消除磁干扰')
boxes=[(35,110,145,58,'USB-C / 5 V','输入限流'),(236,110,160,58,'BQ24074','PowerPath / 充电'),(452,110,155,58,'TLV75533','VSYS → 3V3'),(663,110,145,58,'S3 + sensors','3V3'),(235,238,161,58,'Protected 1S battery','电池 + NTC')]
for x,y,w,h,a,b in boxes:
    C.setFillColor(HexColor('#eaf1f6'));C.setStrokeColor(BLUE)
    C.rect(x,H-y-h,w,h,fill=1)
    text(x+10,y+23,a,11);text(x+10,y+43,b,10)
for x1,x2 in [(180,236),(396,452),(607,663)]:
    C.setStrokeColor(BLUE);C.line(x1,H-139,x2,H-139)
    C.line(x2-6,H-135,x2,H-139);C.line(x2-6,H-143,x2,H-139)
C.line(315,H-168,315,H-238)
text(407,246,'电池充电电流初步约 103 mA',11)
text(407,267,'NTC 网络与电池温区必须匹配',11)
para(30,332,'USB 默认 USB100；枚举并获得允许后才能切换 USB500，且需要处理挂起。USB 电源插入/拔出时，电源路径管理应避免反灌并维持系统供电。',size=11)
para(30,390,'LDO 没有升压功能。低电量时，电池路径压降 + LDO 压降会影响 3V3。暂以约 3.5–3.6 V 作为待验证的停机阈值起点，不能按放到 3.0 V 计算可用容量。',size=11)
para(30,448,'充电电流、NTC、硬件欠压和电源开关尚未定稿。使用受保护电池包；充电芯片不替代电池包安全保护。不得依据本草案直接连接裸电芯。',size=11)
finish()

for name in ['U1 ESP32-S3-PICO-1-N8R8','U2 MLX90393SLQ-ABA-011-RE','U3 LSM6DSOXTR (Mode 1)','U4 BQ24074RGTR','U5 TLV75533PDRVR','J1 GCT USB4105','ANT1 2450AT18D0100001E']:
    start(name,'逐针连接草案 | 表内数字为封装脚号，不是 GPIO 号 | 须在 EDA 中复核')
    rows=connections[name]
    table(['封装脚','信号','连接 / 约束'],rows,widths=[92,195,493],rowh=21)
    if name.startswith('U2'):
        para(30,350,'I2C 上拉：SDA、SCL 各预留一组 4.7 kΩ 到 3V3；根据总线电容和目标速率复核。初版可从 100 kHz 调通，再验证 400 kHz。',size=11)
        para(30,420,'UTDFN-8 的引脚与 QFN-16 不兼容。本型号地址固定为 0x10；更换订货后缀必须重新确认地址。',size=11)
    if name.startswith('U3'):
        para(30,430,'使用各自 DRDY 的采样时间戳；顺序读取 MLX 和 IMU 不代表两颗传感器同时完成转换。',size=11)
    if name.startswith('J1'):
        table(['U6 封装脚','TPD2EUSB30A','连接'],connections['U6 TPD2EUSB30A'],y=333,widths=[92,195,493],rowh=26)
        para(30,479,'另需审核 CC/VBUS ESD、电源保护和屏蔽壳回流。USB 差分走线、过孔和串联电阻位置需正式 PCB 检查。',size=11)
    if name.startswith('ANT1'):
        para(30,254,'官方第 5 页有 20 mm 圆板参考布局，但注明仅供参考且没有对应评估板。迁移到 18 mm 圆板、加 USB 和电池后，匹配数值不能直接照抄。',size=12)
        para(30,335,'射频应在最终外壳、装入电池、USB 插入/拔出和手握状态下测试。不能仅凭能搜索到蓝牙就判断 RF 设计合格。',size=12)
    finish()

start('交付边界、复核清单与来源','先验证电路与装配，再决定最小直径；本稿不包含生产文件')
checks=['确认电池具体型号、允许充电电流/温度、NTC 曲线、尺寸及欠压策略。',
        '核对全部符号/封装和坐标轴，补齐 RC、ESD、电源开关及测试焊盘。',
        '在 KiCad 或其它正式 EDA 中完成原理图 ERC、完整布线、DRC、DFM 和 3D 干涉检查。',
        '测 USB 供电、拔线切换、BLE 工作和低电量状态；再测至少 2 小时完整工作流。',
        '对 BLE 发射、USB 插拔和充电分别测磁传感器偏置/噪声，并验证 RF 匹配。']
y=98
for i,s in enumerate(checks,1): y=para(30,y,f'{i}. {s}',size=11,leading=17)+12
sources=[('Espressif S3-PICO-1','https://www.espressif.com/sites/default/files/documentation/esp32-s3-pico-1_datasheet_en.pdf'),
('Melexis MLX90393 Rev 012','https://www.melexis.com/-/media/files/documents/datasheets/mlx90393-datasheet-melexis.pdf'),
('ST LSM6DSOX','https://www.st.com/resource/en/datasheet/lsm6dsox.pdf'),
('GCT USB4105','https://gct.co/files/drawings/usb4105.pdf'),
('Johanson antenna Rev 5','https://www.johansontechnology.com/docs/3791/Antenna-2450AT18D0100001E-Rev5.0.pdf'),
('TI BQ24074 / TLV755P / TPD2EUSB30A','https://www.ti.com/product/BQ24074')]
text(30,350,'可点击的官方来源；本地资料哈希见 generated/source_manifest.json',11,BLUE)
for i,(label,url) in enumerate(sources):
    yy=376+i*25
    text(30,yy,label,10,BLUE)
    C.linkURL(url,(30,H-yy-4,780,H-yy+12),relative=0)
finish()
C.save()

manifest={p.name:dict(bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
          for p in sorted((ROOT/'references').iterdir()) if p.is_file() and p.stat().st_size}
(OUT/'source_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({'pdf_pages':page_no,'geometry':[{'diameter':s['pcb_diameter_mm'],'major_only_pass':s['major_body_check_pass'],'errors':s['errors']} for s in studies]},ensure_ascii=False,indent=2))
