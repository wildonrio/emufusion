#!/usr/bin/env python3
"""Stage the Nintendo Switch (Native) / Switch 2 host library from its pinned source.

engines/nxnative-source-lock.json names the commit of the nxnative-android repository, the NDK,
and the SHA-256 the build must give. The library is built with `build_host.py --release`, which
gives the same bytes wherever it is built. It lands in engines/build/nxnative/, outside the
arm64-v8a staging directory that release recipes compare before and after a build.

  stage_nxnative_host.py            staged and matching: nothing to do. Otherwise build and check.
  stage_nxnative_host.py --check    fail unless the staged library matches the lock. Builds nothing.
  stage_nxnative_host.py --relock   build the locked commit and write the SHA-256 it gives.

The source comes from NXNATIVE_SRC, else ~/Code/nxnative-android, else a clone of the lock's
repository. It is read with git archive, so a dirty checkout cannot change the result.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "engines/nxnative-source-lock.json"
STAGED = ROOT / "engines/build/nxnative/libdmhost.so"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def source_repo(lock, work):
    """A git directory holding the locked commit."""
    candidates = [os.environ.get("NXNATIVE_SRC"), str(Path.home() / "Code/nxnative-android")]
    for candidate in candidates:
        if not candidate or not Path(candidate).is_dir():
            continue
        found = subprocess.run(["git", "-C", candidate, "cat-file", "-e", lock["commit"] + "^{commit}"],
                               capture_output=True)
        if found.returncode == 0:
            return Path(candidate)
    clone = work / "clone"
    subprocess.run(["git", "clone", "--quiet", lock["repository"], str(clone)], check=True)
    return clone


def build(lock):
    """The locked commit's library, built in a scratch folder; returns (bytes path, scratch)."""
    ndk = Path(os.environ.get("ANDROID_SDK_ROOT", Path.home() / "Library/Android/sdk")) / "ndk" / lock["ndk"]
    if not (ndk / "toolchains").is_dir():
        sys.exit(f"stage_nxnative_host: the pinned NDK {lock['ndk']} is not installed at {ndk}")
    scratch = Path(tempfile.mkdtemp(prefix="nxnative-host-", dir=STAGED.parent))
    repo = source_repo(lock, scratch)
    tree = scratch / "src"
    tree.mkdir()
    archive = scratch / "src.tar"
    subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", "-o", str(archive), lock["commit"]], check=True)
    with tarfile.open(archive) as stream:
        stream.extractall(tree, filter="data") if sys.version_info >= (3, 12) else stream.extractall(tree)
    archive.unlink()
    env = dict(os.environ, ANDROID_NDK=str(ndk))
    out = scratch / "out"
    subprocess.run([sys.executable, str(tree / "dm/android/build_host.py"), str(out), "--so", "--release"],
                   cwd=tree, env=env, check=True)
    return out / "libdmhost.so", scratch


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--relock", action="store_true")
    args = parser.parse_args()
    lock = json.loads(LOCK.read_text())
    want = lock["libdmhostSha256"]
    if not args.relock and STAGED.is_file() and sha256(STAGED) == want:
        print(f"stage_nxnative_host: staged library matches the lock ({want[:12]})")
        return 0
    if args.check:
        sys.exit(f"stage_nxnative_host: {STAGED} is absent or does not match the lock's {want}")
    STAGED.parent.mkdir(parents=True, exist_ok=True)
    built, scratch = build(lock)
    try:
        got = sha256(built)
        if args.relock:
            lock["libdmhostSha256"] = got
            LOCK.write_text(json.dumps(lock, indent=2) + "\n")
            print(f"stage_nxnative_host: lock now names {got}")
        elif got != want:
            sys.exit(f"stage_nxnative_host: commit {lock['commit']} built {got}, the lock says {want}. "
                     "Same commit and NDK must give the same bytes: find out why before relocking.")
        temporary = STAGED.with_suffix(".tmp")
        shutil.copyfile(built, temporary)
        temporary.replace(STAGED)
        receipt = {"commit": lock["commit"], "ndk": lock["ndk"], "sha256": got}
        STAGED.with_suffix(".so.build.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(f"stage_nxnative_host: staged {STAGED} ({got[:12]})")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
