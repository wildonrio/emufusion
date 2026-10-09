"""One-time cleanup of three completed PS2 trials, dry-run unless --apply.

Only regenerable .o files under their exact CMake output roots are removed.
Retain source, build recipes, archives, linked libraries and debugging symbols.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import time

from prune_build_apks import open_paths, sha256, unchanged

ROOT = Path(__file__).resolve().parents[2]
TRIALS = (
    ('armsx2-descriptor-batch-20261005', 'armsx2-arm64-v8a'),
    ('armsx2-descriptors-normal-4096-20261005', 'armsx2-arm64-v8a'),
    ('armsx2-descriptors-normal-16384-20261005', 'armsx2_16k-arm64-v8a'),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    build = ROOT / 'unified-android/build'
    lock = build / '.lucent-build-lock'
    lock.mkdir()  # Never steal the assembler's lock.
    try:
        opened = open_paths()
        tracked = set(subprocess.check_output(
            ['git', 'ls-files', '-z', '--', 'engines/build/candidates'], cwd=ROOT
        ).decode().split('\0'))
        plan = []
        retained = {}
        for name, core in TRIALS:
            trial = ROOT / 'engines/build/candidates' / name
            out = trial / 'work' / core / 'out'
            if not out.is_dir() or out.resolve() != out:
                raise RuntimeError(f'Unexpected output root: {out}')
            if any(p == str(trial) or p.startswith(str(trial) + '/') for p in opened):
                raise RuntimeError(f'Trial still open: {trial}')
            libraries = list((trial / 'arm64-v8a').glob('*.so'))
            if not libraries:
                raise RuntimeError(f'Missing completed trial library: {trial}')
            for parent, _, files in os.walk(out, followlinks=False):
                for name in files:
                    path = Path(parent) / name
                    if path.suffix not in ('.o', '.a', '.so'):
                        continue
                    meta = path.lstat()
                    if stat.S_ISLNK(meta.st_mode) and path.suffix != '.o':
                        continue  # Preserve library aliases without following them.
                    if not stat.S_ISREG(meta.st_mode) or path.resolve() != path:
                        raise RuntimeError(f'Unexpected link: {path}')
                    if path.suffix == '.o':
                        if str(path.relative_to(ROOT)) in tracked:
                            raise RuntimeError(f'Tracked object: {path}')
                        plan.append((path, meta))
                    else:
                        libraries.append(path)
            retained.update((str(p), sha256(p)) for p in libraries)
        total = sum(meta.st_size for _, meta in plan)
        print(f'{len(plan)} regenerable objects; {total / 1024**3:.2f} GiB; '
              f'{len(retained)} linked libraries/archives retained', flush=True)
        if not args.apply:
            return
        # Recheck the whole plan before deleting anything; build inputs are not
        # part of this plan. No recursive directory deletion or native stripping.
        opened = open_paths()
        if any(str(p) in opened or not unchanged(p, meta) for p, meta in plan):
            raise RuntimeError('An object changed or is open')
        free_before = shutil.disk_usage(ROOT).free
        receipts = build / 'retention-receipts'
        receipt = receipts / f'{time.time_ns()}-completed-ps2-objects.jsonl'
        with receipt.open('x') as stream:
            stream.write(json.dumps(dict(event='retained', sha256=retained)) + '\n')
            stream.flush()
            for path, meta in plan:
                if not unchanged(path, meta):
                    raise RuntimeError(f'Object changed: {path}')
                stream.write(json.dumps(dict(event='planned_unlink', path=str(path),
                    bytes=meta.st_size)) + '\n')
                stream.flush()
                path.unlink()
                stream.write(json.dumps(dict(event='unlinked', path=str(path))) + '\n')
            if any(sha256(Path(p)) != digest for p, digest in retained.items()):
                raise RuntimeError('Retained library changed')
            delta = shutil.disk_usage(ROOT).free - free_before
            stream.write(json.dumps(dict(event='complete', files=len(plan),
                logical_bytes=total, filesystem_free_bytes_change=delta,
                retained_libraries_verified=len(retained))) + '\n')
        print(f'Removed {len(plan)} objects; {delta / 1024**3:.2f} GiB filesystem '
              f'free-space increase. Receipt: {receipt}', flush=True)
    finally:
        lock.rmdir()


if __name__ == '__main__':
    main()
