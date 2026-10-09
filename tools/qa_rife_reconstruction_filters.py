"""Offline filter experiment; known motion isolates reconstruction from flow."""
import argparse
import json
from pathlib import Path
import numpy as np
from qa_rife_texture_translation import render
from evaluate_rife_patch_motion import sample_cubic


def sample_lanczos(image,x,y,limit=False):
    h,w=image.shape[:2]
    ix=np.floor(x).astype(int);iy=np.floor(y).astype(int)
    offsets=range(-2,4)
    def weights(t):
        raw=np.stack([np.sinc(t-k)*np.sinc((t-k)/3) for k in offsets])
        return raw/raw.sum(axis=0)
    wx=weights(x-ix);wy=weights(y-iy)
    result=np.zeros((*x.shape,image.shape[2]))
    taps=[]
    for j,dy in enumerate(offsets):
        for i,dx in enumerate(offsets):
            tap=image[np.clip(iy+dy,0,h-1),np.clip(ix+dx,0,w-1)]
            result+=tap*(wx[i]*wy[j])[...,None]
            if limit=='plateau':taps.append(tap)
    if limit=='plateau':
        taps=np.stack(taps)
        lo=taps.min(0);hi=taps.max(0)
        # Only flat plateaus: every source component must be within one
        # quantization level of a footprint extremum. No candidate/reference
        # participates. Smoothly varying textures retain the sharp filter.
        plateau=(np.minimum(abs(taps-lo),abs(taps-hi))<=1).all(axis=(0,3))
        neighbors=np.stack([image[np.clip(iy+dy,0,h-1),np.clip(ix+dx,0,w-1)]
                            for dy in (0,1) for dx in (0,1)])
        result=np.where(plateau[...,None],
                        np.clip(result,neighbors.min(0),neighbors.max(0)),result)
    elif limit:
        # Local range clamp is a hypothesis, not an accepted artifact fix.
        neighbors=np.stack([image[np.clip(iy+dy,0,h-1),np.clip(ix+dx,0,w-1)]
                            for dy in (0,1) for dx in (0,1)])
        result=np.clip(result,neighbors.min(0),neighbors.max(0))
    return np.clip(result,0,255)


def evaluate():
    methods={'cubic':sample_cubic,'lanczos3':sample_lanczos,
             'lanczos3_plateau':lambda im,x,y:sample_lanczos(im,x,y,'plateau'),
             'lanczos3_limited':lambda im,x,y:sample_lanczos(im,x,y,True)}
    rows=[]
    for velocity in ((2,0),(3,0),(-3,0),(0,3),(3,3)):
        for frequency in (.06,.15,.25,.38):
            left=render(0,velocity,frequency);right=render(1,velocity,frequency)
            truth=render(.5,velocity,frequency);y,x=np.mgrid[:48,:80]
            scores={}
            for name,method in methods.items():
                candidate=(method(left,x-velocity[0]/2,y-velocity[1]/2)+
                           method(right,x+velocity[0]/2,y+velocity[1]/2))/2
                error=abs(candidate-truth)[8:-8,8:-8]
                scores[name]=dict(mae=float(error.mean()),maximum=float(error.max()))
            rows.append(dict(velocity=velocity,frequency=frequency,scores=scores))
    y,x=np.mgrid[:24,:64]
    left=np.repeat(np.where(x<28,30.,220.)[...,None],3,axis=2)
    truth=np.repeat((30+190*np.clip(x+.5-29,0,1))[...,None],3,axis=2)
    edges={}
    for name,method in methods.items():
        candidate=method(left,x-1.5,y)
        area=candidate[8:-8,20:38]
        edges[name]=dict(mae=float(abs(candidate-truth)[8:-8,20:38].mean()),
                         undershoot=float(max(0,30-area.min())),
                         overshoot=float(max(0,area.max()-220)))
    return dict(textures=rows,hard_edge=edges,production_changed=False,
                artifact_free_qualified=False,
                scope='Known-motion interior reconstruction only; no inference, disocclusion or GPU timing.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();report=evaluate()
    with args.output.open('x') as f:json.dump(report,f,indent=2)
    print(json.dumps(dict(finest_diagonal=report['textures'][-1],hard_edge=report['hard_edge']),indent=2))
