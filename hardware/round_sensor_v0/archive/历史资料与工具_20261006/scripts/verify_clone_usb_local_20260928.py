"""USB 局部实验的独立拒收检查；不把离散铜几何检查当作原生 DRC。"""
import hashlib
import json
from build_clone_usb_local_20260928 import OUT, SOURCE, PREFIX, ROOT, dimensions
from check_pcb_a5 import U, parse, distance, xy
from audit_a5_routed_snapshot import routes, track_gap
from repair_clone_batch_20260928 import clearance


def verify(candidate=OUT,report_path=None):
    doc,parts,copper,holes=parse(candidate)
    tracks,vias,_=routes(doc)
    width_errors=[];via_errors=[];via_rounding=[];smd_holes=[];reference_conflicts=[];reference_vias=[]
    for t in tracks:
        if not t['id'].startswith(PREFIX):continue
        w,_,_=dimensions(doc,t['net'])
        if t['width']<w-1e-5:width_errors.append([t['id'],t['net'],t['width'],w])
    for s in doc['shape']:
        v=s.split('~')
        if v[0]!='VIA' or not v[6].startswith(PREFIX):continue
        _,od,drill=dimensions(doc,v[4]);actual_od=float(v[3])*U;actual_drill=2*float(v[5])*U
        if actual_od<od-1e-5 or actual_drill<drill-1e-5:
            item=[v[6],v[4],actual_od,actual_drill,od,drill]
            # 原生导出可将标称0.25mm孔环写为0.2499868mm；单独保留原值供Gerber复核，
            # 不把0.0000254mm编码舍入混作0.01mm级布线缺陷，也不修改规则或铜几何。
            (via_rounding if max(od-actual_od,drill-actual_drill)<=.00003 else via_errors).append(item)
        center=xy(v[1],v[2])
        for p in copper:
            if p['kind']!='pad' or p['layer'] not in ('1','2'):continue
            gap=distance([center],p['poly'])-actual_drill/2
            if gap<.1-1e-5:smd_holes.append([v[6],p['ref']+'.'+p['pin'],gap])
    # 底层相邻层是 L3。仅 L2 连续地并不能验收底层的参考地。
    usb=[t for t in tracks if t['id'].startswith(PREFIX) and t['net'].startswith('USB_D') and t['layer']=='2']
    for t in usb:
        for q in tracks:
            if q['layer']!='22' or q['net']=='GND':continue
            gap=min(distance([a,b],[c,d]) for a,b in zip(t['points'],t['points'][1:]) for c,d in zip(q['points'],q['points'][1:]))-(t['width']+q['width'])/2
            if gap<.2982+.2-1e-5:reference_conflicts.append([t['id'],q['id'],q['net'],round(gap,6)])
        # 通孔在 L3 的反焊盘同样切断参考地，不能只检查 L3 导线。
        for v in vias+[p for p in copper if p['kind']=='via']:
            if v['net']=='GND':continue
            # USB 自身换层通孔是必需的参考转换区，另行检查回流孔；不与普通阻挡混为一谈。
            if v['net'].startswith('USB_D'):continue
            gap=track_gap(t,v['poly'])
            required=.2982+clearance(doc,v['net'],'GND')
            if gap<required-1e-5:reference_vias.append([t['id'],v.get('id',v.get('ref')),v['net'],round(gap,6),required])
    plane_layers=[s.split('~')[2] for s in doc['shape'] if s.startswith('COPPERAREA~') and s.split('~')[3]=='GND']
    result={
        '候选文件':str(candidate),
        '候选SHA256':hashlib.sha256(candidate.read_bytes()).hexdigest(),
        '来源SHA256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        '新增线宽违反现有规则':width_errors,'新增过孔违反现有规则':via_errors,
        '原生过孔尺寸编码舍入差异_标称尺寸仍须输出核对':via_rounding,
        '新孔钻边至表贴焊盘小于0.1mm':smd_holes,
        '底层USB投影及三倍介质厚度邻域内的L3信号线':reference_conflicts,
        '底层USB参考走廊内的非USB非地通孔':reference_vias,
        '已声明GND铺铜层':plane_layers,
        'USB参考地已验收':False,'原生DRC已验收':False,'允许覆盖云端':False,
        '说明':'0.2982mm 使用层叠候选的 3h；L3 信号另加 0.2mm 地铜避让，非地通孔另加反焊盘避让。USB 自身换层区须单独核查回流。此项不是阻抗验收；须重建铺铜并验证实际铜面。',
    }
    path=report_path or ROOT/'easyeda_std/克隆板USB局部重布独立检查_20260928.json'
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result


if __name__=='__main__':
    import argparse
    from pathlib import Path
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,default=OUT);p.add_argument('--report',type=Path)
    args=p.parse_args();verify(args.source,args.report)
