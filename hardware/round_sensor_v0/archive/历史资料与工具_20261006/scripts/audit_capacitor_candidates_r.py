"""读取三星公开曲线并核对R源；只输出选料筛查，不修改设计，不批准采购。"""
import hashlib
import json
import re
import math
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    'easyeda_std/PCB_克隆板USB局部重布_原生回读_20260929.json':
        'c3c0d4e5630df0b756df07d380213af8edc1a5eab8da054e44c54a5e4e337954',
    'easyeda_std/usb_keep_min_candidate/原生回读_全部封装绑定.json':
        '0f59ca7f783b71e3960a888bd03df6a802ee880eaf73133de7f2530a92fd1e15',
}
PARTS = [
    ('CL05A105KO5NNNC', 1.0, .10, 'C29266', []),
    ('CL05A225KA5NUNC', 2.2, .10, 'C307418', ['C7', 'C10']),
    ('CL05A475MO5NUNC', 4.7, .20, 'C318563', ['C6', 'C9']),
]


def check_sources():
    for path, expected in SOURCES.items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected, path


def points(series):
    return [(float(p['x']), float(p['y'])) for p in series['chartList'][0]['data']]


def interpolate(data, x):
    for (a, ya), (b, yb) in zip(data, data[1:]):
        if a <= x <= b and a != b:
            return ya + (x - a) * (yb - ya) / (b - a)
    raise ValueError('不允许超出曲线范围外推')


