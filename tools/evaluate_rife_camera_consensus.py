"""Offline camera-consensus correction; no withheld reference in synthesis."""
import argparse
import json
from pathlib import Path
import numpy as np
from evaluate_rife_patch_motion import match, sample_cubic, box_mean
from evaluate_rife_stationary_candidate import preserve_agreeing_neighborhoods
from evaluate_rife_temporal_stationary import quality_scores


def camera_motion(left, right):
    def dominant(a,b):
        flow,valid=match(a,b)
        if valid.sum()<100:
            return None
        vectors,counts=np.unique(flow[valid],axis=0,return_counts=True)
        i=int(np.argmax(counts))
        return vectors[i] if counts[i]/valid.sum()>.9 else None
    f,b=dominant(left,right),dominant(right,left)
    if f is None or b is None or np.linalg.norm(f+b)>.01 or np.linalg.norm(f)<1:
        return None
    return f


def cubic_support(x,y,width,height,radius=2):
    """Integer samples use one texel; fractional samples need four taps."""
    def axis(value,size):
        integer=abs(value-np.rint(value))<1e-8
        floor=np.floor(value)
        return np.where(integer,(value>=0)&(value<size),(floor>=radius-1)&(floor+radius<size))
    return axis(x,width)&axis(y,height)


def cubic_mask_overlap(mask,x,y,radius=2):
    """Reject every nonzero reconstruction tap that intersects a fixed layer."""
    h,w=mask.shape;ix=np.floor(x).astype(int);iy=np.floor(y).astype(int)
    integer_x=abs(x-ix)<1e-8;integer_y=abs(y-iy)<1e-8
    overlap=np.zeros(x.shape,bool)
    for dy in range(1-radius,radius+1):
        for dx in range(1-radius,radius+1):
            active=(~integer_x if dx!=0 else np.ones(x.shape,bool))
            active &= (~integer_y if dy!=0 else np.ones(y.shape,bool))
            overlap |= active&mask[np.clip(iy+dy,0,h-1),np.clip(ix+dx,0,w-1)]
    return overlap


def _correct_cubic(left, right, generated, following=None, boundary_lookahead=False,
            static_mask=None, previous=None):
    f=camera_motion(left,right)
    empty=np.zeros(left.shape[:2],bool)
    if f is None:
        return generated.copy(),empty
    h,w=left.shape[:2];y,x=np.mgrid[:h,:w]
    a=sample_cubic(left,x-f[0]/2,y-f[1]/2)
    z=sample_cubic(right,x+f[0]/2,y+f[1]/2)
    # Bilateral correspondence must support this proposal at the midpoint.
    valid=(abs(a-z).max(2)<4)
    valid &= (x-abs(f[0])/2>=1)&(x+abs(f[0])/2<w-2)
    valid &= (y-abs(f[1])/2>=1)&(y+abs(f[1])/2<h-2)
    # Do not apply a global camera vector to an unchanged local overlay.
    _,stationary=preserve_agreeing_neighborhoods(left,right,generated,2)
    valid &= ~stationary
    result=generated.copy();result[valid]=(a[valid]+z[valid])/2
    if not boundary_lookahead or following is None:
        return result,valid
    if following.shape!=left.shape:
        raise ValueError('following geometry mismatch')
    next_motion=camera_motion(right,following)
    if next_motion is None or np.linalg.norm(next_motion-f)>.01:
        return result,valid
    # This experiment requires equally spaced sources. A withheld-reference
    # sequence with a half-interval lookahead must not be supplied here.
    left_support=cubic_support(x-f[0]/2,y-f[1]/2,w,h)
    right_support=cubic_support(x+f[0]/2,y+f[1]/2,w,h)
    if static_mask is not None:
        if static_mask.shape!=left.shape[:2]: raise ValueError('static mask geometry mismatch')
        stationary |= static_mask
        left_support &= ~cubic_mask_overlap(static_mask,x-f[0]/2,y-f[1]/2)
        right_support &= ~cubic_mask_overlap(static_mask,x+f[0]/2,y+f[1]/2)
        result=generated.copy();valid=empty.copy()
    both=left_support&right_support&(abs(a-z).max(2)<4)&~stationary
    result[both]=(a[both]+z[both])/2
    future=sample_cubic(following,x+1.5*f[0],y+1.5*f[1])
    future_support=cubic_support(x+1.5*f[0],y+1.5*f[1],w,h)
    if static_mask is not None:
        future_support &= ~cubic_mask_overlap(static_mask,x+1.5*f[0],y+1.5*f[1])
    def consistent(first,second,support):
        delta=abs(first-second).max(2)
        weight=box_mean(support.astype(float),2)
        error=box_mean(np.where(support,delta,0),2)/np.maximum(weight,1e-9)
        return support&(delta<4)&(weight>=.4)&(error<4)
    entering=(~left_support)&right_support&future_support&~stationary
    entering &= consistent(z,future,right_support&future_support)
    # This is a spatially shifted sample at phase 0.5, not a held endpoint.
    result[entering]=z[entering]
    valid |= both|entering
    if previous is not None:
        if previous.shape!=left.shape: raise ValueError('previous geometry mismatch')
        old_motion=camera_motion(previous,left)
        if old_motion is not None and np.linalg.norm(old_motion-f)<=.01:
            past=sample_cubic(previous,x-1.5*f[0],y-1.5*f[1])
            past_support=cubic_support(x-1.5*f[0],y-1.5*f[1],w,h)
            if static_mask is not None:
                past_support &= ~cubic_mask_overlap(static_mask,x-1.5*f[0],y-1.5*f[1])
            leaving=left_support&(~right_support)&past_support&~stationary
            leaving &= consistent(a,past,left_support&past_support)
            result[leaving]=a[leaving];valid |= leaving
    return result,valid


