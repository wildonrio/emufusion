"""Oracle-flow ablation for controlled pan ONLY; never a gameplay estimator."""
import argparse
from pathlib import Path
import numpy as np
from analyze_dense_flow_merging import read_dump
from prepare_held_out_case import write_dump


def exact_planes(meta, planes, displacement=4):
    planes=dict(planes)
    w,h=meta['history_width'],meta['history_height']
    for d,dx in [(0,displacement),(1,-displacement)]:
        q=int(round(dx*256))&65535
        raw=bytes([q>>8,q&255,0,0])*(w*h)
        rg=int(np.clip(round(128+127*np.sign(dx)*np.sqrt(abs(dx)/meta['flow_limits'][0])),0,255))
        planes[f'final{d}']=(w,h,raw)
        planes[f'validated{d}']=(w,h,bytes([rg,128,255,0])*(w*h))
    return planes


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();meta,planes=read_dump(args.input)
    write_dump(args.output,meta,exact_planes(meta,planes))
