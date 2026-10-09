"""Endpoint-derived translation self-consistency, not ground-truth image quality."""
import argparse
import json
from pathlib import Path
import numpy as np
from evaluate_rife_patch_motion import match,sample_cubic,box_mean,synthesize


def measure(left,right,candidates):
    flow,confidence=match(left,right)
    vectors,counts=np.unique(flow[confidence],axis=0,return_counts=True)
    if not len(counts):return dict(qualified=False,reason='no unambiguous motion')
    i=int(np.argmax(counts));dx,dy=vectors[i]
    if counts[i]<100 or counts[i]/confidence.sum()<.7 or np.hypot(dx,dy)<1:
        return dict(qualified=False,reason='no dominant moving layer')
    h,w=left.shape[:2];y,x=np.mgrid[:h,:w]
    # This mask uses only endpoint motion and endpoint reconstruction, not any
    # candidate or withheld frame. Keep away from layer boundaries and borders.
    agrees=confidence&(np.linalg.norm(flow-[dx,dy],axis=2)<.01)
    mask=box_mean(agrees.astype(float),4)>.999
    mask &= (x>8+abs(dx))&(x<w-9-abs(dx))&(y>8+abs(dy))&(y<h-9-abs(dy))
    endpoint_error=abs(sample_cubic(left,x-dx,y-dy)-right).max(2)
    mask &= box_mean(endpoint_error,4)<2
    if mask.sum()<100:return dict(qualified=False,reason='insufficient coherent pixels')
    scores={name:[] for name in candidates}
    phases=np.linspace(0,1,41)
    for phase in phases:
        template=sample_cubic(left,x-phase*dx,y-phase*dy)
        for name,candidate in candidates.items():
            scores[name].append(float(abs(template-candidate)[mask].mean()))
    results={}
    for name,errors in scores.items():
        index=int(np.argmin(errors))
        results[name]=dict(best_phase=float(phases[index]),fit_rgb_mae=errors[index],
                           uniform_midpoint_rgb_mae=errors[20])
    return dict(dominant_displacement=[float(dx),float(dy)],pixels=int(mask.sum()),
                candidates=results,qualified=False,
                caveat='Single dominant layer and cubic template only; no proof for occlusions, other objects, or image quality.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('case',type=Path)
    case=p.parse_args().case;m=json.loads((case/'rife/inference.json').read_text())['input_manifest']
    def read(n):return np.frombuffer((case/n).read_bytes(),np.uint8).reshape(m['height'],m['width'],4)[...,:3].astype(float)
    left,right=read('native-left.rgba'),read('native-right.rgba')
    generated=read('rife/generated.rgba')
    patch,_=synthesize(left,right,generated,sharper=True,consensus=True)
    print(json.dumps(measure(left,right,dict(original=generated,patch=patch,
                       reference=read('withheld-reference.rgba'))),indent=2))
