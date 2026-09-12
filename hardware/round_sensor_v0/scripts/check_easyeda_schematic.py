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
    actual={};floating=[]
    for endpoint,point in pins.items():
        names=local_names[find(point)]
        assert not (names and point in nc),(endpoint,"connected pin marked NC")
        assert names or point in nc,(endpoint,"unconnected without NC")
        actual[endpoint]=next(iter(names)) if names else None
        if not names:floating.append(endpoint)
    expected={c["ref"]+"."+p["number"]:p["net"] for c in manifest["components"] for p in c["pins"]}
    assert actual==expected,{k:(expected.get(k),actual.get(k)) for k in expected.keys()|actual.keys() if expected.get(k)!=actual.get(k)}
    reference={"U1.25":"USB_DM_SOC","U1.26":"USB_DP_SOC","U1.6":"I2C_SDA","U1.7":"I2C_SCL",
       "U2.1":"I2C_SCL","U2.2":"I2C_SDA","U2.7":"3V3","U2.8":"MLX_INT","U2.3":None,
       "U3.1":"GND","U3.2":"GND","U3.3":"GND","U3.12":"3V3","U3.13":"I2C_SCL","U3.14":"I2C_SDA",
       "U4.1":"TS_CELL","U4.4":"CE_N","U4.5":"CHG_EN2","U4.6":"CHG_EN1","U4.13":"USB_5V",
       "U4.14":None,"U4.15":None,"U4.16":"ISET_SET","U4.17":"GND","U5.6":"VSYS","U5.4":"REG_EN",
       "U5.1":"3V3","U5.3":"GND","U5.7":"GND","Q1.1":"CE_BASE","Q1.2":"GND","Q1.3":"CE_N",
       "Q2.1":"VBUS_BASE","Q2.2":"GND","Q2.3":"VBUS_PRESENT_N","R11.1":"VSYS","R11.2":"CE_N"}
    for n in [2,3,20,46,55,56]:reference[f"U1.{n}"]="3V3"
    for n in [28,29,30,31,32,33,34,35,38,39,40,41,42,53,54]:reference[f"U1.{n}"]=None
    for key,net in reference.items():assert actual[key]==net,(key,net,actual[key])
    for half in ["A","B"]:
        for number,net in [(1,"GND"),(4,"USB_5V"),(6,"USB_DP"),(7,"USB_DM"),(9,"USB_5V"),(12,"GND")]:
            assert actual[f"J1.{half}{number}"]==net
    assert actual["J1.A5"]=="CC1" and actual["J1.B5"]=="CC2"
    values={c["ref"]:c for c in manifest["components"]}
    assert values["R1"]["value"]==values["R2"]["value"]=="5.1k / 1%"
    assert not values["R16"]["fitted"] and not values["R17"]["fitted"]
    assert values["R10"]["value"]=="8.66k / 1%"
    recovered=defaultdict(list)
    for endpoint,net in actual.items():
        if net is not None:recovered[net].append(endpoint)
    assert all(len(p)>=2 for p in recovered.values()),"Single-pin named net"
    editor_path=ROOT/"editor_validation.json"
    editor=json.loads(editor_path.read_text()) if editor_path.exists() else {}
    if editor:
        expected_files=[s["file"] for s in sheets_manifest["sheets"]]
        if editor.get("multi_sheet_import_verified"):
            assert editor["source_files"]==expected_files
            assert editor["sheet_names"]==[s["name"] for s in sheets_manifest["sheets"]]
        else:
            assert editor["source_file"]=="round_sensor_SCH_A1.json"
        assert editor["component_count"]==len(refs)
        assert editor["named_net_count"]==len(recovered)
        assert editor["valid_net_count"]==len(recovered)
    combined_hash=hashlib.sha256(b"".join(raw_by_sheet[name] for name in raw_by_sheet)).hexdigest()
    report=dict(status="PASS_LOCAL_SERIALIZED_CONNECTIVITY",sha256=combined_hash,
      source_sha256={name:hashlib.sha256(raw).hexdigest() for name,raw in raw_by_sheet.items()},
      sheet_count=len(docs),sheet_names=[name for name,_ in docs],
      components=len(refs),pins=len(pins),named_nets=len(recovered),intentional_no_connects=len(floating),
      checked_reference_pins=len(reference)+14,checks=["all electrical pin dots match their declared coordinates",
      "all pins wire to expected net labels or have explicit no-connect markers","no conflicting labels share a wire",
      "five-sheet geometry is isolated by page while same-name labels merge globally",
      "USB orientation, sensor modes, PSRAM reservations, charge CE isolation and power pin mapping checked",
      "R16/R17 DNP and separate CC pull-down values checked"],
      editor_import_verified=bool(editor.get("import_verified",False)),
      editor_render_verified=bool(editor.get("render_verified",False)),
      editor_erc_run=bool(editor.get("integrated_erc_refreshed",False)),
      editor_erc_error_count=editor.get("erc_error_count"),
      editor_validation=editor or None,footprints_bound=False,
      limitations=["No PCB/DRC/RF/thermal/runtime validation",
      "Standard-edition integrated ERC does not replace footprint, datasheet or manufacturability review",
      "NTC network and cell selection unresolved; charging physically inhibited by open R16"],
      nets=dict(recovered),no_connects=floating)
    (ROOT/"validation_report.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({k:report[k] for k in ["status","components","pins","named_nets","intentional_no_connects"]}))


if __name__=="__main__":main()
