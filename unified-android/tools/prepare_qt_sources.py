#!/usr/bin/env python3
"""Fetch checksum-pinned frontend sources into the isolated qualification tree.

Existing source directories (including local patches) are never replaced.
Downloads and extraction do not change the APK or production native staging.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(root, name, url, expected):
    download = root / "downloads" / name
    download.parent.mkdir(parents=True, exist_ok=True)
    if not download.exists():
        partial = download.with_name(download.name + ".partial")
        subprocess.run(["curl", "--fail", "--location", "--silent", "--show-error",
                        "--retry", "2", "--connect-timeout", "20", "--max-time", "180",
                        url, "-o", str(partial)], check=True)
        if sha256(partial) != expected:
            raise ValueError("Downloaded source checksum mismatch: " + name)
        partial.rename(download)
    if sha256(download) != expected:
        raise ValueError("Existing source checksum mismatch: " + name)
    return download


def prepare(root, name, url, expected):
    download = fetch(root, name, url, expected)
    source = root / "source"
    source.mkdir(parents=True, exist_ok=True)
    with tarfile.open(download) as archive:
        members = archive.getmembers()
        tops = {Path(item.name).parts[0] for item in members}
        if len(tops) != 1 or any(Path(item.name).is_absolute() or ".." in Path(item.name).parts for item in members):
            raise ValueError("Unexpected source archive paths: " + name)
        target = source / tops.pop()
        if not target.exists():
            archive.extractall(source, filter="data")
            action = "extracted"
        else:
            action = "existing source preserved (tree not revalidated)"
    print(json.dumps({"archive": name, "sha256": expected, "source": str(target), "action": action}), flush=True)
    return target


def main():
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=project / "build/qt-5.15.10-16k")
    args = parser.parse_args()
    lock = json.loads((project / "qt-source-lock.json").read_text())
    for module, expected in lock["qt_modules"].items():
        name = module + lock["qt_archive_suffix"]
        prepare(args.root, name, lock["qt_archive_base_url"] + name, expected)
    for entry, name in ((lock["openssl"], "openssl-1.1.1t.tar.gz"),
                        (lock["pegasus"], "pegasus-6b322063.tar.gz")):
        prepare(args.root, name, entry["url"], entry["sha256"])
    pegasus = args.root / "source" / ("pegasus-frontend-" + lock["pegasus"]["commit"])
    for entry in lock["pegasus"]["submodules"]:
        source = prepare(args.root, entry["archive"], entry["url"], entry["sha256"])
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Invalid submodule path")
        target = pegasus / relative
        if target.is_symlink():
            if target.resolve() != source.resolve():
                raise ValueError("Existing submodule points elsewhere: " + str(target))
        else:
            if target.exists():
                # Archives can contain empty gitlink directories. rmdir refuses
                # any populated directory, preserving existing source edits.
                target.rmdir()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(source.resolve(), target_is_directory=True)
    apng = lock["frontend_apng"]
    prepare(args.root, apng["archive"], apng["url"], apng["sha256"])
    fetch(args.root, apng["patch_archive"], apng["patch_url"], apng["patch_sha256"])


if __name__ == "__main__":
    main()
