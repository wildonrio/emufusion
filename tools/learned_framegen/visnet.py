"""Learned visibility on top of GPU DIS (synthesis 21): which side to trust.

The weight branch of the REA-studied design (methods only; our own network and
weights), applied to DIS motion: a 8x8-block oracle choosing A-warped,
C-warped or the phase blend would cut the hold-out error 14-43% on most
captured games, and synthesis 21 always blends by the phase alone.

At the flow resolution (where the device's DIS stops), per pixel:
  inputs  A(p), C(q) at the fixed-point sources (as the output shader finds
          them), their max-channel difference, each side's forward-backward
          flow error e/(1+e), t, each side's motion size m/(4+m) and
          photometric visibility check (16 channels, two zero);
  network 3x3 convs 16->16->16->8->1 (clip activations, 8-bit, like RGBA8);
  output  a logit L: alpha = sigmoid(L + log((1-t)/t)) weights A(p) against
          C(q) at full resolution. L = 0 is today's phase blend, so the
          network starts exactly at the shipped behaviour.

usage: /Library/Developer/CommandLineTools/usr/bin/python3 -m tools.learned_framegen.visnet
           --train ROOT --eval ROOT --out DIR [--steps N]
"""
import argparse
import json
import random
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image

from .model import store8


def conv(cin, cout):
    return nn.Conv2d(cin, cout, 3, 1, 1, padding_mode='replicate')


def sample_at(image, pos):
    """Bilinear, edge-clamped sample of image (1,C,H,W) at normalised top-origin pos (1,2,h,w)."""
    _, c, ih, iw = image.shape
    h, w = pos.shape[-2:]
    px = (pos[:, 0] * iw - 0.5).clamp(0, iw - 1)
    py = (pos[:, 1] * ih - 0.5).clamp(0, ih - 1)
    x0 = px.detach().floor().clamp(max=iw - 1); y0 = py.detach().floor().clamp(max=ih - 1)
    fx = (px - x0).unsqueeze(1); fy = (py - y0).unsqueeze(1)
    x0 = x0.long(); y0 = y0.long()
    x1 = (x0 + 1).clamp(max=iw - 1); y1 = (y0 + 1).clamp(max=ih - 1)
    flat = image.reshape(1, c, ih * iw)

    def take(yy, xx):
        return flat.gather(2, (yy * iw + xx).view(1, 1, h * w).expand(1, c, h * w)).view(1, c, h, w)

    return (take(y0, x0) * (1 - fx) + take(y0, x1) * fx) * (1 - fy) + \
        (take(y1, x0) * (1 - fx) + take(y1, x1) * fx) * fy


def grid(h, w, device):
    ys = (torch.arange(h, device=device, dtype=torch.float32) + 0.5) / h
    xs = (torch.arange(w, device=device, dtype=torch.float32) + 0.5) / w
    gy, gx = torch.meshgrid(ys, xs, indexing='ij')
    return torch.stack((gx, gy))[None]


def sources(flow_ac, flow_ca, t, h, w):
    """Fixed-point sources on an h x w grid, as the output shader computes them."""
    fsize = torch.tensor([flow_ac.shape[-1], flow_ac.shape[-2]], device=flow_ac.device,
                         dtype=torch.float32).view(1, 2, 1, 1)
    u = grid(h, w, flow_ac.device)
    fac = lambda p: sample_at(flow_ac, p) / fsize
    fca = lambda p: sample_at(flow_ca, p) / fsize
    p = u - t * fac(u); q = u - (1 - t) * fca(u)
    for _ in range(2):
        p = u - t * fac(p); q = u - (1 - t) * fca(q)
    return p, q, fac, fca, fsize


class VisNet(nn.Module):
    def __init__(self, width=16):
        super().__init__()
        self.c0 = conv(16, width)
        self.c1 = conv(width, width)
        self.c2 = conv(width, 8)
        self.c3 = conv(8, 1)
        with torch.no_grad():
            self.c3.weight.normal_(0.0, 1e-3)
            self.c3.bias.zero_()

    def features(self, a, c, flow_ac, flow_ca, t):
        h, w = flow_ac.shape[-2:]
        p, q, fac, fca, fsize = sources(flow_ac, flow_ca, t, h, w)
        aw, cw = sample_at(a, p), sample_at(c, q)
        diff = (aw - cw).abs().amax(1, keepdim=True)
        ga, gc = fac(p), fca(q)
        ea = ((ga + fca(p + ga)) * fsize).norm(dim=1, keepdim=True)
        ec = ((gc + fac(q + gc)) * fsize).norm(dim=1, keepdim=True)
        tt = t.expand(1, 1, h, w)
        # Motion size at each source (pixels).
        ma = (ga * fsize).norm(dim=1, keepdim=True)
        mc = (gc * fsize).norm(dim=1, keepdim=True)
        # Photometric visibility: does A's pixel reappear in C where its flow
        # says (and C's in A)? A pixel covered by then fails its own check.
        va = (aw - sample_at(c, p + ga)).abs().amax(1, keepdim=True)
        vc = (cw - sample_at(a, q + gc)).abs().amax(1, keepdim=True)
        zero = torch.zeros_like(tt)
        return torch.cat([aw, cw, diff, ea / (1 + ea), ec / (1 + ec), tt, ma / (4 + ma), mc / (4 + mc),
                          va, vc, zero, zero], 1)

    def forward(self, x):
        x = store8(self.c0(x))
        x = store8(self.c1(x))
        x = store8(self.c2(x))
        return self.c3(x)


