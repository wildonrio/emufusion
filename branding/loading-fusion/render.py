#!/opt/homebrew/bin/python3
"""Render the EmuFusion "fusion" boot loop from the app icon.

The icon is separated by colour, not geometry: each rainbow arm of the swirl,
the dark D-pad body and the light button body become their own layer. The
layers always sum back to the exact icon. Rendered in linear HDR:

  0.0-1.7 s  the layers circle as rings of liquid light (twisted into spiral
             arms, rippled by flowing noise), drawn inward by spectral light
             streams; they spin faster as they contract and unwind
  1.7 s      every layer locks into place at once: the fused icon ignites with
             an anamorphic streak, chromatic shockwave, particle burst and
             camera punch
  1.7-5.2 s  the icon floats in god rays, circled by orbiting comets of light;
             a glass sweep crosses it and the wordmark resolves beneath
  5.2-6.0 s  the colours spin apart into a vortex and collapse into a point of
             light, which seeds the next loop

Bloom + ACES tone mapping, vignette, chromatic aberration and film grain finish
each frame. Output: 1920x1080, 60 fps, H.264, silent. Needs numpy, Pillow and
OpenCV (Homebrew python3).

usage: render.py [OUTPUT.mp4] | SEGMENT.mkv START STOP | --preview T [T ...] | --check-loop
(render_all.sh renders segments in parallel and encodes loading.mp4)
"""
import math
from pathlib import Path
import subprocess
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

cv2.setNumThreads(2)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ICON_PATH = ROOT / 'unified-android/res/drawable/lucent_icon.png'
FONT_PATH = Path('/Users/tyleryoung/Library/Android/sdk/platforms/android-21/data/fonts/Roboto-Light.ttf')

W, H, FPS = 1920, 1080, 60
T = 6.0
FRAMES = int(T * FPS)
CX, CY = W / 2, 470.0
ICON = 560
R = ICON / 2
TF = 1.70                       # fusion instant
OUTRO = 5.15                    # implosion start
SHUTTER = 0.5 / FPS             # 180-degree shutter

rng = np.random.default_rng(91)


# ---------------------------------------------------------------- helpers
def clamp01(x):
    return np.clip(x, 0.0, 1.0)


def smooth(x):
    x = clamp01(x)
    return x * x * (3 - 2 * x)


def ease_out(x, k=3.0):
    return 1 - (1 - clamp01(x)) ** k


def ease_in(x, k=3.0):
    return clamp01(x) ** k


def blur(img, sigma):
    return cv2.GaussianBlur(img, (0, 0), sigma) if sigma > 0.05 else img


def srgb_to_linear(a):
    return (a / 255.0) ** 2.2


def hue_rgb(h, s=1.0):
    h = np.asarray(h, np.float32) % 1.0
    rgb = np.stack([np.clip(np.abs(h * 6 - 3) - 1, 0, 1),
                    np.clip(2 - np.abs(h * 6 - 2), 0, 1),
                    np.clip(2 - np.abs(h * 6 - 4), 0, 1)], -1)
    return ((1 - s) + s * rgb).astype(np.float32)


SPECTRUM = np.array([0.0, 0.05, 0.11, 0.16, 0.30, 0.47, 0.58, 0.68, 0.76, 0.84], np.float32)


def spectral(u, s=0.95):
    """Map u in [0,1) onto the icon's arm colours (red..magenta)."""
    u = np.asarray(u, np.float32) % 1.0
    idx = u * (len(SPECTRUM) - 1)
    lo = np.floor(idx).astype(int)
    hi = np.minimum(lo + 1, len(SPECTRUM) - 1)
    f = idx - lo
    return hue_rgb(SPECTRUM[lo] * (1 - f) + SPECTRUM[hi] * f, s)


