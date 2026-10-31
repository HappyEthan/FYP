"""Explicit per-segment control references, independent of smooth nominal Z."""
import numpy as np
from brushbot.feedforward import lookup_depth_m


def stroke_entry_profile(profile,index):
    """Resolve per-stroke contact settings without sharing progress across strokes."""
    result={key:value for key,value in (profile or {}).items() if key!='stroke_profiles'}
    profiles=(profile or {}).get('stroke_profiles')
    if profiles is not None:
        result.update(profiles[index])
    return result

def validate_segment_targets(profile,table):
    if not isinstance(profile,dict) or set(profile)!={'nodes_s','values_uT'}:
        raise ValueError('segment_magnetic_targets requires nodes_s and values_uT')
    nodes=np.asarray(profile['nodes_s'],float);values=profile['values_uT']
    if (nodes.ndim!=1 or len(nodes)<2 or not np.isfinite(nodes).all()
            or nodes[0]!=0 or nodes[-1]!=1 or np.any(np.diff(nodes)<=0)
            or not isinstance(values,list) or len(values)!=len(nodes)-1):
        raise ValueError('invalid segment_magnetic_targets boundaries')
    for value in values:
        if value is not None:
            if isinstance(value,bool) or not isinstance(value,(int,float)):
                raise ValueError('segment target must be numeric or inherited')
            lookup_depth_m(table,[value])
    return nodes,values

def apply_segment_targets(progress,inherited,profile,table):
    nodes,values=validate_segment_targets(profile,table)
    q=np.asarray(progress,float);result=np.asarray(inherited,float).copy()
    owner=np.clip(np.searchsorted(nodes,q,side='right')-1,0,len(values)-1)
    for k,value in enumerate(values):
        if value is not None:result[owner==k]=float(value)
    return result
