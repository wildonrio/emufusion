"""Endpoint-only diagnostics; never establishes midpoint accuracy without truth."""
import argparse
import ast
import json
from pathlib import Path
import numpy as np


def compare(left, right, generated):
    a, b, g = [np.asarray(x, dtype=np.float64) for x in (left, right, generated)]
    if a.shape != b.shape or a.shape != g.shape or a.ndim != 3 or a.shape[2] != 3:
        raise ValueError('Expected matching RGB images')
    changing = np.max(abs(a-b), axis=2) > 1
    agreeing = ~changing
    result = {'image_quality_qualified': False, 'ground_truth_available': False,
              'endpoint_changing_pixels': int(changing.sum()),
              'endpoint_agreeing_pixels': int(agreeing.sum()), 'controls': {}}
    for name, control in [('left', a), ('right', b), ('crossfade', (a+b)/2)]:
        delta = np.max(abs(g-control), axis=2)
        result['controls'][name] = {
            'equal_within_1': bool(np.all(delta <= 1)),
            'changing_pixels_distinct_over_1': int((changing & (delta > 1)).sum()),
            'changing_rgb_mae': float(abs(g-control)[changing].mean()) if changing.any() else None}
    # Agreement of endpoints is NOT proof the true midpoint is stationary.
    away = np.minimum(np.max(abs(g-a), axis=2), np.max(abs(g-b), axis=2))
    result['endpoint_agreeing_pixels_changed_over_40'] = int((agreeing & (away > 40)).sum())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    args = parser.parse_args()
    meta = dict(line.split('=', 1) for line in (args.capture/'metadata.txt').read_text().splitlines())
    w, h = int(meta['width']), int(meta['height'])
    x, y, vw, vh = ast.literal_eval(meta['viewport'])
    if not (0 <= x < w and 0 <= y < h and 0 < vw <= w-x and 0 < vh <= h-y):
        raise ValueError('Invalid viewport')
    images = [np.fromfile(args.capture/(name+'.rgba'), dtype=np.uint8).reshape(h,w,4)
              [y:y+vh,x:x+vw,:3] for name in ('left','right','generated')]
    result = compare(*images)
    result['capture_metadata'] = meta
    result['scope'] = 'Gameplay viewport only; excludes bars and diagnostic marker. No withheld midpoint.'
    (args.capture/'endpoint-analysis.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
