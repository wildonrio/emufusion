"""Score an offline reconstruction against withheld RGB, including weak controls."""
import argparse,json
from pathlib import Path
import numpy as np
from analyze_dense_flow_merging import read_dump


def spatial_evidence(a,b,reference,generated):
    """Keep static-image damage separate from inherently ambiguous animation.

    Masks use the withheld reference only for scoring, never synthesis input.
    A low whole-image error on a mostly-static scene is not quality proof.
    """
    a,b,reference,generated=[np.asarray(x,dtype=float) for x in (a,b,reference,generated)]
    if not (a.shape==b.shape==reference.shape==generated.shape) or a.ndim!=3 or a.shape[2]!=3:
        raise ValueError('Expected four equally sized RGB images')
    stable=(np.max(abs(a-reference),axis=2)<=1)&(np.max(abs(b-reference),axis=2)<=1)
    changing=~stable
    error=np.max(abs(generated-reference),axis=2)
    regions={}
    for name,mask in [('stable',stable),('changing',changing)]:
        regions[name]={'pixels':int(mask.sum()),
            'rgb_mae':float(abs(generated-reference)[mask].mean()) if mask.any() else None,
            'pixels_error_over_1':int((mask&(error>1)).sum()),
            'pixels_error_over_40':int((mask&(error>40)).sum())}
    controls={}
    for name,value in [('left',a),('right',b),('crossfade',(a+b)/2)]:
        distance=np.max(abs(generated-value),axis=2)
        controls[name]={'whole_image_equal_within_1':bool(np.all(distance<=1)),
            'changing_pixels_distinct_over_1':int((changing&(distance>1)).sum())}
    return {'regions':regions,'copy_controls':controls,'image_quality_qualified':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('case',type=Path)
    args=parser.parse_args();case=args.case
    meta,p=read_dump(case/'outer-initial.bin');w,h=meta['history_width'],meta['history_height']
    def image(data):
        return np.frombuffer(data,np.uint8).reshape(h,w,4)[...,:3].astype(float)
    a,b=image(p['previousFull'][2]),image(p['currentFull'][2])
    reference=image((case/'reference.rgba').read_bytes())
    generated=image((case/'output/phase-0.5.rgba').read_bytes())
    changed=np.maximum(np.max(abs(a-reference),axis=2),np.max(abs(b-reference),axis=2))>=20
    result={'image_quality_qualified':False,'changed_pixels':int(changed.sum()),'scores':{},
            'spatial_evidence':spatial_evidence(a,b,reference,generated)}
    for name,value in [('hold_left',a),('hold_right',b),('crossfade',(a+b)/2),('generated',generated)]:
        error=abs(value-reference);maximum=np.max(error,axis=2)
        result['scores'][name]={'full_rgb_mae':float(error.mean()),
            'changed_rgb_mae':float(error[changed].mean()) if changed.any() else 0,
            'changed_max_channel_mae':float(maximum[changed].mean()) if changed.any() else 0,
            'changed_pixels_error_over_40':int((changed&(maximum>40)).sum())}
    (case/'scores.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))


if __name__=='__main__':main()
