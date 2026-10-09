#!/usr/bin/env python3
"""Generate the signed APK manifest for bundled EmuFusion core artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def generate(registry_path: Path, library_dir: Path,
             artifact_kind: str = "core") -> dict:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    by_filename: dict[str, dict] = {}
    for row in registry.get("engines", []):
        engine_id = row.get("id", "")
        normalized = engine_id.replace("-", "_")
        if artifact_kind == "native-adapter":
            # Phase 3 adapters are in-process engines, not libretro cores. Only
            # a registry row that actually declares the native-adapter route may
            # contribute an artifact, and it may only claim the one file name
            # NativeAdapterCatalog reconstructs from the engine id.
            if row.get("route") != "native-adapter":
                continue
            by_filename[f"liblucent_native_adapter_{normalized}.so"] = row
            continue
        for filename in (
            f"liblucent_core_{normalized}.so",
            f"{engine_id}_libretro.so",
            f"{normalized}_libretro.so",
            f"lib{engine_id}_libretro.so",
            f"lib{normalized}_libretro.so",
        ):
            by_filename[filename] = row

    artifacts = []
    for library in sorted(library_dir.glob("*.so")):
        row = by_filename.get(library.name)
        if row is None:
            continue
        source = row.get("source") or {}
        artifact = {
            "engineId": row["id"],
            "fileName": library.name,
            "sha256": sha256(library),
            "sourceCommit": source.get("commit", ""),
        }
        if row["id"] == "armsx2":
            variant = library_dir / "liblucent_core_armsx2_16k.so"
            if not variant.is_file():
                raise ValueError("PS2 APK requires its bundled 16 KiB host-page variant")
            artifact["hostPageSize"] = 4096
            artifact["pageSizeVariants"] = [{
                "hostPageSize": 16384,
                "fileName": variant.name,
                "sha256": sha256(variant),
                "sourceCommit": source.get("commit", ""),
            }]
        artifacts.append(artifact)
    return {"schemaVersion": 1, "artifacts": artifacts}


def write_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=path.name + ".pending-", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--library-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--artifact-kind", choices=("core", "native-adapter"), default="core",
        help="'core' hashes bundled libretro cores (Phase 1/2); "
             "'native-adapter' hashes bundled Phase 3 in-process adapters",
    )
    parser.add_argument(
        "--expected-count", type=int, default=None, metavar="N",
        help="fail unless exactly N registered core artifacts are found; a "
             "build that stages cores must never emit an empty (or partial) "
             "manifest silently",
    )
    args = parser.parse_args()
    manifest = generate(args.registry, args.library_dir, args.artifact_kind)
    actual = len(manifest["artifacts"])
    if args.expected_count is not None and actual != args.expected_count:
        found = ", ".join(
            row["fileName"] for row in manifest["artifacts"]) or "none"
        print(
            f"ERROR: expected exactly {args.expected_count} registered core "
            f"artifact(s) in {args.library_dir}, found {actual} ({found})",
            file=sys.stderr,
        )
        return 1
    write_atomic(args.output, manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
