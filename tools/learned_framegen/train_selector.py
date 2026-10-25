"""Train the visibility selector (selector.py) on replay-bench DIS fields.

usage: python3 -m tools.learned_framegen.train_selector TRAIN_FIELDS EVAL_FIELDS OUT.pt
       [--data ~/Code/emufusion-training-data] [--epochs 40] [--batch 8]

TRAIN_FIELDS/EVAL_FIELDS hold <case>/<triplet>.bin field dumps from
tools/qa/replay_bench.py --field-only (the device's own synthesis-24 field for
each triplet); the frames come from the capture set of the same name. The
score printed per case is the bench's: generated error over changing pixels
as a fraction of a cross-fade's, beside production's 50/50 warp blend.
"""
import argparse
import math
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from . import selector as S


def load_set(fields_root, frames_root):
    items = []
    for case_dir in sorted(p for p in Path(fields_root).iterdir() if p.is_dir()):
        for dump in sorted(case_dir.glob('*.bin')):
            if not dump.stem.isdigit():
                continue
            folder = Path(frames_root) / case_dir.name / dump.stem
            field = S.read_field(dump)
            if field is None or not (folder / 'B.png').is_file():
                continue
            frames = [np.asarray(Image.open(folder / f'{n}.png').convert('RGB')) for n in 'ABC']
            items.append((case_dir.name, frames, field))
    return items


def geometry(width, field_width):
    divisor = 4 if width > 1280 else 2 if width > 640 else 1
    level = int(round(math.log2(width / divisor / field_width)))
    return divisor, level


def to_batch(items, device, flip=None):
    a, b, c, f = [], [], [], []
    for _, frames, field in items:
        tensors = [torch.from_numpy(x).permute(2, 0, 1).float() / 255 for x in frames]
        v = torch.from_numpy(field).permute(2, 0, 1).float()
        if flip and flip[0]:
            tensors = [x.flip(-1) for x in tensors]
            v = v.flip(-1) * torch.tensor([-1.0, 1.0]).view(2, 1, 1)
        if flip and flip[1]:
            tensors = [x.flip(-2) for x in tensors]
            v = v.flip(-2) * torch.tensor([1.0, -1.0]).view(2, 1, 1)
        a.append(tensors[0]); b.append(tensors[1]); c.append(tensors[2]); f.append(v)
    stack = lambda xs: torch.stack(xs).to(device)
    return stack(a), stack(b), stack(c), stack(f)


def batches(items, size, rng=None):
    """Index batches of one frame and field size each (captures keep native sizes)."""
    groups = {}
    for i, (_, frames, field) in enumerate(items):
        groups.setdefault((frames[0].shape, field.shape), []).append(i)
    out = []
    for members in groups.values():
        if rng is not None:
            members = list(rng.permutation(members))
        out += [members[k:k + size] for k in range(0, len(members), size)]
    if rng is not None:
        out = [out[i] for i in rng.permutation(len(out))]
    return out


def evaluate(model, items, device, batch=8):
    """Per case: (selector, 50/50 warp blend) error over changing pixels / cross-fade's."""
    sums = {}
    model.eval()
    with torch.no_grad():
        for indices in batches(items, batch):
            chunk = [items[i] for i in indices]
            a, b, c, f = to_batch(chunk, device)
            divisor, level = geometry(a.shape[-1], f.shape[-1])
            logits = model(S.features(a, c, f, level, divisor))
            g, aw, cw = S.generate(a, c, f, logits)
            mask = S.changing_mask(a, b, c)
            md = lambda x: ((x - b).abs().amax(1, keepdim=True) * mask).sum((1, 2, 3))
            for k, (case, _, _) in enumerate(chunk):
                s = sums.setdefault(case, np.zeros(3))
                s += [md(g)[k].item(), md(0.5 * (aw + cw))[k].item(), md(0.5 * (a + c))[k].item()]
    model.train()
    return {case: (s[0] / s[2], s[1] / s[2]) for case, s in sums.items() if s[2] > 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('train_fields')
    parser.add_argument('eval_fields')
    parser.add_argument('out')
    parser.add_argument('--data', default=str(Path.home() / 'Code/emufusion-training-data'))
    parser.add_argument('--epochs', type=int, default=40)
    parser.add_argument('--batch', type=int, default=8)
    parser.add_argument('--lr', type=float, default=2e-3)
    parser.add_argument('--still-weight', type=float, default=0.05)
    parser.add_argument('--train-set', default='train', help='capture set holding the training frames')
    args = parser.parse_args()
    device = torch.device('mps' if torch.backends.mps.is_available() else 'cpu')
    torch.manual_seed(0)
    train = load_set(args.train_fields, Path(args.data) / args.train_set)
    held = load_set(args.eval_fields, Path(args.data) / 'eval')
    print(f'train {len(train)} triplets, eval {len(held)}', flush=True)
    model = S.Selector().to(device)
    optimiser = torch.optim.Adam(model.parameters(), lr=args.lr)
    steps = args.epochs * len(batches(train, args.batch))
    schedule = torch.optim.lr_scheduler.OneCycleLR(optimiser, args.lr, total_steps=steps)
    rng = np.random.default_rng(0)
    best = None
    for epoch in range(args.epochs):
        started = time.time()
        total = 0.0
        for indices in batches(train, args.batch, rng):
            chunk = [train[i] for i in indices]
            a, b, c, f = to_batch(chunk, device, flip=(rng.random() < 0.5, rng.random() < 0.5))
            divisor, level = geometry(a.shape[-1], f.shape[-1])
            g, _, _ = S.generate(a, c, f, model(S.features(a, c, f, level, divisor)))
            mask = S.changing_mask(a, b, c)
            weight = mask + args.still_weight * (1 - mask)
            loss = ((g - b).abs().mean(1, keepdim=True) * weight).sum() / weight.sum()
            optimiser.zero_grad()
            loss.backward()
            optimiser.step()
            schedule.step()
            total += loss.item() * len(chunk)
        scores = evaluate(model, held, device)
        mean = float(np.mean([s[0] for s in scores.values()]))
        base = float(np.mean([s[1] for s in scores.values()]))
        line = '  '.join(f'{k} {v[0]:.3f}/{v[1]:.3f}' for k, v in sorted(scores.items()))
        print(f'epoch {epoch + 1:2d} loss {total / len(train) * 255:.3f} eval {mean:.4f} '
              f'(50/50 {base:.4f}) {time.time() - started:.0f}s  {line}', flush=True)
        if best is None or mean < best:
            best = mean
            plain = {k: [float(x) for x in v] for k, v in scores.items()}
            torch.save({'model': model.state_dict(), 'eval': plain, 'epoch': epoch + 1}, args.out)
    print(f'best eval {best:.4f} -> {args.out}')


if __name__ == '__main__':
    main()
