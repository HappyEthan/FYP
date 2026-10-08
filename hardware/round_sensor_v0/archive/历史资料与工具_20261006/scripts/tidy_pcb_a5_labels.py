"""只生成原生位号整理脚本；铜、元件位置、网络和封装实例不变。"""
import json
import math
import re
from check_pcb_a5 import ROOT, U, parse

SOURCE = ROOT/'easyeda_std/PCB_A5_cloud_reopened_20260916.json'


def bounds(points):
    return min(x for x,y in points), min(y for x,y in points), max(x for x,y in points), max(y for x,y in points)


def overlap(a, b, margin=.12):
    return not (a[2]+margin <= b[0] or b[2]+margin <= a[0] or a[3]+margin <= b[1] or b[3]+margin <= a[1])


def main():
    _, parts, copper, holes = parse(SOURCE)
    changes, placed = [], {'1': [], '2': []}
    for layer in ('1','2'):
        obstacles = []
        for r,p in parts.items():
            if p['layer'] == layer:
                points = [q for a in copper if a['ref']==r and a['kind']=='pad' for q in a['poly']]
                obstacles.append(bounds(points))
        obstacles += [bounds(a['poly']) for a in copper if a['layer']=='11']
        obstacles += [bounds(h['poly']) for h in holes]
        # 大器件先分配文字；小器件仍保持就近，避免先占用仅有的边缘空白。
        refs = sorted([r for r,p in parts.items() if p['layer']==layer], key=lambda r:(not r.startswith(('U','J','ANT','SW')),r))
        for ref in refs:
            p=parts[ref]
            t=next(v for v in p['items'] if v[:2]==['TEXT','P'])
            nums=list(map(float,re.findall(r'-?\d+(?:\.\d+)?',t[11])))
            # 将旧文本旋转恢复为水平，再测量字形，保留底面镜像。
            angle=math.radians(float(t[5] or 0))
            points=[]
            for x,y in zip(nums[::2],nums[1::2]):
                x,y=x-float(t[2]),y-float(t[3])
                points.append((x*math.cos(angle)-y*math.sin(angle),x*math.sin(angle)+y*math.cos(angle)))
            bb=bounds(points)
            size=.5/U
            scale=size/float(t[9])
            w,h=(bb[2]-bb[0])*scale*U+.10,(bb[3]-bb[1])*scale*U+.10
            px,py=p['center']
            candidates=[]
            for ix in range(-30,31):
                for iy in range(-30,31):
                    dx,dy=ix*.2,iy*.2
                    cx,cy=px+dx,py+dy
                    box=(cx-w/2,cy-h/2,cx+w/2,cy+h/2)
                    if max(math.hypot(x,y) for x in (box[0],box[2]) for y in (box[1],box[3]))>8.8:
                        continue
                    if any(overlap(box,b) for b in obstacles+placed[layer]):
                        continue
                    # 优先紧邻器件且正上/下或正侧方；不覆盖铜或其他文字。
                    score=dx*dx+dy*dy+.05*abs(dx)+.03*(dy>0)+.04*min(abs(dx),abs(dy))
                    candidates.append((score,cx,cy,box))
            if not candidates:
                raise ValueError('没有位号空位：'+ref)
            _,cx,cy,box=min(candidates)
            placed[layer].append(box)
            changes.append({'ref':ref,'gId':t[13],'x':4020+cx/U-(bb[0]+bb[2])/2*scale,
                            'y':3404+cy/U-(bb[1]+bb[3])/2*scale,'fontSize':size,
                            'strokeWidth':.10/U,'rotation':0,'display':'','center_mm':[cx,cy],
                            'distance_mm':round(math.hypot(cx-px,cy-py),3)})
            change=changes[-1]
            coordinates=iter(v for x,y in points for v in (change['x']+x*scale,change['y']+y*scale))
            change['pathStr']=re.sub(r'-?\d+(?:\.\d+)?',lambda m:format(next(coordinates),'.4f'),t[11])
    code="// A5 位号整理：仅改 TEXT；0.50 mm 字高、0.10 mm 线宽，用于试排阅读，生产丝印另行终审。\n(function(){\nvar d=api('getSource',{type:'json'});if(String(d.head.docType)!=='3'||Object.keys(d.FOOTPRINT).length!==41)throw Error('不是41元件A5 PCB');\nvar changes="+json.dumps(changes,ensure_ascii=False)+";\nvar byId={};Object.keys(d.FOOTPRINT).forEach(function(id){var f=d.FOOTPRINT[id];Object.keys(f.TEXT).forEach(function(k){byId[k]=f.TEXT[k];});});\nchanges.forEach(function(t){var target=byId[t.gId];if(!target||target.text!==t.ref||target.type!=='P')throw Error('位号不符');['x','y','fontSize','strokeWidth','rotation','display','pathStr'].forEach(function(k){target[k]=t[k];});});\napi('applySource',{source:d,createNew:false});\n})();\n"
    (ROOT/'scripts/tidy_pcb_a5_labels.js').write_text(code)
    (ROOT/'easyeda_std/pcb_a5_label_positions.json').write_text(json.dumps(changes,ensure_ascii=False,indent=2)+'\n')
    print('41 位号已排位；最大偏移 mm：',max(t['distance_mm'] for t in changes))


if __name__=='__main__':
    main()