def synthesize(a, c, flow_ac, flow_ca, t, logit):
    h, w = a.shape[-2:]
    p, q, *_ = sources(flow_ac, flow_ca, t, h, w)
    up = F.interpolate(logit, size=(h, w), mode='bilinear', align_corners=False)
    tc = t.clamp(0.02, 0.98)
    alpha = torch.sigmoid(up + torch.log((1 - tc) / tc))
    return alpha * sample_at(a, p) + (1 - alpha) * sample_at(c, q)


def load_triplet(folder, device):
    img = lambda k: torch.from_numpy(np.asarray(Image.open(folder / f'{k}.png').convert('RGB')).astype(
        np.float32) / 255).permute(2, 0, 1)[None].to(device)
    flows = torch.from_numpy(np.load(folder / 'dis.npy').astype(np.float32)).permute(2, 0, 1)[None].to(device)
    t = float(json.loads((folder / 'meta.json').read_text()).get('phase', 0.5))
    return img('A'), img('B'), img('C'), flows[:, 0:2], flows[:, 2:4], torch.tensor(t, device=device).view(1, 1, 1, 1)


def usable(folder):
    if not (folder / 'dis.npy').exists():
        return False
    a, b, c = (np.asarray(Image.open(folder / f'{k}.png').convert('L'), np.int16) for k in 'ABC')
    return np.abs(a - b).mean() > 0.02 and np.abs(b - c).mean() > 0.02 and np.abs(a - c).mean() > 0.05


def holdout(g, a, c, b):
    d = lambda x, y: (x - y).abs().amax(1)
    changing = torch.maximum(d(a, b), d(c, b)) > 2 / 255
    return float(d(g, b)[changing].sum()), float(d(0.5 * (a + c), b)[changing].sum())


@torch.no_grad()
def evaluate(net, folders, device, per_case=40):
    net.eval()
    sums = defaultdict(lambda: np.zeros(3)); counts = defaultdict(int)
    for folder in folders:
        case = json.loads((folder / 'meta.json').read_text())['case']
        if counts[case] >= per_case:
            continue
        counts[case] += 1
        a, b, c, fac, fca, t = load_triplet(folder, device)
        g0 = synthesize(a, c, fac, fca, t, torch.zeros(1, 1, *fac.shape[-2:], device=device))
        g1 = synthesize(a, c, fac, fca, t, net(net.features(a, c, fac, fca, t)))
        q = lambda x: torch.round(x.clamp(0, 1) * 255) / 255
        e0, cf = holdout(q(g0), a, c, b); e1, _ = holdout(q(g1), a, c, b)
        sums[case] += [e0, e1, cf]
    net.train()
    return {case: (s[0] / s[2], s[1] / s[2]) for case, s in sorted(sums.items())}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--train', nargs='+', required=True)
    parser.add_argument('--eval', nargs='+', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--steps', type=int, default=20000)
    parser.add_argument('--accumulate', type=int, default=8)
    parser.add_argument('--lr', type=float, default=1e-3)
    parser.add_argument('--eval-every', type=int, default=2000)
    args = parser.parse_args()
    device = torch.device('mps' if torch.backends.mps.is_available() else 'cpu')
    random.seed(0); torch.manual_seed(0)
    find = lambda roots: [m.parent for r in roots for m in sorted(Path(r).glob('*/*/meta.json'))
                          if not m.parent.parent.name.startswith('_')]
    train = [f for f in find(args.train) if usable(f)]
    evals = [f for f in find(args.eval) if usable(f)]
    print(f'train {len(train)} eval {len(evals)}', flush=True)
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    net = VisNet().to(device)
    opt = torch.optim.Adam(net.parameters(), lr=args.lr)
    base = evaluate(net, evals, device)
    print('  start', ' '.join(f'{k}={v[0]:.3f}' for k, v in base.items()), flush=True)
    step, running, started = 0, [0.0, 0.0], time.time()
    while step < args.steps:
        random.shuffle(train)
        for folder in train:
            a, b, c, fac, fca, t = load_triplet(folder, device)
            if random.random() < 0.5:  # time reversal
                a, c, fac, fca, t = c, a, fca, fac, 1 - t
            logit = net(net.features(a, c, fac, fca, t))
            g = synthesize(a, c, fac, fca, t, logit)
            # Only where the candidates disagree does the choice matter.
            with torch.no_grad():
                h, w = a.shape[-2:]
                p, q, *_ = sources(fac, fca, t, h, w)
                weight = 0.05 + ((sample_at(a, p) - sample_at(c, q)).abs().amax(1, keepdim=True) > 2 / 255).float()
            loss = (torch.sqrt((g - b) ** 2 + 1e-6) * weight).sum() / (weight.sum() * 3)
            (loss / args.accumulate).backward()
            running[0] += float(loss.detach()); running[1] += 1
            if int(running[1]) % args.accumulate == 0:
                torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
                opt.step(); opt.zero_grad(set_to_none=True); step += 1
                if step % 250 == 0:
                    print(f'step {step} loss {running[0] / running[1]:.5f} {time.time() - started:.0f}s', flush=True)
                    running = [0.0, 0.0]
                if step % args.eval_every == 0 or step >= args.steps:
                    torch.save(net.state_dict(), out / 'visnet.pt')
                    report = evaluate(net, evals, device)
                    print('  eval', ' '.join(f'{k}={v[0]:.3f}->{v[1]:.3f}' for k, v in report.items()), flush=True)
                if step >= args.steps:
                    break


if __name__ == '__main__':
    main()
