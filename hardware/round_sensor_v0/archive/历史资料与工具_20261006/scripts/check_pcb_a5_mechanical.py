"""从真实 PCB 导出生成机械审核图；不修改 PCB、电气网络或云端工程。"""
import hashlib
import html
import itertools
import json
import math
from check_pcb_a5 import ROOT, U, parse, rect, distance, xy

SOURCE = ROOT/'easyeda_std/PCB_A5_MLX040_verified_20260916.json'
OUT = ROOT/'easyeda_std'


def box(points):
    return [min(x for x,y in points), min(y for x,y in points),
            max(x for x,y in points), max(y for x,y in points)]


def inspect(source=SOURCE):
    d, parts, copper, holes = parse(source)
    assert len(parts) == 41
    # 原生 LIB 原点不等于 USB 外壳中心。用实际 SH 中心和厂家尺寸配准。
    usb_pads = [p for p in parts['J1']['items'] if p[0]=='PAD']
    stakes = [xy(p[2],p[3]) for p in usb_pads if p[8]=='SH']
    cx = sum(p[0] for p in stakes)/4
    front_stakes = min(p[1] for p in stakes)
    rear_stakes = max(p[1] for p in stakes)
    assert abs(rear_stakes-front_stakes-4.18) < .001
    face = front_stakes-2.60
    cy = face+7.35/2
    row = xy(next(p for p in usb_pads if p[8]=='A1')[2],
             next(p for p in usb_pads if p[8]=='A1')[3])[1]
    # 用信号行与定位孔独立交叉核对配准，而不只相信封装原点。
    row_error = abs(row-(face+7.35+.005))
    hole_y = [xy(p[1],p[2])[1] for p in parts['J1']['items'] if p[0]=='HOLE']
    hole_error = max(abs(y-(face+6.28)) for y in hole_y)
    assert row_error < .002 and hole_error < .005

    # 平面尺寸按当前引脚实际方向对齐；不把底层投影再镜像一次。
    specs = {
        'J1': (8.94,7.35,3.31,9.09,7.50,3.46,'usb4105.pdf，第1页；名义外壳及一般公差'),
        'U1': (7,7,.96,7.1,7.1,1.06,'esp32-s3-pico-1.pdf，第30页'),
        'U2': (2.5,2,.355,2.6,2.1,.4,'mlx90393.pdf，第39页；按当前左右引脚排布旋转'),
        'U3': (3,2.5,.83,3.1,2.6,.86,'ST LSM6DSOX DS12814 Rev4，第160页；按实际引脚方向'),
        'U4': (.922,1.155,.55,.947,1.180,.588,'sgm40567.pdf，第14页'),
        'U5': (2,2,.75,2.1,2.1,.8,'tlv755p.pdf，第41页 DRV0006A'),
        'U6': (.8,1,.47,.85,1.05,.5,'tpd2eusb30a.pdf，第26页 DRT；不含引脚/飞边最大外包'),
        'Q1': (1,.6,.48,1.05,.65,.53,'lp0404n3t5g.pdf，第6页'),
        'D4': (1,.6,.48,1.05,.65,.53,'lmbr4010bst5g.pdf，第3页'),
        'ANT1': (3,3.1,1.25,None,None,None,'Hirose_U.FL_catalog.pdf，第12页；保守外包矩形，非精细本体'),
    }
    bodies = {}
    for ref, p in parts.items():
        if ref in ('J2','J3','SW1'):
            continue  # 这些是裸焊盘，不冒充板载连接器或开关本体。
        verified = ref in specs
        if verified:
            w,h,z,mw,mh,mz,src = specs[ref]
        elif ref.startswith('D'):
            w,h,z,mw,mh,mz,src = 1,.6,None,None,None,None,'TI DPY 标称尺寸；最大高度/公差待定'
        elif ref=='C20':
            w,h,z,mw,mh,mz,src = 2,1.25,1.3,None,None,None,'0805 库名标称；具体料号未定，非厂家最大尺寸'
        else:
            w,h,z,mw,mh,mz,src = 1,.5,.5,None,None,None,'0402 标称示意；具体料号未定，非厂家最大尺寸'
        center = (cx,cy) if ref=='J1' else p['center']
        if ref=='ANT1':
            # 2.6 mm 本体关于扣合中心对称，信号端延伸到 +1.8 mm。
            center=(center[0],center[1]+.25)
        bodies[ref] = dict(center=list(center), layer=p['layer'],
                           nominal_mm=[w,h,z], maximum_mm=[mw,mh,mz], source=src,
                           drawing_checked=verified, fitted=ref not in ('C30','C31'),
                           polygon=rect(*center,w,h))
    # 本体只是二维筛查，不把通过称为装配合格。
    gaps = []
    for (ra,a),(rb,b) in itertools.combinations(bodies.items(),2):
        if a['layer'] != b['layer'] or not a['fitted'] or not b['fitted']:
            continue
        gap=distance(a['polygon'],b['polygon'])
        if gap<.2-.0001:
            gaps.append({'元件':[ra,rb],'名义本体间距_mm':round(gap,4),
                         '性质':'部分本体为未选料号标称值，不能用于制造放行'})
    radial = max(math.hypot(x,y) for x,y in bodies['J1']['polygon'])
    native_origin_delta = [cx-parts['J1']['center'][0],cy-parts['J1']['center'][1]]
    pin_positions = {p[8]:xy(p[2],p[3]) for p in parts['U2']['items'] if p[0]=='PAD'}
    pitches = [math.dist(pin_positions[str(i)],pin_positions[str(i+1)]) for i in (1,2,3)]
    mlx_matches = all(abs(p-.4)<.0003 for p in pitches)
    usb = {
        '外壳中心_mm':[cx,cy], '原生定位点至外壳中心偏移_mm':native_origin_delta,
        '开口线_y_mm':face, '相对圆板最前端外伸_mm':-9-face,
        '名义外壳角点半径_mm':radial,
        '不挖侧孔且完全包住外壳的同心内径几何下限_mm':2*radial,
        '信号焊盘行配准误差_mm':row_error, '定位孔配准误差_mm':hole_error,
        '说明':'同心内径下限只是不挖侧孔的几何比较，不是推荐笔杆内径；可通过侧开孔/可拆结构让 USB 外壳局部穿出。',
        '壳体算例':{'板径_mm':18,'径向装配间隙_mm':.25,'打印壁厚_mm':1,
                    '圆筒内径_mm':18.5,'圆筒外径_mm':20.5,
                    '沿中心线接口相对外壁内缩_mm':10.25+face,
                    '状态':'均为演示参数，非打印成品尺寸；缺少线缆宽度、打印公差与装配方案'},
        '插头厂家配合示意':{'插头尾壳高度上限_mm':6.5,'完全插入时尾壳至母座前端最小距离_mm':1.85,
                            '来源':'usb4105.pdf 第1页；具体线缆仍需实测'}
    }
    terminals = {}
    for ref in ('J2','J3','SW1'):
        padpoints=[q for p in copper if p['ref']==ref for q in p['poly']]
        bb=box(padpoints)
        terminals[ref]={'铜包围框_mm':bb,'暂定操作区_mm':[bb[0]-.5,bb[1]-.5,bb[2]+.5,bb[3]+.5],
                        '说明':'0.5 mm 外扩仅为操作区提示，不是已验证的探针/焊接/导线净空'}
    result = {
        '日期':'2026-09-16','输入':source.name,'输入SHA256':hashlib.sha256(source.read_bytes()).hexdigest(),
        '状态':('U2节距已修正；机械与制造验证未完成，禁止投板' if mlx_matches else '机械审核发现封装阻塞项；禁止按现版投板或冻结布局'),
        'PCB与网络未修改':True,'板径_mm':18,'器件本体':bodies,'USB核对':usb,
        'MLX封装阻塞项':{'位号':'U2','型号':'MLX90393SLQ-ABA-011-RE',
                        '节距错误已修正':mlx_matches,
                        '当前焊盘中心距_mm':pitches,'厂家端子中心距_mm':.4,
                        '来源':'mlx90393.pdf 第39页图28',
                        '后果':('已替换专用0.40mm封装，原生几何/网络回读见mlx90393_native_verification.json；钢网制造审核仍待完成。' if mlx_matches else '当前通用0.50mm节距封装不匹配；需重建/替换专用0.40mm封装并复核EP、焊盘、1脚及轴向。')},
        '同面名义本体间距小于0.2mm':gaps,'焊线与测试操作区':terminals,
        '天线':{'FPC名义尺寸_mm':[5.9,4.1,.24],'FPC图纸上限_mm':[6.2,4.4,.34],
                '线缆标称长度_mm':45,'线缆标称直径_mm':.81,
                '线端接头外形上限_mm':[5.7,3.2],
                '来源':'FXP75.07.0045B.pdf，第5页，SPE-13-8-067-F',
                '待定':'端头相对扣合中心偏移、混配后的扣合高度、线缆允许弯曲半径、轴向转弯、FPC贴附位置与射频净空'},
        '限制':['未将二维本体间距当作焊接/装配合格。','无电池尺寸、实际USB线缆外包胶宽度、打印公差或支架，因此不能给最终壳体。',
                '通孔壳脚长度可选0.60/0.95/1.20mm，需结合板厚确认底部凸出；未选定。',
                '底面图采用顶视投影，供空间对照，不是翻板安装视图。','小阻容为标称示意，料号/高度未冻结。']
    }
    return result,parts,copper,holes


