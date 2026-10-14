"""Training triplets captured on the Thor by the hold-out path (train_capture.py).

Each triplet folder holds A.png (previous real frame), B.png (the withheld real
frame between them), C.png (next real frame) and meta.json (phase of B in the
A..C span, case, system). Game frames are the owner's local data and never
leave this machine or enter the repository.
"""
import json
import random
from pathlib import Path

import numpy as np
import torch
from PIL import Image


def load_rgb(path):
    return np.asarray(Image.open(path).convert('RGB'))


def triplet_folders(roots):
    found = []
    for root in roots:
        for meta in sorted(Path(root).glob('*/*/meta.json')):
            if meta.parent.parent.name.startswith('_'):
                continue
            found.append(meta.parent)
    return found


def frame_change(a, b):
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean())


def screen(folders, keep_static=0.05, seed=0):
    """Drop held frames (B equal to an endpoint) and most fully static triplets."""
    rng = random.Random(seed)
    kept, held, static = [], 0, 0
    for folder in folders:
        a, b, c = (load_rgb(folder / f'{k}.png') for k in 'ABC')
        if a.shape != b.shape or b.shape != c.shape:
            continue
        if frame_change(a, b) < 0.02 or frame_change(b, c) < 0.02:
            held += 1
            continue
        if frame_change(a, c) < 0.05 and rng.random() > keep_static:
            static += 1
            continue
        kept.append(folder)
    return kept, held, static


class TripletDataset(torch.utils.data.Dataset):
    def __init__(self, folders, crop=160, augment=True):
        self.folders = list(folders)
        self.crop = crop
        self.augment = augment

    def __len__(self):
        return len(self.folders)

    def __getitem__(self, index):
        folder = self.folders[index]
        meta = json.loads((folder / 'meta.json').read_text())
        t = float(meta.get('phase', 0.5))
        a, b, c = (load_rgb(folder / f'{k}.png') for k in 'ABC')
        h, w = a.shape[:2]
        # Small native (2-D) images are also seen at 2x nearest, the scale the
        # device can analyse them at.
        if self.augment and max(h, w) <= 400 and random.random() < 0.5:
            a, b, c = (np.repeat(np.repeat(v, 2, 0), 2, 1) for v in (a, b, c))
            h, w = a.shape[:2]
        size = self.crop
        mask = np.ones((h, w), np.float32)
        if h < size or w < size:
            ph, pw = max(0, size - h), max(0, size - w)
            pad = ((0, ph), (0, pw), (0, 0))
            a, b, c = (np.pad(x, pad, mode='edge') for x in (a, b, c))
            mask = np.pad(mask, ((0, ph), (0, pw)))
            h, w = a.shape[:2]
        y = random.randint(0, h - size) if self.augment else (h - size) // 2
        x = random.randint(0, w - size) if self.augment else (w - size) // 2
        a, b, c = (v[y:y + size, x:x + size] for v in (a, b, c))
        mask = mask[y:y + size, x:x + size]
        if self.augment:
            if random.random() < 0.5:
                a, b, c, mask = (v[:, ::-1] for v in (a, b, c, mask))
            if random.random() < 0.2:
                a, b, c, mask = (v[::-1] for v in (a, b, c, mask))
            if random.random() < 0.5:
                a, c, t = c, a, 1.0 - t
        stack = np.stack([a, b, c]).astype(np.float32) / 255.0
        frames = torch.from_numpy(np.ascontiguousarray(stack)).permute(0, 3, 1, 2)
        return frames, torch.tensor(t, dtype=torch.float32), \
            torch.from_numpy(np.ascontiguousarray(mask))[None]
