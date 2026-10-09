"""Score withheld native middle separately on stable and changing pixels."""
import argparse,json
from pathlib import Path
import numpy as np
from score_held_out_frame import spatial_evidence

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('case',type=Path);args=p.parse_args();case=args.case
    def read(path):return np.fromfile(path,np.uint8).reshape(192,256,4)[...,:3].astype(float)
    a=read(case/'native-left.rgba');b=read(case/'native-right.rgba');truth=read(case/'withheld-reference.rgba')
    changed=np.maximum(abs(a-truth).max(axis=2),abs(b-truth).max(axis=2))>=20
    controls={'hold_left':a,'hold_right':b,'crossfade':(a+b)/2}
    scores={}
    for name,value in list(controls.items())+[(p.name,read(p)) for p in sorted((case/'images').glob('old-*-round-?.rgba'))]:
        error=abs(value-truth)
        scores[name]={'changing_rgb_mae':float(error[changed].mean()) if changed.any() else None,
            'changing_severe_pixels':int((changed&(error.max(axis=2)>40)).sum()),
            'whole_rgb_mae':float(error.mean()),'spatial':spatial_evidence(a,b,truth,value)}
    result={'image_quality_qualified':False,'changing_pixels':int(changed.sum()),'scores':scores}
    (case/'native-control-scores.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'changing_pixels':result['changing_pixels'],'scores':{k:{x:y for x,y in v.items() if x!='spatial'} for k,v in scores.items()}},indent=2))

if __name__=='__main__':main()
