#!/usr/bin/env python3
"""Verify any fail-closed Phase 3 native-adapter qualification payload."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path


REGISTRY = "assets/phase3-engine-registry.json"
OPT_IN = "assets/phase3-qualification-opt-in.json"
ARTIFACTS = "assets/phase3-engine-artifacts.json"
EXPECTED = {"eden", "cemu", "aps3e"}
EXPECTED_LIBRARY_ROUTES = {
    "eden": ["switch"],
    "cemu": ["wiiu"],
    "aps3e": ["ps3"],
}
FORBIDDEN_RUNTIME_INPUT_NAMES = {
    "prod.keys", "title.keys", "console.keys", "keys.txt", "ps3updat.pup",
}
FORBIDDEN_RUNTIME_INPUT_SUFFIXES = (
    ".keys", ".nca", ".xci", ".nsp", ".pup",
)


def _read_json(archive: zipfile.ZipFile, name: str) -> dict:
    return json.loads(archive.read(name).decode("utf-8"))


def _by_id(rows: list, key: str = "id") -> dict:
    result: dict = {}
    for row in rows:
        value = row.get(key) if isinstance(row, dict) else None
        if not isinstance(value, str) or value in result:
            raise ValueError(f"duplicate or invalid {key}")
        result[value] = row
    return result


def _asset_names(engine_id: str) -> tuple[str, str, str]:
    stem = engine_id.replace("-", "_")
    return (
        f"lib/arm64-v8a/liblucent_native_adapter_{stem}.so",
        f"assets/phase3-{engine_id}-source-lock.json",
        f"assets/phase3-{engine_id}-lucent-adapter.cpp",
    )


def verify(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        return [f"cannot open APK: {exc}"]
    with archive:
        names = set(archive.namelist())
        for name in (REGISTRY, OPT_IN, ARTIFACTS):
            if name not in names:
                errors.append(f"missing Phase 3 qualification payload: {name}")
        if errors:
            return errors
        try:
            registry = _read_json(archive, REGISTRY)
            opt_in = _read_json(archive, OPT_IN)
            artifacts = _read_json(archive, ARTIFACTS)
            enabled = _by_id(opt_in.get("engines", []))
            identities = _by_id(artifacts.get("artifacts", []), "engineId")
            rows = _by_id(registry.get("engines", []))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            return [f"invalid Phase 3 qualification JSON: {exc}"]

        if (set(enabled) != EXPECTED or not identities or
                not set(identities) <= EXPECTED):
            errors.append("Phase 3 opt-in/artifact set is not the exact qualified set")
        if any(document.get("schemaVersion") != 1
               for document in (registry, opt_in, artifacts)):
            errors.append("Phase 3 asset schema versions are not the pinned version 1")
        if opt_in.get("qualificationOnly") is not True or \
                opt_in.get("autoSelect") is not False:
            errors.append("Phase 3 qualification payload is not fail-closed")
        actual_routes = {
            engine_id: row.get("libraryRouteSystems", [])
            for engine_id, row in enabled.items()
        }
        if actual_routes != EXPECTED_LIBRARY_ROUTES:
            errors.append("Phase 3 normal-library routes are not the exact qualified subset")

        for engine_id, identity in sorted(identities.items()):
            row = rows.get(engine_id)
            enable = enabled.get(engine_id)
            library, lock_asset, source_asset = _asset_names(engine_id)
            for required in (library, lock_asset, source_asset):
                if required not in names:
                    errors.append(f"missing Phase 3 qualification payload: {required}")
            if row is None or enable is None or any(
                    required not in names for required in
                    (library, lock_asset, source_asset)):
                continue
            try:
                source_lock = _read_json(archive, lock_asset)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                errors.append(f"invalid {engine_id} source lock: {exc}")
                continue

            commit = (row.get("source") or {}).get("commit")
            actual = hashlib.sha256(archive.read(library)).hexdigest()
            file_name = Path(library).name
            if enable.get("runtime") != "native-adapter" or \
                    row.get("route") != "native-adapter":
                errors.append(f"{engine_id} is not an in-process native adapter")
            if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
                errors.append(f"{engine_id} registry source commit is not pinned")
            if enable.get("commit") != commit or \
                    identity.get("sourceCommit") != commit:
                errors.append(f"{engine_id} source commit differs across qualification assets")
            if enable.get("libraryName") != file_name or \
                    identity.get("fileName") != file_name:
                errors.append(f"{engine_id} packaged adapter name differs across assets")
            if identity.get("sha256") != actual:
                errors.append(f"{engine_id} packaged adapter hash does not match the manifest")
            if row.get("shipped") is not False or row.get("status") != "research":
                errors.append(f"{engine_id} registry unexpectedly claims a shipped engine")
            if any(value is not False for value in (row.get("gates") or {}).values()):
                errors.append(f"{engine_id} registry unexpectedly claims a qualification gate")

            lock_core = source_lock.get("core") or {}
            lock_artifact = source_lock.get("artifact") or {}
            if source_lock.get("route") != "native-adapter" or \
                    source_lock.get("engineId") != engine_id:
                errors.append(f"{engine_id} source lock does not describe its native adapter")
            if lock_core.get("commit") != commit:
                errors.append(f"{engine_id} source lock commit differs from the registry")
            if source_lock.get("reproducible") is not False:
                errors.append(
                    f"{engine_id.capitalize()} source lock claims reproducibility that was never proven")
            if lock_artifact.get("sha256") != actual or \
                    lock_artifact.get("fileName") != file_name:
                errors.append(f"{engine_id} source lock artifact differs from the packaged adapter")
            runtime_inputs = source_lock.get("runtimeInputs") or {}
            if runtime_inputs.get("keysAndFirmwareBundled") is not False or \
                    runtime_inputs.get("gameContentBundled", False) is not False:
                errors.append(f"{engine_id} source lock does not disclaim bundled runtime inputs")

            if engine_id == "aps3e":
                license_asset = "assets/LICENSE-GPL-2.0-APS3E.txt"
                if license_asset not in names:
                    errors.append(
                        f"missing Phase 3 qualification payload: {license_asset}")
                else:
                    expected_license = (source_lock.get("license") or {}).get(
                        "packagedLicenseSha256")
                    actual_license = hashlib.sha256(
                        archive.read(license_asset)).hexdigest()
                    if expected_license != actual_license:
                        errors.append("Packaged aPS3e GPL-2.0 license differs from the source lock")

            expected_source_path = f"engines/patches/{engine_id}-lucent-adapter.cpp"
            adapter_patches = [entry for entry in source_lock.get("patches", [])
                               if entry.get("path") == expected_source_path]
            if len(adapter_patches) != 1 or \
                    adapter_patches[0].get("sha256") != hashlib.sha256(
                        archive.read(source_asset)).hexdigest():
                errors.append(f"Packaged {engine_id} adapter source differs from the source lock")
            for entry in source_lock.get("patches", []):
                if entry.get("role") == "local-source-patch" and not entry.get("note"):
                    errors.append(f"{engine_id} local source patch has no reason")

        for name in names:
            base = Path(name).name.lower()
            if base in FORBIDDEN_RUNTIME_INPUT_NAMES or \
                    base.endswith(FORBIDDEN_RUNTIME_INPUT_SUFFIXES):
                errors.append(f"Console keys/firmware are unexpectedly bundled: {name}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("apk", type=Path)
    args = parser.parse_args()
    errors = verify(args.apk)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("Phase 3 native-adapter qualification payload verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
