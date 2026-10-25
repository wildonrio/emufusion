"""Replay quality bench: score the installed frame generator on saved hold-out triplets.

Each triplet (A, B, C) holds two real frames and the real frame between them.
HoldoutReplay (in the installed APK, run as its own shell process through
app_process) plays them into a real DisplayFrameGenerator with hold-out
scoring, which generates the frame between A and C and measures it against B.
No emulator runs and the app itself is not touched, so the Thor stays quiet
and the same frames are scored on every build.

The score is the generated image's mean error over pixels that changed
between A and C, as a fraction of a plain cross-fade's error on the same
pixels (lower is better; 1.0 = no better than a cross-fade).

Only moving triplets are scored by default. A held triplet, whose B is
nearly A or C (animation drawn on twos, a 30 Hz object in a 60 Hz game), has
no in-between to recover: there the metric measures the source's own frame
timing, not interpolation (the Link's Awakening capture is 150 of 261 held).

usage: replay_bench.py [--per-case N] [--levels 24,21,115] [--dex DEX] [--json OUT] [CASE ...]
       cases are folders of ~/Code/emufusion-training-data/eval (default: all)
       --dex: a working-tree build (tools/qa/build_replay_dex.sh) scored in
       place of the installed APK's code, without installing anything
       --compare: an earlier --json run; each case is compared on exactly the
       triplets both runs scored (the generator is deterministic per triplet;
       runs differ only in which few triplets a run drops)
"""
import argparse
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ADB = [str(Path.home() / 'Library/Android/sdk/platform-tools/adb'), '-s', '427c87b2']
DATA = Path.home() / 'Code/emufusion-training-data'
EVAL = DATA / 'eval'
DEVICE_ROOT = '/data/local/tmp/emufusion-replay'
DEVICE_DEX = '/data/local/tmp/emufusion-replay.dex'
DEVICE_DUMPS = '/data/local/tmp/emufusion-replay-dumps'
PACKAGE = 'com.thorium.preview'
QUALITY = re.compile(r'Hold-out quality generator=\S+ .*')
TRIPLET = re.compile(r'Replay triplet name=(\S+) referenceNs=(\d+)')
PAIR = re.compile(r'Hold-out pair referenceNs=(\d+) (.*)')
WARMUP_TRIPLETS = 15
FIELD_ONLY = False


def shell(command, timeout=120):
    run = subprocess.run(ADB + ['shell', command], capture_output=True, text=True, timeout=timeout)
    return run.stdout


def installed_paths():
    apk = shell(f'pm path {PACKAGE}').strip().splitlines()
    apk = [line.split(':', 1)[1] for line in apk if line.endswith('/base.apk')]
    if len(apk) != 1:
        sys.exit('cannot find the installed EmuFusion APK')
    return apk[0], apk[0].rsplit('/', 1)[0] + '/lib/arm64'


def motion_class(folder):
    """'moving', 'held' (B is nearly one endpoint) or 'static' (A ~ C)."""
    import numpy as np
    from PIL import Image
    a, b, c = (np.asarray(Image.open(folder / f'{n}.png').convert('RGB'), dtype=np.float32)
               for n in 'ABC')
    span = np.abs(a - c).mean()
    if span < 0.5:
        return 'static'
    return 'held' if min(np.abs(b - a).mean(), np.abs(b - c).mean()) < 0.25 * span else 'moving'


def choose(case, per_case, kind, only=None):
    folders = sorted(p for p in (EVAL / case).iterdir()
                     if p.is_dir() and all((p / n).is_file() for n in ('A.png', 'B.png', 'C.png')))
    if only:
        # Generation qualifies on about a second of steady source first:
        # lead with unreported moving triplets so the chosen ones all count.
        chosen = [p for p in folders if p.name in only]
        warmup = [p for p in folders if p.name not in only and motion_class(p) == 'moving']
        return warmup[:WARMUP_TRIPLETS] + chosen
    if kind != 'all':
        folders = [p for p in folders if motion_class(p) == kind]
    if per_case and len(folders) > per_case:
        # Deterministic spread over the whole capture, not its first seconds.
        random.Random(case).shuffle(folders)
        folders = sorted(folders[:per_case])
    return folders


def push(case, folders):
    with tempfile.TemporaryDirectory() as temp:
        stage = Path(temp) / case
        for folder in folders:
            target = stage / folder.name
            target.mkdir(parents=True)
            for name in ('A.png', 'B.png', 'C.png'):
                shutil.copyfile(folder / name, target / name)
        shell(f'rm -rf {DEVICE_ROOT}/{case}; mkdir -p {DEVICE_ROOT}')
        subprocess.run(ADB + ['push', '-q', str(stage), f'{DEVICE_ROOT}/'], check=True,
                       capture_output=True, timeout=600)


