"""Remove the October 6 successful build's leftover scratch; dry-run by default."""
import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import time
import zipfile

from prune_build_apks import open_paths, sha256, unchanged

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'unified-android/build'
DIGEST = '59521d8bbff477d03658f54d49b4e2998c6a9272210186ca89c965c531334924'
APK = BUILD / f'lucent-3.2.16-lsfg-framegen-qualification-{DIGEST}.apk'
TARGETS = tuple(BUILD / name for name in ('work', 'classes', 'stub-classes', 'dex'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if BUILD.resolve() != BUILD or APK.is_symlink():
        raise RuntimeError('Unexpected build or APK path')
    lock = BUILD / '.lucent-build-lock'
    lock.mkdir()  # Do not race the assembler or steal a live lock.
    try:
        if sha256(APK) != DIGEST:
            raise RuntimeError('Completed signed APK changed')
        tracked = subprocess.check_output(['git', 'ls-files', '-z', '--',
            *(str(p.relative_to(ROOT)) for p in TARGETS)], cwd=ROOT)
        if tracked:
            raise RuntimeError('Scratch contains tracked files')
        files = []
        for target in TARGETS:
            if not target.exists():
                continue
            if target.resolve() != target or not target.is_dir():
                raise RuntimeError(f'Unexpected scratch root: {target}')
            for path in target.rglob('*'):
                meta = path.lstat()
                if not (stat.S_ISREG(meta.st_mode) or stat.S_ISDIR(meta.st_mode)):
                    raise RuntimeError(f'Unexpected scratch entry: {path}')
                if stat.S_ISREG(meta.st_mode):
                    files.append((path, meta))
        with zipfile.ZipFile(APK) as archive:
            for name in ('work/classes2.dex', 'dex/classes.dex'):
                path = BUILD / name
                if path.exists() and path.read_bytes() != archive.read('classes2.dex'):
                    raise RuntimeError(f'Dex differs from completed APK: {path}')
            decoded = BUILD / 'work/apk'
            for name in ('lib', 'assets'):
                for path in (decoded / name).rglob('*'):
                    if path.is_file() and path.read_bytes() != archive.read(
                            str(path.relative_to(decoded))):
                        raise RuntimeError(f'Bundled input differs: {path}')
        opened = open_paths()
        if any(p == str(t) or p.startswith(str(t) + '/') for p in opened for t in TARGETS):
            raise RuntimeError('Scratch is in use')
        if any(not unchanged(p, meta) for p, meta in files):
            raise RuntimeError('Scratch changed during inspection')
        total = sum(meta.st_size for _, meta in files)
        print(f'{len(files)} regenerable assembly files; {total / 1024**3:.2f} GiB', flush=True)
        if not args.apply or not files:
            return
        before = shutil.disk_usage(BUILD).free
        receipt = BUILD / 'retention-receipts' / f'{time.time_ns()}-assembly-scratch.jsonl'
        with receipt.open('x') as stream:
            stream.write(json.dumps(dict(event='verified_apk', path=str(APK), sha256=DIGEST)) + '\n')
            for target in TARGETS:
                if not target.exists():
                    continue
                stream.write(json.dumps(dict(event='planned_remove', path=str(target))) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
                shutil.rmtree(target)
                stream.write(json.dumps(dict(event='removed', path=str(target))) + '\n')
            if sha256(APK) != DIGEST:
                raise RuntimeError('Retained APK changed')
            delta = shutil.disk_usage(BUILD).free - before
            stream.write(json.dumps(dict(event='complete', files=len(files), logical_bytes=total,
                filesystem_free_bytes_change=delta, retained_apk_verified=True,
                recovery='Regenerate with unified-android/build-portable.sh; source and signed APK retained')) + '\n')
        print(f'Reclaimed {delta / 1024**3:.2f} GiB; receipt: {receipt}')
    finally:
        lock.rmdir()


if __name__ == '__main__':
    main()
