"""Create an editable EasyEDA Standard schematic using its documented JSON format.

Embedded symbols carry real electrical pins. Footprint binding is intentionally
left empty until actual land patterns are reviewed. This is schematic revision
SCH-A2, independent of the earlier component-body packing study.
"""
from pathlib import Path
from collections import defaultdict, OrderedDict
from heapq import heappop, heappush
import html
import json
import math
import uuid

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "easyeda_std"
OUT.mkdir(exist_ok=True)
SHAPES, COMPONENTS = [], []
SHEET_SHAPES = OrderedDict()
CONNECTIONS = defaultdict(list)
OBSTACLES = defaultdict(list)
CURRENT_SHEET = None
UID = 0
REV = "SCH-A2"
REV_FILE = REV.replace("-", "_")
GRID = 5
LABEL_ONLY_NETS = {"GND", "3V3", "USB_5V", "VSYS", "BAT_P"}

SHEETS = OrderedDict([
    ("01_MCU", dict(file="round_sensor_SCH_A2_01_MCU.json", svg="01_mcu.svg",
                    title="01  ESP32-S3 最小系统", region=(60,160,1080,1180))),
    ("02_SENSORS", dict(file="round_sensor_SCH_A2_02_SENSORS.json", svg="02_sensors.svg",
                        title="02  I2C 传感器", region=(1200,160,1100,1180))),
    ("03_USB", dict(file="round_sensor_SCH_A2_03_USB.json", svg="03_usb.svg",
                    title="03  USB-C 数据与 ESD 防护", region=(2360,160,1180,1180))),
    ("04_POWER", dict(file="round_sensor_SCH_A2_04_POWER.json", svg="04_power.svg",
                      title="04  电池、电源路径与充电", region=(60,1400,1680,1400))),
    ("05_RF_BATTERY_DEBUG", dict(file="round_sensor_SCH_A2_05_RF_BATTERY_DEBUG.json",
                                 svg="05_rf_bringup.svg", title="05  射频、电池与调试",
                                 region=(1680,1400,2100,1520))),
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
        CONNECTIONS[CURRENT_SHEET].append(dict(pin=(x, y), stub=(end, y), net=net, side=side))


def _cells_on_path(points):
    cells = set()
    for a, b in zip(points, points[1:]):
        x1, y1 = a
        x2, y2 = b
        if x1 == x2:
            lo, hi = sorted((y1, y2))
            cells.update((x1, y) for y in range(lo, hi + GRID, GRID))
        elif y1 == y2:
            lo, hi = sorted((x1, x2))
            cells.update((x, y1) for x in range(lo, hi + GRID, GRID))
        else:
            raise ValueError(f"Non-Manhattan schematic path: {a} -> {b}")
    return cells


def _compress_path(points):
    """Remove collinear grid nodes without relying on point uniqueness."""
    if len(points) <= 2:
        return points
    out = [points[0]]
    for i in range(1, len(points) - 1):
        ax, ay = out[-1]
        bx, by = points[i]
        cx, cy = points[i + 1]
        if (ax == bx == cx) or (ay == by == cy):
            continue
        out.append((bx, by))
    out.append(points[-1])
    return out


def _route_grid(start, targets, blocked, bounds):
    """A* route from start to any existing same-net target on a 5-unit grid."""
    x0, y0, x1, y1 = bounds
    targets = set(targets)
    if start in targets:
        return [start]

    def heuristic(point):
        x, y = point
        return min(abs(x - tx) + abs(y - ty) for tx, ty in targets)

    queue = [(heuristic(start), 0, start, None)]
    best = {(start, None): 0}
    parent = {}
    finish = None
    while queue:
        _, cost, point, direction = heappop(queue)
        if point in targets:
            finish = (point, direction)
            break
        x, y = point
        for dx, dy, new_dir in ((GRID, 0, "H"), (-GRID, 0, "H"), (0, GRID, "V"), (0, -GRID, "V")):
            nxt = (x + dx, y + dy)
            if not (x0 <= nxt[0] <= x1 and y0 <= nxt[1] <= y1):
                continue
            if nxt in blocked and nxt not in targets:
                continue
            turn = 12 if direction is not None and direction != new_dir else 0
            new_cost = cost + GRID + turn
            state = (nxt, new_dir)
            if new_cost >= best.get(state, 10**12):
                continue
            best[state] = new_cost
            parent[state] = (point, direction)
            heappush(queue, (new_cost + heuristic(nxt), new_cost, nxt, new_dir))
    if finish is None:
        return None
    path = [finish[0]]
    state = finish
    while state[0] != start:
        state = parent[state]
        path.append(state[0])
    path.reverse()
    return _compress_path(path)


def route_connections():
    """Draw continuous same-sheet nets and label every pin endpoint defensively."""
    for sheet, meta in SHEETS.items():
        select_sheet(sheet)
        x, y, w, h = meta["region"]
        bounds = (x - 40, max(20, y - 90), x + w + 40, y + h + 20)
        conns = CONNECTIONS[sheet]
        by_net = defaultdict(list)
        occupied = defaultdict(set)

        # Every pin gets a visible outward stub. Reserve those cells first so
        # independently routed nets cannot cross or touch another pin stub.
        for conn in conns:
            add_shape(line([conn["pin"], conn["stub"]], "#008800", "W"))
            cells = _cells_on_path([conn["pin"], conn["stub"]])
            conn["cells"] = cells
            occupied[conn["net"]].update(cells)
            by_net[conn["net"]].append(conn)

        obstacle_cells = set()
        for bx0, by0, bx1, by1 in OBSTACLES[sheet]:
            for gx in range(int(math.floor((bx0 - 5) / GRID)) * GRID,
                            int(math.ceil((bx1 + 5) / GRID)) * GRID + GRID, GRID):
                for gy in range(int(math.floor((by0 - 5) / GRID)) * GRID,
                                int(math.ceil((by1 + 5) / GRID)) * GRID + GRID, GRID):
                    obstacle_cells.add((gx, gy))

        # Route dense nets first. Power rails remain conventional repeated
        # labels; signal and control nets are continuous within each sheet.
        for net, endpoints in sorted(by_net.items(), key=lambda item: (-len(item[1]), item[0])):
            if net in LABEL_ONLY_NETS or len(endpoints) == 1:
                for conn in endpoints:
                    add_shape(label(*conn["stub"], net, conn["side"]))
                continue

            tree = {endpoints[0]["stub"]}
            reserved_stub_cells = set().union(*(conn["cells"] for conn in endpoints))
            routed_ok = True
            for conn in endpoints[1:]:
                start = conn["stub"]
                other_net_cells = set().union(*(cells for other, cells in occupied.items() if other != net))
                blocked = obstacle_cells | other_net_cells | (reserved_stub_cells - tree - {start})
                blocked.discard(start)
                path = _route_grid(start, tree, blocked, bounds)
                if path is None:
                    routed_ok = False
                    break
                if len(path) > 1:
                    add_shape(line(path, "#008800", "W"))
                    cells = _cells_on_path(path)
                    occupied[net].update(cells)
                    tree.update(cells)

            if routed_ok:
                # EasyEDA's imported-wire parser can split a T-junction into
                # more than one physical net unless every branch is explicitly
                # named.  Keep the visible continuous wire, and repeat the
                # same label at each pin endpoint as an electrical safeguard.
                for conn in endpoints:
                    add_shape(label(*conn["stub"], net, conn["side"]))
            else:
                # Conservative fallback: preserve electrical intent through
                # same-name labels if the automatic obstacle-aware route fails.
                for conn in endpoints:
                    add_shape(label(*conn["stub"], net, conn["side"]))


def emit(ref, value, package, x, y, shapes, pins, notes="", fitted=True, body_bbox=None):
    # Embedded symbol IDs are deterministic, without claiming an online library ID.
    lib_id = uuid.uuid5(uuid.NAMESPACE_URL, f"fyp/{REV}/"+ref).hex
    attrs = {"package":"", "nameAlias":"Value", "Value":value,
             "spicePre":ref.rstrip("0123456789"), "spiceSymbolName":value,
             "Manufacturer Part":value, "Package candidate":package,
             "审查备注":notes or "封装未绑定；转入 PCB 前复核", "装配状态":"装配" if fitted else "不装配"}
    para="`".join(str(z) for pair in attrs.items() for z in pair)+"`"
    head=f"LIB~{x}~{y}~{para}~0~0~{gid()}~{lib_id}~~0~~yes~yes"
    add_shape(head+"#@$"+"#@$".join(shapes))
    COMPONENTS.append(dict(ref=ref,value=value,package_candidate=package,footprint_bound=False,
                           fitted=fitted,notes=notes,sheet=CURRENT_SHEET,pins=pins))
    if body_bbox is not None:
        OBSTACLES[CURRENT_SHEET].append(body_bbox)


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
    emit(ref,value,package,x,y,s,pins,notes,body_bbox=(x, y, x + width, y + height))


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
    emit(ref,value,package,x,y,s,pins,notes,fitted,body_bbox=(x - 22, y - 12, x + 22, y + 12))


def section(x,y,w,h,title,subtitle):
    add_shapes([rectangle(x,y,w,h,"#94A8B6"),txt(x+20,y+30,title,18),txt(x+20,y+55,subtitle,11)])


def note(x,y,*lines):
    for i,t in enumerate(lines): add_shape(txt(x,y+23*i,t,11,color="#805023"))


def p(n,name,net,t=0): return (n,name,net,t)


def build():
    select_sheet("01_MCU")
    add_shape(txt(60,65,"圆形传感器 / SCH-A2 / 01 主控",28))
    add_shape(txt(60,105,"ESP32-S3 最小系统 | 跨页网络使用全局同名网络标签",15))
    section(60,160,1080,1180,"01  ESP32-S3 最小系统","完整列出 57 个封装端子；保留内部 Flash、PSRAM 与晶振连接")

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
          12:"VBUS_VALID_N",15:"CHARGE_DISABLE",16:"CHG_EN1",17:"CHG_EN2",18:"PGOOD_N",19:"CHG_N",
          25:"USB_DM_SOC",26:"USB_DP_SOC",49:"UART_TX",50:"UART_RX",57:"GND"}
    nets.update({i:"3V3" for i in [2,3,20,46,55,56]})
    pins=[p(i,names[i],nets.get(i),4 if i in [2,3,20,46,55,56,57] else (1 if i==4 else 3)) for i in range(1,58)]
    ic("U1","ESP32-S3-PICO-1-N8R8","LGA-56 + EP / 7x7 mm",350,280,pins[:29],pins[29:],400,
       "28、38 至 42 脚为内部 PSRAM；29 脚输出电源不得连接 3V3；未使用的启动配置脚采用数据手册默认状态")
    passive("R7","10k","3V3","MCU_EN",300,1230)
    passive("C1","1uF / 10V","MCU_EN","GND",780,1230,"C")

    select_sheet("02_SENSORS")
    add_shape(txt(1200,65,"圆形传感器 / SCH-A2 / 02 传感器",28))
    add_shape(txt(1200,105,"MLX90393 + LSM6DSOX | I2C 与中断网络通过同名标签跨页连接",15))
    section(1200,160,1100,1180,"02  I2C 传感器","数据就绪信号相互独立；工作电压 3.3 V；MLX 地址 0x10，IMU 地址 0x6A")
    ic("U2","MLX90393SLQ-ABA-011-RE","UTDFN-8 + EP / 2.5x2 mm",1450,280,
       [p(1,"SCL","I2C_SCL",1),p(2,"SDA","I2C_SDA",3),p(3,"MISO",None,2),p(4,"VDD_IO","3V3",4),p(5,"VSS","GND",4)],
       [p(6,"VDD","3V3",4),p(7,"MS/CS","3V3",1),p(8,"INT","MLX_INT",2),p(9,"EP [pad 9]","GND",4)],300,
       "7 位 I2C 地址为 0x10；裸露焊盘编号设为 9，供后续封装映射")
    passive("C2","100nF / 10V","3V3","GND",2080,340,"C")
    passive("C3","100nF / 10V","3V3","GND",2080,440,"C")
    ic("U3","LSM6DSOXTR","LGA-14 / 2.5x3 mm",1450,690,
       [p(1,"SDO/SA0","GND",3),p(2,"SDx","GND",3),p(3,"SCx","GND",3),p(4,"INT1","IMU_INT",2),
        p(5,"VDDIO","3V3",4),p(6,"GND","GND",4),p(7,"GND","GND",4)],
       [p(8,"VDD","3V3",4),p(9,"INT2",None,2),p(10,"OCS_Aux",None,3),p(11,"SDO_Aux",None,3),
        p(12,"CS","3V3",1),p(13,"SCL","I2C_SCL",1),p(14,"SDA","I2C_SDA",3)],300,"模式 1；地址 0x6A")
    for ref,yy in [("C4",750),("C5",850)]: passive(ref,"100nF / 10V","3V3","GND",2080,yy,"C")
    passive("R5","4.7k","3V3","I2C_SDA",1470,1120)
    passive("R6","4.7k","3V3","I2C_SCL",2050,1120)
    note(1230,1230,"每个 100 nF 电容应紧靠对应电源脚放置；共用 GND。","GPIO4 = MLX 数据就绪；GPIO5 = IMU 中断 1。两路采样分别加时间戳。")

    select_sheet("03_USB")
    add_shape(txt(2360,65,"圆形传感器 / SCH-A2 / 03 USB",28))
    add_shape(txt(2360,105,"侧向插入 USB-C 数据与供电接口 | USB 2.0 设备，不支持 PD",15))
    section(2360,160,1180,1180,"03  USB-C 数据与 ESD 防护","USB 2.0 设备，不支持 PD；CC1、CC2 分别下拉；检测 USB VBUS")
    usb=[]
    for row in ["A","B"]:
        for n,name,net in [(1,"GND","GND"),(4,"VBUS","USB_5V"),(5,"CC",f"CC{1 if row=='A' else 2}"),
                           (6,"D+","USB_DP"),(7,"D-","USB_DM"),(8,"SBU",None),(9,"VBUS","USB_5V"),(12,"GND","GND")]:
            usb.append(p(f"{row}{n}",f"{row}{n} {name}",net))
    ic("J1","USB4105-GF-A-060","USB-C 16 signal contacts + SH",2550,280,usb[:8],usb[8:]+[p("SH","SHIELD","GND")],270,
       "四个外壳固定脚共用封装焊盘 SH；USB 2.0 信号触点按网络成对连接")
    ic("U6","TPD2EUSB30ADRTR","SOT DRT 3 pins / 1.0x0.8 mm body",3200,280,
       [p(1,"IO1","USB_DP"),p(2,"IO2","USB_DM")],[p(3,"GND","GND",4)],210)
    passive("R1","5.1k / 1%","CC1","GND",2640,740)
    passive("R2","5.1k / 1%","CC2","GND",3160,740)
    passive("R3","22Ω 初始值","USB_DP","USB_DP_SOC",2640,870)
    passive("R4","22Ω 初始值","USB_DM","USB_DM_SOC",3160,870)
    for ref,net,xx,yy in [("D1","USB_5V",2640,1000),("D2","CC1",3160,1000),("D3","CC2",2640,1130)]:
        passive(ref,"TPD1E10B06DPYR",net,"GND",xx,yy,"TVS","X1SON DPY-2 / 0402", "双向 ESD 保护；两脚可互换；未配置 PD/CC 过压控制器")
    note(2390,1240,"VBUS 仅为 5 V；U7 进行带阈值检测，避免向未上电 GPIO 反向供电。",
         "仅使用 USB 冷启动时，能否满足枚举前 100 mA 限流要求需要实测。")

    select_sheet("04_POWER")
    add_shape(txt(60,1320,"圆形传感器 / SCH-A2 / 04 电源",28))
    add_shape(txt(60,1360,"带保护的单节锂电池 | 目标续航约 2 小时 | 使用电池包 NTC 独立充电",15))
    section(60,1400,1680,1400,"04  电池、电源路径与充电","接入 USB 且检测到有效 10 kΩ NTC 时默认允许充电；GPIO 拉高可禁止充电")
    ic("U4","BQ24074RGTR","VQFN-16 + EP / RGT 3x3 mm",340,1540,
       [p(1,"TS","TS_CELL",1),p(2,"BAT","BAT_P",4),p(3,"BAT","BAT_P",4),p(4,"CE_N","CE_N",1),
        p(5,"EN2","CHG_EN2",1),p(6,"EN1","CHG_EN1",1),p(7,"PGOOD_N","PGOOD_N",2),p(8,"VSS","GND",4),p(17,"EP [pad 17]","GND",4)],
       [p(9,"CHG_N","CHG_N",2),p(10,"OUT","VSYS",4),p(11,"OUT","VSYS",4),p(12,"ILIM","ILIM_SET",1),
        p(13,"IN","USB_5V",4),p(14,"TMR",None,1),p(15,"ITERM",None,1),p(16,"ISET","ISET_SET",1)],300,
       "直接连接兼容 103AT-2 的电池包 NTC；TMR/ITERM 悬空表示采用默认计时与终止设置；必须使用带保护的 4.2 V 电芯")
    ic("U5","TLV75533PDRVR","WSON DRV-6 + EP / 2x2 mm",1180,1540,
       [p(6,"IN","VSYS",4),p(4,"EN","REG_EN",1),p(3,"GND","GND",4),p(7,"EP [pad 7]","GND",4)],
       [p(1,"OUT","3V3",4),p(2,"NC",None),p(5,"NC",None)],260,
       "无升压功能；VSYS 低于关断阈值时，U7 将 REG_EN 拉低")
    passive("SW1","电源 / 单刀单掷","VSYS","PWR_SW_ON",1050,1760,"SW","机械开关或外接开关焊盘",
            "仅断开系统使能路径；电池仍与充电器保持连接")
    passive("R19","100k / 1%","PWR_SW_ON","REG_EN",1450,1760,
            notes="限制欠压关断期间 U7 OUTA 的灌电流")
    passive("R20","1M / 1%","REG_EN","GND",1230,1870)
    power_passives=[
        ("C6","1uF / 16V","USB_5V","GND","C"),("C7","10uF / 10V","BAT_P","GND","C"),
        ("C8","10uF / 10V","VSYS","GND","C"),("C9","1uF / 10V","VSYS","GND","C"),
        ("C10","1uF / 10V","3V3","GND","C"),("R9","3.24k / 1%","ILIM_SET","GND","R"),
        ("R10","8.66k / 1%","ISET_SET","GND","R"),("R11","100k","CE_N","GND","R"),
        ("R12","100k","CHG_EN1","GND","R"),("R13","100k","CHG_EN2","GND","R"),
        ("R14","100k","3V3","PGOOD_N","R"),("R15","100k","3V3","CHG_N","R"),
        ("R21","10k","CHARGE_DISABLE","CE_N","R")]
    # First six above/below charger, others in evenly spaced rows at the bottom.
    positions=[(300,1970),(750,1970),(300,2080),(750,2080)]
    positions += [(xx,yy) for yy in [2230,2340,2450,2560] for xx in [300,820,1390]]
    for spec,(xx,yy) in zip(power_passives,positions):
        ref,val,a,b,kind=spec
        package="0603 / metric 1608" if ref in ["C7","C8"] else "0402 / metric 1005"
        passive(ref,val,a,b,xx,yy,kind,package)
    note(90,2680,"ISET 典型值约 103 mA；需确认电芯额定充电电流与器件容差。BAT/OUT 电容需复核直流偏压降容。",
         "EN2 EN1：00 = USB100；主机允许后 01 = USB500；11 = 挂起。不得默认自动使用 500 mA。",
         "开关关闭后 3V3 断电，但充电仍可独立进行。CHARGE_DISABLE 拉高可由固件选择性禁止充电。")

    select_sheet("05_RF_BATTERY_DEBUG")
    add_shape(txt(1800,1320,"圆形传感器 / SCH-A2 / 05 射频 + 电池 + 调试",28))
    add_shape(txt(1800,1360,"陶瓷天线 | 电池包 103AT-2 NTC | USB/欠压监测 | 恢复下载焊盘",15))
    section(1800,1400,1740,1400,"05  射频、调试与装配说明","在线封装核对：60/60 已绑定；PCB 外形与射频调谐仍待完成")
    ic("ANT1","2450AT18D0100001E","4-terminal 1206 ceramic antenna",2100,1540,
       [p(1,"FEED","RF_ANT")],[p(2,"GND","GND"),p(3,"GND","GND"),p(4,"TUNE/GND","ANT_TUNE")],300)
    passive("R30","0Ω / 射频串联","RF_SOC","RF_ANT",2060,1750)
    passive("C30","不装配 / 射频调谐","RF_SOC","GND",2650,1750,"C",fitted=False)
    passive("C31","不装配 / 射频调谐","RF_ANT","GND",3190,1750,"C",fitted=False)
    passive("R31","0Ω / 调谐预留","ANT_TUNE","GND",2060,1860,notes="射频审查后可替换为电感或电容")
    note(1840,1940,"使用 50 Ω 馈线；匹配参数必须结合实际 PCB、外壳、电池和握持状态确定。",
         "天线净空区贯穿整个板层，并适用于电路板正反两面的所有元件。")
    ic("J2","带保护的单节锂电池","3 个焊盘；间距和焊盘尺寸待定",3060,1520,
       [p(1,"PACK+","BAT_P",4),p(2,"PACK-","GND",4),p(3,"CELL_NTC","NTC_PACK",1)],[],230,
       "容量预算 350 至 400 mAh；真实电芯 NTC 接在 3、2 脚之间；不得用固定电阻绕过温度检测")
    passive("R16","0Ω / 1%","TS_CELL","NTC_PACK",2060,2070,
            notes="仅当带保护电池包内置 10 kΩ、兼容 103AT-2 且连接至 PACK- 的 NTC 时装配")
    passive("R17","不装配 / TS 并联预留","NTC_PACK","GND",2650,2070,
            notes="仅预留用于经过计算的充电温度窗口扩展",fitted=False)
    note(1840,2140,"充电要求带保护电池包在 J2.3 提供兼容 103AT-2 的 10 kΩ NTC；NTC 开路或缺失时禁止充电。")

    ic("U7","TLV6700DSER","WSON DSE-6 / 1.5x1.5 mm / LCSC C2876178",1900,2210,
       [p(2,"VDD","VSYS",4),p(5,"GND","GND",4),p(4,"INA+ / UV","UV_SENSE",1)],
       [p(6,"OUTA / UV","REG_EN",2),p(3,"INB- / VBUS","VBUS_SENSE",1),p(1,"OUTB / VBUS","VBUS_VALID_N",2)],300,
       "OUTA 通过外部迟滞直接控制 LDO 使能；OUTB 为低电平有效的 USB 有效信号。装配前重新确认立创商城库存")
    passive("R23","407k / 1%","VSYS","UV_SENSE",2570,2230)
    passive("R24","49.9k / 1%","UV_SENSE","GND",3110,2230)
    passive("R25","8.2M / 1%","REG_EN","UV_SENSE",2570,2340,
            notes="正反馈迟滞：SW1 闭合时标称关断约 3.48 V，恢复约 3.68 V")
    passive("R26","1.05M / 1%","USB_5V","VBUS_SENSE",3110,2340)
    passive("R27","100k / 1%","VBUS_SENSE","GND",2570,2450)
    passive("R28","100k","3V3","VBUS_VALID_N",3110,2450)
    passive("C22","100nF / 10V","VSYS","GND",2450,2560,"C")
    passive("C23","1nF / 10V","VBUS_SENSE","GND",2900,2560,"C",
            notes="比较器输入滤波；需验证 USB 拔出检测时间仍小于 3 ms")
    passive("C24","10nF / 10V","UV_SENSE","GND",3250,2560,"C",
            notes="抑制短时电源瞬变；不能替代储能电容")
    passive("R8","10k","3V3","BOOT_N",3250,2670)
    ic("J3","恢复下载测试点","6 个探针焊盘；不是排针",1900,2510,
       [p(1,"GND","GND"),p(2,"3V3","3V3"),p(3,"EN","MCU_EN")],
       [p(4,"BOOT","BOOT_N"),p(5,"UART_TX","UART_TX"),p(6,"UART_RX","UART_RX")],250,
       "复位 EN 时将 BOOT 接地可进入恢复下载模式；不得从外部向 LDO 输出端注入 3V3")
    passive("C20","22uF / 10V","3V3","GND",2450,2670,"C","0805 / metric 2012","SiP 储能电容；必须核对 3.3 V 直流偏压下的实际容量")
    passive("C21","100nF / 10V","3V3","GND",2900,2670,"C")
    note(1840,2760,"GPIO7 读取 VBUS_VALID_N：标称 4.60 V 置有效、4.54 V 释放；固件逻辑为低电平有效。",
         "GPIO6 电池 ADC 暂不连接，等待加入受控采样电路；关机状态下不得形成反向供电路径。",
         "仍必须使用带保护电芯。U7 关断/恢复阈值及仅 USB 启动均需进行容差分析和台架验证。")
    add_shape(txt(1800,2870,"原理图审查版本 SCH-A2 | PCB 布局、DRC、射频调谐、电芯选型与硬件测试仍待完成",16,color="#AA3333"))
    route_connections()


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
    (OUT/"sheets_manifest.json").write_text(json.dumps(dict(revision=REV,sheet_count=len(SHEETS),
        cross_page_rule="同一份嘉立创 EDA 标准版多页原理图中，同名网络标签为全局连接",
        sheets=sheet_manifest),ensure_ascii=False,indent=2)+"\n")
    project_doc=dict(editorVersion="6.5.57",docType="5",title=f"圆形传感器_{REV_FILE}",
                     description=f"五页原理图 {REV}",colors={},schematics=project_sheets)
    (OUT/f"round_sensor_{REV_FILE}_multi.json").write_text(json.dumps(project_doc,ensure_ascii=False,indent=2)+"\n")
    nets=defaultdict(list)
    for c in COMPONENTS:
        for p0 in c["pins"]:
            if p0["net"] is not None:nets[p0["net"]].append(c["ref"]+"."+p0["number"])
    (OUT/"design_netlist.json").write_text(json.dumps(dict(revision=REV,components=COMPONENTS,nets=dict(nets)),indent=2)+"\n")
    (OUT/"bom_draft.json").write_text(json.dumps([{k:v for k,v in c.items() if k!="pins"} for c in COMPONENTS],indent=2)+"\n")
    print(json.dumps(dict(sheets=len(SHEETS),components=len(COMPONENTS),pins=sum(len(c["pins"]) for c in COMPONENTS),nets=len(nets),shapes=len(SHAPES))))


if __name__=="__main__": main()
