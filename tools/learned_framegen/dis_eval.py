"""Run the GPU DIS passes (dis_gles.py) on the desktop GPU over captured triplets
and score them like the device hold-out, beside the device's synthesis 15.

usage: python3 -m tools.learned_framegen.dis_eval EVAL_ROOT [--per-case N] [--finest-small 0] [--finest-large 1]
"""
import argparse
import json
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from . import dis_gles as D


def load(path):
    return np.asarray(Image.open(path).convert('RGB')).astype(np.float32) / 255.0


def sums(g, a, c, b):
    d = lambda x, y: np.abs(x - y).max(2)
    changing = np.maximum(d(a, b), d(c, b)) > 2 / 255
    return float(d(g, b)[changing].sum()), float(d(0.5 * (a + c), b)[changing].sum())


def area(img, w, h):
    return np.asarray(Image.fromarray((img * 255 + 0.5).clip(0, 255).astype(np.uint8)).resize(
        (w, h), Image.BOX)).astype(np.float32) / 255.0


class Script:
    def __init__(self, folder):
        self.folder = Path(folder); self.lines = []; self.n = 0

    def upload(self, name, img):
        h, w = img.shape[:2]
        rgba = np.ones((h, w, 4), np.float32); rgba[..., :3] = img
        path = self.folder / f'{name}.in'; rgba.tofile(path)
        self.lines.append(f'tex {name} {w} {h} rgba8 {path}')

    def tex(self, name, w, h, half=False):
        self.lines.append(f"tex {name} {w} {h} {'rgba16f' if half else 'rgba8'}")

    def draw(self, prog, w, h, targets, uniforms):
        self.lines.append(f'use {prog}'); unit = 0
        for kind, name, *value in uniforms:
            if kind == 'sampler':
                self.lines.append(f'sampler {name} {value[0]} {unit}'); unit += 1
            else:
                self.lines.append(f'{kind} {name} ' + ' '.join(str(v) for v in value))
        self.lines.append(f"draw {w} {h} {','.join(targets)}")


