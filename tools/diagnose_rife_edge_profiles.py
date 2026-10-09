"""Endpoint-selected edge placement/spreading; not full-image qualification."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from evaluate_rife_camera_consensus import camera_motion, correct as camera_correct
from evaluate_rife_static_edge_support import invariant_components, component_correct
from evaluate_rife_temporal_stationary import runtime_available_candidate


def edge_profiles(left,right,candidates,dx):
    if int(dx)!=dx or dx<=0:
        raise ValueError('this diagnostic requires positive integer horizontal translation')
    dx=int(dx);h,w=left.shape[:2];selected=[]
    # Select isolated, high-contrast, flat-color steps from endpoints ONLY.
    # No candidate or withheld image participates in selecting these rows.
    for y in range(2,h-2):
        for x in range(4,w-dx-4):
            low=left[y,x-1];high=left[y,x]
            direction=high-low
            if abs(direction).max()<40:continue
            indices=np.arange(x-3,x+dx+3)
            expected_left=np.where((indices<x)[:,None],low,high)
            expected_right=np.where((indices<x+dx)[:,None],low,high)
            if abs(left[y,indices]-expected_left).max()>1:continue
            if abs(right[y,indices]-expected_right).max()>1:continue
            center=x-.5+dx/2
            ideal=np.clip(indices+.5-center,0,1)
            mass=np.diff(ideal);positions=indices[:-1]+.5
            ideal_variance=float(np.sum(mass*(positions-center)**2)/mass.sum())
            selected.append((y,x,indices,low,direction,center,ideal_variance))
    results={}
    for name,candidate in candidates.items():
        if candidate.shape!=left.shape:raise ValueError('candidate geometry mismatch')
        rows=[]
        for y,x,indices,low,direction,center,ideal_variance in selected:
            pixels=candidate[y,indices]
            profile=(pixels-low)@direction/(direction@direction)
            derivative=np.diff(profile);positive=np.maximum(derivative,0)
            mass=float(positive.sum())
            if mass<.2:
                rows.append(dict(x=x,y=y,missing_edge=True));continue
            positions=indices[:-1]+.5
            location=float(positive@positions/mass)
            variance=float(positive@((positions-location)**2)/mass)
            perpendicular=pixels-(low+profile[:,None]*direction)
            rows.append(dict(x=x,y=y,missing_edge=False,
                             spatial_phase=(location-(x-.5))/dx,
                             midpoint_position_error_pixels=location-center,
                             spread_variance=variance,ideal_variance=ideal_variance,
                             excess_spread=max(0.,variance-ideal_variance),
                             contrast_error=abs(float(profile[-1]-profile[0])-1.),
                             reverse_gradient_mass=float(np.maximum(-derivative,0).sum()),
                             off_color_line_mae=float(abs(perpendicular).mean())))
        valid=[row for row in rows if not row['missing_edge']]
        def stats(key,absolute=False):
            values=np.array([row[key] for row in valid])
            if absolute:values=abs(values)
            return None if not len(values) else dict(median=float(np.median(values)),
                        p95=float(np.percentile(values,95)),maximum=float(values.max()))
        results[name]=dict(edge_rows=len(rows),missing=sum(row['missing_edge'] for row in rows),
                           phase=stats('spatial_phase'),
                           position_error=stats('midpoint_position_error_pixels',True),
                           excess_spread=stats('excess_spread'),
                           contrast_error=stats('contrast_error'),
                           reverse_gradient=stats('reverse_gradient_mass'),
                           off_color_line=stats('off_color_line_mae'),rows=rows)
    return dict(selected_edge_rows=len(selected),
                distinct_columns=sorted(set(row[1] for row in selected)),
                displacement=dx,candidates=results,artifact_free_qualified=False,
                scope='Isolated horizontal-camera edge rows only; no occlusion, curved-edge, timing, or whole-image proof.')


def evaluate(case,reconstruction='cubic',return_images=False):
    meta=json.loads((case/'rife/inference.json').read_text());m=meta['input_manifest']
    shape=(m['height'],m['width'],4)
    hashes={}
    def read(path,expected=None):
        data=path.read_bytes();sha=hashlib.sha256(data).hexdigest()
        if expected and sha!=expected:raise ValueError('hash mismatch')
        hashes[str(path)]=sha
        return np.frombuffer(data,np.uint8).reshape(shape)[...,:3].astype(float)
    def endpoint(folder,side):
        manifest=json.loads((folder/'rife/inference.json').read_text())['input_manifest']
        index=0 if side=='left' else 1
        if manifest['endpoint_sequences'][index]!=int(folder.name)+(-1 if index==0 else 1):
            raise ValueError('sequence mismatch')
        return read(folder/('native-'+side+'.rgba'),manifest['inputs'][side+'.rgba']['sha256'])
    left=endpoint(case,'left');right=endpoint(case,'right')
    motion=camera_motion(left,right)
    if motion is None or motion[1]!=0 or motion[0]<=0:
        return dict(available=False,reason='no supported horizontal camera',artifact_free_qualified=False)
    generated=read(case/'rife/generated.rgba',meta['generated_sha256'])
    immediate=endpoint(case.parent/str(int(case.name)+1),'right')
    future=endpoint(case.parent/str(int(case.name)+2),'right')
    past=endpoint(case.parent/str(int(case.name)-2),'left')
    baseline,_=runtime_available_candidate(left,right,immediate,generated)
    fixed=invariant_components(left,right,future)&invariant_components(past,left,right)
    candidate,_=camera_correct(left,right,baseline,future,True,fixed,past,
                               reconstruction=reconstruction)
    candidate,_=component_correct(left,right,future,candidate)
    candidate=np.clip(np.rint(candidate),0,255)
    # Read withheld truth last. It has no role in generation or edge selection.
    reference=read(case/'withheld-reference.rgba')
    result=edge_profiles(left,right,dict(original=generated,candidate=candidate,
                         native_reference=reference,hold_left=left,hold_right=right,
                         crossfade=(left+right)/2),int(motion[0]))
    result.update(hashes=hashes,available=True,production_changed=False)
    if return_images:
        return result,dict(left=left,original=generated,candidate=candidate,
                           reference=reference,right=right)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=evaluate(args.case)
    with args.output.open('x') as handle:json.dump(result,handle,indent=2)
    if result['available']:
        print('edge rows',result['selected_edge_rows'],'columns',result['distinct_columns'])
        for name,row in result['candidates'].items():
            print(name,{key:row[key] for key in ('phase','position_error','excess_spread')})
    else:print(result)
