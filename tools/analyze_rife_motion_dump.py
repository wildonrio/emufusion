"""Inspect model blending without changing its generated frame."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np


def evaluate(folder):
    meta=json.loads((folder/'inference.json').read_text())
    data=(folder/'motion.npz').read_bytes()
    if hashlib.sha256(data).hexdigest()!=meta['motion_dump']['sha256']:
        raise ValueError('motion dump hash mismatch')
    with np.load(folder/'motion.npz',allow_pickle=False) as dump:
        left,right,mask,flow=[dump[key] for key in ('left','right','mask','flow')]
    h,w=left.shape[:2]
    rgba=(folder/'generated.rgba').read_bytes()
    if hashlib.sha256(rgba).hexdigest()!=meta['generated_sha256']:raise ValueError('generated hash mismatch')
    generated=np.frombuffer(rgba,np.uint8).reshape(h,w,4)[::-1,:,:3]
    blend=np.clip(np.rint((left*mask+right*(1-mask))*255),0,255)
    rows={}
    for name,(x0,y0,x1,y1) in {'character':(112,140,145,180),
                              'lightning':(54,25,98,179),'building':(147,40,235,130)}.items():
        a=left[y0:y1,x0:x1];b=right[y0:y1,x0:x1];m=mask[y0:y1,x0:x1,0]
        delta=abs(a-b).max(2)*255
        mixed=(m>.2)&(m<.8)
        rows[name]=dict(pixels=int(m.size),mixed_pixels=int(mixed.sum()),
                        mixed_disagreement_over20=int((mixed&(delta>20)).sum()),
                        warped_disagreement_median=float(np.median(delta)),
                        warped_disagreement_p95=float(np.percentile(delta,95)),
                        mask_median=float(np.median(m)),
                        median_flow=np.median(flow[y0:y1,x0:x1],axis=(0,1)).tolist())
    return dict(regions=rows,blend_reconstruction_max_error=float(abs(blend-generated).max()),
                production_changed=False,artifact_free_qualified=False,
                caveat='ROI includes background; blend disagreement is not confidence or proof of the correct midpoint.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();report=evaluate(a.folder)
    with a.output.open('x') as f:json.dump(report,f,indent=2)
    print(json.dumps(report,indent=2))