def fit_and_startup():
    """以候选推荐焊盘下限只做内存试算，不写PCB；补充已有选料报告。"""
    from check_pcb_a5 import parse, distance
    from audit_a5_routed_snapshot import routes, track_gap
    check_sources()
    target = ROOT / 'easyeda_std/克隆板R电容选料筛查.json'
    report = json.loads(target.read_text())
    assert report['设计源SHA256'] == SOURCES
    doc, parts, copper, _ = parse(ROOT / next(iter(SOURCES)))
    tracks, vias, _ = routes(doc)
    refs = ['C6', 'C7', 'C9', 'C10']
    board_center = (22.999954, -78.999842)
    radius = 8.999982
    def center(poly):
        return tuple(sum(p[k] for p in poly) / len(poly) for k in (0, 1))
    def oriented(mid, axis, length, width):
        normal = (-axis[1], axis[0])
        return [(mid[0]+x*axis[0]+y*normal[0], mid[1]+x*axis[1]+y*normal[1])
                for x,y in [(-length/2,-width/2),(length/2,-width/2),
                            (length/2,width/2),(-length/2,width/2)]]
    revised, rows = {}, []
    for ref in refs:
        pads = sorted([a for a in copper if a['ref']==ref and a['kind']=='pad'], key=lambda a:a['pin'])
        assert len(pads)==2
        centers = [center(a['poly']) for a in pads]
        pitch = math.dist(*centers)
        axis = tuple((centers[1][k]-centers[0][k])/pitch for k in (0,1))
        mid = tuple((centers[0][k]+centers[1][k])/2 for k in (0,1))
        dims=[]
        for a in pads:
            projections = [[p[0]*v[0]+p[1]*v[1] for p in a['poly']]
                           for v in [axis,(-axis[1],axis[0])]]
            dims.append([max(p)-min(p) for p in projections])
        # 三星2025-12目录第48页，公制1005、尺寸公差±0.20行的推荐下限。
        gap,length,width = .42,.53,.66
        trial=[]
        for sign,a in zip([-1,1],pads):
            nc=tuple(mid[k]+sign*(gap+length)/2*axis[k] for k in (0,1))
            trial.append(dict(a,poly=oriented(nc,axis,length,width)))
        revised[ref]=trial
        body=oriented(mid,axis,1.20,.70)
        rows.append({'位号':ref,'当前单焊盘长宽_mm':dims,
                     '当前中心距_mm':pitch,'当前内间隙_mm':pitch-sum(d[0] for d in dims)/2,
                     '候选推荐下限_间隙_焊盘长_焊盘宽_mm':[gap,length,width],
                     '本体最大边角至板边_mm':radius-max(math.dist(board_center,p) for p in body),
                     '仅本体不越板边':all(math.dist(board_center,p)<radius for p in body),
                     '现焊盘符合候选推荐范围':False})
    all_trial=[a for a in copper if a['ref'] not in refs]+[a for ps in revised.values() for a in ps]
    for row in rows:
        ref=row['位号'];bad=[];minimum=(float('inf'),'')
        def record(g,label):
            nonlocal minimum
            minimum=min(minimum,(g,label))
            if g < .15-1e-5:bad.append({'对象':label,'铜间距_mm':g})
        for a in revised[ref]:
            for b in all_trial+vias:
                if b['net']==a['net'] or b['layer'] not in [a['layer'],'11']:continue
                record(distance(a['poly'],b['poly']),b.get('id',b.get('ref','')+'.'+b.get('pin','')))
            for t in tracks:
                if t['net']!=a['net'] and t['layer']==a['layer']:
                    record(track_gap(t,a['poly']),t['id'])
        edge=min(radius-max(math.dist(board_center,p) for p in a['poly']) for a in revised[ref])
        row.update({'不动中心扩大焊盘_最小板边距_mm':edge,
                    '不动中心扩大焊盘_最小异网铜间距_mm':minimum[0],
                    '最近异网图元':minimum[1],
                    '低于0.15mm的图元':bad,
                    '板边0.30mm筛查通过':edge>=.30,
                    '不动中心扩大焊盘_局部铜筛查通过':not bad and edge>=.30})
    witnesses=[]
    for ref,delta in [('C7',(-.10,.09)),('C9',(-.05,.05)),('C10',(.05,0))]:
        trial=[dict(a,poly=[(x+delta[0],y+delta[1]) for x,y in a['poly']]) for a in revised[ref]]
        checks=[]
        for a in trial:
            for b in copper+vias:
                if b.get('ref')==ref or b['net']==a['net'] or b['layer'] not in [a['layer'],'11']:continue
                checks.append((distance(a['poly'],b['poly']),b.get('id',b.get('ref','')+'.'+b.get('pin',''))))
            for t in tracks:
                if t['net']!=a['net'] and t['layer']==a['layer']:
                    checks.append((track_gap(t,a['poly']),t['id']))
        original=[a for a in copper if a['ref']==ref and a['kind']=='pad']
        contacts=[]
        for a in original:
            new=next(b for b in trial if b['pin']==a['pin'])
            old_tracks=[t for t in tracks if t['net']==a['net'] and t['layer']==a['layer'] and track_gap(t,a['poly'])<=1e-5]
            contacts.append({'引脚':a['pin'],'原接触导线':[t['id'] for t in old_tracks],
                             '仍接触':all(track_gap(t,new['poly'])<=1e-5 for t in old_tracks)})
        edge=min(radius-max(math.dist(board_center,p) for p in a['poly']) for a in trial)
        witnesses.append({'位号':ref,'相对R位移_mm':delta,'最近异网铜':[min(checks)[1],min(checks)[0]],
                          '板边距_mm':edge,'原导线接触':contacts,
                          '0.155铜距与0.305板边筛查通过':min(checks)[0]>=.155 and edge>=.305 and all(x['仍接触'] for x in contacts)})
    # 非线性MLCC不能用末端C(V)×V计算充电电荷；此处只是固定标称容量场景。
    charges=[]
    for name,c6,c9,c10 in [('现有标称',1,1,1),('上轮增容候选',4.7,4.7,2.2)]:
        output=c10+22+.5  # 5颗100nF，MCU_EN的1uF单列
        charges.append({'方案':name,'C6_C9标称合计_uF':c6+c9,
                        'C6_C9均按5V常容量估计_uC':(c6+c9)*5,
                        'C6_C9仅正公差20%示例_uF':(c6+c9)*1.2,
                        '3V3直连外置标称_uF':output,
                        'MCU_EN支路额外标称_uF':1,
                        '3V3外置电容按3.3V常容量估计_uC':output*3.3,
                        '另需计入':'PICO内部电容、笔头模块电容、负载电流和充电器启动；C7在充电器后，不直接当VBUS并联。'})
    report['装配与启动续审']={
        '日期':'2026-09-29',
        '三星目录':'https://samsungsem.com/resources/file/kr/support/product_catalog/MLCC_2512.pdf',
        '目录SHA256':hashlib.sha256((ROOT/'references/samsung_mlcc_2512.pdf').read_bytes()).hexdigest(),
        '目录定位':'印刷第48页、公制1005、尺寸公差±0.20；不是英制01005对应的公制0402行',
        '推荐范围_mm':{'间隙':[.42,.50],'单焊盘长':[.53,.61],'单焊盘宽':[.66,.74]},
        '几何':rows,
        '单颗微移见证_未联动写入PCB':witnesses,
        '几何边界':'现有推荐范围不符不等于一定焊不上。只检查推荐下限的局部焊盘/导线/过孔与板边；不含真实器件间本体/高度、装配偏移、阻焊钢网和重铺铜；未修改中心/走线，无原生DRC。',
        '启动标称场景':charges,
        '启动电压说明':'统一取5V仅用于前后同口径比较；实际C9需考虑D4压降或已上电电池，MLCC容量随电压而变。不得将表中电荷视为实测USBET积分。',
        'USB判据来源':'https://compliance.usb.org/index.asp?UpdateFile=Electrical',
        'USB判据':'2021-06更新：至少采集连接后100ms，至少1MS/s；按超过100mA的电流区域积分，降至100mA以下至少100us才分区。电容合计不能代替波形测试。',
        'TLV755P':'手册第6页启动时间550us仅为典型，表条件CIN=COUT=1uF；不能当作大电容下的固定线性上升时间或USB浪涌保证。第13页6.3.3要求考虑启动折返限流与负载。',
        '已有充电边界':'如果109.09mA充电从连接后持续100ms，单这一项的超过100mA电荷约909uC。这是假设场景，不是实测；该风险来自原有固定充电方案，不是增容才引入。保持已确认架构，不自行增加管理电路。',
        '处理决定':'保留原容量、原焊盘和布局，先核实原村田候选。缺少资料不等于原设计失败；三星增容及微移仅为历史备选，不作为默认换料待办。当前不覆盖云端。',
        '设计未修改':True,'制造及电源性能验收':False,
    }
    check_sources()
    target.write_text(json.dumps(report,ensure_ascii=False,separators=(',',':'))+'\n')
    print(json.dumps(report['装配与启动续审'],ensure_ascii=False,indent=2))


