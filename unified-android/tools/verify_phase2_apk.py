#!/usr/bin/env python3
"""Verify the fail-closed multi-core Phase 2 qualification payload."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path


REGISTRY = "assets/phase2-engine-registry.json"
OPT_IN = "assets/phase2-qualification-opt-in.json"
ARTIFACTS = "assets/phase2-engine-artifacts.json"
SBOM = "assets/phase2-sbom.spdx.json"
PLAY_LOCK = "assets/phase2-play-source-lock.json"
FLYCAST_LOCK = "assets/phase2-flycast-source-lock.json"
ARMSX2_LOCK = "assets/phase2-armsx2-source-lock.json"
ARMSX2_PATCHES = [
    {"path": "engines/patches/armsx2-libretro-android-build.patch",
     "sha256": "f8d1f6c46125ab953c9333eb57400a8f4ff339ea91ebc3221ab8638514bded78"},
    {"path": "engines/patches/armsx2-libretro-frame-clock.patch",
     "sha256": "c94ef2e4fc1440fbbfceef124433343df8f1bbddd320307dc6719effd838d49f"},
    {"path": "engines/patches/armsx2-libretro-descriptor-batch.patch",
     "sha256": "d7e781701ad7c05494310aebcc1750cc9f816289048b00d85ffbc1db9a95ff61"},
    {"path": "engines/patches/armsx2-libretro-input-attachment.patch",
     "sha256": "0312e9a6d7f45caefb1d62784dfac1fbda196c87b67a3f5252307b2a945af9e4"},
]
AZAHAR_LOCK = "assets/phase2-azahar-source-lock.json"
DOLPHIN_LOCK = "assets/phase2-dolphin-source-lock.json"
APPLEWIN_LOCK = "assets/phase2-applewin-source-lock.json"
APPLEWIN_FIRMWARE_POLICY = "assets/phase2-applewin-firmware-policy.json"
PUAE_LOCK = "assets/phase2-puae-source-lock.json"
PUAE_FIRMWARE_POLICY = "assets/phase2-puae-firmware-policy.json"
PUAE_AUDIT = "assets/phase2-puae-dependency-audit.json"
PUAE_CONTENT = "assets/phase2-puae-test-content-lock.json"
PUAE_NOTICES = "assets/PUAE-CORE-NOTICES.txt"
SCUMMVM_LOCK = "assets/phase2-scummvm-source-lock.json"
SCUMMVM_AUDIT = "assets/phase2-scummvm-dependency-audit.json"
SCUMMVM_CONTENT = "assets/phase2-scummvm-test-content-lock.json"
SCUMMVM_COMPLIANCE_MANIFEST = "assets/scummvm-compliance/scummvm-linked-objects.json"
SCUMMVM_NOTICES = "assets/scummvm-compliance/SCUMMVM-CORE-NOTICES.txt"
AZAHAR_RELEASE_ARCHIVE_SHA256 = "4946db52ba9a559834cb3db075544480ac71fa4ae08b090a6708825a012a7b1b"
EXPECTED = {
    "applewin", "puae", "beetle-saturn", "dolphin", "ppsspp", "play", "armsx2", "flycast",
    "azahar", "virtualjaguar", "scummvm",
}
EXPECTED_LIBRARY_ROUTES = {
    "applewin": ["apple2"],
    "puae": ["amiga", "amigacd32"],
    "beetle-saturn": [],
    "dolphin": ["gamecube", "wii"],
    "ppsspp": ["psp"],
    "play": [],
    "armsx2": ["ps2"],
    "flycast": ["dreamcast"],
    "azahar": ["3ds"],
    "virtualjaguar": [],
    "scummvm": ["scummvm"],
}
LICENSES = {
    "applewin": "assets/APPLEWIN-LICENSE.txt",
    "puae": "assets/PUAE-LICENSE.txt",
    "beetle-saturn": "assets/BEETLE-SATURN-LICENSE.txt",
    "dolphin": "assets/DOLPHIN-LICENSE.txt",
    "ppsspp": "assets/PPSSPP-LICENSE.txt",
    "play": "assets/PLAY-LICENSE.txt",
    "armsx2": "assets/ARMSX2-LICENSE.txt",
    "flycast": "assets/FLYCAST-LICENSE.txt",
    "azahar": "assets/AZAHAR-LICENSE.txt",
    "virtualjaguar": "assets/VIRTUALJAGUAR-LICENSE.txt",
    "scummvm": "assets/scummvm-compliance/licenses/ScummVM-GPL-3.0.txt",
}


def _read_json(archive: zipfile.ZipFile, name: str) -> dict:
    return json.loads(archive.read(name).decode("utf-8"))


def _by_id(rows: list[dict], key: str = "id") -> dict[str, dict]:
    result: dict[str, dict] = {}
    for row in rows:
        value = row.get(key)
        if not isinstance(value, str) or value in result:
            raise ValueError(f"duplicate or invalid {key}")
        result[value] = row
    return result


def _asset_tree_sha256(archive: zipfile.ZipFile, root: str) -> str:
    prefix = "assets/" + root.rstrip("/") + "/"
    digest = hashlib.sha256()
    files = sorted(name for name in archive.namelist()
                   if name.startswith(prefix) and not name.endswith("/"))
    for name in files:
        relative = name[len(prefix):].encode("utf-8")
        file_hash = hashlib.sha256(archive.read(name)).hexdigest().encode("ascii")
        digest.update(relative + b"\0" + file_hash + b"\0")
    return digest.hexdigest()


def verify_ps2_page_variant(archive, artifact, commit, sbom_checksums):
    """Both memory geometries must be in this APK, with exact identities."""
    name = "liblucent_core_armsx2_16k.so"
    variants = artifact.get("pageSizeVariants", [])
    if artifact.get("hostPageSize") != 4096 or len(variants) != 1:
        return ["PS2 requires exactly the 4 KiB base and one 16 KiB variant"]
    variant = variants[0]
    if (variant.get("hostPageSize") != 16384 or variant.get("fileName") != name or
            variant.get("sourceCommit") != commit):
        return ["PS2 host-page variant has an invalid page size, file name, or source"]
    try:
        actual = hashlib.sha256(archive.read("lib/arm64-v8a/" + name)).hexdigest()
    except KeyError:
        return ["PS2 16 KiB core is missing from the APK"]
    if variant.get("sha256") != actual or actual not in sbom_checksums:
        return ["PS2 16 KiB core hash differs from manifest or SBOM"]
    return []


def verify(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        return [f"cannot open APK: {exc}"]
    with archive:
        names = set(archive.namelist())
        required = {
            REGISTRY, OPT_IN, ARTIFACTS, SBOM, PLAY_LOCK, FLYCAST_LOCK,
            ARMSX2_LOCK, AZAHAR_LOCK, DOLPHIN_LOCK, APPLEWIN_LOCK,
            APPLEWIN_FIRMWARE_POLICY, PUAE_LOCK, PUAE_FIRMWARE_POLICY,
            PUAE_AUDIT, PUAE_CONTENT, PUAE_NOTICES, SCUMMVM_LOCK,
            SCUMMVM_AUDIT, SCUMMVM_CONTENT, SCUMMVM_COMPLIANCE_MANIFEST,
            SCUMMVM_NOTICES,
            *LICENSES.values(),
        }
        for name in sorted(required - names):
            errors.append(f"missing qualification payload: {name}")
        if errors:
            return errors
        try:
            registry = _read_json(archive, REGISTRY)
            opt_in = _read_json(archive, OPT_IN)
            artifacts = _read_json(archive, ARTIFACTS)
            sbom = _read_json(archive, SBOM)
            play_lock = _read_json(archive, PLAY_LOCK)
            flycast_lock = _read_json(archive, FLYCAST_LOCK)
            armsx2_lock = _read_json(archive, ARMSX2_LOCK)
            azahar_lock = _read_json(archive, AZAHAR_LOCK)
            dolphin_lock = _read_json(archive, DOLPHIN_LOCK)
            applewin_lock = _read_json(archive, APPLEWIN_LOCK)
            applewin_policy = _read_json(archive, APPLEWIN_FIRMWARE_POLICY)
            puae_lock = _read_json(archive, PUAE_LOCK)
            puae_policy = _read_json(archive, PUAE_FIRMWARE_POLICY)
            puae_audit = _read_json(archive, PUAE_AUDIT)
            puae_content = _read_json(archive, PUAE_CONTENT)
            scummvm_lock = _read_json(archive, SCUMMVM_LOCK)
            scummvm_audit = _read_json(archive, SCUMMVM_AUDIT)
            scummvm_content = _read_json(archive, SCUMMVM_CONTENT)
            scummvm_compliance = _read_json(archive, SCUMMVM_COMPLIANCE_MANIFEST)
            enabled = _by_id(opt_in.get("engines", []))
            identities = _by_id(artifacts.get("artifacts", []), "engineId")
            rows = _by_id(registry.get("engines", []))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            return [f"invalid qualification JSON: {exc}"]

        if set(enabled) != EXPECTED or set(identities) != EXPECTED:
            errors.append("Phase 2 opt-in/artifact set is not the exact qualified set")
        if opt_in.get("qualificationOnly") is not True or opt_in.get("autoSelect") is not False:
            errors.append("Phase 2 qualification payload is not fail-closed")
        actual_routes = {
            engine_id: row.get("libraryRouteSystems", [])
            for engine_id, row in enabled.items()
        }
        if actual_routes != EXPECTED_LIBRARY_ROUTES:
            errors.append("Phase 2 normal-library routes are not the exact qualified subset")
        if (sbom.get("spdxVersion") != "SPDX-2.3" or
                sbom.get("dataLicense") != "CC0-1.0"):
            errors.append("Phase 2 SBOM is not SPDX 2.3 CC0 data")
        sbom_checksums = {
            checksum.get("checksumValue")
            for package in sbom.get("packages", [])
            for checksum in package.get("checksums", [])
            if checksum.get("algorithm") == "SHA256"
        }
        sbom_versions = {package.get("versionInfo") for package in sbom.get("packages", [])}
        sbom_by_name = {package.get("name"): package
                        for package in sbom.get("packages", [])}
        relationships = sbom.get("relationships", [])

        locked_patches = play_lock.get("patches", [])
        if len(locked_patches) != 6:
            errors.append("Play source lock does not identify the six reviewed patches")
        for patch in locked_patches:
            package = sbom_by_name.get(patch.get("path"))
            checksums = [] if package is None else package.get("checksums", [])
            if not any(value.get("algorithm") == "SHA256" and
                       value.get("checksumValue") == patch.get("sha256")
                       for value in checksums):
                errors.append(f"SBOM does not identify locked Play patch {patch.get('path')}")
                continue
            patch_id = package.get("SPDXID")
            if not any(value.get("spdxElementId") == patch_id and
                       value.get("relationshipType") == "PATCH_FOR"
                       for value in relationships):
                errors.append(f"SBOM does not bind Play patch to source {patch.get('path')}")

        flycast_dependencies = flycast_lock.get("dependencies", [])
        if len(flycast_dependencies) != 4:
            errors.append("Flycast source lock does not identify its four external dependencies")
        for dependency in flycast_dependencies:
            package = sbom_by_name.get(dependency.get("path"))
            checksums = [] if package is None else package.get("checksums", [])
            if not any(value.get("algorithm") == "SHA256" and
                       value.get("checksumValue") == dependency.get("archiveSha256")
                       for value in checksums):
                errors.append(
                    f"SBOM does not identify locked Flycast dependency {dependency.get('path')}"
                )

        armsx2_dependencies = armsx2_lock.get("dependencies", [])
        if len(armsx2_dependencies) != 7:
            errors.append("ARMSX2 source lock does not identify its seven shaderc dependencies")
        for dependency in armsx2_dependencies:
            package = sbom_by_name.get(dependency.get("path"))
            checksums = [] if package is None else package.get("checksums", [])
            if not any(value.get("algorithm") == "SHA256" and
                       value.get("checksumValue") == dependency.get("archiveSha256")
                       for value in checksums):
                errors.append(
                    f"SBOM does not identify locked ARMSX2 dependency {dependency.get('path')}"
                )
        armsx2_patches = armsx2_lock.get("patches", [])
        if armsx2_patches != ARMSX2_PATCHES:
            errors.append("ARMSX2 source lock does not identify the exact integration and frame-clock patches")
        for patch in armsx2_patches:
            package = sbom_by_name.get(patch.get("path"))
            checksums = [] if package is None else package.get("checksums", [])
            if not any(value.get("algorithm") == "SHA256" and
                       value.get("checksumValue") == patch.get("sha256")
                       for value in checksums):
                errors.append(
                    f"SBOM does not identify locked ARMSX2 patch {patch.get('path')}"
                )
                continue
            patch_id = package.get("SPDXID")
            if not any(value.get("spdxElementId") == patch_id and
                       value.get("relationshipType") == "PATCH_FOR"
                       for value in relationships):
                errors.append(
                    f"SBOM does not bind ARMSX2 patch to source {patch.get('path')}"
                )
        armsx2_row = rows.get("armsx2", {})
        armsx2_source = armsx2_row.get("source") or {}
        armsx2_core = armsx2_lock.get("core") or {}
        armsx2_toolchain = armsx2_lock.get("toolchain") or {}
        if (armsx2_core.get("repository") != armsx2_source.get("repository") or
                armsx2_core.get("commit") != armsx2_source.get("commit") or
                armsx2_core.get("archiveSha256") !=
                armsx2_source.get("archiveSha256")):
            errors.append("ARMSX2 source lock core identity differs from registry")
        if (armsx2_toolchain.get("androidAbi") != "arm64-v8a" or
                armsx2_toolchain.get("androidApi") != 26 or
                armsx2_toolchain.get("ndkVersion") != "27.0.12077973" or
                armsx2_toolchain.get("cmakeVersion") != "3.31.6-g38307f9" or
                armsx2_toolchain.get("ninjaVersion") != "1.12.1"):
            errors.append("ARMSX2 source lock toolchain profile is inconsistent")

        azahar_row = rows.get("azahar", {})
        azahar_source = azahar_row.get("source") or {}
        azahar_core = azahar_lock.get("core") or {}
        azahar_release = azahar_lock.get("releaseArtifact") or {}
        if (azahar_core.get("repository") != azahar_source.get("repository") or
                azahar_core.get("commit") != azahar_source.get("commit") or
                azahar_core.get("archiveSha256") !=
                azahar_source.get("archiveSha256")):
            errors.append("Azahar source lock core identity differs from registry")
        azahar_source_build = azahar_lock.get("sourceBuild")
        if azahar_source_build is not None:
            expected_profile = {
                "androidAbi": "arm64-v8a", "androidApi": 23,
                "ndkVersion": "27.0.12077973", "linkAlignment": 16384,
                "builtinKeyblob": False,
            }
            if (azahar_release or not isinstance(azahar_source_build, dict) or
                    any(azahar_source_build.get(k) != v for k, v in expected_profile.items()) or
                    azahar_source_build.get("artifactSha256") !=
                    (azahar_row.get("build") or {}).get("proofArtifactSha256")):
                errors.append("Azahar source-build artifact/profile is inconsistent")
            dependencies = azahar_lock.get("dependencies", [])
            paths = [item.get("path") for item in dependencies]
            if (len(dependencies) != 52 or len(set(paths)) != len(paths) or
                    any(not isinstance(item.get("path"), str) or
                        ".." in item["path"].split("/") or item["path"].startswith("/") or
                        not str(item.get("repository", "")).startswith("https://github.com/") or
                        not re.fullmatch(r"[0-9a-f]{40}", str(item.get("commit", ""))) or
                        not re.fullmatch(r"[0-9a-f]{40}", str(item.get("gitTreeSha1", "")))
                        for item in dependencies)):
                errors.append("Azahar source-build recursive gitlink closure is invalid")
            patches = azahar_lock.get("patches", [])
            if (len(patches) != 1 or
                    patches[0].get("path") != "engines/patches/azahar-android-strerror.patch" or
                    not re.fullmatch(r"[0-9a-f]{64}", str(patches[0].get("sha256", "")))):
                errors.append("Azahar source-build Android patch identity is invalid")
        elif (azahar_release.get("member") != "azahar_libretro.so" or
                azahar_release.get("memberSha256") !=
                (azahar_row.get("build") or {}).get("proofArtifactSha256") or
                not str(azahar_release.get("url", "")).startswith(
                    "https://github.com/azahar-emu/azahar/releases/download/2125.1.3/") or
                azahar_release.get("archiveSha256") !=
                AZAHAR_RELEASE_ARCHIVE_SHA256):
            errors.append("Azahar official release artifact lock is inconsistent")
        if azahar_source_build is None and (azahar_lock.get("dependencies") != [] or azahar_lock.get("patches") != []):
            errors.append("Azahar published-artifact lock has an unexpected staged closure")

        dolphin_row = rows.get("dolphin", {})
        dolphin_source = dolphin_row.get("source") or {}
        dolphin_core = dolphin_lock.get("core") or {}
        dolphin_options = dolphin_lock.get("cmakeOptions") or {}
        if (dolphin_core.get("repository") != dolphin_source.get("repository") or
                dolphin_core.get("commit") != dolphin_source.get("commit") or
                dolphin_core.get("archiveSha256") !=
                dolphin_source.get("archiveSha256")):
            errors.append("Dolphin source lock core identity differs from registry")
        if (dolphin_options.get("normalizedByRemovingSection") !=
                ".note.gnu.build-id" or
                dolphin_options.get("normalizedArtifactSha256") !=
                (dolphin_row.get("build") or {}).get("proofArtifactSha256")):
            errors.append("Dolphin normalized reproducibility lock is inconsistent")

        applewin_row = rows.get("applewin", {})
        applewin_source = applewin_row.get("source") or {}
        applewin_core = applewin_lock.get("core") or {}
        applewin_artifact = applewin_lock.get("artifact") or {}
        applewin_firmware = applewin_row.get("firmware") or {}
        if (applewin_core.get("repository") != applewin_source.get("repository") or
                applewin_core.get("commit") != applewin_source.get("commit") or
                applewin_core.get("archiveSha256") !=
                applewin_source.get("archiveSha256")):
            errors.append("AppleWin source lock core identity differs from registry")
        if (applewin_artifact.get("sha256") !=
                (applewin_row.get("build") or {}).get("proofArtifactSha256") or
                applewin_artifact.get("firstCleanBuildSha256") !=
                applewin_artifact.get("sha256") or
                applewin_artifact.get("secondCleanBuildSha256") !=
                applewin_artifact.get("sha256") or
                applewin_artifact.get("embeddedUpstreamFirmwareByteMatches") != 0):
            errors.append("AppleWin clean-build or firmware-exclusion proof is inconsistent")
        policy_lock = applewin_lock.get("firmwarePolicy") or {}
        if (policy_lock.get("path") != "engines/applewin-firmware-policy.json" or
                policy_lock.get("sha256") !=
                hashlib.sha256(archive.read(APPLEWIN_FIRMWARE_POLICY)).hexdigest()):
            errors.append("AppleWin packaged firmware policy differs from source lock")
        distribution = applewin_policy.get("distribution") or {}
        release_gates = applewin_policy.get("releaseGates") or {}
        if (applewin_policy.get("engineId") != "applewin" or
                applewin_policy.get("sourceCommit") != applewin_source.get("commit") or
                distribution.get("firmwareBundled") is not False or
                distribution.get("upstreamFirmwareResourcesRemoved") is not True or
                distribution.get("userFilesCopiedToPrivateStorageOnly") is not True or
                any(release_gates.get(gate) is not False for gate in (
                    "firmwareProvenance", "legalTestContent", "deviceQualification")) or
                applewin_firmware.get("acceptedHashes") != [] or
                (applewin_row.get("gates") or {}).get("firmware") is not False):
            errors.append("AppleWin firmware policy does not preserve the open release gates")
        applewin_profiles = enabled.get("applewin", {}).get("firmwareProfiles", [])
        applewin_profile = next((profile for profile in applewin_profiles
                                 if profile.get("system") == "apple2"), {})
        alternatives = applewin_profile.get("alternatives", [])
        policy_files = applewin_policy.get("requiredFiles", [])
        profile_files = alternatives[0] if len(alternatives) == 1 else []
        policy_identity = [
            {key: file.get(key) for key in ("destination", "size", "md5", "sha256")}
            for file in policy_files
        ]
        if (applewin_profile.get("mode") != "user-files" or
                len(policy_files) != 6 or profile_files != policy_identity or
                len({file.get("destination") for file in policy_files}) != 6 or
                any(len(str(file.get("sha256", ""))) != 64 or
                    any(character not in "0123456789abcdef" for character in
                        str(file.get("sha256", ""))) for file in policy_files)):
            errors.append("AppleWin does not fail closed on the exact six-file user firmware policy")
        forbidden_firmware_names = {file.get("destination") for file in policy_files}
        if any(Path(name).name in forbidden_firmware_names for name in names):
            errors.append("AppleWin firmware bytes or files are unexpectedly bundled in the APK")
        applewin_patches = applewin_lock.get("patches", [])
        if len(applewin_patches) != 1:
            errors.append("AppleWin source lock does not identify its firmware-removal patch")
        for patch in applewin_patches:
            package = sbom_by_name.get(patch.get("path"))
            checksums = [] if package is None else package.get("checksums", [])
            if not any(value.get("algorithm") == "SHA256" and
                       value.get("checksumValue") == patch.get("sha256")
                       for value in checksums):
                errors.append("SBOM does not identify the locked AppleWin patch")
                continue
            patch_id = package.get("SPDXID")
            if not any(value.get("spdxElementId") == patch_id and
                       value.get("relationshipType") == "PATCH_FOR"
                       for value in relationships):
                errors.append("SBOM does not bind AppleWin patch to source")

        puae_row = rows.get("puae", {})
        puae_source = puae_row.get("source") or {}
        puae_core = puae_lock.get("core") or {}
        puae_artifact = puae_lock.get("artifact") or {}
        if (puae_core.get("repository") != puae_source.get("repository") or
                puae_core.get("commit") != puae_source.get("commit") or
                puae_core.get("archiveSha256") != puae_source.get("archiveSha256")):
            errors.append("PUAE source lock core identity differs from registry")
        if (puae_artifact.get("sha256") !=
                (puae_row.get("build") or {}).get("proofArtifactSha256") or
                puae_artifact.get("firstCleanBuildSha256") !=
                puae_artifact.get("sha256") or
                puae_artifact.get("secondCleanBuildSha256") !=
                puae_artifact.get("sha256") or
                puae_artifact.get("embeddedArosCompressedMatches") != 1):
            errors.append("PUAE clean-build or embedded AROS proof is inconsistent")
        for key, asset, expected_path in (
                ("firmwarePolicy", PUAE_FIRMWARE_POLICY,
                 "engines/puae-firmware-policy.json"),
                ("dependencyAudit", PUAE_AUDIT,
                 "engines/puae-dependency-audit.json"),
                ("legalTestContent", PUAE_CONTENT,
                 "engines/puae-test-content-lock.json"),
                ("notices", PUAE_NOTICES, "engines/PUAE-CORE-NOTICES.txt")):
            locked = puae_lock.get(key) or {}
            if (locked.get("path") != expected_path or locked.get("sha256") !=
                    hashlib.sha256(archive.read(asset)).hexdigest()):
                errors.append(f"PUAE packaged {key} differs from source lock")
        puae_aros = puae_policy.get("amiga") or {}
        puae_aros_raw = puae_aros.get("compressedPayload") or {}
        puae_aros_rom = puae_aros.get("decompressedPayload") or {}
        puae_cd32 = puae_policy.get("amigacd32") or {}
        if (puae_aros_raw.get("sha256") !=
                "5ee9dade0feeae8b0f30e3b35b0b79535b7313c89e3328dc6ad6bc43f42f620c" or
                puae_aros_rom.get("sha256") !=
                "1211897caea79785f2441da4b75a460255b7f85e5129e03fe0ab61a8aebfb2c1" or
                puae_aros.get("provenance", {}).get("status") !=
                "exact-core-snapshot-bound-upstream-build-unresolved" or
                puae_policy.get("distribution", {}).get(
                    "proprietaryFirmwareBundled") is not False or
                any(puae_policy.get("releaseGates", {}).values()) or
                any((puae_row.get("gates") or {}).get(gate) is not False
                    for gate in ("license", "dependencies", "firmware",
                                 "legalContent", "renderer", "state",
                                 "performance", "device"))):
            errors.append("PUAE firmware policy does not preserve exact identity and open gates")
        if puae_cd32.get("alternatives") != next(
                (profile.get("alternatives") for profile in
                 enabled.get("puae", {}).get("firmwareProfiles", [])
                 if profile.get("system") == "amigacd32"), None):
            errors.append("PUAE CD32 user firmware profile differs from policy")
        if (puae_audit.get("linkedObjectCount") != 227 or
                sum(component.get("objectCount", 0) for component in
                    puae_audit.get("components", [])) != 227 or
                not puae_audit.get("unresolved")):
            errors.append("PUAE configuration-specific dependency audit is inconsistent")
        if (puae_content.get("license") != "CC0-1.0" or
                (puae_content.get("artifact") or {}).get("sha256") !=
                "e5692a1ef7a769936b283b465f1dd965979a2cae1e16e4f8af32e41c310724b1" or
                puae_content.get("runtimeQualification") is not False):
            errors.append("PUAE legal test-content lock is inconsistent")
        for component in puae_lock.get("embeddedComponents", []):
            package = sbom_by_name.get(component.get("id"))
            checksums = [] if package is None else package.get("checksums", [])
            if not any(value.get("algorithm") == "SHA256" and
                       value.get("checksumValue") == component.get("evidenceSha256")
                       for value in checksums):
                errors.append(
                    f"SBOM does not identify PUAE embedded component {component.get('id')}"
                )
        if any(Path(name).name in {"kick40060.CD32", "kick40060.CD32.ext"}
               for name in names):
            errors.append("Proprietary CD32 firmware file is unexpectedly bundled in APK")

        scummvm_row = rows.get("scummvm", {})
        scummvm_source = scummvm_row.get("source") or {}
        scummvm_core = scummvm_lock.get("core") or {}
        scummvm_artifact = scummvm_lock.get("artifact") or {}
        scummvm_fixture_rows = scummvm_content.get("fixtures", [])
        scummvm_fixture = scummvm_fixture_rows[0] if len(scummvm_fixture_rows) == 1 else {}
        if (scummvm_core.get("repository") != scummvm_source.get("repository") or
                scummvm_core.get("commit") != scummvm_source.get("commit") or
                scummvm_core.get("archiveSha256") !=
                scummvm_source.get("archiveSha256")):
            errors.append("ScummVM source lock core identity differs from registry")
        if (scummvm_artifact.get("sha256") !=
                (scummvm_row.get("build") or {}).get("proofArtifactSha256") or
                scummvm_artifact.get("firstCleanBuildSha256") !=
                scummvm_artifact.get("sha256") or
                scummvm_artifact.get("secondCleanBuildSha256") !=
                scummvm_artifact.get("sha256") or
                scummvm_artifact.get("ptLoadAlignment") != "0x4000"):
            errors.append("ScummVM clean-build artifact proof is inconsistent")
        if (scummvm_audit.get("coreArtifactSha256") !=
                scummvm_artifact.get("sha256") or
                scummvm_audit.get("externalObjectCount") != 337 or
                len(scummvm_audit.get("components", [])) != 15 or
                len(scummvm_audit.get("embeddedComponents", [])) != 4):
            errors.append("ScummVM exact linked-component audit is inconsistent")
        if (scummvm_compliance.get("artifact", {}).get("sha256") !=
                scummvm_artifact.get("sha256") or
                scummvm_compliance.get("externalObjectCount") != 337 or
                len(scummvm_compliance.get("objects", [])) != 337):
            errors.append("ScummVM packaged compliance manifest is inconsistent")
        if (scummvm_fixture.get("sha256") !=
                (scummvm_row.get("legalTestContent") or {}).get("artifactSha256") or
                scummvm_fixture.get("distributionPolicy") != "official-download-only" or
                scummvm_fixture.get("bundleInApk") is not False):
            errors.append("ScummVM official download-only fixture lock is inconsistent")
        azahar_archive_package = next((
            package for package in sbom.get("packages", [])
            if any(checksum.get("algorithm") == "SHA256" and
                   checksum.get("checksumValue") == AZAHAR_RELEASE_ARCHIVE_SHA256
                   for checksum in package.get("checksums", []))
        ), None)
        azahar_binary_package = sbom_by_name.get("liblucent_core_azahar.so")
        if azahar_source_build is not None:
            source_package = sbom_by_name.get("Azahar source")
            if (azahar_binary_package is None or source_package is None or not any(
                    value.get("spdxElementId") == azahar_binary_package.get("SPDXID") and
                    value.get("relationshipType") == "GENERATED_FROM" and
                    value.get("relatedSpdxElement") == source_package.get("SPDXID")
                    for value in relationships)):
                errors.append("SBOM does not bind Azahar source-built core to its source")
            for dependency in azahar_lock.get("dependencies", []):
                package = sbom_by_name.get(dependency.get("path"), {})
                if (source_package is None or package.get("versionInfo") != dependency.get("commit") or
                        {"algorithm": "SHA1", "checksumValue": dependency.get("gitTreeSha1")} not in package.get("checksums", []) or
                        not any(value.get("spdxElementId") == source_package.get("SPDXID") and
                                value.get("relationshipType") == "DEPENDS_ON" and
                                value.get("relatedSpdxElement") == package.get("SPDXID")
                                for value in relationships)):
                    errors.append("SBOM does not bind Azahar Git dependency: " + str(dependency.get("path")))
            if azahar_binary_package is not None and any(
                    value.get("spdxElementId") == azahar_binary_package.get("SPDXID") and
                    value.get("relationshipType") == "EXTRACTED_FROM"
                    for value in relationships):
                errors.append("SBOM incorrectly describes source-built Azahar as an extracted release")
        elif azahar_archive_package is None or azahar_binary_package is None:
            errors.append("SBOM does not identify Azahar release archive and extracted core")
        else:
            extracted = any(
                value.get("spdxElementId") == azahar_binary_package.get("SPDXID") and
                value.get("relationshipType") == "EXTRACTED_FROM" and
                value.get("relatedSpdxElement") == azahar_archive_package.get("SPDXID")
                for value in relationships
            )
            if not extracted:
                errors.append("SBOM does not bind Azahar core to its release archive")
            if any(
                value.get("spdxElementId") == azahar_binary_package.get("SPDXID") and
                value.get("relationshipType") == "GENERATED_FROM"
                for value in relationships
            ):
                errors.append("SBOM overstates Azahar source-to-binary reproduction")

        for engine_id in sorted(EXPECTED):
            row = rows.get(engine_id)
            enable = enabled.get(engine_id)
            identity = identities.get(engine_id)
            if row is None or enable is None or identity is None:
                continue
            commit = (row.get("source") or {}).get("commit")
            expected_hash = (row.get("build") or {}).get("proofArtifactSha256")
            core = f"lib/arm64-v8a/liblucent_core_{engine_id.replace('-', '_')}.so"
            if core not in names:
                errors.append(f"missing qualification core: {core}")
                continue
            actual = hashlib.sha256(archive.read(core)).hexdigest()
            if enable.get("runtime") not in {"gles-libretro", "vulkan-libretro"}:
                errors.append(f"{engine_id} has no approved in-app qualification runtime")
            if enable.get("commit") != commit or identity.get("sourceCommit") != commit:
                errors.append(f"{engine_id} source commit differs across qualification assets")
            if enable.get("libraryName") != Path(core).name or identity.get("fileName") != Path(core).name:
                errors.append(f"{engine_id} packaged core name differs across assets")
            if not expected_hash or actual != expected_hash or identity.get("sha256") != actual:
                errors.append(f"{engine_id} packaged core hash does not match proof and manifest")
            if actual not in sbom_checksums or commit not in sbom_versions:
                errors.append(f"SBOM does not identify {engine_id} source and binary")
            if row.get("shipped") is not False:
                errors.append(f"{engine_id} registry unexpectedly marks the engine shipped")
            if not archive.read(LICENSES[engine_id]).strip():
                errors.append(f"{engine_id} license payload is empty")
            if engine_id == "armsx2":
                errors.extend(verify_ps2_page_variant(archive, identity, commit, sbom_checksums))

        ppsspp_root = "assets/phase2-system/ppsspp/PPSSPP/"
        if enabled.get("ppsspp", {}).get("systemAssetRoot") != \
                "phase2-system/ppsspp/PPSSPP":
            errors.append("PPSSPP system asset root is not the pinned package path")
        if not any(name.startswith(ppsspp_root) and not name.endswith("/") for name in names):
            errors.append("PPSSPP app-private runtime asset payload is empty")
        ppsspp_enabled = enabled.get("ppsspp", {})
        if (ppsspp_enabled.get("systemAssetRevision") !=
                _asset_tree_sha256(archive, "phase2-system/ppsspp/PPSSPP")):
            errors.append("PPSSPP runtime asset revision does not match packaged tree")
        for relative in ppsspp_enabled.get("systemAssetRequiredFiles", []):
            if "assets/phase2-system/ppsspp/PPSSPP/" + relative.removeprefix(
                    "PPSSPP/") not in names:
                errors.append(f"PPSSPP required runtime asset is missing: {relative}")
        armsx2_root = "assets/phase2-system/armsx2/pcsx2/resources/"
        if enabled.get("armsx2", {}).get("systemAssetRoot") != \
                "phase2-system/armsx2/pcsx2":
            errors.append("ARMSX2 system asset root is not the pinned package path")
        if not any(name.startswith(armsx2_root) and not name.endswith("/") for name in names):
            errors.append("ARMSX2 app-private runtime asset payload is empty")
        armsx2_enabled = enabled.get("armsx2", {})
        if (armsx2_enabled.get("systemAssetRevision") !=
                _asset_tree_sha256(archive, "phase2-system/armsx2/pcsx2")):
            errors.append("ARMSX2 runtime asset revision does not match packaged tree")
        for relative in armsx2_enabled.get("systemAssetRequiredFiles", []):
            if "assets/phase2-system/armsx2/pcsx2/" + relative.removeprefix(
                    "pcsx2/") not in names:
                errors.append(f"ARMSX2 required runtime asset is missing: {relative}")
        dolphin_root = "assets/phase2-system/dolphin/dolphin-emu/"
        dolphin_enabled = enabled.get("dolphin", {})
        if dolphin_enabled.get("systemAssetRoot") != \
                "phase2-system/dolphin/dolphin-emu":
            errors.append("Dolphin system asset root is not the pinned package path")
        if not any(name.startswith(dolphin_root) and not name.endswith("/") for name in names):
            errors.append("Dolphin app-private Sys payload is empty")
        if (dolphin_enabled.get("systemAssetRevision") !=
                _asset_tree_sha256(archive, "phase2-system/dolphin/dolphin-emu")):
            errors.append("Dolphin runtime asset revision does not match packaged tree")
        for relative in dolphin_enabled.get("systemAssetRequiredFiles", []):
            if dolphin_root + relative.removeprefix("dolphin-emu/") not in names:
                errors.append(f"Dolphin required runtime asset is missing: {relative}")
        scummvm_root = "assets/phase2-system/scummvm/scummvm/"
        scummvm_enabled = enabled.get("scummvm", {})
        if scummvm_enabled.get("systemAssetRoot") != \
                "phase2-system/scummvm/scummvm":
            errors.append("ScummVM runtime asset root is not the pinned package path")
        if not any(name.startswith(scummvm_root) and not name.endswith("/")
                   for name in names):
            errors.append("ScummVM app-private runtime data payload is empty")
        if (scummvm_enabled.get("systemAssetRevision") !=
                _asset_tree_sha256(archive, "phase2-system/scummvm/scummvm")):
            errors.append("ScummVM runtime asset revision does not match packaged tree")
        scummvm_files = [name for name in names
                         if name.startswith(scummvm_root) and not name.endswith("/")]
        if len(scummvm_files) != 207:
            errors.append("ScummVM runtime asset file count is not the pinned 207-file tree")
        for relative in scummvm_enabled.get("systemAssetRequiredFiles", []):
            if scummvm_root + relative.removeprefix("scummvm/") not in names:
                errors.append(f"ScummVM required runtime asset is missing: {relative}")

        puae_profiles = enabled.get("puae", {}).get("firmwareProfiles", [])
        puae_by_system = {profile.get("system"): profile for profile in puae_profiles}
        if (puae_by_system.get("amiga", {}).get("mode") != "builtin" or
                puae_by_system.get("amiga", {}).get("identity") !=
                "puae-aros-sha256-1211897caea79785f2441da4b75a460255b7f85e5129e03fe0ab61a8aebfb2c1"):
            errors.append("PUAE Amiga baseline is not pinned to its built-in AROS identity")
        cd32 = puae_by_system.get("amigacd32", {})
        if cd32.get("mode") != "user-files" or len(cd32.get("alternatives", [])) != 2:
            errors.append("PUAE CD32 does not fail closed on audited user firmware alternatives")
        saturn_profiles = enabled.get("beetle-saturn", {}).get("firmwareProfiles", [])
        saturn = next((profile for profile in saturn_profiles
                       if profile.get("system") == "saturn"), {})
        if saturn.get("mode") != "user-files" or len(saturn.get("alternatives", [])) != 2:
            errors.append("Beetle Saturn does not fail closed on audited regional BIOS identities")
        for profile in (applewin_profile, cd32, saturn):
            for alternative in profile.get("alternatives", []):
                for firmware in alternative:
                    md5 = str(firmware.get("md5", ""))
                    if (len(md5) != 32 or any(character not in "0123456789abcdef"
                                              for character in md5) or
                            not isinstance(firmware.get("size"), int) or
                            firmware.get("size", 0) <= 0):
                        errors.append("Phase 2 firmware profile contains an invalid identity")
                    sha256 = str(firmware.get("sha256", ""))
                    if sha256 and (len(sha256) != 64 or
                            any(character not in "0123456789abcdef"
                                for character in sha256)):
                        errors.append("Phase 2 firmware profile contains an invalid SHA-256 identity")
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
    print("Phase 2 multi-core qualification payload verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
