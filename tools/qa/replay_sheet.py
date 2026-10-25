"""Contact sheets for replay bench dumps (HOD1): what each generated frame got wrong.

Rows: A | real B | C;  generated per level | cross-fade;  |error| heat per level | cross-fade's.
usage: replay_sheet.py DUMP.bin [...] OUT_DIR
"""
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def planes(path):
    data = path.read_bytes()
    magic, phase, limit, synth, count = struct.unpack('>iffii', data[:20])
    assert magic == 0x484f4431, hex(magic)
    off, out = 20, {}
    for _ in range(count):
        (n,) = struct.unpack('>i', data[off:off + 4]); off += 4
        name = data[off:off + n].decode(); off += n
        w, h = struct.unpack('>ii', data[off:off + 8]); off += 8
        out[name] = np.frombuffer(data[off:off + w * h * 4], np.uint8).reshape(h, w, 4)[::-1, :, :3]
        off += w * h * 4
    return phase, out


def fit(img, w, h):
    return img if img.shape[:2] == (h, w) else np.asarray(
        Image.fromarray(img).resize((w, h), Image.BILINEAR))


def sheet(path, out_dir):
    phase, p = planes(path)
    levels = sorted((n for n in p if n.startswith('generated')), key=lambda n: n)
    gs = [p[n] for n in levels]
    h, w = gs[0].shape[:2]
    a, r, c = (fit(p[n], w, h) for n in ('previous', 'reference', 'current'))
    x = ((a.astype(np.float32) + c) / 2).astype(np.uint8)
    err = lambda img: np.abs(img.astype(np.int16) - r).max(-1)
    heat = lambda e: np.repeat(np.clip(e * 4, 0, 255).astype(np.uint8)[..., None], 3, -1)
    rows = [[a, r, c], gs + [x], [heat(err(g)) for g in gs] + [heat(err(x))]]
    cols = max(len(row) for row in rows)
    blank = np.zeros_like(a)
    grid = np.concatenate([np.concatenate(row + [blank] * (cols - len(row)), 1) for row in rows], 0)
    image = Image.fromarray(grid)
    draw = ImageDraw.Draw(image)
    labels = [['A', 'real B', 'C'], [n.replace('generated', 'level ') for n in levels] + ['cross-fade'],
              ['|err| ' + n.replace('generated', '') for n in levels] + ['|err| cross-fade']]
    moving = np.maximum(np.abs(a.astype(np.int16) - r).max(-1), np.abs(c.astype(np.int16) - r).max(-1)) >= 2
    for y, row in enumerate(labels):
        for k, label in enumerate(row):
            draw.text((k * w + 4, y * h + 4), label, fill='yellow')
    target = out_dir / (path.stem + '.png')
    image.save(target)
    maes = ' '.join(f'{n.replace("generated", "")}={err(g)[moving].mean():.2f}' for n, g in zip(levels, gs))
    print(f'{path.stem} phase={phase:.3f} moving={moving.mean() * 100:.1f}% {maes} '
          f'crossfade={err(x)[moving].mean():.2f} -> {target}')


if __name__ == '__main__':
    out = Path(sys.argv[-1]); out.mkdir(parents=True, exist_ok=True)
    for name in sys.argv[1:-1]:
        sheet(Path(name), out)
