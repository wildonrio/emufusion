"""Diagnose nonuniform source motion; never qualifies or modifies synthesis."""
import argparse
import json
from pathlib import Path
import numpy as np
from evaluate_rife_patch_motion import match


def dominant_motion(left, right):
    flow, valid = match(left,right)
    values, counts = np.unique(flow[valid],axis=0,return_counts=True)
    if not len(counts):
        return dict(vector=None,support=0,accepted=0,fraction=0.0)
    index=int(np.argmax(counts))
    return dict(vector=values[index].tolist(),support=int(counts[index]),
                accepted=int(valid.sum()),fraction=float(counts[index]/valid.sum()))


def diagnose(left, reference, right):
    outer=dominant_motion(left,right)
    first=dominant_motion(left,reference)
    second=dominant_motion(reference,right)
    reliable=all(d['support']>=100 and d['fraction']>.7 for d in (outer,first,second))
    consistent=False;offset=None
    if reliable:
        total=np.array(outer['vector']);a=np.array(first['vector']);b=np.array(second['vector'])
        consistent=bool(np.allclose(a+b,total))
        if consistent:offset=(a-total/2).tolist()
    return dict(outer=outer,left_to_reference=first,reference_to_right=second,
                dominant_motion_composes=consistent,
                reference_offset_from_uniform_midpoint_pixels=offset,
                reconstruction_and_smoothness_require_separate_evidence=bool(offset is not None and any(abs(x)>.1 for x in offset)),
                image_quality_qualified=False,
                caveat='Dominant motion only; does not validate objects, occlusions, or generated frames.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('case',type=Path)
    case=p.parse_args().case
    m=json.loads((case/'rife/inference.json').read_text())['input_manifest']
    def read(name):
        return np.frombuffer((case/name).read_bytes(),np.uint8).reshape(m['height'],m['width'],4)[...,:3].astype(float)
    print(json.dumps(diagnose(read('native-left.rgba'),read('withheld-reference.rgba'),read('native-right.rgba')),indent=2))
