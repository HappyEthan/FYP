"""Geometry and export model for the brush XY editor (no hardware access)."""
import copy
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import uuid
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT/'runs/brush2/plans/heng_flat_tail_v16'
CONTEXT = ROOT/'runs/brush2/plans/11_中字底横延长30mm_实测第9次'

def arc(points):
    return np.r_[0., np.cumsum(np.linalg.norm(np.diff(points,axis=0),axis=1))]

def simplify_indices(points,tolerance=.20):
    """RDP handles only; original dense geometry is retained between handles."""
    def recurse(a,b):
        if b<=a+1:return [a,b]
        d=points[b]-points[a];den=float(d@d)
        q=points[a+1:b]-points[a]
        u=np.clip(q@d/den,0,1) if den>1e-15 else np.zeros(len(q))
        dist=np.linalg.norm(q-u[:,None]*d,axis=1)
        k=int(np.argmax(dist));i=a+1+k
        if dist[k]<=tolerance:return [a,b]
        return recurse(a,i)[:-1]+recurse(i,b)
    return np.array(recurse(0,len(points)-1),int)

class PathModel:
    def __init__(self,folder=DEFAULT):
        self.folder=Path(folder).resolve()
        self.base=json.loads((self.folder/'recipe.json').read_text())
        if self.base['path']['kind']!='rounded_polyline':
            raise ValueError('目前仅支持已有的 rounded_polyline 路径')
        if float(self.base['path'].get('corner_radius_mm',0))!=0:
            raise ValueError('当前编辑器要求 corner_radius_mm=0，以便预览与导出一致')
        self.original=np.array(self.base['path']['points_mm'],float)
        self.indices=simplify_indices(self.original)
        self.nodes=self.original[self.indices].copy()
        self.node_enabled=np.ones(len(self.nodes),dtype=bool)
        self.magnetic_values=np.array(self.base['magnetic_target']['knots_s_uT'],float)[:,1].copy()
        self.lift_mm=np.zeros(len(self.nodes))
        self.segment_magnetic=np.array([None]*(len(self.nodes)-1),dtype=object)
        self.endpoint_speed_mode=False
        self.node_speeds=np.full(len(self.nodes),None,dtype=object)
        self.segment_speeds=np.full(len(self.nodes)-1,None,dtype=object)
        self.speed_positions=np.full(len(self.nodes)-1,.5)
        self.node_angles=np.full((len(self.nodes),2),None,dtype=object)
        self.allow_low_response=False
        self.feedforward_override=None
        self.settings_override=None
        self.entry_profile_override=None
        self.stroke_id='stroke-1'
        self.stroke_name='笔画1'
        self.stroke_order=[self.stroke_id]
        self.other_strokes=[]
        self.pending_point=None
        self.pending_stroke_position='end'
        self.rhythm_regions=[]
        self.validate()

    def validate(self):
        if not np.isfinite(self.nodes).all():raise ValueError('节点坐标必须是有限数值')
        if np.any(np.linalg.norm(np.diff(self.nodes,axis=0),axis=1)<.02):
            raise ValueError('相邻节点至少相隔0.02 mm')
        self.test_node_range()

    def test_node_range(self):
        enabled=getattr(self,'node_enabled',np.ones(len(self.nodes),dtype=bool))
        if np.shape(enabled)!=(len(self.nodes),):raise ValueError('测试节点状态数量不匹配')
        active=np.flatnonzero(enabled)
        if len(active)<2:raise ValueError('分段测试至少保留两个相邻节点')
        if np.any(np.diff(active)!=1):raise ValueError('一次只能测试连续区间；不能隐藏中间节点后跨段直连。请使用“仅测试框选范围”。')
        return int(active[0]),int(active[-1])

    def set_test_range(self,first,last):
        if not 0<=first<last<len(self.nodes):raise ValueError('测试起点必须小于终点，至少保留一段')
        self.node_enabled=np.zeros(len(self.nodes),dtype=bool)
        self.node_enabled[first:last+1]=True

    def hide_nodes(self,indices):
        previous=self.node_enabled.copy()
        try:
            self.node_enabled[list(indices)]=False
            self.test_node_range()
        except Exception:
            self.node_enabled=previous
            raise

    def test_points(self):
        first,last=self.test_node_range()
        return self.points()[self.indices[first]:self.indices[last]+1]

    def points(self):
        self.validate();parts=[]
        for k,(a,b) in enumerate(zip(self.indices[:-1],self.indices[1:])):
            old=self.original[b]-self.original[a];new=self.nodes[k+1]-self.nodes[k]
            den=float(old@old)
            if den<1e-12:raise ValueError('原路径中有重合的控制端点')
            c=float(old@new/den);s=float((old[0]*new[1]-old[1]*new[0])/den)
            transform=np.array([[c,-s],[s,c]])
            segment=(self.original[a:b+1]-self.original[a])@transform.T+self.nodes[k]
            parts.append(segment if k==0 else segment[1:])
        return np.vstack(parts)

    def _bake_geometry(self, points):
        """Rebase dense geometry without baking explicit magnetic overrides."""
        before=arc(self.original);after=arc(points)
        base=copy.deepcopy(self.base)
        for section,key in [('magnetic_target','knots_s_uT'),('timing','speed_knots_s_mm_s'),('orientation','heading_knots_s_deg'),('orientation','node_angles_s_deg')]:
            if key in base[section]:
                base[section][key]=[[float(np.interp(row[0]*before[-1],before,after)/after[-1]),*row[1:]]
                    for row in base[section][key]]
        base['magnetic_target']['knots_s_uT']=[[s,float(v)] for (s,_),v in
            zip(base['magnetic_target']['knots_s_uT'],self.magnetic_values)]
        base['path']['points_mm']=points.tolist()
        self.base=base;self.original=points.copy()
        self.nodes=self.original[self.indices].copy()

    def add_point(self, segment, target_xy=None):
        """Split at half arc length; retain curve and duplicate segment target."""
        if not 0<=segment<len(self.nodes)-1:raise ValueError('请先选择要添加点的段')
        p=self.points();a,b=self.indices[segment:segment+2]
        distances=arc(p[a:b+1]);half=distances[-1]/2
        xy=np.array([np.interp(half,distances,p[a:b+1,j]) for j in range(2)])
        position=xy if target_xy is None else np.asarray(target_xy,float)
        if min(np.linalg.norm(position-p[a]),np.linalg.norm(position-p[b]))<.02:
            raise ValueError('该段太短或折返，无法添加相隔0.02 mm的中点')
        midpoint=[None,None]
        if any(v is not None for v in self.node_angles[segment:segment+2].flat):
            from scripts.generate_strokeplan_from_json import build_plan
            from brushbot.experiments.strokeplan_character import orientation_heading
            st=build_plan(self.recipe()).strokes[0];progress=(arc(p)[a]+half)/arc(p)[-1]
            heading=np.unwrap([orientation_heading(rpy) for rpy in st.orientation])
            incl=np.rad2deg(np.arccos(np.clip(np.cos(st.orientation[:,0])*np.cos(st.orientation[:,1]),-1,1)))
            midpoint=[float(np.interp(progress,st.s,incl)),float(np.rad2deg(np.interp(progress,st.s,heading)))]
        speed_active=any(value is not None for value in [*self.node_speeds[segment:segment+2],self.segment_speeds[segment]])
        speed_samples=[None,None,None]
        if speed_active:
            knots=np.array(self.recipe()['timing']['speed_knots_s_mm_s'],float)
            distances_all=arc(p)
            sample_q=(distances_all[a]+distances[-1]*np.array([.25,.5,.75]))/distances_all[-1]
            speed_samples=np.interp(sample_q,knots[:,0],knots[:,1]).tolist()
        self._bake_geometry(p)
        relative=int(np.searchsorted(distances,half))
        index=a+relative
        if abs(distances[relative]-half)>1e-10:
            self.original=np.insert(self.original,index,xy,axis=0)
            self.indices[self.indices>=index]+=1
        self.indices=np.insert(self.indices,segment+1,index)
        self.base['path']['points_mm']=self.original.tolist()
        self.nodes=self.original[self.indices].copy()
        # Same quintic height interpolation as execution; midpoint weight is 0.5.
        self.node_enabled=np.insert(self.node_enabled,segment+1,bool(self.node_enabled[segment] and self.node_enabled[segment+1]))
        self.node_speeds=np.insert(self.node_speeds,segment+1,speed_samples[1])
        self.segment_speeds=np.insert(self.segment_speeds,segment+1,speed_samples[2])
        self.segment_speeds[segment]=None if self.endpoint_speed_mode else speed_samples[0]
        if self.endpoint_speed_mode:self.segment_speeds[segment+1]=None
        self.speed_positions=np.insert(self.speed_positions,segment+1,.5);self.speed_positions[segment]=.5
        self.node_angles=np.insert(self.node_angles,segment+1,midpoint,axis=0)
        self.lift_mm=np.insert(self.lift_mm,segment+1,(self.lift_mm[segment]+self.lift_mm[segment+1])/2)
        self.segment_magnetic=np.insert(self.segment_magnetic,segment+1,self.segment_magnetic[segment])
        self.nodes[segment+1]=position
        self.validate()
        return segment+1

    def insert_point(self, node, xy):
        """Insert at any path order, including before the start/after the end."""
        if not 0<=node<=len(self.nodes):raise ValueError('新点编号必须在0和当前点数之间')
        xy=np.asarray(xy,float)
        if xy.shape!=(2,) or not np.isfinite(xy).all():raise ValueError('新点X/Y必须是有限数值')
        neighbors=self.nodes[max(0,node-1):min(node+1,len(self.nodes))]
        if np.any(np.linalg.norm(neighbors-xy,axis=1)<.02):raise ValueError('新点与相邻节点至少相隔0.02 mm')
        candidate=copy.deepcopy(self)
        if 0<node<len(self.nodes):
            candidate.add_point(node-1,target_xy=xy)
        else:
            candidate._extend_endpoint(node,xy)
        candidate.validate()
        self.__dict__=candidate.__dict__
        return node

    def _extend_endpoint(self,node,xy):
        prepend=node==0;p=self.points();length=arc(p)[-1]
        distance=float(np.linalg.norm(xy-(p[0] if prepend else p[-1])))
        self._resolve_endpoint_angles()
        self._bake_geometry(p)
        for section,key in [('magnetic_target','knots_s_uT'),('timing','speed_knots_s_mm_s'),('orientation','heading_knots_s_deg'),('orientation','node_angles_s_deg')]:
            if key not in self.base[section]:continue
            rows=self.base[section][key]
            shifted=[[(s*length+(distance if prepend else 0))/(length+distance),*values] for s,*values in rows]
            extension=[0.,*rows[0][1:]] if prepend else [1.,*rows[-1][1:]]
            self.base[section][key]=[extension,*shifted] if prepend else [*shifted,extension]
        if prepend:
            self.original=np.vstack([xy,p]);self.indices=np.r_[0,self.indices+1]
        else:
            self.original=np.vstack([p,xy]);self.indices=np.r_[self.indices,len(p)]
        self.base['path']['points_mm']=self.original.tolist()
        self.magnetic_values=np.array(self.base['magnetic_target']['knots_s_uT'],float)[:,1]
        edge=0 if prepend else -1;segment=0 if prepend else len(self.segment_magnetic)
        self.node_enabled=np.insert(self.node_enabled,node,self.node_enabled[edge])
        self.node_speeds=np.insert(self.node_speeds,node,self.node_speeds[edge])
        self.node_angles=np.insert(self.node_angles,node,self.node_angles[edge],axis=0)
        self.lift_mm=np.insert(self.lift_mm,node,self.lift_mm[edge])
        self.segment_magnetic=np.insert(self.segment_magnetic,segment,self.segment_magnetic[edge])
        self.segment_speeds=np.insert(self.segment_speeds,segment,None)
        self.speed_positions=np.insert(self.speed_positions,segment,.5)
        self.nodes=self.original[self.indices].copy()

    def _resolve_endpoint_angles(self):
        # Legacy heading profiles start at a nonzero progress with a null value;
        # they cannot be extended/clipped as generic knots starting at zero.
        # Preserve the old headings at retained handles as explicit node angles.
        if any(key in self.base['orientation'] for key in ('heading_knots_s_deg','node_angles_s_deg')):
            displayed=self.displayed_node_angles()
            for row in range(len(self.nodes)):
                for column in range(2):
                    if self.node_angles[row,column] is None:self.node_angles[row,column]=float(displayed[row,column])
            self.base=copy.deepcopy(self.base)
            self.base['orientation'].pop('heading_knots_s_deg',None)
            self.base['orientation'].pop('node_angles_s_deg',None)

    def _trim_endpoint(self,node):
        """Remove the adjacent entire segment, clipping source profiles to it."""
        p=self.points();self._resolve_endpoint_angles();self._bake_geometry(p)
        start,end=(self.indices[1],len(p)-1) if node==0 else (0,self.indices[-2])
        distances=arc(p);lo,hi=distances[[start,end]]/distances[-1]
        for section,key in [('magnetic_target','knots_s_uT'),('timing','speed_knots_s_mm_s'),('orientation','heading_knots_s_deg'),('orientation','node_angles_s_deg')]:
            if key not in self.base[section]:continue
            rows=self.base[section][key];positions=np.array([row[0] for row in rows])
            q=np.unique(np.r_[lo,positions[(positions>lo)&(positions<hi)],hi])
            if section=='magnetic_target':
                # Sample quintic source curves before clipping; no endpoint spike.
                q=np.unique(np.r_[q,np.linspace(lo,hi,1001)])
                knots=np.array(rows,float)
                if self.base[section]['interpolation']=='quintic':
                    from scripts.generate_calligraphy_trial import contact_profile
                    values=contact_profile(q,knots)
                else:values=np.interp(q,positions,knots[:,1])
                clipped=np.column_stack([(q-lo)/(hi-lo),values]).tolist()
                self.base[section]['interpolation']='linear'
            else:
                def value_at(s,column):
                    exact=np.flatnonzero(np.isclose(positions,s,rtol=0,atol=1e-12))
                    if len(exact):return rows[int(exact[0])][column]
                    k=int(np.searchsorted(positions,s))
                    if k==0:return rows[0][column]
                    if k==len(rows):return rows[-1][column]
                    left,right=rows[k-1][column],rows[k][column]
                    if left is None or right is None:return None
                    u=(s-positions[k-1])/(positions[k]-positions[k-1])
                    if section=='orientation':u=6*u**5-15*u**4+10*u**3
                    return float((1-u)*left+u*right)
                clipped=[[(s-lo)/(hi-lo),*[value_at(s,c) for c in range(1,len(rows[0]))]] for s in q]
            self.base[section][key]=clipped
        self.original=p[start:end+1].copy();self.indices=np.delete(self.indices,node)-start
        self.base['path']['points_mm']=self.original.tolist()
        self.magnetic_values=np.array(self.base['magnetic_target']['knots_s_uT'],float)[:,1]
        self.nodes=self.original[self.indices].copy()
        segment=0 if node==0 else len(self.segment_magnetic)-1
        for name in ['node_enabled','node_speeds','lift_mm']:
            setattr(self,name,np.delete(getattr(self,name),node))
        self.node_angles=np.delete(self.node_angles,node,axis=0)
        for name in ['segment_magnetic','segment_speeds','speed_positions']:
            setattr(self,name,np.delete(getattr(self,name),segment))

    def delete_point(self, node):
        """Delete any handle; endpoints remove only their adjacent segment."""
        if not 0<=node<len(self.nodes):raise ValueError('请选择有效节点删除')
        if len(self.nodes)<=2:raise ValueError('路径至少保留两个节点')
        if self.node_enabled[node] and np.count_nonzero(self.node_enabled)<=2:raise ValueError('测试区间至少保留两个节点；请先恢复全部点')
        if node in (0,len(self.nodes)-1):
            candidate=copy.deepcopy(self);candidate._trim_endpoint(node);candidate.validate()
            self.__dict__=candidate.__dict__
            return
        if np.linalg.norm(self.nodes[node+1]-self.nodes[node-1])<.02:
            raise ValueError('删除后相邻节点距离不足0.02 mm')
        p=self.points();a,b=self.indices[node-1],self.indices[node+1]
        lengths=arc(p)
        merged_position=self.speed_positions[node-1]*(lengths[self.indices[node]]-lengths[a])/(lengths[b]-lengths[a])
        self._bake_geometry(p)
        progress=arc(p[a:b+1]);progress/=progress[-1]
        p[a:b+1]=p[a]+progress[:,None]*(p[b]-p[a])
        self._bake_geometry(p)
        self.indices=np.delete(self.indices,node)
        self.nodes=self.original[self.indices].copy()
        self.node_enabled=np.delete(self.node_enabled,node)
        self.node_speeds=np.delete(self.node_speeds,node)
        self.segment_speeds=np.delete(self.segment_speeds,node)
        self.speed_positions=np.delete(self.speed_positions,node)
        self.speed_positions[node-1]=np.clip(merged_position,.05,.95)
        self.node_angles=np.delete(self.node_angles,node,axis=0)
        self.lift_mm=np.delete(self.lift_mm,node)
        self.segment_magnetic=np.delete(self.segment_magnetic,node)
        self.validate()

    def set_segment(self,k,length,angle):
        if not np.isfinite([length,angle]).all() or length<.02:
            raise ValueError('段长度至少0.02 mm，角度必须为有限数值')
        theta=np.deg2rad(angle)
        endpoint=self.nodes[k]+length*np.array([np.cos(theta),np.sin(theta)])
        delta=endpoint-self.nodes[k+1]
        self.nodes[k+1:]+=delta

    def settings(self):
        settings={n:json.loads(((self.folder if (self.folder/n).exists() else CONTEXT)/n).read_text())
            for n in ['feedforward.json','settings.json','entry_profile.json','pi_profile.json']}
        if self.feedforward_override:
            settings['feedforward.json']=json.loads(Path(self.feedforward_override).read_text())
        for attribute,name in [('settings_override','settings.json'),('entry_profile_override','entry_profile.json')]:
            path=getattr(self,attribute,None)
            if path:settings[name]=json.loads(Path(path).read_text())
        settings['feedforward.json'].pop('low_response_trial',None)
        settings['feedforward.json'].pop('low_response_trial_note',None)
        return settings

    def select_feedforward(self,path):
        from brushbot.feedforward import validate_table
        path=Path(path).resolve();table=json.loads(path.read_text());validate_table(table)
        setting=entry=None
        if table.get('high_speed_trial'):
            setting=path.with_name('settings_cyg.json');entry=path.with_name('entry_profile_cyg.json')
            if not setting.exists() or not entry.exists():
                setting=path.with_name('settings.json');entry=path.with_name('entry_profile.json')
            if not setting.exists() or not entry.exists():raise ValueError('高速试验表须配套settings_cyg.json和entry_profile_cyg.json')
            paired_setup=json.loads(setting.read_text());paired_entry=json.loads(entry.read_text())
            if paired_setup.get('max_accel_mm_s2')!=400. or paired_entry.get('angular_speed_deg_s')!=40. or paired_entry.get('angular_accel_deg_s2')!=80.:raise ValueError('高速试验配套限值应为400 mm/s²、40°/s和80°/s²')
            from brushbot.experiments.strokeplan_execution import runtime_settings
            runtime_settings(json.loads(setting.read_text()))
        self.feedforward_override=str(path)
        self.settings_override=str(setting) if setting else None
        self.entry_profile_override=str(entry) if entry else None

    def set_timing(self, timing):
        """Accept speed knots in current displayed path progress coordinates."""
        result=copy.deepcopy(timing)
        for key in ['speed_mm_s','accel_mm_s2','angular_speed_deg_s','angular_accel_deg_s2']:
            value=float(result[key])
            if not np.isfinite(value) or value<=0:raise ValueError('速度和加速度必须为正有限数值')
            result[key]=value
        knots=np.array(result['speed_knots_s_mm_s'],float)
        if (knots.ndim!=2 or knots.shape[1]!=2 or len(knots)<2 or not np.isfinite(knots).all()
                or knots[0,0]!=0 or knots[-1,0]!=1 or np.any(np.diff(knots[:,0])<=0)
                or np.any(knots[:,1]<=0)):
            raise ValueError('速度节点至少两个，进度从0到100%且严格递增，速度必须大于0')
        before=arc(self.original);after=arc(self.points())
        knots[:,0]=np.interp(knots[:,0]*after[-1],after,before)/before[-1]
        result['speed_knots_s_mm_s']=knots.tolist()
        self.base=copy.deepcopy(self.base);self.base['timing']=result

    def set_orientation(self, orientation):
        """Edit inclination and heading nodes in current displayed path progress."""
        from scripts.generate_strokeplan_from_json import build_plan
        candidate=copy.deepcopy(self)
        result=copy.deepcopy(orientation)
        tilt=float(result['tilt_deg']);entry=self.settings()['entry_profile.json']['entry_tilt_deg']
        if not np.isfinite(tilt) or not 0<tilt<entry:
            raise ValueError(f'书写倾角必须大于0°且小于进笔倾角{entry:g}°')
        result['tilt_deg']=tilt
        if 'heading_knots_s_deg' in result:
            before=arc(self.original);after=arc(self.points())
            result['heading_knots_s_deg']=[[float(np.interp(s*after[-1],after,before)/before[-1]),angle]
                for s,angle in result['heading_knots_s_deg']]
        candidate.base['orientation']=result
        build_plan(candidate.recipe())
        self.base=candidate.base

    def displayed_node_angles(self):
        from scripts.generate_strokeplan_from_json import build_plan
        from brushbot.experiments.strokeplan_character import orientation_heading
        st=build_plan(self.recipe()).strokes[0]
        distances=arc(self.points());progress=distances[self.indices]/distances[-1]
        heading=np.unwrap([orientation_heading(rpy) for rpy in st.orientation])
        tilt=np.rad2deg(np.arccos(np.clip(np.cos(st.orientation[:,0])*np.cos(st.orientation[:,1]),-1,1)))
        return np.column_stack([np.interp(progress,st.s,tilt),np.rad2deg(np.interp(progress,st.s,heading))])

    def _apply_local_speeds(self,result,distances,upper=None):
        if (self.node_speeds.shape!=(len(self.nodes),) or self.segment_speeds.shape!=(len(self.nodes)-1,)
                or self.speed_positions.shape!=(len(self.nodes)-1,)):
            raise ValueError('局部速度节点数量不匹配')
        if not np.isfinite(self.speed_positions).all() or np.any((self.speed_positions<.05)|(self.speed_positions>.95)):
            raise ValueError('节奏位置须在5%至95%之间')
        values=[*self.node_speeds,*self.segment_speeds]
        if upper is None:upper=self.settings()['feedforward.json']['speed_mm_s']
        if any(v is not None and (not np.isfinite(v) or not 0<v<=upper) for v in values):
            raise ValueError(f'局部速度须大于0且不超过{upper:g} mm/s')
        if not any(v is not None for v in values):return
        boundaries=distances[self.indices]/distances[-1]
        old=np.array(result['timing'].get('speed_knots_s_mm_s',[[0,result['timing']['speed_mm_s']],[1,result['timing']['speed_mm_s']]]),float)
        mids=boundaries[:-1]+np.diff(boundaries)*self.speed_positions
        q=np.unique(np.r_[np.linspace(0,1,2001),old[:,0],boundaries,mids])
        baseline=np.interp(q,old[:,0],old[:,1]);target=baseline.copy()
        for k in range(len(self.segment_speeds)):
            left,right=self.node_speeds[k:k+2];mid=None if self.endpoint_speed_mode else self.segment_speeds[k]
            if left is None and right is None and mid is None:continue
            spans=[(boundaries[k],boundaries[k+1],left,right)] if mid is None else [(boundaries[k],mids[k],left,mid),(mids[k],boundaries[k+1],mid,right)]
            for start,end,v0,v1 in spans:
                mask=(q>=start)&(q<=end);u=np.clip((q[mask]-start)/(end-start),0,1);w=6*u**5-15*u**4+10*u**3
                a=baseline[mask] if v0 is None else v0;b=baseline[mask] if v1 is None else v1
                target[mask]=(1-w)*a+w*b
        result['timing']['speed_knots_s_mm_s']=np.column_stack([q,target]).tolist()
        result['timing']['speed_mm_s']=max(result['timing']['speed_mm_s'],float(target.max()))

    def use_endpoint_speeds(self):
        self.endpoint_speed_mode=True
        self.segment_speeds[:]=None
        self.speed_positions[:]=.5

    def speed_curve(self,upper=None,distances=None):
        """Preview timing only; never build pose/magnetic plans while dragging."""
        if distances is None:distances=arc(self.points())
        before=arc(self.original)
        timing=copy.deepcopy(self.base['timing'])
        timing['speed_knots_s_mm_s']=[[float(np.interp(q*before[-1],before,distances)/distances[-1]),v] for q,v in timing.get('speed_knots_s_mm_s',[[0,timing['speed_mm_s']],[1,timing['speed_mm_s']]])]
        result={'timing':timing};self._apply_local_speeds(result,distances,upper)
        return np.array(result['timing']['speed_knots_s_mm_s'],float)

    def displayed_node_speeds(self,upper=None,distances=None):
        if distances is None:distances=arc(self.points())
        knots=self.speed_curve(upper,distances)
        return np.interp(distances[self.indices]/distances[-1],knots[:,0],knots[:,1])

    def displayed_local_speeds(self):
        distances=arc(self.points());q=distances[self.indices]/distances[-1]
        knots=self.speed_curve(distances=distances)
        sample=np.column_stack([q[:-1],q[:-1]+np.diff(q)*self.speed_positions,q[1:]])
        return np.interp(sample,knots[:,0],knots[:,1])

    def inherited_segment_values(self):
        """Original magnetic target at each segment's start/mid/end."""
        distances=arc(self.original);node_s=distances[self.indices]/distances[-1]
        q=np.column_stack([node_s[:-1],(node_s[:-1]+node_s[1:])/2,node_s[1:]])
        knots=np.array(self.base['magnetic_target']['knots_s_uT'],float);knots[:,1]=self.magnetic_values
        if self.base['magnetic_target']['interpolation']=='quintic':
            from scripts.generate_calligraphy_trial import contact_profile
            return contact_profile(q,knots)
        return np.interp(q,knots[:,0],knots[:,1])

    def recipe(self):
        p=self.points();before=arc(self.original);after=arc(p)
        result=copy.deepcopy(self.base)
        result['name']='交互编辑：'+self.base['name']
        result['description']='User-edited XY geometry; magnetic levels and speed requests retained at corresponding source positions.'
        result['path']['points_mm']=p.tolist()
        for section,key in [('magnetic_target','knots_s_uT'),('timing','speed_knots_s_mm_s'),('orientation','heading_knots_s_deg'),('orientation','node_angles_s_deg')]:
            if key in result[section]:
                result[section][key]=[[float(np.interp(row[0]*before[-1],before,after)/after[-1]),*row[1:]]
                    for row in self.base[section][key]]
        if self.node_angles.shape!=(len(self.nodes),2):raise ValueError('笔杆角度节点数量不匹配')
        for tilt,heading in self.node_angles:
            if tilt is not None and (not np.isfinite(tilt) or not 0<tilt<30):raise ValueError('节点倾角须大于0°且小于30°')
            if heading is not None and not np.isfinite(heading):raise ValueError('节点朝向须为有限角度')
        if any(v is not None for v in self.node_angles.flat):
            result['orientation']['node_angles_s_deg']=[[float(progress),*values] for progress,values in zip(after[self.indices]/after[-1],self.node_angles.tolist())]
        table=self.settings()['feedforward.json']
        amplitudes=np.array(table['amplitude_uT'],float);depths=np.array(table['depth_mm'],float)
        if (self.magnetic_values.shape!=(len(self.base['magnetic_target']['knots_s_uT']),)
                or not np.isfinite(self.magnetic_values).all()
                or np.any(self.magnetic_values<0) or np.any(self.magnetic_values>amplitudes[-1])):
            raise ValueError(f'磁目标输入范围必须在 0–{amplitudes[-1]:.2f} μT 内')
        if self.lift_mm.shape!=(len(self.nodes),) or not np.isfinite(self.lift_mm).all() or np.any(self.lift_mm<0):
            raise ValueError('提笔高度必须为非负有限数值')
        knots=result['magnetic_target']['knots_s_uT']
        result['magnetic_target']['knots_s_uT']=[[x,float(v)] for (x,_),v in zip(knots,self.magnetic_values)]
        if self.segment_magnetic.shape!=(len(self.nodes)-1,):raise ValueError('分段磁目标数量不匹配')
        if any(v is not None for v in self.segment_magnetic):
            from scripts.generate_strokeplan_from_json import build_plan
            st=build_plan(result).strokes[0]
            node_s=after[self.indices]/after[-1]
            q=np.unique(np.r_[np.linspace(0.,1.,1501),st.s,node_s])
            target=np.interp(q,st.s,st.g_target)
            baseline=target.copy()
            values=self.segment_magnetic
            for value in values:
                if value is not None and (not np.isfinite(value) or not 0<=value<=amplitudes[-1]):
                    raise ValueError('分段磁目标超出输入范围（下限0）')
            k=0
            while k<len(values):
                if values[k] is None:
                    k+=1;continue
                first=k
                while k+1<len(values) and values[k+1] is not None:k+=1
                last=k
                mask=(q>=node_s[first])&(q<=node_s[last+1])
                selected=np.clip(np.searchsorted(node_s,q[mask],side='right')-1,first,last)
                target[mask]=np.array([float(values[i]) for i in selected])
                # Enter an explicit region once, not once per segment.
                width=.25*(node_s[first+1]-node_s[first])
                enter=(q>=node_s[first])&(q<=node_s[first]+width)
                u=np.clip((q[enter]-node_s[first])/width,0.,1.);w=6*u**5-15*u**4+10*u**3
                target[enter]=(1-w)*baseline[enter]+w*float(values[first])
                # Shared boundary transitions connect the two requested values.
                # Equal values therefore remain constant with no source-curve spike.
                for boundary in range(first+1,last+1):
                    if values[boundary-1]==values[boundary]:continue
                    center=node_s[boundary]
                    half=.20*min(node_s[boundary]-node_s[boundary-1],node_s[boundary+1]-node_s[boundary])
                    transition=(q>=center-half)&(q<=center+half)
                    u=np.clip((q[transition]-(center-half))/(2*half),0.,1.);w=6*u**5-15*u**4+10*u**3
                    target[transition]=(1-w)*float(values[boundary-1])+w*float(values[boundary])
                # Only blend back if there really is an inherited next segment.
                # At the end of writing keep the explicit final target until lift.
                if last<len(values)-1:
                    width=.25*(node_s[last+1]-node_s[last])
                    leave=(q>=node_s[last+1]-width)&(q<=node_s[last+1])
                    u=np.clip((q[leave]-(node_s[last+1]-width))/width,0.,1.);w=6*u**5-15*u**4+10*u**3
                    target[leave]=(1-w)*float(values[last])+w*baseline[leave]
                k+=1
            result['magnetic_target']={'interpolation':'linear','knots_s_uT':np.column_stack([q,target]).tolist()}
        self._apply_local_speeds(result,after)
        result['notes']=['XY edited in brush path editor; reference image/line is not measured ink.',
            'Smooth magnetic curve supplies nominal Z feedforward only. Exact per-segment control references override it through entry_profile.segment_magnetic_targets, with no reference blending inside explicit segments. Writing Z offsets are stored separately.',
            'Compiled timing and tangent-derived orientation may change with XY; existing limits still apply.',
            'No early lift added; actual contact and ink shape require experimental verification.']
        return result

    def state(self,include_workspace=True):
        result=dict(node_enabled=self.node_enabled.tolist(),endpoint_speed_mode=self.endpoint_speed_mode,settings_override=getattr(self,'settings_override',None),entry_profile_override=getattr(self,'entry_profile_override',None),node_speeds_mm_s=self.node_speeds.tolist(),segment_speeds_mm_s=self.segment_speeds.tolist(),speed_positions=self.speed_positions.tolist(),node_angles_deg=self.node_angles.tolist(),schema_version=1,source_folder=str(self.folder),base_recipe=self.base,
                    indices=self.indices.tolist(),nodes_mm=self.nodes.tolist(),magnetic_values_uT=self.magnetic_values.tolist(),lift_mm=self.lift_mm.tolist(),segment_magnetic_uT=self.segment_magnetic.tolist(),height_mode='writing_z_offset',allow_low_response_trial=self.allow_low_response,feedforward_override=str(self.feedforward_override) if self.feedforward_override else None)
        result.update(stroke_id=self.stroke_id,stroke_name=self.stroke_name,rhythm_regions=copy.deepcopy(self.rhythm_regions))
        if include_workspace:
            result['stroke_workspace']=dict(order=self.stroke_order.copy(),others=copy.deepcopy(self.other_strokes),pending_point=copy.deepcopy(self.pending_point),pending_stroke_position=self.pending_stroke_position)
        return result

    @classmethod
    def restore(cls,path):
        return cls.from_state(json.loads(Path(path).read_text()))

    @classmethod
    def from_state(cls,state):
        state=copy.deepcopy(state)
        if state.get('schema_version')!=1:raise ValueError('不支持的编辑器存档版本')
        obj=cls.__new__(cls);obj.folder=Path(state['source_folder'])
        obj.base=state['base_recipe'];obj.original=np.array(obj.base['path']['points_mm'],float)
        obj.indices=np.array(state['indices'],int);obj.nodes=np.array(state['nodes_mm'],float)
        flags=state.get('node_enabled',[True]*len(obj.nodes))
        if any(type(flag) is not bool for flag in flags):raise ValueError('测试节点状态必须为布尔值')
        obj.node_enabled=np.array(flags,dtype=bool)
        if obj.indices[0]!=0 or obj.indices[-1]!=len(obj.original)-1 or np.any(np.diff(obj.indices)<=0):
            raise ValueError('存档节点索引不合法')
        if obj.nodes.shape!=(len(obj.indices),2):raise ValueError('存档节点数量不匹配')
        obj.magnetic_values=np.array(state.get('magnetic_values_uT',np.array(obj.base['magnetic_target']['knots_s_uT'])[:,1]),float)
        obj.lift_mm=np.array(state.get('lift_mm',np.zeros(len(obj.nodes))) if state.get('height_mode')=='writing_z_offset' else np.zeros(len(obj.nodes)),float)
        obj.segment_magnetic=np.array(state.get('segment_magnetic_uT',[None]*(len(obj.nodes)-1)),dtype=object)
        obj.endpoint_speed_mode=state.get('endpoint_speed_mode',False) is True
        obj.node_speeds=np.array(state.get('node_speeds_mm_s',[None]*len(obj.nodes)),dtype=object)
        obj.segment_speeds=np.array(state.get('segment_speeds_mm_s',[None]*(len(obj.nodes)-1)),dtype=object)
        obj.speed_positions=np.array(state.get('speed_positions',[.5]*(len(obj.nodes)-1)),float)
        obj.node_angles=np.array(state.get('node_angles_deg',[[None,None] for _ in obj.nodes]),dtype=object)
        obj.allow_low_response=state.get('allow_low_response_trial',False) is True
        obj.feedforward_override=state.get('feedforward_override')
        obj.settings_override=state.get('settings_override')
        obj.entry_profile_override=state.get('entry_profile_override')
        obj.stroke_id=state.get('stroke_id','stroke-1')
        obj.stroke_name=state.get('stroke_name','笔画1')
        workspace=state.get('stroke_workspace',{})
        obj.other_strokes=workspace.get('others',[])
        ids=[obj.stroke_id]
        for other in obj.other_strokes:
            if 'stroke_workspace' in other:raise ValueError('笔画存档不允许嵌套工作区')
            restored=cls.from_state(other)
            ids.append(restored.stroke_id)
        obj.stroke_order=workspace.get('order',ids)
        if len(set(ids))!=len(ids) or len(obj.stroke_order)!=len(ids) or set(obj.stroke_order)!=set(ids):
            raise ValueError('独立笔画编号不合法')
        obj.pending_point=workspace.get('pending_point')
        obj.pending_stroke_position=workspace.get('pending_stroke_position','end')
        if obj.pending_stroke_position not in ('start','end'):raise ValueError('新笔画顺序须为最前或末尾')
        obj.rhythm_regions=state.get('rhythm_regions',[])
        from scripts.brush_rhythm import validate_regions
        validate_regions(obj.rhythm_regions)
        if obj.pending_point is not None:
            xy=np.asarray(obj.pending_point,float)
            if xy.shape!=(2,) or not np.isfinite(xy).all():raise ValueError('独立起点坐标必须为有限X/Y')
        obj.validate();return obj

    def stroke_entries(self):
        entries={s['stroke_id']:s['stroke_name'] for s in self.other_strokes}
        entries[self.stroke_id]=self.stroke_name
        return [(key,entries[key]) for key in self.stroke_order]

    def stroke_node_offset(self,stroke_id=None):
        """Global, contiguous point numbers follow stroke order, including hidden points."""
        stroke_id=stroke_id or self.stroke_id
        counts={s['stroke_id']:len(s['nodes_mm']) for s in self.other_strokes}
        counts[self.stroke_id]=len(self.nodes)
        offset=1 if self.pending_point is not None and self.pending_stroke_position=='start' else 0
        for key in self.stroke_order:
            if key==stroke_id:return offset
            offset+=counts[key]
        raise ValueError('找不到笔画编号')

    def total_node_count(self):
        return len(self.nodes)+sum(len(s['nodes_mm']) for s in self.other_strokes)

    def pending_node_number(self):
        return 0 if self.pending_stroke_position=='start' else self.total_node_count()

    def switch_stroke(self,stroke_id):
        if stroke_id==self.stroke_id:return
        if self.pending_point is not None:raise ValueError('请先添加第二个点完成新笔画，或取消独立起点')
        target=next((s for s in self.other_strokes if s['stroke_id']==stroke_id),None)
        if target is None:raise ValueError('找不到所选笔画')
        candidate=self.from_state(target)
        candidate.other_strokes=[copy.deepcopy(s) for s in self.other_strokes if s['stroke_id']!=stroke_id]+[copy.deepcopy(self.state(False))]
        candidate.stroke_order=self.stroke_order.copy()
        self.__dict__=candidate.__dict__

    def add_independent_point(self,xy,position='end'):
        """First point is isolated; second starts a new, separately executable stroke."""
        xy=np.asarray(xy,float)
        if xy.shape!=(2,) or not np.isfinite(xy).all():raise ValueError('新点X/Y必须是有限数值')
        if position not in ('start','end'):raise ValueError('新笔画顺序须为最前或末尾')
        if self.pending_point is None:
            self.pending_point=xy.tolist()
            self.pending_stroke_position=position
            return False
        points=np.array([self.pending_point,xy],float)
        if np.linalg.norm(points[1]-points[0])<.02:raise ValueError('新笔画的两个点至少相隔0.02 mm')
        # Copy only settings, never geometry or the old stroke's progress profiles.
        state=copy.deepcopy(self.state(False))
        value=self.segment_magnetic[-1]
        if value is None:value=float(self.inherited_segment_values()[-1,-1])
        speed=float(self.displayed_node_speeds()[-1])
        angles=self.displayed_node_angles()[-1].tolist()
        state['base_recipe']['path']['points_mm']=points.tolist()
        state['base_recipe']['magnetic_target'].update(knots_s_uT=[[0.,float(value)],[1.,float(value)]],interpolation='linear')
        state['base_recipe']['timing']['speed_knots_s_mm_s']=[[0.,speed],[1.,speed]]
        for key in ('heading_knots_s_deg','node_angles_s_deg'):
            state['base_recipe']['orientation'].pop(key,None)
        state.update(indices=[0,1],nodes_mm=points.tolist(),node_enabled=[True,True],magnetic_values_uT=[float(value)]*2,
            lift_mm=[0.,0.],segment_magnetic_uT=[float(value)],node_speeds_mm_s=[speed]*2,
            segment_speeds_mm_s=[None],speed_positions=[.5],node_angles_deg=[angles.copy(),angles.copy()],
            rhythm_regions=[],stroke_id='stroke-'+uuid.uuid4().hex[:12],stroke_name=f'{"新增首笔" if self.pending_stroke_position=="start" else "笔画"}{len(self.stroke_order)+1}')
        candidate=self.from_state(state)
        candidate.other_strokes=copy.deepcopy(self.other_strokes)+[copy.deepcopy(self.state(False))]
        candidate.stroke_order=[candidate.stroke_id,*self.stroke_order] if self.pending_stroke_position=='start' else [*self.stroke_order,candidate.stroke_id]
        self.__dict__=candidate.__dict__
        return True

    def execution_model(self):
        """Crop a continuous test interval, retaining world placement and profiles."""
        first,last=self.test_node_range()
        if first==0 and last==len(self.nodes)-1:return self
        from scripts.generate_strokeplan_from_json import build_plan
        from brushbot.experiments.strokeplan_character import orientation_heading
        full=self.recipe();p=self.points();distances=arc(p)
        a,b=self.indices[[first,last]];lo,hi=distances[[a,b]]/distances[-1]
        # Resolve inherited tangent headings using the full path before cropping.
        st=build_plan(full).strokes[0]
        q=distances[self.indices[first:last+1]]/distances[-1]
        heading=np.rad2deg(np.unwrap([orientation_heading(rpy) for rpy in st.orientation]))
        tilt=np.rad2deg(np.arccos(np.clip(np.cos(st.orientation[:,0])*np.cos(st.orientation[:,1]),-1,1)))
        resolved=np.column_stack([np.interp(q,st.s,tilt),np.interp(q,st.s,heading)])
        for section,key in [('magnetic_target','knots_s_uT'),('timing','speed_knots_s_mm_s')]:
            rows=np.array(full[section][key],float)
            progress=np.unique(np.r_[lo,rows[(rows[:,0]>lo)&(rows[:,0]<hi),0],hi])
            if section=='magnetic_target':
                # Preserve the evaluated original curve, including quintic profiles.
                progress=np.unique(np.r_[progress,st.s[(st.s>lo)&(st.s<hi)]])
                values=np.interp(progress,st.s,st.g_target)
                full[section]['interpolation']='linear'
            else:values=np.interp(progress,rows[:,0],rows[:,1])
            full[section][key]=np.column_stack([(progress-lo)/(hi-lo),values]).tolist()
        full['orientation'].pop('heading_knots_s_deg',None)
        full['orientation'].pop('node_angles_s_deg',None)
        full['path']['points_mm']=p[a:b+1].tolist()
        partial=copy.deepcopy(self);partial.base=full;partial.original=p[a:b+1].copy()
        partial.indices=self.indices[first:last+1]-a;partial.nodes=self.nodes[first:last+1].copy()
        partial.node_enabled=np.ones(len(partial.nodes),dtype=bool)
        partial.node_angles=resolved.astype(object)
        partial.magnetic_values=np.array(full['magnetic_target']['knots_s_uT'])[:,1]
        partial.segment_magnetic=self.segment_magnetic[first:last].copy()
        # The full recipe already contains local speed edits; do not apply twice.
        partial.node_speeds=np.full(len(partial.nodes),None,dtype=object)
        partial.segment_speeds=np.full(len(partial.nodes)-1,None,dtype=object)
        partial.speed_positions=np.full(len(partial.nodes)-1,.5)
        partial.lift_mm=self.lift_mm[first:last+1].copy()
        partial.rhythm_regions=[]
        for row in self.rhythm_regions:
            start,end=max(lo,row['start']),min(hi,row['end'])
            if end-start>=(hi-lo)*1e-5:
                partial.rhythm_regions.append(dict(row,start=(start-lo)/(hi-lo),end=(end-lo)/(hi-lo)))
        return partial

    def compile(self,entry_adjustments=None,reference_only=False):
        if self.pending_point is not None:raise ValueError('新笔画只有独立起点；请添加第二个点或取消独立起点后再预检、导出')
        effective=self.execution_model()
        if effective is not self:
            result=effective.compile(entry_adjustments,reference_only)
            self.last_speed_adaptation=effective.last_speed_adaptation
            return result
        from scripts.generate_strokeplan_from_json import build_plan
        from brushbot.experiments.strokeplan_execution import compile_recorded_plan
        from brushbot.experiments.z_identification import _check_trajectory
        settings=self.settings()
        if entry_adjustments:settings['entry_profile.json'].update(entry_adjustments)
        if 'tail_exit' in settings['entry_profile.json']:raise ValueError('不支持提前离纸方案')
        recipe=self.recipe();plan=build_plan(recipe)
        settings['entry_profile.json']['writing_tilt_deg']=round(float(np.rad2deg(np.arccos(np.clip(np.cos(plan.strokes[0].orientation[0,0])*np.cos(plan.strokes[0].orientation[0,1]),-1,1)))),12)
        lower=settings['feedforward.json']['amplitude_uT'][0]
        if min(plan.strokes[0].g_target)<lower-1e-9 and not self.allow_low_response:
            raise ValueError(f'磁目标低于现有标定下限 {lower:.2f} μT；数值可编辑并保存草稿，但不可外推压深执行。需要补充低响应标定。')
        if self.lift_mm[0]!=0:raise ValueError('起笔前高度固定；第一节点的书写提笔量必须为0')
        if np.any(self.lift_mm>0):
            distances=arc(self.points())
            settings['entry_profile.json']['writing_height']={'knots_s_mm':np.column_stack([distances[self.indices]/distances[-1],self.lift_mm]).tolist()}
        else:
            settings['entry_profile.json'].pop('writing_height',None)
        if self.allow_low_response:
            table=settings['feedforward.json']
            table['low_response_trial']=dict(method='linear_to_nominal_zero_depth',trial_authorized=True,
                measured_lower_uT=float(table['amplitude_uT'][0]),measured_lower_depth_mm=float(table['depth_mm'][0]))
            table['low_response_trial_note']='User-authorized unmeasured low-response experiment; measured knots unchanged. 0uT maps to zero nominal depth, not a verified contact state.'
        if any(value is not None for value in self.segment_magnetic):
            distances=arc(self.points())
            settings['entry_profile.json']['segment_magnetic_targets']={'nodes_s':(distances[self.indices]/distances[-1]).tolist(),'values_uT':self.segment_magnetic.tolist()}
        else:
            settings['entry_profile.json'].pop('segment_magnetic_targets',None)
        from scripts.brush_rhythm import verified_reference,rhythm_knots
        recipe,plan,compiled,limits,report=verified_reference(recipe,settings)
        if self.rhythm_regions and not reference_only:
            from scripts.brush_speed_adaptation import adapt_speed
            reference_report=copy.deepcopy(report)
            recipe=copy.deepcopy(recipe)
            recipe['timing']['speed_knots_s_mm_s']=rhythm_knots(recipe['timing'],self.rhythm_regions).tolist()
            recipe,plan,compiled,limits,report=adapt_speed(recipe,settings)
            report.update(rhythm_regions=copy.deepcopy(self.rhythm_regions),reference_report=reference_report,
                rhythm_iterations=report['iterations'],iterations=report['iterations']+reference_report['iterations'],
                adapted=report['adapted'] or reference_report['adapted'])
        self.last_speed_adaptation=report
        self.audit_targets(compiled)
        return recipe,plan,compiled,settings,limits

    def compile_workspace(self):
        """Compile each stroke locally, then verify one complete lift/transfer sequence."""
        if self.pending_point is not None:raise ValueError('新笔画只有独立起点；请添加第二个点或取消独立起点')
        if len(self.stroke_order)==1:
            result=self.compile()
            self.last_workspace_strokes=[dict(stroke_id=self.stroke_id,stroke_name=self.stroke_name,
                point_range=list(self.test_node_range()),recipe=result[0],speed_adaptation=self.last_speed_adaptation)]
            return result
        from brushbot.target_strokeplan import StrokePlan
        from brushbot.experiments.strokeplan_execution import compile_recorded_plan
        from brushbot.experiments.z_identification import _check_trajectory
        states={s['stroke_id']:s for s in self.other_strokes};states[self.stroke_id]=self.state(False)
        parts=[];profiles=[];common=None;shared_entry=None;rows=[];models=[]
        contact_keys={'writing_tilt_deg','segment_magnetic_targets','writing_height','entry_reverse_mm'}
        for i,key in enumerate(self.stroke_order):
            model=self.from_state(states[key]);models.append(model)
            # Every later pen-down starts directly at its first enabled point.
            recipe,plan,_,settings,_=model.compile({'entry_reverse_mm':0.} if i else None)
            entry=settings['entry_profile.json']
            if entry.get('mode')!='directional_character':raise ValueError('多笔画执行需要 directional_character 进笔配置')
            signature={name:value for name,value in settings.items() if name!='entry_profile.json'}
            transport={k:v for k,v in entry.items() if k not in contact_keys}
            if common is None:
                common=signature;shared_entry=transport
                settings_all=copy.deepcopy(settings)
            elif signature!=common or transport!=shared_entry:
                raise ValueError('多笔画的前馈表、现场设置、PI和悬空转场配置必须一致；请先统一各笔画配置')
            profiles.append({**{k:copy.deepcopy(v) for k,v in entry.items() if k in contact_keys},
                'node_angles':recipe['orientation'].get('node_angles_s_deg') is not None})
            parts.extend(plan.strokes)
            first,last=model.test_node_range();offset=self.stroke_node_offset(key)
            rows.append(dict(stroke_id=key,stroke_name=model.stroke_name,point_range=[offset+first,offset+last],
                hidden_points=(offset+np.flatnonzero(~model.node_enabled)).tolist(),recipe=recipe,
                speed_adaptation=copy.deepcopy(model.last_speed_adaptation)))
            if i==0:meta=copy.deepcopy(plan.meta)
        entry=settings_all['entry_profile.json']
        for key in contact_keys:entry.pop(key,None)
        entry.update(writing_tilt_deg=profiles[0]['writing_tilt_deg'],
            entry_reverse_mm=profiles[0].get('entry_reverse_mm',0.),stroke_profiles=profiles)
        meta.update(stroke_names=[row['stroke_name'] for row in rows],stroke_point_ranges=[row['point_range'] for row in rows])
        combined=StrokePlan(parts,meta)
        compiled=compile_recorded_plan(combined,settings_all['feedforward.json'],settings_all['settings.json'],
            label='interactive_brush_sequence_pi',control_mode='pi',feedback_profile=settings_all['pi_profile.json'],entry_profile=entry)
        limits=_check_trajectory(compiled['pose_m_rad'],settings_all['settings.json'],entry)
        self.last_workspace_audit=[]
        for i,(model,row) in enumerate(zip(models,rows)):
            mask=compiled['phase']==f'measure_{i:02}'
            audit=model.audit_targets(dict(phase=np.full(int(mask.sum()),'measure_00'),s=compiled['s'][mask],g_ref_uT=compiled['g_ref_uT'][mask]))
            self.last_workspace_audit.extend(dict(stroke_id=row['stroke_id'],stroke_name=row['stroke_name'],**item) for item in audit)
        reports=[row['speed_adaptation'] for row in rows]
        self.last_speed_adaptation=dict(enabled=True,method='per_stroke_local_adaptation_then_full_sequence_verification',
            adapted=any(r['adapted'] for r in reports),iterations=sum(r['iterations'] for r in reports),
            writing_duration_s=sum(float(s.t[-1]) for s in parts),
            planned_max_writing_speed_mm_s=max(r['planned_max_writing_speed_mm_s'] for r in reports),
            global_time_scaling_applied=False,hardware_executed=False,strokes=reports,limits=limits)
        self.last_workspace_strokes=rows
        manifest=dict(kind='brush_stroke_workspace',execution_scope='all_strokes_in_order',strokes=rows)
        return manifest,combined,compiled,settings_all,limits

    def audit_targets(self,compiled):
        effective=self.execution_model()
        if effective is not self:return effective.audit_targets(compiled)
        distances=arc(self.points());nodes=distances[self.indices]/distances[-1]
        mask=compiled['phase']=='measure_00'
        q=compiled['s'][mask];targets=compiled['g_ref_uT'][mask]
        owner=np.clip(np.searchsorted(nodes,q,side='right')-1,0,len(self.segment_magnetic)-1)
        report=[]
        for k,value in enumerate(self.segment_magnetic):
            if value is None:continue
            samples=targets[owner==k]
            if len(samples)==0:raise ValueError(f'第{k+1}段没有控制采样点，不能保证执行该段磁目标')
            if not np.allclose(samples,float(value),atol=1e-10,rtol=0):
                raise ValueError(f'第{k+1}段磁目标与设置不一致，禁止导出')
            report.append(dict(segment=k+1,requested_uT=float(value),samples=len(samples),
                actual_reference_min_uT=float(samples.min()),actual_reference_max_uT=float(samples.max())))
        return report

    def export(self,parent=None):
        # Compile before creating an executable version; failure leaves no runnable export.
        recipe,plan,compiled,settings,limits=self.compile_workspace()
        parent=Path(parent) if parent else ROOT/'runs/brush2/plans/interactive'
        name=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d/%H-%M-%S')+'__'+uuid.uuid4().hex[:6]
        folder=parent/name;folder.mkdir(parents=True,exist_ok=False)
        plan.save(folder/'strokeplan.npz')
        multiple=len(self.stroke_order)>1
        summary=dict(hardware_executed=False,ink_quality_verified=False,
            stroke_id=self.stroke_id,stroke_name=self.stroke_name,workspace_stroke_count=len(self.stroke_order),execution_scope='all_strokes_in_order',
            execution_order=[{k:row[k] for k in ('stroke_id','stroke_name','point_range')} for row in self.last_workspace_strokes],
            transfer_z_mm=settings['entry_profile.json'].get('transfer_z_mm'),
            test_node_range=list(self.test_node_range()),hidden_nodes=np.flatnonzero(~self.node_enabled).tolist(),
            low_response_trial=self.allow_low_response,retiming_factor=1. if multiple else float(recipe['timing']['speed_mm_s']/self.recipe()['timing']['speed_mm_s']),
            writing_duration_s=sum(float(st.t[-1]) for st in plan.strokes),full_duration_s=float(compiled['t_s'][-1]),limits=limits,
            auto_speed_adaptation=True,local_speed_adapted=self.last_speed_adaptation['adapted'],
            local_speed_iterations=self.last_speed_adaptation['iterations'])
        extra={'workspace_recipe.json':recipe} if multiple else {}
        current_recipe=next(row['recipe'] for row in self.last_workspace_strokes if row['stroke_id']==self.stroke_id)
        for name,value in {**settings,**extra,'recipe.json':current_recipe,'editor_state.json':self.state(),'preflight.json':summary,'segment_target_audit.json':self.last_workspace_audit if multiple else self.audit_targets(compiled),'speed_adaptation.json':self.last_speed_adaptation}.items():
            (folder/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
        return folder,summary
