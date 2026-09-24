#!/usr/bin/env python3
"""Generate synthetic V3 targets without experiment data or Z. Offline only."""
import argparse
from pathlib import Path
import numpy as np
from brushbot.target_strokeplan import Stroke, StrokePlan, FEATURE

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'runs/plans/target_v3.npz'
TARGETS_UT=[30.,70.,30.]
LENGTH_MM=200.
SPEED_MM_S=10.
ACCEL_MM_S2=50.
FILTER_DEFINITION={'kind':'ema','alpha':.3}


def generate(*, targets_uT, length_mm=LENGTH_MM, speed_mm_s=SPEED_MM_S, filter_definition=None):
    if (not np.isfinite([length_mm,speed_mm_s]).all() or length_mm<=0 or speed_mm_s<=0):
        raise ValueError('length/speed must be finite and positive')
    targets=np.asarray(targets_uT,float)
    if targets.ndim != 1 or not len(targets) or not np.isfinite(targets).all() or np.any(targets<0):
        raise ValueError('targets must be finite nonnegative values')
    length, speed, accel=length_mm/1000,speed_mm_s/1000,ACCEL_MM_S2/1000
    ramp=min(speed/accel,np.sqrt(length/accel))
    peak=accel*ramp
    duration=length/peak+ramp
    # All support times lie on the 20 ms grid; last interval is a terminal hold.
    t=np.arange(int(np.ceil(duration/.02))+1)*.02
    tau=np.minimum(t,duration)
    x=np.where(tau<ramp,.5*accel*tau**2,
               np.where(tau<=duration-ramp,peak*(tau-.5*ramp),length-.5*accel*(duration-tau)**2))
    s=np.clip(x/length,0,1)
    g=np.interp(s,np.linspace(0,1,len(targets)),targets)
    plan=StrokePlan([Stroke(s,np.column_stack([s*length,np.zeros(len(s))]),t,g)],
        dict(source='synthetic',coordinate_frame='paper',feature=FEATURE,
             filter_definition=dict(FILTER_DEFINITION if filter_definition is None else filter_definition),
             description='Synthetic +X target; no measured labels or Z',
             cruise_speed_mm_s=speed_mm_s))
    plan.validate()
    return plan


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=OUTPUT)
    parser.add_argument('--targets-ut',nargs='+',type=float,default=TARGETS_UT)
    parser.add_argument('--length-mm',type=float,default=LENGTH_MM)
    parser.add_argument('--speed-mm-s',type=float,default=SPEED_MM_S)
    args=parser.parse_args()
    plan=generate(targets_uT=args.targets_ut,length_mm=args.length_mm,speed_mm_s=args.speed_mm_s)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    plan.save(args.output)
    print('Saved target-only V3:',args.output)


if __name__=='__main__': main()
