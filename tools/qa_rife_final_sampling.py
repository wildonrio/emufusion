"""Reconstruct pinned flow/mask with alternate filters; no new network inference."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from qa_refine_native_flow import sample
from evaluate_rife_patch_motion import sample_cubic
from qa_rife_reconstruction_filters import sample_lanczos


def sample_nearest(image, x, y):
    """Host-only ablation: retain motion/mask, remove bilinear spatial blending."""
    ix=np.clip(np.floor(x+.5).astype(np.int64),0,image.shape[1]-1)
    iy=np.clip(np.floor(y+.5).astype(np.int64),0,image.shape[0]-1)
    return image[iy,ix]


def evaluate(root):
    methods={'linear':sample,'nearest':sample_nearest,'cubic':sample_cubic,
             'plateau':lambda image,x,y:sample_lanczos(image,x,y,'plateau')}
    regions={'character':(112,140,145,180),'lightning':(54,25,98,179),'whole':(0,0,256,192)}
    rows=[];history={name:[] for name in methods};truths=[]
    for seq in (3818,3819,3820):
        folder=root/f'rife-motion-{seq}-20260917'
        meta=json.loads((folder/'inference.json').read_text())
        case=root/'rife-camera-sequence-2026-09-16'/str(seq)
        def checked(path,sha):
            data=path.read_bytes()
            if hashlib.sha256(data).hexdigest()!=sha:raise ValueError('hash mismatch')
            return data
        frames=[]
        for side in ('left','right'):
            data=checked(case/f'native-{side}.rgba',meta['input_manifest']['inputs'][side+'.rgba']['sha256'])
            frames.append(np.frombuffer(data,np.uint8).reshape(192,256,4)[::-1,:,:3].astype(float))
        checked(folder/'motion.npz',meta['motion_dump']['sha256'])
        with np.load(folder/'motion.npz',allow_pickle=False) as d:
            flow=d['flow'];mask=d['mask']
        y,x=np.mgrid[:192,:256]
        candidates={}
        for name,method in methods.items():
            a=method(frames[0],x+flow[...,0],y+flow[...,1])
            b=method(frames[1],x+flow[...,2],y+flow[...,3])
            candidates[name]=np.clip(np.rint(a*mask+b*(1-mask)),0,255)
        original=np.frombuffer(checked(folder/'generated.rgba',meta['generated_sha256']),np.uint8).reshape(192,256,4)[::-1,:,:3]
        reconstruction_error=float(abs(candidates['linear']-original).max())
        if reconstruction_error>1:raise ValueError('linear baseline fails to reproduce model')
        truth=np.frombuffer((case/'withheld-reference.rgba').read_bytes(),np.uint8).reshape(192,256,4)[::-1,:,:3].astype(float)
        truths.append(truth);scores={}
        for name,candidate in candidates.items():
            history[name].append(candidate);scores[name]={}
            for region,(x0,y0,x1,y1) in regions.items():
                error=abs(candidate-truth)[y0:y1,x0:x1]
                scores[name][region]=dict(mae=float(error.mean()),severe=int((error.max(2)>40).sum()))
        rows.append(dict(sequence=seq,linear_reconstruction_max_error=reconstruction_error,scores=scores))
    temporal={};truth_delta=truths[2]-2*truths[1]+truths[0]
    for name,frames in history.items():
        error=abs(frames[2]-2*frames[1]+frames[0]-truth_delta)
        temporal[name]={region:float(error[y0:y1,x0:x1].mean()) for region,(x0,y0,x1,y1) in regions.items()}
    return dict(cases=rows,temporal_error=temporal,production_changed=False,qualified=False,
                caveat='ROI includes background, native camera phase differs; no GPU cost or physical pacing proof.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=evaluate(a.root)
    with a.output.open('x') as f:json.dump(r,f,indent=2)
    print(json.dumps(r,indent=2))
