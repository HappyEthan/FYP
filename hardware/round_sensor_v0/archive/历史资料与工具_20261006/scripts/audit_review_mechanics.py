#!/usr/bin/env python3
"""Bounded current-source body/height screen using retained manufacturer dimensions."""
import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
from check_pcb_a5 import parse, xy, rect, distance


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pcb',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();d,parts,pads,_=parse(a.pcb);assert len(parts)==43
    centre=xy(4110.551,3092.977)
    # Current source is rotated relative to the September 16 drawing. Register
    # the connector to this actual footprint; do not reuse old coordinates.
    j=parts['J1']['items'];stakes=[xy(v[2],v[3]) for v in j if v[0]=='PAD' and v[8]=='SH']
    jx=sum(v[0] for v in stakes)/4
    face=max(v[1] for v in stakes)+2.6
    jy=face-7.35/2
    row=xy(*next(v[2:4] for v in j if v[0]=='PAD' and v[8]=='A1'))[1]
    nh=[xy(v[1],v[2])[1] for v in j if v[0]=='HOLE']
    residuals={'row_mm':abs(row-(face-7.355)),'NPTH_mm':max(abs(y-(face-6.28)) for y in nh)}
    assert max(residuals.values())<.001
    # w/h follow actual pin rows in this frozen source. Heights from retained
    # manufacturer drawings; they are not extracted from a model z-offset.
    specs={
        'J1':([8.94,7.35,3.31],[9.09,7.5,3.46],'GCT usb4105.pdf p1'),
        'U1':([7,7,.96],[7.1,7.1,1.06],'Espressif esp32-s3-pico-1.pdf p30'),
        'U2':([2.5,2,.355],[2.6,2.1,.4],'Melexis mlx90393.pdf p39'),
        'U3':([3,2.5,.83],[3.1,2.6,.86],'ST DS12814 Rev4 p160, retained mechanical review; live PDF fetch timed out'),
        'U4':([.922,1.155,.55],[.947,1.180,.588],'SGMICRO sgm40567.pdf p14'),
        'U5':([2,2,.75],[2.1,2.1,.8],'TI tlv755p.pdf DRV0006A'),
        'U6':([1,.8,.47],[1.05,.85,.5],'TI tpd2eusb30a.pdf DRT; excludes terminal outline'),
        'Q1':([1,.6,.48],[1.05,.65,.53],'LRC lp0404n3t5g.pdf p6'),
        'D4':([1,.6,.48],[1.05,.65,.53],'LRC lmbr4010bst5g.pdf p3'),
        'ANT1':([3,3.1,1.25],None,'Hirose_U.FL_catalog.pdf p12; unmated bounding envelope'),
        'SW2':([1.6,2.6,.53],[1.7,2.7,.63],'Panasonic panasonic_evpbb.pdf p2; terminals extend length to 3.0 +/-0.1'),
        'SW3':([1.6,2.6,.53],[1.7,2.7,.63],'Panasonic panasonic_evpbb.pdf p2; terminals extend length to 3.0 +/-0.1'),
        'C20':([2,1.25,1.25],[2.2,1.45,1.45],'Murata GRM21BR61A226ME44-01A.pdf')}
    bodies={};models={}
    for ref,p in parts.items():
        sv=[json.loads(v[1])['attrs'] for v in p['items'] if v[0]=='SVGNODE']
        models[ref]=[{'title':s.get('title'),'uuid':s.get('uuid'),'xy_size_mm':[float(s['c_width'])*.254,float(s['c_height'])*.254],
                      'rotation':s.get('c_rotation'),'z_offset':s.get('z'),'origin':s.get('c_origin')} for s in sv]
        if ref in {'J2','J4','SW1','C30','C31'}:continue
        pin=[v for v in p['items'] if v[0]=='PAD']
        if ref in specs:nom,mx,source=specs[ref]
        else:
            nom=[1,.6,.5] if ref.startswith('D') else [1,.5,.5]
            mx=[1.05,.55,.55] if ref in {'C1','C6','C7','C9','C10'} else None
            source='Retained Murata 0402 drawing' if mx else 'Nominal package screen; tolerance/placement not simulated'
            q,r=[xy(v[2],v[3]) for v in pin[:2]]
            if abs(q[1]-r[1])>abs(q[0]-r[0]):
                nom=[nom[1],nom[0],nom[2]]
                if mx:mx=[mx[1],mx[0],mx[2]]
        c=(jx,jy) if ref=='J1' else p['center']
        if ref=='ANT1':c=(c[0],c[1]-.25)
        bodies[ref]={'side':p['layer'],'source_center_mm':c,'nominal_mm':nom,'maximum_mm':mx,'source':source,
                     'polygon':rect(*c,*nom[:2]),'max_polygon':rect(*c,*mx[:2]) if mx else None}
    gaps=[]
    for (ra,x),(rb,y) in itertools.combinations(bodies.items(),2):
        if x['side']!=y['side']:continue
        gap=distance(x['polygon'],y['polygon'])
        if gap<.3:
            gaps.append({'refs':[ra,rb],'nominal_gap_mm':gap,
                         'maximum_body_gap_mm':distance(x['max_polygon'],y['max_polygon']) if x['max_polygon'] and y['max_polygon'] else None})
    usb=bodies['J1'];rad=max(math.dist(v,centre) for v in usb['polygon'])
    report={'date':'2026-10-04','source':{'path':str(a.pcb.resolve()),'sha256':hashlib.sha256(a.pcb.read_bytes()).hexdigest()},
      'status':'Bounded body/height design review; not enclosure fit or manufacturing acceptance',
      'model_counts':{'attached':sum(bool(m) for m in models.values()),'positions':43},'models':models,
      'board_candidate_mm':{'diameter':18,'thickness':.8,'thickness_example_range':[.7,.9]},
      'USB':{'face_source_y_mm':face,'centre_source_mm':[jx,jy], 'registration_residuals':residuals,
             'front_overhang_from_circle_mm':face-(centre[1]+9),'corner_radius_mm':rad,
             'unbroken_concentric_cylinder_minimum_ID_mm':2*rad,'nominal_height_mm':3.31,'drawing_height_upper_mm':3.46,
             'stake_option_mm':.6,'note':'-060 is stake length; check solder fillet and slot plating at 0.8mm. Cylinder figure is not a pen diameter recommendation.'},
      'height_envelope_without_cable_or_wires_mm':{'nominal_pcb_plus_USB_nominal_plus_IMU_max':.8+3.31+.86,
                                                'upper_example':.9+3.46+.86},
      'bodies':bodies,'same_side_gaps_below_0_3mm':sorted(gaps,key=lambda g:g['nominal_gap_mm']),
      'open_physical_items':['USB plug tail and insertion path through pen opening','actual mating height and cable bend of FXP75.07.0045B to U.FL',
         'battery, soldered-wire height, insulation and strain relief','button actuator clearance and travel','printing and mounting tolerances'],
      'limits':['3D z is model offset, not actual height. Native JSON contains projected model outline, not full 3D solid.',
                'USB model is approximate; real connector dimensions above control the envelope.',
                'Same-side rectangles are nominal screens. Placement tolerance, paste and rework access not included.',
                'No enclosure or battery selection added to the task.']}
    assert len(bodies)==38 and report['model_counts']['attached']==40
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('model_counts','USB','height_envelope_without_cable_or_wires_mm','same_side_gaps_below_0_3mm')},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
