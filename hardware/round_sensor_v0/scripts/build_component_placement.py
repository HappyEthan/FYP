"""Deterministic component-body packing study; not a PCB router or DRC engine."""
from pathlib import Path
import json
import math
import random

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "generated"
OUT.mkdir(exist_ok=True)

# Sizes are nominal body/pad-envelope estimates in mm. 0402 passives are
# represented as 1.0 x 0.5 mm plus the clearance used by the checker.
SMALL_PARTS = [
    *(dict(ref=f"R{i}", kind="0402 resistor", w=1.0, h=.5) for i in range(1, 20)),
    *(dict(ref=f"C{i}", kind="0402 capacitor", w=1.0, h=.5) for i in range(1, 13)),
    dict(ref="L1", kind="0402 RF matching/DNP", w=1.0, h=.5),
    dict(ref="U6", kind="USB D+/D- ESD", w=1.0, h=1.0),
    dict(ref="U7", kind="CC/VBUS ESD candidate", w=1.6, h=1.0),
    dict(ref="BAT+", kind="battery solder pad", w=2.0, h=2.0),
    dict(ref="BAT-", kind="battery solder pad", w=2.0, h=2.0),
    *(dict(ref=x, kind="test pad", w=.9, h=.9) for x in
      ["TP_EN", "TP_BOOT", "TP_TX", "TP_RX", "TP_3V3", "TP_GND"]),
]

PASSIVE_SCHEDULE = {
    "R1,R2": "5.1k 1% USB-C CC pull-down",
    "R3,R4": "22R initial USB series; tune after signal-integrity review",
    "R5,R6": "4.7k I2C pull-up",
    "R7": "10k CHIP_PU pull-up",
    "R8": "10k GPIO0 pull-up",
    "R9": "3.24k BQ24074 ILIM candidate",
    "R10": "8.66k 1% BQ24074 ISET; about 103mA typical",
    "R11": "10k BQ24074 CE defined pull-up",
    "R12,R13": "100k EN1/EN2 external pull-down",
    "R14,R15": "10k PGOOD/CHG pull-up",
    "R16,R17": "battery NTC hot/cold network; values TBD with selected cell",
    "R18,R19": "1M/330k battery ADC divider candidate",
    "C1": "1uF CHIP_PU reset capacitor",
    "C2,C3": "100nF MLX90393 VDDIO/VDD",
    "C4,C5": "100nF LSM6DSOX VDDIO/VDD",
    "C6": "1uF BQ24074 IN",
    "C7": "10uF BQ24074 BAT",
    "C8": "10uF BQ24074 OUT/VSYS",
    "C9": "1uF TLV75533 IN",
    "C10": "1uF TLV75533 OUT",
    "C11": "100nF battery ADC filter",
    "C12,L1": "RF matching reserve/DNP; final values by assembled RF tuning",
}


def fixed_parts(radius):
    return [
        dict(ref="U1", kind="ESP32-S3-PICO-1", side="F", x=-3.5, y=.9, w=7, h=7),
        dict(ref="J1", kind="USB-C", side="F", x=radius-.2-3.675, y=0, w=7.35, h=8.94),
        dict(ref="ANT1", kind="2.4GHz antenna", side="F", x=-1, y=-radius+1.8, w=3.2, h=1.6),
        dict(ref="U2", kind="MLX90393", side="B", x=0, y=0, w=2, h=2.5),
        dict(ref="U3", kind="LSM6DSOX", side="B", x=-4, y=0, w=3, h=2.5),
        dict(ref="U4", kind="BQ24074", side="B", x=-1, y=4.2, w=3, h=3),
        dict(ref="U5", kind="TLV75533", side="B", x=-5.3, y=3.6, w=2, h=2),
    ]


def rect(p, extra):
    return (p["x"]-p["w"]/2-extra, p["y"]-p["h"]/2-extra,
            p["x"]+p["w"]/2+extra, p["y"]+p["h"]/2+extra)


def overlap(a, b):
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def shell_keepouts(radius):
    result=[]
    for yy, length in [(-3.105, 2.1), (1.075, 1.8)]:
        for xx in [-4.32, 4.32]:
            x, y = radius-.2-3.675+yy, -xx
            result.append((x-length/2-.2, y-.7, x+length/2+.2, y+.7))
    return result


def inside_circle(p, radius, clearance=.15):
    b=rect(p, .15)
    return max(math.hypot(x, y) for x in (b[0], b[2]) for y in (b[1], b[3])) <= radius-clearance