def main():
    check_sources()
    records = []
    for mpn, nominal, tolerance, code, refs in PARTS:
        url = 'https://product.samsungsem.com/cn/mlcc/' + mpn[:-1] + '.do'
        raw = urllib.request.urlopen(url, timeout=30).read()
        match = re.search(r'var datasheetData = (\[.*?\]);', raw.decode(), re.S)
        assert match, '官网曲线格式已变，停止'
        graphs = json.loads(match[1])
        dc = next(g for g in graphs if g['graphType'] == 'DCBias')['selectPartsList'][0]
        ac = next(g for g in graphs if g['graphType'] == 'ACVolt')['selectPartsList'][0]
        # AC最小值来自另一条零偏压典型曲线；不可与DC独立相乘后称保证下限。
        ac_factor = 1 + min(y for x, y in points(ac)) / 100
        scenarios = []
        for voltage in [3.3, 3.366, 4.2, 4.242, 5.0, 5.5]:
            change = interpolate(points(dc), voltage)
            typical = nominal * (1 + change / 100)
            scenarios.append({
                '直流偏压_V': voltage, '典型变化百分数': change,
                '典型容量_uF_非保证': typical,
                '独立相乘敏感性_uF_非保证': typical * (1 - tolerance) * .85 * .90 * ac_factor,
            })
        records.append({
            '完整候选料号': mpn, '国内商品编号': code, '评估位号': refs,
            '标称_uF': nominal, '公差': tolerance, '官网': url,
            '网页SHA256': hashlib.sha256(raw).hexdigest(),
            '原始曲线': [g for g in graphs if g['graphType'] in ['DCBias', 'ACVolt', 'TCC']],
            'AC曲线最小容量系数_零偏压典型': ac_factor, '计算': scenarios,
            '已批准替换': False,
        })
    check_sources()
    report = {
        '抓取时间UTC': datetime.now(timezone.utc).isoformat(), '设计源SHA256': SOURCES,
        '性质': '同封装物料候选比较，不是完整BOM、元件库绑定、制造放行或电源验收',
        'PCB原理图云端均未修改': True,
        '电压边界': '5.5V是LDO输入上限的筛查点，不表示USB额定电压；3.366/4.242仅是上偏压敏感性点，不替代完整误差计算。',
        '敏感性条件': '典型DC容量×(1-料号公差)×0.85温度因子×0.90假设老化因子×零偏压AC曲线最小因子。10%老化是假设而非原厂承诺；不同曲线并不独立，结果不可当保证最小容量。',
        '待关闭': ['原村田候选的规格、供应和工作偏压依据；缺项不默认换料', '最大本体及端头与现有焊盘装配复核',
                    '原设计启动和USB插入电流实测；增容仅为历史备选', '物料核定后补全字段及原生复核，不预设改变容量或封装',
                    'C20有效容量与负载瞬态', '采购时库存和SMT分配确认'],
        '候选': records, '允许采购生产': False,
    }
    target = ROOT / 'easyeda_std/克隆板R电容选料筛查.json'
    if target.exists():
        previous=json.loads(target.read_text())
        assert previous['设计源SHA256']==SOURCES
        if '装配与启动续审' in previous:
            report['装配与启动续审']=previous['装配与启动续审']
        if '原村田候选核查' in previous:
            report['原村田候选核查']=previous['原村田候选核查']
    target.write_text(json.dumps(report, ensure_ascii=False, separators=(',', ':')) + '\n')
    for rec in records:
        print(rec['完整候选料号'], rec['评估位号'])
        print(json.dumps(rec['计算'], ensure_ascii=False, indent=2))
    print(target)


