"""Create an editable EasyEDA Standard schematic using its documented JSON format.

Embedded symbols carry real electrical pins. Footprint binding is intentionally
left empty until actual land patterns are reviewed. This is schematic revision
SCH-A1, independent of the earlier component-body packing study.
"""
from pathlib import Path
from collections import defaultdict, OrderedDict
import html
import json
import math
import uuid

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "easyeda_std"
OUT.mkdir(exist_ok=True)
SHAPES, COMPONENTS = [], []
SHEET_SHAPES = OrderedDict()
CURRENT_SHEET = None
UID = 0

SHEETS = OrderedDict([
    ("01_MCU", dict(file="round_sensor_SCH_A1_01_MCU.json", svg="01_mcu.svg",
                    title="01  ESP32-S3 MINIMUM SYSTEM", region=(60,160,1080,1180))),
    ("02_SENSORS", dict(file="round_sensor_SCH_A1_02_SENSORS.json", svg="02_sensors.svg",
                        title="02  I2C SENSORS", region=(1200,160,1100,1180))),
    ("03_USB", dict(file="round_sensor_SCH_A1_03_USB.json", svg="03_usb.svg",
                    title="03  USB-C DATA + ESD", region=(2360,160,1180,1180))),
    ("04_POWER", dict(file="round_sensor_SCH_A1_04_POWER.json", svg="04_power.svg",
                      title="04  BATTERY / POWER PATH / CHARGING", region=(60,1400,1680,1400))),
    ("05_RF_BATTERY_DEBUG", dict(file="round_sensor_SCH_A1_05_RF_BATTERY_DEBUG.json",
                                 svg="05_rf_bringup.svg", title="05  RF / BATTERY / BRING-UP",
                                 region=(1800,1400,1740,1400))),
])


def select_sheet(name):
    global CURRENT_SHEET
    assert name in SHEETS
    CURRENT_SHEET = name
    SHEET_SHAPES.setdefault(name, [])


def add_shape(value):
    assert CURRENT_SHEET is not None
    SHAPES.append(value)
    SHEET_SHAPES[CURRENT_SHEET].append(value)


def add_shapes(values):
    for value in values:
        add_shape(value)


def gid():
    global UID
    UID += 1
    return f"gge{UID}"


def txt(x, y, value, size=12, mark="L", color="#243746", anchor="start"):
    assert not any(c in str(value) for c in ("~", "`", "#@$", "^^"))
    return f"T~{mark}~{x}~{y}~0~{color}~Arial~{size}pt~~~~comment~{value}~1~{anchor}~{gid()}~0~"


def rectangle(x, y, w, h, color="#A00000", fill="none"):
    return f"R~{x}~{y}~~~{w}~{h}~{color}~1~0~{fill}~{gid()}~0"


def line(points, color="#A00000", command="PL"):
    return f"{command}~{' '.join(str(a) for p in points for a in p)}~{color}~1~0~none~{gid()}~0"


def label(x, y, net, side):
    return f"N~{x}~{y}~0~#006A49~{net}~{gid()}~{'end' if side=='L' else 'start'}~{x}~{y-3}~Arial~9pt~0"


def pin(number, name, x, y, side, etype=0, show=True):
    dx = 20 if side == "L" else -20
    anchor = "start" if side == "L" else "end"
    return (f"P~show~{etype}~{number}~{x}~{y}~{180 if side=='L' else 0}~{gid()}~0"
            f"^^{x}~{y}^^M {x} {y} h {dx}~#880000"
            f"^^{int(show)}~{x+dx+(4 if side=='L' else -4)}~{y+4}~0~{name}~{anchor}~Arial~9pt~#000000"
            f"^^1~{x+dx/2}~{y-4}~0~{number}~middle~Arial~7pt~#000000"
            "^^0~0~0^^0~M 0 0")


def connect(x, y, net, side):
    if net is None:
        add_shape(f"O~{x}~{y}~{gid()}~M{x-3},{y-3} L{x+3},{y+3} M{x+3},{y-3} L{x-3},{y+3}~#CC0000~0")
    else:
        end = x + (-45 if side == "L" else 45)
        add_shape(line([(x, y), (end, y)], "#008800", "W"))
        add_shape(label(end, y, net, side))


