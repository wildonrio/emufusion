"""Compare pinned model analysis scales over the inspected capture sequence."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np


def evaluate(root,candidate_prefix='rife-scale2'):
    regions={'character':(112,140,145,180),'lightning':(54,25,98,179),
             'building':(147,40,235,130),'whole':(0,0,256,192)}
    history={'original':[],'candidate':[],'reference':[]};rows=[]
    for seq in (3818,3819,3820):
        row={'sequence':seq,'methods':{}}
        manifests=[]
        for name,prefix in (('original','rife-motion'),('candidate',candidate_prefix)):
            folder=root/f'{prefix}-{seq}-20260917'
            meta=json.loads((folder/'inference.json').read_text());manifests.append(meta['input_manifest'])
            if meta['input_manifest']['endpoint_sequences']!=[seq-1,seq+1]:raise ValueError('wrong sequence')
            data=(folder/'generated.rgba').read_bytes()
            if hashlib.sha256(data).hexdigest()!=meta['generated_sha256']:raise ValueError('wrong output')
            history[name].append(np.frombuffer(data,np.uint8).reshape(192,256,4)[::-1,:,:3].astype(float))
            row['methods'][name]={'host_seconds':meta['host_single_inference_seconds']}
        if manifests[0]!=manifests[1]:raise ValueError('endpoint manifests differ')
        ref=root/'rife-camera-sequence-2026-09-16'/str(seq)/'withheld-reference.rgba'
        truth=np.frombuffer(ref.read_bytes(),np.uint8).reshape(192,256,4)[::-1,:,:3].astype(float)
        history['reference'].append(truth)
        for name in ('original','candidate'):
            row['methods'][name]['regions']={}
            for region,(x0,y0,x1,y1) in regions.items():
                error=abs(history[name][-1]-truth)[y0:y1,x0:x1]
                row['methods'][name]['regions'][region]=dict(mae=float(error.mean()),severe=int((error.max(2)>40).sum()))
        rows.append(row)
    temporal={}
    ref=history['reference'];truth_delta=ref[2]-2*ref[1]+ref[0]
    for name in ('original','candidate'):
        frames=history[name];error=abs(frames[2]-2*frames[1]+frames[0]-truth_delta)
        temporal[name]={region:float(error[y0:y1,x0:x1].mean()) for region,(x0,y0,x1,y1) in regions.items()}
    return dict(candidate_prefix=candidate_prefix,cases=rows,temporal_error=temporal,production_changed=False,
                artifact_free_qualified=False,android_performance_qualified=False,
                caveat='Native camera spatial phase confounds RGB comparison; host runtime is not GPU timing.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--candidate-prefix',default='rife-scale2');a=p.parse_args()
    r=evaluate(a.root,a.candidate_prefix)
    with a.output.open('x') as f:json.dump(r,f,indent=2)
    print(json.dumps(r,indent=2))
