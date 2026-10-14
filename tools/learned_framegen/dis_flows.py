"""Write the GPU DIS flows (the device's exact passes, run on the desktop GPU)
for every captured triplet, for training the visibility network on top of them.

usage: /opt/homebrew/bin/python3 -m tools.learned_framegen.dis_flows ROOT [ROOT...]

Writes dis.npy (float16, h x w x 4: F_AC.xy, F_CA.xy in pixels of the level
the device stops at: full analysis resolution for <= 400 px images, else a
half) beside each triplet's PNGs, top row first like the PNGs. Existing files
are kept.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from . import dis_gles as D
from .dis_eval import Script, load

BATCH = 40


def run_batch(jobs, harness):
    with tempfile.TemporaryDirectory(prefix='dis-flows-') as tmp:
        tmp = Path(tmp)
        for name, text in D.shaders().items():
            (tmp / f"{name}.{'vert' if name.startswith('VERTEX') else 'frag'}").write_text(text)
        s = Script(tmp)
        for name in ('GRAY', 'DOWN', 'GRAD', 'PATCH_SEARCH', 'DENSIFY'):
            s.lines.append(f'prog {name} {tmp}/VERTEX.vert {tmp}/{name}.frag')
        reads = []
        for index, folder in enumerate(jobs):
            a, c = load(folder / 'A.png'), load(folder / 'C.png')
            h, w = a.shape[:2]
            stop = 0 if max(h, w) <= 400 else 1
            sizes, _ = D.levels_for(w, h, stop)
            tag = f'j{index}'
            for side, img in (('A', a), ('C', c)):
                s.upload(f'{tag}{side}rgb', img)
                s.tex(f'{tag}{side}g0', w, h)
                s.draw('GRAY', w, h, [f'{tag}{side}g0'], [('sampler', 'uIn0', f'{tag}{side}rgb'),
                       ('f2', 'uTexel', 1.0 / w, 1.0 / h), ('i1', 'uDivisor', 1)])
                for k in range(1, len(sizes)):
                    s.tex(f'{tag}{side}g{k}', *sizes[k])
                    s.draw('DOWN', *sizes[k], [f'{tag}{side}g{k}'],
                           [('sampler', 'uIn0', f'{tag}{side}g{k - 1}'), ('i2', 'uIn', *sizes[k - 1])])
                for k in range(stop, len(sizes)):
                    s.tex(f'{tag}{side}d{k}', *sizes[k], half=True)
                    s.draw('GRAD', *sizes[k], [f'{tag}{side}d{k}'],
                           [('sampler', 'uIn0', f'{tag}{side}g{k}'), ('i2', 'uSize', *sizes[k])])
            s.tex(f'{tag}zero', 1, 1, half=True)
            for ref, tgt in (('A', 'C'), ('C', 'A')):
                coarse = f'{tag}zero'
                for k in reversed(range(stop, len(sizes))):
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
                s.lines.append(f'read {tag}{ref}f{stop} {tmp}/{tag}{ref}.flow')
            reads.append((folder, sizes[stop]))
        run = subprocess.run([harness], input='\n'.join(s.lines) + '\n', text=True, capture_output=True)
        if run.returncode:
            raise RuntimeError(run.stderr[-2000:])
        for index, (folder, (w, h)) in enumerate(reads):
            ac = np.fromfile(tmp / f'j{index}A.flow', np.float32).reshape(h, w, 4)[..., :2]
            ca = np.fromfile(tmp / f'j{index}C.flow', np.float32).reshape(h, w, 4)[..., :2]
            # GL texel coordinates have y up; the PNGs (and training) are top-origin.
            flows = np.concatenate([ac, ca], 2) * np.array([1, -1, 1, -1], np.float32)
            np.save(folder / 'dis.npy', flows.astype(np.float16))


def main():
    harness = '/private/tmp/claude-501/gl_harness'
    folders = []
    for root in sys.argv[1:]:
        folders += [m.parent for m in sorted(Path(root).glob('*/*/meta.json'))
                    if not m.parent.parent.name.startswith('_') and not (m.parent / 'dis.npy').exists()]
    for start in range(0, len(folders), BATCH):
        run_batch(folders[start:start + BATCH], harness)
        print(f'{min(start + BATCH, len(folders))}/{len(folders)}', flush=True)


if __name__ == '__main__':
    main()