def emit(ref, value, package, x, y, shapes, pins, notes="", fitted=True):
    # Embedded symbol IDs are deterministic, without claiming an online library ID.
    lib_id = uuid.uuid5(uuid.NAMESPACE_URL, "fyp/SCH-A1/"+ref).hex
    attrs = {"package":"", "nameAlias":"Value", "Value":value,
             "spicePre":ref.rstrip("0123456789"), "spiceSymbolName":value,
             "Manufacturer Part":value, "Package candidate":package,
             "Review":notes or "Footprint not bound; review before PCB", "Assembly":"FIT" if fitted else "DNP"}
    para="`".join(str(z) for pair in attrs.items() for z in pair)+"`"
    head=f"LIB~{x}~{y}~{para}~0~0~{gid()}~{lib_id}~~0~~yes~yes"
    add_shape(head+"#@$"+"#@$".join(shapes))
    COMPONENTS.append(dict(ref=ref,value=value,package_candidate=package,footprint_bound=False,
                           fitted=fitted,notes=notes,sheet=CURRENT_SHEET,pins=pins))


def ic(ref, value, package, x, y, left, right, width=300, notes=""):
    height=max(len(left),len(right))*30+30
    s=[rectangle(x,y,width,height,fill="#FFFDF2"),txt(x,y-30,ref,13,"P"),txt(x,y-10,value,12,"N")]
    pins=[]
    for side,items in [("L",left),("R",right)]:
        for i,(num,name,net,etype) in enumerate(items):
            px=x-20 if side=="L" else x+width+20
            py=y+30+i*30
            s.append(pin(str(num),name,px,py,side,etype))
            pins.append(dict(number=str(num),name=name,net=net,x=px,y=py,side=side,electrical=etype))
            connect(px,py,net,side)
    emit(ref,value,package,x,y,s,pins,notes)


def passive(ref,value,net1,net2,x,y,kind="R",package="0402 / metric 1005",notes="",fitted=True):
    s=[txt(x-20,y-40,ref,11,"P"),txt(x-20,y-20,value,10,"N")]
    if kind=="C":
        s += [line([(x-4,y-10),(x-4,y+10)]),line([(x+4,y-10),(x+4,y+10)]),
              line([(x-20,y),(x-4,y)]),line([(x+4,y),(x+20,y)])]
    elif kind=="SW":
        s += [line([(x-20,y),(x+16,y-12)]),line([(x+16,y),(x+20,y)])]
    else:
        s += [rectangle(x-20,y-7,40,14)]
    pins=[]
    for num,net,side,px in [(1,net1,"L",x-40),(2,net2,"R",x+40)]:
        s.append(pin(str(num),str(num),px,y,side,0,False))
        pins.append(dict(number=str(num),name=str(num),net=net,x=px,y=y,side=side,electrical=0))
        connect(px,y,net,side)
    emit(ref,value,package,x,y,s,pins,notes,fitted)


def section(x,y,w,h,title,subtitle):
    add_shapes([rectangle(x,y,w,h,"#94A8B6"),txt(x+20,y+30,title,18),txt(x+20,y+55,subtitle,11)])


def note(x,y,*lines):
    for i,t in enumerate(lines): add_shape(txt(x,y+23*i,t,11,color="#805023"))


def p(n,name,net,t=0): return (n,name,net,t)


