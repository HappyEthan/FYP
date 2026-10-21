"""A refreshable, offline home over immutable template and character bundles."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import quote

from .bundle import load_fitted_geometry, read_json
from .schema import fixture_kind, validate_annotation, validate_template


DEFAULT_ROOT = Path(__file__).resolve().parents[3]/'outputs/stroke_templates'
MARKER = '<!-- brushbot-stroke-catalog:v1 -->'
NAMES = {'heng': '横', 'shu': '竖', 'dian': '点', 'hengzhegou': '横折钩',
         'hengpie': '横撇', 'pie': '撇', 'na': '捺', 'unknown': '待定笔画'}
TYPE_ORDER = ['heng', 'shu', 'pie', 'na', 'dian', 'ti', 'hengzhe', 'henggou',
              'shugou', 'wangou', 'xiegou', 'wogou', 'shuwan', 'shuwangou',
              'shuti', 'hengpie', 'piezhe', 'piedian', 'shuzhe', 'hengzhegou',
              'hengzheti', 'hengzhewan', 'hengzhewangou', 'shuzhepie',
              'shuzhezhegou', 'hengzhezhepie', 'hengpiewangou', 'hengzhezhezhegou']
VARIANT_ORDER = {'heng': ['long', 'short', 'standard'],
                 'shu': ['chuilu', 'xuanzhen', 'short', 'standard'],
                 'pie': ['slant', 'vertical', 'short_flat', 'short_slant', 'standard'],
                 'na': ['slant', 'flat', 'standard'],
                 'dian': ['right_dot', 'left_dot', 'vertical_dot', 'long_dot', 'standard']}


def _local_file(directory, name):
    relative = Path(name)
    if relative.is_absolute() or not relative.parts or any(p in ('.', '..') for p in relative.parts):
        raise ValueError('invalid artifact path')
    path = directory/relative
    if any((directory/Path(*relative.parts[:i])).is_symlink() for i in range(1, len(relative.parts)+1)):
        raise ValueError('symlinked artifact is not a local bundle file')
    if not path.resolve().is_relative_to(directory.resolve()) or not path.is_file():
        raise ValueError('artifact missing or outside bundle')
    return path


def _verify(directory, manifest):
    files = manifest.get('files')
    if manifest.get('schema_version') != 1 or not isinstance(files, dict) or not 1 <= len(files) <= 2048:
        raise ValueError('invalid bundle manifest')
    for name, expected in files.items():
        hasher = hashlib.sha256()
        with _local_file(directory, name).open('rb') as stream:
            for block in iter(lambda: stream.read(1024*1024), b''):
                hasher.update(block)
        if hasher.hexdigest() != expected:
            raise ValueError('artifact checksum mismatch: '+name)


def _href(root, path):
    return './'+quote(path.relative_to(root).as_posix(), safe='/')


def _entry(root, directory, manifest):
    role = manifest['role']
    common = dict(path=directory.relative_to(root).as_posix(),
                  modified=datetime.fromtimestamp((directory/'manifest.json').stat().st_mtime, timezone.utc).isoformat(),
                  modified_ns=(directory/'manifest.json').stat().st_mtime_ns)
    if role == 'stroke_template_bundle':
        model = validate_template(read_json(_local_file(directory, 'template.json')))
        if model['template_id'] != manifest.get('template_id') or not {'template.json', 'report.html'} <= manifest['files'].keys():
            raise ValueError('template/manifest binding mismatch')
        reference = next((r for r in model['references'] if r['reference_id']==model['prototype']['reference_id']), None)
        if reference is None:
            raise ValueError('representative template reference is missing')
        description = model.get('guide_trace', model.get('teaching', {}))
        return dict(common, kind='template', id=model['template_id'], type=model['type'],
            name=description.get('name',NAMES.get(model['type'], model['type'])),
            variant=model['variant'], style=model['style_id'],
            collection='teaching' if model['evidence']['level']=='teaching_rule_candidate' else 'other',
            reviewed=description.get('review_status')=='confirmed', guide_traced='guide_trace' in model,
            group=json.dumps([model['type'], model['variant'], model['style_id']]),
            evidence=model['evidence']['level'], reference_count=len(model['references']),
            reference_characters=sorted({r.get('character', '') for r in model['references']}),
            xy=reference['xy_px'], width_px=reference['width_px'], anchors=reference['anchors'], coordinate_role='representative_reference_original_orientation',
            href=_href(root, _local_file(directory, 'report.html')))
    annotation = validate_annotation(read_json(_local_file(directory, 'annotation.json')))
    if role == 'templated_character_xy_bundle':
        geometry = load_fitted_geometry(directory)
        strokes = [dict(id=s['id'], type=s['type'], xy=s['xy_px'] if s['status']=='candidate' else a['xy_px'],
                        candidate=s['status']=='candidate') for s, a in zip(geometry['strokes'], annotation['strokes'])]
        complete, reviewed = geometry['complete'], geometry['review_status']=='annotation_reviewed'
        candidate_count = sum(s['candidate'] for s in strokes)
        identity, kind = geometry['geometry_id'], 'geometry'
        report = 'review.html' if 'review.html' in manifest['files'] else 'report.html'
    else:
        required = {'annotation.json', 'source_image.bin', 'image.png', 'report.html'}
        if (set(manifest['files']) != required or annotation['annotation_id'] != manifest.get('annotation_id')
                or annotation['source_sha256'] != manifest['files']['source_image.bin']):
            raise ValueError('annotation/manifest binding mismatch')
        strokes = [dict(id=s['id'], type=s['type'], xy=s['xy_px'], candidate=False) for s in annotation['strokes']]
        complete, reviewed, candidate_count = False, all(s['review_status']=='confirmed' for s in annotation['strokes']), 0
        identity, kind, report = annotation['annotation_id'], 'annotation', 'report.html'
    return dict(common, kind=kind, id=identity, character=annotation['character'], group=annotation['character'],
        evidence=fixture_kind(annotation['provenance']) or 'image_geometry',
        composition=annotation['provenance'].get('source_kind')=='template_composition',
        stroke_writings=list(dict.fromkeys(s.get('display_name') or NAMES.get(s['type'],s['type'])
                                           for s in annotation['strokes'])),
        size=annotation['image_size_px'], strokes=strokes, complete=complete, reviewed=reviewed,
        candidate_count=candidate_count, image_href=_href(root, _local_file(directory, 'image.png')),
        href=_href(root, _local_file(directory, report)))


def _character_order(root):
    path = root/'catalog_settings.json'
    if not path.exists():
        return []
    settings = read_json(path)
    if (not isinstance(settings,dict) or settings.get('schema_version')!=1
            or settings.get('role')!='stroke_template_catalog_settings'):
        raise ValueError('unsupported catalog settings')
    order = settings.get('character_order',[])
    if (not isinstance(order,list) or len(order)>128
            or any(not isinstance(c,str) or len(c)!=1 for c in order)
            or len(set(order))!=len(order)):
        raise ValueError('character_order must contain unique single characters (at most 128)')
    return order


def collect_catalog(root):
    root = Path(root).resolve()
    character_order = _character_order(root)
    templates, characters, errors = [], [], []
    roles = {'stroke_template_bundle', 'templated_character_xy_bundle', 'stroke_annotation_bundle'}
    for path in sorted(root.rglob('manifest.json')):
        relative = path.relative_to(root)
        if any(p.startswith('.') for p in relative.parts):
            continue
        if any((root/Path(*relative.parts[:i])).is_symlink() for i in range(1, len(relative.parts)+1)):
            continue
        try:
            manifest = read_json(path)
            if not isinstance(manifest, dict) or manifest.get('role') not in roles:
                continue
            _verify(path.parent, manifest)
            entry = _entry(root, path.parent, manifest)
            (templates if entry['kind']=='template' else characters).append(entry)
        except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
            errors.append(dict(path=path.parent.relative_to(root).as_posix(), reason=str(exc)))
    def unique(entries):
        result, seen = [], {}
        for item in sorted(entries, key=lambda e: (-e['modified_ns'], e['path'])):
            key = (item['kind'], item['id'])
            if key in seen:
                seen[key]['copies'] += 1
                continue
            item.pop('modified_ns'); item['copies'] = 1
            seen[key] = item; result.append(item)
        return result
    templates = unique(templates)
    def stroke_order(item):
        kind, variant = item['type'], item['variant']
        variants = VARIANT_ORDER.get(kind, [])
        return (TYPE_ORDER.index(kind) if kind in TYPE_ORDER else len(TYPE_ORDER), kind,
                variants.index(variant) if variant in variants else len(variants), variant, item['style'])
    # Stable sort retains newest-first ordering inside each type/variant/style.
    templates.sort(key=stroke_order)
    characters = unique(characters)
    if character_order:
        ranks = {c:i for i,c in enumerate(character_order)}
        counts = {}
        for entry in characters:
            counts.setdefault(entry['character'],len(entry['strokes']))
        # Keep newest first within a character, including when showing all versions.
        characters.sort(key=lambda e:(ranks.get(e['character'],len(ranks)),
            0 if e['character'] in ranks else counts[e['character']],e['character']))
    return dict(templates=templates, characters=characters, character_order=character_order, errors=errors,
                generated_at=datetime.now(timezone.utc).isoformat(), root=str(root))


def write_catalog(root=DEFAULT_ROOT):
    root = Path(root).resolve()
    destination = root/'index.html'
    if (root/'manifest.json').exists():
        raise ValueError('catalog root is a published bundle; choose its parent library directory')
    if destination.is_symlink() or (destination.exists() and not destination.read_text(encoding='utf-8').startswith(MARKER)):
        raise ValueError('refusing to overwrite unmanaged index.html; choose a library directory')
    data = collect_catalog(root)
    serialized = json.dumps(data, ensure_ascii=False, allow_nan=False).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    root.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', prefix='.catalog-', suffix='.html', dir=root, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(MARKER+PAGE.replace('__DATA__', serialized))
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return dict(role='stroke_template_catalog', report_html=str(destination), catalog_html=str(destination),
                template_count=len(data['templates']), character_count=len(data['characters']), errors=data['errors'])


PAGE = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>笔画与字 · XY 资料库</title><style>
:root{font-family:system-ui,-apple-system,'Noto Sans CJK SC',sans-serif;color:#243347;background:#f4f6f9;color-scheme:light}*{box-sizing:border-box}body{max-width:1440px;margin:auto;padding:28px}h1{font-size:28px;margin:8px 0}h2{font-size:20px;margin:0}p{line-height:1.7}.muted{color:#63748b;font-size:14px}header{margin-bottom:24px}.toolbar{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:18px 0}button,input,select{font:inherit;color:inherit;border:1px solid #b9c7d8;border-radius:9px;padding:10px 14px;background:white}button{cursor:pointer}button.active{background:#245db9;color:white;border-color:#245db9}#search{flex:1;min-width:160px}label{font-size:14px}#catalogGrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:18px}.assetCard{background:white;border:1px solid #dce3ec;border-radius:14px;padding:18px;min-width:0}.preview{width:100%;height:225px;border-radius:9px;background:#f9fafc;margin:12px 0;border:1px solid #edf0f5}.badges{display:flex;gap:6px;flex-wrap:wrap;margin:9px 0}.badge{font-size:12px;background:#eaf0fa;color:#2a5796;padding:4px 8px;border-radius:20px}.warn{background:#fff2d8;color:#825810}.small{font-size:13px;line-height:1.7;overflow-wrap:anywhere}.openAsset{display:inline-block;color:#245db9;font-weight:600;margin-top:10px;text-decoration:none}.path{color:#758296;font-size:12px;overflow-wrap:anywhere;margin-top:12px}#empty{padding:40px;text-align:center;background:white;border-radius:12px}details{margin-top:24px;padding:15px;background:white;border:1px solid #dce3ec;border-radius:10px}code{overflow-wrap:anywhere}#errorList{color:#8e3f32}svg{display:block}@media(max-width:600px){body{padding:14px}h1{font-size:24px}#catalogGrid{grid-template-columns:1fr}.preview{height:240px}.toolbar{gap:8px}#search{order:2;flex-basis:100%}}
</style><header><div class="muted">BRUSHBOT · 离线 XY</div><h1>笔画与字的资料库</h1><p>从这里浏览笔画写法与整字路径。打开一项查看来源、阶段或继续修正。</p><div id="summary" class="muted"></div></header>
<nav class="toolbar" aria-label="资料分类"><button class="active" data-tab="templates">笔画库</button><button data-tab="characters">字库</button><select id="templateSource" aria-label="笔画来源"><option value="teaching">新库 · 教学图与规则</option><option value="all">全部来源（含旧库）</option></select><select id="characterSource" aria-label="整字来源" hidden><option value="composition">模板合成字</option><option value="all">全部资料（含旧测试）</option></select><input id="search" type="search" placeholder="搜索字、笔画类型、写法或目录" aria-label="搜索资料"><label><input id="allVersions" type="checkbox">全部版本</label></nav>
<p id="resultCount" class="muted" role="status"></p><div id="catalogGrid"></div><div id="empty" hidden></div>
<details><summary>目录与更新方式</summary><p class="small">使用本工具在资料库目录内生成新结果，首页会自动更新。手动复制、删除或直接调用 Python 核心生成后，运行下面的索引命令；刷新本页即可看到变化。建议笔画放在 strokes/，整字放在 characters/，已有批次也会递归收录。</p><code id="refreshCommand"></code><p class="small muted">首页收录本工具完整发布的数据包。仅放入一张图片，还需要先建立标注或生成路径。当前显示的复核状态来自已保存数据；下载到其他位置的修正 JSON 尚未入库。</p></details>
<details id="errors" hidden><summary id="errorSummary"></summary><ul id="errorList"></ul></details>
<script id="catalog-data" type="application/json">__DATA__</script><script>
'use strict';
const data=JSON.parse(document.getElementById('catalog-data').textContent),$=id=>document.getElementById(id),ns='http://www.w3.org/2000/svg';let tab='templates';
const palette=['#2868bd','#bc791c','#268568','#ae4f85','#6b5ab5','#237f91'];
const evidenceNames={teaching_rule_candidate:'教学规则重建候选',teaching_reconstruction:'教学规则重建候选',font_geometry_fixture:'字库几何原型',font_fixture:'字库几何原型',synthetic_geometry_fixture:'解析测试样本',synthetic_fixture:'解析测试样本',manual_geometry_reviewed:'人工已复核参考',unreviewed_geometry:'尚未复核参考',image_geometry:'图像几何候选'};
$('templateSource').value=data.templates.some(e=>e.collection==='teaching')?'teaching':'all';
$('characterSource').value=data.characters.some(e=>e.composition)?'composition':'all';
function node(tag,text,parent,cls){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;parent.appendChild(n);return n;}
function svgNode(tag,attrs,parent){const n=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);parent.appendChild(n);return n;}
function preview(entry,parent,commonSpan){const svg=svgNode('svg',{class:'preview',role:'img','aria-label':entry.kind==='template'?entry.name+'模板路径':entry.character+'整字路径'},parent);
 if(entry.kind==='template'){const path=entry.xy.map(p=>[(p[0]-entry.xy[0][0])/entry.width_px,(p[1]-entry.xy[0][1])/entry.width_px]),x=path.map(p=>p[0]),y=path.map(p=>-p[1]),low=[Math.min(...x),Math.min(...y)],high=[Math.max(...x),Math.max(...y)],span=Math.max(commonSpan,1)*1.32;svg.setAttribute('viewBox',[(low[0]+high[0]-span)/2,(low[1]+high[1]-span)/2,span,span].join(' '));for(let i=0;i<3;i++)svgNode('polyline',{points:path.slice(entry.anchors[i],entry.anchors[i+1]+1).map(p=>[p[0],-p[1]].join(',')).join(' '),fill:'none',stroke:['#c67b20','#2868bd','#268568'][i],'stroke-width':span/100,'stroke-linecap':'round','stroke-linejoin':'round'},svg);
 }else{const[W,H]=entry.size;svg.setAttribute('viewBox',[-.5,-.5,W,H].join(' '));if(!entry.composition)svgNode('image',{x:-.5,y:-.5,width:W,height:H,href:entry.image_href,preserveAspectRatio:'none',opacity:.7},svg);entry.strokes.forEach((s,i)=>{const polyline=svgNode('polyline',{points:s.xy.map(p=>[p[0],H-1-p[1]].join(',')).join(' '),fill:'none',stroke:palette[i%palette.length],'stroke-width':W/220,'stroke-linecap':'round','stroke-linejoin':'round','stroke-dasharray':s.candidate?'none':`${W/100} ${W/160}`},svg);svgNode('title',{},polyline).textContent=`第 ${i+1} 笔 · ${s.type}`;});}}
function draw(){const search=$('search').value.trim().toLowerCase(),seen=new Set(),pool=data[tab].filter(e=>{if(tab==='templates'&&$('templateSource').value==='teaching'&&e.collection!=='teaching')return false;if(tab==='characters'&&$('characterSource').value==='composition'&&!e.composition)return false;if(!$('allVersions').checked){if(seen.has(e.group))return false;seen.add(e.group);}return true;}),entries=pool.filter(e=>JSON.stringify([e.character,e.name,e.type,e.variant,e.style,e.path,e.reference_characters,e.stroke_writings]).toLowerCase().includes(search)),spans={};for(const e of pool){if(e.kind!=='template')continue;const x=e.xy.map(p=>p[0]),y=e.xy.map(p=>p[1]);spans[e.type]=Math.max(spans[e.type]||0,(Math.max(...x)-Math.min(...x))/e.width_px,(Math.max(...y)-Math.min(...y))/e.width_px);}$('templateSource').hidden=tab!=='templates';$('characterSource').hidden=tab!=='characters';$('catalogGrid').replaceChildren();document.querySelectorAll('[data-tab]').forEach(b=>{b.classList.toggle('active',b.dataset.tab===tab);b.setAttribute('aria-pressed',b.dataset.tab===tab)});
 for(const e of entries){const card=node('article',null,$('catalogGrid'),'assetCard');node('h2',e.kind==='template'?e.name:e.character,card);const badges=node('div',null,card,'badges');node('span',evidenceNames[e.evidence]||e.evidence,badges,'badge warn');if(e.kind!=='template')node('span',e.kind==='annotation'?'标注草稿':`${e.candidate_count}/${e.strokes.length} 笔有候选`,badges,'badge');if(e.composition)node('span','笔画模板合成',badges,'badge');if(e.kind!=='template'&&data.character_order.includes(e.character))node('span','练习 '+(data.character_order.indexOf(e.character)+1),badges,'badge');if(e.kind!=='template')node('span',e.reviewed?'输入已复核':'待人工复核',badges,'badge');preview(e,card,spans[e.type]);
 if(e.kind==='template'){node('div',`写法：${e.style} / ${e.variant}`,card,'small');node('div',e.collection==='teaching'?`${e.guide_traced?'原图引导线追踪':'规则重建候选（保留）'} · ${e.reviewed?'几何已检查':'待人工检查'}`:`${e.reference_count} 条参考${e.reference_characters.filter(Boolean).length?' · 来源字：'+e.reference_characters.filter(Boolean).join('、'):''}`,card,'small');node('div','原方向 · 同类按参考宽度等比例预览',card,'small muted');node('div','橙：起笔　蓝：行笔　绿：收笔',card,'small muted');}else{node('div','写法：'+e.stroke_writings.join('、'),card,'small');node('div',e.complete?'整字几何候选，可打开查看或局部修正。':e.kind==='annotation'?'分笔标注草稿，可打开继续复核。':'存在未支持笔画，可打开查看原因。',card,'small');}
 node('div',new Date(e.modified).toLocaleString('zh-CN')+(e.copies>1?` · ${e.copies} 个相同副本`:''),card,'small muted');const link=node('a',e.kind==='template'?'查看模板与来源 →':e.kind==='annotation'?'查看／编辑标注 →':'查看／修正整字 →',card,'openAsset');link.href=e.href;node('div',e.path,card,'path');}
 $('resultCount').textContent=`${tab==='templates'?'笔画库':'字库'} · 显示 ${entries.length} 项${$('allVersions').checked?'（去重后的全部版本）':'（各类最新版本）'}${tab==='templates'?' · 常用基础笔画优先':$('characterSource').value==='composition'?' · 覆盖 '+new Set(entries.flatMap(e=>e.strokes.map(s=>s.type))).size+' 类笔画':''}${tab==='templates'&&$('templateSource').value==='teaching'&&!$('allVersions').checked?' · 引导线 '+pool.filter(e=>e.guide_traced).length+' 条／保留规则候选 '+pool.filter(e=>!e.guide_traced).length+' 条':''}`;$('empty').hidden=entries.length>0;$('empty').textContent=search?'没有匹配的资料。可清空搜索，或勾选“全部版本”查找历史结果。':`当前还没有${tab==='templates'?'笔画模板':'整字结果'}。通过生成工具保存到此资料库后即可浏览。`;}
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{tab=b.dataset.tab;draw();});$('search').oninput=draw;$('allVersions').onchange=draw;$('templateSource').onchange=draw;$('characterSource').onchange=draw;
$('summary').textContent=`已收录 ${data.templates.length} 个笔画模板版本、${data.characters.length} 个整字／标注版本 · 索引更新 ${new Date(data.generated_at).toLocaleString('zh-CN')}`;
$('refreshCommand').textContent='PYTHONPATH=src:. python scripts/stroke_templates.py catalog --root '+"'"+data.root.replaceAll("'", "'\"'\"'")+"'";
if(data.errors.length){$('errors').hidden=false;$('errorSummary').textContent=`${data.errors.length} 个数据包未收录：文件不完整或校验失败`;for(const error of data.errors)node('li',error.path+'：'+error.reason,$('errorList'),'small');}
draw();
</script></html>'''
