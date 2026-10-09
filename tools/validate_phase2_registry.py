#!/usr/bin/env python3
"""JSON Schema and fail-closed policy checks for the Phase 2 registry."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import jsonschema

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

PHASE_TWO_IDS = {
    "applewin", "puae", "beetle-saturn", "ymir", "yabasanshiro",
    "flycast", "play", "armsx2", "dolphin", "ppsspp", "azahar", "scummvm",
    "virtualjaguar",
}
PHASE_TWO_SYSTEMS = {
    "apple2", "amiga", "amigacd32", "saturn", "dreamcast", "naomi",
    "atomiswave", "ps2", "gamecube", "wii", "psp", "3ds", "scummvm",
    "jaguar",
}
ALLOWED_STATUS = {"experimental", "source-blocked", "license-blocked"}
ALLOWED_ROUTE = {"libretro-core", "native-adapter", "benchmark-only"}
ALLOWED_STATE = {
    "libretro-serialize", "native-save-state", "engine-saves-only", "unverified"
}
ALLOWED_RENDERER = {"software", "opengl", "vulkan", "multi"}

PPSSPP_COMMIT = "fa50bb1976065c4f8b1b47af227d367fe9771555"
PPSSPP_TAG_OBJECT = "3a31057b7e44270b4d5cef8c31b6559d51802a3b"
PPSSPP_ARCHIVE_SHA = "9054138072d49c306d65c17059bd85662b4ff46abe1ea6bb53d854dc80592ea6"
PPSSPP_SUBMODULES = {
    "ext/SPIRV-Cross": "4212eef67ed0ca048cb726a6767185504e7695e5",
    "ext/aemu_postoffice": "530fee545c27ffb8524a8f496cbbcfdb687fe8c5",
    "ext/armips": "a8d71f0f279eb0d30ecf6af51473b66ae0cf8e8d",
    "ext/armips/ext/filesystem": "3f1c185ab414e764c694b8171d1c4d8c5c437517",
    "ext/cpu_features": "fd4ffc1632db7b4e763bd28ffa6fc9d761cf3587",
    "ext/glslang": "50e0708ec3a5c16020c4f845c654b80b8edb80bd",
    "ext/libadrenotools": "8fae8ce254dfc1344527e05301e43f37dea2df80",
    "ext/libadrenotools/lib/linkernsbypass": "aa3975893d83ef1bc84c321ec60c65fbf1287887",
    "ext/libchdr": "8bba7745d758627258b315997a860039244cedaf",
    "ext/lua": "7648485f14e8e5ee45e8e39b1eb4d3206dbd405a",
    "ext/miniupnp": "27d13ca9beeb5541f5fbf11959dced03dac39972",
    "ext/naett": "5f695cfa9fcbf30668a4d3ac4b4abf1cd89a1302",
    "ext/OpenXR-SDK": "be392bf6949adeeabad5082aa79d12aacbda781f",
    "ext/rapidjson": "73063f5002612c6bf64fe24f851cd5cc0d83eef9",
    "ext/rcheevos": "ebfe8ca1bf944358e27200d66964fcb4e00e2487",
    "ext/zstd": "f8745da6ff1ad1e7bab384bd1f9d742439278e99",
    "ffmpeg": "1e3b4965632f60b1d85360261d1b9dd45444bc71",
    "libretro/libretro-common": "76a3d54feb0ee0ce9d59b90aa24694f3782063d3",
}
PSPSDK_COMMIT = "314b2083f2e1eaf145fc5de342736336fe1f0148"
PPSSPP_DEPENDENCY_LOCK = "engines/ppsspp-source-lock.json"
PPSSPP_FIXTURE_PATH = "engines/qa/fixtures/ppsspp-minimal"
PLAY_COMMIT = "50aedca2639521bc498ace0b2be1ea012801a86a"
PLAY_ARCHIVE_SHA = "a1dffa7cff03de6e40297a2a16ce6a61da31305b74b9233de9fa97238888758f"
PLAY_DEPENDENCY_LOCK = "engines/play-source-lock.json"
FLYCAST_COMMIT = "d4fc0774107c4c307346b469499b9303a6ca0ffa"
FLYCAST_ARCHIVE_SHA = "fb19f122cb1c8bb9eae302c0e97ef75df168dacc2807da53a3af829cd6a98e71"
FLYCAST_DEPENDENCY_LOCK = "engines/flycast-source-lock.json"
ARMSX2_COMMIT = "788a59d641c777cb7f70726ea573d420508e0931"
ARMSX2_ARCHIVE_SHA = "bc2bb2f106ca499252e3bfe0a40366de5e9749fd84bebbbe80ed52c4b07abf63"
ARMSX2_DEPENDENCY_LOCK = "engines/armsx2-source-lock.json"
ARMSX2_DEPENDENCY_LOCK_SHA = "987ff5aed12bfb029484d968a47d9b6a957e64434846357be3c0471090a5bf2a"
ARMSX2_PATCH = "engines/patches/armsx2-libretro-android-build.patch"
ARMSX2_PATCH_SHA = "f8d1f6c46125ab953c9333eb57400a8f4ff339ea91ebc3221ab8638514bded78"
ARMSX2_CLOCK_PATCH = "engines/patches/armsx2-libretro-frame-clock.patch"
ARMSX2_CLOCK_PATCH_SHA = "c94ef2e4fc1440fbbfceef124433343df8f1bbddd320307dc6719effd838d49f"
ARMSX2_DESCRIPTOR_PATCH = "engines/patches/armsx2-libretro-descriptor-batch.patch"
ARMSX2_DESCRIPTOR_PATCH_SHA = "d7e781701ad7c05494310aebcc1750cc9f816289048b00d85ffbc1db9a95ff61"
ARMSX2_INPUT_ATTACHMENT_PATCH = "engines/patches/armsx2-libretro-input-attachment.patch"
ARMSX2_INPUT_ATTACHMENT_PATCH_SHA = "0312e9a6d7f45caefb1d62784dfac1fbda196c87b67a3f5252307b2a945af9e4"
AZAHAR_COMMIT = "b42d0916ba9799297ae0e27c07d56801da1b5de5"
AZAHAR_ARCHIVE_SHA = "8da46436e9d4cd937af2dba5ed39a33c2102e4f833c9051a9bb6e2711831e065"
AZAHAR_DEPENDENCY_LOCK = "engines/azahar-source-lock.json"
AZAHAR_DEPENDENCY_LOCK_SHA = "b609bf954d6c21776bd0dbe26f1c6599f01bac0657ab37bbca66fcb3a1d47753"
AZAHAR_SOURCE_MEMBER_SHA = "d7150458b86d5493f5a78d850df204fe04b854124d92d0d2040fb104b6f69c7d"
AZAHAR_RELEASE_ARCHIVE_SHA = "4946db52ba9a559834cb3db075544480ac71fa4ae08b090a6708825a012a7b1b"
AZAHAR_RELEASE_MEMBER_SHA = "d723066fa7c812618b5695d94b0fd85594e6c196e9e08ca9ba7134371a8da645"
DOLPHIN_REPOSITORY = "https://github.com/libretro/dolphin"
DOLPHIN_COMMIT = "0ff12a5a2835762e0665afe6a161a648b433f996"
DOLPHIN_ARCHIVE_SHA = "3c6698d6da772065194be118871ce24620f0fdc76894bc568e34d48f93de7494"
DOLPHIN_DEPENDENCY_LOCK = "engines/dolphin-source-lock.json"
DOLPHIN_ARTIFACT_SHA = "12fecae4b12872ff80d6c677cbb2c65504cae439d86e0cad204cd1166642c6a6"
DOLPHIN_PATCH = "engines/patches/dolphin-libretro-submit-rendered-duplicate-xfb.patch"
DOLPHIN_PATCH_SHA = "5dd844b8546eea62706a4dd84304077cddaf83c68987459a532f6055f2f5919b"
DOLPHIN_STACK_PATCH = "engines/patches/dolphin-libretro-own-signal-stack.patch"
DOLPHIN_STACK_PATCH_SHA = "68c853fa395b8c87c41729355c2149dbb83f024b9cb851123b21cfc575ac074b"
DOLPHIN_DESCRIPTOR_PATCH = "engines/patches/dolphin-libretro-descriptor-errors.patch"
DOLPHIN_DESCRIPTOR_PATCH_SHA = "d508e5c96869b925a8a1c01139c76ee2ae13abcd74a0475c4f5281aded85cbcd"
SCUMMVM_COMMIT = "6aa8fa9b6f9e5a7ae670cc355af1b727ff75c995"
SCUMMVM_ARCHIVE_SHA = "8e2080a442b4e78c045795714ac4b699023f631e2045fb133d496cd29419fa67"
SCUMMVM_DEPENDENCY_LOCK = "engines/scummvm-source-lock.json"
SCUMMVM_AUDIT = "engines/scummvm-dependency-audit.json"
SCUMMVM_CONTENT_LOCK = "engines/scummvm-test-content-lock.json"
SCUMMVM_ARTIFACT_SHA = "668aa27dd70990921372d95338dab6384610f721b7bcb4f224b67e63e44d1f4d"
ROOT = Path(__file__).resolve().parents[1]


def _object(value: object, where: str, errors: list[str]) -> dict:
    if not isinstance(value, dict):
        errors.append(f"{where} must be an object")
        return {}
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate(path: Path, *, verify_artifacts: bool = False,
             artifact_root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read Phase 2 registry: {exc}"]

    try:
        schema = json.loads(
            (ROOT / "engines" / "phase2-registry.schema.json").read_text(
                encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
    except (OSError, json.JSONDecodeError, jsonschema.SchemaError) as exc:
        return [f"cannot read Phase 2 schema: {exc}"]
    schema_validator = jsonschema.Draft202012Validator(schema)
    for problem in sorted(schema_validator.iter_errors(data), key=lambda item: list(item.path)):
        location = ".".join(str(part) for part in problem.path) or "$"
        errors.append(f"schema {location}: {problem.message}")

    if data.get("schemaVersion") != 1:
        errors.append("schemaVersion must be 1")
    expected = data.get("expectedSystems")
    if not isinstance(expected, list) or set(expected) != PHASE_TWO_SYSTEMS:
        errors.append("expectedSystems must exactly match plan section 8")

    engines = data.get("engines")
    if not isinstance(engines, list):
        return errors + ["engines must be an array"]

    seen: set[str] = set()
    covered: set[str] = set()
    selected: list[str] = []
    for index, raw in enumerate(engines):
        engine = _object(raw, f"engines[{index}]", errors)
        engine_id = engine.get("id")
        if not isinstance(engine_id, str) or not ID_RE.fullmatch(engine_id):
            errors.append(f"engines[{index}].id is invalid")
            continue
        if engine_id in seen:
            errors.append(f"duplicate engine id: {engine_id}")
        seen.add(engine_id)

        systems = engine.get("systems")
        if not isinstance(systems, list) or not systems:
            errors.append(f"{engine_id}: systems must be a non-empty array")
            systems = []
        elif len(systems) != len(set(systems)):
            errors.append(f"{engine_id}: systems must be unique")
        for system in systems:
            if not isinstance(system, str) or system not in PHASE_TWO_SYSTEMS:
                errors.append(f"{engine_id}: unexpected system {system!r}")
            else:
                covered.add(system)

        if engine.get("route") not in ALLOWED_ROUTE:
            errors.append(f"{engine_id}: invalid route")
        if engine.get("status") not in ALLOWED_STATUS:
            errors.append(f"{engine_id}: Phase 2 must remain fail-closed")
        if engine.get("shipped") is not False:
            errors.append(f"{engine_id}: Phase 2 engine cannot ship")
        if engine.get("selectedFirstRunnable") is True:
            selected.append(engine_id)

        source = _object(engine.get("source"), f"{engine_id}.source", errors)
        source_status = source.get("status")
        commit = source.get("commit")
        archive = source.get("archive")
        archive_sha = source.get("archiveSha256")
        repository = source.get("repository")
        if source_status == "pinned":
            if not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit):
                errors.append(f"{engine_id}: pinned source needs a full commit")
            if not isinstance(archive, str) or not archive.startswith("https://"):
                errors.append(f"{engine_id}: pinned source needs an archive URL")
            elif isinstance(repository, str):
                if not archive.startswith(repository.rstrip("/") + "/archive/"):
                    errors.append(f"{engine_id}: archive must belong to repository")
                if isinstance(commit, str) and commit not in archive:
                    errors.append(f"{engine_id}: archive must pin commit")
        elif source_status == "unavailable":
            if any(value is not None for value in (commit, archive, archive_sha)):
                errors.append(f"{engine_id}: unavailable source cannot claim pins")
        else:
            errors.append(f"{engine_id}: invalid source status")
        if archive_sha is not None and (
                not isinstance(archive_sha, str) or not SHA_RE.fullmatch(archive_sha)):
            errors.append(f"{engine_id}: archiveSha256 must be null or SHA-256")
        submodules = source.get("submodules")
        if not isinstance(submodules, list):
            errors.append(f"{engine_id}: source.submodules must be an array")
            submodules = []
        submodule_map: dict[str, str] = {}
        submodule_tuples: dict[str, tuple[str, str, str]] = {}
        for row in submodules:
            if not isinstance(row, dict):
                errors.append(f"{engine_id}: invalid submodule row")
                continue
            sub_path = row.get("path")
            sub_repository = row.get("repository")
            sub_commit = row.get("commit")
            sub_archive_sha = row.get("archiveSha256")
            if not isinstance(sub_path, str) or not sub_path:
                errors.append(f"{engine_id}: invalid submodule path")
            elif sub_path in submodule_map:
                errors.append(f"{engine_id}: duplicate submodule path {sub_path}")
            if not isinstance(sub_commit, str) or not COMMIT_RE.fullmatch(sub_commit):
                errors.append(f"{engine_id}: invalid submodule commit for {sub_path}")
            elif isinstance(sub_path, str):
                submodule_map[sub_path] = sub_commit
            if (not isinstance(sub_repository, str) or
                    not sub_repository.startswith("https://")):
                errors.append(f"{engine_id}: invalid submodule repository for {sub_path}")
            if (not isinstance(sub_archive_sha, str) or
                    not SHA_RE.fullmatch(sub_archive_sha)):
                errors.append(f"{engine_id}: invalid submodule archive hash for {sub_path}")
            if (isinstance(sub_path, str) and isinstance(sub_repository, str) and
                    isinstance(sub_commit, str) and isinstance(sub_archive_sha, str)):
                submodule_tuples[sub_path] = (
                    sub_repository, sub_commit, sub_archive_sha)

        license_info = _object(engine.get("license"), f"{engine_id}.license", errors)
        dependency_audit_complete = license_info.get("dependencyAuditComplete")
        if dependency_audit_complete is not (engine_id == "scummvm"):
            errors.append(f"{engine_id}: dependency audit completion disagrees with exact audit evidence")
        if license_info.get("distributionGate") not in {
                "compatible-candidate", "audit-required", "blocked"}:
            errors.append(f"{engine_id}: invalid distribution gate")

        android = _object(engine.get("android"), f"{engine_id}.android", errors)
        android_abis = android.get("abis")
        if not isinstance(android_abis, list) or any(
                not isinstance(value, str) for value in android_abis):
            errors.append(f"{engine_id}: android.abis must be a string array")

        firmware = _object(engine.get("firmware"), f"{engine_id}.firmware", errors)
        required_for = firmware.get("requiredForSystems")
        if not isinstance(required_for, list) or not set(required_for).issubset(set(systems)):
            errors.append(f"{engine_id}: firmware systems must be mapped by engine")
        accepted = firmware.get("acceptedHashes")
        if not isinstance(accepted, list) or any(
                not isinstance(value, str) or not SHA_RE.fullmatch(value)
                for value in accepted):
            errors.append(f"{engine_id}: firmware hashes must be SHA-256 values")

        state = _object(engine.get("state"), f"{engine_id}.state", errors)
        if state.get("capability") not in ALLOWED_STATE:
            errors.append(f"{engine_id}: invalid state capability")
        if state.get("qualified") is not False or state.get("migrationQualified") is not False:
            errors.append(f"{engine_id}: state must remain unqualified")

        renderer = _object(engine.get("renderer"), f"{engine_id}.renderer", errors)
        if renderer.get("requested") not in ALLOWED_RENDERER:
            errors.append(f"{engine_id}: invalid renderer")
        if renderer.get("qualified") is not False:
            errors.append(f"{engine_id}: renderer must remain unqualified")

        legal_content = _object(
            engine.get("legalTestContent"), f"{engine_id}.legalTestContent", errors)
        if "sourcePath" not in legal_content:
            errors.append(f"{engine_id}: legalTestContent.sourcePath is required")

        build = _object(engine.get("build"), f"{engine_id}.build", errors)
        if build.get("reproducible") is not False:
            errors.append(f"{engine_id}: build must remain unqualified")
        proof_sha = build.get("proofArtifactSha256")
        proof_path = build.get("proofArtifactPath")
        if proof_sha is not None and (
                not isinstance(proof_sha, str) or not SHA_RE.fullmatch(proof_sha)):
            errors.append(f"{engine_id}: proof artifact must be SHA-256")
        if (proof_sha is None) != (proof_path is None):
            errors.append(f"{engine_id}: proof artifact path and hash must be paired")
        if proof_path is not None:
            if not isinstance(proof_path, str) or not proof_path.strip():
                errors.append(f"{engine_id}: proof artifact path must be non-empty")
            else:
                candidate = (artifact_root / proof_path).resolve()
                try:
                    candidate.relative_to(artifact_root.resolve())
                except ValueError:
                    errors.append(f"{engine_id}: proof artifact path escapes repository")
                else:
                    if verify_artifacts:
                        if not candidate.is_file():
                            errors.append(f"{engine_id}: proof artifact is missing: {proof_path}")
                        elif isinstance(proof_sha, str):
                            actual_sha = _sha256(candidate)
                            if actual_sha != proof_sha:
                                errors.append(
                                    f"{engine_id}: proof artifact SHA-256 mismatch: "
                                    f"expected {proof_sha}, got {actual_sha}")

        gates = _object(engine.get("gates"), f"{engine_id}.gates", errors)
        gate_names = {
            "source", "license", "dependencies", "androidArm64", "firmware",
            "legalContent", "renderer", "state", "performance", "device",
        }
        if set(gates) != gate_names or any(not isinstance(v, bool) for v in gates.values()):
            errors.append(f"{engine_id}: gates must contain the exact boolean gate set")
        fail_closed_gates = ["legalContent", "renderer", "state", "performance", "device"]
        if engine_id != "scummvm":
            fail_closed_gates.extend(["license", "dependencies"])
        for fail_closed in fail_closed_gates:
            if gates.get(fail_closed) is not False:
                errors.append(f"{engine_id}: {fail_closed} gate cannot pass before qualification")
        if engine_id == "scummvm" and (
                gates.get("license") is not True or
                gates.get("dependencies") is not True):
            errors.append("scummvm: exact license and dependency audit gates must pass")
        # Android ARM64 is a compiler/linker qualification gate, not a release
        # approval. It may advance independently when the registry identifies
        # a reproducible exact-pin proof artifact; all runtime, legal, and
        # device gates remain fail-closed above.
        android_proved = (
            android.get("integrationEvidence") == "build-reproduced" and
            isinstance(proof_path, str) and isinstance(proof_sha, str)
        )
        if gates.get("androidArm64") is not android_proved:
            errors.append(
                f"{engine_id}: androidArm64 gate disagrees with exact build proof evidence")
        should_have_source_gate = source_status == "pinned" and archive_sha is not None
        if gates.get("source") is not should_have_source_gate:
            errors.append(f"{engine_id}: source gate disagrees with pin/hash evidence")

        if engine_id == "ppsspp":
            if commit != PPSSPP_COMMIT or archive_sha != PPSSPP_ARCHIVE_SHA:
                errors.append("ppsspp: source is not official v1.20.4 peeled identity")
            if (source.get("tag") != "v1.20.4" or
                    source.get("tagObject") != PPSSPP_TAG_OBJECT):
                errors.append("ppsspp: annotated tag identity is incomplete")
            if submodule_map != PPSSPP_SUBMODULES:
                errors.append("ppsspp: staged compile-input closure is incomplete or inconsistent")
            legal = _object(engine.get("legalTestContent"), "ppsspp.legalTestContent", errors)
            if (legal.get("sourcePath") != PPSSPP_FIXTURE_PATH or
                    legal.get("license") != "CC0-1.0" or
                    legal.get("artifactSha256") is not None):
                errors.append("ppsspp: legal fixture must remain CC0 source-only")
            if source.get("dependencyLock") != PPSSPP_DEPENDENCY_LOCK:
                errors.append("ppsspp: dependency lock path is inconsistent")
            else:
                try:
                    lock = json.loads((ROOT / PPSSPP_DEPENDENCY_LOCK).read_text(
                        encoding="utf-8"))
                    locked = {row["path"]: (
                        row["repository"], row["commit"], row["archiveSha256"])
                              for row in lock.get("dependencies", [])}
                    ffmpeg = lock["ffmpeg"]
                    locked["ffmpeg"] = (
                        ffmpeg["repository"], ffmpeg["commit"],
                        ffmpeg["sparseClosureSha256"])
                except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
                    errors.append(f"ppsspp: cannot read dependency lock: {exc}")
                else:
                    if locked != submodule_tuples:
                        errors.append("ppsspp: registry and dependency lock disagree")
                    core = lock.get("core", {})
                    if (core.get("commit") != commit or
                            core.get("archiveSha256") != archive_sha or
                            core.get("tag") != source.get("tag") or
                            core.get("tagObject") != source.get("tagObject")):
                        errors.append("ppsspp: core identity and dependency lock disagree")
            if build.get("recipe") != "engines/build_core.sh ppsspp":
                errors.append("ppsspp: build recipe must name the pinned source recipe")
            if proof_path is None or proof_sha is None:
                errors.append("ppsspp: compiler/linker proof path and hash are missing")

        if engine_id == "play":
            if commit != PLAY_COMMIT or archive_sha != PLAY_ARCHIVE_SHA:
                errors.append("play: source is not the qualified official commit identity")
            if source.get("dependencyLock") != PLAY_DEPENDENCY_LOCK:
                errors.append("play: dependency lock path is inconsistent")
            else:
                try:
                    lock = json.loads((ROOT / PLAY_DEPENDENCY_LOCK).read_text(
                        encoding="utf-8"))
                    locked = {row["path"]: (
                        row["repository"], row["commit"], row["archiveSha256"])
                              for row in lock.get("dependencies", [])}
                except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
                    errors.append(f"play: cannot read dependency lock: {exc}")
                else:
                    if not locked or locked != submodule_tuples:
                        errors.append("play: registry and dependency lock disagree")
                    core = lock.get("core", {})
                    if (core.get("repository") != repository or
                            core.get("commit") != commit or
                            core.get("archiveSha256") != archive_sha):
                        errors.append("play: core identity and dependency lock disagree")
            if build.get("recipe") != "engines/build_core.sh play":
                errors.append("play: build recipe must name the pinned source recipe")
            if proof_path is None or proof_sha is None:
                errors.append("play: compiler/linker proof path and hash are missing")

        if engine_id == "flycast":
            if commit != FLYCAST_COMMIT or archive_sha != FLYCAST_ARCHIVE_SHA:
                errors.append("flycast: source is not the qualified official commit identity")
            if source.get("dependencyLock") != FLYCAST_DEPENDENCY_LOCK:
                errors.append("flycast: dependency lock path is inconsistent")
            else:
                try:
                    lock = json.loads((ROOT / FLYCAST_DEPENDENCY_LOCK).read_text(
                        encoding="utf-8"))
                    locked = {row["path"]: (
                        row["repository"], row["commit"], row["archiveSha256"])
                              for row in lock.get("dependencies", [])}
                except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
                    errors.append(f"flycast: cannot read dependency lock: {exc}")
                else:
                    if not locked or locked != submodule_tuples:
                        errors.append("flycast: registry and dependency lock disagree")
                    core = lock.get("core", {})
                    if (core.get("repository") != repository or
                            core.get("commit") != commit or
                            core.get("archiveSha256") != archive_sha):
                        errors.append("flycast: core identity and dependency lock disagree")
                    toolchain = lock.get("toolchain", {})
                    if (toolchain.get("androidAbi") != "arm64-v8a" or
                            toolchain.get("androidApi") != 24):
                        errors.append("flycast: locked Android toolchain profile is inconsistent")
            if build.get("recipe") != "engines/build_core.sh flycast":
                errors.append("flycast: build recipe must name the pinned source recipe")
            if proof_path is None or proof_sha is None:
                errors.append("flycast: compiler/linker proof path and hash are missing")

        if engine_id == "armsx2":
            if commit != ARMSX2_COMMIT or archive_sha != ARMSX2_ARCHIVE_SHA:
                errors.append("armsx2: source is not the qualified official commit identity")
            if source.get("dependencyLock") != ARMSX2_DEPENDENCY_LOCK:
                errors.append("armsx2: dependency lock path is inconsistent")
            else:
                try:
                    lock_path = ROOT / ARMSX2_DEPENDENCY_LOCK
                    if _sha256(lock_path) != ARMSX2_DEPENDENCY_LOCK_SHA:
                        errors.append("armsx2: dependency lock SHA-256 mismatch")
                    lock = json.loads(lock_path.read_text(encoding="utf-8"))
                    locked_dependencies = lock.get("dependencies", [])
                    locked_patches = lock.get("patches", [])
                    dependency_identities = {
                        row["path"]: (
                            row["repository"], row["commit"],
                            row["archiveSha256"])
                        for row in locked_dependencies
                    }
                except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
                    errors.append(f"armsx2: cannot read dependency lock: {exc}")
                else:
                    if len(dependency_identities) != 7:
                        errors.append("armsx2: dependency lock must identify seven shaderc inputs")
                    if len(dependency_identities) != len(locked_dependencies):
                        errors.append("armsx2: dependency lock contains duplicate paths")
                    core = lock.get("core", {})
                    if (core.get("repository") != repository or
                            core.get("commit") != commit or
                            core.get("archiveSha256") != archive_sha):
                        errors.append("armsx2: core identity and dependency lock disagree")
                    toolchain = lock.get("toolchain", {})
                    if (toolchain.get("androidAbi") != "arm64-v8a" or
                            toolchain.get("androidApi") != 26 or
                            toolchain.get("ndkVersion") != "27.0.12077973" or
                            toolchain.get("cmakeVersion") != "3.31.6-g38307f9" or
                            toolchain.get("ninjaVersion") != "1.12.1" or
                            not all(SHA_RE.fullmatch(str(toolchain.get(key, "")))
                                    for key in ("ndkSourcePropertiesSha256",
                                                "cmakeExecutableSha256",
                                                "ninjaExecutableSha256"))):
                        errors.append("armsx2: locked Android toolchain profile is inconsistent")
                    if locked_patches != [{
                            "path": ARMSX2_PATCH,
                            "sha256": ARMSX2_PATCH_SHA,
                    }, {
                            "path": ARMSX2_CLOCK_PATCH,
                            "sha256": ARMSX2_CLOCK_PATCH_SHA,
                    }, {
                            "path": ARMSX2_DESCRIPTOR_PATCH,
                            "sha256": ARMSX2_DESCRIPTOR_PATCH_SHA,
                    }, {
                            "path": ARMSX2_INPUT_ATTACHMENT_PATCH,
                            "sha256": ARMSX2_INPUT_ATTACHMENT_PATCH_SHA,
                    }]:
                        errors.append("armsx2: integration patch lock is inconsistent")
                    else:
                        for patch in locked_patches:
                            patch_path = ROOT / patch["path"]
                            try:
                                patch_sha = _sha256(patch_path)
                            except OSError as exc:
                                errors.append(f"armsx2: cannot read integration patch: {exc}")
                            else:
                                if patch_sha != patch["sha256"]:
                                    errors.append("armsx2: integration patch SHA-256 mismatch")
            if build.get("recipe") != "engines/build_core.sh armsx2":
                errors.append("armsx2: build recipe must name the pinned source recipe")
            if proof_path is None or proof_sha is None:
                errors.append("armsx2: compiler/linker proof path and hash are missing")

        if engine_id == "azahar":
            if commit != AZAHAR_COMMIT or archive_sha != AZAHAR_ARCHIVE_SHA:
                errors.append("azahar: source is not official stable 2125.1.3 identity")
            if source.get("dependencyLock") != AZAHAR_DEPENDENCY_LOCK:
                errors.append("azahar: source build lock path is inconsistent")
            else:
                try:
                    lock_path = ROOT / AZAHAR_DEPENDENCY_LOCK
                    if _sha256(lock_path) != AZAHAR_DEPENDENCY_LOCK_SHA:
                        errors.append("azahar: source build lock SHA-256 mismatch")
                    lock = json.loads(lock_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    errors.append(f"azahar: cannot read source build lock: {exc}")
                else:
                    core = lock.get("core", {})
                    release = lock.get("referenceReleaseArtifact", {})
                    if (core.get("repository") != repository or
                            core.get("commit") != commit or
                            core.get("archiveSha256") != archive_sha or
                            core.get("tag") != "2125.1.3"):
                        errors.append("azahar: core identity and source build lock disagree")
                    if (release.get("archiveSha256") != AZAHAR_RELEASE_ARCHIVE_SHA or
                            release.get("member") != "azahar_libretro.so" or
                            release.get("memberSha256") != AZAHAR_RELEASE_MEMBER_SHA):
                        errors.append("azahar: official Android release artifact identity is inconsistent")
                    profile = lock.get("sourceBuild", {})
                    if profile != {
                            "artifactSha256": AZAHAR_SOURCE_MEMBER_SHA,
                            "androidAbi": "arm64-v8a", "androidApi": 23,
                            "ndkVersion": "27.0.12077973", "linkAlignment": 16384,
                            "builtinKeyblob": False}:
                        errors.append("azahar: source build profile is inconsistent")
                    if (len(lock.get("dependencies", [])) != 52 or
                            lock.get("patches") != [{
                                "path": "engines/patches/azahar-android-strerror.patch",
                                "sha256": "49d1f108da6cb40dc8b862bd080708ace1c0e8595c376b1ecccb98f5cf1a4861"}]):
                        errors.append("azahar: source build closure is inconsistent")
                    for patch in lock.get("patches", []):
                        try:
                            if _sha256(ROOT / patch["path"]) != patch["sha256"]:
                                errors.append("azahar: source build patch hash mismatch")
                        except (KeyError, OSError) as exc:
                            errors.append(f"azahar: cannot verify source build patch: {exc}")
            if build.get("recipe") != "engines/build_core.sh azahar":
                errors.append("azahar: recipe must build the pinned Android source")
            if proof_sha != AZAHAR_SOURCE_MEMBER_SHA or proof_path is None:
                errors.append("azahar: source build proof path or hash is missing")

        if engine_id == "dolphin":
            if commit != DOLPHIN_COMMIT or archive_sha != DOLPHIN_ARCHIVE_SHA:
                errors.append("dolphin: source is not the qualified official commit identity")
            if source.get("dependencyLock") != DOLPHIN_DEPENDENCY_LOCK:
                errors.append("dolphin: dependency lock path is inconsistent")
            else:
                try:
                    lock = json.loads((ROOT / DOLPHIN_DEPENDENCY_LOCK).read_text(
                        encoding="utf-8"))
                    locked_dependencies = lock.get("dependencies", [])
                    identities = {
                        row["path"]: (
                            row["repository"], row["commit"],
                            row["archiveSha256"])
                        for row in locked_dependencies
                    }
                except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
                    errors.append(f"dolphin: cannot read dependency lock: {exc}")
                else:
                    if len(identities) != 30 or len(identities) != len(locked_dependencies):
                        errors.append("dolphin: dependency lock must identify 30 unique staged inputs")
                    if any(not path or not repository.startswith("https://") or
                           not COMMIT_RE.fullmatch(dep_commit) or
                           not SHA_RE.fullmatch(dep_sha)
                           for path, (repository, dep_commit, dep_sha)
                           in identities.items()):
                        errors.append("dolphin: dependency lock contains an invalid identity")
                    core = lock.get("core", {})
                    if (core.get("repository") != DOLPHIN_REPOSITORY or
                            core.get("commit") != commit or
                            core.get("archiveSha256") != archive_sha):
                        errors.append("dolphin: core identity and dependency lock disagree")
                    toolchain = lock.get("toolchain", {})
                    if (toolchain.get("androidAbi") != "arm64-v8a" or
                            toolchain.get("androidApi") != 26 or
                            toolchain.get("ndkVersion") != "27.0.12077973" or
                            toolchain.get("cmakeVersion") != "3.22.1-g37088a8" or
                            toolchain.get("ninjaVersion") != "1.10.2" or
                            not all(SHA_RE.fullmatch(str(toolchain.get(key, "")))
                                    for key in ("ndkSourcePropertiesSha256",
                                                "cmakeExecutableSha256",
                                                "ninjaExecutableSha256"))):
                        errors.append("dolphin: locked Android toolchain profile is inconsistent")
                    expected_options = {
                        "LIBRETRO": True,
                        "ENABLE_VULKAN": True,
                        "ENABLE_TESTS": False,
                        "ENABLE_QT": False,
                        "androidMaxPageSize": 16384,
                        "normalizedByRemovingSection": ".note.gnu.build-id",
                        "normalizedArtifactSha256": DOLPHIN_ARTIFACT_SHA,
                        "rawBuildIds": [
                            "e48dde89c6c5a1a07bcfa11ee1252c669ed420db",
                        ],
                    }
                    if lock.get("cmakeOptions") != expected_options:
                        errors.append("dolphin: locked CMake profile is inconsistent")
                    expected_patches = [{
                        "path": DOLPHIN_PATCH,
                        "sha256": DOLPHIN_PATCH_SHA,
                        "purpose": (
                            "Submit the OpenGL framebuffer rendered for duplicate XFB "
                            "presentation instead of incorrectly reporting a null duplicate "
                            "frame to Lucent."
                        ),
                    }, {
                        "path": DOLPHIN_STACK_PATCH,
                        "sha256": DOLPHIN_STACK_PATCH_SHA,
                        "purpose": (
                            "Do not free Android's existing alternate signal stack on aborted "
                            "startup; release only Dolphin's allocation and restore the previous "
                            "stack on normal unload."
                        ),
                    }, {
                        "path": DOLPHIN_DESCRIPTOR_PATCH,
                        "sha256": DOLPHIN_DESCRIPTOR_PATCH_SHA,
                        "purpose": (
                            "Reject non-null output handles on failed Vulkan descriptor allocation, "
                            "retry exhausted pools and bound fresh-pool failure without recursion."
                        ),
                    }]
                    if lock.get("patches") != expected_patches:
                        errors.append("dolphin: compiler proof patch identity is inconsistent")
                    patch_path = ROOT / DOLPHIN_PATCH
                    if not patch_path.is_file() or _sha256(patch_path) != DOLPHIN_PATCH_SHA:
                        errors.append("dolphin: locked frontend patch is missing or changed")
                    stack_patch = ROOT / DOLPHIN_STACK_PATCH
                    if not stack_patch.is_file() or _sha256(stack_patch) != DOLPHIN_STACK_PATCH_SHA:
                        errors.append("dolphin: locked signal-stack patch is missing or changed")
                    descriptor_patch = ROOT / DOLPHIN_DESCRIPTOR_PATCH
                    if not descriptor_patch.is_file() or _sha256(descriptor_patch) != DOLPHIN_DESCRIPTOR_PATCH_SHA:
                        errors.append("dolphin: locked descriptor-allocation patch is missing or changed")
            if build.get("recipe") != "engines/build_core.sh dolphin":
                errors.append("dolphin: build recipe must name the pinned source recipe")
            if proof_path is None or proof_sha != DOLPHIN_ARTIFACT_SHA:
                errors.append("dolphin: compiler/linker proof path and hash are missing")

        if engine_id == "scummvm":
            if commit != SCUMMVM_COMMIT or archive_sha != SCUMMVM_ARCHIVE_SHA:
                errors.append("scummvm: source is not the audited exact commit identity")
            if source.get("dependencyLock") != SCUMMVM_DEPENDENCY_LOCK:
                errors.append("scummvm: dependency lock path is inconsistent")
            try:
                lock = json.loads((ROOT / SCUMMVM_DEPENDENCY_LOCK).read_text(
                    encoding="utf-8"))
                audit = json.loads((ROOT / SCUMMVM_AUDIT).read_text(
                    encoding="utf-8"))
                content = json.loads((ROOT / SCUMMVM_CONTENT_LOCK).read_text(
                    encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"scummvm: cannot read exact lock/audit inputs: {exc}")
            else:
                core = lock.get("core", {})
                locked_dependencies = {
                    row["path"]: (row["repository"], row["commit"],
                                  row["archiveSha256"])
                    for row in lock.get("dependencies", [])
                }
                if (core.get("repository") != repository or
                        core.get("commit") != commit or
                        core.get("archiveSha256") != archive_sha):
                    errors.append("scummvm: core identity and dependency lock disagree")
                if locked_dependencies != submodule_tuples or len(locked_dependencies) != 2:
                    errors.append("scummvm: exact two-archive dependency closure disagrees")
                artifact = lock.get("artifact", {})
                if (artifact.get("sha256") != SCUMMVM_ARTIFACT_SHA or
                        artifact.get("firstCleanBuildSha256") != SCUMMVM_ARTIFACT_SHA or
                        artifact.get("secondCleanBuildSha256") != SCUMMVM_ARTIFACT_SHA or
                        artifact.get("ptLoadAlignment") != "0x4000" or
                        artifact.get("reproducible") is not True):
                    errors.append("scummvm: clean-build artifact proof is inconsistent")
                if (audit.get("coreArtifactSha256") != SCUMMVM_ARTIFACT_SHA or
                        audit.get("externalObjectCount") != 337 or
                        len(audit.get("components", [])) != 15 or
                        len(audit.get("embeddedComponents", [])) != 4):
                    errors.append("scummvm: exact linked-component audit is inconsistent")
                fixtures = content.get("fixtures", [])
                fixture = fixtures[0] if len(fixtures) == 1 else {}
                if (fixture.get("sha256") != legal_content.get("artifactSha256") or
                        fixture.get("distributionPolicy") != "official-download-only" or
                        fixture.get("bundleInApk") is not False):
                    errors.append("scummvm: official download-only fixture lock is inconsistent")
            if build.get("recipe") != "engines/build_scummvm_core.sh":
                errors.append("scummvm: build recipe must name the exact audited recipe")
            if (proof_path != "engines/build/arm64-v8a/scummvm_libretro.so" or
                    proof_sha != SCUMMVM_ARTIFACT_SHA):
                errors.append("scummvm: compiler/linker proof path or hash is inconsistent")

    if seen != PHASE_TWO_IDS:
        errors.append("Phase 2 engine set mismatch: expected " + ", ".join(sorted(PHASE_TWO_IDS)))
    if covered != PHASE_TWO_SYSTEMS:
        errors.append("Phase 2 system coverage mismatch")
    if data.get("selectedFirstRunnable") != "ppsspp" or selected != ["ppsspp"]:
        errors.append("PPSSPP must be the single first runnable candidate")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "path", nargs="?",
        default=Path(__file__).resolve().parents[1] / "engines" / "phase2-registry.json",
        type=Path,
    )
    parser.add_argument(
        "--verify-artifacts", action="store_true",
        help="Hash declared local build artifacts; default validation is clean-checkout-safe.",
    )
    args = parser.parse_args()
    errors = validate(args.path, verify_artifacts=args.verify_artifacts)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Phase 2 registry valid: {args.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
