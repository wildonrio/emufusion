"""Train PhaseNet on Thor hold-out triplets and score it like the device hold-out.

usage: python3 -m tools.learned_framegen.train --train DIR [DIR...] --eval DIR
           --out CHECKPOINT_DIR [--steps N] [--batch B] [--crop C]

The score matches the device's `Hold-out quality ... totalVsCrossfade`: over
pixels where the withheld real frame differs from either endpoint by more than
2/255, the summed max-channel error of the generated frame divided by that of
a 50/50 cross-fade (lower is better). The device's own synthesis-15 output in
each eval triplet is scored on the same pixels for a paired comparison.
"""
import argparse
import json
import math
import random
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from . import dataset
from .model import PhaseNet, pad_to, parameter_count


def charbonnier(x, y, mask):
    e = torch.sqrt((x - y) ** 2 + 1e-6).mean(1, keepdim=True)
    return (e * mask).sum() / mask.sum().clamp(min=1)


def census_transform(image, patch=7):
    gray = (image * torch.tensor([0.299, 0.587, 0.114], device=image.device).view(1, 3, 1, 1)).sum(1, keepdim=True)
    p = patch // 2
    patches = F.unfold(F.pad(gray, (p, p, p, p), mode='replicate'), patch)
    diff = patches - gray.flatten(2)
    return diff / torch.sqrt(0.81 + diff ** 2)


def census_loss(x, y, mask):
    d = (census_transform(x) - census_transform(y)) ** 2
    d = (d / (0.1 + d)).mean(1).view_as(mask)
    return (d * mask).sum() / mask.sum().clamp(min=1)


def smoothness(field, image, mask):
    gx = (image[..., :, 1:] - image[..., :, :-1]).abs().mean(1, keepdim=True)
    gy = (image[..., 1:, :] - image[..., :-1, :]).abs().mean(1, keepdim=True)
    fx = (field[..., :, 1:] - field[..., :, :-1]).abs().mean(1, keepdim=True)
    fy = (field[..., 1:, :] - field[..., :-1, :]).abs().mean(1, keepdim=True)
    return ((fx * torch.exp(-10 * gx) * mask[..., :, 1:]).mean() +
            (fy * torch.exp(-10 * gy) * mask[..., 1:, :]).mean())


def holdout_sums(g, a, c, b):
    """Device hold-out score parts for (3,H,W) tensors in [0,1]."""
    d = lambda x, y: (x - y).abs().amax(0)
    changing = torch.maximum(d(a, b), d(c, b)) > 2.0 / 255.0
    return float(d(g, b)[changing].sum()), float(d(0.5 * (a + c), b)[changing].sum())


def load_tensor(path, device):
    return torch.from_numpy(dataset.load_rgb(path).astype(np.float32) / 255.0).permute(2, 0, 1).to(device)


