#!/usr/bin/env python3
"""Dependency-free structural and policy validation for engines/registry.json."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
ALLOWED_STATUS = {"approved", "license-blocked", "experimental", "external"}
ALLOWED_TIERS = {"1A", "1B"}
ALLOWED_CAPABILITIES = {"deterministic", "serialized", "basic", "unverified"}
ALLOWED_RENDERERS = {"software", "opengl", "vulkan", "multi"}
ENGINE_REQUIRED = {
    "id", "phase", "tier", "displayName", "systems", "status",
    "statusReason", "source", "license", "android", "state", "firmware",
    "renderer", "build", "shipped",
}
SOURCE_REQUIRED = {"repository", "commit", "archive", "archiveSha256", "verifiedAt"}
LICENSE_REQUIRED = {"spdx", "distributionGate", "auditNote"}
ANDROID_REQUIRED = {"abis", "minApi"}
STATE_REQUIRED = {"capability", "compatibilityVersion", "qualified"}
FIRMWARE_REQUIRED = {"required", "acceptedHashes"}
BUILD_REQUIRED = {"recipe", "reproducible", "todo"}
PHASE_ONE_IDS = {
    "mesen", "mesen-s", "sameboy", "mgba", "gearsystem", "gearcoleco",
    "freeintv", "swanstation", "melonds-ds", "fuse", "mame",
    "stella-2023", "atari800", "prosystem", "caprice32", "hatari",
    "beetle-pce-fast", "blastem", "picodrive", "beetle-neopop", "beetle-cygne",
    "beetle-vb", "mupen64plus-next", "vice-x64sc", "bluemsx", "o2em",
    "dosbox-pure",
}
PHASE_ONE_B_IDS = {
    "stella-2023", "atari800", "caprice32", "hatari",
    "picodrive", "beetle-vb", "vice-x64sc",
    "bluemsx", "o2em",
}


def validate(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read registry: {exc}"]

    if data.get("schemaVersion") != 1:
        errors.append("schemaVersion must be 1")
    engines = data.get("engines")
    if not isinstance(engines, list):
        return errors + ["engines must be an array"]

    seen_ids: set[str] = set()
    seen_systems: dict[str, str] = {}
    for index, engine in enumerate(engines):
        where = f"engines[{index}]"
        if not isinstance(engine, dict):
            errors.append(f"{where} must be an object")
            continue
        absent = ENGINE_REQUIRED - set(engine)
        if absent:
            errors.append(f"{where} missing fields: {', '.join(sorted(absent))}")
        engine_id = engine.get("id")
        if not isinstance(engine_id, str) or not ID_RE.fullmatch(engine_id):
            errors.append(f"{where}.id is invalid")
            continue
        if engine_id in seen_ids:
            errors.append(f"duplicate engine id: {engine_id}")
        seen_ids.add(engine_id)
        if engine.get("phase") != 1 or engine.get("tier") not in ALLOWED_TIERS:
            errors.append(f"{engine_id}: invalid phase/tier")
        if engine.get("status") not in ALLOWED_STATUS:
            errors.append(f"{engine_id}: invalid status")
        systems = engine.get("systems")
        if not isinstance(systems, list) or not systems:
            errors.append(f"{engine_id}: systems must be non-empty")
        else:
            for system in systems:
                if not isinstance(system, str) or not ID_RE.fullmatch(system):
                    errors.append(f"{engine_id}: invalid system id {system!r}")
                elif system in seen_systems:
                    errors.append(
                        f"system {system} assigned to both {seen_systems[system]} and {engine_id}"
                    )
                else:
                    seen_systems[system] = engine_id

        source = engine.get("source", {})
        if not isinstance(source, dict):
            errors.append(f"{engine_id}: source must be an object")
            source = {}
        missing_source = SOURCE_REQUIRED - set(source)
        if missing_source:
            errors.append(f"{engine_id}: source missing {', '.join(sorted(missing_source))}")
        if not COMMIT_RE.fullmatch(str(source.get("commit", ""))):
            errors.append(f"{engine_id}: source.commit must be a full Git commit")
        repository = source.get("repository")
        archive = source.get("archive")
        commit = source.get("commit")
        if isinstance(repository, str) and isinstance(archive, str):
            expected_prefix = repository.rstrip("/") + "/archive/"
            if not archive.startswith(expected_prefix):
                errors.append(f"{engine_id}: source.archive must belong to source.repository")
            if isinstance(commit, str) and commit not in archive:
                errors.append(f"{engine_id}: source.archive must pin source.commit")
        archive_sha = source.get("archiveSha256")
        if archive_sha is not None and not SHA_RE.fullmatch(str(archive_sha)):
            errors.append(f"{engine_id}: archiveSha256 must be null or SHA-256")

        build = engine.get("build", {})
        if not isinstance(build, dict):
            errors.append(f"{engine_id}: build must be an object")
            build = {}
        missing_build = BUILD_REQUIRED - set(build)
        if missing_build:
            errors.append(f"{engine_id}: build missing {', '.join(sorted(missing_build))}")
        if archive_sha is None and not build.get("todo"):
            errors.append(f"{engine_id}: unverified archive requires an explicit todo")
        if build.get("reproducible") and (not build.get("recipe") or archive_sha is None):
            errors.append(f"{engine_id}: reproducible build requires recipe and archive hash")

        state = engine.get("state", {})
        if not isinstance(state, dict):
            errors.append(f"{engine_id}: state must be an object")
            state = {}
        missing_state = STATE_REQUIRED - set(state)
        if missing_state:
            errors.append(f"{engine_id}: state missing {', '.join(sorted(missing_state))}")
        if state.get("capability") not in ALLOWED_CAPABILITIES:
            errors.append(f"{engine_id}: invalid state capability")
        if engine.get("renderer") not in ALLOWED_RENDERERS:
            errors.append(f"{engine_id}: invalid renderer")
        for field, required in (("license", LICENSE_REQUIRED), ("android", ANDROID_REQUIRED),
                                ("firmware", FIRMWARE_REQUIRED)):
            section = engine.get(field, {})
            if not isinstance(section, dict):
                errors.append(f"{engine_id}: {field} must be an object")
            else:
                missing_section = required - set(section)
                if missing_section:
                    errors.append(
                        f"{engine_id}: {field} missing {', '.join(sorted(missing_section))}"
                    )
        firmware = engine.get("firmware", {})
        if isinstance(firmware, dict):
            hashes = firmware.get("acceptedHashes")
            if not isinstance(hashes, list) or any(
                    not isinstance(value, str) or not SHA_RE.fullmatch(value)
                    for value in hashes):
                errors.append(f"{engine_id}: firmware.acceptedHashes must contain SHA-256 values")
            elif len(hashes) != len(set(hashes)):
                errors.append(f"{engine_id}: firmware.acceptedHashes must be unique")
            conditional = firmware.get("requiredForSystems", [])
            if not isinstance(conditional, list) or any(
                    not isinstance(value, str) for value in conditional):
                errors.append(f"{engine_id}: firmware.requiredForSystems must be an array of system ids")
            else:
                duplicates = len(conditional) != len(set(conditional))
                if duplicates:
                    errors.append(f"{engine_id}: firmware.requiredForSystems must be unique")
                unknown = sorted(set(conditional) - set(systems or []))
                if unknown:
                    errors.append(
                        f"{engine_id}: firmware.requiredForSystems contains unmapped systems: " +
                        ", ".join(unknown)
                    )
                if firmware.get("required") and conditional:
                    errors.append(
                        f"{engine_id}: universally required firmware cannot also be conditional"
                    )
            notes = firmware.get("notes")
            if notes is not None and (not isinstance(notes, str) or not notes.strip()):
                errors.append(f"{engine_id}: firmware.notes must be non-empty when present")
        else:
            firmware = {}
        if state.get("qualified") and engine.get("status") != "approved":
            errors.append(f"{engine_id}: qualified state requires approved status")
        if engine.get("shipped") and engine.get("status") != "approved":
            errors.append(f"{engine_id}: only approved engines may ship")
        if engine.get("status") != "approved" and engine.get("shipped") is not False:
            errors.append(f"{engine_id}: unapproved engines must explicitly set shipped=false")
        if engine.get("status") == "approved":
            license_info = engine.get("license", {})
            if license_info.get("distributionGate") != "compatible-candidate":
                errors.append(f"{engine_id}: approved engine has unresolved license gate")
            if not state.get("qualified") or not build.get("reproducible"):
                errors.append(f"{engine_id}: approved engine lacks state/build qualification")
            if archive_sha is None:
                errors.append(f"{engine_id}: approved engine requires an archive hash")
            if firmware.get("required") or firmware.get("requiredForSystems"):
                if not firmware.get("acceptedHashes"):
                    errors.append(f"{engine_id}: approved firmware dependency requires hashes")

        if engine_id in PHASE_ONE_B_IDS:
            if engine.get("tier") != "1B":
                errors.append(f"{engine_id}: Phase 1B candidate must remain tier 1B")
            if engine.get("status") != "license-blocked":
                errors.append(f"{engine_id}: Phase 1B candidate must remain license-blocked")
            if engine.get("shipped") is not False:
                errors.append(f"{engine_id}: Phase 1B candidate cannot ship")
            if state.get("qualified") is not False:
                errors.append(f"{engine_id}: Phase 1B candidate cannot be state-qualified")
            if build.get("reproducible") is not False:
                errors.append(f"{engine_id}: Phase 1B candidate cannot be release-reproducible")

    missing = sorted(PHASE_ONE_IDS - seen_ids)
    extra = sorted(seen_ids - PHASE_ONE_IDS)
    if missing:
        errors.append("missing Phase 1 candidates: " + ", ".join(missing))
    if extra:
        errors.append("unexpected Phase 1 candidates: " + ", ".join(extra))
    return errors


def validate_qualification_opt_in(path: Path, registry_path: Path) -> list[str]:
    """Validate the checked-in development opt-in without enabling any core."""
    errors: list[str] = []
    try:
        opt_in = json.loads(path.read_text(encoding="utf-8"))
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read qualification manifest: {exc}"]
    if opt_in.get("qualificationOnly") is not True:
        errors.append("qualification manifest must set qualificationOnly=true")
    if opt_in.get("autoSelect") is not False:
        errors.append("qualification manifest must set autoSelect=false")
    by_id = {row.get("id"): row for row in registry.get("engines", [])
             if isinstance(row, dict)}
    rows = opt_in.get("engines")
    if not isinstance(rows, list):
        return errors + ["qualification manifest engines must be an array"]
    seen: set[str] = set()
    for index, row in enumerate(rows):
        where = f"qualification.engines[{index}]"
        if not isinstance(row, dict):
            errors.append(f"{where} must be an object")
            continue
        engine_id = row.get("id")
        if engine_id in seen:
            errors.append(f"duplicate qualification engine id: {engine_id}")
        seen.add(engine_id)
        engine = by_id.get(engine_id)
        if engine is None:
            errors.append(f"{where}: unknown engine {engine_id!r}")
            continue
        if engine.get("status") != "experimental" or engine.get("shipped") is not False:
            errors.append(f"{engine_id}: qualification opt-in requires unshipped experimental status")
        if row.get("commit") != engine.get("source", {}).get("commit"):
            errors.append(f"{engine_id}: qualification commit does not match registry")
        expected_library = "libemufusion_core_" + str(engine_id).replace("-", "_") + ".so"
        if row.get("libraryName") != expected_library:
            errors.append(f"{engine_id}: qualification libraryName must be {expected_library}")
    return errors


def main() -> int:
    default = Path(__file__).resolve().parents[1] / "engines" / "registry.json"
    parser = argparse.ArgumentParser()
    parser.add_argument("registry", nargs="?", type=Path, default=default)
    args = parser.parse_args()
    errors = validate(args.registry)
    default_registry = Path(__file__).resolve().parents[1] / "engines" / "registry.json"
    if args.registry.resolve() == default_registry.resolve():
        errors.extend(validate_qualification_opt_in(
            default_registry.with_name("qualification-opt-in.json"), default_registry))
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    data = json.loads(args.registry.read_text(encoding="utf-8"))
    print(f"validated {len(data['engines'])} Phase 1 engine candidates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
