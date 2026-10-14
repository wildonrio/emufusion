"""Run the GPU DIS passes (dis_gles.py) on the desktop GPU over captured triplets
and score them like the device hold-out, beside the device's synthesis 15.

usage: python3 -m tools.learned_framegen.dis_eval EVAL_ROOT [--per-case N] [--finest-small 0] [--finest-large 1]
"""
import argparse
import json
import os
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from . import dis_gles as D

PHASE = False
PHASE_PASSES = 1


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
    if PHASE:
        fw, fh = sizes[finest]
        gw, gh = D.grid(sizes[finest])
        s.tex(f'{tag}pp', gw, gh, half=True)
        s.tex(f'{tag}pf', fw, fh, half=True)
        prior = f'{tag}zero'
        for rep in range(PHASE_PASSES):
            dst = f'{tag}pf' if rep == PHASE_PASSES - 1 else f'{tag}pf{rep}'
            if dst != f'{tag}pf':
                s.tex(dst, fw, fh, half=True)
            s.draw('PHASE_SEARCH', gw, gh, [f'{tag}pp'],
                   [('sampler', 'uGradA', f'{tag}Ad{finest}'), ('sampler', 'uGradC', f'{tag}Cd{finest}'),
                    ('sampler', 'uFlowAC', f'{tag}Af{finest}'), ('sampler', 'uFlowCA', f'{tag}Cf{finest}'),
                    ('sampler', 'uPrior', prior), ('i2', 'uSize', fw, fh), ('f1', 'uT', t),
                    ('f1', 'uHasPrior', 0.0 if rep == 0 else 1.0)])
            s.draw('PHASE_DENSIFY', fw, fh, [dst],
                   [('sampler', 'uGrayA', f'{tag}Ag{finest}'), ('sampler', 'uGrayC', f'{tag}Cg{finest}'),
                    ('sampler', 'uPatches', f'{tag}pp'), ('i2', 'uSize', fw, fh), ('i2', 'uGrid', gw, gh), ('f1', 'uT', t)])
            prior = dst
        # The cut/fade verdict after DIS, as the device computes and reads it.
        s.tex(f'{tag}cut', 1, 1)
        s.draw('CUT', 1, 1, [f'{tag}cut'],
               [('sampler', 'uGrayA', f'{tag}Ag0'), ('sampler', 'uGrayC', f'{tag}Cg0'),
                ('sampler', 'uFlowAC', f'{tag}Af{finest}'), ('f2', 'uFlowSize', fw, fh)])
        s.draw('GENERATE_PHASE', w, h, [f'{tag}out'],
               [('sampler', 'uFrameA', f'{tag}Argb'), ('sampler', 'uFrameC', f'{tag}Crgb'),
                ('sampler', 'uPhaseFlow', f'{tag}pf'), ('f1', 'uT', t), ('f2', 'uFlowSize', fw, fh),
                ('f2', 'uHistorySize', w, h), ('sampler', 'uCut', f'{tag}cut'), ('f1', 'uCutEnabled', 1.0)])
        out = s.folder / f'{tag}.out'
        s.lines.append(f'read {tag}out {out}')
        s.lines.append(f'read {tag}cut {s.folder}/{tag}.cut')
        return out, (w, h)
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
    parser.add_argument('--phase', action='store_true', help='per-phase symmetric refinement')
    parser.add_argument('--phase-passes', type=int, default=1)
    parser.add_argument('--densify-power', type=float, help='per-phase densification weight exponent (experiment)')
    parser.add_argument('--no-densify-cross', action='store_true', help='per-phase densification at one pixel')
    parser.add_argument('--skip-flat-cross', action='store_true')
    parser.add_argument('--coarse-radius', type=int)
    parser.add_argument('--coarse-bias', type=float)
    parser.add_argument('--fade-gain', type=float, nargs=2)
    parser.add_argument('--fade-coverage', type=float)
    parser.add_argument('--cut-threshold', type=float)
    parser.add_argument('--save', default='', help='write each generated frame (uint8, top row first) here')
    args = parser.parse_args()
    global SAVE, VERDICTS
    SAVE = args.save
    VERDICTS = {} if os.environ.get('DIS_VERDICTS') else None
    D.ITERATIONS, D.STRIDE = args.iterations, args.stride
    if args.densify_power is not None:
        D.PHASE_DENSIFY_POWER = int(args.densify_power) if args.densify_power == int(args.densify_power) else args.densify_power
    if args.skip_flat_cross: D.SKIP_FLAT_CROSS = True
    if args.coarse_radius is not None: D.COARSE_RADIUS = args.coarse_radius
    if args.coarse_bias is not None: D.COARSE_BIAS = args.coarse_bias
    if args.fade_gain: D.FADE_GAIN = tuple(args.fade_gain)
    if args.fade_coverage is not None: D.FADE_COVERAGE = args.fade_coverage
    if args.cut_threshold is not None: D.CUT_THRESHOLD = args.cut_threshold
    if args.no_densify_cross:
        D.PHASE_DENSIFY_CROSS = False
    global PHASE, PHASE_PASSES
    PHASE = args.phase
    PHASE_PASSES = args.phase_passes
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
            for name in ('GRAY', 'DOWN', 'GRAD', 'PATCH_SEARCH', 'DENSIFY', 'PHASE_SEARCH', 'PHASE_DENSIFY', 'CUT'):
                # The per-phase route's instance densifies its endpoint flows sharply.
                frag = 'DENSIFY_SHARP' if name == 'DENSIFY' and PHASE else name
                s.lines.append(f'prog {name} {tmp}/VERTEX.vert {tmp}/{frag}.frag')
            s.lines.append(f'prog GENERATE {tmp}/VERTEX_TRI_UV.vert {tmp}/GENERATE.frag')
            s.lines.append(f'prog GENERATE_PHASE {tmp}/VERTEX_TRI_UV.vert {tmp}/GENERATE_PHASE.frag')
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
            for index, (folder, a, b, c, out, (w, h)) in enumerate(jobs):
                g = np.fromfile(out, np.float32).reshape(h, w, 4)[..., :3]
                if SAVE:
                    dest = Path(SAVE) / case; dest.mkdir(parents=True, exist_ok=True)
                    np.save(dest / f"{index:03d}.npy", np.clip(g * 255 + 0.5, 0, 255).astype(np.uint8))
                    (dest / f'{index:03d}.txt').write_text(str(folder))
                n1, c1 = sums(g, a, c, b); tot[0] += n1; tot[1] += c1
                cutf = out.with_suffix('.cut')
                if VERDICTS is not None and cutf.exists():
                    cv = np.fromfile(cutf, np.float32)[:2]
                    VERDICTS.setdefault(case, []).append((float(cv[0]), float(cv[1]), n1 / max(c1, 1e-9), folder.name))
                d15p = folder / 'generated15.png'
                if d15p.exists():
                    d15 = load(d15p); hh, ww = d15.shape[:2]
                    rs = (lambda x: area(x, ww, hh)) if (hh, ww) != (h, w) else (lambda x: x)
                    p1, q1 = sums(d15, rs(a), rs(c), rs(b)); tot[2] += p1; tot[3] += q1
            if VERDICTS is not None and case in VERDICTS:
                v = VERDICTS[case]
                print(f'  {case}: cut {sum(1 for x in v if x[0] >= 0.25)}/{len(v)} fade {sum(1 for x in v if x[1] >= 0.5)}/{len(v)} ' +
                      ' '.join(f'{x[3]}:{x[0]:.2f}/{x[1]:.0f}/{x[2]:.2f}' for x in v if x[0] >= 0.25 or x[1] >= 0.5)[:900])
            print(f'{case:10s} n={len(jobs):3d} gpu-dis={tot[0] / max(tot[1], 1e-9):.3f} '
                  f'device15={tot[2] / max(tot[3], 1e-9):.3f}', flush=True)


if __name__ == '__main__':
    main()
