"""Offline endpoint-only candidate; reference is used exclusively for scoring."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from score_held_out_frame import spatial_evidence


def preserve_agreeing_neighborhoods(left, right, generated, radius):
    if radius < 0:
        raise ValueError('negative radius')
    disagreement = np.max(abs(left - right), axis=2) > 1
    padded = np.pad(disagreement, radius, mode='edge')
    near_motion = np.zeros(disagreement.shape, dtype=bool)
    h, w = disagreement.shape
    for y in range(2 * radius + 1):
        for x in range(2 * radius + 1):
            near_motion |= padded[y:y+h, x:x+w]
    result = generated.copy()
    result[~near_motion] = left[~near_motion]
    return result, ~near_motion


def evaluate(case, inference):
    metadata = json.loads((inference / 'inference.json').read_text())
    manifest = metadata['input_manifest']
    h, w = manifest['height'], manifest['width']
    if manifest['reference_included'] is not False or manifest['phase'] != 0.5:
        raise ValueError('expected endpoint-only midpoint inference')
    def read(path, expected=None):
        data = path.read_bytes()
        if expected and hashlib.sha256(data).hexdigest() != expected:
            raise ValueError('hash mismatch')
        return np.frombuffer(data, np.uint8).reshape(h, w, 4)[..., :3].astype(float)
    a, b = [read(case / ('native-' + name + '.rgba'),
                 manifest['inputs'][name + '.rgba']['sha256']) for name in ('left', 'right')]
    g = read(inference / 'generated.rgba', metadata['generated_sha256'])
    reference = read(case / 'withheld-reference.rgba')
    rows = []
    for radius in (0, 2, 4, 8):
        candidate, selected = preserve_agreeing_neighborhoods(a, b, g, radius)
        original_error = np.max(abs(g-reference), axis=2)
        error = np.max(abs(candidate-reference), axis=2)
        rows.append(dict(radius=radius, selected_pixels=int(selected.sum()),
                         pixels_improved=int((error < original_error).sum()),
                         pixels_worsened=int((error > original_error).sum()),
                         spatial=spatial_evidence(a, b, reference, candidate)))
    return dict(image_quality_qualified=False, production_changed=False,
                baseline=spatial_evidence(a, b, reference, g), candidates=rows)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('case', type=Path)
    p.add_argument('inference', type=Path)
    args = p.parse_args()
    print(json.dumps(evaluate(args.case, args.inference), indent=2))