def try_pack(diameter, seed=240907):
    radius=diameter/2
    fixed=fixed_parts(radius)
    rf=(-3, -radius, 1, -radius+6)
    holes=shell_keepouts(radius)
    rng=random.Random(seed+diameter)
    best=[]
    for _restart in range(500):
        placed=[]
        parts=list(SMALL_PARTS)
        rng.shuffle(parts)
        parts.sort(key=lambda p:p["w"]*p["h"], reverse=True)
        ok=True
        for spec in parts:
            success=False
            sides=["B","F"] if spec["ref"].startswith("BAT") else ["F","B"]
            rng.shuffle(sides)
            for _ in range(1800):
                side=sides[_ % 2]
                p=dict(spec, side=side,
                       x=round(rng.uniform(-radius+.6, radius-.6), 2),
                       y=round(rng.uniform(-radius+.6, radius-.6), 2))
                b=rect(p,.15)
                if not inside_circle(p,radius):
                    continue
                if side=="F" and overlap(b,rf):
                    continue
                if side=="B" and any(overlap(b,h) for h in holes):
                    continue
                if any(q["side"]==side and overlap(b,rect(q,.2)) for q in fixed):
                    continue
                if any(q["side"]==side and overlap(b,rect(q,.15)) for q in placed):
                    continue
                placed.append(p); success=True; break
            if not success:
                ok=False; break
        if len(placed)>len(best): best=placed
        if ok:
            return dict(diameter_mm=diameter, all_component_bodies_packed=True,
                        placed_count=len(placed), expected_count=len(SMALL_PARTS),
                        fixed=fixed, placed=placed, rf_keepout_mm=rf,
                        usb_shell_keepout_mm=holes,
                        scope="Body packing with estimated courtyards only; no nets, routing, vias, copper, impedance, thermal, assembly or DRC proof.")
    return dict(diameter_mm=diameter, all_component_bodies_packed=False,
                placed_count=len(best), expected_count=len(SMALL_PARTS), fixed=fixed,
                placed=best, rf_keepout_mm=rf, usb_shell_keepout_mm=holes,
                scope="Search failure is not proof that the diameter is impossible. No routing/DRC proof.")


def svg(study):
    d=study["diameter_mm"]; r=d/2; scale=24; pad=35
    panel=d*scale+2*pad; width=2*panel; height=panel+45
    colors={"F":"#3078ad","B":"#438b72"}
    lines=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
           '<rect width="100%" height="100%" fill="#f7fafb"/>',
           f'<text x="{width/2}" y="22" text-anchor="middle" font-size="15" fill="#193046">φ{d} mm component-body packing - NOT ROUTED / NOT DRC</text>']
    for panel_index,side in enumerate(("F","B")):
        ox=panel_index*panel
        def xy(x,y): return ox+pad+(x+r)*scale, 40+pad+(y+r)*scale
        cx,cy=xy(0,0)
        lines.append(f'<circle cx="{cx}" cy="{cy}" r="{r*scale}" fill="#eef4f1" stroke="#193046" stroke-width="2"/>')
        if side=="F":
            rf=study["rf_keepout_mm"]; x,y=xy(rf[0],rf[1])
            lines.append(f'<rect x="{x}" y="{y}" width="{(rf[2]-rf[0])*scale}" height="{(rf[3]-rf[1])*scale}" fill="#d9b55b" opacity=".35" stroke="#9b6a00"/>')
        for p in study["fixed"]+study["placed"]:
            if p["side"] != side: continue
            x,y=xy(p["x"]-p["w"]/2,p["y"]-p["h"]/2)
            c=colors[side]
            lines.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{p["w"]*scale:.1f}" height="{p["h"]*scale:.1f}" fill="{c}" fill-opacity=".24" stroke="{c}"/>')
            if p in study["fixed"]:
                lines.append(f'<text x="{x+p["w"]*scale/2:.1f}" y="{y+p["h"]*scale/2+4:.1f}" text-anchor="middle" font-size="11" fill="#193046">{p["ref"]}</text>')
        lines.append(f'<text x="{cx}" y="{height-12}" text-anchor="middle" font-size="14" fill="{colors[side]}">{"FRONT: MCU / USB / ANT" if side=="F" else "BACK: SENSORS / POWER"}</text>')
    lines.append('</svg>')
    return "\n".join(lines)+"\n"


studies=[try_pack(d) for d in (18,20,22)]
(OUT/"component_placement_checks.json").write_text(json.dumps(studies,ensure_ascii=False,indent=2)+"\n")
(OUT/"passive_schedule.json").write_text(json.dumps(PASSIVE_SCHEDULE,ensure_ascii=False,indent=2)+"\n")
for s in studies:
    (OUT/f"placement_{s['diameter_mm']}mm.svg").write_text(svg(s))
print(json.dumps([{k:s[k] for k in ("diameter_mm","all_component_bodies_packed","placed_count","expected_count")} for s in studies],indent=2))
