"""Offline color-connected static-edge experiment; never used by the renderer."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from evaluate_rife_stationary_candidate import preserve_agreeing_neighborhoods
from evaluate_rife_temporal_stationary import runtime_available_candidate, quality_scores


def invariant_components(left, right, following, minimum_area=25):
    """Require an entire flat-color shape and its boundary to stay identical.

    Local agreement can freeze the overlapping interior of a moving shape.
    This candidate requires the connected component itself, not just some of
    its pixels, to have identical membership in all three available sources.
    """
    mask=np.zeros(left.shape[:2],bool)
    if following is None:
        return mask
    sources = [np.asarray(frame,dtype=float) for frame in (left,right,following)]
    if any(frame.shape != sources[0].shape for frame in sources) or sources[0].shape[2] != 3:
        raise ValueError('expected matching RGB sources')
    if any(not np.isfinite(frame).all() or (frame<0).any() or (frame>255).any() or
           (frame != np.round(frame)).any() for frame in sources):
        raise ValueError('component identity requires RGB8 sources')
    def pack(frame):
        rgb=frame.astype(np.uint32)
        return rgb[...,0] | (rgb[...,1]<<8) | (rgb[...,2]<<16)
    a,b,c=map(pack,sources)
    h,w=a.shape;visited=np.zeros((h,w),bool)
    for y in range(h):
        for x in range(w):
            if visited[y,x]: continue
            color=a[y,x];stack=[(y,x)];visited[y,x]=True
            pixels=[];boundary=set()
            while stack:
                py,px=stack.pop();pixels.append((py,px))
                for ny,nx in ((py-1,px),(py+1,px),(py,px-1),(py,px+1)):
                    if not (0<=ny<h and 0<=nx<w): continue
                    if a[ny,nx] != color:
                        boundary.add((ny,nx))
                    elif not visited[ny,nx]:
                        visited[ny,nx]=True;stack.append((ny,nx))
            if len(pixels)<minimum_area: continue
            iy,ix=np.asarray(pixels).T
            if (b[iy,ix]!=color).any() or (c[iy,ix]!=color).any(): continue
            if boundary:
                by,bx=np.asarray(list(boundary)).T
                if (b[by,bx]==color).any() or (c[by,bx]==color).any(): continue
            mask[iy,ix]=True
    return mask


def component_correct(left, right, following, generated, minimum_area=25):
    baseline,mask=runtime_available_candidate(left,right,following,generated)
    mask |= invariant_components(left,right,following,minimum_area)&(abs(generated-left).max(2)>1)
    baseline[mask]=left[mask]
    return baseline,mask


def correct(left, right, following, generated, steps=2):
    if steps < 0:
        raise ValueError('negative expansion')
    left, right, generated = [np.asarray(x, dtype=float) for x in (left, right, generated)]
    if left.shape != right.shape or left.shape != generated.shape or left.ndim != 3:
        raise ValueError('source/output geometry mismatch')
    if following is None:
        return generated.copy(), np.zeros(left.shape[:2], bool)
    following = np.asarray(following, dtype=float)
    if following.shape != left.shape:
        raise ValueError('following geometry mismatch')
    _, support = preserve_agreeing_neighborhoods(left, right, generated, 2)
    _, next_support = preserve_agreeing_neighborhoods(right, following, generated, 2)
    support &= next_support
    # Expanding toward motion is less certain than the eroded interior. Only
    # exact, flat-color continuity may extend support, not near-color texture.
    agreed = (abs(left-right).max(2) == 0) & (abs(right-following).max(2) == 0)
    h, w = support.shape
    colors = np.pad(left, ((1, 1), (1, 1), (0, 0)), mode='edge')
    for _ in range(steps):
        padded = np.pad(support, 1, constant_values=False)
        extended = support.copy()
        for dy, dx in ((-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)):
            neighbor = padded[1+dy:1+dy+h, 1+dx:1+dx+w]
            same_color = abs(left-colors[1+dy:1+dy+h, 1+dx:1+dx+w]).max(2) == 0
            extended |= neighbor & same_color & agreed
        support = extended
    support &= abs(generated-left).max(2) > 1
    result = generated.copy()
    result[support] = left[support]
    return result, support


def evaluate(root, components=False, temporal_camera=False, reconstruction='cubic'):
    rows = []
    for case in sorted(root.iterdir()):
        if not case.name.isdigit():
            continue
        following_case = root / str(int(case.name)+1)
        if not (following_case/'rife/inference.json').exists():
            continue
        def endpoint(folder, side):
            manifest = json.loads((folder/'rife/inference.json').read_text())['input_manifest']
            index = 0 if side == 'left' else 1
            if manifest['endpoint_sequences'][index] != int(folder.name)+(-1 if index == 0 else 1):
                raise ValueError('endpoint sequence mismatch')
            data = (folder/('native-'+side+'.rgba')).read_bytes()
            if hashlib.sha256(data).hexdigest() != manifest['inputs'][side+'.rgba']['sha256']:
                raise ValueError('endpoint hash mismatch')
            return np.frombuffer(data,np.uint8).reshape(manifest['height'],manifest['width'],4)[...,:3].astype(float)
        left, right = endpoint(case,'left'), endpoint(case,'right')
        following = endpoint(following_case,'right')
        meta = json.loads((case/'rife/inference.json').read_text())
        data = (case/'rife/generated.rgba').read_bytes()
        if hashlib.sha256(data).hexdigest() != meta['generated_sha256']:
            raise ValueError('generated hash mismatch')
        generated = np.frombuffer(data,np.uint8).reshape(*left.shape[:2],4)[...,:3].astype(float)
        baseline, _ = runtime_available_candidate(left,right,following,generated)
        previous_available=False;following_available=False
        if temporal_camera:
            from evaluate_rife_camera_consensus import correct as camera_correct
            # Pairs in this archive span two native frames. Use +/-two cases,
            # not the immediate neighbor, for equally spaced temporal support.
            future_case=root/str(int(case.name)+2)
            past_case=root/str(int(case.name)-2)
            following_available=(future_case/'rife/inference.json').exists()
            previous_available=(past_case/'rife/inference.json').exists()
            if following_available:
                future=endpoint(future_case,'right')
                past=endpoint(past_case,'left') if previous_available else None
                fixed=invariant_components(left,right,future)
                if past is not None: fixed &= invariant_components(past,left,right)
                candidate, selected=camera_correct(left,right,baseline,future,True,fixed,past,
                                                   reconstruction=reconstruction)
                candidate,_=component_correct(left,right,future,candidate)
                candidate=np.clip(np.rint(candidate),0,255)
            else:
                candidate=baseline.copy();selected=np.zeros(left.shape[:2],bool)
        else:
            candidate, selected = (component_correct if components else correct)(left,right,following,generated)
        # Withheld truth is read only after both candidates have been synthesized.
        reference = np.frombuffer((case/'withheld-reference.rgba').read_bytes(),np.uint8).reshape(*left.shape[:2],4)[...,:3].astype(float)
        before, after = abs(baseline-reference).max(2), abs(candidate-reference).max(2)
        changed = abs(candidate-baseline).max(2)>0
        rows.append(dict(sequence=int(case.name),newly_changed=int(changed.sum()),
                         temporal_camera=temporal_camera,camera_selected=int(selected.sum()) if temporal_camera else 0,
                         previous_available=previous_available,following_available=following_available,
                         improved=int((after<before).sum()),worsened=int((after>before).sum()),
                         newly_severe=int(((after>40)&(before<=40)).sum()),
                         max_worsening=float(np.maximum(after-before,0).max()),
                         quality=quality_scores(left,right,reference,candidate)))
    return dict(production_changed=False,artifact_free_qualified=False,cases=rows)


def evaluate_analytic_camera(case, output=None, boundary_lookahead=False, layered=False):
    from create_fractional_motion_case import render
    from evaluate_rife_camera_consensus import correct as camera_correct
    metadata=json.loads((case/'rife/inference.json').read_text())
    manifest=metadata['input_manifest']
    description=json.loads((case/'analytic-reference.json').read_text())
    if description['kind']!='camera' or description['endpoint_times']!=[0,1]:
        raise ValueError('expected the independent analytic camera fixture')
    def read(path,expected=None):
        data=path.read_bytes()
        if expected and hashlib.sha256(data).hexdigest()!=expected:
            raise ValueError('fixture hash mismatch')
        return np.frombuffer(data,np.uint8).reshape(manifest['height'],manifest['width'],4)[...,:3].astype(float)
    left=read(case/'native-left.rgba',manifest['inputs']['left.rgba']['sha256'])
    right=read(case/'native-right.rgba',manifest['inputs']['right.rgba']['sha256'])
    generated=read(case/'rife/generated.rgba',metadata['generated_sha256'])
    following_time=2.0 if boundary_lookahead else 1.5
    following=render(following_time,'camera')[...,:3].astype(float)
    previous=render(-1,'camera')[...,:3].astype(float) if layered else None
    fixed=invariant_components(left,right,following) if layered else None
    if layered:
        fixed &= invariant_components(previous,left,right)
    camera,moving=camera_correct(left,right,generated,following=following,
                                 boundary_lookahead=boundary_lookahead,
                                 static_mask=fixed,previous=previous)
    candidate,static=component_correct(left,right,following,camera)
    # Match an actual RGB8 output, rather than scoring unrepresentable floats.
    candidate=np.clip(np.rint(candidate),0,255)
    if output is not None:
        output.mkdir(parents=True,exist_ok=False)
        rgba=np.full((*candidate.shape[:2],4),255,np.uint8)
        rgba[...,:3]=candidate.astype(np.uint8)
        data=rgba.tobytes()
        (output/'generated.rgba').write_bytes(data)
        (output/'inference.json').write_text(json.dumps(dict(
            input_manifest=manifest,generated_sha256=hashlib.sha256(data).hexdigest(),
            algorithm='offline-camera-consensus-plus-static-component',
            following_time=following_time,boundary_lookahead=boundary_lookahead,
            layered=layered,previous_time=-1 if layered else None,
            production_changed=False,artifact_free_qualified=False,
            evaluator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),indent=2))
    reference=read(case/'withheld-reference.rgba')
    return dict(production_changed=False,artifact_free_qualified=False,
                camera_selected=int(moving.sum()),static_selected=int(static.sum()),
                following_time=following_time,boundary_lookahead=boundary_lookahead,
                layered=layered,previous_time=-1 if layered else None,
                baseline=quality_scores(left,right,reference,generated),
                camera_only=quality_scores(left,right,reference,camera),
                candidate=quality_scores(left,right,reference,candidate))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('roots',nargs='*',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--components',action='store_true')
    parser.add_argument('--analytic-camera',type=Path)
    parser.add_argument('--analytic-output',type=Path)
    parser.add_argument('--boundary-lookahead',action='store_true')
    parser.add_argument('--layered-camera',action='store_true')
    parser.add_argument('--captured-temporal-camera',action='store_true')
    parser.add_argument('--reconstruction',choices=('cubic','plateau'),default='cubic')
    args=parser.parse_args()
    if not args.roots and args.analytic_camera is None:
        parser.error('at least one captured root or analytic camera fixture is required')
    if args.analytic_output is not None and args.analytic_camera is None:
        parser.error('--analytic-output requires --analytic-camera')
    if args.layered_camera and not args.boundary_lookahead:
        parser.error('--layered-camera requires --boundary-lookahead')
    if args.reconstruction!='cubic' and (not args.captured_temporal_camera or args.analytic_camera):
        parser.error('alternate reconstruction currently requires captured temporal evaluation only')
    report={str(root):evaluate(root,args.components,args.captured_temporal_camera,args.reconstruction) for root in args.roots}
    if args.analytic_camera:
        report['analytic_camera']=evaluate_analytic_camera(
            args.analytic_camera,args.analytic_output,args.boundary_lookahead,args.layered_camera)
    report['_method']=dict(components=args.components,
                         reconstruction=args.reconstruction,
                         captured_temporal_camera=args.captured_temporal_camera,
                         evaluator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    with args.output.open('x') as handle:
        json.dump(report,handle,indent=2)
    for name,result in report.items():
        if 'cases' not in result: continue
        print(name, {key:sum(row[key] for row in result['cases']) for key in
                     ('newly_changed','improved','worsened','newly_severe')})
    if args.analytic_camera:
        print('analytic camera',report['analytic_camera']['candidate']['gate'])
