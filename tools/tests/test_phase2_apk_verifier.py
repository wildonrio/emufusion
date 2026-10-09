import hashlib
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "unified-android" / "tools" / "verify_phase2_apk.py"
SPEC = importlib.util.spec_from_file_location("verify_phase2_apk", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class PhaseTwoApkVerifierTest(unittest.TestCase):
    def make_apk(self, root: Path, *, core=b"pinned-core", auto_select=False) -> Path:
        path = root / "lucent.apk"
        runtime_assets = {
            "phase2-system/ppsspp/PPSSPP": {
                "compat.ini": b"[games]",
            },
            "phase2-system/armsx2/pcsx2": {
                "resources/GameIndex.yaml": b"games: {}",
                "resources/patches.zip": b"locked-patches",
            },
            "phase2-system/dolphin/dolphin-emu": {
                "Sys/GC/dsp_rom.bin": b"dsp-rom",
                "Sys/GC/font_western.bin": b"font",
                "Sys/Resources/OSD_Font.ttf": b"osd-font",
                "Sys/Wii/shared2/wc24/nwc24msg.cfg": b"wii-config",
            },
            "phase2-system/scummvm/scummvm": {
                "extra/encoding.dat": b"encoding",
                "extra/sky.cpt": b"sky",
                **{f"extra/test-{index:03}.dat": f"asset-{index}".encode()
                   for index in range(205)},
            },
        }

        def tree_revision(files):
            digest = hashlib.sha256()
            for name, payload in sorted(files.items()):
                digest.update(name.encode() + b"\0" +
                              hashlib.sha256(payload).hexdigest().encode() + b"\0")
            return digest.hexdigest()

        payloads = {
            "applewin": b"applewin-core-without-firmware",
            "puae": b"puae-core",
            "beetle-saturn": b"saturn-core",
            "dolphin": b"dolphin-core",
            "ppsspp": core,
            "play": b"play-core",
            "armsx2": b"armsx2-core",
            "flycast": b"flycast-core",
            "azahar": b"azahar-core",
            "virtualjaguar": b"jaguar-core",
            "scummvm": b"scummvm-core",
        }
        commits = {engine_id: character * 40 for engine_id, character in
                   (("applewin", "0"), ("puae", "2"), ("beetle-saturn", "3"), ("dolphin", "4"),
                    ("ppsspp", "a"), ("play", "b"), ("armsx2", "c"),
                    ("flycast", "d"), ("azahar", "e"),
                    ("virtualjaguar", "f"), ("scummvm", "1"))}

        def firmware_profiles(engine_id):
            if engine_id == "applewin":
                return [{
                    "system": "apple2", "mode": "user-files",
                    "alternatives": [[
                        {"destination": name, "size": index + 1,
                         "md5": f"{index + 1:032x}",
                         "sha256": hashlib.sha256(name.encode()).hexdigest()}
                        for index, name in enumerate((
                            "Apple2e_Enhanced.rom", "Apple2e_Enhanced_Video.rom",
                            "DISK2-13sector.rom", "DISK2.rom", "Parallel.rom",
                            "SSC.rom"))
                    ]],
                }]
            if engine_id == "puae":
                return [{
                    "system": "amiga", "mode": "builtin",
                    "identity": ("puae-aros-sha256-"
                                 "1211897caea79785f2441da4b75a460255b7f85e5129e03fe0ab61a8aebfb2c1"),
                }, {
                    "system": "amigacd32", "mode": "user-files",
                    "alternatives": [
                        [{"destination": "kick40060.CD32", "size": 1048576,
                          "md5": "f2f241bf094168cfb9e7805dc2856433"}],
                        [{"destination": "kick40060.CD32", "size": 524288,
                          "md5": "5f8924d013dd57a89cf349f4cdedc6b1"},
                         {"destination": "kick40060.CD32.ext", "size": 524288,
                          "md5": "bb72565701b1b6faece07d68ea5da639"}],
                    ],
                }]
            if engine_id == "beetle-saturn":
                return [{
                    "system": "saturn", "mode": "user-files",
                    "alternatives": [
                        [{"destination": "sega_101.bin", "size": 524288,
                          "md5": "85ec9ca47d8f6807718151cbcca8b964"}],
                        [{"destination": "mpr-17933.bin", "size": 524288,
                          "md5": "3240872c70984b6cbfda1586cab68dbe"}],
                    ],
                }]
            return None
        library_routes = {
            "applewin": ["apple2"],
            "puae": ["amiga", "amigacd32"],
            "dolphin": ["gamecube", "wii"],
            "ppsspp": ["psp"],
            "armsx2": ["ps2"],
            "flycast": ["dreamcast"],
            "azahar": ["3ds"],
            "scummvm": ["scummvm"],
        }
        registry = {"engines": [{
            "id": engine_id,
            "source": {
                "repository": f"https://github.com/example/{engine_id}",
                "commit": commits[engine_id],
                "archiveSha256": hashlib.sha256(
                    f"{engine_id}-source".encode()).hexdigest(),
            },
            "build": {"proofArtifactSha256": hashlib.sha256(payload).hexdigest()},
            **({"firmware": {"acceptedHashes": []},
                "gates": {"firmware": False}} if engine_id == "applewin" else {}),
            "shipped": False,
        } for engine_id, payload in payloads.items()]}
        scummvm_fixture_sha = hashlib.sha256(b"official-scummvm-fixture").hexdigest()
        next(row for row in registry["engines"] if row["id"] == "scummvm")[
            "legalTestContent"] = {"artifactSha256": scummvm_fixture_sha}
        puae_registry = next(row for row in registry["engines"]
                             if row["id"] == "puae")
        puae_registry["gates"] = {
            key: False for key in ("license", "dependencies", "firmware",
                                   "legalContent", "renderer", "state",
                                   "performance", "device")
        }
        def qualification_entry(engine_id):
            entry = {
                "id": engine_id,
                "commit": commits[engine_id],
                "libraryName": f"liblucent_core_{engine_id.replace('-', '_')}.so",
                "runtime": ("vulkan-libretro" if engine_id in {"armsx2", "azahar"}
                            else "gles-libretro"),
                **({"firmwareProfiles": firmware_profiles(engine_id)}
                   if firmware_profiles(engine_id) else {}),
                **({"libraryRouteSystems": library_routes[engine_id]}
                   if engine_id in library_routes else {}),
            }
            system_assets = ({
                    "systemAssetRoot": "phase2-system/ppsspp/PPSSPP",
                    "systemAssetRevision": tree_revision(
                        runtime_assets["phase2-system/ppsspp/PPSSPP"]),
                    "systemAssetRequiredFiles": ["PPSSPP/compat.ini"],
                  }
                  if engine_id == "ppsspp" else
                  {
                    "systemAssetRoot": "phase2-system/armsx2/pcsx2",
                    "systemAssetRevision": tree_revision(
                        runtime_assets["phase2-system/armsx2/pcsx2"]),
                    "systemAssetRequiredFiles": [
                        "pcsx2/resources/GameIndex.yaml",
                        "pcsx2/resources/patches.zip",
                    ],
                  }
                  if engine_id == "armsx2" else
                  {
                    "systemAssetRoot": "phase2-system/dolphin/dolphin-emu",
                    "systemAssetDestination": "dolphin-emu",
                    "systemAssetProbe": "dolphin-emu/Sys/GC/dsp_rom.bin",
                    "systemAssetRevision": tree_revision(
                        runtime_assets["phase2-system/dolphin/dolphin-emu"]),
                    "systemAssetRequiredFiles": [
                        "dolphin-emu/Sys/GC/dsp_rom.bin",
                        "dolphin-emu/Sys/GC/font_western.bin",
                        "dolphin-emu/Sys/Resources/OSD_Font.ttf",
                        "dolphin-emu/Sys/Wii/shared2/wc24/nwc24msg.cfg",
                    ],
                  }
                  if engine_id == "dolphin" else
                  {
                    "systemAssetRoot": "phase2-system/scummvm/scummvm",
                    "systemAssetDestination": "scummvm",
                    "systemAssetProbe": "scummvm/extra/encoding.dat",
                    "systemAssetRevision": tree_revision(
                        runtime_assets["phase2-system/scummvm/scummvm"]),
                    "systemAssetRequiredFiles": [
                        "scummvm/extra/encoding.dat", "scummvm/extra/sky.cpt",
                    ],
                  }
                  if engine_id == "scummvm" else {})
            entry.update(system_assets)
            return entry

        opt_in = {
            "qualificationOnly": True,
            "autoSelect": auto_select,
            "engines": [qualification_entry(engine_id) for engine_id in payloads],
        }
        artifacts = {"artifacts": [{
            "engineId": engine_id,
            "sourceCommit": commits[engine_id],
            "fileName": f"liblucent_core_{engine_id.replace('-', '_')}.so",
            "sha256": hashlib.sha256(payload).hexdigest(),
        } for engine_id, payload in payloads.items()]}
        ps2_variant_payload = b"armsx2-16k-core"
        ps2_variant = {
            "hostPageSize": 16384, "fileName": "liblucent_core_armsx2_16k.so",
            "sourceCommit": commits["armsx2"],
            "sha256": hashlib.sha256(ps2_variant_payload).hexdigest(),
        }
        ps2_artifact = next(a for a in artifacts["artifacts"] if a["engineId"] == "armsx2")
        ps2_artifact.update(hostPageSize=4096, pageSizeVariants=[ps2_variant])
        play_patches = [{
            "path": f"engines/patches/play-{index}.patch",
            "sha256": hashlib.sha256(f"patch-{index}".encode()).hexdigest(),
        } for index in range(6)]
        play_lock = {"patches": play_patches}
        applewin_policy_files = list(
            firmware_profiles("applewin")[0]["alternatives"][0]
        )
        applewin_policy = {
            "engineId": "applewin",
            "sourceCommit": commits["applewin"],
            "distribution": {
                "firmwareBundled": False,
                "upstreamFirmwareResourcesRemoved": True,
                "userFilesCopiedToPrivateStorageOnly": True,
            },
            "requiredFiles": applewin_policy_files,
            "releaseGates": {
                "firmwareProvenance": False,
                "legalTestContent": False,
                "deviceQualification": False,
            },
        }
        applewin_policy_bytes = json.dumps(applewin_policy).encode()
        applewin_patch = {
            "path": "engines/patches/applewin-external-firmware.patch",
            "sha256": hashlib.sha256(b"applewin-patch").hexdigest(),
        }
        applewin_sha = hashlib.sha256(payloads["applewin"]).hexdigest()
        applewin_lock = {
            "core": {
                "repository": "https://github.com/example/applewin",
                "commit": commits["applewin"],
                "archiveSha256": hashlib.sha256(b"applewin-source").hexdigest(),
            },
            "patches": [applewin_patch],
            "firmwarePolicy": {
                "path": "engines/applewin-firmware-policy.json",
                "sha256": hashlib.sha256(applewin_policy_bytes).hexdigest(),
            },
            "artifact": {
                "sha256": applewin_sha,
                "firstCleanBuildSha256": applewin_sha,
                "secondCleanBuildSha256": applewin_sha,
                "embeddedUpstreamFirmwareByteMatches": 0,
            },
        }
        puae_policy = {
            "amiga": {
                "compressedPayload": {
                    "sha256": "5ee9dade0feeae8b0f30e3b35b0b79535b7313c89e3328dc6ad6bc43f42f620c"
                },
                "decompressedPayload": {
                    "sha256": "1211897caea79785f2441da4b75a460255b7f85e5129e03fe0ab61a8aebfb2c1"
                },
                "provenance": {
                    "status": "exact-core-snapshot-bound-upstream-build-unresolved"
                },
            },
            "amigacd32": {
                "alternatives": firmware_profiles("puae")[1]["alternatives"]
            },
            "distribution": {"proprietaryFirmwareBundled": False},
            "releaseGates": {
                "arosSourceReproduction": False,
                "arosLicenseProvenance": False,
                "cd32LawfulProvenance": False,
                "deviceExecution": False,
            },
        }
        puae_policy_bytes = json.dumps(puae_policy).encode()
        puae_audit = {
            "linkedObjectCount": 227,
            "components": [{"objectCount": 227}],
            "unresolved": ["rights audit remains open"],
        }
        puae_audit_bytes = json.dumps(puae_audit).encode()
        puae_content = {
            "license": "CC0-1.0",
            "artifact": {
                "sha256": "e5692a1ef7a769936b283b465f1dd965979a2cae1e16e4f8af32e41c310724b1"
            },
            "runtimeQualification": False,
        }
        puae_content_bytes = json.dumps(puae_content).encode()
        puae_notices = b"PUAE qualification notices"
        puae_sha = hashlib.sha256(payloads["puae"]).hexdigest()
        puae_components = [{
            "id": "puae-core",
            "path": "sources",
            "evidenceSha256": hashlib.sha256(b"puae-license").hexdigest(),
        }]
        puae_lock = {
            "core": {
                "repository": "https://github.com/example/puae",
                "commit": commits["puae"],
                "archiveSha256": hashlib.sha256(b"puae-source").hexdigest(),
            },
            "artifact": {
                "sha256": puae_sha,
                "firstCleanBuildSha256": puae_sha,
                "secondCleanBuildSha256": puae_sha,
                "embeddedArosCompressedMatches": 1,
            },
            "firmwarePolicy": {
                "path": "engines/puae-firmware-policy.json",
                "sha256": hashlib.sha256(puae_policy_bytes).hexdigest(),
            },
            "dependencyAudit": {
                "path": "engines/puae-dependency-audit.json",
                "sha256": hashlib.sha256(puae_audit_bytes).hexdigest(),
            },
            "legalTestContent": {
                "path": "engines/puae-test-content-lock.json",
                "sha256": hashlib.sha256(puae_content_bytes).hexdigest(),
            },
            "notices": {
                "path": "engines/PUAE-CORE-NOTICES.txt",
                "sha256": hashlib.sha256(puae_notices).hexdigest(),
            },
            "embeddedComponents": puae_components,
        }
        flycast_dependencies = [{
            "path": f"core/deps/flycast-dependency-{index}",
            "archiveSha256": hashlib.sha256(
                f"flycast-dependency-{index}".encode()).hexdigest(),
        } for index in range(4)]
        flycast_lock = {"dependencies": flycast_dependencies}
        armsx2_dependencies = [{
            "path": f"core/deps/armsx2-dependency-{index}",
            "repository": f"https://github.com/example/armsx2-dependency-{index}",
            "commit": str(index + 1) * 40,
            "archiveSha256": hashlib.sha256(
                f"armsx2-dependency-{index}".encode()).hexdigest(),
        } for index in range(7)]
        armsx2_patches = [dict(patch) for patch in MODULE.ARMSX2_PATCHES]
        armsx2_lock = {
            "core": {
                "repository": "https://github.com/example/armsx2",
                "commit": commits["armsx2"],
                "archiveSha256": hashlib.sha256(b"armsx2-source").hexdigest(),
            },
            "toolchain": {
                "androidAbi": "arm64-v8a",
                "androidApi": 26,
                "ndkVersion": "27.0.12077973",
                "cmakeVersion": "3.31.6-g38307f9",
                "ninjaVersion": "1.12.1",
            },
            "dependencies": armsx2_dependencies,
            "patches": armsx2_patches,
        }
        azahar_lock = {
            "core": {
                "repository": "https://github.com/example/azahar",
                "commit": commits["azahar"],
                "archiveSha256": hashlib.sha256(b"azahar-source").hexdigest(),
            },
            "releaseArtifact": {
                "url": ("https://github.com/azahar-emu/azahar/releases/download/"
                        "2125.1.3/azahar-libretro-android-arm64-v8a-2125.1.3.zip"),
                "archiveSha256": MODULE.AZAHAR_RELEASE_ARCHIVE_SHA256,
                "member": "azahar_libretro.so",
                "memberSha256": hashlib.sha256(payloads["azahar"]).hexdigest(),
            },
            "dependencies": [],
            "patches": [],
        }
        dolphin_lock = {
            "core": {
                "repository": "https://github.com/example/dolphin",
                "commit": commits["dolphin"],
                "archiveSha256": hashlib.sha256(b"dolphin-source").hexdigest(),
            },
            "cmakeOptions": {
                "normalizedByRemovingSection": ".note.gnu.build-id",
                "normalizedArtifactSha256": hashlib.sha256(
                    payloads["dolphin"]).hexdigest(),
            },
        }
        scummvm_artifact_sha = hashlib.sha256(payloads["scummvm"]).hexdigest()
        scummvm_lock = {
            "core": {
                "repository": "https://github.com/example/scummvm",
                "commit": commits["scummvm"],
                "archiveSha256": hashlib.sha256(b"scummvm-source").hexdigest(),
            },
            "artifact": {
                "sha256": scummvm_artifact_sha,
                "firstCleanBuildSha256": scummvm_artifact_sha,
                "secondCleanBuildSha256": scummvm_artifact_sha,
                "ptLoadAlignment": "0x4000",
            },
        }
        scummvm_audit = {
            "coreArtifactSha256": scummvm_artifact_sha,
            "externalObjectCount": 337,
            "components": [{"id": f"component-{index}"} for index in range(15)],
            "embeddedComponents": [
                {"id": f"embedded-{index}"} for index in range(4)
            ],
        }
        scummvm_content = {"fixtures": [{
            "sha256": scummvm_fixture_sha,
            "distributionPolicy": "official-download-only",
            "bundleInApk": False,
        }]}
        scummvm_compliance = {
            "artifact": {"sha256": scummvm_artifact_sha},
            "externalObjectCount": 337,
            "objects": [{"path": f"object-{index:03}.o"} for index in range(337)],
        }
        sbom = {
            "spdxVersion": "SPDX-2.3",
            "dataLicense": "CC0-1.0",
            "packages": [{
                "name": engine_id,
                "versionInfo": commits[engine_id],
                "checksums": [{"algorithm": "SHA256", "checksumValue":
                               hashlib.sha256(payload).hexdigest()}],
            } for engine_id, payload in payloads.items()] + [{
                "SPDXID": f"SPDXRef-play-patch-{index}",
                "name": patch["path"],
                "checksums": [{"algorithm": "SHA256",
                               "checksumValue": patch["sha256"]}],
            } for index, patch in enumerate(play_patches)],
            "relationships": [{
                "spdxElementId": f"SPDXRef-play-patch-{index}",
                "relationshipType": "PATCH_FOR",
                "relatedSpdxElement": "SPDXRef-play-source",
            } for index in range(6)],
        }
        sbom["packages"].extend({
            "name": dependency["path"],
            "checksums": [{"algorithm": "SHA256",
                           "checksumValue": dependency["archiveSha256"]}],
        } for dependency in flycast_dependencies)
        sbom["packages"].extend({
            "name": dependency["path"],
            "checksums": [{"algorithm": "SHA256",
                           "checksumValue": dependency["archiveSha256"]}],
        } for dependency in armsx2_dependencies)
        for index, patch in enumerate(armsx2_patches):
            patch_id = f"SPDXRef-armsx2-patch-{index}"
            sbom["packages"].append({
                "SPDXID": patch_id,
                "name": patch["path"],
                "checksums": [{"algorithm": "SHA256",
                               "checksumValue": patch["sha256"]}],
            })
            sbom["relationships"].append({
                "spdxElementId": patch_id,
                "relationshipType": "PATCH_FOR",
                "relatedSpdxElement": "SPDXRef-armsx2-source",
            })
        applewin_patch_id = "SPDXRef-applewin-patch"
        sbom["packages"].append({
            "SPDXID": applewin_patch_id,
            "name": applewin_patch["path"],
            "checksums": [{"algorithm": "SHA256",
                           "checksumValue": applewin_patch["sha256"]}],
        })
        sbom["relationships"].append({
            "spdxElementId": applewin_patch_id,
            "relationshipType": "PATCH_FOR",
            "relatedSpdxElement": "SPDXRef-applewin-source",
        })
        for component in puae_components:
            sbom["packages"].append({
                "name": component["id"],
                "checksums": [{"algorithm": "SHA256",
                               "checksumValue": component["evidenceSha256"]}],
            })
        azahar_archive_id = "SPDXRef-azahar-release-archive"
        azahar_binary_id = "SPDXRef-azahar-binary"
        for package in sbom["packages"]:
            if package.get("name") == "azahar":
                package["name"] = "liblucent_core_azahar.so"
                package["SPDXID"] = azahar_binary_id
                break
        sbom["packages"].append({
            "SPDXID": azahar_archive_id,
            "name": "azahar-libretro-android-arm64-v8a-2125.1.3.zip",
            "downloadLocation": azahar_lock["releaseArtifact"]["url"],
            "checksums": [{
                "algorithm": "SHA256",
                "checksumValue": azahar_lock["releaseArtifact"]["archiveSha256"],
            }],
        })
        sbom["relationships"].append({
            "spdxElementId": azahar_binary_id,
            "relationshipType": "EXTRACTED_FROM",
            "relatedSpdxElement": azahar_archive_id,
        })
        with zipfile.ZipFile(path, "w") as apk:
            apk.writestr("lib/arm64-v8a/liblucent_core_armsx2_16k.so", ps2_variant_payload)
            sbom["packages"].append({
                "name": ps2_variant["fileName"], "versionInfo": commits["armsx2"],
                "checksums": [{"algorithm": "SHA256", "checksumValue": ps2_variant["sha256"]}],
            })
            for engine_id, payload in payloads.items():
                normalized = engine_id.replace("-", "_")
                apk.writestr(f"lib/arm64-v8a/liblucent_core_{normalized}.so", payload)
            apk.writestr(MODULE.REGISTRY, json.dumps(registry))
            apk.writestr(MODULE.OPT_IN, json.dumps(opt_in))
            apk.writestr(MODULE.ARTIFACTS, json.dumps(artifacts))
            apk.writestr(MODULE.SBOM, json.dumps(sbom))
            apk.writestr(MODULE.PLAY_LOCK, json.dumps(play_lock))
            apk.writestr(MODULE.FLYCAST_LOCK, json.dumps(flycast_lock))
            apk.writestr(MODULE.ARMSX2_LOCK, json.dumps(armsx2_lock))
            apk.writestr(MODULE.AZAHAR_LOCK, json.dumps(azahar_lock))
            apk.writestr(MODULE.DOLPHIN_LOCK, json.dumps(dolphin_lock))
            apk.writestr(MODULE.APPLEWIN_LOCK, json.dumps(applewin_lock))
            apk.writestr(MODULE.APPLEWIN_FIRMWARE_POLICY, applewin_policy_bytes)
            apk.writestr(MODULE.PUAE_LOCK, json.dumps(puae_lock))
            apk.writestr(MODULE.PUAE_FIRMWARE_POLICY, puae_policy_bytes)
            apk.writestr(MODULE.PUAE_AUDIT, puae_audit_bytes)
            apk.writestr(MODULE.PUAE_CONTENT, puae_content_bytes)
            apk.writestr(MODULE.PUAE_NOTICES, puae_notices)
            apk.writestr(MODULE.SCUMMVM_LOCK, json.dumps(scummvm_lock))
            apk.writestr(MODULE.SCUMMVM_AUDIT, json.dumps(scummvm_audit))
            apk.writestr(MODULE.SCUMMVM_CONTENT, json.dumps(scummvm_content))
            apk.writestr(MODULE.SCUMMVM_COMPLIANCE_MANIFEST,
                         json.dumps(scummvm_compliance))
            apk.writestr(MODULE.SCUMMVM_NOTICES, "ScummVM qualification notices")
            for license_path in MODULE.LICENSES.values():
                apk.writestr(license_path, "qualification license")
            for asset_root, files in runtime_assets.items():
                for relative, payload in files.items():
                    apk.writestr(f"assets/{asset_root}/{relative}", payload)
        return path

    def test_complete_fail_closed_payload_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual([], MODULE.verify(self.make_apk(Path(directory))))

    def test_core_drift_and_auto_selection_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_apk(Path(directory), auto_select=True)
            errors = MODULE.verify(path)
            self.assertTrue(any("fail-closed" in error for error in errors))
            replacement = Path(directory) / "drift.apk"
            with zipfile.ZipFile(path) as source, zipfile.ZipFile(replacement, "w") as out:
                for item in source.infolist():
                    payload = b"drift" if item.filename == \
                        "lib/arm64-v8a/liblucent_core_ppsspp.so" \
                        else source.read(item.filename)
                    out.writestr(item, payload)
            errors = MODULE.verify(replacement)
            self.assertTrue(any("hash" in error for error in errors))

    def test_unqualified_normal_library_route_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_apk(Path(directory))
            replacement = Path(directory) / "route-leak.apk"
            with zipfile.ZipFile(path) as source, zipfile.ZipFile(replacement, "w") as out:
                for item in source.infolist():
                    payload = source.read(item.filename)
                    if item.filename == MODULE.OPT_IN:
                        opt_in = json.loads(payload)
                        next(row for row in opt_in["engines"]
                             if row["id"] == "beetle-saturn")[
                                 "libraryRouteSystems"] = ["saturn"]
                        payload = json.dumps(opt_in).encode()
                    out.writestr(item, payload)
            self.assertTrue(any("exact qualified subset" in error
                                for error in MODULE.verify(replacement)))

    def test_missing_runtime_assets_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_apk(Path(directory))
            replacement = Path(directory) / "no-assets.apk"
            with zipfile.ZipFile(path) as source, zipfile.ZipFile(replacement, "w") as out:
                for item in source.infolist():
                    if not item.filename.startswith(
                            "assets/phase2-system/ppsspp/PPSSPP/"):
                        out.writestr(item, source.read(item.filename))
            self.assertTrue(any("runtime asset payload" in error
                                for error in MODULE.verify(replacement)))

    def test_tampered_armsx2_lock_or_missing_sbom_binding_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_apk(Path(directory))
            tampered = Path(directory) / "tampered-armsx2-lock.apk"
            with zipfile.ZipFile(path) as source, zipfile.ZipFile(tampered, "w") as out:
                for item in source.infolist():
                    payload = source.read(item.filename)
                    if item.filename == MODULE.ARMSX2_LOCK:
                        lock = json.loads(payload)
                        lock["core"]["commit"] = "f" * 40
                        payload = json.dumps(lock).encode()
                    out.writestr(item, payload)
            self.assertTrue(any("core identity" in error
                                for error in MODULE.verify(tampered)))

            unbound = Path(directory) / "unbound-armsx2-patch.apk"
            with zipfile.ZipFile(path) as source, zipfile.ZipFile(unbound, "w") as out:
                for item in source.infolist():
                    payload = source.read(item.filename)
                    if item.filename == MODULE.SBOM:
                        sbom = json.loads(payload)
                        sbom["relationships"] = [
                            row for row in sbom["relationships"]
                            if row.get("spdxElementId") != "SPDXRef-armsx2-patch-1"
                        ]
                        payload = json.dumps(sbom).encode()
                    out.writestr(item, payload)
            self.assertTrue(any("bind ARMSX2 patch" in error
                                for error in MODULE.verify(unbound)))

    def test_ps2_frame_clock_patch_cannot_be_omitted_or_relabelled(self):
        current_lock = json.loads((ROOT / "engines/armsx2-source-lock.json").read_text())
        self.assertEqual(current_lock["patches"], MODULE.ARMSX2_PATCHES)
        mutations = [
            MODULE.ARMSX2_PATCHES[:1],
            [MODULE.ARMSX2_PATCHES[0]] * 2,
            list(reversed(MODULE.ARMSX2_PATCHES)),
            [MODULE.ARMSX2_PATCHES[0], dict(MODULE.ARMSX2_PATCHES[1], sha256="0"*64)],
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_apk(Path(directory))
            self.assertEqual([], MODULE.verify(path))
            for index, patches in enumerate(mutations):
                with self.subTest(patches=patches):
                    altered = Path(directory) / f"old-clock-{index}.apk"
                    with zipfile.ZipFile(path) as source, zipfile.ZipFile(altered, "w") as out:
                        for item in source.infolist():
                            payload = source.read(item.filename)
                            if item.filename == MODULE.ARMSX2_LOCK:
                                lock = json.loads(payload)
                                lock["patches"] = patches
                                payload = json.dumps(lock).encode()
                            out.writestr(item, payload)
                    self.assertTrue(any("exact integration and frame-clock" in error
                                        for error in MODULE.verify(altered)))

    def test_tampered_or_missing_armsx2_runtime_asset_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_apk(Path(directory))
            replacement = Path(directory) / "no-patches.apk"
            with zipfile.ZipFile(path) as source, zipfile.ZipFile(replacement, "w") as out:
                for item in source.infolist():
                    if not item.filename.endswith("pcsx2/resources/patches.zip"):
                        out.writestr(item, source.read(item.filename))
            errors = MODULE.verify(replacement)
            self.assertTrue(any("runtime asset revision" in error for error in errors))
            self.assertTrue(any("required runtime asset" in error for error in errors))

    def test_source_built_azahar_requires_matching_build_and_git_closure(self):
        with tempfile.TemporaryDirectory() as directory:
            original = self.make_apk(Path(directory))
            with zipfile.ZipFile(original) as archive:
                data = {name: archive.read(name) for name in archive.namelist()}
            lock = json.loads(data[MODULE.AZAHAR_LOCK])
            sha = lock.pop('releaseArtifact')['memberSha256']
            lock['sourceBuild'] = dict(artifactSha256=sha, androidAbi='arm64-v8a', androidApi=23,
                ndkVersion='27.0.12077973', linkAlignment=16384, builtinKeyblob=False)
            lock['patches'] = [dict(path='engines/patches/azahar-android-strerror.patch', sha256='1' * 64)]
            lock['dependencies'] = [dict(path=f'externals/pin-{i}', repository='https://github.com/example/dependency',
                commit=f'{i + 1:040x}', gitTreeSha1=f'{i + 53:040x}') for i in range(52)]
            sbom = json.loads(data[MODULE.SBOM])
            source_id = 'SPDXRef-azahar-local-source'
            sbom['packages'].append(dict(name='Azahar source', SPDXID=source_id))
            for relation in sbom['relationships']:
                if relation['spdxElementId'] == 'SPDXRef-azahar-binary' and relation['relationshipType'] == 'EXTRACTED_FROM':
                    relation.update(relationshipType='GENERATED_FROM', relatedSpdxElement=source_id)
            for i, dep in enumerate(lock['dependencies']):
                dep_id = f'SPDXRef-azahar-dep-{i}'
                sbom['packages'].append(dict(name=dep['path'], SPDXID=dep_id, versionInfo=dep['commit'],
                    checksums=[dict(algorithm='SHA1', checksumValue=dep['gitTreeSha1'])]))
                sbom['relationships'].append(dict(spdxElementId=source_id, relationshipType='DEPENDS_ON', relatedSpdxElement=dep_id))
            def package(changed_lock, changed_sbom):
                target = Path(directory) / 'source.apk'
                with zipfile.ZipFile(target, 'w') as archive:
                    for name, value in data.items():
                        if name == MODULE.AZAHAR_LOCK: value = json.dumps(changed_lock).encode()
                        if name == MODULE.SBOM: value = json.dumps(changed_sbom).encode()
                        archive.writestr(name, value)
                return MODULE.verify(target)
            self.assertEqual([], package(lock, sbom))
            for key, value in [('artifactSha256', '0' * 64), ('linkAlignment', 4096), ('builtinKeyblob', True)]:
                altered = json.loads(json.dumps(lock))
                altered['sourceBuild'][key] = value
                self.assertTrue(any('source-build artifact/profile' in x for x in package(altered, sbom)))
            altered = json.loads(json.dumps(lock))
            altered['dependencies'].pop()
            self.assertTrue(any('gitlink closure' in x for x in package(altered, sbom)))
            altered_sbom = json.loads(json.dumps(sbom))
            altered_sbom['relationships'] = [r for r in sbom['relationships'] if r['relatedSpdxElement'] != 'SPDXRef-azahar-dep-0']
            self.assertTrue(any('Azahar Git dependency' in x for x in package(lock, altered_sbom)))
            altered_sbom = json.loads(json.dumps(sbom))
            for row in altered_sbom['relationships']:
                if row['spdxElementId'] == 'SPDXRef-azahar-binary' and row['relationshipType'] == 'GENERATED_FROM':
                    row['relationshipType'] = 'EXTRACTED_FROM'
            self.assertTrue(any('source-built' in x for x in package(lock, altered_sbom)))

    def test_tampered_azahar_release_provenance_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_apk(Path(directory))
            replacement = Path(directory) / "tampered-azahar.apk"
            with zipfile.ZipFile(path) as source, zipfile.ZipFile(replacement, "w") as out:
                for item in source.infolist():
                    payload = source.read(item.filename)
                    if item.filename == MODULE.AZAHAR_LOCK:
                        lock = json.loads(payload)
                        lock["releaseArtifact"]["archiveSha256"] = "0" * 64
                        payload = json.dumps(lock).encode()
                    out.writestr(item, payload)
            errors = MODULE.verify(replacement)
            self.assertTrue(any("Azahar official release artifact" in error
                                for error in errors))

            unbound = Path(directory) / "unbound-azahar.apk"
            with zipfile.ZipFile(path) as source, zipfile.ZipFile(unbound, "w") as out:
                for item in source.infolist():
                    payload = source.read(item.filename)
                    if item.filename == MODULE.SBOM:
                        sbom = json.loads(payload)
                        sbom["relationships"] = [
                            row for row in sbom["relationships"]
                            if row.get("relationshipType") != "EXTRACTED_FROM"
                        ]
                        payload = json.dumps(sbom).encode()
                    out.writestr(item, payload)
            self.assertTrue(any("bind Azahar core" in error
                                for error in MODULE.verify(unbound)))


if __name__ == "__main__":
    unittest.main()
