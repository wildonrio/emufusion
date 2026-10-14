"""Synthetic frame-generation behaviour suite with exact ground truth.

Each case is a real-frame pair A, C and the true middle frame B (t = 0.5),
written like the captured hold-out triplets (ROOT/<case>/<NNNN>/{A,B,C}.png and
meta.json), so dis_eval.py scores it the same way:

  python3 -m tools.learned_framegen.synth_suite ROOT
  python3 -m tools.learned_framegen.dis_eval ROOT --per-case 12 --phase

Cases: camera pans (2-24 px per real frame), a static HUD over a fast pan,
textured objects (4-32 px) over a textured background, flat-coloured outlined
sprites (16-48 px) over flat and textured backgrounds, a rotating disc, text
appearing and vanishing between frames, a linear fade, pixel-art scrolling at
2 px (exact) and 1 px (B is a half-pixel resample: approximate). Deterministic.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 480, 270


def texture(w, h, scale, seed):
    base = np.random.default_rng(seed).random((h // scale + 2, w // scale + 2, 3))
    img = Image.fromarray((base * 255).astype(np.uint8)).resize((w + 2 * scale, h + 2 * scale), Image.BICUBIC)
    return np.asarray(img).astype(np.float32)[:h, :w]


def shifted(img, dx, dy):
    """Content moved by (+dx, +dy), bilinear, edge-clamped."""
    h, w = img.shape[:2]
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    sx, sy = np.clip(xs - dx, 0, w - 1), np.clip(ys - dy, 0, h - 1)
    x0, y0 = np.floor(sx).astype(int), np.floor(sy).astype(int)
    x1, y1 = np.minimum(x0 + 1, w - 1), np.minimum(y0 + 1, h - 1)
    fx, fy = (sx - x0)[..., None], (sy - y0)[..., None]
    return (img[y0, x0] * (1 - fx) + img[y0, x1] * fx) * (1 - fy) + \
        (img[y1, x0] * (1 - fx) + img[y1, x1] * fx) * fy


def generate(root):
    root = Path(root)

    def save(case, idx, frames):
        d = root / case / f'{idx:04d}'
        d.mkdir(parents=True, exist_ok=True)
        for k, f in zip('ABC', frames):
            Image.fromarray(np.clip(f + 0.5, 0, 255).astype(np.uint8)).save(d / f'{k}.png')
        (d / 'meta.json').write_text(json.dumps({'case': case, 'phase': 0.5, 'synthetic': True}))

    big = texture(W + 200, H + 200, 12, 1)
    for n in range(12):  # camera pans
        v = [2, 6, 12, 24][n % 4]
        o = 40 + n * 3
        save(f'pan{v:02d}', n // 4, [big[o:o + H, o + k * v // 2:o + k * v // 2 + W] for k in (0, 1, 2)])
    for n in range(12):  # textured square over a textured background
        v = [4, 12, 32][n % 3]
        bg, sq = texture(W, H, 8, 10 + n), texture(80, 80, 6, 50 + n)
        frames = []
        for k in (0, 1, 2):
            f = bg.copy()
            x = 120 + n * 5 + k * v // 2
            f[90:170, x:x + 80] = sq
            frames.append(f)
        save(f'object{v:02d}', n // 3, frames)
    font = ImageFont.load_default()

    def with_text(f):
        im = Image.fromarray(np.clip(f + 0.5, 0, 255).astype(np.uint8))
        dr = ImageDraw.Draw(im)
        dr.rectangle([60, 200, 420, 240], fill=(10, 10, 10))
        dr.text((70, 212), 'Press A to continue the journey', fill=(240, 240, 240), font=font)
        return np.asarray(im).astype(np.float32)

    for n in range(6):  # text appearing / vanishing between the real frames
        pan = [shifted(texture(W, H, 10, 80 + n), k * 2, 0) for k in (0, 1, 2)]
        save('text_appears', n, [pan[0], with_text(pan[1]), with_text(pan[2])])
        save('text_vanishes', n, [with_text(pan[0]), with_text(pan[1]), pan[2]])
    for n in range(6):  # static HUD over a fast pan
        o, v = 30 + n * 7, 16
        frames = [big[o:o + H, o + k * v // 2:o + k * v // 2 + W].copy() for k in (0, 1, 2)]
        for f in frames:
            f[10:40, 10:200] = (20, 20, 60)
            f[18:32, 20:190] = (250, 220, 40)
        save('hud_over_pan', n, frames)
    for n in range(6):  # linear fade, rotating disc
        img = texture(W, H, 10, 120 + n)
        save('fade', n, [img * 1.0, img * 0.7, img * 0.4])
        disc = Image.fromarray(texture(200, 200, 8, 140 + n).astype(np.uint8))
        bg = texture(W, H, 14, 160 + n)
        yy, xx = np.mgrid[0:200, 0:200]
        inside = ((yy - 100) ** 2 + (xx - 100) ** 2 < 95 ** 2)[..., None]
        frames = []
        for k in (0, 1, 2):
            f = bg.copy()
            r = np.asarray(disc.rotate(k * 6, resample=Image.BICUBIC)).astype(np.float32)
            f[35:235, 140:340] = np.where(inside, r, f[35:235, 140:340])
            frames.append(f)
        save('rotate', n, frames)
    tile_rng = np.random.default_rng(7)
    for n in range(6):  # pixel art: nearest-neighbour tiles scrolling 1 and 2 px per real frame
        tile = (tile_rng.random((H // 4 + 4, W // 4 + 40)) > 0.5).astype(np.float32)
        art = np.repeat(np.repeat(tile, 4, 0), 4, 1)[..., None] * np.array([[[200, 80, 40]]]) + 30
        s = 2 * n
        save('pixel_scroll2', n, [art[:H, s + 2 * k:s + 2 * k + W] for k in (0, 1, 2)])
        save('pixel_scroll1', n, [art[:H, s:s + W], shifted(art[:H, s + 1:s + 1 + W], -0.5, 0), art[:H, s + 1:s + 1 + W]])
    for n in range(12):  # game-like sprite over a flat or textured background
        v, flat = [16, 32, 48][n % 3], n // 3 % 2 == 1
        bg = np.full((H, W, 3), (70, 110, 160), np.float32) if flat else texture(W, H, 16, 200 + n)
        spr = Image.new('RGBA', (60, 60), (0, 0, 0, 0))
        dr = ImageDraw.Draw(spr)
        dr.ellipse([2, 2, 57, 57], fill=(230, 60, 40, 255), outline=(20, 10, 10, 255), width=4)
        dr.ellipse([14, 12, 30, 26], fill=(255, 220, 200, 255))
        spr = np.asarray(spr).astype(np.float32)
        alpha = spr[..., 3:4] / 255
        frames = []
        for k in (0, 1, 2):
            f = bg.copy()
            x = 100 + n * 7 + k * v // 2
            f[100:160, x:x + 60] = alpha * spr[..., :3] + (1 - alpha) * f[100:160, x:x + 60]
            frames.append(f)
        save(f"sprite{'flat' if flat else 'tex'}{v:02d}", n // 6, frames)


if __name__ == '__main__':
    generate(sys.argv[1])
