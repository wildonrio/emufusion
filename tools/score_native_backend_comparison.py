"""Score a separately inferred midpoint against a withheld native frame."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from score_held_out_frame import spatial_evidence


def midpoint_improvement_gate(scores, changing_pixels):
    """Necessary per-scene improvement, not a claim of artifact-free gameplay."""
    failures = []
    generated = scores['generated']
    if changing_pixels <= 0:
        failures.append('no moving-region evidence')
    else:
        for control in ('hold_left', 'hold_right', 'crossfade'):
            baseline = scores[control]
            value = generated['changing_rgb_mae']
            if value is None or not np.isfinite(value) or not value < baseline['changing_rgb_mae']:
                failures.append('moving-region MAE does not improve on ' + control)
            if generated['changing_severe_pixels'] > baseline['changing_severe_pixels']:
                failures.append('more severe moving-region errors than ' + control)
    stable = generated['spatial']['regions']['stable']
    if stable['pixels_error_over_1']:
        failures.append('stationary reference pixels altered')
    return {'useful_midpoint_gate_passed': not failures, 'failures': failures,
            'artifact_free_qualified': False,
            'scope': 'Necessary gate for this withheld frame only; no temporal or all-system qualification.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', type=Path)
    parser.add_argument('inference', type=Path)
    args = parser.parse_args()
    metadata = json.loads((args.inference / 'inference.json').read_text())
    def read(path, expected=None):
        raw = path.read_bytes()
        if expected and hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('input/output hash mismatch: ' + str(path))
        return np.frombuffer(raw, np.uint8).reshape(192, 256, 4)[..., :3].astype(float)
    inputs = metadata['input_manifest']['inputs']
    left = read(args.case / 'native-left.rgba', inputs['left.rgba']['sha256'])
    right = read(args.case / 'native-right.rgba', inputs['right.rgba']['sha256'])
    reference = read(args.case / 'withheld-reference.rgba')
    generated = read(args.inference / 'generated.rgba', metadata['generated_sha256'])
    changing = np.maximum(abs(left-reference).max(2), abs(right-reference).max(2)) >= 20
    scores = {}
    for name, candidate in {'generated': generated, 'hold_left': left,
                            'hold_right': right, 'crossfade': (left+right)/2}.items():
        error = abs(candidate-reference)
        scores[name] = {'changing_rgb_mae': float(error[changing].mean()) if changing.any() else None,
                        'changing_severe_pixels': int((changing & (error.max(2)>40)).sum()),
                        'whole_rgb_mae': float(error.mean()),
                        'spatial': spatial_evidence(left, right, reference, candidate)}
    result = {'changing_pixels': int(changing.sum()), 'scores': scores,
              'reference_sha256': hashlib.sha256((args.case/'withheld-reference.rgba').read_bytes()).hexdigest(),
              'image_quality_qualified': False, 'android_performance_qualified': False}
    report = args.inference / 'comparison.json'
    if report.exists():
        if json.loads(report.read_text()) != result:
            raise ValueError('refusing to replace different comparison evidence')
    else:
        with report.open('x') as target:
            json.dump(result, target, indent=2)
    sheet = Image.new('RGB', (256*4, 212))
    draw = ImageDraw.Draw(sheet)
    for index, (label, pixels) in enumerate([
            ('Left', left), ('Withheld reference', reference),
            ('Generated', generated), ('Right', right)]):
        draw.text((256*index+4, 3), label, fill='white')
        sheet.paste(Image.fromarray(pixels[::-1].astype(np.uint8)), (256*index, 20))
    sheet.save(args.inference / 'comparison.png')
    print(json.dumps({k: {m: v for m, v in score.items() if m != 'spatial'}
                      for k, score in scores.items()}, indent=2))
    print(json.dumps(midpoint_improvement_gate(scores, int(changing.sum())), indent=2))


if __name__ == '__main__':
    main()
