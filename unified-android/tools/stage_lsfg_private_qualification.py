#!/usr/bin/env python3
"""Stage the owner's LSFG shaders for a private EmuFusion qualification run.

The Windows DLL is hash-checked and never copied or executed.  This tool only
copies the already-extracted SPIR-V resource range used by the pinned public
wrapper into a new private staging directory and emits the manifest consumed
by LsfgQualificationRuntime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile


WRAPPER_COMMIT = "3e89e5439a98f55d5acb003d20039426ab24e69c"
EXPECTED_DLL_SHA256 = (
    "fe0faeb147accab84539ac2bdcaa4eb3dec850752a336e710b85fc87477004e4"
)
SOURCE_FIRST = 255
SOURCE_LAST = 302
RESOURCE_OFFSET = 98
SPIRV_MAGIC = b"\x03\x02\x23\x07"


class StageError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_shader(path: Path) -> int:
    if not path.is_file():
        raise StageError(f"missing extracted shader: {path.name}")
    size = path.stat().st_size
    if size < 20 or size % 4:
        raise StageError(f"invalid SPIR-V size for {path.name}: {size}")
    with path.open("rb") as stream:
        if stream.read(4) != SPIRV_MAGIC:
            raise StageError(f"invalid SPIR-V magic for {path.name}")
    return size


def stage_private_payload(
    dll: Path,
    extracted_shader_directory: Path,
    output: Path,
    *,
    expected_dll_sha256: str = EXPECTED_DLL_SHA256,
) -> Path:
    dll = dll.resolve()
    source = extracted_shader_directory.resolve()
    output = output.resolve()
    if not dll.is_file():
        raise StageError(f"owner-supplied DLL is absent: {dll}")
    actual_dll_sha256 = sha256(dll)
    if actual_dll_sha256 != expected_dll_sha256:
        raise StageError(
            "owner-supplied DLL SHA-256 mismatch: "
            f"expected {expected_dll_sha256}, got {actual_dll_sha256}"
        )
    if not source.is_dir():
        raise StageError(f"extracted shader directory is absent: {source}")
    if output.exists():
        raise StageError(f"refusing to replace existing output: {output}")

    expected_source_names = {
        f"{resource}.spv" for resource in range(SOURCE_FIRST, SOURCE_LAST + 1)
    }
    actual_source_names = {path.name for path in source.glob("*.spv")}
    if actual_source_names != expected_source_names:
        missing = sorted(expected_source_names - actual_source_names)
        extra = sorted(actual_source_names - expected_source_names)
        raise StageError(
            f"extracted shader set mismatch: missing={missing}, extra={extra}"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        shader_output = temporary / "shaders"
        shader_output.mkdir()
        entries = []
        for resource in range(SOURCE_FIRST, SOURCE_LAST + 1):
            source_path = source / f"{resource}.spv"
            size = _validate_shader(source_path)
            target_name = f"{resource + RESOURCE_OFFSET}.spv"
            target_path = shader_output / target_name
            shutil.copyfile(source_path, target_path)
            if target_path.stat().st_size != size:
                raise StageError(f"short shader copy: {target_name}")
            entries.append(
                {
                    "name": target_name,
                    "bytes": size,
                    "sha256": sha256(target_path),
                }
            )

        manifest = {
            "schemaVersion": 1,
            "wrapperCommit": WRAPPER_COMMIT,
            "sourceDllSha256": actual_dll_sha256,
            "dllPackaged": False,
            "dllExecuted": False,
            "generationCount": 1,
            "fixedPhase": 0.5,
            "shaders": entries,
        }
        manifest_path = temporary / "qualification-manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.rename(output)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return output / "qualification-manifest.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dll", required=True, type=Path)
    parser.add_argument("--extracted-shaders", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    manifest = stage_private_payload(args.dll, args.extracted_shaders, args.output)
    print(f"STAGED manifest={manifest} sha256={sha256(manifest)} shaders=48 dllCopied=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