def pipeline(s, tag, a, c, t, finest):
    h, w = a.shape[:2]
    sizes, _ = D.levels_for(w, h, finest)
    for side, img in (('A', a), ('C', c)):
        s.upload(f'{tag}{side}rgb', img)
        s.tex(f'{tag}{side}g0', w, h)
        s.draw('GRAY', w, h, [f'{tag}{side}g0'], [('sampler', 'uIn0', f'{tag}{side}rgb'),
               ('f2', 'uTexel', 1.0 / w, 1.0 / h), ('i1', 'uDivisor', 1)])
        for k in range(1, len(sizes)):
            s.tex(f'{tag}{side}g{k}', *sizes[k])
            s.draw('DOWN', *sizes[k], [f'{tag}{side}g{k}'], [('sampler', 'uIn0', f'{tag}{side}g{k - 1}'),
                   ('i2', 'uIn', *sizes[k - 1])])
        for k in range(finest, len(sizes)):
            s.tex(f'{tag}{side}d{k}', *sizes[k], half=True)
            s.draw('GRAD', *sizes[k], [f'{tag}{side}d{k}'], [('sampler', 'uIn0', f'{tag}{side}g{k}'),
                   ('i2', 'uSize', *sizes[k])])
    s.tex(f'{tag}zero', 1, 1, half=True)
    for ref, tgt in (('A', 'C'), ('C', 'A')):
        coarse = f'{tag}zero'
        for k in reversed(range(finest, len(sizes))):
            gw, gh = D.grid(sizes[k])
            s.tex(f'{tag}{ref}p{k}', gw, gh, half=True)
            s.tex(f'{tag}{ref}f{k}', *sizes[k], half=True)
            s.draw('PATCH_SEARCH', gw, gh, [f'{tag}{ref}p{k}'],
                   [('sampler', 'uRef', f'{tag}{ref}d{k}'), ('sampler', 'uTarget', f'{tag}{tgt}g{k}'),
                    ('sampler', 'uCoarse', coarse), ('i2', 'uSize', *sizes[k]),
                    ('f1', 'uHasCoarse', 0.0 if coarse.endswith('zero') else 1.0)])
            s.draw('DENSIFY', *sizes[k], [f'{tag}{ref}f{k}'],
                   [('sampler', 'uRef', f'{tag}{ref}g{k}'), ('sampler', 'uTarget', f'{tag}{tgt}g{k}'),
                    ('sampler', 'uPatches', f'{tag}{ref}p{k}'), ('i2', 'uSize', *sizes[k]),
                    ('i2', 'uGrid', gw, gh)])
            coarse = f'{tag}{ref}f{k}'
    s.tex(f'{tag}out', w, h)
    s.draw('GENERATE', w, h, [f'{tag}out'],
           [('sampler', 'uFrameA', f'{tag}Argb'), ('sampler', 'uFrameC', f'{tag}Crgb'),
            ('sampler', 'uFlowAC', f'{tag}Af{finest}'), ('sampler', 'uFlowCA', f'{tag}Cf{finest}'),
            ('f1', 'uT', t), ('f2', 'uFlowSize', *sizes[finest])])
    out = s.folder / f'{tag}.out'
    s.lines.append(f'read {tag}out {out}')
    return out, (w, h)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('root')
    parser.add_argument('--per-case', type=int, default=60)
    parser.add_argument('--finest-small', type=int, default=0)
    parser.add_argument('--finest-large', type=int, default=1)
    parser.add_argument('--harness', default='/private/tmp/claude-501/gl_harness')
    parser.add_argument('--iterations', type=int, default=D.ITERATIONS)
    parser.add_argument('--stride', type=int, default=D.STRIDE)
    args = parser.parse_args()
    D.ITERATIONS, D.STRIDE = args.iterations, args.stride
    by_case = defaultdict(list)
    for meta in sorted(Path(args.root).glob('*/*/meta.json')):
        by_case[json.loads(meta.read_text())['case']].append(meta.parent)
    for case, folders in sorted(by_case.items()):
        with tempfile.TemporaryDirectory(prefix='dis-eval-') as tmp:
            tmp = Path(tmp)
            for name, text in D.shaders().items():
                (tmp / f"{name}.{'vert' if name.startswith('VERTEX') else 'frag'}").write_text(text)
            (tmp / 'VERTEX_TRI_UV.vert').write_text(
                "#version 300 es\nout vec2 vTexCoord;\nvoid main(){vec2 p=vec2(gl_VertexID==1?3.0:-1.0,"
                "gl_VertexID==2?3.0:-1.0);gl_Position=vec4(p,0.0,1.0);vTexCoord=0.5*(p+1.0);}\n")
            s = Script(tmp)
            for name in ('GRAY', 'DOWN', 'GRAD', 'PATCH_SEARCH', 'DENSIFY'):
                s.lines.append(f'prog {name} {tmp}/VERTEX.vert {tmp}/{name}.frag')
            s.lines.append(f'prog GENERATE {tmp}/VERTEX_TRI_UV.vert {tmp}/GENERATE.frag')
            jobs = []
            for folder in folders:
                if len(jobs) >= args.per_case:
                    break
                a, b, c = (load(folder / f'{k}.png') for k in 'ABC')
                if np.abs(a - b).mean() < 1e-4 or np.abs(b - c).mean() < 1e-4:
                    continue
                t = float(json.loads((folder / 'meta.json').read_text()).get('phase', 0.5))
                finest = args.finest_small if max(a.shape[:2]) <= 400 else args.finest_large
                out, size = pipeline(s, f'j{len(jobs)}', a, c, t, finest)
                jobs.append((folder, a, b, c, out, size))
            run = subprocess.run([args.harness], input='\n'.join(s.lines) + '\n', text=True, capture_output=True)
            if run.returncode:
                print(case, 'harness failed', run.stderr[-2000:]); continue
            tot = np.zeros(4)
            for folder, a, b, c, out, (w, h) in jobs:
                g = np.fromfile(out, np.float32).reshape(h, w, 4)[..., :3]
                n1, c1 = sums(g, a, c, b); tot[0] += n1; tot[1] += c1
                d15p = folder / 'generated15.png'
                if d15p.exists():
                    d15 = load(d15p); hh, ww = d15.shape[:2]
                    rs = (lambda x: area(x, ww, hh)) if (hh, ww) != (h, w) else (lambda x: x)
                    p1, q1 = sums(d15, rs(a), rs(c), rs(b)); tot[2] += p1; tot[3] += q1
            print(f'{case:10s} n={len(jobs):3d} gpu-dis={tot[0] / max(tot[1], 1e-9):.3f} '
                  f'device15={tot[2] / max(tot[3], 1e-9):.3f}', flush=True)


if __name__ == '__main__':
    main()