def correct(left,right,generated,following=None,boundary_lookahead=False,
            static_mask=None,previous=None,reconstruction='cubic'):
    if reconstruction not in ('cubic','plateau'):
        raise ValueError('unsupported reconstruction')
    result,selected=_correct_cubic(left,right,generated,following,
                                  boundary_lookahead,static_mask,previous)
    if reconstruction=='cubic':return result,selected
    from qa_rife_reconstruction_filters import sample_lanczos
    motion=camera_motion(left,right)
    if motion is None:return result,selected
    h,w=left.shape[:2];y,x=np.mgrid[:h,:w]
    ax=x-motion[0]/2;ay=y-motion[1]/2
    bx=x+motion[0]/2;by=y+motion[1]/2
    supported=cubic_support(ax,ay,w,h,3)&cubic_support(bx,by,w,h,3)
    _,stationary=preserve_agreeing_neighborhoods(left,right,generated,2)
    fixed=stationary if static_mask is None else stationary|static_mask
    supported &= ~fixed
    supported &= ~cubic_mask_overlap(fixed,ax,ay,3)
    supported &= ~cubic_mask_overlap(fixed,bx,by,3)
    a=sample_lanczos(left,ax,ay,'plateau')
    b=sample_lanczos(right,bx,by,'plateau')
    supported &= selected&(abs(a-b).max(2)<4)
    # Retain established reconstruction for one-sided/occluded boundaries.
    # Wider support is only authorized for bilateral same-layer agreement.
    result[supported]=(a[supported]+b[supported])/2
    return result,selected


if __name__=='__main__':
    import hashlib
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('case',type=Path);p.add_argument('inference',type=Path)
    args=p.parse_args();meta=json.loads((args.inference/'inference.json').read_text())
    m=meta['input_manifest'];shape=(m['height'],m['width'],4)
    def read(path,sha=None):
        data=path.read_bytes()
        if sha and hashlib.sha256(data).hexdigest()!=sha: raise ValueError('hash mismatch')
        return np.frombuffer(data,np.uint8).reshape(shape)[...,:3].astype(float)
    left=read(args.case/'native-left.rgba',m['inputs']['left.rgba']['sha256'])
    right=read(args.case/'native-right.rgba',m['inputs']['right.rgba']['sha256'])
    generated=read(args.inference/'generated.rgba',meta['generated_sha256'])
    candidate,mask=correct(left,right,generated)
    reference=read(args.case/'withheld-reference.rgba')
    report=quality_scores(left,right,reference,candidate)
    print(json.dumps(dict(selected=int(mask.sum()),quality=report,production_changed=False),indent=2))
