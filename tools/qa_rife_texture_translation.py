"""Independent continuous textured-world probe for the offline camera correction.

The reference is evaluated analytically, never interpolated from input pixels.
This tests reconstruction, not RIFE inference or Android presentation timing.
"""
import argparse
import json
from pathlib import Path
import numpy as np
from evaluate_rife_camera_consensus import correct


def render(time, velocity, frequency, height=48, width=80):
    y,x=np.mgrid[:height,:width]
    x=x-velocity[0]*time;y=y-velocity[1]*time
    # Different non-collinear waves prevent one-dimensional correspondence
    # ambiguity; continuous evaluation supplies independent half-time truth.
    return np.stack([
        128+60*np.sin(2*np.pi*(frequency*x+.037*y))
           +30*np.cos(2*np.pi*(.043*x+.071*y)),
        128+55*np.cos(2*np.pi*(.061*x+frequency*y))
           +25*np.sin(2*np.pi*(.097*x-.053*y)),
        128+65*np.sin(2*np.pi*(frequency*x-.083*y)+.8)
           +20*np.cos(2*np.pi*(.029*x+.113*y)),
    ],axis=2)


def evaluate():
    rows=[]
    for velocity in ((2,0),(3,0),(-3,0),(0,3),(3,3)):
        for frequency in (.06,.15,.25,.38):
            frames=[render(t,velocity,frequency) for t in (-1,0,1,2)]
            past,left,right,future=frames
            # Deliberately imperfect input reveals which pixels the correction
            # actually takes responsibility for. Unselected pixels scored too.
            baseline=(left+right)/2
            candidate,selected=correct(left,right,baseline,future,True,previous=past)
            reference=render(.5,velocity,frequency)
            interior=np.zeros(selected.shape,bool);interior[8:-8,8:-8]=True
            mask=selected&interior
            def score(image):
                error=abs(image-reference)
                return dict(mae=float(error[mask].mean()) if mask.any() else None,
                            severe_pixels=int(((error.max(2)>40)&mask).sum()),
                            maximum=float(error[mask].max()) if mask.any() else None)
            rows.append(dict(velocity=velocity,frequency=frequency,
                             selected_pixels=int(mask.sum()),interior_pixels=int(interior.sum()),
                             candidate=score(candidate),crossfade=score(baseline)))
    return dict(cases=rows,artifact_free_qualified=False,production_changed=False,
                scope='Analytic continuous textures; excludes occlusion, RIFE baseline, GPU cost and physical pacing.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();report=evaluate()
    with args.output.open('x') as handle:json.dump(report,handle,indent=2)
    for row in report['cases']:
        print(row)