def build():
    select_sheet("01_MCU")
    add_shape(txt(60,65,"ROUND SENSOR / SCH-A1 / 01 MCU",28))
    add_shape(txt(60,105,"ESP32-S3 minimum system | cross-page nets use global same-name labels",15))
    section(60,160,1080,1180,"01  ESP32-S3 MINIMUM SYSTEM","All 57 package terminals explicit; internal Flash / PSRAM / crystal retained")

    names={1:"LNA_IN",2:"VDD3P3",3:"VDD3P3",4:"CHIP_PU",5:"GPIO0",20:"VDD3P3_RTC",
           21:"GPIO15 / X32K_P",22:"GPIO16 / X32K_N",28:"SPICS1 / PSRAM",29:"VDD_SPI_OUT",
           36:"SPICLK_N / GPIO48",37:"SPICLK_P / GPIO47",38:"GPIO33 / PSRAM",39:"GPIO34 / PSRAM",
           40:"GPIO35 / PSRAM",41:"GPIO36 / PSRAM",42:"GPIO37 / PSRAM",43:"GPIO38",44:"MTCK / GPIO39",
           45:"MTDO / GPIO40",46:"VDD3P3_CPU",47:"MTDI / GPIO41",48:"MTMS / GPIO42",49:"U0TXD / GPIO43",
           50:"U0RXD / GPIO44",51:"GPIO45 STRAP",52:"GPIO46 STRAP",55:"VDDA",56:"VDDA",57:"GND_EP"}
    names.update({i:f"GPIO{i-5}" for i in range(6,20)})
    names.update({i:f"GPIO{i-6}" for i in range(23,28)})
    names.update({i:"NC" for i in [30,31,32,33,34,35,53,54]})
    nets={1:"RF_SOC",4:"MCU_EN",5:"BOOT_N",6:"I2C_SDA",7:"I2C_SCL",9:"MLX_INT",10:"IMU_INT",
          12:"VBUS_PRESENT_N",15:"CHARGE_ALLOW",16:"CHG_EN1",17:"CHG_EN2",18:"PGOOD_N",19:"CHG_N",
          25:"USB_DM_SOC",26:"USB_DP_SOC",49:"UART_TX",50:"UART_RX",57:"GND"}
    nets.update({i:"3V3" for i in [2,3,20,46,55,56]})
    pins=[p(i,names[i],nets.get(i),4 if i in [2,3,20,46,55,56,57] else (1 if i==4 else 3)) for i in range(1,58)]
    ic("U1","ESP32-S3-PICO-1-N8R8","LGA-56 + EP / 7x7 mm",350,280,pins[:29],pins[29:],400,
       "Pins 28,38-42 internal PSRAM; 29 output rail not tied to 3V3; unused straps use documented defaults")
    passive("R7","10k","3V3","MCU_EN",300,1230)
    passive("C1","1uF / 10V","MCU_EN","GND",780,1230,"C")

    select_sheet("02_SENSORS")
    add_shape(txt(1200,65,"ROUND SENSOR / SCH-A1 / 02 SENSORS",28))
    add_shape(txt(1200,105,"MLX90393 + LSM6DSOX | I2C and interrupt nets continue by label",15))
    section(1200,160,1100,1180,"02  I2C SENSORS","Separate data-ready signals; 3.3 V; MLX 0x10 and IMU 0x6A")
    ic("U2","MLX90393SLQ-ABA-011-RE","UTDFN-8 + EP / 2.5x2 mm",1450,280,
       [p(1,"SCL","I2C_SCL",1),p(2,"SDA","I2C_SDA",3),p(3,"MISO",None,2),p(4,"VDD_IO","3V3",4),p(5,"VSS","GND",4)],
       [p(6,"VDD","3V3",4),p(7,"MS/CS","3V3",1),p(8,"INT","MLX_INT",2),p(9,"EP [pad 9]","GND",4)],300,
       "7-bit I2C 0x10; exposed pad assigned 9 for later footprint mapping")
    passive("C2","100nF / 10V","3V3","GND",2080,340,"C")
    passive("C3","100nF / 10V","3V3","GND",2080,440,"C")
    ic("U3","LSM6DSOXTR","LGA-14 / 2.5x3 mm",1450,690,
       [p(1,"SDO/SA0","GND",3),p(2,"SDx","GND",3),p(3,"SCx","GND",3),p(4,"INT1","IMU_INT",2),
        p(5,"VDDIO","3V3",4),p(6,"GND","GND",4),p(7,"GND","GND",4)],
       [p(8,"VDD","3V3",4),p(9,"INT2",None,2),p(10,"OCS_Aux",None,3),p(11,"SDO_Aux",None,3),
        p(12,"CS","3V3",1),p(13,"SCL","I2C_SCL",1),p(14,"SDA","I2C_SDA",3)],300,"Mode 1; address 0x6A")
    for ref,yy in [("C4",750),("C5",850)]: passive(ref,"100nF / 10V","3V3","GND",2080,yy,"C")
    passive("R5","4.7k","3V3","I2C_SDA",1470,1120)
    passive("R6","4.7k","3V3","I2C_SCL",2050,1120)
    note(1230,1230,"Each 100 nF capacitor at its own supply pin; common GND.","GPIO4 = MLX DRDY; GPIO5 = IMU INT1. Stamp samples separately.")

    select_sheet("03_USB")
    add_shape(txt(2360,65,"ROUND SENSOR / SCH-A1 / 03 USB",28))
    add_shape(txt(2360,105,"Side-entry USB-C data/power | USB 2.0 device, no PD",15))
    section(2360,160,1180,1180,"03  USB-C DATA + ESD","USB 2.0 device / no PD; independent CC pull-downs; USB VBUS detection")
    usb=[]
    for row in ["A","B"]:
        for n,name,net in [(1,"GND","GND"),(4,"VBUS","USB_5V"),(5,"CC",f"CC{1 if row=='A' else 2}"),
                           (6,"D+","USB_DP"),(7,"D-","USB_DM"),(8,"SBU",None),(9,"VBUS","USB_5V"),(12,"GND","GND")]:
            usb.append(p(f"{row}{n}",f"{row}{n} {name}",net))
    ic("J1","USB4105-GF-A-060","USB-C 16 signal contacts + SH",2550,280,usb[:8],usb[8:]+[p("SH","SHIELD","GND")],270,
       "Four shell anchors share footprint pad SH; USB2 signal contacts paired by net")
    ic("U6","TPD2EUSB30ADRTR","SOT DRT 3 pins / 1.0x0.8 mm body",3200,280,
       [p(1,"IO1","USB_DP"),p(2,"IO2","USB_DM")],[p(3,"GND","GND",4)],210)
    passive("R1","5.1k / 1%","CC1","GND",2640,740)
    passive("R2","5.1k / 1%","CC2","GND",3160,740)
    passive("R3","22R initial","USB_DP","USB_DP_SOC",2640,870)
    passive("R4","22R initial","USB_DM","USB_DM_SOC",3160,870)
    for ref,net,xx,yy in [("D1","USB_5V",2640,1000),("D2","CC1",3160,1000),("D3","CC2",2640,1130)]:
        passive(ref,"TPD1E10B06DPYR",net,"GND",xx,yy,"TVS","X1SON DPY-2 / 0402", "Bidirectional ESD; pins interchangeable; no PD/CC overvoltage controller")
    note(2390,1240,"VBUS is 5 V only; see Q2 for isolated VBUS detection.","USB-only cold start under the 100 mA pre-enumeration limit requires testing.")

    select_sheet("04_POWER")
    add_shape(txt(60,1320,"ROUND SENSOR / SCH-A1 / 04 POWER",28))
    add_shape(txt(60,1360,"Protected 1S battery | about 2 h target | charge disabled by default",15))
    section(60,1400,1680,1400,"04  BATTERY / POWER PATH / CHARGING","Charge disabled by default; NTC link DNP until the cell and temperature network are approved")
    ic("U4","BQ24074RGTR","VQFN-16 + EP / RGT 3x3 mm",340,1540,
       [p(1,"TS","TS_CELL",1),p(2,"BAT","BAT_P",4),p(3,"BAT","BAT_P",4),p(4,"CE_N","CE_N",1),
        p(5,"EN2","CHG_EN2",1),p(6,"EN1","CHG_EN1",1),p(7,"PGOOD_N","PGOOD_N",2),p(8,"VSS","GND",4),p(17,"EP [pad 17]","GND",4)],
       [p(9,"CHG_N","CHG_N",2),p(10,"OUT","VSYS",4),p(11,"OUT","VSYS",4),p(12,"ILIM","ILIM_SET",1),
        p(13,"IN","USB_5V",4),p(14,"TMR",None,1),p(15,"ITERM",None,1),p(16,"ISET","ISET_SET",1)],300,
       "NTC network unapproved; TMR/ITERM open = default timer/termination; protected 4.2 V cell required")
    ic("U5","TLV75533PDRVR","WSON DRV-6 + EP / 2x2 mm",1180,1540,
       [p(6,"IN","VSYS",4),p(4,"EN","REG_EN",1),p(3,"GND","GND",4),p(7,"EP [pad 7]","GND",4)],
       [p(1,"OUT","3V3",4),p(2,"NC",None),p(5,"NC",None)],260,"No boost; battery low-voltage behavior and dropout need testing")
    passive("SW1","POWER / SPST","VSYS","REG_EN",1230,1760,"SW","Mechanical switch or wired switch pads","Opens LDO EN only; battery still attached to charger")
    passive("R20","100k","REG_EN","GND",1230,1850)
    # NPN interface prevents a dead 3V3 rail from enabling charge or receiving VSYS injection.
    ic("Q1","MMBT3904","SOT-23 / B1 E2 C3",1150,1990,
       [p(1,"BASE","CE_BASE",1)],[p(3,"COLLECTOR","CE_N",2),p(2,"EMITTER","GND",4)],200,
       "CHARGE_ALLOW high enables charging only if BQ input and TS permit")
    power_passives=[
        ("C6","1uF / 16V","USB_5V","GND","C"),("C7","10uF / 10V","BAT_P","GND","C"),
        ("C8","10uF / 10V","VSYS","GND","C"),("C9","1uF / 10V","VSYS","GND","C"),
        ("C10","1uF / 10V","3V3","GND","C"),("R9","3.24k / 1%","ILIM_SET","GND","R"),
        ("R10","8.66k / 1%","ISET_SET","GND","R"),("R11","10k","VSYS","CE_N","R"),
        ("R12","100k","CHG_EN1","GND","R"),("R13","100k","CHG_EN2","GND","R"),
        ("R14","10k","3V3","PGOOD_N","R"),("R15","10k","3V3","CHG_N","R"),
        ("R21","10k","CHARGE_ALLOW","CE_BASE","R"),("R22","47k","CE_BASE","GND","R")]
    # First six above/below charger, others in evenly spaced rows at the bottom.
    positions=[(300,1970),(750,1970),(300,2080),(750,2080)]
    positions += [(xx,yy) for yy in [2230,2340,2450,2560] for xx in [300,820,1390]]
    for spec,(xx,yy) in zip(power_passives,positions):
        ref,val,a,b,kind=spec
        package="0603 / metric 1608" if ref in ["C7","C8"] else "0402 / metric 1005"
        passive(ref,val,a,b,xx,yy,kind,package)
    note(90,2680,"ISET about 103 mA typical; confirm cell rating and tolerances. BAT/OUT caps require DC-bias review.",
         "EN2 EN1: 00 = USB100; 01 = USB500 after host permits; 11 = suspend. No automatic 500 mA assumption.",
         "Switch OFF turns off 3V3 and disables charge. It does not disconnect the battery protection/charger.")

    select_sheet("05_RF_BATTERY_DEBUG")
    add_shape(txt(1800,1320,"ROUND SENSOR / SCH-A1 / 05 RF + BATTERY + DEBUG",28))
    add_shape(txt(1800,1360,"Ceramic antenna option | cell/NTC interface | recovery pads",15))
    section(1800,1400,1740,1400,"05  RF / BRING-UP / BUILD NOTES","No PCB footprints bound in SCH-A1; geometry studies do not cover this revision")
    ic("ANT1","2450AT18D0100001E","4-terminal 1206 ceramic antenna",2100,1540,
       [p(1,"FEED","RF_ANT")],[p(2,"GND","GND"),p(3,"GND","GND"),p(4,"TUNE/GND","ANT_TUNE")],300)
    passive("R30","0R / RF series","RF_SOC","RF_ANT",2060,1750)
    passive("C30","DNP / RF tune","RF_SOC","GND",2650,1750,"C",fitted=False)
    passive("C31","DNP / RF tune","RF_ANT","GND",3190,1750,"C",fitted=False)
    passive("R31","0R / tune option","ANT_TUNE","GND",2060,1860,notes="May replace with L/C after RF review")
    note(1840,1940,"Use 50 ohm feed; matching values require the actual PCB, enclosure, battery and hand grip.",
         "Antenna keepout applies through the board stack and to components on BOTH sides.")
    ic("J2","PROTECTED_1S_BATTERY","3 solder pads / pitch and pad size TBD",3060,1520,
       [p(1,"PACK+","BAT_P",4),p(2,"PACK-","GND",4),p(3,"CELL_NTC","NTC_PACK",1)],[],230,
       "350-400 mAh budget; real cell NTC between pins 3 and 2; no fixed-resistor temperature bypass")
    passive("R16","DNP / TS series TBD","TS_CELL","NTC_PACK",2060,2070,notes="Fit only after cell NTC curve and charge temperature calculation",fitted=False)
    passive("R17","DNP / TS parallel TBD","NTC_PACK","GND",2650,2070,notes="Parallel adjustment only with actual cell NTC; not a standalone TS bypass",fitted=False)
    note(1840,2140,"R16 is OPEN as delivered: charging is inhibited. Choose the battery and NTC network before fitting it.")

    # VBUS sense through NPN, avoiding a VBUS divider feeding an unpowered GPIO.
    ic("Q2","MMBT3904","SOT-23 / B1 E2 C3",2060,2260,
       [p(1,"BASE","VBUS_BASE",1)],[p(3,"COLLECTOR","VBUS_PRESENT_N",2),p(2,"EMITTER","GND",4)],220)
    passive("R23","100k","USB_5V","VBUS_BASE",2630,2290)
    passive("R24","100k","VBUS_BASE","GND",3170,2290)
    passive("R25","10k","3V3","VBUS_PRESENT_N",2630,2400)
    passive("R8","10k","3V3","BOOT_N",3170,2400)
    ic("J3","POGO_RECOVERY","6 probe pads; not a pin header",2060,2510,
       [p(1,"GND","GND"),p(2,"3V3","3V3"),p(3,"EN","MCU_EN")],
       [p(4,"BOOT","BOOT_N"),p(5,"UART_TX","UART_TX"),p(6,"UART_RX","UART_RX")],250,
       "Ground BOOT while resetting EN to recover download mode; do not inject external 3V3 into LDO")
    passive("C20","22uF / 10V","3V3","GND",2630,2570,"C","0805 / metric 2012","SiP bulk reserve; capacitance under 3.3 V bias must be checked")
    passive("C21","100nF / 10V","3V3","GND",3170,2570,"C")
    note(1840,2700,"GPIO7 reads VBUS_PRESENT_N. Firmware must detach USB when VBUS is absent and handle USB suspend.",
         "GPIO6 battery ADC is intentionally unconnected pending switched sensing; no off-state back-power path.",
         "Cell protection remains required. Brownout / low-battery cutoff and USB-only boot need bench verification.")
    add_shape(txt(1800,2860,"SCHEMATIC REVIEW REV SCH-A1 | Footprints / PCB / RF tuning / cell NTC / hardware tests pending",16,color="#AA3333"))