def render(result,parts,copper,holes):
    bodies=result['器件本体']; usb=result['USB核对']; face=usb['开口线_y_mm']
    fixed=result['MLX封装阻塞项']['节距错误已修正']
    s=['<svg xmlns="http://www.w3.org/2000/svg" width="1500" height="1510" viewBox="0 0 1500 1510">',
       '<rect width="1500" height="1510" fill="#f5f7fa"/>',
       '<style>text{font-family:"PingFang SC","Microsoft YaHei",sans-serif;fill:#20334a} .small{font-size:16px}.body{font-size:19px}.head{font-size:25px;font-weight:600}</style>',
       '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="#ad6120"/></marker></defs>',
       '<text x="42" y="49" font-size="31" font-weight="650">A5 圆板 · 机械空间审核</text>',
       '<text x="42" y="83" class="body">基于真实 18 mm PCB 云端回读 · U2 专用封装修订 · 未布线 · 2026-09-16</text>',
       '<rect x="40" y="106" width="1420" height="66" rx="9" fill="#fff0ed" stroke="#dfb4ab"/>',
       '<text x="59" y="133" class="body" fill="#ab352c">'+('U2 已修正为 0.40 mm 专用封装；原理图绑定、PCB 几何和云端重开回读一致。' if fixed else '阻塞项：U2 现有焊盘节距 0.50 mm；厂家端子节距 0.40 mm。')+'</text>',
       '<text x="59" y="158" class="small">'+('U2 向内微移 0.10 mm；与 C2 铜间隙约 0.23 mm。全板仍未布线，不是可生产图。' if fixed else '应先修正专用封装，再确定最终布局。本图不是可生产图。')+'</text>']
    scale=26
    for i,layer in enumerate(('1','2')):
        ox,oy=380+740*i,515
        s.append(f'<text x="{ox}" y="215" text-anchor="middle" class="head">'+('顶面' if layer=='1' else '底面（顶视投影）')+'</text>')
        def poly(points,style):
            points=' '.join(f'{ox+x*scale:.2f},{oy+y*scale:.2f}' for x,y in points)
            s.append(f'<polygon points="{points}" {style}/>')
        s.append(f'<circle cx="{ox}" cy="{oy}" r="{9*scale}" fill="#eaf2ef" stroke="#397b65" stroke-width="2.5"/>')
        # 对面 USB 壳体/贯穿脚投影，帮助理解轴向叠放。
        if layer=='2':
            poly(bodies['J1']['polygon'],'fill="none" stroke="#9ca9b8" stroke-width="1.2" stroke-dasharray="6 6"')
        for p in copper:
            if p['layer'] not in (layer,'11'):continue
            poly(p['poly'],'fill="#c48c3f" fill-opacity=".65" stroke="#fff" stroke-width=".4"')
        for h in holes:
            poly(h['poly'],'fill="#f5f7fa" stroke="#5e6a76" stroke-width="1"')
        for ref,b in bodies.items():
            if b['layer']!=layer:continue
            color='#bf453d' if ref=='U2' and not fixed else ('#317ca0' if b['drawing_checked'] else '#8795a2')
            dash='' if b['fitted'] else 'stroke-dasharray="3 3"'
            poly(b['polygon'],f'fill="{color}" fill-opacity=".12" stroke="{color}" stroke-width="1.5" {dash}')
            x,y=b['center']
            if ref.startswith(('U','ANT','Q')) or ref in ('J1','C20','D4'):
                label=f'{ref} 待修' if ref=='U2' and not fixed else ref
                s.append(f'<text x="{ox+x*scale}" y="{oy+y*scale+5}" text-anchor="middle" font-size="14" font-weight="600">{label}</text>')
        if layer=='1':
            fy=oy+face*scale
            s.append(f'<line x1="{ox-4.47*scale}" y1="{fy}" x2="{ox+4.47*scale}" y2="{fy}" stroke="#b55f18" stroke-width="4"/>')
            s.append(f'<line x1="{ox}" y1="238" x2="{ox}" y2="{fy-10}" stroke="#b55f18" stroke-width="2" marker-end="url(#arrow)"/>')
            s.append(f'<text x="{ox+22}" y="246" class="small">USB 插入方向</text>')
            ax,ay=parts['ANT1']['center']
            s.append(f'<circle cx="{ox+ax*scale}" cy="{oy+ay*scale}" r="{2*scale}" fill="none" stroke="#a373ae" stroke-width="1.4" stroke-dasharray="5 4"/>')
            s.append(f'<text x="{ox-250}" y="814" class="small">蓝色：已核图的本体 / 外包；灰色：未选料号的标称示意。</text>')
            s.append(f'<text x="{ox-250}" y="838" class="small">紫圈：天线垂直扣合操作区提示，半径 2 mm 为暂定值。</text>')
        else:
            for ref,t in result['焊线与测试操作区'].items():
                x0,y0,x1,y1=t['暂定操作区_mm']
                poly([(x0,y0),(x1,y0),(x1,y1),(x0,y1)],'fill="none" stroke="#996ba2" stroke-width="1.5" stroke-dasharray="5 4"')
                s.append(f'<text x="{ox+(x0+x1)/2*scale}" y="{oy+(y0+y1)/2*scale+5}" font-size="14" text-anchor="middle">{ref}</text>')
            s.append(f'<text x="{ox-275}" y="814" class="small">J2：电池焊线；SW1：外接开关焊线；J3：测试焊盘。</text>')
            s.append(f'<text x="{ox-275}" y="838" class="small">紫框为铜边外扩 0.5 mm 的操作提示，不是装配放行。</text>')
        s.append(f'<line x1="{ox-234}" y1="766" x2="{ox+234}" y2="766" stroke="#397b65"/>')
        s.append(f'<text x="{ox}" y="789" text-anchor="middle" class="small">圆板直径 18 mm（试排）</text>')
    s.extend(['<rect x="40" y="853" width="1420" height="315" rx="10" fill="white" stroke="#d7e0e9"/>',
              '<text x="62" y="890" class="head">USB 与圆形笔杆：必须设计侧开孔和装配路径</text>'])
    lines=[
        f'① USB 名义外壳 8.94 × 7.35 mm，高 3.31 mm；开口线 y = {face:.3f} mm。',
        f'② 外壳前角超出半径 9 mm 圆板约 {usb["名义外壳角点半径_mm"]-9:.2f} mm；这是壳体外伸，不是铜焊盘越界。',
        f'③ 若用无侧开孔的完整圆筒包住整个外壳，同心内径几何下限约 {usb["不挖侧孔且完全包住外壳的同心内径几何下限_mm"]:.2f} mm（尚未加公差）。',
        '④ 为保持细笔杆，应评估局部侧开孔、接口凹口及分体装壳，不必直接把整根笔杆做粗。',
        '⑤ 演示：径向间隙 0.25 mm、壁厚 1.0 mm → 内径 18.5 mm / 外径 20.5 mm；不是最终尺寸。',
        f'   该例接口相对最前外壁内缩约 {usb["壳体算例"]["沿中心线接口相对外壁内缩_mm"]:.2f} mm；还须代入实际插头尾壳和圆弧侧壁。',
        '⑥ 厂家配合图给出尾壳高度 6.5 mm 上限及 1.85 mm 最小退距；插头宽度、线缆型号仍待确认。']
    for j,line in enumerate(lines):s.append(f'<text x="62" y="{927+j*31}" class="body">{html.escape(line)}</text>')
    s.extend(['<rect x="40" y="1188" width="1420" height="225" rx="10" fill="white" stroke="#d7e0e9"/>',
              '<text x="62" y="1225" class="head">沿笔杆轴向，还要给这些部件留空间</text>'])
    lines=['USB 顶面名义高度 3.31 mm；底面 IMU 最大高度 0.86 mm。板厚、焊料、线头和支架须另加。',
           'FPC 天线片：5.9 × 4.1 × 0.24 mm；线长标称 45 mm、线径 0.81 mm，须贴在壳内合适位置。',
           '天线线端接头外形上限约 5.7 × 3.2 mm；不能只按板上 3.0 × 3.1 mm 插座来留空间。',
           '未确定：电池外形、USB 线尾壳宽度、实际扣合高度、弯曲半径、固定结构与打印公差。']
    for j,line in enumerate(lines):s.append(f'<text x="62" y="{1261+j*35}" class="body">{html.escape(line)}</text>')
    s.extend(['<text x="42" y="1455" class="small">来源：GCT、Melexis、Espressif、Hirose、ST、TI、SG Micro、LRC、Taoglas 尺寸图；详见机械审核记录。</text>',
              '<text x="42" y="1483" class="small">二维检查，不代表实物可装配、射频合格或可投板；本图不是壳体加工图。</text>','</svg>'])
    (OUT/'PCB_A5_机械空间审核.svg').write_text('\n'.join(s))


def main():
    result,parts,copper,holes=inspect()
    (OUT/'pcb_a5_mechanical_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    render(result,parts,copper,holes)
    print(json.dumps({k:result[k] for k in ['状态','USB核对','MLX封装阻塞项','同面名义本体间距小于0.2mm']},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
