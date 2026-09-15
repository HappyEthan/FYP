"""Independently recover nets from exported pin dots, wires and net labels.

Does not call the generator. Checks the serialized electrical drawing against
the design manifest and key datasheet pin assignments. Not a substitute for EDA ERC.
"""
from pathlib import Path
from collections import defaultdict
import json
import hashlib

ROOT=Path(__file__).resolve().parents[1]/"easyeda_std"


def main():
    sheets_manifest=json.loads((ROOT/"sheets_manifest.json").read_text())
    assert sheets_manifest["sheet_count"]==5
    docs=[]; raw_by_sheet={}
    for sheet in sheets_manifest["sheets"]:
        raw=(ROOT/sheet["file"]).read_bytes()
        doc=json.loads(raw)
        assert doc["head"]["docType"]=="1"
        docs.append((sheet["name"],doc))
        raw_by_sheet[sheet["name"]]=raw
    manifest=json.loads((ROOT/"design_netlist.json").read_text())
    pins={}; labels=defaultdict(set); segments=[]; nc=set(); refs=set(); ids=[]
    def xy(a,b):return (float(a),float(b))
    for sheet_name,doc in docs:
        def node(a,b):return (sheet_name,)+xy(a,b)
        for shape in doc["shape"]:
            v=shape.split("~");cmd=v[0]
            if cmd=="LIB":
                parts=shape.split("#@$"); prefix=[s.split("~")[12] for s in parts[1:] if s.startswith("T~P~")]
                assert len(prefix)==1
                ref=prefix[0];assert ref not in refs;refs.add(ref);ids.append(v[6])
                for sub in parts[1:]:
                    if not sub.startswith("P~"):continue
                    pp=sub.split("^^");cfg=pp[0].split("~");dot=pp[1].split("~");num=pp[4].split("~")[4]
                    assert cfg[3]==num, (ref,"SPICE pin number differs",cfg[3],num)
                    assert xy(cfg[4],cfg[5])==xy(*dot),(ref,num,"pin dot mismatch")
                    endpoint=ref+"."+num;assert endpoint not in pins
                    pins[endpoint]=node(*dot);ids.append(cfg[7])
            elif cmd=="W":
                pts=list(map(float,v[1].split()));assert len(pts)%2==0; ids.append(v[6])
                points=[(sheet_name,x,y) for x,y in zip(pts[::2],pts[1::2])]
                segments.extend(zip(points,points[1:]))
            elif cmd=="N":labels[node(v[1],v[2])].add(v[5]);ids.append(v[6])
            elif cmd=="O":nc.add(node(v[1],v[2]));ids.append(v[3])
    assert len(ids)==len(set(ids)),"Duplicate electrical primitive ID"
    nodes=set(pins.values())|set(labels)|nc|{p for ab in segments for p in ab}
    parent={p:p for p in nodes}
    def find(p):
        if parent[p]!=p:parent[p]=find(parent[p])
        return parent[p]
    def union(a,b):parent[find(a)]=find(b)
    def on(p,a,b):
        if p[0]!=a[0] or a[0]!=b[0]:return False
        cross=(p[1]-a[1])*(b[2]-a[2])-(p[2]-a[2])*(b[1]-a[1])
        return abs(cross)<1e-9 and min(a[1],b[1])<=p[1]<=max(a[1],b[1]) and min(a[2],b[2])<=p[2]<=max(a[2],b[2])
    for a,b in segments:
        assert a[1]==b[1] or a[2]==b[2],"Unexpected diagonal electrical wire"
        for point in nodes:
            if on(point,a,b):union(a,point)
    local_names=defaultdict(set)
    for point,names in labels.items():local_names[find(point)].update(names)
    assert all(len(v)==1 for v in local_names.values()),"Conflicting labels shorted by wires"
    expected={c["ref"]+"."+p["number"]:p["net"] for c in manifest["components"] for p in c["pins"]}
    pins_by_root=defaultdict(list)
    for endpoint,point in pins.items():pins_by_root[find(point)].append(endpoint)
    actual={};floating=[]
    for endpoint,point in pins.items():
        names=local_names[find(point)]
        assert not (names and point in nc),(endpoint,"connected pin marked NC")
        if point in nc:
            actual[endpoint]=None
            floating.append(endpoint)
            continue
        if names:
            actual[endpoint]=next(iter(names))
            continue
        root=find(point)
        connected_pins=pins_by_root[root]
        expected_names={expected[p] for p in connected_pins}
        assert len(connected_pins)>=2,(endpoint,"unconnected without NC")
        assert None not in expected_names and len(expected_names)==1,(connected_pins,"unlabelled wire joins conflicting expected nets")
        actual[endpoint]=next(iter(expected_names))
    assert actual==expected,{k:(expected.get(k),actual.get(k)) for k in expected.keys()|actual.keys() if expected.get(k)!=actual.get(k)}
    reference={"U1.25":"USB_DM_SOC","U1.26":"USB_DP_SOC","U1.6":"I2C_SDA","U1.7":"I2C_SCL",
       "U1.12":"VBUS_VALID_N","U1.15":"CHARGE_DISABLE",
       "U2.1":"I2C_SCL","U2.2":"I2C_SDA","U2.7":"3V3","U2.8":"MLX_INT","U2.3":None,
       "U3.1":"GND","U3.2":"GND","U3.3":"GND","U3.12":"3V3","U3.13":"I2C_SCL","U3.14":"I2C_SDA",
       "U4.1":"TS_CELL","U4.4":"CE_N","U4.5":"CHG_EN2","U4.6":"CHG_EN1","U4.13":"USB_5V",
       "U4.14":None,"U4.15":None,"U4.16":"ISET_SET","U4.17":"GND","U5.6":"VSYS","U5.4":"REG_EN",
       "U5.1":"3V3","U5.3":"GND","U5.7":"GND","U7.1":"VBUS_VALID_N","U7.2":"VSYS",
       "U7.3":"VBUS_SENSE","U7.4":"UV_SENSE","U7.5":"GND","U7.6":"REG_EN",
       "R11.1":"CE_N","R11.2":"GND","R19.1":"PWR_SW_ON","R19.2":"REG_EN",
       "R21.1":"CHARGE_DISABLE","R21.2":"CE_N"}
    for n in [2,3,20,46,55,56]:reference[f"U1.{n}"]="3V3"
    for n in [28,29,30,31,32,33,34,35,38,39,40,41,42,53,54]:reference[f"U1.{n}"]=None
    for key,net in reference.items():assert actual[key]==net,(key,net,actual[key])
    for half in ["A","B"]:
        for number,net in [(1,"GND"),(4,"USB_5V"),(6,"USB_DP"),(7,"USB_DM"),(9,"USB_5V"),(12,"GND")]:
            assert actual[f"J1.{half}{number}"]==net
    assert actual["J1.A5"]=="CC1" and actual["J1.B5"]=="CC2"
    values={c["ref"]:c for c in manifest["components"]}
    assert values["R1"]["value"]==values["R2"]["value"]=="5.1k / 1%"
    assert values["R16"]["fitted"] and not values["R17"]["fitted"]
    assert values["R10"]["value"]=="8.66k / 1%"
    assert values["R23"]["value"]=="407k / 1%"
    assert values["R24"]["value"]=="49.9k / 1%"
    assert values["R25"]["value"]=="8.2M / 1%"
    assert values["R26"]["value"]=="1.05M / 1%"
    assert values["R27"]["value"]=="100k / 1%"
    # Nominal TLV6700 thresholds. OUTA-low clamps REG_EN for restart; the
    # high-impedance state includes the R19/R20 enable divider and R25 feedback.
    r19,r20,r23,r24,r25,r26,r27=100e3,1e6,407e3,49.9e3,8.2e6,1.05e6,100e3
    a=1/r19+1/r20+1/r25; b=-1/r25; c=b; d=1/r23+1/r24+1/r25
    e=1/r19; f=1/r23; determinant=a*d-b*c
    uv_high_gain=(a*f-c*e)/determinant
    uv_low_gain=(1/r23)/(1/r23+1/r24+1/r25)
    thresholds={
      "vsys_cutoff_falling":0.3945/uv_high_gain,
      "vsys_restart_rising":0.4000/uv_low_gain,
      "vbus_valid_assert_rising":0.4000*(r26+r27)/r27,
      "vbus_valid_release_falling":0.3945*(r26+r27)/r27,
    }
    assert 3.45 < thresholds["vsys_cutoff_falling"] < 3.51
    assert 3.65 < thresholds["vsys_restart_rising"] < 3.71
    assert 4.55 < thresholds["vbus_valid_assert_rising"] < 4.65
    assert 4.50 < thresholds["vbus_valid_release_falling"] < 4.57
    recovered=defaultdict(list)
    for endpoint,net in actual.items():
        if net is not None:recovered[net].append(endpoint)
    assert all(len(p)>=2 for p in recovered.values()),"Single-pin named net"
    revision=manifest["revision"]
    current_editor_path=ROOT/"editor_validation_SCH_A2_CN_FINAL.json"
    editor=json.loads(current_editor_path.read_text()) if current_editor_path.exists() else {}
    editor_is_current=bool(editor and editor.get("源文件")=="round_sensor_SCH_A2_WIRED_multi.json")
    if editor_is_current:
        assert editor["原理图页数"]==len(docs)
        assert editor["页面名称"]==[s["name"] for s in sheets_manifest["sheets"]]
        assert editor["元件数量"]==len(refs)
        assert editor["命名网络数量"]==len(recovered)
        assert editor["有效网络数量"]==len(recovered)
        assert editor["已绑定封装"]==len(refs)
        assert editor["未绑定封装"]==0
    combined_hash=hashlib.sha256(b"".join(raw_by_sheet[name] for name in raw_by_sheet)).hexdigest()
    report=dict(status="PASS_LOCAL_SERIALIZED_CONNECTIVITY",revision=revision,sha256=combined_hash,
      source_sha256={name:hashlib.sha256(raw).hexdigest() for name,raw in raw_by_sheet.items()},
      sheet_count=len(docs),sheet_names=[name for name,_ in docs],
      components=len(refs),pins=len(pins),named_nets=len(recovered),intentional_no_connects=len(floating),
      checked_reference_pins=len(reference)+14,checks=["all electrical pin dots match their declared coordinates",
      "all pins join the expected physical wire component, a net label, or an explicit no-connect marker","no conflicting labels share a wire",
      "five-sheet geometry is isolated by page while same-name labels merge globally",
      "USB orientation, sensor modes, PSRAM reservations, autonomous charge control and power pin mapping checked",
      "103AT-2 pack NTC link, U7 USB/UV divider values and separate CC pull-down values checked"],
      editor_import_verified=bool(editor_is_current and editor.get("已保存至个人工作区",False)),
      editor_render_verified=bool(editor_is_current and editor.get("中文标题与说明已逐页检查",False)),
      editor_erc_run=bool(editor_is_current and editor.get("设计管理器结果")),
      editor_erc_error_count=editor.get("可见错误条目") if editor_is_current else None,
      editor_validation=editor if editor_is_current else None,
      footprints_bound=False,
      nominal_thresholds_V={key:round(value,3) for key,value in thresholds.items()},
      limitations=["No PCB/DRC/RF/thermal/runtime validation",
      "Standard-edition integrated ERC does not replace footprint, datasheet or manufacturability review",
      "Battery cell selection remains unresolved; only a protected pack with a 10 k 103AT-2-compatible NTC may enable charging",
      "U7 nominal thresholds still require tolerance analysis and hardware validation"],
      nets=dict(recovered),no_connects=floating)
    (ROOT/"validation_report.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({k:report[k] for k in ["status","components","pins","named_nets","intentional_no_connects"]}))


if __name__=="__main__":main()
