"""Retire old RIFE benchmark compiler objects, not source or symbols.

Dry-run by default. The scope is the benchmark app's generated .cxx directory
before October 2026; the newest configuration of each build type is retained.
All static archives and linked, unstripped libraries remain. Ninja/Gradle can
recreate missing objects from retained source and generated build recipes.
--static-archives instead losslessly compresses the old static archives; the
newest configurations, linked debug libraries and source still remain intact.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import time

from prune_build_apks import open_paths, sha256, unchanged
from archive_retired_ps3_intermediates import archive, record

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'experiments/rife-ncnn-vulkan-android/android-benchmark/app'
CUTOFF = datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp()


def regular(path):
    if path.resolve() != path or not stat.S_ISREG(path.lstat().st_mode):
        raise RuntimeError(f'Not an unaliased regular file: {path}')
    return path.stat()


def select(app, opened=(), tracked=()):
    if app.resolve() != app or not app.is_dir():
        raise RuntimeError('Unexpected benchmark app root')
    # A live compiler might not yet have opened the particular object selected.
    if any(p == str(app) or p.startswith(str(app) + '/') for p in opened):
        raise RuntimeError('Benchmark app is in use')
    objects, retained = [], set()
    for variant in ('Debug', 'RelWithDebInfo'):
        parent = app / '.cxx' / variant
        if not parent.exists():
            continue
        if parent.resolve() != parent:
            raise RuntimeError('Aliased compiler root')
        configs = []
        for config in parent.iterdir():
            if not config.is_dir() or config.resolve() != config:
                raise RuntimeError(f'Unexpected compiler configuration: {config}')
            abi = config / 'arm64-v8a'
            cache, ninja = abi / 'CMakeCache.txt', abi / 'build.ninja'
            if not cache.is_file() or not ninja.is_file():
                continue
            configs.append((regular(ninja).st_mtime_ns, abi, cache, ninja))
        # Preserve the newest incremental configuration even when it is old.
        configs.sort(key=lambda item: (item[0], str(item[1])), reverse=True)
        for _, abi, cache, ninja in configs[1:]:
            if max(regular(cache).st_mtime, regular(ninja).st_mtime) >= CUTOFF:
                continue
            library = (app / 'build/intermediates/cxx' / variant / abi.parent.name
                       / 'obj/arm64-v8a/librife_benchmark.so')
            if not library.exists():
                continue  # Incomplete trial: do not discard its objects.
            regular(library)
            description = subprocess.check_output(['file', str(library)], text=True)
            if 'with debug_info, not stripped' not in description:
                raise RuntimeError(f'Missing linked debug symbols: {library}')
            trial_objects, trial_retained = [], {library, cache, ninja}
            recent = False
            for base, _, names in os.walk(abi, followlinks=False):
                for name in names:
                    path = Path(base) / name
                    if path.suffix not in ('.o', '.a', '.so'):
                        continue
                    meta = regular(path)
                    if meta.st_mtime >= CUTOFF:
                        recent = True
                    if path.suffix == '.o':
                        if str(path) in tracked:
                            raise RuntimeError(f'Tracked object: {path}')
                        trial_objects.append((path, meta))
                    else:
                        trial_retained.add(path)
            if not recent:
                objects.extend(trial_objects)
                retained.update(trial_retained)
    return sorted(objects), sorted(retained)


def static_archive_plan(app, opened=(), tracked=()):
    _, retained = select(app, opened, tracked)
    plan = []
    for path in retained:
        if path.suffix != '.a':
            continue
        if str(path) in tracked:
            raise RuntimeError(f'Tracked static archive: {path}')
        if any(os.path.lexists(str(path) + suffix) for suffix in ('.gz', '.gz.partial')):
            raise RuntimeError(f'Existing archive or incomplete compaction: {path}')
        plan.append((path, regular(path)))
    return plan, [p for p in retained if p.suffix != '.a']


def compact_static_archives(build, tracked, apply):
    plan, retained = static_archive_plan(APP, open_paths(), tracked)
    total = sum(meta.st_size for _, meta in plan)
    print(f'{len(plan)} retired static archives; {total / 1024**3:.3f} GiB expanded; '
          f'{"apply" if apply else "dry-run"}', flush=True)
    if not apply or not plan:
        return
    identities = {str(path): sha256(path) for path in retained}
    again, _ = static_archive_plan(APP, open_paths(), tracked)
    if again != plan:
        raise RuntimeError('Static archives changed during inspection')
    receipts = build / 'retention-receipts'
    if receipts.resolve() != receipts or not receipts.is_dir():
        raise RuntimeError('Unexpected receipt directory')
    receipt = receipts / f'{time.time_ns()}-retired-rife-static-archives.jsonl'
    before = shutil.disk_usage(build).free
    saved = 0
    with receipt.open('x') as stream:
        record(stream, event='retained', sha256=identities,
               recovery='gzip -dk EXACT_ARCHIVE_PATH.a.gz; each original SHA-256 is recorded. '
                        'Newest incremental caches and all linked debug libraries retained.')
        for index, (path, meta) in enumerate(plan, 1):
            saved += archive(path, meta, stream, open_paths)
            print(f'{index}/{len(plan)} ({100 * index // len(plan)}%): '
                  f'{saved / 1024**3:.3f} GiB net reclaimed', flush=True)
        if any(sha256(Path(p)) != digest for p, digest in identities.items()):
            raise RuntimeError('Retained debug library or recipe changed')
        delta = shutil.disk_usage(build).free - before
        record(stream, event='complete', files=len(plan), net_logical_bytes=saved,
               filesystem_free_bytes_change=delta, retained_hashes_verified=len(identities))
    print(f'Finished: {saved / 1024**3:.3f} GiB net; '
          f'{delta / 1024**3:.3f} GiB filesystem increase. Receipt: {receipt}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--static-archives', action='store_true',
                        help='Losslessly compact retired static archives instead of removing objects')
    args = parser.parse_args()
    build = ROOT / 'unified-android/build'
    lock = build / '.lucent-build-lock'
    lock.mkdir()
    try:
        tracked = {str(ROOT / name) for name in subprocess.check_output(
            ['git', 'ls-files', '-z', '--', str(APP.relative_to(ROOT))], cwd=ROOT
        ).decode().split('\0') if name}
        if args.static_archives:
            compact_static_archives(build, tracked, args.apply)
            return
        plan, retained = select(APP, open_paths(), tracked)
        total = sum(meta.st_size for _, meta in plan)
        print(f'{len(plan)} obsolete objects; {total / 1024**3:.3f} GiB; '
              f'{len(retained)} libraries/archives/recipes retained; '
              f'{"apply" if args.apply else "dry-run"}', flush=True)
        if not args.apply or not plan:
            return
        identities = {str(path): sha256(path) for path in retained}
        again, _ = select(APP, open_paths(), tracked)
        if again != plan or any(not unchanged(p, m) for p, m in plan):
            raise RuntimeError('Compiler outputs changed during inspection')
        before = shutil.disk_usage(build).free
        receipt = build / 'retention-receipts' / f'{time.time_ns()}-retired-rife-objects.jsonl'
        with receipt.open('x') as stream:
            def record(**entry):
                stream.write(json.dumps(entry) + '\n')
                stream.flush()
            record(event='retained', sha256=identities,
                   recovery='Rebuild benchmark with its retained Gradle/CMake recipes; '
                            'objects removed, linked debug libraries and archives retained.')
            for path, meta in plan:
                regular(path)
                if not unchanged(path, meta):
                    raise RuntimeError(f'Object changed: {path}')
                record(event='planned_unlink', path=str(path), bytes=meta.st_size)
                path.unlink()
                record(event='unlinked', path=str(path))
            if any(sha256(Path(p)) != digest for p, digest in identities.items()):
                raise RuntimeError('Retained library or recipe changed')
            delta = shutil.disk_usage(build).free - before
            record(event='complete', removed_files=len(plan), logical_bytes=total,
                   filesystem_free_bytes_change=delta,
                   retained_hashes_verified=len(identities))
            os.fsync(stream.fileno())
        print(f'Reclaimed {total / 1024**3:.3f} GiB logical; '
              f'{delta / 1024**3:.3f} GiB filesystem increase. Receipt: {receipt}', flush=True)
    finally:
        lock.rmdir()


if __name__ == '__main__':
    main()
