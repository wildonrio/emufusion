"""Run the exported GLES passes on the host GPU and compare each stage with PyTorch.

usage: python3 -m tools.learned_framegen.verify_gles CHECKPOINT TRIPLET_DIR [--harness PATH]

The pass order here is the order LearnedFrameEstimator uses on the device.
"""
import argparse
import json
import math
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import torch

from . import dataset
from .export_gles import shaders
from .model import PhaseNet


def ceil_half(n):
    return (n + 1) // 2


class Script:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.lines = []
        self.reads = {}

    def tex(self, name, w, h, half=False, data=None):
        path = ''
        if data is not None:
            path = str(self.folder / f'{name}.in')
            rgba = np.zeros((h, w, 4), np.float32)
            rgba[..., :data.shape[-1]] = data
            rgba.tofile(path)
        self.lines.append(f"tex {name} {w} {h} {'rgba16f' if half else 'rgba8'} {path}".rstrip())

    def draw(self, prog, w, h, targets, uniforms):
        self.lines.append(f'use {prog}')
        unit = 0
        for kind, name, *value in uniforms:
            if kind == 'sampler':
                self.lines.append(f'sampler {name} {value[0]} {unit}'); unit += 1
            else:
                self.lines.append(f'{kind} {name} ' + ' '.join(str(v) for v in value))
        self.lines.append(f"draw {w} {h} {','.join(targets)}")

    def read(self, name, w, h):
        path = str(self.folder / f'{name}.out')
        self.lines.append(f'read {name} {path}')
        self.reads[name] = (path, w, h)

    def result(self, name):
        path, w, h = self.reads[name]
        return np.fromfile(path, np.float32).reshape(h, w, 4)