def render_svg(doc):
    """Render only the documented primitives emitted above, for a portable preview."""
    output=['<svg xmlns="http://www.w3.org/2000/svg" width="3600" height="2900" viewBox="0 0 3600 2900">',
            '<rect width="3600" height="2900" fill="white"/>']
    def path(d,col,width=1): output.append(f'<path d="{html.escape(d)}" stroke="{col}" stroke-width="{width}" fill="none"/>')
    def text(x,y,s,col,size,anchor="start"):
        output.append(f'<text x="{x}" y="{y}" fill="{col}" font-size="{size}" font-family="Arial,sans-serif" text-anchor="{anchor}">{html.escape(s)}</text>')
    def shape(s):
        v=s.split("~");cmd=v[0]
        if cmd=="LIB":
            for sub in s.split("#@$")[1:]: shape(sub)
        elif cmd=="T": text(v[2],v[3],v[12],v[5],float(v[7].replace("pt",""))*1.333,v[14])
        elif cmd=="R": output.append(f'<rect x="{v[1]}" y="{v[2]}" width="{v[5]}" height="{v[6]}" stroke="{v[7]}" fill="{v[10]}"/>')
        elif cmd in ["PL","W"]: output.append(f'<polyline points="{v[1]}" stroke="{v[2]}" fill="none" stroke-width="{v[3]}"/>')
        elif cmd=="P":
            blocks=s.split("^^"); pp=blocks[2].split("~");path(pp[0],pp[1])
            for b in blocks[3:5]:
                q=b.split("~")
                if q[0]=="1":text(q[1],q[2],q[4],"#000000",float(q[7].replace("pt",""))*1.333,q[5])
        elif cmd=="N":text(v[8],v[9],v[5],v[4],12,v[7])
        elif cmd=="O":path(v[4],v[5])
        else:raise ValueError(cmd)
    for s in doc["shape"]:shape(s)
    output.append('</svg>')
    return "\n".join(output)


