"""Offline construction of tutorial-guided, explicitly provisional templates."""
from __future__ import annotations

import copy
import hashlib
import io
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
from PIL import Image, ImageDraw

from .bundle import publish, write_json
from .geometry import build_template
from .schema import identifier, identity, number, points, source_hash, validate_annotation, validate_template


DEFAULT_SOURCE_DIR = Path(__file__).resolve().parents[3]/'reference/stroke_teaching_v1'
WIDTH_DEFINITION = 'authored_relative_width_intent_not_measured_ink_or_force'
PHASES = ('entry','body','exit')


def _url(value):
    if not isinstance(value,str) or urlparse(value).scheme not in ('http','https') or not urlparse(value).netloc:
        raise ValueError('source URL must be http or https')


def generate_stroke(recipe, *, body_scales=None):
    """Change body spans along their chords; preserve local ends and turn shapes."""
    recipe = copy.deepcopy(recipe)
    for key in ('id','type','variant'):
        identifier(recipe.get(key), key)
    if not isinstance(recipe.get('name'),str) or not recipe['name'].strip():
        raise ValueError('recipe needs a name')
    parts, events = recipe.get('parts'), recipe.get('events')
    if not isinstance(parts,list) or not 3 <= len(parts) <= 20 or not isinstance(events,list) or not 4 <= len(events) <= 64:
        raise ValueError('recipe needs 3..20 parts and 4..64 events')
    ids, phases = set(), []
    for part in parts:
        pid = identifier(part.get('id'),'part id')
        if pid in ids or part.get('phase') not in PHASES:
            raise ValueError('parts need unique ids and valid phases')
        ids.add(pid); phases.append(PHASES.index(part['phase']))
        controls = points(part.get('controls'))
        if len(controls)!=4 or np.linalg.norm(controls[0])>1e-10 or np.linalg.norm(controls[-1])<=1e-8:
            raise ValueError('part needs four local Bezier controls, starting at zero, with positive span')
        part['controls'] = controls
    if set(phases)!={0,1,2} or phases!=sorted(phases):
        raise ValueError('parts must follow entry, body, exit phases')
    if recipe.get('review_status','unreviewed') not in ('unreviewed','confirmed'):
        raise ValueError('invalid recipe review status')
    adjustable = {p['id'] for p in parts if p.get('adjustable_span') is True and p['phase']=='body'}
    scales = dict(recipe.get('parameters',{}).get('body_scales',{}))
    scales.update(body_scales or {})
    if set(scales)-adjustable:
        raise ValueError('span scale can only name an adjustable body part')
    scales = {key:number(value,'span scale',positive=True) for key,value in scales.items()}
    if any(not .5 <= value <= 1.6 for value in scales.values()):
        raise ValueError('span scale outside engineering preview range [.5, 1.6]')
    names=set()
    for event in events:
        name=identifier(event.get('name'),'event name')
        if name in names or event.get('part') not in ids or not 0 <= number(event.get('t'),'event t') <= 1:
            raise ValueError('events need unique names and valid part positions')
        if (not isinstance(event.get('label'),str) or event.get('action') not in
            ('touch_hint','travel','press_hint','lift_hint','finish_hint') or
            event.get('speed_hint') not in ('unspecified','slower','faster')):
            raise ValueError('invalid qualitative event hint')
        names.add(name)
    xy, phase_id, ranges, event_indices = [], [], [], {}
    origin=np.zeros(2)
    for part in parts:
        controls=part['controls'].copy()
        chord=controls[-1]/np.linalg.norm(controls[-1])
        controls += (scales.get(part['id'],1.)-1.)*(controls@chord)[:,None]*chord
        local_events=[e for e in events if e['part']==part['id']]
        at=np.unique(np.r_[np.linspace(0,1,25),[e['t'] for e in local_events]])
        t=at[:,None]
        curve=(1-t)**3*controls[0]+3*(1-t)**2*t*controls[1]+3*(1-t)*t*t*controls[2]+t**3*controls[3]+origin
        first=max(0,len(xy)-1)
        xy.extend(curve.tolist() if not xy else curve[1:].tolist())
        if not phase_id:
            phase_id.extend([part['phase']]*len(curve))
        else:
            phase_id[-1]=part['phase'];phase_id.extend([part['phase']]*(len(curve)-1))
        ranges.append(dict(id=part['id'],phase=part['phase'],first=first,last=len(xy)-1,adjustable_span=part.get('adjustable_span') is True))
        for event in local_events:
            event_indices[event['name']]=first+int(np.flatnonzero(at==event['t'])[0])
        origin=curve[-1]
    xy=points(xy)
    arc=np.r_[0.,np.cumsum(np.linalg.norm(np.diff(xy,axis=0),axis=1))]
    anchors=[0,next(r['first'] for r in ranges if r['phase']=='body'),
             next(r['first'] for r in ranges if r['phase']=='exit'),len(xy)-1]
    resolved=[]
    for event in sorted(events,key=lambda e:event_indices[e['name']]):
        index=event_indices[event['name']]
        phase=0 if index<anchors[1] else 1 if index<anchors[2] else 2
        first,last=anchors[phase:phase+2]
        resolved.append(dict(event,index=index,xy=xy[index].tolist(),s=float(arc[index]/arc[-1]),
            phase_id=PHASES[phase],phase_u=float((arc[index]-arc[first])/(arc[last]-arc[first]))))
    knots=recipe.get('width_knots')
    if not isinstance(knots,list) or not 2 <= len(knots) <= 64:
        raise ValueError('relative width needs 2..64 knots')
    indices, widths=[],[]
    for knot in knots:
        if knot.get('event') not in event_indices:
            raise ValueError('width knot names an unknown event')
        indices.append(event_indices[knot['event']]);widths.append(number(knot.get('ratio'),'relative width'))
    if indices[0]!=0 or indices[-1]!=len(xy)-1 or any(a>=b for a,b in zip(indices,indices[1:])) or min(widths)<0 or max(widths)>4 or max(widths)<=0:
        raise ValueError('width knots must span the ordered path with ratios in [0,4]')
    features=[]
    for name in recipe.get('landmarks',[]):
        if name not in event_indices:
            raise ValueError('landmark event is absent')
        features.append(dict(name=name,index=event_indices[name]))
    from .schema import landmarks
    features=landmarks(features,anchors)
    return dict(xy=xy.tolist(),anchors=anchors,landmarks=features,events=resolved,parts=ranges,
        relative_width=np.interp(arc,arc[indices],widths).tolist(),width_definition=WIDTH_DEFINITION,
        phase_id=phase_id,s=(arc/arc[-1]).tolist(),parameters=dict(body_scales=scales))