def build_pipeline(s, width, height, levels, t, frames):
    """frames: {'A': HxWx3, 'B': HxWx3} float32. Returns names of result textures."""
    sizes = [(width, height)]
    for k in range(1, levels):
        sizes.append((ceil_half(sizes[-1][0]), ceil_half(sizes[-1][1])))
    q = [(ceil_half(ceil_half(w)), ceil_half(ceil_half(h))) for w, h in sizes]
    for side in 'AB':
        s.tex(f'{side}m0', width, height, data=frames[side])
        for k in range(levels):
            w, h = sizes[k]
            if k > 0:
                s.tex(f'{side}m{k}', w, h)
                pw, ph = sizes[k - 1]
                s.draw('MIP', w, h, [f'{side}m{k}'], [('sampler', 'uIn0', f'{side}m{k - 1}'),
                                                       ('i2', 'uIn', pw, ph), ('i2', 'uOut', w, h)])
            hw, hh = ceil_half(w), ceil_half(h)
            qw, qh = q[k]
            for i in range(2):
                s.tex(f'{side}e0_{k}_{i}', hw, hh); s.tex(f'{side}e1_{k}_{i}', hw, hh)
            for i in range(4):
                s.tex(f'{side}e2_{k}_{i}', qw, qh); s.tex(f'{side}f{k}_{i}', qw, qh)
            s.draw('ENC0', hw, hh, [f'{side}e0_{k}_{i}' for i in range(2)],
                   [('sampler', 'uIn0', f'{side}m{k}'), ('i2', 'uIn', w, h), ('i2', 'uOut', hw, hh)])
            s.draw('ENC1', hw, hh, [f'{side}e1_{k}_{i}' for i in range(2)],
                   [('sampler', f'uIn{i}', f'{side}e0_{k}_{i}') for i in range(2)] +
                   [('i2', 'uIn', hw, hh), ('i2', 'uOut', hw, hh)])
            s.draw('ENC2', qw, qh, [f'{side}e2_{k}_{i}' for i in range(4)],
                   [('sampler', f'uIn{i}', f'{side}e1_{k}_{i}') for i in range(2)] +
                   [('i2', 'uIn', hw, hh), ('i2', 'uOut', qw, qh)])
            s.draw('ENC3', qw, qh, [f'{side}f{k}_{i}' for i in range(4)],
                   [('sampler', f'uIn{i}', f'{side}e2_{k}_{i}') for i in range(4)] +
                   [('i2', 'uIn', qw, qh), ('i2', 'uOut', qw, qh)])
    s.tex('dummy', 1, 1, half=True, data=np.zeros((1, 1, 4), np.float32))
    feats = lambda side, k: [('sampler', f'u{side}{i}', f'{"A" if side == "A" else "B"}f{k}_{i}') for i in range(4)]
    for k in reversed(range(levels)):
        qw, qh = q[k]
        coarse = f'F1_{k + 1}' if k + 1 < levels else 'dummy'
        has = 1.0 if k + 1 < levels else 0.0
        for i in range(3):
            s.tex(f'corr{k}_{i}', qw, qh)
        for n in ('h', 'g'):
            for i in range(4):
                s.tex(f'{n}{k}_{i}', qw, qh)
        s.tex(f'F1_{k}', qw, qh, half=True)
        s.draw('CORR', qw, qh, [f'corr{k}_{i}' for i in range(3)],
               feats('A', k) + feats('B', k) + [('sampler', 'uCoarse', coarse), ('f1', 'uHasCoarse', has),
                                                ('f1', 'uT', t), ('i2', 'uOut', qw, qh)])
        for head in ('H1', 'H2') if k < 3 else ('H1',):
            out = 'F1' if head == 'H1' else 'F2'
            if head == 'H2':
                s.tex(f'F2_{k}', qw, qh, half=True)
            dims = [('i2', 'uIn', qw, qh), ('i2', 'uOut', qw, qh)]
            s.draw(f'{head}C1', qw, qh, [f'h{k}_{i}' for i in range(4)],
                   [('sampler', f'uIn{i}', f'corr{k}_{i}') for i in range(3)] + dims)
            s.draw(f'{head}C2', qw, qh, [f'g{k}_{i}' for i in range(4)],
                   [('sampler', f'uIn{i}', f'h{k}_{i}') for i in range(4)] + dims)
            s.draw(f'{head}C3', qw, qh, [f'h{k}_{i}' for i in range(4)],
                   [('sampler', f'uIn{i}', f'g{k}_{i}') for i in range(4)] + dims)
            s.draw(f'{head}OUT', qw, qh, [f'{out}_{k}'],
                   [('sampler', f'uIn{i}', f'h{k}_{i}') for i in range(4)] + dims +
                   [('sampler', 'uCoarse', coarse), ('f1', 'uHasCoarse', has)])
        if k < 3:
            low2 = f'F2_{k + 1}' if k + 1 < 3 else coarse
            for i in range(2):
                s.tex(f'v{k}_{i}', qw, qh); s.tex(f'u{k}_{i}', qw, qh)
            s.tex(f'W{k}', qw, qh, half=True)
            dims = [('i2', 'uIn', qw, qh), ('i2', 'uOut', qw, qh)]
            s.draw('VIS0', qw, qh, [f'v{k}_{i}' for i in range(2)],
                   feats('A', k) + feats('B', k) + [('sampler', 'uLow1', coarse), ('sampler', 'uLow2', low2),
                                                    ('f1', 'uT', t), ('i2', 'uOut', qw, qh)])
            s.draw('VIS1', qw, qh, [f'u{k}_{i}' for i in range(2)],
                   [('sampler', f'uIn{i}', f'v{k}_{i}') for i in range(2)] + dims)
            s.draw('VIS2', qw, qh, [f'v{k}_{i}' for i in range(2)],
                   [('sampler', f'uIn{i}', f'u{k}_{i}') for i in range(2)] + dims)
            s.draw('VIS3', qw, qh, [f'u{k}_{i}' for i in range(2)],
                   [('sampler', f'uIn{i}', f'v{k}_{i}') for i in range(2)] + dims)
            prev = f'W{k + 1}' if k + 1 < 3 else 'dummy'
            s.draw('VISOUT', qw, qh, [f'W{k}'],
                   [('sampler', f'uIn{i}', f'u{k}_{i}') for i in range(2)] + dims +
                   [('sampler', 'uPrev', prev), ('f1', 'uHasPrev', 1.0 if k + 1 < 3 else 0.0)])
    s.tex('OUT', width, height)
    s.draw('GENERATE', width, height, ['OUT'],
           [('sampler', 'uFrameA', 'Am0'), ('sampler', 'uFrameB', 'Bm0'), ('sampler', 'uF1', 'F1_0'),
            ('sampler', 'uF2', 'F2_0'), ('sampler', 'uW', 'W0'), ('f1', 'uT', t),
            ('f2', 'uQ0', *q[0])])
    return sizes, q


