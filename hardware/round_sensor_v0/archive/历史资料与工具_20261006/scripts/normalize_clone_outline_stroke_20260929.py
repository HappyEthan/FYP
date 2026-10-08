"""仅细化板框绘图线宽，保持圆心/半径及所有铜不变；不降低 DRC 间距。"""
from refine_clone_usb_20260928 import *
from check_pcb_a5 import U
doc,_,_,_=parse(OUT);old=[]
for i,s in enumerate(doc['shape']):
    a=s.split('~')
    if a[0]=='CIRCLE' and a[5]=='10':
        old.append(float(a[4])*U);a[4]=str(.05/U);doc['shape'][i]='~'.join(a)
assert len(old)==1
save(doc);r=json.loads(REPORT.read_text());r['圆板框线宽表达']={'原线宽_mm':old[0],'现线宽_mm':.05,'圆心半径未变':True,'铜几何未变':True,'板边间距规则未变':True,'原生隔离对照':'D轮仅改变线宽后 DRC 53→40；不是13处铜被移动','Gerber外形中心线待核验':True}
REPORT.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