def ribbon(xy,width):
    xy=np.asarray(xy,float);width=np.asarray(width,float)
    tangent=np.gradient(xy,axis=0);norm=np.linalg.norm(tangent,axis=1)
    if np.any(norm<=1e-10):
        tangent=np.vstack([np.diff(xy,axis=0),xy[-1]-xy[-2]]);norm=np.linalg.norm(tangent,axis=1)
    normal=np.column_stack([-tangent[:,1],tangent[:,0]])/norm[:,None]
    return np.r_[xy+normal*width[:,None]/2,(xy-normal*width[:,None]/2)[::-1]]


def _render_reference(stroke):
    xy=np.asarray(stroke['xy']);width=np.asarray(stroke['relative_width'])
    outline=ribbon(xy,width);scale=18.
    low=outline.min(axis=0)-1.5;high=outline.max(axis=0)+1.5
    size=np.maximum(np.ceil((high-low)*scale+1),100).astype(int)
    if int(size[0])*int(size[1])>40_000_000:
        raise ValueError('reference render size exceeds 40 million pixels; check recipe coordinate units')
    offset=(size-1)/2-(high+low)*scale/2
    image=Image.new('RGB',tuple(size),'white')
    draw=ImageDraw.Draw(image)
    polygon=outline*scale+offset;polygon[:,1]=size[1]-1-polygon[:,1]
    draw.polygon([tuple(p) for p in polygon],fill='#444b55')
    stream=io.BytesIO();image.save(stream,format='PNG')
    return stream.getvalue(),(xy*scale+offset).tolist(),size.tolist(),scale


def generate_library(config, source_dir, output_dir):
    """Preflight all recipes/assets, then publish a new immutable library batch."""
    if (not isinstance(config,dict) or config.get('schema_version')!=1 or config.get('role')!='teaching_stroke_recipes'
            or not isinstance(config.get('strokes'),list) or not 1 <= len(config['strokes']) <= 128):
        raise ValueError('invalid teaching recipe collection')
    identifier(config.get('style_id'),'style id')
    if not isinstance(config.get('sources'),list) or not config['sources']:
        raise ValueError('teaching collection needs disclosed sources')
    source_ids=set()
    for source in config['sources']:
        sid=identifier(source.get('id'),'source id');_url(source.get('url'));source_ids.add(sid)
    pending=[];seen=set()
    for recipe in config['strokes']:
        generated=generate_stroke(recipe)
        if recipe['id'] in seen:
            raise ValueError('duplicate recipe id')
        seen.add(recipe['id'])
        illustration=recipe.get('illustration',{});filename=illustration.get('filename')
        if (not isinstance(filename,str) or Path(filename).name!=filename or filename in ('.','..')
                or illustration.get('source_id') not in source_ids):
            raise ValueError('invalid source illustration filename or id')
        _url(illustration.get('url'));source_hash(illustration.get('sha256'))
        source=Path(source_dir)/filename
        if source.is_symlink():
            raise ValueError('source illustration must be a regular file')
        raw=source.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=illustration['sha256']:
            raise ValueError('source illustration checksum mismatch: '+filename)
        with Image.open(io.BytesIO(raw)) as image:
            image.verify()
        pending.append((copy.deepcopy(recipe),generated,raw))
    def write(stage):
        entries=[]
        write_json(stage/'recipes.json',config)
        for recipe,generated,source in pending:
            result=_publish_template(config,recipe,generated,source,stage/'templates'/recipe['id'])
            entries.append(dict(id=recipe['id'],name=recipe['name'],type=recipe['type'],variant=recipe['variant'],
                category=recipe.get('category'),template_id=result['template_id'],href='templates/'+recipe['id']+'/report.html'))
        from .teaching_report import write_library_report
        write_library_report(entries,stage/'index.html')
        return dict(template_count=len(entries),basic_type_count=len({e['type'] for e in entries}),
                    style_id=config['style_id'],evidence='teaching_rule_candidate',
                    physical_validation=False,templates=entries)
    result=publish(output_dir,'teaching_stroke_library',write)
    result['report_html']=str(Path(result['output_dir'])/'index.html')
    return result


