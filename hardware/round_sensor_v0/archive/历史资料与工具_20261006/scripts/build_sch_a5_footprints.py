"""生成A5剩余五个封装的铜焊盘初稿；发布前须原生回读及阻焊/钢网审核。"""
from pathlib import Path
import copy
import json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'easyeda_std' / 'footprints'
TEMPLATE = ROOT / 'archive/pre_SCH_A5_20260916/easyeda_std/PCBLIB_DMC2400UV_SOT563_DIODES_LAND_2026-09-15.json'

# 顶视图，毫米，y向下。编号刻意匹配A5符号；不是所有第三方库的默认编号。
SPECS = {
 'U4': dict(name='SGM40567_WLCSP_6B_SGM_LAND_A5', body=[.922,1.155], source='sgm40567.pdf，第3、14页',
   pads=[(f'{r}{c}', x, y, .20,.20,'ELLIPSE') for r,y in [('A',-.4),('B',0),('C',.4)] for c,x in [('1',-.2),('2',.2)]],
   note='A1左上；0.4mm间距；铜直径0.20mm（官方0.19至0.21）；钢网、NSMD开窗及贴装工艺待审核'),
 'Q1': dict(name='LP0404N3_SOT883_LRC_LAND_A5', body=[1,.6], source='lp0404n3t5g.pdf，第1、6页',
   pads=[('1',.35,0,.4,.55,'RECT'),('2',-.35,-.17,.4,.2,'RECT'),('3',-.35,.17,.4,.2,'RECT')],
   note='A5自定义编号1=D大焊盘，2=G左上，3=S左下；铜最小间距0.14mm；顶视图，不直接照抄底视图'),
 'D4': dict(name='LMBR4010_SOD882_LRC_LAND_A5', body=[1,.6], source='lmbr4010bst5g.pdf，第1、3页',
   pads=[('1',-.35,0,.4,.7,'RECT'),('2',.35,0,.4,.7,'RECT')],
   note='1阴极左侧，2阳极右侧；中心距0.70mm，铜间隙0.30mm'),
 'J2': dict(name='BATTERY_WIRE_2PAD_A5', body=[3.3,2], source='项目自定义电线焊盘，无器件外壳',
   pads=[('1',-.9,0,1.5,2,'RECT'),('2',.9,0,1.5,2,'RECT')],
   note='1电池正极左，2负极右；沿用原1.5x2.0mm单焊盘、1.8mm间距；线径、电流、应力释放和禁开钢网须审核'),
 'ANT1': dict(name='U_FL_R_SMT_1_HIROSE_LAND_A5', body=[3,3.1], source='Hirose_U.FL_catalog.pdf，第12页',
   pads=[('1',0,1.525,1,1.05,'RECT'),('2',-1.475,0,1.05,2.2,'RECT'),('3',1.475,0,1.05,2.2,'RECT')],
   note='信号焊盘上边缘位于地焊盘中心线下1.00mm，故中心y=1.525mm；旧稿1.625mm偏大0.10mm；中心禁走线，官方钢网不同于铜形状')
}


def main():
    OUT.mkdir(exist_ok=True)
    base=json.loads(TEMPLATE.read_text())
    report={}
    for ref,spec in SPECS.items():
        doc=copy.deepcopy(base)
        doc['head']={'docType':'4','editorVersion':'6.5.51','newgId':True,'c_para':{'package':spec['name'],'pre':ref.rstrip('0123456789')+'?','Contributor':'eda_htyqpfoe','说明':spec['note']},'x':400,'y':300}
        doc['shape']=[]
        def conv(v,offset=0):return f'{offset+v/.254:.6f}'
        for i,(n,x,y,w,h,shape) in enumerate(spec['pads']):
            px,py=conv(x,400),conv(y,300)
            doc['shape'].append(f'PAD~{shape}~{px}~{py}~{conv(w)}~{conv(h)}~1~~{n}~0~~0~ggeA5FP{i}~0~~Y~0')
        w,h=spec['body'];pts=[(-w/2,-h/2),(w/2,-h/2),(w/2,h/2),(-w/2,h/2),(-w/2,-h/2)]
        coords=' '.join(f'{conv(x,400)} {conv(y,300)}' for x,y in pts)
        doc['shape'].append(f'TRACK~{conv(.05)}~12~~{coords}~ggeA5BODY~0')
        # Pin-1 marker on documentation layer, no unreviewed silk over tiny copper lands.
        n,x,y,_,_,_=spec['pads'][0]
        doc['shape'].append(f'CIRCLE~{conv(x,400)}~{conv(y-.25,300)}~{conv(.04)}~{conv(.03)}~12~ggeA5MARK~0')
        doc.pop('BBox',None)
        path=OUT/(spec['name']+'.json')
        path.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n')
        # Independent decode confirms coordinate unit conversion and numbering survived serialization.
        actual=[]
        for s in json.loads(path.read_text())['shape']:
            if not s.startswith('PAD~'):continue
            v=s.split('~');actual.append((v[8],round((float(v[2])-400)*.254,5),round((float(v[3])-300)*.254,5),round(float(v[4])*.254,5),round(float(v[5])*.254,5),v[1]))
        assert actual==spec['pads'],(ref,actual)
        report[ref]={**spec,'file':path.name,'状态':'本地铜焊盘几何通过；原生绑定状态见editor_validation_SCH_A5.json；阻焊/钢网待审核'}
    (OUT/'封装几何清单.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('已生成5个封装，铜几何序列化检查通过；未声称钢网/阻焊及原生绑定完成。')


if __name__=='__main__':main()
