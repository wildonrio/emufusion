"""Visible-artifact measure for replay bench dumps (replay_bench.py --dump-dir).

A generated pixel counts as wrong only when no pixel of the real middle frame
within one pixel matches it: placing pixel art a pixel off, or a half-pixel
sub-sample, is not an artifact, while blocks, tears, a doubled HUD or content
from the wrong repeat are. Severe: 48+ grey levels off and 24 more than a
cross-fade (same tolerance); solid: 3 of 4 neighbours severe too. A frame has
a visible artifact when solid pixels cover 0.1% of it.

usage: replay_artifacts.py DUMP_DIR [DUMP_DIR...]   (each holding <case>/<triplet>.bin)
       replay_artifacts.py --paired BEFORE_DIR AFTER_DIR
"""
import sys
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent))
import replay_sheet as R

def fit(img, w, h):
    return img if img.shape[:2] == (h, w) else np.asarray(Image.fromarray(img).resize((w, h), Image.BILINEAR))

def tol_err(g, r):
    h, w = g.shape[:2]
    pad = np.pad(r, ((1, 1), (1, 1), (0, 0)), mode='edge').astype(np.int16)
    best = np.full((h, w), 255, np.int16)
    for dy in range(3):
        for dx in range(3):
            best = np.minimum(best, np.abs(g.astype(np.int16) - pad[dy:dy + h, dx:dx + w]).max(-1))
    return best

def solid(mask):
    n = np.zeros_like(mask, np.int8)
    n[1:-1, 1:-1] = mask[:-2, 1:-1].astype(np.int8) + mask[2:, 1:-1] + mask[1:-1, :-2] + mask[1:-1, 2:]
    return mask & (n >= 3)

def score(path):
    _, p = R.planes(path)
    g = p['generated24']; h, w = g.shape[:2]
    a, b, c = (fit(p[n], w, h) for n in ('previous', 'reference', 'current'))
    x = ((a.astype(np.int16) + c) // 2).astype(np.uint8)
    changing = np.maximum(np.abs(a.astype(np.int16) - b).max(-1), np.abs(c.astype(np.int16) - b).max(-1)) > 2
    eg, ex = tol_err(g, b), tol_err(x, b)
    sev = changing & (eg >= 48) & (eg >= ex + 24)
    return 100.0 * solid(sev).sum() / sev.size

def per_triplet(root):
    return {case.name: {f.stem: score(f) for f in sorted(case.glob('*.bin')) if f.stem.isdigit()}
            for case in sorted(d for d in Path(root).iterdir() if d.is_dir())}


if len(sys.argv) == 4 and sys.argv[1] == '--paired':
    # Two dump sets of the same triplets (before, after): visible-artifact
    # frames and solid area on exactly the triplets both scored.
    before, after = per_triplet(sys.argv[2]), per_triplet(sys.argv[3])
    for case in sorted(set(before) & set(after)):
        common = sorted(set(before[case]) & set(after[case]))
        if not common:
            continue
        art = lambda rows: 100 * np.mean([rows[t] >= 0.1 for t in common])
        area = lambda rows: np.mean([rows[t] for t in common])
        print(f'{case:10s} {len(common):3d} common  artifact frames {art(before[case]):4.0f}% -> '
              f'{art(after[case]):4.0f}%  solid area {area(before[case]):.3f}% -> {area(after[case]):.3f}%')
else:
    for root in sys.argv[1:]:
        out = per_triplet(root)
        print(Path(root).name, '  '.join(
            f'{c}: art {100*np.mean([v >= 0.1 for v in vals.values()]):.0f}% '
            f'solid {np.mean(list(vals.values())):.3f}% n={len(vals)}' for c, vals in out.items() if vals))