def compare(name, gl, ref, channels):
    d = np.abs(gl[..., :channels] - ref[..., :channels])
    print(f'  {name:10s} max {d.max():.5f} mean {d.mean():.6f} ref-range {np.abs(ref[..., :channels]).max():.3f}')
    return d.max()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('checkpoint')
    parser.add_argument('triplet')
    parser.add_argument('--harness', default='/private/tmp/claude-501/gl_harness')
    parser.add_argument('--levels', type=int, default=5)
    args = parser.parse_args()
    model = PhaseNet(levels=args.levels)
    if args.checkpoint != 'random':
        model.load_state_dict(torch.load(args.checkpoint, map_location='cpu'))
    model.eval()
    folder = Path(args.triplet)
    meta = json.loads((folder / 'meta.json').read_text())
    t = float(meta.get('phase', 0.5))
    a, c = (dataset.load_rgb(folder / f'{k}.png').astype(np.float32) / 255 for k in 'AC')
    h, w = a.shape[:2]
    with torch.no_grad():
        ta, tc = (torch.from_numpy(x).permute(2, 0, 1)[None] for x in (a, c))
        tt = torch.tensor([t])
        fa, fc = model.features(ta), model.features(tc)
        f1, f2, logits = model.fields(fa, fc, tt)
        out, *_ = model.synthesize(ta, tc, tt, f1, f2, logits)
    with tempfile.TemporaryDirectory(prefix='lf-verify-') as tmp:
        tmp = Path(tmp)
        src = shaders(model)
        for name, text in src.items():
            (tmp / f"{name}.{'vert' if name.startswith('VERTEX') else 'frag'}").write_text(text)
        # The harness has no quad buffer: a full-screen triangle with matching texcoords.
        (tmp / 'VERTEX_TRI_UV.vert').write_text(
            "#version 300 es\nout vec2 vTexCoord;\nvoid main(){vec2 p=vec2(gl_VertexID==1?3.0:-1.0,"
            "gl_VertexID==2?3.0:-1.0);gl_Position=vec4(p,0.0,1.0);vTexCoord=0.5*(p+1.0);}\n")
        s = Script(tmp)
        for name in src:
            if not name.startswith('VERTEX'):
                vert = 'VERTEX_TRI_UV' if name == 'GENERATE' else 'VERTEX'
                s.lines.append(f'prog {name} {tmp}/{vert}.vert {tmp}/{name}.frag')
        sizes, q = build_pipeline(s, w, h, args.levels, t, {'A': a, 'B': c})
        for k in range(args.levels):
            for i in range(4):
                s.read(f'Af{k}_{i}', *q[k])
        s.read('F1_0', *q[0]); s.read('F2_0', *q[0]); s.read('W0', *q[0]); s.read('OUT', w, h)
        run = subprocess.run([args.harness], input='\n'.join(s.lines) + '\n', text=True, capture_output=True)
        if run.returncode:
            print(run.stderr[-3000:]); raise SystemExit(run.returncode)
        worst = 0.0
        for k in range(args.levels):
            gl = np.concatenate([s.result(f'Af{k}_{i}') for i in range(4)], -1)
            ref = fa[k][0].permute(1, 2, 0).numpy()
            worst = max(worst, compare(f'feat{k}', gl, ref, 16))
        compare('F1', s.result('F1_0'), f1[0].permute(1, 2, 0).numpy(), 4)
        compare('F2', s.result('F2_0'), f2[0].permute(1, 2, 0).numpy(), 4)
        compare('W', s.result('W0'), logits[0].permute(1, 2, 0).numpy(), 4)
        gl_out = s.result('OUT')[..., :3]
        ref_out = out[0].permute(1, 2, 0).numpy()
        compare('output', gl_out, ref_out, 3)
        print(f'  output PSNR gl-vs-torch {10 * math.log10(1 / max(1e-12, ((gl_out - ref_out) ** 2).mean())):.1f} dB')


if __name__ == '__main__':
    main()