@torch.no_grad()
def evaluate(model, folders, device, limit_per_case=None):
    model.eval()
    sums = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0])  # net, crossfade, device15, crossfade@15
    per_case = defaultdict(int)
    for folder in folders:
        meta = json.loads((folder / 'meta.json').read_text())
        case = meta['case']
        if limit_per_case and per_case[case] >= limit_per_case:
            continue
        per_case[case] += 1
        a, b, c = (load_tensor(folder / f'{k}.png', device) for k in 'ABC')
        t = torch.tensor([float(meta.get('phase', 0.5))], device=device)
        pa, h, w = pad_to(a[None], 32)
        pc, _, _ = pad_to(c[None], 32)
        g = model(pa, pc, t)[0][0, :, :h, :w].clamp(0, 1)
        g = torch.round(g * 255) / 255
        s = sums[case]
        net, cross = holdout_sums(g, a, c, b)
        s[0] += net; s[1] += cross; s[4] += 1
        device_path = folder / 'generated15.png'
        if device_path.exists():
            d15 = load_tensor(device_path, device)
            size = d15.shape[-2:]
            if tuple(size) != (h, w):
                rs = lambda x: F.interpolate(x[None], size=size, mode='area')[0]
                gg, aa, bb, cc = rs(g), rs(a), rs(b), rs(c)
            else:
                gg, aa, bb, cc = g, a, b, c
            n15, c15 = holdout_sums(gg, aa, cc, bb)
            d15s, _ = holdout_sums(d15, aa, cc, bb)
            s[2] += d15s; s[3] += c15
            sums[case + '@15'][0] += n15; sums[case + '@15'][1] += c15
    model.train()
    report = {}
    for case, s in sorted(sums.items()):
        if case.endswith('@15'):
            continue
        at15 = sums.get(case + '@15')
        report[case] = {
            'n': s[4],
            'net': s[0] / max(s[1], 1e-9),
            'net@15': at15[0] / max(at15[1], 1e-9) if at15 else None,
            'device15@15': s[2] / max(s[3], 1e-9) if s[3] else None,
        }
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--train', nargs='+', required=True)
    parser.add_argument('--eval', nargs='+', default=[])
    parser.add_argument('--out', required=True)
    parser.add_argument('--steps', type=int, default=60000)
    parser.add_argument('--batch', type=int, default=16)
    parser.add_argument('--crop', type=int, default=160)
    parser.add_argument('--lr', type=float, default=6e-4)
    parser.add_argument('--levels', type=int, default=5)
    parser.add_argument('--census', type=float, default=0.5)
    parser.add_argument('--smooth', type=float, default=0.02)
    parser.add_argument('--eval-every', type=int, default=5000)
    parser.add_argument('--eval-limit', type=int, default=60)
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--resume', default=None)
    args = parser.parse_args()
    device = torch.device('mps' if torch.backends.mps.is_available() else 'cpu')
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    random.seed(0); torch.manual_seed(0)

    train_folders, held, static = dataset.screen(dataset.triplet_folders(args.train))
    eval_folders, _, _ = dataset.screen(dataset.triplet_folders(args.eval), keep_static=0.0) if args.eval else ([], 0, 0)
    print(f'train {len(train_folders)} triplets (dropped {held} held, {static} static); eval {len(eval_folders)}', flush=True)
    loader = torch.utils.data.DataLoader(
        dataset.TripletDataset(train_folders, crop=args.crop), batch_size=args.batch, shuffle=True,
        num_workers=args.workers, drop_last=True, persistent_workers=args.workers > 0)
    model = PhaseNet(levels=args.levels).to(device)
    if args.resume:
        model.load_state_dict(torch.load(args.resume, map_location=device))
    print(f'parameters {parameter_count(model)} device {device}', flush=True)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    schedule = torch.optim.lr_scheduler.OneCycleLR(optimizer, max_lr=args.lr, total_steps=args.steps,
                                                   pct_start=0.05)
    step, started, running = 0, time.time(), defaultdict(float)
    while step < args.steps:
        for frames, t, mask in loader:
            frames, t, mask = frames.to(device), t.to(device), mask.to(device)
            a, b, c = frames[:, 0], frames[:, 1], frames[:, 2]
            g, aux = model(a, c, t)
            l1 = charbonnier(g, b, mask)
            lc = census_loss(g, b, mask)
            ls = smoothness(aux['f1'], b, mask) + smoothness(aux['f2'], b, mask)
            loss = l1 + args.census * lc + args.smooth * ls
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step(); schedule.step()
            running['l1'] += float(l1.detach()); running['census'] += float(lc.detach()); running['n'] += 1
            step += 1
            if step % 500 == 0:
                n = running.pop('n')
                print(f'step {step} l1 {running["l1"] / n:.4f} census {running["census"] / n:.4f} '
                      f'lr {schedule.get_last_lr()[0]:.2e} {time.time() - started:.0f}s', flush=True)
                running.clear()
            if step % args.eval_every == 0 or step == args.steps:
                torch.save(model.state_dict(), out / 'phasenet.pt')
                if eval_folders:
                    report = evaluate(model, eval_folders, device, args.eval_limit)
                    (out / f'eval-{step}.json').write_text(json.dumps(report, indent=1))
                    for case, r in report.items():
                        print(f'  eval {case:10s} n={r["n"]:3d} net={r["net"]:.3f} net@15={r["net@15"]} '
                              f'device15={r["device15@15"]}', flush=True)
            if step >= args.steps:
                break


if __name__ == '__main__':
    main()