def splat(buf, x, y, rgb):
    """Bilinear additive splat of N points with (N,3) linear intensities."""
    x = np.asarray(x, np.float32).ravel()
    y = np.asarray(y, np.float32).ravel()
    rgb = np.broadcast_to(np.asarray(rgb, np.float32), (len(x), 3)) if np.ndim(rgb) == 1 \
        else np.asarray(rgb, np.float32).reshape(-1, 3)
    ok = (x >= 0) & (x < W - 1) & (y >= 0) & (y < H - 1) & np.isfinite(rgb).all(1)
    x, y, rgb = x[ok], y[ok], rgb[ok]
    if not len(x):
        return
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    fx, fy = x - x0, y - y0
    flat = buf.reshape(-1, 3)
    for dx, dy, wgt in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)),
                        (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
        index = (y0 + dy) * W + (x0 + dx)
        for c in range(3):
            flat[:, c] += np.bincount(index, weights=wgt * rgb[:, c], minlength=W * H)


def over(dst, rgba_lin, ox, oy):
    """Alpha-composite a linear (h,w,4) array onto dst at (ox, oy)."""
    h, w = rgba_lin.shape[:2]
    x0, y0 = max(0, ox), max(0, oy)
    x1, y1 = min(W, ox + w), min(H, oy + h)
    if x1 <= x0 or y1 <= y0:
        return
    src = rgba_lin[y0 - oy:y1 - oy, x0 - ox:x1 - ox]
    a = src[..., 3:4]
    dst[y0:y1, x0:x1] = dst[y0:y1, x0:x1] * (1 - a) + src[..., :3] * a


def add_at(dst, src, ox, oy):
    h, w = src.shape[:2]
    x0, y0 = max(0, ox), max(0, oy)
    x1, y1 = min(W, ox + w), min(H, oy + h)
    if x1 > x0 and y1 > y0:
        dst[y0:y1, x0:x1] += src[y0 - oy:y1 - oy, x0 - ox:x1 - ox]


def to_linear_rgba(img):
    a = np.asarray(img, np.float32)
    out = np.empty_like(a)
    out[..., :3] = srgb_to_linear(a[..., :3])
    out[..., 3] = a[..., 3] / 255.0
    return out


def saturation(rgb):
    mx, mn = rgb.max(-1), rgb.min(-1)
    return (mx - mn) / (mx + 1e-4)


def fbm(shape, octaves, seed):
    g = np.random.default_rng(seed)
    out = np.zeros(shape, np.float32)
    amp = 1.0
    for o in range(octaves):
        cells = (max(2, shape[0] // (64 >> o)), max(2, shape[1] // (64 >> o)))
        n = g.random(cells).astype(np.float32)
        out += amp * cv2.resize(n, (shape[1], shape[0]), interpolation=cv2.INTER_CUBIC)
        amp *= 0.5
    return (out - out.min()) / (out.max() - out.min())


# ---------------------------------------------------------------- icon layers
icon_img = Image.open(ICON_PATH).convert('RGBA').resize((ICON, ICON), Image.LANCZOS)
_lin = to_linear_rgba(icon_img)
_sat = saturation(_lin[..., :3])
ICON_EMIT = (_lin[..., :3] * (_sat ** 2)[..., None] * _lin[..., 3:4]).astype(np.float32)

_hsv = cv2.cvtColor(np.asarray(icon_img, np.float32)[..., :3] / 255.0, cv2.COLOR_RGB2HSV)
_chroma = smooth((_hsv[..., 1] - 0.18) / 0.30)
_dark = (1 - _chroma) * (1 - smooth((_hsv[..., 2] - 0.30) / 0.35))
_weights = [_dark, (1 - _chroma) - _dark]           # D-pad body, button body
for centre in (0, 60, 120, 180, 240, 300):          # the swirl's rainbow arms
    d = np.abs((_hsv[..., 0] - centre + 180) % 360 - 180)
    _weights.append(_chroma * np.where(d < 60, np.cos(d / 60 * math.pi / 2) ** 2, 0))
LAYERS = []
for wgt in _weights:
    layer = np.empty((ICON, ICON, 4), np.float32)
    layer[..., 3] = _lin[..., 3] * wgt
    layer[..., :3] = _lin[..., :3] * layer[..., 3:4]
    LAYERS.append(layer)
assert np.allclose(sum(LAYERS)[..., 3], _lin[..., 3], atol=1e-4)
CHROMATIC = [False, False] + [True] * 6
#                 dark  light  red   yel   grn   cyan  blue  mag
L_RING = np.array([300, 360,   520,  600,  460,  660,  560,  620], np.float32)   # ring radius px
L_SCALE = np.array([0.15, 0.20, 0.35, 0.50, 0.30, 0.60, 0.40, 0.55], np.float32)
L_SPIN = 2 * math.pi * np.array([1.30, 1.55, 1.70, 2.05, 1.45, 2.30, 1.85, 2.15], np.float32) \
    + np.array([0.0, math.pi, 0.9, 2.6, 4.2, 1.7, 3.4, 5.1], np.float32)
L_TWIST = np.array([3.2, 3.6, 4.8, 5.4, 4.4, 6.0, 5.0, 5.7], np.float32)
L_UNSPIN = np.array([3.0, -3.4, 4.2, -4.8, 5.0, -5.6, 6.0, -6.4], np.float32)     # implosion

# Twinkle points sampled from bright, saturated swirl pixels.
_mx = _lin[..., :3].max(-1)
_cand = np.argwhere((_mx > 0.55) & (_sat > 0.5) & (_lin[..., 3] > 0.9))
_pick = _cand[rng.choice(len(_cand), 70, replace=False)]
TW_Y, TW_X = _pick[:, 0].astype(np.float32) - R, _pick[:, 1].astype(np.float32) - R
TW_PHASE = rng.random(70)
TW_COL = _lin[_pick[:, 0], _pick[:, 1], :3]

# ---------------------------------------------------------------- backdrop
yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
rad = np.hypot((xx - CX) / W, (yy - CY) / H) * 2
DIST = np.hypot(xx - CX, yy - CY)
THETA = np.arctan2(yy - CY, xx - CX)
BG = np.stack([0.010 + 0.016 * np.exp(-rad * 2.2),
               0.008 + 0.010 * np.exp(-rad * 2.2),
               0.020 + 0.045 * np.exp(-rad * 2.0)], -1).astype(np.float32)
_n1 = fbm((270, 480), 5, 3)
_n2 = fbm((270, 480), 5, 4)
_neb = cv2.resize(np.clip(_n1 * 1.6 - 0.75, 0, 1) ** 2, (W, H), interpolation=cv2.INTER_LINEAR)
_mix = cv2.resize(_n2, (W, H), interpolation=cv2.INTER_LINEAR)
NEBULA = (_neb[..., None] * (np.array([0.05, 0.012, 0.09]) * _mix[..., None] +
                              np.array([0.010, 0.025, 0.08]) * (1 - _mix[..., None]))
          * (0.35 + 0.65 * np.exp(-rad * 1.4))[..., None]).astype(np.float32)
STARS_X = rng.random(500) * W
STARS_Y = rng.random(500) * H
STARS_B = (rng.random(500) ** 3) * 0.25 + 0.01
STARS_P = rng.random(500)
STARS_K = rng.integers(1, 4, 500)
# Flowing liquid displacement for the swirling layers (padded for scrolling).
PAD = 480
FLOW_X = cv2.resize(fbm(((H + PAD) // 6, (W + PAD) // 6), 4, 11), (W + PAD, H + PAD)) * 2 - 1
FLOW_Y = cv2.resize(fbm(((H + PAD) // 6, (W + PAD) // 6), 4, 12), (W + PAD, H + PAD)) * 2 - 1

# God rays behind the fused icon: colour follows the swirl's angle.
RAY_COL = spectral((THETA / (2 * math.pi) + 0.62) % 1.0, 0.8)
RAY_FALL = (np.exp(-np.maximum(DIST - R * 0.85, 0) / 330.0) * clamp01((DIST - R * 0.7) / 60)).astype(np.float32)

# Light streams: spirals that all arrive at the core at TF.
NS = 140
S_HUE = rng.random(NS)
S_THETA0 = rng.random(NS) * 2 * math.pi
S_R0 = 760 + rng.random(NS) * 760
S_START = -0.25 + rng.random(NS) * 0.85
S_SPIN = 2.6 + rng.random(NS) * 1.4
S_GAIN = 1.0 + rng.random(NS) * 1.5
S_TILT = 0.80 + rng.random(NS) * 0.2

# Fusion burst.
NB = 3200
B_ANG = rng.random(NB) * 2 * math.pi
B_SPEED = 250 + rng.random(NB) ** 1.8 * 1700
B_DRAG = 1.6 + rng.random(NB) * 2.4
B_LIFE = 0.45 + rng.random(NB) * 1.4
B_HUE = rng.random(NB)
B_B = 0.4 + rng.random(NB) ** 3 * 4.0
B_SWIRL = (rng.random(NB) - 0.3) * 1.2

# Orbiting comets: (semi-major, squash, roll, period s, phase, hue, tail rad, gain)
COMETS = [
    (R * 1.55, 0.21, math.radians(-15), 2.6, 0.3, 0.02, 4.4, 1.0),
    (R * 1.36, 0.30, math.radians(22), 3.3, 2.6, 0.55, 3.9, 0.85),
    (R * 1.86, 0.15, math.radians(-4), 4.1, 4.4, 0.30, 3.2, 0.7),
]
NA = 1800
A_RING = rng.integers(0, len(COMETS), NA)
A_PHI = rng.random(NA) * 2 * math.pi
A_SPREAD = 1 + rng.normal(0, 0.05, NA)
A_PH = rng.random(NA)
A_B = 0.15 + rng.random(NA) ** 5 * 1.6

font_big = ImageFont.truetype(str(FONT_PATH), 56)


# ---------------------------------------------------------------- timeline
def cam(t):
    """Camera zoom and shake (applied to the final image)."""
    zoom = 1.025 + 0.025 * (0.5 - 0.5 * math.cos(2 * math.pi * t / T))
    sx = sy = 0.0
    if t >= TF:
        dt = t - TF
        zoom += 0.045 * math.exp(-dt / 0.16) * math.cos(dt * 18)
        amp = 9 * math.exp(-dt / 0.14)
        sx = amp * math.sin(dt * 2 * math.pi * 23)
        sy = amp * math.cos(dt * 2 * math.pi * 17)
    return zoom, sx, sy


def implode(t):
    return float(ease_in((t - OUTRO) / 0.62, 2.2))


def hold_pose(t):
    """Fused-icon breathing: (scale, vertical bob) while it floats."""
    dt = t - TF
    wobble = 0.075 * math.exp(-dt / 0.2) * math.cos(dt * 2 * math.pi / 0.34)
    breathe = 0.012 * math.sin(2 * math.pi * dt / 1.8) * float(smooth(dt / 0.6))
    bob = 5 * math.sin(2 * math.pi * dt / 2.4) * float(smooth(dt / 0.8))
    return 1 + wobble + breathe, bob


def layer_state(t):
    """(remaining assembly k, implosion, centre y, base scale, opacity, glow)."""
    if t < TF:
        u = float(clamp01(t / TF))
        e = u ** 1.7                            # spin accelerates into the lock
        return 1 - e, 0.0, CY, 1.0, float(smooth(t / 0.8)), 0.4 + 1.4 * e ** 3
    imp = implode(t)
    scale, bob = hold_pose(t)
    return 0.0, imp, CY + bob, scale, 1.0, 0.55 + 6.0 * imp ** 1.5


def layer_buffers(t):
    """Warp every colour layer for time t; returns region and premul sums."""
    k, imp, cy, base, _, _ = layer_state(t)
    ring = L_RING * k ** 1.5 * (1 + 0.8 * k ** 8)   # sweeps in from the frame edges
    scale = base * (1 + L_SCALE * k ** 1.3) * (1 - 0.985 * imp ** 1.3)
    spin = L_SPIN * k + L_UNSPIN * imp ** 1.6
    twist = L_TWIST * k + 7.0 * imp ** 1.5
    amp = 30.0 * k + 14.0 * imp
    reach = float(np.max(ring + R * scale * 1.45)) + amp + 8
    x0, x1 = max(0, int(CX - reach)), min(W, int(math.ceil(CX + reach)))
    y0, y1 = max(0, int(cy - reach)), min(H, int(math.ceil(cy + reach)))
    gx, gy = np.meshgrid(np.arange(x0, x1, dtype=np.float32) - CX,
                         np.arange(y0, y1, dtype=np.float32) - cy)
    if amp > 0.05:
        oy, ox = int(70 * t) % PAD, int(45 * t) % PAD
        gx = gx + amp * FLOW_X[y0 + oy:y1 + oy, x0 + ox:x1 + ox]
        gy = gy + amp * FLOW_Y[y0 + oy:y1 + oy, x0 + ox:x1 + ox]
    r = np.hypot(gx, gy)
    theta = np.arctan2(gy, gx)
    colour = np.zeros((y1 - y0, x1 - x0, 3), np.float32)
    cover = np.zeros((y1 - y0, x1 - x0), np.float32)
    glow = np.zeros_like(colour)
    for i, layer in enumerate(LAYERS):
        rs = (r - ring[i]) / scale[i]                  # source radius, icon px
        rho = np.maximum(rs, 0) / R
        ts = theta - spin[i] - twist[i] * (0.75 * rho + 0.35 / (rho + 0.35) - 1.0)
        mx = np.where(rs >= 0, R - 0.5 + rs * np.cos(ts), -9).astype(np.float32)
        my = np.where(rs >= 0, R - 0.5 + rs * np.sin(ts), -9).astype(np.float32)
        out = cv2.remap(layer, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                        borderValue=(0, 0, 0, 0))
        if k > 0.01:
            # Thin the layer's core while it is a ring, so no hard circle forms.
            out *= (1 - k ** 0.7 * (1 - smooth(rs / (0.4 * R))))[..., None]
        colour += out[..., :3]
        cover += out[..., 3]
        if CHROMATIC[i]:
            glow += out[..., :3]
    return (x0, y0, x1, y1), colour, cover, glow


def draw_layers(scene, emit, t):
    k, imp, _, _, alpha, glow_gain = layer_state(t)
    # Motion blur: average sub-frames across the shutter; more while spinning fast.
    speed = 2.0 * math.sqrt(max(0.0, 1 - k)) / TF * float(np.max(L_SPIN)) if t < TF else 6 * imp
    subs = int(np.clip(1 + speed * 0.5, 1, 6))
    acc = None
    for s in range(subs):
        ts = t - SHUTTER * s / (subs - 1) if subs > 1 else t
        box, colour, cover, glow = layer_buffers(ts)
        if acc is None:
            acc = [box, colour, cover, glow]
            continue
        # Sub-frames can cover different regions; accumulate into the union.
        bx = (min(acc[0][0], box[0]), min(acc[0][1], box[1]), max(acc[0][2], box[2]), max(acc[0][3], box[3]))
        for j, buf in ((1, colour), (2, cover), (3, glow)):
            if bx != acc[0]:
                grown = np.zeros((bx[3] - bx[1], bx[2] - bx[0]) + acc[j].shape[2:], np.float32)
                grown[acc[0][1] - bx[1]:acc[0][3] - bx[1], acc[0][0] - bx[0]:acc[0][2] - bx[0]] = acc[j]
                acc[j] = grown
            acc[j][box[1] - bx[1]:box[3] - bx[1], box[0] - bx[0]:box[2] - bx[0]] += buf
        acc[0] = bx
    (x0, y0, x1, y1), colour, cover, glow = acc
    colour, cover, glow = colour / subs, cover / subs, glow / subs
    bright = 1 + 5.0 * imp ** 1.5
    a = np.clip(cover * alpha, 0, 1)[..., None]
    region = scene[y0:y1, x0:x1]
    scene[y0:y1, x0:x1] = region * (1 - a) + colour * alpha * bright
    emit[y0:y1, x0:x1] += glow * alpha * glow_gain


# ---------------------------------------------------------------- effects
def streams(emit, t):
    if t >= TF:
        return
    layer = np.zeros_like(emit)
    for i in range(NS):
        if t < max(0.0, S_START[i]):
            continue
        p = (t - S_START[i]) / (TF - S_START[i])
        head = p ** 1.9
        tail = max(0.0, head - 0.42)
        if head <= 0:
            continue
        u = np.linspace(tail, head, 560)
        r = S_R0[i] * (1 - u) ** 1.7 + 3
        th = S_THETA0[i] + S_SPIN[i] * u ** 1.15
        x = CX + r * np.cos(th)
        y = CY + r * np.sin(th) * S_TILT[i]
        w = clamp01((u - tail) / max(1e-4, head - tail)) ** 2.4
        fade = float(smooth(t / 0.35)) * float(smooth(p / 0.12))
        hot = 1 + 6 * clamp01((u - 0.80) / 0.2) ** 2
        col = spectral(S_HUE[i] + 0.12 * u)
        splat(layer, x, y, (w * hot * S_GAIN[i] * fade * 0.15)[:, None] * col)
    emit += layer * 0.6 + blur(layer, 1.6) * 2.2


def burst(emit, t):
    dt0 = t - TF
    if dt0 <= 0 or dt0 > 2.3:
        return
    for s in range(6):
        dt = dt0 - SHUTTER * 3.0 * s / 5
        if dt <= 0:
            continue
        dist = B_SPEED / B_DRAG * (1 - np.exp(-B_DRAG * dt))
        ang = B_ANG + B_SWIRL * (1 - np.exp(-1.5 * dt))
        life = clamp01(dt / B_LIFE)
        inten = B_B * (1 - life) ** 2 * np.exp(-dt * 1.2)
        splat(emit, CX + (30 + dist) * np.cos(ang), CY + (30 + dist) * np.sin(ang) * 0.9,
              spectral(B_HUE, 0.75) * (inten / 6)[:, None])


def orbit_xy(a, squash, roll, phi, extent):
    lx = a * extent * np.cos(phi)
    ly = a * extent * squash * np.sin(phi)
    return (CX + lx * math.cos(roll) - ly * math.sin(roll),
            CY + lx * math.sin(roll) + ly * math.cos(roll))


def comets(back, front, t):
    dt = t - TF - 0.05
    if dt <= 0 or t >= OUTRO + 0.62:
        return
    grow = float(ease_out(dt / 1.1, 4))
    imp = implode(t)
    extent = (0.35 + 0.65 * grow) * (1 - imp)
    level = float(smooth(dt / 0.5)) * (1 + 1.5 * imp)
    for (a, squash, roll, period, phase, hue, tail_len, gain) in COMETS:
        head = phase + 2 * math.pi * dt / period * (1 + 2.0 * imp)
        s = np.linspace(0, 1, 2600)
        phi = head - s * tail_len * (0.3 + 0.7 * grow)
        x, y = orbit_xy(a, squash, roll, phi, extent)
        bright = (1 - s) ** 2.4 * 0.42 * gain + 3.5 * gain * np.exp(-(s / 0.008) ** 2)
        col = spectral(hue + 0.35 * s, 0.85) * (bright * level)[:, None]
        near = np.sin(phi) > 0
        splat(front, x[near], y[near], col[near])
        splat(back, x[~near], y[~near], col[~near])
        phi = np.linspace(0, 2 * math.pi, 2400, endpoint=False)
        x, y = orbit_xy(a, squash, roll, phi, extent)
        col = spectral(hue + phi / (2 * math.pi), 0.6) * (0.035 * level * gain)
        near = np.sin(phi) > 0
        splat(front, x[near], y[near], col[near])
        splat(back, x[~near], y[~near], col[~near])
    for ring, (a, squash, roll, period, phase, hue, _, _) in enumerate(COMETS):
        m = A_RING == ring
        phi = A_PHI[m] + 2 * math.pi * dt / period * 0.8
        x, y = orbit_xy(a * A_SPREAD[m], squash, roll, phi, extent)
        tw = np.clip(np.sin(2 * math.pi * (t * 1.3 + A_PH[m])), 0, 1) ** 6
        col = spectral(hue + phi / (2 * math.pi), 0.7) * (A_B[m] * tw * level * 0.5)[:, None]
        near = np.sin(phi) > 0
        splat(front, x[near], y[near], col[near])
        splat(back, x[~near], y[~near], col[~near])


def god_rays(scene, t):
    dt = t - TF
    if dt <= 0 or t >= OUTRO + 0.55:
        return
    level = float(smooth(dt / 0.7)) * (1 - float(smooth((t - OUTRO) / 0.4)))
    level *= 1 + 1.8 * math.exp(-dt / 0.35)
    pat = ((0.5 + 0.5 * np.cos(9 * THETA + 0.55 * t)) ** 8 * 0.7 +
           (0.5 + 0.5 * np.cos(14 * THETA - 0.8 * t + 1.3)) ** 12 * 0.5 +
           (0.5 + 0.5 * np.cos(5 * THETA + 0.3 * t + 2.1)) ** 4 * 0.35)
    scene += RAY_COL * (pat * RAY_FALL * 0.085 * level)[..., None]


def core(emit, t):
    """Gathering glow, ignition, anamorphic streak, shockwave, loop seed."""
    gather = float(clamp01((t - (TF - 0.6)) / 0.6)) ** 3 if t < TF else 0.0
    dt = t - TF
    ignite = (14.0 * math.exp(-dt / 0.07) + 2.2 * math.exp(-dt / 0.45)) if dt >= 0 else 0.0
    settle = 0.28 * float(smooth(dt / 0.5)) * (1 - implode(t)) if dt >= 0 else 0.0
    collapse = 9.0 * math.exp(-((t - (OUTRO + 0.6)) / 0.07) ** 2)
    since = (t - (OUTRO + 0.6)) % T              # wraps across the loop seam
    seed = 0.9 * math.exp(-since / 0.4) * float(smooth(since / 0.06)) if since < 2.5 else 0.0
    seed *= 1 + 0.25 * math.sin(since * 2 * math.pi * 3)
    level = 2.5 * gather + ignite + settle + collapse + seed
    if level > 0.003:
        emit += (level / (1 + DIST ** 2 / 34.0 ** 2) ** 1.6)[..., None] * np.array([1.0, 0.93, 0.85], np.float32)
    streak = 6.5 * math.exp(-dt / 0.16) if dt >= 0 else 0.0
    streak += 2.4 * math.exp(-((t - (OUTRO + 0.6)) / 0.09) ** 2)
    if streak > 0.01:
        band = np.exp(-((yy - CY) / 2.6) ** 2) * np.exp(-np.abs(xx - CX) / 520)
        emit += (streak * band)[..., None] * np.array([0.55, 0.75, 1.25], np.float32)
    if dt >= 0:
        ring_t = dt / 0.95
        if ring_t < 1:
            radius = 40 + 1500 * (1 - (1 - ring_t) ** 2.4)
            fade = (1 - ring_t) ** 1.8 * 1.4
            d = np.hypot(xx - CX, (yy - CY) / 0.9)
            for c, scale in ((0, 1.0), (1, 0.982), (2, 0.964)):
                emit[..., c] += fade * np.exp(-((d - radius * scale) / (10 + 22 * ring_t)) ** 2)


def stars(emit, t):
    tw = 0.6 + 0.4 * np.sin(2 * math.pi * (STARS_K * t / T + STARS_P))
    flash = 0.0 if t < TF else 2.5 * math.exp(-(t - TF) / 0.3)
    col = (STARS_B * tw * (1 + flash))[:, None] * np.array([0.8, 0.85, 1.0], np.float32)
    splat(emit, STARS_X, STARS_Y, col)


def fused_icon(scene, emit, t):
    """The assembled icon between the lock and the implosion."""
    dt = t - TF
    scale, bob = hold_pose(t)
    size = int(round(ICON * scale))
    img = icon_img.resize((size, size), Image.LANCZOS)
    lin = to_linear_rgba(img)
    lin[..., :3] *= 1 + 2.4 * math.exp(-dt / 0.3)
    ox, oy = int(round(CX - size / 2)), int(round(CY + bob - size / 2))
    over(scene, lin, ox, oy)
    em = ICON_EMIT if size == ICON else cv2.resize(ICON_EMIT, (size, size), interpolation=cv2.INTER_AREA)
    add_at(emit, em * (0.55 + 1.6 * math.exp(-dt / 0.35)), ox, oy)
    sw = (t - 2.6) / 0.8                                   # glass light sweep
    if 0 < sw < 1:
        ly, lx = np.mgrid[0:size, 0:size].astype(np.float32)
        diag = (lx * 0.8 + ly) / (1.8 * size)
        band = np.exp(-((diag - (sw * 1.6 - 0.3)) / 0.04) ** 2) * lin[..., 3]
        add_at(emit, (band * 0.7 * math.sin(math.pi * sw))[..., None] * np.ones(3, np.float32), ox, oy)
    ph = (t * 0.9 + TW_PHASE) % 1.0                          # twinkles on the swirl
    tw = np.clip(np.sin(math.pi * ph / 0.18), 0, 1) * (ph < 0.18) * float(smooth(dt / 0.8))
    if tw.max() > 0:
        px, py = CX + TW_X * scale, CY + bob + TW_Y * scale
        taps = [(0, 0, 3.0)] + [(d, 0, 0.9 / abs(d)) for d in (-6, -4, -2, 2, 4, 6)] \
            + [(0, d, 0.9 / abs(d)) for d in (-6, -4, -2, 2, 4, 6)]
        for ox2, oy2, wgt in taps:
            splat(emit, px + ox2, py + oy2, TW_COL * (tw * wgt * 1.2)[:, None])


def wordmark(scene, emit, t):
    k = (t - 2.05) / 1.0
    if k <= 0:
        return
    out = float(smooth((t - OUTRO + 0.05) / 0.35))
    a = float(smooth(k)) * (1 - out)
    if a <= 0.002:
        return
    text = 'EMUFUSION'
    track = 24 + 70 * (1 - float(ease_out(k, 3))) - 18 * out
    widths = [font_big.getlength(ch) for ch in text]
    total = sum(widths) + track * (len(text) - 1)
    layer = Image.new('L', (int(total) + 60, 110))
    d = ImageDraw.Draw(layer)
    x = 30.0
    for ch, wch in zip(text, widths):
        d.text((x, 20), ch, font=font_big, fill=255)
        x += wch + track
    radius = 6 * (1 - float(ease_out(k, 2))) + 4 * out
    if radius > 0.3:
        layer = layer.filter(ImageFilter.GaussianBlur(radius))
    m = np.asarray(layer, np.float32) / 255.0 * a
    ox, oy = int(CX - layer.width / 2), int(CY + R + 62)
    h, w = m.shape
    col = np.array([0.80, 0.83, 0.94], np.float32)
    scene[oy:oy + h, ox:ox + w] = scene[oy:oy + h, ox:ox + w] * (1 - m[..., None]) + m[..., None] * col
    sh = (t - 3.35) / 0.9                                    # spectral shimmer
    lx = np.arange(w, dtype=np.float32)[None, :] / w
    if 0 < sh < 1:
        band = np.exp(-((lx - (sh * 1.4 - 0.2)) / 0.06) ** 2)
        emit[oy:oy + h, ox:ox + w] += (m * band)[..., None] * spectral(lx[0] * 0.9)[None, :, :] * 2.2
    emit[oy:oy + h, ox:ox + w] += m[..., None] * col * 0.18


# ---------------------------------------------------------------- frame
def bloom(src):
    small = cv2.resize(src, (W // 2, H // 2), interpolation=cv2.INTER_AREA)
    acc = np.zeros_like(small)
    for sigma, wgt in ((2.0, 0.55), (6.0, 0.35), (16.0, 0.30), (42.0, 0.25)):
        acc += blur(small, sigma) * wgt
    return cv2.resize(acc, (W, H), interpolation=cv2.INTER_LINEAR)


def aces(x):
    x = np.maximum(x, 0)
    a, b, c, d, e = 2.51, 0.03, 2.43, 0.59, 0.14
    return np.clip((x * (a * x + b)) / (x * (c * x + d) + e), 0, 1)


def render(t, frame_index=0):
    t = t % T
    scene = BG.copy()
    flash_bg = 0.0 if t < TF else 6.0 * math.exp(-(t - TF) / 0.25)
    scene += NEBULA * (1 + flash_bg + 0.25 * math.sin(2 * math.pi * t / T) ** 2)
    emit = np.zeros((H, W, 3), np.float32)
    back = np.zeros((H, W, 3), np.float32)
    front = np.zeros((H, W, 3), np.float32)
    stars(emit, t)
    streams(emit, t)
    god_rays(scene, t)
    comets(back, front, t)
    back = back * 0.5 + blur(back, 1.1) * 1.5
    front = front * 0.5 + blur(front, 1.1) * 1.5
    scene += back
    if t < TF or (t >= OUTRO and implode(t) < 0.995):
        draw_layers(scene, emit, t)
    elif TF <= t < OUTRO:
        fused_icon(scene, emit, t)
    scene += front
    wordmark(scene, emit, t)
    burst(emit, t)
    core(emit, t)
    hdr = scene + emit
    hdr = hdr + bloom(np.maximum(scene - 0.8, 0) + emit * 0.7 + back + front) * 0.9
    exposure = 1.25 + (2.0 * math.exp(-(t - TF) / 0.12) if t >= TF else 0.0)
    ldr = aces(hdr * exposure) ** (1 / 2.2)
    ldr *= (1 - 0.42 * np.clip(rad, 0, 1.4) ** 2)[..., None]
    img = np.clip(ldr * 255 + 0.5, 0, 255).astype(np.uint8)
    # Lens: chromatic aberration (stronger at the impact), then camera.
    ca = 0.0015 + (0.010 * math.exp(-(t - TF) / 0.2) if t >= TF else 0.0)
    zoom, sx, sy = cam(t)
    out = np.empty_like(img)
    for c, k in zip(range(3), (1 + ca, 1.0, 1 - ca)):
        z = zoom * k
        m = np.float32([[z, 0, (CX + sx) - z * CX], [0, z, (CY + sy) - z * CY]])
        out[..., c] = cv2.warpAffine(img[..., c], m, (W, H), flags=cv2.INTER_CUBIC,
                                     borderMode=cv2.BORDER_REPLICATE)
    grain = np.random.default_rng(1000 + frame_index).normal(0, 2.2, (H, W, 1))
    return np.clip(out + grain, 0, 255).astype(np.uint8)


def main():
    if '--check-loop' in sys.argv:
        first, second, last = (render(v, n).astype(int) for v, n in
                               ((0.0, 0), (1 / FPS, 1), (T - 1 / FPS, FRAMES - 1)))
        print('seam (last->first) mean abs', float(np.abs(last - first).mean()),
              'max', int(np.abs(last - first).max()))
        print('ordinary (first->second) mean abs', float(np.abs(second - first).mean()),
              'max', int(np.abs(second - first).max()))
        return
    if '--preview' in sys.argv:
        times = [float(v) for v in sys.argv[sys.argv.index('--preview') + 1:]]
        out_dir = HERE / 'previews' if (HERE / 'previews').is_dir() else Path('.')
        for v in times:
            Image.fromarray(render(v)).save(out_dir / f'fusion-{v:05.2f}.png')
            print('preview', v, flush=True)
        return
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'loading.mp4'
    if output.suffix == '.mkv':
        # Worker mode: frames [start, stop) as a lossless segment for render_all.sh.
        start, stop = int(sys.argv[2]), int(sys.argv[3])
        seg = subprocess.Popen(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'rawvideo',
                                '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
                                '-c:v', 'libx264rgb', '-qp', '0', '-preset', 'ultrafast', str(output)],
                               stdin=subprocess.PIPE)
        for n in range(start, stop):
            seg.stdin.write(render(n / FPS, n).tobytes())
        seg.stdin.close()
        if seg.wait():
            raise SystemExit('ffmpeg segment failed')
        return
    cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'rawvideo',
           '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
           '-frames:v', str(FRAMES), '-an', '-c:v', 'libx264', '-preset', 'slow',
           '-crf', '17', '-tune', 'grain', '-profile:v', 'high', '-level:v', '4.2',
           '-maxrate', '14M', '-bufsize', '28M', '-g', '120', '-keyint_min', '120',
           '-sc_threshold', '0', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(output)]
    encoder = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for n in range(FRAMES):
        encoder.stdin.write(render(n / FPS, n).tobytes())
    encoder.stdin.close()
    if encoder.wait():
        raise SystemExit('ffmpeg failed')
    print('wrote', output)


if __name__ == '__main__':
    main()
