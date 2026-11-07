#!/usr/bin/env python3
"""stretch_check.py NARROW.png WIDE.png [...pairs]: is the wide picture a stretched copy of the narrow one?

Both are full-screen captures of the same moment, one narrow and one wide. Widening must add picture at
the sides and leave everything already there at its own size, so the middle of the narrow capture should
match the middle of the wide one at a horizontal scale of 1.0. A picture stretched from 4:3 to 16:9
matches at about 1.33. Prints the best scale and how well it matched; a weak match means the two
moments differ and the pair proves nothing.
"""
import sys

import numpy as np
from PIL import Image

SCALES = np.round(np.arange(0.90, 1.46, 0.01), 2)


def grey(path):
    return np.asarray(Image.open(path).convert('L'), dtype=np.float32)


def best_scale(narrow, wide):
    height, width = narrow.shape
    centre = width / 2
    # The middle of the old picture, away from bars, overlays and the frame rate counter.
    top, bottom = int(height * 0.25), int(height * 0.75)
    half = int(width * 0.16)
    columns = np.arange(int(centre - half), int(centre + half))
    target = wide[top:bottom, columns]
    target = target - target.mean()
    results = []
    for scale in SCALES:
        # Where each wide column would come from in the narrow picture if the wide one were it scaled by `scale`.
        source = centre + (columns - centre) / scale
        left = np.clip(np.floor(source).astype(int), 0, width - 2)
        fraction = source - left
        sample = narrow[top:bottom, left] * (1 - fraction) + narrow[top:bottom, left + 1] * fraction
        sample = sample - sample.mean()
        denominator = np.sqrt((sample * sample).sum() * (target * target).sum())
        results.append((float((sample * target).sum() / denominator) if denominator else 0.0, float(scale)))
    return max(results)


def main():
    paths = sys.argv[1:]
    if len(paths) < 2 or len(paths) % 2:
        sys.exit(__doc__)
    worst = 0.0
    for narrow_path, wide_path in zip(paths[::2], paths[1::2]):
        match, scale = best_scale(grey(narrow_path), grey(wide_path))
        verdict = 'no match' if match < 0.6 else 'STRETCHED' if scale > 1.08 else 'ok'
        print(f'{scale:.2f} match {match:.2f} {verdict}  {narrow_path} {wide_path}')
        if match >= 0.6:
            worst = max(worst, scale)
    return 1 if worst > 1.08 else 0


if __name__ == '__main__':
    sys.exit(main())
