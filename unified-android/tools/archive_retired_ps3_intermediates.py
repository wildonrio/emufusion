#!/usr/bin/env python3
"""Losslessly archive retired September diagnostic artifacts (dry-run default).

By default only the exact librpcs3_emu.trace.a intermediate is eligible.
--retired-symbols also archives the exact unstripped diagnostic library, without
discarding any symbols. Runnable shared libraries, sources, objects and the
active normal link inputs stay put. Recover with `gzip -dk /absolute/path/FILE.gz`.
--retired-switch includes seven completed September 9 Switch test builds, never
the live Switch build tree, October portability inputs or multiplayer rollback.
--completed-ps2-archives includes only static .a intermediates in three completed
October 5 PS2 compiler output trees. Their source, final cores and symbols stay.
--completed-ps2-symbols losslessly archives those three trials' exact unstripped
compiler outputs; the smaller runnable cores under arm64-v8a remain unchanged.
--completed-switch-archives includes five exact link/symbol outputs from the
closed October 4 Switch load/start-failure/handheld trials. All remain recoverable by gzip;
the live configured build, runnable libraries and source are never selected.
--completed-cemu-symbols archives four exact superseded linked-before.so copies;
all symbols remain recoverable and current configured/runnable libraries stay.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import time

from prune_build_apks import open_paths, unchanged
from cleanup_completed_ps2_objects_20261006 import TRIALS as COMPLETED_PS2

ROOT = Path(__file__).resolve().parents[2]
CANDIDATES = ROOT / 'engines/build/candidates'
RETIRED = re.compile(r'aps3e-[a-z0-9-]+-2026-09-0[89]\Z')
PROTECTED = {'aps3e-wrapper-sync-clean-linked-2026-09-09'}
RETIRED_SWITCH = {
    'eden-clock-recovery-2026-09-09',
    'eden-coupled-clock-2026-09-09',
    'eden-direct-feedback-v2-2026-09-09',
    'eden-missed-presentation-v2-2026-09-09',
    'eden-native-dispatch-only-2026-09-09',
    'eden-phase-preservation-2026-09-09',
    'eden-present-dispatch-2026-09-09',
}
CHUNK = 4 * 1024 * 1024
COMPLETED_SWITCH_OUTPUTS = (
    'android-portability-2026-10-04-switch-load/libcore.a',
    'android-portability-2026-10-04-switch-load/libeden-unstripped.so',
    'android-portability-2026-10-04-start-failure/libeden-unstripped.so',
    'android-portability-2026-10-04-switch-handheld/libeden-unstripped.so',
    'android-portability-2026-10-04-switch-handheld/r2/libeden-unstripped.so',
)
COMPLETED_CEMU_SYMBOLS = (
    'android-portability-2026-10-04-cemu-source-lock/linked-before.so',
    'android-portability-2026-10-05-wiiu-content-inputs/linked-before.so',
    'android-portability-2026-10-06-native-start-pause/linked-before.so',
    'android-portability-2026-10-07-wiiu-phone-screen/linked-before.so',
)


def completed_cemu_symbols(qa, opened=()):
    """Only historical before-build copies, never current outputs/link inputs."""
    if qa.resolve() != qa or qa.is_symlink():
        raise RuntimeError('Unexpected evidence root')
    result = []
    for relative in COMPLETED_CEMU_SYMBOLS:
        path = qa / relative
        trial = path.parent
        if any(p == str(trial) or p.startswith(str(trial) + '/') for p in opened):
            continue
        if not os.path.lexists(path):
            continue
        meta = path.lstat()
        if path.resolve() != path or not stat.S_ISREG(meta.st_mode):
            raise RuntimeError(f'Unexpected completed Cemu symbols: {path}')
        result.append((path, meta))
    return result


def completed_switch_archives(qa, opened=()):
    """Frozen completed-trial allowlist; not an age rule for new candidates."""
    if qa.resolve() != qa or qa.is_symlink():
        raise RuntimeError('Unexpected evidence root')
    result = []
    for relative in COMPLETED_SWITCH_OUTPUTS:
        path = qa / relative
        trial = qa / Path(relative).parts[0]
        if any(p == str(trial) or p.startswith(str(trial) + '/') for p in opened):
            continue
        if not os.path.lexists(path):
            continue
        meta = path.lstat()
        if path.resolve() != path or not stat.S_ISREG(meta.st_mode):
            raise RuntimeError(f'Unexpected completed Switch output: {path}')
        result.append((path, meta))
    return result


def completed_ps2_archives(root, opened=()):
    """Exact completed output trees, not the source or currently packaged cores.

    These trees already had their disposable .o files retired. Keep their static
    link inputs recoverable without carrying gigabytes of expanded debug data.
    No age-based selection of arbitrary October candidates is permitted.
    """
    if root.resolve() != root or root.is_symlink():
        raise RuntimeError('Unexpected candidate root')
    result = []
    for name, core in COMPLETED_PS2:
        trial = root / name
        out = trial / 'work' / core / 'out'
        if not out.exists():
            continue
        if out.resolve() != out or not out.is_dir():
            raise RuntimeError(f'Unexpected completed compiler output: {out}')
        if any(p == str(trial) or p.startswith(str(trial) + '/') for p in opened):
            continue
        for parent, _, files in os.walk(out, followlinks=False):
            for name in files:
                if not name.endswith('.a'):
                    continue
                path = Path(parent) / name
                meta = path.lstat()
                if stat.S_ISLNK(meta.st_mode):
                    continue  # Preserve CMake library aliases; never follow links.
                if path.resolve() != path or not stat.S_ISREG(meta.st_mode):
                    raise RuntimeError(f'Unexpected static archive: {path}')
                result.append((path, meta))
    return sorted(result, key=lambda item: str(item[0]))


def completed_ps2_symbols(root, opened=()):
    """Only the linked debug copy from each already-closed PS2 compiler tree."""
    if root.resolve() != root or root.is_symlink():
        raise RuntimeError('Unexpected candidate root')
    result = []
    for name, core in COMPLETED_PS2:
        trial = root / name
        if any(p == str(trial) or p.startswith(str(trial) + '/') for p in opened):
            continue
        path = trial / 'work' / core / 'out/pcsx2-libretro/armsx2_libretro.so'
        if not os.path.lexists(path):
            continue
        meta = path.lstat()
        if path.resolve() != path or not stat.S_ISREG(meta.st_mode):
            raise RuntimeError(f'Unexpected completed PS2 debug output: {path}')
        # Never remove a runnable core in order to retain only debug material.
        runtime_name = 'armsx2_16k_libretro.so' if '_16k-' in core else 'armsx2_libretro.so'
        runtime = trial / 'arm64-v8a' / runtime_name
        if (runtime.resolve() != runtime or not runtime.is_file()
                or os.path.samefile(path, runtime)):
            raise RuntimeError(f'Missing or aliased retained runtime core: {runtime}')
        result.append((path, meta))
    return result


def select(root, now, opened=(), retired_symbols=False, retired_switch=False):
    if root.resolve() != root or root.is_symlink():
        raise RuntimeError('Unexpected candidate root')
    result = []
    for folder in sorted(root.iterdir()):
        switch_trial = retired_switch and folder.name in RETIRED_SWITCH
        if ((not RETIRED.fullmatch(folder.name) and not switch_trial) or folder.name in PROTECTED
                or folder.is_symlink() or not folder.is_dir()):
            continue
        # A live diagnostic may have an object or runnable library open, not
        # just its symbol file. Do not retire anything from that candidate.
        if any(p == str(folder) or p.startswith(str(folder) + '/') for p in opened):
            continue
        names = (['libcore.a', 'libvideo_core.a', 'libeden.unstripped.so']
                 if switch_trial else ['librpcs3_emu.trace.a'])
        if retired_symbols and not switch_trial:
            names.append('liblucent_native_adapter_aps3e.trace.unstripped.so')
        for name in names:
            path = folder / name
            if not path.exists():
                continue
            meta = path.lstat()
            if (stat.S_ISREG(meta.st_mode)
                    and now - meta.st_mtime >= 14 * 86400):
                result.append((path, meta))
    return result


def record(receipt, **entry):
    receipt.write(json.dumps(entry) + '\n')
    receipt.flush()
    os.fsync(receipt.fileno())


def archive(path, meta, receipt, opened):
    target = path.with_name(path.name + '.gz')
    partial = path.with_name(path.name + '.gz.partial')
    if (target.exists() or target.is_symlink() or partial.exists()
            or partial.is_symlink() or not unchanged(path, meta)):
        raise RuntimeError(f'Changed input or archive already exists: {path}')
    digest = hashlib.sha256()
    with partial.open('xb') as output:
        with gzip.GzipFile(filename='', mode='wb', fileobj=output,
                           compresslevel=1, mtime=int(meta.st_mtime)) as zipped:
            with path.open('rb') as source:
                for block in iter(lambda: source.read(CHUNK), b''):
                    digest.update(block)
                    zipped.write(block)
        output.flush()
        os.fsync(output.fileno())
    verified = hashlib.sha256()
    restored_bytes = 0
    with gzip.open(partial, 'rb') as source:
        for block in iter(lambda: source.read(CHUNK), b''):
            restored_bytes += len(block)
            verified.update(block)
    in_use = any(p == str(path.parent) or p.startswith(str(path.parent) + '/')
                 for p in opened())
    if (restored_bytes != meta.st_size or verified.digest() != digest.digest()
            or not unchanged(path, meta) or in_use):
        raise RuntimeError(f'Archive verification/input guard failed: {path}')
    # Same-filesystem link publishes without ever replacing an existing archive.
    os.link(partial, target)
    partial.unlink()
    record(receipt, event='verified_archive', original=str(path), archive=str(target),
           sha256=digest.hexdigest(), original_bytes=meta.st_size,
           compressed_bytes=target.stat().st_size, original_mode=stat.S_IMODE(meta.st_mode))
    if not unchanged(path, meta):
        raise RuntimeError(f'Input changed before retirement: {path}')
    path.unlink()
    record(receipt, event='removed_uncompressed_copy', path=str(path))
    return meta.st_size - target.stat().st_size


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--retired-symbols', action='store_true',
                        help='Also losslessly archive old diagnostic symbols; keep runnable libraries')
    parser.add_argument('--retired-switch', action='store_true',
                        help='Also archive seven explicitly retired September Switch trials')
    parser.add_argument('--completed-ps2-archives', action='store_true',
                        help='Also archive static link inputs from three completed PS2 builds')
    parser.add_argument('--completed-ps2-symbols', action='store_true',
                        help='Losslessly archive debug copies from those three closed PS2 builds')
    parser.add_argument('--completed-switch-archives', action='store_true',
                        help='Also archive five exact closed October 4 Switch link/symbol outputs')
    parser.add_argument('--completed-cemu-symbols', action='store_true',
                        help='Archive four superseded Cemu before-build debug copies')
    args = parser.parse_args()
    build = ROOT / 'unified-android/build'
    if build.resolve() != build:
        raise RuntimeError('Unexpected build root')
    lock = build / '.lucent-build-lock'
    lock.mkdir()
    try:
        opened = open_paths()
        selected = select(CANDIDATES, time.time(), opened, args.retired_symbols,
                          args.retired_switch)
        if args.completed_ps2_archives:
            selected += completed_ps2_archives(CANDIDATES, opened)
        if args.completed_ps2_symbols:
            selected += completed_ps2_symbols(CANDIDATES, opened)
        if args.completed_switch_archives:
            selected += completed_switch_archives(ROOT / 'docs/qa', opened)
        if args.completed_cemu_symbols:
            selected += completed_cemu_symbols(ROOT / 'docs/qa', opened)
        tracked = subprocess.check_output(['git', 'ls-files', '-z', '--',
            'engines/build/candidates', 'docs/qa'], cwd=ROOT).decode().split('\0')
        tracked = {str(ROOT / p) for p in tracked if p}
        if any(str(p) in tracked for p, _ in selected):
            raise RuntimeError('Refusing to archive tracked inputs')
        total = sum(meta.st_size for _, meta in selected)
        print(f'{len(selected)} retired intermediates; {total / 1024**3:.2f} GiB; '
              f'{"apply" if args.apply else "dry-run"}', flush=True)
        if not args.apply:
            for path, _ in selected:
                print(path)
            return
        receipts = build / 'retention-receipts'
        receipts.mkdir(exist_ok=True)
        if receipts.resolve() != receipts:
            raise RuntimeError('Unexpected receipt directory')
        scope = 'ps3-switch' if args.retired_switch else 'ps3'
        if args.completed_ps2_archives:
            scope += '-ps2'
        if args.completed_ps2_symbols:
            scope += '-ps2-symbols'
        if args.completed_switch_archives:
            scope += '-october-switch'
        if args.completed_cemu_symbols:
            scope += '-cemu-symbols'
        receipt_path = receipts / f'{time.time_ns()}-retired-{scope}-intermediates.jsonl'
        before = shutil.disk_usage(build).free
        saved = 0
        with receipt_path.open('x') as receipt:
            for index, (path, meta) in enumerate(selected, 1):
                saved += archive(path, meta, receipt, open_paths)
                print(f'{index}/{len(selected)} ({100 * index // len(selected)}%): '
                      f'{saved / 1024**3:.2f} GiB net archived', flush=True)
            delta = shutil.disk_usage(build).free - before
            record(receipt, event='complete', files=len(selected), net_logical_bytes=saved,
                   filesystem_free_bytes_change=delta,
                   recovery='gzip -dk ORIGINAL_PATH.gz; every original SHA-256 is recorded')
        print(f'Finished: {saved / 1024**3:.2f} GiB net; '
              f'{delta / 1024**3:.2f} GiB filesystem free-space increase; {receipt_path}', flush=True)
    finally:
        lock.rmdir()


if __name__ == '__main__':
    main()
