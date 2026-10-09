"""Captured foreground correspondence audit; ROIs are diagnostics, not synthesis hints."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from evaluate_rife_patch_motion import match,synthesize


def evaluate(case,search=6):
    meta=json.loads((case/'rife/inference.json').read_text())
    m=meta['input_manifest'];shape=(m['height'],m['width'],4)
    def read(name,sha=None):
        data=(case/name).read_bytes()
        if sha and hashlib.sha256(data).hexdigest()!=sha:raise ValueError('hash mismatch')
        return np.frombuffer(data,np.uint8).reshape(shape)[...,:3].astype(float)
    left=read('native-left.rgba',m['inputs']['left.rgba']['sha256'])
    right=read('native-right.rgba',m['inputs']['right.rgba']['sha256'])
    original=read('rife/generated.rgba',meta['generated_sha256'])
    forward,confidence=match(left,right,search=search)
    candidate,selected=synthesize(left,right,original,sharper=True,consensus=False,search=search)
    reference=read('withheld-reference.rgba')
    # Coordinates from upright inspected 256x192 captured Castlevania scene.
    # Explicit scope prevents these diagnostic regions becoming game heuristics.
    if shape[:2]!=(192,256):raise ValueError('ROI audit requires inspected 256x192 scene')
    regions={'character':(112,140,145,180),'lightning':(54,25,98,179),
             'building':(147,40,235,130)}
    rows={}
    for name,(x0,y0,x1,y1) in regions.items():
        roi=np.zeros(shape[:2],bool);roi[192-y1:192-y0,x0:x1]=True
        vectors,counts=np.unique(forward[roi&confidence],axis=0,return_counts=True)
        order=np.argsort(counts)[::-1][:8]
        before=abs(original-reference).max(2);after=abs(candidate-reference).max(2)
        rows[name]=dict(pixels=int(roi.sum()),confident=int((roi&confidence).sum()),
                        corrected=int((roi&selected).sum()),
                        improved=int((roi&(after<before)).sum()),
                        worsened=int((roi&(after>before)).sum()),
                        original_mae=float(abs(original-reference)[roi].mean()),
                        candidate_mae=float(abs(candidate-reference)[roi].mean()),
                        dominant_vectors=[dict(vector=vectors[i].tolist(),pixels=int(counts[i])) for i in order])
    return dict(case=str(case),search=search,regions=rows,production_changed=False,artifact_free_qualified=False,
                scope='Manually selected diagnostic ROIs only; native reference not uniform camera phase; no timing proof.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('case',type=Path)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--search',type=int,choices=(6,12,18),default=6);a=p.parse_args()
    report=evaluate(a.case,a.search)
    with a.output.open('x') as f:json.dump(report,f,indent=2)
    print(json.dumps(report,indent=2))