def record_originals():
    """归档本轮人工核对的厂家证据，并从R重测焊盘；不修改设计。"""
    from check_pcb_a5 import parse
    check_sources()
    target=ROOT/'easyeda_std/克隆板R电容选料筛查.json'
    report=json.loads(target.read_text())
    assert report['设计源SHA256']==SOURCES
    _,_,copper,_=parse(ROOT/next(iter(SOURCES)))
    specs=[
        ('GRM155R61C105KA12D',['C6'],'C77006','GRM155R61C105KA12-01A.pdf',
         '2026-06-15',2,27,[1.05,.55,.55],[[.3,.5],[.35,.45],[.4,.6]]),
        ('GRM155R61A105KE15D',['C7','C9','C10'],'C76999','GRM155R61A105KE15-01A_立创镜像.pdf',
         '2017-11-17',1,25,[1.05,.55,.55],[[.3,.5],[.35,.45],[.4,.6]]),
        ('GRM21BR61A226ME44L',['C20'],'C441864','GRM21BR61A226ME44-01A.pdf',
         '2026-06-25',2,27,[2.2,1.45,1.45],[[1,1.4],[.6,.8],[1.2,1.4]]),
    ]
    records=[]
    for mpn,refs,code,pdf,date,specpage,landpage,body,ranges in specs:
        dims=[]
        for ref in refs:
            pads=sorted([p for p in copper if p['ref']==ref and p['kind']=='pad'],key=lambda p:p['pin'])
            assert len(pads)==2
            centers=[tuple(sum(p[k] for p in a['poly'])/len(a['poly']) for k in (0,1)) for a in pads]
            pitch=math.dist(*centers)
            axis=tuple((centers[1][k]-centers[0][k])/pitch for k in (0,1))
            sizes=[]
            for pad in pads:
                projections=[[p[0]*v[0]+p[1]*v[1] for p in pad['poly']] for v in [axis,(-axis[1],axis[0])]]
                sizes.append([max(p)-min(p) for p in projections])
            values=[pitch-sum(d[0] for d in sizes)/2,*sizes[0]]
            dims.append({'位号':ref,'实测_间隙_单盘长_宽_mm':values,
                         '在推荐范围内':[lo-1e-5<=v<=hi+1e-5 for v,(lo,hi) in zip(values,ranges)]})
        path=ROOT/'references'/pdf
        records.append({'料号':mpn,'位号':refs,'国内编号':code,'PDF':str(path.relative_to(ROOT)),
            'PDF_SHA256':hashlib.sha256(path.read_bytes()).hexdigest(),'规格书日期':date,
            '规格页':specpage,'推荐焊盘页':landpage,'本体最大长宽高_mm':body,
            '推荐_间隙_单盘长_宽范围_mm':ranges,'当前铜尺寸':dims})
    report['原村田候选核查']={
        '日期':'2026-09-29','条目':records,
        '10V料生命周期':'2026-09-29村田SimSurfing查询GRM155R61A105KE15，结果显示生産中止予定（计划停产）；不是已无库存，未取得具体停产日期。',
        '生命周期来源':'https://ds.murata.com/simsurfing/mlcc.html',
        '供应边界':'三个国内商品条目存在；可分配库存、价格及SMT备料未核实。C1也使用该10V候选，采购时一并处理。',
        '曲线边界':'没有取得原三种料号的组合工作偏压曲线；SimSurfing加载后出现使用许可协议，未代用户接受，不再操作受该协议限制的工具。',
        '结论':'原值原焊盘和布局保持。C6/C7/C9/C10单盘长0.50mm比村田推荐上限0.45mm大；C20单盘长1.41mm/间隙0.59mm偏离推荐0.6–0.8mm/1.0–1.4mm。需装配复核，不推断一定失效或要求换电容。',
        '默认换料':False,'允许生产':False}
    report['待关闭']=['原村田候选工作偏压依据和可采购库存','C20焊盘/锡膏及0402单盘长度的装配复核','USB及制造其他审核','样板供电与热验证']
    if '装配与启动续审' in report:
        report['装配与启动续审']['处理决定']='保留原值、原焊盘、布局；先核原村田候选。三星增容和微移仅历史试算，不是实施待办。'
    check_sources()
    target.write_text(json.dumps(report,ensure_ascii=False,separators=(',',':'))+'\n')
    print(json.dumps(report['原村田候选核查'],ensure_ascii=False,indent=2))


if __name__ == '__main__':
    if sys.argv[1:]==['--fit-only']:
        fit_and_startup()
    elif sys.argv[1:]==['--original-only']:
        record_originals()
    elif not sys.argv[1:]:
        main()
    else:
        raise SystemExit('用法：audit_capacitor_candidates_r.py [--fit-only | --original-only]')
