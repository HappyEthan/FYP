"""Offline inference from one complete stroke; no true label is an input.

Requires raw dBx/dBy, sensor clock and >=100 pre-stroke valid samples, or
already-preprocessed 128-point feature vectors via --features-npy.
"""
import argparse
import csv
import io
import json
from pathlib import Path
import zipfile
import joblib
import numpy as np
from analysis_utils import LABELS,prepare_sensor,extract_stroke


def main():
    p=argparse.ArgumentParser(description=__doc__)
    source=p.add_mutually_exclusive_group(required=True)
    source.add_argument('--sensor-csv',type=Path)
    source.add_argument('--archive',type=Path)
    source.add_argument('--features-npy',type=Path,help='128 preprocessed delta-uT values, not raw amplitude')
    p.add_argument('--seq-start',type=int);p.add_argument('--seq-end',type=int)
    p.add_argument('--stroke',type=int,choices=range(1,6),help='archive window selector only; never a model feature')
    p.add_argument('--model',type=Path,default=Path(__file__).resolve().parent/'model.joblib')
    args=p.parse_args()
    if args.features_npy:
        feature=np.load(args.features_npy,allow_pickle=False)
        if feature.shape!=(128,) or not np.all(np.isfinite(feature)):p.error('expected one finite 128-point vector')
        baseline=None
    else:
        if args.archive:
            if args.stroke is None:p.error('--archive requires --stroke')
            with zipfile.ZipFile(args.archive) as z:
                sensor_text=z.read('sensor.csv').decode()
                ticks=[json.loads(l) for l in z.read('control.jsonl').decode().splitlines() if l.strip()]
            ticks=[r for r in ticks if r.get('phase')==f'measure_{args.stroke-1:02d}']
            if not ticks:p.error('no matching measurement window')
            first,last=int(ticks[0]['sample_seq']),int(ticks[-1]['sample_seq'])
        else:
            if args.seq_start is None or args.seq_end is None:p.error('--sensor-csv requires --seq-start and --seq-end')
            sensor_text=args.sensor_csv.read_text(encoding='utf-8-sig');first,last=args.seq_start,args.seq_end
        rows=list(csv.DictReader(io.StringIO(sensor_text)))
        feature,baseline,_=extract_stroke(prepare_sensor(rows),first,last)
    model=joblib.load(args.model)
    pred=int(model.predict(feature[None])[0]);scores=model.decision_function(feature[None])[0]
    print(json.dumps(dict(predicted_label=LABELS[pred],predicted_class_id=pred,
        decision_scores_not_probabilities={LABELS[int(c)]:float(s) for c,s in zip(model.classes_,scores)},
        reference_baseline_uT=baseline,scope='one of five known classes; no unknown rejection'),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
