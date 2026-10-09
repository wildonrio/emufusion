"""Offline four-source-frame stationary guard; withheld midpoint is scoring-only."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from evaluate_rife_stationary_candidate import preserve_agreeing_neighborhoods
from score_held_out_frame import spatial_evidence
from score_native_backend_comparison import midpoint_improvement_gate


def quality_scores(left, right, reference, generated):
    changing = np.maximum(abs(left-reference).max(2), abs(right-reference).max(2)) >= 20
    scores = {}
    for name, candidate in {'generated': generated, 'hold_left': left,
                            'hold_right': right, 'crossfade': (left+right)/2}.items():
        error = abs(candidate-reference)
        scores[name] = dict(changing_rgb_mae=float(error[changing].mean()) if changing.any() else None,
                            changing_severe_pixels=int((changing & (error.max(2)>40)).sum()),
                            spatial=spatial_evidence(left,right,reference,candidate))
    return dict(scores=scores, gate=midpoint_improvement_gate(scores,int(changing.sum())))


def temporal_candidate(previous, left, right, following, generated, radius):
    frames = (previous, left, right, following, generated)
    if any(frame.shape != left.shape for frame in frames):
        raise ValueError('frame geometry mismatch')
    stable = np.ones(left.shape[:2], dtype=bool)
    for endpoint in (previous, right, following):
        _, agrees = preserve_agreeing_neighborhoods(left, endpoint, generated, radius)
        stable &= agrees
    # Use the same one-level RGB tolerance for correction as for agreement.
    # Do not overwrite an already-equivalent generated sample: four source
    # frames still cannot prove that no brief event occurred between them.
    stable &= np.max(abs(generated-left), axis=2) > 1
    result = generated.copy()
    result[stable] = left[stable]
    return result, stable


def runtime_available_candidate(left, right, following, generated, radius=2):
    """Three-source offline analogue; absent lookahead must leave output alone."""
    if following is None:
        return generated.copy(), np.zeros(left.shape[:2], dtype=bool)
    return temporal_candidate(left, left, right, following, generated, radius)


def evaluate(root):
    rows = []
    for case in sorted(root.iterdir()):
        if not case.name.isdigit():
            continue
        middle = int(case.name)
        before, after = root / str(middle-1), root / str(middle+1)
        if not (before / 'rife/inference.json').exists() or not (after / 'rife/inference.json').exists():
            continue
        def endpoint(folder, side):
            manifest = json.loads((folder/'rife/inference.json').read_text())['input_manifest']
            index = 0 if side == 'left' else 1
            expected_sequence = int(folder.name) + (-1 if index == 0 else 1)
            if manifest['endpoint_sequences'][index] != expected_sequence:
                raise ValueError('unexpected temporal identity')
            data = (folder/('native-'+side+'.rgba')).read_bytes()
            if hashlib.sha256(data).hexdigest() != manifest['inputs'][side+'.rgba']['sha256']:
                raise ValueError('endpoint hash mismatch')
            return np.frombuffer(data,np.uint8).reshape(manifest['height'],manifest['width'],4)[...,:3].astype(float)
        previous, left = endpoint(before,'left'), endpoint(case,'left')
        right, following = endpoint(case,'right'), endpoint(after,'right')
        metadata = json.loads((case/'rife/inference.json').read_text())
        data = (case/'rife/generated.rgba').read_bytes()
        if hashlib.sha256(data).hexdigest() != metadata['generated_sha256']:
            raise ValueError('generated hash mismatch')
        generated = np.frombuffer(data,np.uint8).reshape(*left.shape[:2],4)[...,:3].astype(float)
        # Only now load reference; never pass it to candidate selection.
        reference = np.frombuffer((case/'withheld-reference.rgba').read_bytes(),np.uint8).reshape(*left.shape[:2],4)[...,:3].astype(float)
        baseline = abs(generated-reference).max(2)
        baseline_quality = quality_scores(left,right,reference,generated)
        for radius in (0,2,4,8):
            candidate, mask = temporal_candidate(previous,left,right,following,generated,radius)
            error = abs(candidate-reference).max(2)
            rows.append(dict(sequence=middle,radius=radius,selected=int(mask.sum()),
                             improved=int((error<baseline).sum()),worsened=int((error>baseline).sum()),
                             baseline_rgb_mae=float(abs(generated-reference).mean()),
                             candidate_rgb_mae=float(abs(candidate-reference).mean()),
                             baseline_quality=baseline_quality,
                             candidate_quality=quality_scores(left,right,reference,candidate)))
    return dict(production_changed=False,image_quality_qualified=False,
                caveat='Extra source lookahead/latency and GPU cost are not qualified.',cases=rows)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path)
    print(json.dumps(evaluate(parser.parse_args().root),indent=2))
