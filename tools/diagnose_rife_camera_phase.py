"""Measure captured native camera steps; reference is diagnostic-only."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from evaluate_rife_camera_consensus import camera_motion


def diagnose(case):
    meta=json.loads((case/'rife/inference.json').read_text())
    manifest=meta['input_manifest'];shape=(manifest['height'],manifest['width'],4)
    hashes={}
    def read(name,expected=None):
        data=(case/name).read_bytes();sha=hashlib.sha256(data).hexdigest()
        if expected and sha!=expected: raise ValueError('source hash mismatch')
        hashes[name]=sha
        return np.frombuffer(data,np.uint8).reshape(shape)[...,:3].astype(float)
    left=read('native-left.rgba',manifest['inputs']['left.rgba']['sha256'])
    right=read('native-right.rgba',manifest['inputs']['right.rgba']['sha256'])
    reference=read('withheld-reference.rgba')
    whole=camera_motion(left,right)
    first=camera_motion(left,reference)
    second=camera_motion(reference,right)
    phase=None;residual=None;closure=None
    if whole is not None and first is not None:
        phase=float(np.dot(first,whole)/np.dot(whole,whole))
        residual=float(np.linalg.norm(first-phase*whole))
    if all(x is not None for x in (whole,first,second)):
        closure=float(np.linalg.norm(first+second-whole))
    return dict(sequence=int(case.name),endpoint_sequences=manifest['endpoint_sequences'],
                requested_interpolation_phase=manifest['phase'],
                endpoint_camera_displacement=None if whole is None else whole.tolist(),
                first_native_step=None if first is None else first.tolist(),
                second_native_step=None if second is None else second.tolist(),
                native_reference_spatial_phase=phase,perpendicular_residual=residual,
                step_closure_error=closure,hashes=hashes,
                caveat='Dominant integer camera displacement only; not all-object, temporal, or artifact qualification.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path)
    parser.add_argument('sequences',nargs='+',type=int)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    rows=[]
    for sequence in args.sequences:
        row=diagnose(args.root/str(sequence));rows.append(row)
        print(sequence,row['endpoint_camera_displacement'],row['first_native_step'],
              row['second_native_step'],row['native_reference_spatial_phase'],flush=True)
    with args.output.open('x') as handle:
        json.dump(dict(cases=rows,production_changed=False,artifact_free_qualified=False),handle,indent=2)
