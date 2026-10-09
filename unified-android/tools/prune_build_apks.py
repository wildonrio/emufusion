#!/usr/bin/env python3
"""Bound APK history without touching sources, ROMs, saves or native symbols.

Dry-run by default. Normally only direct, content-addressed APK children of the
fixed assembly directory are eligible. Optional retired-diagnostics maintenance
also visits named old test packages in the three fixed diagnostic roots.
Pin installed/rollback APK hashes in
build-retention.json BEFORE a deployment. Historical QA references are receipts,
not permanent binary retention requests. Recursive maintenance only selects the
explicit diagnostic APK names, not arbitrary files or directories.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
NAME = re.compile(r"lucent-(\d+\.\d+\.\d+)(.*)-([a-f0-9]{64})\.apk\Z")
DIAGNOSTIC_NAME = re.compile(
    r"(?:emufusion-[\w.-]+|installed-base|unsigned|aligned|nes-title-01-nes-candidate)\.apk\Z")
LEGACY_BUILD_NAME = re.compile(r"lucent-[\w.-]+\.apk\Z")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def select(build, policy, now, opened=()):
    """Pure selection: metadata snapshot is rechecked before any unlink."""
    keep = policy["keep_per_flavor"]
    days = policy["minimum_age_days"]
    if not isinstance(keep, int) or keep < 1 or not isinstance(days, (int, float)) or days < 1:
        raise ValueError("Retention must keep at least one build and one day")
    pins = set(policy["pinned_sha256"])
    if any(not re.fullmatch(r"[a-f0-9]{64}", pin) for pin in pins):
        raise ValueError("Invalid pinned SHA-256")
    groups = {}
    for path in build.iterdir():
        match = NAME.fullmatch(path.name)
        meta = path.lstat()
        if match and stat.S_ISREG(meta.st_mode):
            # Versions do not create unbounded additional retention buckets.
            groups.setdefault(match[2], []).append((path, meta, match[3]))
    candidates = []
    for entries in groups.values():
        entries.sort(key=lambda item: (item[1].st_mtime_ns, item[0].name), reverse=True)
        for path, meta, digest in entries[keep:]:
            if (digest not in pins and str(path) not in opened
                    and now - meta.st_mtime >= days * 86400):
                candidates.append((path, meta, digest))
    return sorted(candidates, key=lambda item: item[0].name)


def unchanged(path, meta):
    current = path.lstat()
    return (stat.S_ISREG(current.st_mode)
            and (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns,
                 current.st_ctime_ns)
            == (meta.st_dev, meta.st_ino, meta.st_size, meta.st_mtime_ns, meta.st_ctime_ns))


def retired_diagnostics(roots, now, opened):
    """Explicit maintenance only: retired test packages, never native outputs."""
    found = []
    for root in roots:
        if root.is_symlink() or root.resolve() != root:
            raise RuntimeError(f"Unexpected diagnostic root: {root}")
        # os.walk does not follow symlink directories; also reject symlink files.
        for parent, _, files in os.walk(root, followlinks=False):
            for name in files:
                if not DIAGNOSTIC_NAME.fullmatch(name):
                    continue
                path = Path(parent) / name
                meta = path.lstat()
                if (stat.S_ISREG(meta.st_mode) and str(path) not in opened
                        and now - meta.st_mtime >= 14 * 86400):
                    found.append((path, meta, None))
    return sorted(found, key=lambda item: item[0].name)


def completed_diagnostics(root, roots, policy, opened):
    """Explicitly closed trials need not wait 14 days or retain stale pins.

    Only exact recorded APK paths/hashes are eligible; their optional v4 signing
    sidecars are disposable too. Recipes, evidence and native libraries stay.
    Missing entries are normal on subsequent builds. Pins always win.
    """
    found = []
    for relative, entry in policy.get("retired_diagnostic_apks", {}).items():
        path = root / relative
        digest = entry["sha256"]
        if (Path(relative).is_absolute() or ".." in Path(relative).parts
                or not any(path.is_relative_to(folder) for folder in roots)
                # Exact path + hash + reason is the allowlist for closed trials.
                # Custom names must not require a broad recursive deletion rule.
                or path.suffix != ".apk"
                or not re.fullmatch(r"[a-f0-9]{64}", digest)
                or not entry.get("reason")):
            raise ValueError(f"Invalid completed diagnostic: {relative}")
        if path.resolve() != path:
            raise RuntimeError(f"Symlink in completed diagnostic: {relative}")
        if not path.exists() or digest in policy["pinned_sha256"]:
            continue
        targets = [path, Path(str(path) + ".idsig")]
        # Preserve both files when either is open.
        if any(str(target) in opened for target in targets):
            continue
        for target in targets:
            if target.is_symlink():
                raise RuntimeError(f"Symlink in completed diagnostic: {target}")
            if not target.exists():
                continue
            meta = target.lstat()
            if not stat.S_ISREG(meta.st_mode):
                raise RuntimeError(f"Not a regular diagnostic file: {target}")
            found.append((target, meta, digest if target == path else None))
    return found


def open_paths():
    # Do not print process arguments, environment, or unrelated open filenames.
    result = subprocess.run(["lsof", "-n", "-P", "-F", "n"],
                            capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError("Cannot inspect open files; refusing APK cleanup")
    return {line[1:] for line in result.stdout.splitlines() if line.startswith("n/")}


def orphan_signatures(roots, now, opened, pins):
    """Retire stale signing sidecars only when their generated APK is absent."""
    found = []
    for root in roots:
        if root.is_symlink() or root.resolve() != root:
            raise RuntimeError(f"Unexpected signature root: {root}")
        for parent, _, files in os.walk(root, followlinks=False):
            for name in files:
                if not name.endswith(".apk.idsig"):
                    continue
                path = Path(parent) / name
                apk = path.with_suffix("")
                match = NAME.fullmatch(apk.name)
                if not (match or LEGACY_BUILD_NAME.fullmatch(apk.name)
                        or DIAGNOSTIC_NAME.fullmatch(apk.name)):
                    continue
                meta = path.lstat()
                if (stat.S_ISREG(meta.st_mode) and not os.path.lexists(apk)
                        and str(path) not in opened and str(apk) not in opened
                        and now - meta.st_mtime >= 86400
                        and (not match or match[3] not in pins)):
                    found.append((path, meta, None))
    return sorted(found, key=lambda item: str(item[0]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--retired-diagnostics", action="store_true",
                        help="Prune named diagnostic APKs older than 14 days and explicitly closed trials")
    parser.add_argument("--build-lock-owner", type=int,
                        help="Called by the build.sh parent while it owns the assembly lock")
    args = parser.parse_args()
    build = PROJECT / "build"
    if build.is_symlink() or build.resolve() != build or not build.is_dir():
        raise RuntimeError("Unexpected build directory")
    policy = json.loads((PROJECT / "build-retention.json").read_text())
    # Always preserve current public releases, even if the pin list is stale.
    release = json.loads((PROJECT.parent / "release-manifest.json").read_text())
    for key, value in release.items():
        if key.lower().endswith("sha256") and isinstance(value, str):
            policy["pinned_sha256"][value] = "Current release manifest"
    lock = build / ".lucent-build-lock"
    owned = False
    if args.build_lock_owner is not None:
        if (args.build_lock_owner != os.getppid() or lock.is_symlink()
                or (lock / "pid").read_text().strip() != str(args.build_lock_owner)):
            raise RuntimeError("Build-lock ownership mismatch")
    else:
        # Same lock as build.sh: no stale-lock override or concurrent assembly.
        lock.mkdir()
        owned = True
    try:
        opened = open_paths()
        plan = select(build, policy, time.time(), opened)
        if args.retired_diagnostics:
            roots = [
                build, PROJECT.parent / "engines/build/candidates", PROJECT.parent / "docs/qa"
            ]
            plan += retired_diagnostics(roots, time.time(), opened)
            plan += completed_diagnostics(PROJECT.parent, roots, policy, opened)
            orphans = orphan_signatures(roots, time.time(), opened, policy["pinned_sha256"])
            plan += orphans
            # An old closed trial can match both rules; use its explicit hash.
            plan = list({path: (path, meta, digest) for path, meta, digest in plan}.values())
        else:
            orphans = []
        orphan_paths = {path for path, _, _ in orphans}
        total = sum(meta.st_size for _, meta, _ in plan)
        print(f"APK retention: {len(plan)} obsolete files, {total / 1024**3:.2f} GiB logical; "
              f"{'applying' if args.apply else 'dry run'}", file=sys.stderr)
        if not args.apply:
            for path, _, _ in plan:
                print(path)
            return
        tracked = subprocess.check_output(
            ["git", "ls-files", "-z", "--", "unified-android/build",
             "engines/build/candidates", "docs/qa"],
            cwd=PROJECT.parent).decode().split("\0")
        tracked = {str(PROJECT.parent / item) for item in tracked if item}
        receipts = build / "retention-receipts"
        receipts.mkdir(exist_ok=True)
        if receipts.is_symlink():
            raise RuntimeError("Unexpected receipt directory")
        free_before = shutil.disk_usage(build).free
        count = 0
        removed_bytes = 0
        with (receipts / f"{time.time_ns()}-{os.getpid()}.jsonl").open("x") as receipt:
            for path, meta, digest in plan:
                if str(path) in tracked or not unchanged(path, meta):
                    raise RuntimeError(f"Candidate changed or is tracked: {path}")
                if path in orphan_paths and os.path.lexists(path.with_suffix("")):
                    raise RuntimeError(f"Orphan APK reappeared: {path}")
                actual = sha256(path)
                if (digest is not None and actual != digest) or not unchanged(path, meta):
                    raise RuntimeError(f"Immutable APK hash mismatch: {path}")
                if actual in policy["pinned_sha256"]:
                    receipt.write(json.dumps(dict(event="pinned", path=str(path), sha256=actual)) + "\n")
                    continue
                # Persist intent before unlink; distinguish interruptions from completion.
                entry = dict(event="planned_unlink", path=str(path), bytes=meta.st_size,
                             sha256=actual)
                receipt.write(json.dumps(entry) + "\n")
                receipt.flush()
                os.fsync(receipt.fileno())
                path.unlink()
                receipt.write(json.dumps(dict(event="unlinked", path=str(path))) + "\n")
                receipt.flush()
                count += 1
                removed_bytes += meta.st_size
            delta = shutil.disk_usage(build).free - free_before
            receipt.write(json.dumps(dict(event="complete", files=count,
                logical_bytes=removed_bytes, filesystem_free_bytes_change=delta)) + "\n")
        print(f"Removed {count} obsolete APK/signature files; filesystem free-space change "
              f"{delta / 1024**3:.2f} GiB (APFS clones may share blocks).", file=sys.stderr)
    finally:
        if owned:
            lock.rmdir()


if __name__ == "__main__":
    main()
