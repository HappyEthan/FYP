#!/usr/bin/env python3
"""Build a portable relative-link catalogue without changing experimental data."""
import argparse
import csv
import hashlib
import html
import json
import math
import os
import re
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, unquote
from zoneinfo import ZoneInfo

CATEGORIES={
    '01_阶梯与前馈标定':'阶梯压深与前馈标定来源',
    '02_四方向速度压深':'四方向平移、速度与压深实验',
    '03_动态辨识与接触':'Z动态辨识与独立接触进笔',
    '04_磁目标跟踪反馈':'磁目标跟踪、P／PI与限幅对照',
    '05_笔画与多笔轨迹':'笔画试写、路径编辑与多笔轨迹',
    '06_传感器诊断':'传感器检查与诊断导出（非独立机器人运行）',
    '07_手采磁数据':'手持毛笔录制（无同步XY）',
    '08_待核实':'类型或来源待核实',
}
STATUS={'completed':'完成','aborted':'主动／保护中止','fault':'故障','interrupted':'非正常中断','manual_recording':'手采录制','diagnostic':'检查／诊断导出'}


def read_json(path):
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return {}


def csv_stats(filename):
    """Streaming inspection: never interpolate, fill fields or write the source."""
    path=Path(filename);before=path.stat();count=invalid=raw_missing=delta_missing=time_missing=clock_faults=wraps=short=0
    intervals=Counter();elapsed=0;last=None;raw_available=delta_available=False;error=None
    try:
        with path.open(newline='') as stream:
            reader=csv.reader(stream);header=next(reader,[]);lookup={name:i for i,name in enumerate(header)}
            raw=[lookup.get(k) for k in ('Bx_uT','By_uT','Bz_uT')]
            delta=[lookup.get(k) for k in ('dBx_uT','dBy_uT','dBz_uT')]
            raw_available=all(i is not None for i in raw);delta_available=all(i is not None for i in delta)
            time_index=lookup.get('sensor_t_us',lookup.get('t_us'));valid_index=lookup.get('valid',lookup.get('sample_valid'))
            def finite(row,indices):
                try:return all(math.isfinite(float(row[i])) for i in indices)
                except (ValueError,IndexError):return False
            for row in reader:
                if not row:continue
                count+=1
                if len(row)<len(header):short+=1
                if valid_index is not None and (valid_index>=len(row) or row[valid_index].lower() not in ('true','1')):invalid+=1
                if raw_available and not finite(row,raw):raw_missing+=1
                if delta_available and not finite(row,delta):delta_missing+=1
                try:t=int(row[time_index]) if time_index is not None else None
                except (IndexError,ValueError):t=None
                if t is None:time_missing+=1;continue
                if last is not None:
                    dt=t-last
                    if dt<0 and last>2**32-1_000_000 and t<1_000_000:dt+=2**32;wraps+=1
                    if dt>0:intervals[dt]+=1;elapsed+=dt
                    else:clock_faults+=1
                last=t
    except (OSError,csv.Error) as exc:error=str(exc)
    n=sum(intervals.values());median=None
    if n:
        ranks=[(n-1)//2,n//2];values=[];cumulative=0
        for dt,frequency in sorted(intervals.items()):
            for rank in ranks:
                if cumulative<=rank<cumulative+frequency:values.append(dt)
            cumulative+=frequency
        median=sum(values)/2
    return dict(samples=count,invalid_rows=invalid,raw_axes_available=raw_available,delta_axes_available=delta_available,
        raw_missing_rows=raw_missing if raw_available else None,delta_missing_rows=delta_missing if delta_available else None,
        missing_time_rows=time_missing,clock_faults=clock_faults,clock_wraps=wraps,short_rows=short,
        nominal_interval_us=median,nominal_rate_hz=1e6/median if median else None,
        intervals_over_twice_median=sum(v for dt,v in intervals.items() if median and dt>2*median),
        accumulated_sensor_s=elapsed/1e6,bytes=before.st_size,source_changed_during_scan=before.st_mtime_ns!=path.stat().st_mtime_ns,
        read_error=error)


def purpose(spec,folder):
    name=spec.get('name','');kind=spec.get('path',{}).get('kind');label=spec.get('run_label','')+' '+folder.name
    if kind=='ladder':return '01_阶梯与前馈标定'
    if name=='contact_entry_test' or kind=='z_identification':return '03_动态辨识与接触'
    if kind=='four_direction_sweep':return '02_四方向速度压深'
    if kind=='strokeplan':
        if re.search(r'edited|heng|zhong|yong|横|永|中字',label,re.I) or spec.get('path',{}).get('stroke_count',1)>1:return '05_笔画与多笔轨迹'
        return '04_磁目标跟踪反馈'
    return '08_待核实'


def day_of(manifest,folder):
    try:return datetime.fromisoformat(manifest.get('started_at',manifest.get('created_at',''))).astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
    except (ValueError,TypeError):
        return next((part for part in folder.parts if re.fullmatch(r'20\d\d-\d\d-\d\d',part)),'日期待核')


def build(root,workers):
    root=root.resolve();nav=root/'实验数据导航';generated=[];warnings=[]
    def rel(path):return Path(path).relative_to(root).as_posix()
    def md(text):return str(text).replace('|','／').replace('\n',' ').replace('[','［').replace(']','］')
    def link(page,target,label=None,anchor=''):
        target=Path(target);url=quote(os.path.relpath(target,page.parent).replace(os.sep,'/'),safe='/._-')
        return f'[{md(label or target.name)}]({url}{"#"+anchor if anchor else ""})'
    def write(page,body):
        page.parent.mkdir(parents=True,exist_ok=True)
        page.write_text('<!-- Generated by scripts/generate_experiment_navigation.py; relative paths only. -->\n'+body)
        generated.append(page)
    def existing(page,folder,names):
        return ' · '.join(link(page,folder/name,label) for name,label in names if (folder/name).is_file()) or '无对应文件'

    files=[]
    for base in [root/'runs',root/'outputs',root/'docs/05-data-acquisition/results/legacy-acceptance']:
        if base.exists():files.extend(p for p in base.rglob('*') if p.is_file() and '__pycache__' not in p.parts and not p.name.endswith(('.pyc','.tmp','.lock')))
    files=sorted(set(files));records=[];record_dirs=set()
    for manifest_file in sorted((root/'runs').rglob('manifest.json')):
        manifest=read_json(manifest_file)
        if manifest.get('execution_environment')!='hardware':continue
        folder=manifest_file.parent;spec=read_json(folder/'resolved.json');record_dirs.add(folder)
        records.append(dict(kind='hardware',folder=rel(folder),brush=next((p for p in folder.parts if re.fullmatch(r'brush\d+',p)),'未知毛笔'),
            date=day_of(manifest,folder),status=manifest.get('status','未知'),run_id=manifest.get('run_id'),label=spec.get('run_label',folder.name),
            category=purpose(spec,folder),reason=manifest.get('reason',''),control=spec.get('control',{}).get('mode','纯前馈／无磁反馈'),
            path_kind=spec.get('path',{}).get('kind'),axis=spec.get('path',{}).get('axis'),stroke_count=spec.get('path',{}).get('stroke_count'),
            started_at=manifest.get('started_at'),baseline_count=len(manifest.get('baselines') or ([manifest['baseline']] if manifest.get('baseline') else [])),
            sensor=rel(folder/'sensor.csv') if (folder/'sensor.csv').exists() else None,
            signal_feature=spec.get('signal',read_json(folder/'feedforward.json').get('feature'))))
    for sensor in sorted((root/'runs').rglob('sensor.csv')):
        if sensor.parent in record_dirs:continue
        folder=sensor.parent;summary=read_json(folder/'summary.json')
        records.append(dict(kind='diagnostic',folder=rel(folder),brush='brush2',date=day_of(summary,folder),status='diagnostic',
            run_id=None,label=folder.name,category='06_传感器诊断',reason='',control='不适用',sensor=rel(sensor),
            diagnostic_mode=summary.get('mode','未记录'),replay_source=summary.get('source_run'),baseline_count=0))
    for index in sorted((root/'runs').rglob('records.csv')):
        if 'manual' not in index.parts:continue
        with index.open(newline='') as stream:
            for row in csv.DictReader(stream):
                sensor=index.parent/row.get('sensor_csv','')
                if not sensor.is_file():continue
                folder=index.parent;meta=read_json(sensor.with_suffix('.json'))
                records.append(dict(kind='manual',folder=rel(folder),brush=next((p for p in folder.parts if re.fullmatch(r'brush\d+',p)),'未知毛笔'),
                    date=day_of(meta,folder),status='manual_recording',run_id=row.get('recording_id'),label=row.get('action','未标注动作'),
                    category='07_手采磁数据',reason=row.get('note',''),control='无同步机器人反馈',sensor=rel(sensor),
                    manual_meta=rel(sensor.with_suffix('.json')),baseline_count=1 if meta.get('baseline_B0_uT') else 0))
    records.sort(key=lambda x:(x['date'],x.get('started_at') or x.get('run_id') or x['folder']))
    for i,r in enumerate(records):r['id']=f'R{i+1:04d}'
    sensor_paths=sorted({root/r['sensor'] for r in records if r.get('sensor')})
    print(f'Inspecting {len(sensor_paths)} magnetic CSV files; raw data remain unchanged.',flush=True)
    statistics={}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i,(path,stats) in enumerate(zip(sensor_paths,pool.map(csv_stats,map(str,sensor_paths),chunksize=4))):
            statistics[rel(path)]=stats
            if (i+1)%100==0:print(f'  inspected {i+1}/{len(sensor_paths)} CSV files',flush=True)
    by_day=defaultdict(list);by_category=defaultdict(list)
    for r in records:
        r['magnetic_stats']=statistics.get(r.get('sensor'));by_day[(r['brush'],r['date'])].append(r);by_category[r['category']].append(r)
        r['detail_page']=rel(nav/'按日期'/f'{r["brush"]}_{r["date"]}.md')
        folder=root/r['folder'];quality=read_json(folder/'analysis/magnetic_sampling_summary.json')
        r['derived_magnetic']=rel(folder/'analysis/magnetic_timeseries.csv') if (folder/'analysis/magnetic_timeseries.csv').is_file() else None
        r['quality_report']=rel(folder/'analysis/magnetic_sampling_summary.json') if (folder/'analysis/magnetic_sampling_summary.json').is_file() else None
        r['offline_baseline_rows']=quality.get('offline_baseline_rows')
    def stats_text(r):
        s=r.get('magnetic_stats')
        if not s:return '无磁CSV，不能当作有效磁测量'
        rate=f'{s["nominal_rate_hz"]:.2f} Hz' if s['nominal_rate_hz'] else '频率不可估计'
        return f'{s["samples"]:,} 行；无效 {s["invalid_rows"]}；{rate}'
    def row(page,r):
        sensor=link(page,root/r['sensor'],'**原始磁CSV**') if r.get('sensor') else '**缺失原始磁CSV**'
        derived=link(page,root/r['derived_magnetic'],'派生ΔB') if r.get('derived_magnetic') else '无派生表'
        return f'| {link(page,root/r["detail_page"],r["id"],r["id"].lower())} | {r["date"]} | {md(r["label"])} | {STATUS.get(r["status"],md(r["status"]))} | {sensor} · {derived} | {stats_text(r)} |'
    table_header='| 编号 | 日期 | 记录标签 | 执行状态 | 磁传感文件 | 原始采样概况 |\n|---|---|---|---|---|---|\n'
    for key,items in by_day.items():
        page=nav/'按日期'/f'{key[0]}_{key[1]}.md'
        body=f'# {key[0]} · {key[1]}\n\n'+link(page,root/'实验数据总导航.md','返回总导航')+'\n\n'+table_header+'\n'.join(row(page,r) for r in items)+'\n'
        for r in items:
            folder=root/r['folder'];s=r.get('magnetic_stats') or {}
            body+=f'\n<a id="{r["id"].lower()}"></a>\n## {r["id"]} · {md(r["label"])}\n\n'
            body+=f'- 类别：{CATEGORIES[r["category"]]}；状态：{STATUS.get(r["status"],r["status"])}；控制：{md(r["control"])}。\n'
            body+=f'- 记录目录：{link(page,folder,r["folder"])}；运行ID：`{r.get("run_id") or "无硬件运行ID"}`。\n'
            if r.get('sensor'):body+=f'- **磁数据主文件：{link(page,root/r["sensor"])}**。{stats_text(r)}。\n'
            if r.get('derived_magnetic'):body+=f'- 原始频率派生磁响应：{link(page,root/r["derived_magnetic"])}；质量报告：{link(page,root/r["quality_report"])}；离线补基线行数：{r.get("offline_baseline_rows")}。\n'
            if s:
                body+=f'- 三轴B列：{"有" if s["raw_axes_available"] else "无"}；ΔB列：{"有" if s["delta_axes_available"] else "无"}；B缺值行：{s["raw_missing_rows"] if s["raw_missing_rows"] is not None else "未记录B列"}；ΔB缺值行：{s["delta_missing_rows"] if s["delta_missing_rows"] is not None else "未记录ΔB列"}（包含基线采集阶段）。\n'
                body+=f'- 全CSV时轴检查：超过2倍中位采样间隔 {s["intervals_over_twice_median"]} 处；非递增时间 {s["clock_faults"]} 处；缺时间 {s["missing_time_rows"]} 行；截短行 {s["short_rows"]}。不等同于书写阶段丢帧结论。\n'
            body+=f'- 基线与条件：{existing(page,folder,[("manifest.json","manifest／B0基线"),("calibration.json","标定快照"),("feedforward.json","前馈映射"),("setup.json","实际安装条件"),("settings.json","请求设置"),("session.json","手采条件")])}。\n'
            body+=f'- 机器人／控制与目标：{existing(page,folder,[("control.jsonl","磁反馈／目标／命令"),("actual_tcp.csv","实际TCP"),("actual_tcp_meta.json","TCP采集说明"),("resolved.json","本次实验定义"),("strokeplan.npz","目标路径（非磁实测）"),("timeline.npz","命令时间线"),("events.jsonl","事件／异常")])}。\n'
            if r.get('manual_meta'):body+=f'- 手采基线和采样说明：{link(page,root/r["manual_meta"])}；该CSV为原始记录的ΔB，不能当作同时记录了XY／TCP。\n'
            if r.get('diagnostic_mode'):body+=f'- 诊断模式：{md(r["diagnostic_mode"])}；诊断提取或回放不重复计入机器人执行次数。\n'
            if r.get('reason'):body+=f'- 记录说明／终止原因：{md(r["reason"])}。\n'
            companions=sorted(p for p in folder.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
            body+='\n<details><summary>展开本次记录的全部文件</summary>\n\n'+'\n'.join(f'- {link(page,p,str(p.relative_to(folder)))}' for p in companions)+'\n\n</details>\n'
        write(page,body)
    for category,title in CATEGORIES.items():
        page=nav/'按类别'/f'{category}.md';items=by_category[category]
        write(page,f'# {title}\n\n'+link(page,root/'实验数据总导航.md','返回总导航')+f'\n\n共 {len(items)} 条记录。类别按实验定义、路径类型与标签归类；疑似书写的多笔轨迹不自动等同于某个汉字。\n\n'+table_header+'\n'.join(row(page,r) for r in reversed(items))+'\n')
    # Complete file navigation includes offline plans and auxiliary analyses too.
    groups=defaultdict(list)
    for file in files:
        parts=file.relative_to(root).parts
        group='_'.join(parts[:3])
        if len(parts)>4 and parts[:4]==('runs','brush2','plans','interactive'):group='_'.join(parts[:5])
        groups[group].append(file)
    inventory_rows=[]
    inventory_index=nav/'全文件目录.md'
    for i,(group,items) in enumerate(sorted(groups.items()),1):
        page=nav/'文件目录'/f'{i:02d}_{group}.md';dirs=defaultdict(list)
        for file in items:dirs[file.parent].append(file)
        body=f'# 文件目录 · {group}\n\n'+link(page,inventory_index,'返回文件目录总表')+f'\n\n{len(items)} 个文件。此页同时含实测、分析和离线方案；有文件不等于执行过硬件。\n'
        for folder,entries in sorted(dirs.items()):
            body+=f'\n<details><summary>{html.escape(rel(folder))}（{len(entries)} 文件）</summary>\n\n'
            body+='\n'.join(f'- {link(page,p)} · {p.stat().st_size:,} B' for p in entries)+'\n\n</details>\n'
        write(page,body);inventory_rows.append((group,page,len(items),sum(p.stat().st_size for p in items)))
    write(inventory_index,'# 全文件目录\n\n'+link(inventory_index,root/'实验数据总导航.md','返回总导航')+'\n\n覆盖runs、outputs与文档中的历史验收资料；不包括虚拟环境、Git对象和缓存。\n\n| 分组 | 文件数 | 大小MiB |\n|---|---|---|\n'+'\n'.join(f'| {link(inventory_index,p,g)} | {n} | {size/1024**2:.1f} |' for g,p,n,size in inventory_rows)+'\n')
    # Group copied calibration tables by identical parsed contents; retain every location.
    calibrations=defaultdict(list);table_values={}
    for path in files:
        if path.name.startswith('feedforward') and path.suffix=='.json':
            value=read_json(path);key=hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
            calibrations[key].append(path);table_values[key]=value
    page=nav/'前馈与标定表.md';body='# 前馈与标定映射导航\n\n'+link(page,root/'实验数据总导航.md','返回总导航')+'\n\n映射表与原始磁测量分开保存。amplitude_uT→depth_mm是磁响应到名义压深的映射，不是牛顿力标定；相同内容的副本合并展示，所有位置保留。高速或低响应试验标记不等于新增条件已实测。四姿态阶梯不自动当作四个平移方向，具体条件见resolved.json和安装快照。\n'
    for i,(key,locations) in enumerate(sorted(calibrations.items(),key=lambda item:str(item[1][0])) ,1):
        value=table_values[key];amps=value.get('amplitude_uT') or [];depth=value.get('depth_mm') or []
        body+=f'\n## T{i:03d} · {md(value.get("calibration_id","无标定ID"))}\n\n'
        body+=f'- 映射节点 {len(amps)}；磁响应范围 {min(amps) if amps else "未提供"}–{max(amps) if amps else "未提供"} μT；名义压深 {min(depth) if depth else "未提供"}–{max(depth) if depth else "未提供"} mm。\n'
        body+=f'- 表内速度字段：{value.get("speed_mm_s","未提供")} mm/s；高速试验标记：{bool(value.get("high_speed_trial"))}；低响应试验标记：{bool(value.get("low_response_trial"))}。\n'
        body+='\n<details><summary>全部副本位置（'+str(len(locations))+'）</summary>\n\n'+'\n'.join('- '+link(page,p,rel(p)) for p in locations)+'\n\n</details>\n'
    write(page,body)
    hardware=[r for r in records if r['kind']=='hardware'];manual=[r for r in records if r['kind']=='manual'];diagnostics=[r for r in records if r['kind']=='diagnostic']
    statuses=Counter(r['status'] for r in hardware);sensor_samples=sum(r['magnetic_stats']['samples'] for r in hardware if r.get('magnetic_stats'))
    bad=[r for r in records if r['kind']=='hardware' and (r['status']!='completed' or not r.get('magnetic_stats') or not r['magnetic_stats']['samples'] or r['magnetic_stats']['invalid_rows'] or r['magnetic_stats']['raw_missing_rows'])]
    page=nav/'异常与不完整记录.md'
    write(page,'# 异常与不完整记录\n\n'+link(page,root/'实验数据总导航.md','返回总导航')+'\n\n本表收录未完成运行、空磁文件、原始B缺值或无效标记。中止运行也可能保存有效测量窗口；完成不代表没有时轴间隔或可以直接训练。只保留原样，未剔除、补点或改写。\n\n'+table_header+'\n'.join(row(page,r) for r in bad)+'\n')
    page=nav/'磁传感数据总表.md'
    body='# 磁传感数据总表\n\n'+link(page,root/'实验数据总导航.md','返回总导航')+' · '+link(page,nav/'磁传感数据说明.md','字段、空值与质量判读')+'\n\n逐条直达全部原始磁CSV。采样频率按传感时钟正间隔中位数估算；间隔异常覆盖全CSV，包含基线和启动阶段，不能直接判成书写中丢帧。ΔB空值包含基线采集期；手采只有ΔB，B列未记录。\n\n'
    body+='| 记录／日期 | 类别 | 原始磁数据 | 处理／控制数据 | 行数（无效） | 典型Hz | B／ΔB缺值行 | 超2倍间隔处数 |\n|---|---|---|---|---|---|---|---|\n'
    for r in reversed(records):
        s=r.get('magnetic_stats') or {};folder=root/r['folder']
        sensor=link(page,root/r['sensor'],'**原始CSV**') if r.get('sensor') else '**缺失CSV**'
        related=[]
        if r.get('derived_magnetic'):related.append(link(page,root/r['derived_magnetic'],'派生ΔB'))
        if r.get('quality_report'):related.append(link(page,root/r['quality_report'],'质量报告'))
        if (folder/'control.jsonl').is_file():related.append(link(page,folder/'control.jsonl','控制磁反馈'))
        rate=f'{s["nominal_rate_hz"]:.2f}' if s.get('nominal_rate_hz') else '—'
        body+=f'| {link(page,root/r["detail_page"],r["id"],r["id"].lower())} · {r["date"]} | {CATEGORIES[r["category"]]} | {sensor} | {" · ".join(related) or "无派生表"} | {s.get("samples",0):,}（{s.get("invalid_rows",0)}） | {rate} | {s.get("raw_missing_rows") if s.get("raw_axes_available") else "未记录B"}／{s.get("delta_missing_rows") if s.get("delta_axes_available") else "未记录ΔB"} | {s.get("intervals_over_twice_median",0)} |\n'
    write(page,body)
    page=nav/'磁传感数据说明.md'
    write(page,'# 磁传感数据读取与分类\n\n'+link(page,root/'实验数据总导航.md','返回总导航')+'''

| 层级 | 文件／字段 | 解释 |
|---|---|---|
| A：最高优先级原始实测 | 每次运行sensor.csv：Bx_uT、By_uT、Bz_uT、sensor_t_us、seq、valid | 传感器收到的三轴绝对磁场，单位μT；时钟优先使用sensor_t_us，不用批量host_rx_ns间隔推频率。 |
| B：记录时的基线差值 | sensor.csv：dBx_uT、dBy_uT、dBz_uT、baseline_id；manifest.json：B0_uT | ΔB=B−B0。采集基线期间ΔB可能为空，原始B仍可能完整；不要把空值补成0。 |
| C：控制时的实测响应 | control.jsonl：a_raw_uT、a_control_uT | 原始响应与控制滤波后的响应；按本次定义核对，不能将滤波值当作原始三轴数据。 |
| D：目标与控制动作 | control.jsonl：a_ref_uT、a_error_uT、命令位姿、PI修正；strokeplan.npz | 磁目标／命令不是实测磁响应。非书写阶段目标或误差为null可以是正常设计。 |
| E：派生分析 | analysis/magnetic_timeseries.csv、magnetic_sampling_summary.json | 已有派生表包含模长及质量信息；若delta_origin为offline_first_baseline，是用冻结B0离线补基线，不是当时已可用的控制反馈。 |
| F：手采 | manual批次raw/*.csv、同名JSON | CSV直接记录未显示平滑的三轴ΔB，B0在JSON；不同时提供机器人XY或TCP。 |
| G：前馈表 | feedforward*.json、calibration.json | 磁响应与名义压深的模型／快照；数值不是这次实验的原始采样。 |

常用响应为sqrt(dBx²+dBy²)，以具体实验feature与filter为准；三轴模长sqrt(dBx²+dBy²+dBz²)不是同一特征。磁响应量不是力，没有测力标定时不转换成牛顿。

本次逐个扫描原始磁CSV：统计行数、无效标记、有限数值缺失、传感时钟中位间隔、超过两倍中位间隔的次数以及时间非递增。中位间隔可估采样频率；间隔检查覆盖全CSV，包括基线和进笔准备，不直接等同书写阶段丢样。诊断回放／抽取不重复计入机器人运行次数。

没有为旧实验批量生成新的磁响应表，没有插值、填补实测空洞或修改原始日志。部分历史记录尚无派生表，可从原始三轴重新分析；缺少baseline时不能凭空恢复原有控制ΔB。

数据分层时保留整次run_id、毛笔、日期批次、方向、名义Z、速度、姿态、B0、滤波和标定快照。划分训练与验证时按整次实验或批次处理，避免把相邻时间样本随机拆开造成泄漏。墨迹宽度／尾端形态还需要与本次运行对应的照片，路径或磁量本身不能提供视觉标签。
''')
    page=nav/'方案与最终版本.md';body='# 标准笔画、最终字与离线方案\n\n'+link(page,root/'实验数据总导航.md','返回总导航')+'\n\n方案文件不是新增实测记录。恢复完整控制点、磁目标与区域节奏使用editor_state.json；打开路径版本使用recipe.json。不同机器执行前仍需核对原配置，导航可迁移不代表硬件坐标自动适配。\n'
    for base in [root/'runs/brush2/plans/final',root/'runs/brush2/plans/standard']:
        if not base.exists():continue
        for folder in sorted(p for p in base.iterdir() if p.is_dir()):
            body+=f'\n## {folder.name}\n\n'+existing(page,folder,[("README.md","方案说明"),("方案标记.json","来源与最终／标准标记"),("editor_state.json","完整编辑存档"),("recipe.json","路径配方"),("strokeplan.npz","离线目标路径"),("workspace_recipe.json","完整多笔配方"),("preflight.json","离线预检")])+'\n'
    body+='\n其他各次交互导出、标定候选和路径版本均在'+link(page,nav/'全文件目录.md','全文件目录')+'逐项导航；只存在preflight或hardware_executed=false的方案不算本次新增实写。\n'
    write(page,body)
    summary=dict(generated_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),scope='locally_saved_project_records_not_proof_of_execution_host',
        hardware_runs=len(hardware),hardware_status_counts=dict(statuses),manual_recordings=len(manual),diagnostic_csvs=len(diagnostics),
        magnetic_csv_files=len(sensor_paths),hardware_sensor_rows=sensor_samples,manual_sensor_rows=sum(r['magnetic_stats']['samples'] for r in manual),
        existing_derived_magnetic_tables=sum(bool(r.get('derived_magnetic')) for r in records),file_count=len(files),bytes=sum(p.stat().st_size for p in files),
        calibration_copies=sum(map(len,calibrations.values())),distinct_calibration_contents=len(calibrations),raw_data_modified=False,interpolated_samples=0)
    summary.update(empty_magnetic_csvs=sum(not stats['samples'] for stats in statistics.values()),
        invalid_flagged_csvs=sum(stats['invalid_rows']>0 for stats in statistics.values()),
        raw_B_missing_csvs=sum((stats['raw_missing_rows'] or 0)>0 for stats in statistics.values()),
        source_files_changed_during_scan=sum(stats['source_changed_during_scan'] for stats in statistics.values()))
    main=root/'实验数据总导航.md'
    body=f'# 本机实验数据总导航\n\n更新：{summary["generated_at"][:19]}（Asia/Shanghai）。**所有新导航链接均为相对路径**。统计的是当前文件夹中保存的记录；旧迁移目录和旧主机路径不代表在本机重新执行，未凭路径推定采集主机。\n\n'
    body+=f'现存 **{len(hardware)} 次硬件运行记录**、**{len(manual)} 次手采录制**、**{len(diagnostics)} 份传感器诊断／导出CSV**；共导航 **{len(files):,} 个文件**（约 {summary["bytes"]/1024**3:.2f} GiB）。硬件原始磁CSV累计 **{sensor_samples:,} 行**；已有派生磁表 {summary["existing_derived_magnetic_tables"]} 份。这些是记录数／行数，不等于所有样本均有效。\n\n'
    body+='## 先找磁传感数据\n\n- **'+link(main,nav/'磁传感数据总表.md','全部磁传感数据总表：逐条直达原始CSV、派生表和质量报告')+'**。\n- **首选每次实验的sensor.csv**：原始三轴B、时间、有效标记与已记录ΔB。\n- 其次看control.jsonl的实测a_raw_uT／a_control_uT，与a_ref_uT目标分开。\n- B0和采样条件看manifest.json；处理后模长和缺帧报告看已有analysis磁数据文件。\n- '+link(main,nav/'磁传感数据说明.md','完整磁数据分层与空值解释')+' · '+link(main,nav/'前馈与标定表.md','前馈和标定映射全部位置')+' · '+link(main,nav/'异常与不完整记录.md','中止／故障／原始数据异常记录')+'。\n\n'
    body+=f'原始磁CSV初筛：{summary["empty_magnetic_csvs"]} 份为空记录、{summary["invalid_flagged_csvs"]} 份含无效标记、{summary["raw_B_missing_csvs"]} 份存在已记录B列的数值缺失；扫描期间变化的源文件 {summary["source_files_changed_during_scan"]} 份。具体行数与时轴检查见磁数据总表，不把基线阶段ΔB空白当作原始B丢失。\n\n'
    body+='## 按实验用途分类\n\n| 分类 | 记录数 | 主要用途 |\n|---|---|---|\n'
    purposes=['名义压深—磁响应、姿态依赖和前馈来源','方向／速度／Z与磁响应耦合','连续加载、扰动与接触进笔过程','目标跟踪、增益和修正限幅对照','横画、编辑路径及多笔书写','启动检查、基线失败及回放提取','人工写横的磁响应示范，无同步XY','保留并单独核对来源']
    for (key,title),description in zip(CATEGORIES.items(),purposes):body+=f'| {link(main,nav/"按类别"/f"{key}.md",title)} | {len(by_category[key])} | {description} |\n'
    body+='\n四方向阶梯中有“四类笔杆姿态但运动都沿+X”的历史组，不能与真正四个平移方向混为一类。已有标定复用评估见'+link(main,root/'runs/brush2/analysis/2026-10-26_实验汇总/标定数据复用评估.md','历史标定复用评估')+'。类别按实验定义归类，详细参数以每次resolved/setup为准。\n\n'
    body+='## 运行状态汇总\n\n| 状态 | 硬件记录数 |\n|---|---|\n'+'\n'.join(f'| {STATUS.get(k,k)} | {v} |' for k,v in sorted(statuses.items()))+'\n\n完成状态不自动证明墨迹达标或磁数据可直接训练；中止／失败运行仍可能保留有用的原始磁信号，本次均保留并标明状态。\n\n'
    body+='## 按日期逐次打开\n\n| 毛笔／日期 | 硬件 | 手采／诊断 | 原始磁采样行 |\n|---|---|---|---|\n'
    for (brush,day),items in sorted(by_day.items(),reverse=True):
        body+=f'| {link(main,nav/"按日期"/f"{brush}_{day}.md",brush+" · "+day)} | {sum(r["kind"]=="hardware" for r in items)} | {sum(r["kind"]!="hardware" for r in items)} | {sum((r.get("magnetic_stats") or {}).get("samples",0) for r in items):,} |\n'
    body+='\n## 方案、分析与全部文件\n\n- '+link(main,nav/'方案与最终版本.md','永字最终方案、横画与五个标准笔画')+'。\n- '+link(main,nav/'全文件目录.md','全部文件逐项导航（含离线方案、图像、分析、模板与本地草稿）')+'。\n- '+link(main,nav/'实验记录索引.json','机器可读实验索引：记录ID、相对路径、分类、采样检查')+'。\n\n'
    body+='## 拷贝到硬盘\n\n建议完整复制当前项目文件夹，再从本文件打开。只做数据备份时，至少一起复制`runs/`、`outputs/`、`docs/05-data-acquisition/results/legacy-acceptance/`、本文件及`实验数据导航/`，保持相互位置；可以省去`.git/`、`.venv/`和缓存。不能只复制本.md或只复制导航目录。\n\n新导航没有依赖/home前缀或file://地址；原实验内部JSON／旧报告中的历史绝对路径原样保留，本次不重写标定、硬件配置或原始数据。导航能迁移，不表示旧执行配置可在硬盘路径下直接驱动硬件。\n\n需要更新目录时，在项目根运行`python3 scripts/generate_experiment_navigation.py`。本次只新增导航和统计索引，没有重跑实验、插值补磁数据或生成伪造测量。\n'
    write(main,body)
    write(nav/'README.md','# 实验数据导航\n\n'+link(nav/'README.md',main,'打开总导航')+' · '+link(nav/'README.md',nav/'全文件目录.md','全文件目录')+' · '+link(nav/'README.md',nav/'磁传感数据说明.md','磁数据说明')+'\n')
    index_path=nav/'实验记录索引.json';index_path.write_text(json.dumps(dict(summary=summary,records=records),ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    # Check every generated Markdown destination on disk, including cross-page anchors.
    broken=[];absolute=[];links=0
    for page in generated:
        for destination in re.findall(r'\]\(([^\s)]+)\)',page.read_text()):
            links+=1;target,_,anchor=destination.partition('#')
            if target.startswith(('/','file:','http:','https:')):absolute.append((rel(page),destination));continue
            resolved=(page.parent/unquote(target)).resolve()
            if not resolved.exists():broken.append((rel(page),destination))
            elif anchor and resolved.suffix=='.md' and f'id="{anchor}"' not in resolved.read_text():broken.append((rel(page),destination))
    report=dict(summary=summary,markdown_pages=len(generated),checked_links=links,broken_links=broken,absolute_links=absolute,
        generated_files=[rel(p) for p in generated]+[rel(index_path)],warnings=warnings)
    (nav/'导航构建报告.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    if broken or absolute:raise RuntimeError(f'Navigation check failed: broken={len(broken)}, absolute={len(absolute)}')
    print(json.dumps(dict(summary=summary,markdown_pages=len(generated),checked_links=links,broken_links=len(broken),absolute_links=len(absolute)),ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);parser.add_argument('--workers',type=int,default=3)
    args=parser.parse_args();build(args.root,max(1,args.workers))
