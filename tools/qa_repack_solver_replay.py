"""Diagnostic photo/cycle revalidation; NOT the production validity shader."""
import argparse
from pathlib import Path
import numpy as np
from analyze_dense_flow_merging import read_dump
from prepare_held_out_case import write_dump
from qa_refine_native_flow import sample


def decode(data,w,h):
    a=np.frombuffer(data,np.uint8).reshape(h,w,4).astype(np.int32)
    q=np.stack([a[...,0]*256+a[...,1],a[...,2]*256+a[...,3]],2)
    return np.where(q>=32768,q-65536,q)/256


def repack(meta,planes,raw):
    planes=dict(planes);w,h=meta['history_width'],meta['history_height']
    flows=[];frames=[]
    for d in range(2):
        fw,fh,_=planes[f'final{d}'];flows.append(decode(raw[d],fw,fh))
        iw,ih,data=planes['previousFull' if d==0 else 'currentFull']
        frames.append(np.frombuffer(data,np.uint8).reshape(ih,iw,4)[...,:3].astype(float))
    for d in range(2):
        flow=flows[d];fh,fw=flow.shape[:2];y,x=np.mgrid[:fh,:fw]
        sx=(x+.5)*w/fw-.5;sy=(y+.5)*h/fh-.5;qx=sx+flow[...,0];qy=sy+flow[...,1]
        rh,rw=flows[1-d].shape[:2]
        cycle=np.linalg.norm(flow+sample(flows[1-d],(qx+.5)*rw/w-.5,(qy+.5)*rh/h-.5),axis=2)
        photo=np.max(abs(sample(frames[1-d],sx,sy)-sample(frames[d],qx,qy)),axis=2)
        vw,vh,data=planes[f'validated{d}']
        if (vw,vh)!=(fw,fh):raise ValueError('confidence geometry mismatch')
        ceiling=np.frombuffer(data,np.uint8).reshape(fh,fw,4)[...,2]
        conf=np.minimum(ceiling,255*np.clip((40-photo)/32,0,1)*np.clip((2-cycle)/1.5,0,1))
        conf*=((qx>=0)&(qx<=w-1)&(qy>=0)&(qy<=h-1))
        f=flow/meta['flow_limits'][0]
        rg=np.clip(np.round(128+127*np.sign(f)*np.sqrt(abs(f))),0,255).astype(np.uint8)
        valid=np.concatenate([rg,np.round(conf)[...,None].astype(np.uint8),np.zeros((fh,fw,1),np.uint8)],2)
        planes[f'final{d}']=(fw,fh,raw[d]);planes[f'validated{d}']=(fw,fh,valid.tobytes())
    return planes


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('capture',type=Path)
    p.add_argument('replay',type=Path);p.add_argument('variant',choices=['baseline','guarded']);p.add_argument('output',type=Path)
    args=p.parse_args();meta,planes=read_dump(args.capture)
    raw=[(args.replay/f'{args.variant}-{d}.rgba').read_bytes() for d in range(2)]
    write_dump(args.output,meta,repack(meta,planes,raw))
