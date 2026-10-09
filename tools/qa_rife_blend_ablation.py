"""Offline warped-source blend ablation; no reference-guided synthesis."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np


def blend(left,right,mask,power):
    if power=='hard':weight=(mask>=.5).astype(float)
    else:
        a=mask**power;b=(1-mask)**power
        weight=a/np.maximum(a+b,1e-12)
    return np.clip(np.rint((left*weight+right*(1-weight))*255),0,255)


def evaluate(root,captured,sequences):
    methods={'original':1,'power2':2,'power4':4,'hard':'hard'}
    rois={'character':(112,140,145,180),'lightning':(54,25,98,179),'building':(147,40,235,130)}
    rows=[];history={name:[] for name in methods};truths=[]
    for seq in sequences:
        folder=root/f'rife-motion-{seq}-20260917'
        meta=json.loads((folder/'inference.json').read_text())
        if meta['input_manifest']['endpoint_sequences']!=[seq-1,seq+1]:raise ValueError('sequence mismatch')
        if hashlib.sha256((folder/'motion.npz').read_bytes()).hexdigest()!=meta['motion_dump']['sha256']:
            raise ValueError('dump hash mismatch')
        with np.load(folder/'motion.npz',allow_pickle=False) as d:
            candidates={name:blend(d['left'],d['right'],d['mask'],power) for name,power in methods.items()}
        h,w=candidates['original'].shape[:2]
        generated=(folder/'generated.rgba').read_bytes()
        if hashlib.sha256(generated).hexdigest()!=meta['generated_sha256']:raise ValueError('output hash mismatch')
        np.testing.assert_array_equal(candidates['original'],np.frombuffer(generated,np.uint8).reshape(h,w,4)[::-1,:,:3])
        reference=np.frombuffer((captured/str(seq)/'withheld-reference.rgba').read_bytes(),np.uint8).reshape(h,w,4)[::-1,:,:3].astype(float)
        truths.append(reference)
        result={}
        for name,candidate in candidates.items():
            history[name].append(candidate)
            regions={}
            for region,(x0,y0,x1,y1) in rois.items():
                error=abs(candidate-reference)[y0:y1,x0:x1]
                regions[region]=dict(mae=float(error.mean()),severe=int((error.max(2)>40).sum()))
            result[name]=regions
        rows.append(dict(sequence=seq,methods=result))
    temporal={}
    if len(sequences)==3 and sequences==list(range(sequences[0],sequences[0]+3)):
        truth_accel=truths[2]-2*truths[1]+truths[0]
        for name,frames in history.items():
            residual=abs(frames[2]-2*frames[1]+frames[0]-truth_accel)
            temporal[name]={region:float(residual[y0:y1,x0:x1].mean()) for region,(x0,y0,x1,y1) in rois.items()}
    return dict(cases=rows,temporal_second_difference_error=temporal,
                production_changed=False,artifact_free_qualified=False,
                caveat='Native reference phase and changing animation confound scores; temporal difference is not a physical flicker test.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('root',type=Path);p.add_argument('captured',type=Path)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    report=evaluate(a.root,a.captured,[3818,3819,3820])
    with a.output.open('x') as f:json.dump(report,f,indent=2)
    print(json.dumps(report,indent=2))
