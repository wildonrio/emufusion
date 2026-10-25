"""Learned visibility selector on top of synthesis 24's DIS field (replay bench, 2026-10-24).

The production synthesis blends A warped back and C warped forward along the
per-phase DIS field 50/50, with hand rules for zero motion. Lossless
Scaling's network has a learned visibility branch instead (REA study, methods
only). On the replay dumps, the best per-pixel choice among the four samples
production already takes (warped A, warped C, A, C) would cut the error to
0.28 of a cross-fade from 0.59 (0.45 per 8x8 block). This network predicts that
choice: softmax weights over the four samples, one evaluation per field texel,
blended at full resolution. It starts as production's 50/50 warp blend.

Everything here reproduces the device's arithmetic: the DIS luma pyramid (R8,
quantised per level), GL_LINEAR sampling with edge clamping, RGBA8 hidden
activations (model.store8) and RGBA16F inputs and logits.
"""
import struct
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from .model import conv, sample, store8, upsample

LUMA = (0.299, 0.587, 0.114)
FEATURES = 8
HIDDEN = 16
CANDIDATES = 4  # warped A, warped C, A, C
MOTION_SCALE = 1.0 / 8.0


def read_field(path):
    """The disPhaseF32 plane of a replay dump: (h, w, 2) top-down, y down, field pixels."""
    data = Path(path).read_bytes()
    magic, _, _, _, count = struct.unpack('>iffii', data[:20])
    assert magic == 0x484f4431
    off = 20
    for _ in range(count):
        (n,) = struct.unpack('>i', data[off:off + 4]); off += 4
        name = data[off:off + n].decode(); off += n
        w, h = struct.unpack('>ii', data[off:off + 8]); off += 8
        size = w * h * (16 if name.endswith('F32') else 4)
        if name == 'disPhaseF32':
            field = np.frombuffer(data[off:off + size], '>f4').reshape(h, w, 4)[::-1, :, :2]
            field = field.astype(np.float32)  # native byte order, own copy
            field[..., 1] = -field[..., 1]  # GL texture y is up
            return field
        off += size
    return None


def quantise8(x):
    return torch.round(x.clamp(0, 1) * 255) / 255


def luma_level(rgb, level, divisor=1):
    """The DIS pyramid's luma at one level (GRAY then DOWN, each an R8 target)."""
    y = quantise8((rgb * torch.tensor(LUMA, device=rgb.device).view(1, 3, 1, 1)).sum(1, keepdim=True))
    if divisor != 1:
        y = quantise8(F.avg_pool2d(y, divisor))
    for _ in range(level):
        h, w = y.shape[-2:]
        y = F.pad(y, (0, w % 2, 0, h % 2), mode='replicate')
        y = quantise8(F.avg_pool2d(y, 2))
    return y


def field_samples(image, field, t):
    """image sampled at x - t*v (t > 0: back along v) for each texel of field's grid."""
    return sample(image, -t * field)


class Selector(nn.Module):
    def __init__(self):
        super().__init__()
        self.c1 = conv(FEATURES, HIDDEN)
        self.c2 = conv(HIDDEN, HIDDEN)
        self.c3 = conv(HIDDEN, HIDDEN)
        self.out = conv(HIDDEN, CANDIDATES)
        with torch.no_grad():
            # Start as production's 50/50 warp blend: logits (2, 2, -2, -2).
            self.out.weight.mul_(0.01)
            self.out.bias.copy_(torch.tensor([2.0, 2.0, -2.0, -2.0]))

    def forward(self, features):
        x = store8(self.c1(features))
        x = store8(self.c2(x))
        x = store8(self.c3(x))
        return self.out(x)


def features(a, c, field, level, divisor=1):
    """(N, 8, h, w) at the field's grid: warped/unwarped luma, mismatches, motion."""
    ga = luma_level(a, level, divisor)
    gc = luma_level(c, level, divisor)
    v = field
    wa = sample(ga, -0.5 * v)
    wc = sample(gc, 0.5 * v)
    return torch.cat([wa, wc, ga, gc, (wa - wc).abs(), (ga - gc).abs(),
                      v * MOTION_SCALE], 1)


def generate(a, c, field, logits):
    """Full-resolution output: softmax(logits) over (A warped, C warped, A, C)."""
    h, w = a.shape[-2:]
    fh, fw = field.shape[-2:]
    scale = torch.tensor([w / fw, h / fh], device=a.device, dtype=a.dtype).view(1, 2, 1, 1)
    v = upsample(field, (h, w)) * scale
    aw = sample(a, -0.5 * v)
    cw = sample(c, 0.5 * v)
    weights = torch.softmax(upsample(logits, (h, w)), 1)
    return (weights[:, 0:1] * aw + weights[:, 1:2] * cw + weights[:, 2:3] * a +
            weights[:, 3:4] * c), aw, cw


def changing_mask(a, b, c):
    d = lambda x, y: (x - y).abs().amax(1, keepdim=True)
    return (torch.maximum(d(a, b), d(c, b)) > 2 / 255).float()
