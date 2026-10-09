#!/usr/bin/env python3
"""Stage the exact notice-complete RIFE qualification payload into an APK tree.

This script is deliberately not a product-enablement switch.  It accepts only
the host-verified quarantined benchmark artifact and the locked, numerically
identified v4.6 model.  The emitted manifest keeps product routing false.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import zipfile


NATIVE_ENTRY = "lib/arm64-v8a/librife_benchmark.so"
NOTICE_ENTRIES = {
    "assets/RIFE_NCNN_VULKAN_LICENSE.txt": "RIFE_NCNN_VULKAN_LICENSE.txt",
    "assets/NCNN_AND_THIRD_PARTY_LICENSES.txt": "NCNN_AND_THIRD_PARTY_LICENSES.txt",
    "assets/GLSLANG_LICENSES.txt": "GLSLANG_LICENSES.txt",
}
PRACTICAL_LICENSE = "licenses/Practical-RIFE-v4.6-LICENSE"
MODEL_RELATIVE_ROOT = Path("source/rife-ncnn-vulkan/models/rife-v4.6")
EXPECTED_PURPOSE = "quarantined-benchmark-and-qualification"
EXPECTED_RIFE_COMMIT = "a7532fc3f9f8f008cd6eecd6f2ffe2a9698e0cf7"
EXPECTED_PRACTICAL_COMMIT = "f6b5132517695127bdb5d5a8c3727e719f0fda22"
EXPECTED_NCNN_COMMIT = "e54f7b1f88434e1d844ea0551b880a1cfb079ce1"
EXPECTED_MODEL_IDENTITIES = {
    "flownet.param": (16_532,
        "724569596bcd1e7b9fa50455c604777ebed99746d2ef40aa86e31b5725f1053c"),
    "flownet.bin": (10_614_320,
        "f334ed2260149ce0188a6dcf049844e8b0cdd912e01cbcfb63553157d2508958"),
}
EXPECTED_NOTICE_HASHES = {
    "assets/RIFE_NCNN_VULKAN_LICENSE.txt":
        "a73beab18143600af0b10c6050a953ec233775ce31c2bf3373a794db535329fd",
    "assets/NCNN_AND_THIRD_PARTY_LICENSES.txt":
        "7c974bac98848df46be1af5bdaa3c3c9c01f6082a90f55caeb7f60c6208aa255",
    "assets/GLSLANG_LICENSES.txt":
        "17e70c676e1521ff3e4686f04a2053d93a7e28a33be8de7ec37ab0ff72feb677",
}
EXPECTED_PRACTICAL_LICENSE = (
    1_062, "7932fb49341512b959b1744a6d9cbb39e5a1ec89da438a34d0454d5d8df9fecd")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_file(path: Path, expected_bytes: int, expected_sha: str) -> None:
    if (not path.is_file() or path.is_symlink() or
            path.stat().st_size != expected_bytes or sha256(path) != expected_sha):
        raise RuntimeError(f"locked payload identity mismatch: {path}")


def validate_lock(lock: dict[str, object]) -> None:
    components = lock.get("components", {})
    provenance = lock.get("provenanceGate", {})
    rife = components.get("rifeNcnnVulkan", {})
    practical = components.get("practicalRifeV46Original", {})
    ncnn = components.get("ncnnAndroidBenchmark", {})
    model_files = components.get("rifeV46Model", {}).get("files", [])
    locked_models = {
        Path(str(item.get("path", ""))).name:
            (int(item.get("bytes", -1)), str(item.get("sha256", "")))
        for item in model_files
    }
    practical_license = practical.get("license", {})
    if (lock.get("schemaVersion") != 2 or
            lock.get("purpose") != EXPECTED_PURPOSE or
            lock.get("productIntegrationAllowed") is not False or
            rife.get("commit") != EXPECTED_RIFE_COMMIT or
            practical.get("commit") != EXPECTED_PRACTICAL_COMMIT or
            ncnn.get("commit") != EXPECTED_NCNN_COMMIT or
            provenance.get("failClosed") is not True or
            provenance.get("originalModelReleaseExplicitlyMITLicensed") is not True or
            provenance.get("convertedNcnnNumericalIdentityVerified") is not True or
            provenance.get("redistributeModelInApk") is not True or
            provenance.get("qualificationApkRedistributionApproved") is not True or
            provenance.get("routeProductFramesToProvider") is not False or
            locked_models != EXPECTED_MODEL_IDENTITIES or
            (int(practical_license.get("bytes", -1)),
             str(practical_license.get("sha256", ""))) !=
                    EXPECTED_PRACTICAL_LICENSE):
        raise RuntimeError("RIFE qualification redistribution lock is not approved")
    if notice_hashes(lock) != EXPECTED_NOTICE_HASHES:
        raise RuntimeError("RIFE qualification notice identities changed")


def notice_hashes(lock: dict[str, object]) -> dict[str, str]:
    components = lock["components"]
    return {
        "assets/RIFE_NCNN_VULKAN_LICENSE.txt":
            components["rifeNcnnVulkan"]["license"]["sha256"],
        "assets/NCNN_AND_THIRD_PARTY_LICENSES.txt":
            components["ncnnAndroidBenchmark"]["license"]["sha256"],
        "assets/GLSLANG_LICENSES.txt":
            components["ncnnAndroidBenchmark"]["submodules"]["glslang"]
            ["license"]["sha256"],
    }


def model_specs(lock: dict[str, object]) -> list[dict[str, object]]:
    files = lock["components"]["rifeV46Model"]["files"]
    if [Path(str(item["path"])).name for item in files] != [
            "flownet.param", "flownet.bin"]:
        raise RuntimeError("locked RIFE model inventory is not the exact two-file v4.6 graph")
    return files


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(payload)
        stream.flush()
    temporary.replace(path)


def stage(args: argparse.Namespace) -> dict[str, object]:
    lock = json.loads(args.lock.read_text(encoding="utf-8"))
    validate_lock(lock)
    host = json.loads(args.host_record.read_text(encoding="utf-8"))
    if (host.get("schemaVersion") != 1 or
            host.get("status") != "HOST_STATIC_PASS_DEVICE_UNTESTED" or
            host.get("productIntegrationAllowed") is not False or
            host.get("modelPackaged") is not False or
            host.get("appApk", {}).get("sha256") != sha256(args.app_apk) or
            not str(host.get("nativeLibrary", {}).get("buildId", ""))):
        raise RuntimeError("host-verified RIFE APK record is absent or does not match")

    expected_notices = notice_hashes(lock)
    with zipfile.ZipFile(args.app_apk) as archive:
        corrupt = archive.testzip()
        if corrupt is not None:
            raise RuntimeError(f"RIFE benchmark APK CRC failure: {corrupt}")
        native = archive.read(NATIVE_ENTRY)
        if sha256_bytes(native) != host.get("nativeLibrary", {}).get("sha256"):
            raise RuntimeError("RIFE native library does not match host verification record")
        notices: dict[str, bytes] = {}
        for entry, expected_sha in expected_notices.items():
            payload = archive.read(entry)
            if sha256_bytes(payload) != expected_sha:
                raise RuntimeError(f"RIFE notice identity mismatch: {entry}")
            notices[NOTICE_ENTRIES[entry]] = payload

    practical_spec = lock["components"]["practicalRifeV46Original"]["license"]
    practical_path = args.cache_dir / PRACTICAL_LICENSE
    require_file(
        practical_path, int(practical_spec["bytes"]), str(practical_spec["sha256"]))
    notices["PRACTICAL_RIFE_V46_LICENSE.txt"] = practical_path.read_bytes()

    decoded = args.decoded_apk
    atomic_write(decoded / NATIVE_ENTRY, native)
    staged_models: dict[str, dict[str, object]] = {}
    for spec in model_specs(lock):
        name = Path(str(spec["path"])).name
        source = args.cache_dir / MODEL_RELATIVE_ROOT / name
        require_file(source, int(spec["bytes"]), str(spec["sha256"]))
        target = decoded / "assets/framegen/rife-v4.6" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        staged_models[name] = {
            "bytes": target.stat().st_size,
            "sha256": sha256(target),
        }
    for name, payload in notices.items():
        atomic_write(decoded / "assets/framegen/rife-v4.6/licenses" / name, payload)

    manifest = {
        "schemaVersion": 1,
        "kind": "rife-v4.6-framegen-qualification-only",
        "productIntegrationAllowed": False,
        "routeProductFramesToProvider": False,
        "rifeCommit": EXPECTED_RIFE_COMMIT,
        "practicalRifeCommit": EXPECTED_PRACTICAL_COMMIT,
        "ncnnCommit": EXPECTED_NCNN_COMMIT,
        "nativeLibrary": {
            "path": NATIVE_ENTRY,
            "bytes": len(native),
            "sha256": sha256_bytes(native),
            "buildId": host.get("nativeLibrary", {}).get("buildId"),
        },
        "models": staged_models,
        "noticeSha256": {
            name: sha256_bytes(payload) for name, payload in sorted(notices.items())
        },
        "hostVerificationRecordSha256": sha256(args.host_record),
    }
    serialized = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    atomic_write(
        decoded / "assets/framegen/rife-v4.6/qualification-manifest.json", serialized)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--app-apk", required=True, type=Path)
    parser.add_argument("--host-record", required=True, type=Path)
    parser.add_argument("--decoded-apk", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    manifest = stage(parse_args())
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
