"""Reference-free visible artifacts (GPU): content in a frame found in neither real frame.

Per pixel, the 3x3 patch's best match (max-channel abs difference, box-averaged)
among patches of A and of C within +-RADIUS pixels. Invented: > T grey levels;
solid: 3 of 4 neighbours invented too. The real middle frame B gets the same
measure as the floor (new content appearing, noise, the game's own timing), so
only invented area beyond B's counts. A frame has a visible artifact when the
generated frame's solid invented area exceeds B's by MIN_AREA % of the frame.
Comparing against A and C only (not B) forgives where along the motion the
generated frame sits.
usage: replay_invented.py DUMP_DIR [case...] [--plane generated24] [--masks OUT] [--base DUMP_DIR]
       DUMP_DIR from replay_bench.py --dump-dir; --base compares the same triplets
       of an earlier dump (paired). Needs torch (MPS on the Mac, else CPU).
"""
import argparse, sys
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F
sys.path.insert(0, '/Users/tyleryoung/Code/emufusion/tools/qa')
import replay_sheet as R
from PIL import Image

DEV = 'mps' if torch.backends.mps.is_available() else 'cpu'
RADIUS, T, MIN_AREA = 12, 24.0, 0.1


def fit(img, w, h):
    return img if img.shape[:2] == (h, w) else np.asarray(Image.fromarray(img).resize((w, h), Image.BILINEAR))


def t(img):
    return torch.from_numpy(img.astype(np.float32)).permute(2, 0, 1).to(DEV)  # 3,H,W


def best_match(g, refs):
    """Min over shifts/refs of box3(max_c |g - shift(r)|): (H,W)."""
    _, h, w = g.shape
    best = torch.full((h, w), 1e9, device=DEV)
    for r in refs:
        pad = F.pad(r[None], (RADIUS,) * 4, mode='replicate')[0]
        for dy in range(2 * RADIUS + 1):
            rows = pad[:, dy:dy + h, :]                                    # 3,h,W+2R
            # all dx shifts at once: 2R+1, 3, h, w
            shifted = rows.unfold(2, w, 1).permute(2, 0, 1, 3)
            d = (g[None] - shifted).abs().amax(1)                          # S,h,w
            d = F.avg_pool2d(F.pad(d[:, None], (1, 1, 1, 1), mode='replicate'), 3, 1)[:, 0]
            best = torch.minimum(best, d.amin(0))
    return best


def solid(mask):
    m = mask.float()
    n = F.pad(m, (1, 1, 1, 1))
    nb = n[:-2, 1:-1] + n[2:, 1:-1] + n[1:-1, :-2] + n[1:-1, 2:]
    return mask & (nb >= 3)


def frame(path, plane):
    _, p = R.planes(path)
    g = p[plane]; h, w = g.shape[:2]
    a, b, c = (fit(p[k], w, h) for k in ('previous', 'reference', 'current'))
    x = ((a.astype(np.int16) + c) // 2).astype(np.uint8)
    A, C = t(a), t(c)
    out, masks = {}, {}
    for name, img in (('gen', g), ('real', b), ('fade', x)):
        s = solid(best_match(t(img), (A, C)) > T)
        out[name] = 100.0 * s.float().mean().item()
        masks[name] = s.cpu().numpy()
    return out, masks, (a, b, c, g)


def paired(base, var, cases, plane):
    cases = cases or sorted(d.name for d in var.iterdir() if d.is_dir())
    for case in cases:
        names = sorted({f.name for f in (base / case).glob('*.bin')} & {f.name for f in (var / case).glob('*.bin')})
        if not names: continue
        rb, rv = [], []
        for n in names:
            b, _, _ = frame(base / case / n, plane)
            v, _, _ = frame(var / case / n, plane)
            rb.append(max(0.0, b['gen'] - b['real'])); rv.append(max(0.0, v['gen'] - v['real']))
        rb, rv = np.array(rb), np.array(rv)
        print(f"{case:10s} n={len(names):3d}  frames with invented content {100*np.mean(rb >= MIN_AREA):4.0f}% -> "
              f"{100*np.mean(rv >= MIN_AREA):4.0f}%   excess area {rb.mean():.3f}% -> {rv.mean():.3f}%", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dump'); ap.add_argument('cases', nargs='*')
    ap.add_argument('--plane', default='generated24'); ap.add_argument('--masks')
    ap.add_argument('--base')
    args = ap.parse_args()
    if args.base:
        paired(Path(args.base), Path(args.dump), args.cases, args.plane)
        return
    root = Path(args.dump)
    cases = args.cases or sorted(d.name for d in root.iterdir() if d.is_dir())
    total = {}
    for case in cases:
        files = sorted(Path(root, case).glob('*.bin'))
        rows = []
        for f in files:
            r, m, imgs = frame(f, args.plane)
            rows.append((f.stem, r))
            if args.masks and r['gen'] - r['real'] >= MIN_AREA:
                a, b, c, g = imgs
                over = g.copy(); over[m['gen'] & ~m['real']] = (255, 0, 255)
                sheet = np.concatenate([np.concatenate([a, b], 1), np.concatenate([c, over], 1)], 0)
                Path(args.masks, case).mkdir(parents=True, exist_ok=True)
                Image.fromarray(sheet).save(Path(args.masks, case, f'{f.stem}.png'))
        if not rows: continue
        ex = [max(0.0, r['gen'] - r['real']) for _, r in rows]
        exf = [max(0.0, r['fade'] - r['real']) for _, r in rows]
        art = 100 * np.mean([e >= MIN_AREA for e in ex]); artf = 100 * np.mean([e >= MIN_AREA for e in exf])
        total[case] = (art, float(np.mean(ex)))
        worst = sorted(rows, key=lambda t: -(t[1]['gen'] - t[1]['real']))[:3]
        print(f"{case:10s} n={len(rows):3d}  frames with invented content: generated {art:4.0f}%  cross-fade {artf:4.0f}%"
              f"   excess area generated {np.mean(ex):.3f}%  cross-fade {np.mean(exf):.3f}%   worst "
              + ' '.join(f"{n}:{r['gen'] - r['real']:.2f}" for n, r in worst), flush=True)
    if total:
        print(f"MEAN frames {np.mean([v[0] for v in total.values()]):.1f}%  area {np.mean([v[1] for v in total.values()]):.3f}%")


if __name__ == '__main__':
    main()
