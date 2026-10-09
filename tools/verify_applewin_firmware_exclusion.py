#!/usr/bin/env python3
"""Prove that the EmuFusion AppleWin core contains no upstream firmware blobs."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from pathlib import Path


def verify(core_path: Path, archive_path: Path, policy_path: Path) -> list[str]:
    errors: list[str] = []
    core = core_path.read_bytes()
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    expected = {
        row["destination"]: (row["size"], row["sha256"])
        for row in policy.get("requiredFiles", [])
    }
    if len(expected) != 6:
        errors.append("firmware policy must contain the exact six-file profile")

    firmware: dict[str, bytes] = {}
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            path = Path(member.name)
            if (not member.isfile() or path.parent.name != "resource" or
                    path.suffix.lower() not in {".rom", ".bin"}):
                continue
            source = archive.extractfile(member)
            if source is not None:
                firmware[path.name] = source.read()
    if len(firmware) < 20:
        errors.append("upstream firmware inventory is unexpectedly incomplete")
    for name, payload in sorted(firmware.items()):
        if payload and payload in core:
            errors.append(f"upstream firmware bytes remain embedded: {name}")
    for name, (size, sha256) in expected.items():
        payload = firmware.get(name)
        if payload is None:
            errors.append(f"policy firmware is absent from pinned source identity: {name}")
        elif len(payload) != size or hashlib.sha256(payload).hexdigest() != sha256:
            errors.append(f"policy firmware identity differs from pinned source: {name}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", required=True, type=Path)
    parser.add_argument("--source-archive", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    args = parser.parse_args()
    errors = verify(args.core, args.source_archive, args.policy)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("AppleWin core contains no pinned upstream firmware byte sequences")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