def _publish_template(config,recipe,generated,source_raw,output):
    image_raw,xy,size,scale=_render_reference(generated)
    provenance=dict(source_kind='teaching_rule_reconstruction',image_kind='teaching_reconstruction',
        physical_validation=False,coordinate_source='manually_authored_rule_based_curves',sources=config['sources'])
    stroke=dict(id='s01',type=recipe['type'],variant=recipe['variant'],xy_px=xy,anchors=generated['anchors'],
        landmarks=generated['landmarks'],width_hint_px=scale,review_status=recipe.get('review_status','unreviewed'),
        notes='教学规则重建候选；宽度为人工相对意图，不是实测。')
    annotation=validate_annotation(dict(schema_version=1,role='stroke_annotation',character='·',
        source_sha256=hashlib.sha256(image_raw).hexdigest(),image_size_px=size,provenance=provenance,strokes=[stroke]))
    reference=dict(annotation_id=annotation['annotation_id'],source_sha256=annotation['source_sha256'],
        stroke_id='s01',type=recipe['type'],variant=recipe['variant'],xy_px=xy,anchors=stroke['anchors'],
        landmarks=stroke['landmarks'],width_px=scale,width_source='authored_nominal_width',
        review_status=stroke['review_status'],source_kind='teaching_rule_reconstruction',
        image_kind='teaching_reconstruction',annotation_provenance=provenance)
    reference['reference_id']=identity(reference,'reference_id')
    model=build_template([reference],stroke_type=recipe['type'],variant=recipe['variant'],
                         style_id=config['style_id'],allow_unreviewed=True)
    events=[dict(e,xy=model['prototype']['xy'][e['index']]) for e in generated['events']]
    model['teaching']=dict(schema_version=1,name=recipe['name'],review_status=stroke['review_status'],
        coordinate_source='manually_authored_rule_based_curves',numeric_parameter_basis=recipe['numeric_parameter_basis'],
        recipe=recipe,sources=config['sources'],relative_width=generated['relative_width'],events=events,
        width_definition=WIDTH_DEFINITION,source_illustration_sha256=recipe['illustration']['sha256'])
    model['template_id']=identity(model,'template_id');model=validate_template(model)
    variants=[dict(id='default',label='默认候选',stroke=generated,recipe=recipe)]
    labels={'horizontal':'横段','vertical':'竖段','sweep':'主体弧段','dot_body':'点主体'}
    for part in recipe['parts']:
        if not part.get('adjustable_span'):
            continue
        for factor,description in ((.8,'短 20%'),(1.2,'长 20%')):
            parameters=copy.deepcopy(generated['parameters']['body_scales'])
            span=parameters.get(part['id'],1.)*factor
            if not .5 <= span <= 1.6:
                continue
            parameters[part['id']]=span
            alternative=copy.deepcopy(recipe);alternative['parameters']=dict(body_scales=parameters)
            alternative['review_status']='unreviewed'
            name=part.get('label') or labels.get(part['id'])
            if name is None:
                stem,_,suffix=part['id'].partition('_')
                name={'horizontal':'横段','vertical':'竖段','sweep':'弧段'}.get(stem,stem)+((' '+suffix) if suffix else '')
            variants.append(dict(id=part['id']+'_'+str(factor),label=name+description,
                stroke=generate_stroke(alternative),recipe=alternative))
    def write(stage):
        write_json(stage/'template.json',model);write_json(stage/'recipe.json',recipe)
        write_json(stage/'reference_000_annotation.json',annotation)
        (stage/'reference_000_source.bin').write_bytes(image_raw)
        (stage/'source_illustration.bin').write_bytes(source_raw)
        from .teaching_report import write_teaching_report
        write_teaching_report(model,config,variants,source_raw,stage/'report.html')
        return dict(template_id=model['template_id'],evidence=model['evidence'])
    return publish(output,'stroke_template_bundle',write)
