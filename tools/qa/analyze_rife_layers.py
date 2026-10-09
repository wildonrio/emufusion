#!/usr/bin/env python3
"""Rank measured model layers; diagnostic timings are not acceptance evidence."""
import argparse
import json
from pathlib import Path


def analyze(log, parameters):
    lines=parameters.splitlines()
    if lines[0].strip()!='7767517': raise ValueError('not ncnn parameters')
    count=int(lines[1].split()[0])
    layers=[line.split() for line in lines[2:] if line.strip()]
    if len(layers)!=count: raise ValueError('layer count mismatch')
    measured={}
    for line in log.splitlines():
        if not line.startswith('RIFE_GPU_LAYER,'): continue
        _,index,duration=line.split(',')
        index=int(index); duration=float(duration)
        if index in measured or not 0<=index<count or duration<0:
            raise ValueError('invalid or duplicate layer measurement')
        measured[index]={'index':index,'type':layers[index][0],
                         'name':layers[index][1],'milliseconds':duration/1e6}
    if not measured: raise ValueError('no per-layer GPU measurements')
    ranked=sorted(measured.values(),key=lambda row:row['milliseconds'],reverse=True)
    return {'measured_layers':len(ranked),'model_layers':count,
            'sum_measured_ms':sum(row['milliseconds'] for row in ranked),
            'slowest_layers':ranked[:20],'performance_qualified':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log',type=Path)
    parser.add_argument('parameters',type=Path)
    args=parser.parse_args()
    print(json.dumps(analyze(args.log.read_text(),args.parameters.read_text()),indent=2))