def parse(line, levels):
    values = dict(re.findall(r' (\w+)=([-\d.]+)%?', line))
    result = {'samples': int(values.get('totalSamples', 0)),
              'crossfadeMae': float(values.get('totalCrossfadeMae', 0))}
    for level in levels:
        result[f'mae{level}'] = float(values.get(f'totalMae{level}', 0))
        result[f'vsCrossfade{level}'] = float(values.get(f'totalVsCrossfade{level}', 0))
    return result


def run_case(case, per_case, levels, classpath, libs, kind, only=None, dumps=None):
    folders = choose(case, per_case, kind, only)
    if not folders:
        return {'case': case, 'error': f'no {kind} triplets', 'tail': ''}
    push(case, folders)
    subprocess.run(ADB + ['logcat', '-c'], capture_output=True)
    started = time.time()
    system = json.loads((folders[0] / 'meta.json').read_text()).get('system', '') \
        if (folders[0] / 'meta.json').is_file() else ''
    command = (f'CLASSPATH={classpath} app_process -Djava.library.path={libs} '
               f'-Demufusion.replay.system={system} /system/bin '
               f'com.thorium.preview.game.HoldoutReplay {DEVICE_ROOT}/{case} 120 '
               f'{",".join(map(str, levels))}' + (f' {DEVICE_DUMPS}/{case}' if dumps else '') +
               (' field' if dumps and FIELD_ONLY else ''))
    run = subprocess.run(ADB + ['shell', command], capture_output=True, text=True,
                         timeout=60 + 2 * len(folders))
    log = subprocess.run(ADB + ['logcat', '-d', '-s', 'EmuFusionFrameGen:*', 'EmuFusionReplay:*'],
                         capture_output=True, text=True).stdout
    shell(f'rm -rf {DEVICE_ROOT}/{case}')
    names = {int(ns): name for name, ns in TRIPLET.findall(log)}
    if dumps:
        target = Path(dumps) / case
        target.mkdir(parents=True, exist_ok=True)
        subprocess.run(ADB + ['pull', '-q', f'{DEVICE_DUMPS}/{case}/.', str(target)],
                       capture_output=True, timeout=600)
        shell(f'rm -rf {DEVICE_DUMPS}/{case}')
        for dump in target.glob('pair-*.bin'):
            name = names.get(int(dump.stem.split('-', 1)[1]))
            if name: dump.rename(target / f'{name}.bin')
    lines = QUALITY.findall(log)
    if run.returncode != 0 or not lines:
        tail = '\n'.join((run.stdout + run.stderr + log).splitlines()[-25:])
        return {'case': case, 'error': f'exit {run.returncode}, {len(lines)} quality lines', 'tail': tail}
    result = parse(lines[-1], levels)
    pairs = []
    for ns, fields in PAIR.findall(log):
        values = {k: float(v) for k, v in re.findall(r'(\w+)=([-\d.]+)', fields)}
        crossfade = values.get('crossfadeMae', 0.0)
        entry = {'triplet': names.get(int(ns), '?'), 'changing': values.get('changing', 0.0),
                 'crossfadeMae': crossfade}
        for level in levels:
            entry[f'mae{level}'] = values.get(f'mae{level}', 0.0)
            entry[f'severe{level}'] = values.get(f'severe{level}', 0.0)
            entry[f'solid{level}'] = values.get(f'solid{level}', 0.0)
            entry[f'vsCrossfade{level}'] = round(values.get(f'mae{level}', 0.0) / crossfade, 3) \
                if crossfade > 0 else None
        pairs.append(entry)
    pairs = [p for p in pairs if p['triplet'] != '?' and (not only or p['triplet'] in only)]
    # Totals from the per-triplet rows, weighted like the generator's own
    # (error summed over changing pixels), but only for registered triplets.
    weight = sum(p['changing'] for p in pairs)
    crossfade = sum(p['crossfadeMae'] * p['changing'] for p in pairs)
    result['samples'] = len(pairs)
    for level in levels:
        # Share of frame area with severe artifacts (mean over pairs) and the
        # share of pairs with any visible patch (0.5% of the frame or more).
        result[f'severe{level}'] = round(sum(p[f'severe{level}'] for p in pairs) / max(1, len(pairs)), 3)
        result[f'artifactPairs{level}'] = round(
            sum(p[f'severe{level}'] >= 0.5 for p in pairs) / max(1, len(pairs)), 3)
        # Solid severe patches only (blocks, tears; not pixel art's one-pixel
        # edge lines): the visible-artifact measure. A frame counts at 0.1%.
        result[f'solid{level}'] = round(sum(p[f'solid{level}'] for p in pairs) / max(1, len(pairs)), 3)
        result[f'blobPairs{level}'] = round(
            sum(p[f'solid{level}'] >= 0.1 for p in pairs) / max(1, len(pairs)), 3)
    for level in levels:
        total = sum(p[f'mae{level}'] * p['changing'] for p in pairs)
        result[f'vsCrossfade{level}'] = round(total / crossfade, 4) if crossfade else 0.0
        result[f'mae{level}'] = round(total / weight, 3) if weight else 0.0
    result.update(case=case, triplets=len(folders), seconds=round(time.time() - started, 1),
                  pairs=pairs)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('cases', nargs='*')
    parser.add_argument('--per-case', type=int, default=40)
    parser.add_argument('--set', default='eval',
                        help='capture set under emufusion-training-data: eval (480x270) or full (1080p)')
    parser.add_argument('--levels', default='24,21,115')
    parser.add_argument('--kind', default='moving', choices=('moving', 'held', 'static', 'all'))
    parser.add_argument('--triplets', help='comma-separated triplet names (one case)')
    parser.add_argument('--dump-dir', help='pull every scored triplet\'s HOD1 planes here')
    parser.add_argument('--field-only', action='store_true',
                        help='dumps carry only synthesis 24\'s DIS field (training data)')
    parser.add_argument('--compare', help='earlier --json run to compare against, paired')
    parser.add_argument('--dex')
    parser.add_argument('--worst', type=int, default=0, help='list the N worst triplets per case')
    parser.add_argument('--json')
    args = parser.parse_args()
    levels = [int(x) for x in args.levels.split(',')]
    global EVAL, FIELD_ONLY
    EVAL = DATA / args.set
    FIELD_ONLY = args.field_only
    cases = args.cases or sorted(p.name for p in EVAL.iterdir() if p.is_dir() and not p.name.startswith('_'))
    apk, libs = installed_paths()
    classpath = apk
    if args.dex:
        subprocess.run(ADB + ['push', '-q', args.dex, DEVICE_DEX], check=True, capture_output=True)
        classpath = f'{DEVICE_DEX}:{apk}'
    results = []
    try:
        for case in cases:
            only = set(args.triplets.split(',')) if args.triplets else None
            result = run_case(case, args.per_case, levels, classpath, libs, args.kind, only,
                              args.dump_dir)
            results.append(result)
            if 'error' in result:
                print(f'{case:10s} ERROR {result["error"]}\n{result["tail"]}', flush=True)
                continue
            scores = '  '.join(f'{level}: {result[f"vsCrossfade{level}"]:.3f} '
                               f'solid {result[f"solid{level}"]:.2f}% art {100 * result[f"blobPairs{level}"]:.0f}%'
                               for level in levels)
            print(f'{case:10s} pairs {result["samples"]:4d}/{result["triplets"]:<4d} {scores}', flush=True)
            # Worst triplets for the first (production) level, by error added
            # over the cross-fade's, so large-motion failures surface first.
            first = levels[0]
            worst = sorted(result['pairs'], key=lambda p: -(p[f'mae{first}'] * p['changing']))[:args.worst]
            for pair in worst:
                print(f'    {pair["triplet"]}  changing {pair["changing"]:5.1f}%  '
                      f'mae{first} {pair[f"mae{first}"]:6.2f}  crossfade {pair["crossfadeMae"]:6.2f}')
    finally:
        shell(f'rm -rf {DEVICE_ROOT} {DEVICE_DEX} {DEVICE_DUMPS}')
    scored = [r for r in results if 'error' not in r and r['samples']]
    if scored:
        means = '  '.join(f'{level}: {sum(r[f"vsCrossfade{level}"] for r in scored) / len(scored):.3f}'
                          for level in levels)
        print(f'{"mean":10s} {len(scored)} cases            {means}')
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=1) + '\n')
    if args.compare:
        compare(results, json.loads(Path(args.compare).read_text()), levels[0])


def compare(results, earlier, level):
    """Per case, both runs' score on the triplets both scored."""
    before = {r['case']: r for r in earlier if r.get('pairs')}
    deltas = []
    for result in results:
        if not result.get('pairs') or result['case'] not in before:
            continue
        old = {p['triplet']: p for p in before[result['case']]['pairs']}
        new = {p['triplet']: p for p in result['pairs']}
        common = set(old) & set(new)
        crossfade = sum(old[t]['crossfadeMae'] * old[t]['changing'] for t in common)
        if not common or not crossfade:
            continue
        score = lambda rows: sum(rows[t][f'mae{level}'] * rows[t]['changing'] for t in common) / crossfade
        deltas.append(score(new) - score(old))
        print(f'compare {result["case"]:10s} {len(common):3d} common  {score(old):.3f} -> {score(new):.3f} '
              f'({score(new) - score(old):+.3f})')
    if deltas:
        print(f'compare mean change {sum(deltas) / len(deltas):+.4f} over {len(deltas)} cases')


if __name__ == '__main__':
    main()
