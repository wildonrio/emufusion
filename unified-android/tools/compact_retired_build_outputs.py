#!/usr/bin/env python3
"""Compact old generated output, preserving evidence; dry-run unless --apply.

Only September-or-earlier runtime-test logcat text files and two exact retired
decoded library directories are eligible. Logs are SHA-verified gzip archives.
Decoded libraries must match the retained, hash-pinned compressed APK exactly.
--ocr-caches also removes old derived OCR PNGs only when their original
screenshot remains. Never selects games, saves, source, active candidates,
original screenshots, or native symbol files.
--closed-traces losslessly archives six exact September 16 trace captures;
their completed watchdog markers and summary/evidence remain in place.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import time
import zipfile

from archive_retired_ps3_intermediates import archive, record
from prune_build_apks import open_paths, sha256, unchanged

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'unified-android/build'
TRIAL = ROOT / 'engines/build/candidates/ps3-log-access-2026-09-09'
RECOVERY = TRIAL / 'manifest-build.apk'
RECOVERY_SHA = '9998e201d2bda021c372303a73bd4fbc7a02486f3ef6043377e73898025bac27'
LOG_NAME = re.compile(r'[\w.-]*logcat[\w.-]*\.txt\Z')
TRIAL_NAME = re.compile(r'(?:runtime-acceptance|runtime-framegen|runtime-quality|framegen|phase[12]|one-window)[\w.-]*\Z')
# A frozen boundary, not an expanding age rule that could capture future work.
CUTOFF = datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp()
OCR_NAME = re.compile(r'\.(.+\.png)\.ocr-boost\.png\Z')
PNG_HEADER = b'\x89PNG\r\n\x1a\n'
CLOSED_TRACES = (
    'rife-async-live-qwCmJk/async.atrace',
    'rife-acquire-live-Msnkm2/acquire.atrace',
    'rife-submit-live-fYdhcK/submit.atrace',
    'rife-triggered-H9ba3t/failure.atrace',
    'rife-owner-trace-live-kbF5MM/owner.atrace',
    'rife-owner-trace-live-kbF5MM/steady.atrace',
)


def select_closed_traces(qa, opened, tracked):
    """Frozen, closed trials only; never an age rule for future captures."""
    if qa.resolve() != qa:
        raise RuntimeError('Unexpected trace root')
    selected = []
    for relative in CLOSED_TRACES:
        path = qa / relative
        if not os.path.lexists(path):
            continue
        if any(p == str(path.parent) or p.startswith(str(path.parent) + '/')
               for p in opened) or str(path) in tracked:
            continue
        meta = path.lstat()
        if path.resolve() != path or not stat.S_ISREG(meta.st_mode):
            raise RuntimeError(f'Unexpected trace path: {path}')
        for name in ('watchdog-ended', 'stop-test'):
            marker = path.parent / name
            if marker.resolve() != marker or not marker.is_file():
                raise RuntimeError(f'Missing completed-trial marker: {marker}')
        selected.append((path, meta))
    return selected


def select_ocr_caches(build, opened, tracked, now):
    """Only regenerable aids created by run_runtime_acceptance_qa.ocr()."""
    if build.resolve() != build:
        raise RuntimeError('Unexpected build directory')
    selected = []
    for folder in sorted(build.iterdir()):
        if folder.is_symlink() or not folder.is_dir() or not TRIAL_NAME.fullmatch(folder.name):
            continue
        if any(p == str(folder) or p.startswith(str(folder) + '/') for p in opened):
            continue
        for path in sorted(folder.iterdir()):
            match = OCR_NAME.fullmatch(path.name)
            if not match:
                continue
            original = folder / match[1]
            meta = path.lstat()
            if (not stat.S_ISREG(meta.st_mode) or str(path) in tracked
                    or meta.st_mtime >= CUTOFF or now - meta.st_mtime <= 30 * 86400
                    or not original.exists() or original.is_symlink()):
                continue
            source_meta = original.lstat()
            if not stat.S_ISREG(source_meta.st_mode):
                continue
            with path.open('rb') as cache, original.open('rb') as source:
                if cache.read(8) != PNG_HEADER or source.read(8) != PNG_HEADER:
                    continue
            selected.append((path, meta, original, source_meta))
    return selected


def remove_ocr_cache(path, meta, original, source_meta, receipt):
    if not unchanged(path, meta) or not unchanged(original, source_meta):
        raise RuntimeError(f'OCR input changed: {path}')
    source_sha = sha256(original)
    cache_sha = sha256(path)
    if not unchanged(path, meta) or not unchanged(original, source_meta):
        raise RuntimeError(f'OCR input changed during verification: {path}')
    record(receipt, event='planned_ocr_cache_removal', path=str(path),
           sha256=cache_sha, bytes=meta.st_size, original=str(original),
           original_sha256=source_sha,
           recovery='PIL.ImageOps.autocontrast(Image.open(original).convert("L"), '
                    'cutoff=1).save(cache_path); original screenshot retained')
    path.unlink()
    record(receipt, event='ocr_cache_removed', path=str(path))
    return meta.st_size


def select_logs(build, opened, tracked, now):
    selected = []
    for folder in sorted(build.iterdir()):
        if folder.is_symlink() or not folder.is_dir() or not TRIAL_NAME.fullmatch(folder.name):
            continue
        if any(p == str(folder) or p.startswith(str(folder) + '/') for p in opened):
            continue
        for path in sorted(folder.iterdir()):
            meta = path.lstat()
            if (LOG_NAME.fullmatch(path.name) and stat.S_ISREG(meta.st_mode)
                    and meta.st_size >= 1024 * 1024
                    and meta.st_mtime < CUTOFF and now - meta.st_mtime > 30 * 86400
                    and str(path) not in tracked
                    and not os.path.lexists(str(path) + '.gz')
                    and not os.path.lexists(str(path) + '.gz.partial')):
                selected.append((path, meta))
    return selected


def decoded_libraries(trial, recovery, opened, tracked):
    if trial.resolve() != trial or recovery.is_symlink() or sha256(recovery) != RECOVERY_SHA:
        raise RuntimeError('Retained recovery APK identity differs')
    if any(p == str(trial) or p.startswith(str(trial) + '/') for p in opened):
        raise RuntimeError('Retired packaging trial is in use')
    result = []
    with zipfile.ZipFile(recovery) as apk:
        for name in ('decoded', 'resources-decoded'):
            folder = trial / name / 'lib'
            if not folder.exists():
                continue
            if folder.resolve() != folder:
                raise RuntimeError('Decoded library directory contains a symlink')
            for path in sorted(folder.rglob('*')):
                meta = path.lstat()
                if stat.S_ISDIR(meta.st_mode):
                    continue
                if (not stat.S_ISREG(meta.st_mode) or path.resolve() != path
                        or path.suffix != '.so' or str(path) in tracked):
                    raise RuntimeError(f'Unexpected decoded input: {path}')
                member = str(path.relative_to(trial / name))
                with apk.open(member) as stream:
                    hasher = hashlib.sha256()
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        hasher.update(block)
                    digest = hasher.hexdigest()
                if sha256(path) != digest or not unchanged(path, meta):
                    raise RuntimeError(f'Decoded library differs from recovery: {path}')
                result.append((path, meta, member, digest))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--ocr-caches', action='store_true')
    parser.add_argument('--closed-traces', action='store_true')
    args = parser.parse_args()
    if BUILD.resolve() != BUILD:
        raise RuntimeError('Unexpected build directory')
    lock = BUILD / '.lucent-build-lock'
    lock.mkdir()
    try:
        opened = open_paths()
        tracked = {str(ROOT / p) for p in subprocess.check_output(
            ['git', 'ls-files', '-z', '--', 'unified-android/build',
             'engines/build/candidates/ps3-log-access-2026-09-09', 'docs/qa'], cwd=ROOT
        ).decode().split('\0') if p}
        logs = select_logs(BUILD, opened, tracked, time.time())
        traces = select_closed_traces(ROOT / 'docs/qa', opened, tracked) if args.closed_traces else []
        libraries = decoded_libraries(TRIAL, RECOVERY, opened, tracked)
        caches = select_ocr_caches(BUILD, opened, tracked, time.time()) if args.ocr_caches else []
        print(f'{len(logs)} old logs ({sum(m.st_size for _, m in logs)/1024**3:.2f} GiB); '
              f'{len(libraries)} redundant decoded libraries '
              f'({sum(m.st_size for _, m, _, _ in libraries)/1024**3:.2f} GiB); '
              f'{len(caches)} derived OCR caches '
              f'({sum(m.st_size for _, m, _, _ in caches)/1024**3:.2f} GiB); '
              f'{len(traces)} closed traces '
              f'({sum(m.st_size for _, m in traces)/1024**3:.2f} GiB); '
              f'{"apply" if args.apply else "dry-run"}', flush=True)
        if not args.apply:
            return
        receipt_dir = BUILD / 'retention-receipts'
        if receipt_dir.resolve() != receipt_dir:
            raise RuntimeError('Unexpected receipt directory')
        receipt_dir.mkdir(exist_ok=True)
        receipt_path = receipt_dir / f'{time.time_ns()}-retired-output-compaction.jsonl'
        before = shutil.disk_usage(BUILD).free
        saved = 0
        with receipt_path.open('x') as receipt:
            record(receipt, event='retained_recovery', path=str(RECOVERY), sha256=RECOVERY_SHA,
                   recovery='Logs: gzip -dk FILE.txt.gz. Libraries: extract recorded ZIP member '
                            'from retained manifest-build.apk into the recorded original path.')
            for index, (path, meta) in enumerate(logs, 1):
                saved += archive(path, meta, receipt, open_paths)
                if index % 20 == 0 or index == len(logs):
                    print(f'Logs {index}/{len(logs)}: {saved/1024**3:.2f} GiB saved', flush=True)
            for index, (path, meta) in enumerate(traces, 1):
                saved += archive(path, meta, receipt, open_paths)
                print(f'Traces {index}/{len(traces)}: {saved/1024**3:.2f} GiB saved', flush=True)
            opened = open_paths()
            if (sha256(RECOVERY) != RECOVERY_SHA or
                    any(p == str(TRIAL) or p.startswith(str(TRIAL) + '/') for p in opened)):
                raise RuntimeError('Recovery changed or trial became active')
            for path, meta, member, digest in libraries:
                if not unchanged(path, meta):
                    raise RuntimeError(f'Decoded copy changed: {path}')
                record(receipt, event='planned_duplicate_removal', path=str(path),
                       sha256=digest, bytes=meta.st_size, recovery_member=member)
                path.unlink()
                record(receipt, event='duplicate_removed', path=str(path))
                saved += meta.st_size
            if sha256(RECOVERY) != RECOVERY_SHA:
                raise RuntimeError('Recovery APK changed')
            opened = open_paths()
            cache_folders = {str(path.parent) for path, _, _, _ in caches}
            if any(p == folder or p.startswith(folder + '/')
                   for p in opened for folder in cache_folders):
                raise RuntimeError('An OCR trial became active')
            for index, row in enumerate(caches, 1):
                saved += remove_ocr_cache(*row, receipt)
                if index % 500 == 0 or index == len(caches):
                    print(f'OCR caches {index}/{len(caches)}: {saved/1024**3:.2f} GiB saved', flush=True)
            delta = shutil.disk_usage(BUILD).free - before
            record(receipt, event='complete', logs=len(logs), decoded_copies=len(libraries),
                   ocr_caches=len(caches),
                   closed_traces=len(traces),
                   net_logical_bytes=saved, filesystem_free_bytes_change=delta,
                   recovery_apk_verified=True)
        print(f'Finished: {saved/1024**3:.2f} GiB net logical; '
              f'{delta/1024**3:.2f} GiB filesystem increase. Receipt: {receipt_path}', flush=True)
    finally:
        lock.rmdir()


if __name__ == '__main__':
    main()
