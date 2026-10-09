"""Offline bidirectional patch-motion candidate. Never called by the renderer."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from qa_refine_native_flow import sample
from evaluate_rife_temporal_stationary import quality_scores


def box_mean(values, radius):
    padded = np.pad(values, radius, mode='edge')
    summed = np.pad(padded, ((1,0),(1,0))).cumsum(0).cumsum(1)
    size = 2*radius+1
    return (summed[size:,size:]-summed[:-size,size:]-
            summed[size:,:-size]+summed[:-size,:-size])/(size*size)


def sample_cubic(image,x,y):
    """Experimental sharper image reconstruction; flow sampling stays linear."""
    h,w=image.shape[:2]
    x=np.clip(x,0,w-1);y=np.clip(y,0,h-1)
    ix=np.floor(x).astype(int);iy=np.floor(y).astype(int)
    def weights(t):
        return (-.5*t+t*t-.5*t**3,1-2.5*t*t+1.5*t**3,
                .5*t+2*t*t-1.5*t**3,-.5*t*t+.5*t**3)
    wx,wy=weights(x-ix),weights(y-iy)
    result=np.zeros((*x.shape,image.shape[2]))
    for j in range(4):
        for i in range(4):
            result+=image[np.clip(iy+j-1,0,h-1),np.clip(ix+i-1,0,w-1)]*(wy[j]*wx[i])[...,None]
    return np.clip(result,0,255)


def match(source, peer, search=6, radius=2, consensus=False):
    h,w=source.shape[:2]; y,x=np.mgrid[:h,:w]
    best=np.full((h,w),np.inf); second=best.copy(); flow=np.zeros((h,w,2))
    for dy in range(-search,search+1):
        for dx in range(-search,search+1):
            error=abs(source-sample(peer,x+dx,y+dy)).mean(2)
            cost=box_mean(error,radius)
            valid=(x+dx>=radius)&(x+dx<w-radius)&(y+dy>=radius)&(y+dy<h-radius)
            cost=np.where(valid,cost,np.inf)
            take=cost<best
            second=np.where(take,best,np.minimum(second,cost))
            best=np.where(take,cost,best)
            flow[take]=[dx,dy]
    confidence=np.isfinite(best)&(best<4)&(second>best+1)
    if consensus and confidence.sum()>=100:
        vectors,counts=np.unique(flow[confidence],axis=0,return_counts=True)
        index=int(np.argmax(counts))
        if counts[index]/confidence.sum()>.7:
            dx,dy=vectors[index]
            residual=abs(source-sample(peer,x+dx,y+dy)).max(2)
            cost=box_mean(residual,radius)
            # A dominant camera proposal is not permission to cross an edge,
            # invent out-of-frame pixels, or replace a confident object vector.
            take=(~confidence)&(residual<2)&(cost<2)&(cost<=best+.01)
            take &= (x+dx>=0)&(x+dx<w)&(y+dy>=0)&(y+dy<h)
            flow[take]=[dx,dy];confidence[take]=True
    return flow,confidence


def synthesize(left,right,generated,sharper=False,consensus=False,search=6):
    forward,fc=match(left,right,search=search,consensus=consensus); backward,bc=match(right,left,search=search,consensus=consensus)
    h,w=left.shape[:2]; y,x=np.mgrid[:h,:w]
    def warp(image,flow,confidence):
        sx=x.astype(float);sy=y.astype(float)
        for _ in range(4):
            f=sample(flow,sx,sy);sx=x-.5*f[...,0];sy=y-.5*f[...,1]
        f=sample(flow,sx,sy)
        valid=(sx>=0)&(sx<=w-1)&(sy>=0)&(sy<=h-1)
        valid &= sample(confidence[...,None].astype(float),sx,sy)[...,0]>.999
        valid &= np.hypot(sx+.5*f[...,0]-x,sy+.5*f[...,1]-y)<.1
        return (sample_cubic(image,sx,sy) if sharper else sample(image,sx,sy)),f,valid
    a,fa,va=warp(left,forward,fc);b,fb,vb=warp(right,backward,bc)
    mask=va&vb&(np.linalg.norm(fa+fb,axis=2)<.25)&(abs(a-b).max(2)<4)
    # Do not overwrite model output across independently moving patch edges.
    # Neighborhood variance checks motion only, never the withheld reference.
    for flow in (fa,fb):
        for channel in range(2):
            mean=box_mean(flow[...,channel],2)
            variance=box_mean(flow[...,channel]**2,2)-mean**2
            mask &= variance<.01
    # Require actual motion, not a stationary-copy shortcut.
    mask &= np.linalg.norm(fa,axis=2)>=1
    candidate=generated.copy();candidate[mask]=(a[mask]+b[mask])/2
    return candidate,mask


def evaluate(case,inference,sharper=False,consensus=False):
    metadata=json.loads((inference/'inference.json').read_text())
    m=metadata['input_manifest'];h,w=m['height'],m['width']
    def read(path,sha=None):
        data=path.read_bytes()
        if sha and hashlib.sha256(data).hexdigest()!=sha: raise ValueError('hash mismatch')
        return np.frombuffer(data,np.uint8).reshape(h,w,4)[...,:3].astype(float)
    left=read(case/'native-left.rgba',m['inputs']['left.rgba']['sha256'])
    right=read(case/'native-right.rgba',m['inputs']['right.rgba']['sha256'])
    generated=read(inference/'generated.rgba',metadata['generated_sha256'])
    candidate,mask=synthesize(left,right,generated,sharper=sharper,consensus=consensus)
    reference=read(case/'withheld-reference.rgba')
    old=abs(generated-reference).max(2);new=abs(candidate-reference).max(2)
    return dict(selected=int(mask.sum()),improved=int((new<old).sum()),
                worsened=int((new>old).sum()),baseline=quality_scores(left,right,reference,generated),
                candidate=quality_scores(left,right,reference,candidate),production_changed=False)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('case',type=Path);p.add_argument('inference',type=Path)
    p.add_argument('--sharper',action='store_true')
    p.add_argument('--consensus',action='store_true')
    args=p.parse_args();print(json.dumps(evaluate(args.case,args.inference,args.sharper,args.consensus),indent=2))