def main():
    build()
    def make_doc(shapes, bbox=None):
        return dict(head={"docType":"1","editorVersion":"6.5.51","newgId":True,
                          "c_para":{"Prefix Start":"1"},"c_spiceCmd":None},
                    canvas="CA~3600~2900~#FFFFFF~yes~#CCCCCC~5~3600~2900~line~5~pixel~5~0~0",
                    shape=shapes,BBox=bbox or {"x":50,"y":20,"width":3500,"height":2870},colors={})
    doc=make_doc(SHAPES)
    (OUT/"round_sensor_SCH_A1.json").write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n")
    (OUT/"round_sensor_SCH_A1.svg").write_text(render_svg(doc))
    sheet_manifest=[]
    project_sheets=[]
    for name,meta in SHEETS.items():
        x,y,w,h=meta["region"]
        page_doc=make_doc(SHEET_SHAPES[name], {"x":x,"y":max(20,y-140),"width":w,"height":h+160})
        (OUT/meta["file"]).write_text(json.dumps(page_doc,ensure_ascii=False,indent=2)+"\n")
        project_sheets.append(dict(docType="1",title=name,description="",dataStr=page_doc))
        svg=render_svg(page_doc).replace('width="3600" height="2900" viewBox="0 0 3600 2900"',
            f'width="{w}" height="{h+160}" viewBox="{x} {max(20,y-140)} {w} {h+160}"',1)
        (OUT/meta["svg"]).write_text(svg)
        refs=[c["ref"] for c in COMPONENTS if c["sheet"]==name]
        sheet_nets=sorted({p0["net"] for c in COMPONENTS if c["sheet"]==name for p0 in c["pins"] if p0["net"]})
        sheet_manifest.append(dict(name=name,file=meta["file"],title=meta["title"],refs=refs,nets=sheet_nets))
    (OUT/"sheets_manifest.json").write_text(json.dumps(dict(revision="SCH-A1",sheet_count=len(SHEETS),
        cross_page_rule="Same-name net labels are global in one EasyEDA Standard multi-page schematic",
        sheets=sheet_manifest),ensure_ascii=False,indent=2)+"\n")
    project_doc=dict(editorVersion="6.5.57",docType="5",title="round_sensor_SCH_A1",
                     description="Five-sheet SCH-A1",colors={},schematics=project_sheets)
    (OUT/"round_sensor_SCH_A1_multi.json").write_text(json.dumps(project_doc,ensure_ascii=False,indent=2)+"\n")
    nets=defaultdict(list)
    for c in COMPONENTS:
        for p0 in c["pins"]:
            if p0["net"] is not None:nets[p0["net"]].append(c["ref"]+"."+p0["number"])
    (OUT/"design_netlist.json").write_text(json.dumps(dict(revision="SCH-A1",components=COMPONENTS,nets=dict(nets)),indent=2)+"\n")
    (OUT/"bom_draft.json").write_text(json.dumps([{k:v for k,v in c.items() if k!="pins"} for c in COMPONENTS],indent=2)+"\n")
    print(json.dumps(dict(sheets=len(SHEETS),components=len(COMPONENTS),pins=sum(len(c["pins"]) for c in COMPONENTS),nets=len(nets),shapes=len(SHAPES))))


if __name__=="__main__": main()
