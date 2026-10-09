#!/usr/bin/env python3
"""Generate a deterministic SPDX 2.3 SBOM for a Phase 2 qualification APK."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _spdx_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"SPDXRef-{prefix}-{digest}"


def _checksum(value: str) -> list[dict[str, str]]:
    return [{"algorithm": "SHA256", "checksumValue": value}]


def generate(registry: dict, lock: dict, artifacts: dict) -> dict:
    """Generate one SBOM for every exact Phase 2 core in the APK.

    The historic API accepted PPSSPP's lock directly. Keep accepting that
    shape so older callers and tests remain stable; the build now supplies a
    mapping keyed by engine id for multi-core qualification packages.
    """
    locks = {"ppsspp": lock} if "dependencies" in lock else lock
    by_engine = {row["id"]: row for row in registry["engines"]}
    packaged = sorted(artifacts["artifacts"], key=lambda row: row["engineId"])
    if not packaged:
        raise ValueError("Phase 2 qualification SBOM requires an artifact")
    epoch = max([int(value["sourceDateEpoch"]) for value in locks.values()] or [0])
    created = datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    identity = hashlib.sha256(_canonical({
        "artifacts": packaged,
        "dependencies": locks,
    })).hexdigest()

    app_id = "SPDXRef-Lucent-Phase2-Qualification"
    packages = [{
        "SPDXID": app_id,
        "name": "Lucent Phase 2 qualification payload",
        "versionInfo": identity[:12],
        "downloadLocation": "NOASSERTION",
        "filesAnalyzed": False,
        "licenseConcluded": "NOASSERTION",
        "licenseDeclared": "GPL-3.0-only",
        "copyrightText": "NOASSERTION",
        "comment": "Qualification-only payload; not a shipped engine release.",
    }]
    relationships = []
    for artifact in packaged:
        engine_id = artifact["engineId"]
        engine = by_engine[engine_id]
        source = engine["source"]
        core_id = _spdx_id(f"{engine_id}-source", source["commit"])
        artifact_id = _spdx_id(f"{engine_id}-binary", artifact["sha256"])
        packages.extend([{
            "SPDXID": core_id,
            "name": f"{engine['displayName']} source",
            "versionInfo": source.get("tag", source["commit"]),
            "downloadLocation": source["archive"],
            "filesAnalyzed": False,
            "checksums": _checksum(source["archiveSha256"]),
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": engine["license"]["spdx"],
            "copyrightText": "NOASSERTION",
            "sourceInfo": f"Exact upstream commit {source['commit']}",
        }, {
            "SPDXID": artifact_id,
            "name": artifact["fileName"],
            "versionInfo": source["commit"],
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "checksums": _checksum(artifact["sha256"]),
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": engine["license"]["spdx"],
            "copyrightText": "NOASSERTION",
            "comment": "Exact Android ARM64 qualification artifact embedded in the APK.",
        }])
        relationships.append(
            {"spdxElementId": app_id, "relationshipType": "CONTAINS",
             "relatedSpdxElement": artifact_id}
        )
        for variant in artifact.get("pageSizeVariants", []):
            variant_id = _spdx_id(f"{engine_id}-binary", variant["sha256"])
            packages.append({
                "SPDXID": variant_id, "name": variant["fileName"],
                "versionInfo": source["commit"], "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False, "checksums": _checksum(variant["sha256"]),
                "licenseConcluded": "NOASSERTION", "licenseDeclared": engine["license"]["spdx"],
                "copyrightText": "NOASSERTION",
                "comment": f"Bundled {variant['hostPageSize']}-byte host-page variant; qualification only.",
            })
            relationships.extend([
                {"spdxElementId": app_id, "relationshipType": "CONTAINS", "relatedSpdxElement": variant_id},
                {"spdxElementId": variant_id, "relationshipType": "GENERATED_FROM", "relatedSpdxElement": core_id},
            ])
        release_artifact = locks.get(engine_id, {}).get("releaseArtifact")
        if release_artifact:
            # A checksum-locked upstream binary is not a locally reproduced
            # source build. Model the ZIP it was extracted from without
            # claiming that EmuFusion proved its source-to-binary derivation.
            release_id = _spdx_id(
                f"{engine_id}-release-archive", release_artifact["archiveSha256"])
            packages.append({
                "SPDXID": release_id,
                "name": Path(release_artifact["url"]).name,
                "versionInfo": source.get("tag", source["commit"]),
                "downloadLocation": release_artifact["url"],
                "filesAnalyzed": False,
                "checksums": _checksum(release_artifact["archiveSha256"]),
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": engine["license"]["spdx"],
                "copyrightText": "NOASSERTION",
                "comment": "Checksum-pinned official upstream release archive; no upstream signature or local source reproduction is claimed.",
            })
            relationships.append({
                "spdxElementId": artifact_id,
                "relationshipType": "EXTRACTED_FROM",
                "relatedSpdxElement": release_id,
            })
        else:
            relationships.append({
                "spdxElementId": artifact_id,
                "relationshipType": "GENERATED_FROM",
                "relatedSpdxElement": core_id,
            })
        for dependency in locks.get(engine_id, {}).get("dependencies", []):
            dependency_id = _spdx_id(
                f"{engine_id}-dependency", dependency["path"]
            )
            git_tree = dependency.get("gitTreeSha1")
            packages.append({
                "SPDXID": dependency_id,
                "name": dependency["path"],
                "versionInfo": dependency["commit"],
                "downloadLocation": (f"git+{dependency['repository']}@{dependency['commit']}" if git_tree else
                    f"{dependency['repository'].rstrip('/')}/archive/"
                    f"{dependency['commit']}.tar.gz"
                ),
                "filesAnalyzed": False,
                "checksums": ([{"algorithm": "SHA1", "checksumValue": git_tree}] if git_tree else
                              _checksum(dependency["archiveSha256"])),
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": dependency.get("licenseDeclared", "NOASSERTION"),
                "copyrightText": "NOASSERTION",
                "sourceInfo": (f"Staged at {dependency['path']}; checksum identifies the exact Git tree object, not a downloadable archive."
                               if git_tree else f"Staged at {dependency['path']}"),
            })
            relationships.append({
                "spdxElementId": core_id,
                "relationshipType": "DEPENDS_ON",
                "relatedSpdxElement": dependency_id,
            })
        for component in locks.get(engine_id, {}).get("embeddedComponents", []):
            component_id = _spdx_id(
                f"{engine_id}-embedded", component["id"] + ":" + component["path"]
            )
            packages.append({
                "SPDXID": component_id,
                "name": component["id"],
                "versionInfo": source["commit"],
                "downloadLocation": source["archive"],
                "filesAnalyzed": False,
                "checksums": _checksum(component["evidenceSha256"]),
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": component.get("licenseDeclared", "NOASSERTION"),
                "copyrightText": "NOASSERTION",
                "sourceInfo": (
                    f"Vendored inside exact source archive at {component['path']}; "
                    "checksum identifies the recorded license/evidence file."
                ),
            })
            relationships.append({
                "spdxElementId": core_id,
                "relationshipType": "CONTAINS",
                "relatedSpdxElement": component_id,
            })
        for patch in locks.get(engine_id, {}).get("patches", []):
            patch_id = _spdx_id(f"{engine_id}-patch", patch["path"])
            packages.append({
                "SPDXID": patch_id,
                "name": patch["path"],
                "versionInfo": patch["sha256"][:12],
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "checksums": _checksum(patch["sha256"]),
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": "NOASSERTION",
                "copyrightText": "NOASSERTION",
                "sourceInfo": "Exact reviewed integration patch applied by the locked recipe",
            })
            relationships.extend([{
                "spdxElementId": patch_id,
                "relationshipType": "PATCH_FOR",
                "relatedSpdxElement": core_id,
            }, {
                "spdxElementId": artifact_id,
                "relationshipType": "GENERATED_FROM",
                "relatedSpdxElement": patch_id,
            }])

    document = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "Lucent Phase 2 qualification SBOM",
        "documentNamespace": (
            "https://github.com/wildonrio/emufusion/"
            f"spdx/phase2/{identity}"
        ),
        "creationInfo": {
            "created": created,
            "creators": ["Tool: Lucent-generate-phase2-sbom"],
            "licenseListVersion": "3.27",
        },
        "documentDescribes": [app_id],
        "packages": packages,
        "relationships": relationships,
    }
    if any("LicenseRef-Public-Domain-libco" in str(package.get("licenseDeclared", ""))
           for package in packages):
        document["hasExtractedLicensingInfos"] = [{
            "licenseId": "LicenseRef-Public-Domain-libco",
            "extractedText": "The pinned libretro-common libco/libco.c source declares libco public domain.",
            "name": "libco public-domain declaration",
            "seeAlsos": ["https://github.com/libretro/libretro-common"],
        }]
    if any("LicenseRef-Public-Domain-7zip-LZMA-SDK" in
           str(package.get("licenseDeclared", "")) for package in packages):
        document.setdefault("hasExtractedLicensingInfos", []).append({
            "licenseId": "LicenseRef-Public-Domain-7zip-LZMA-SDK",
            "extractedText": "The pinned 7-Zip LZMA SDK source headers declare the selected sources public domain.",
            "name": "7-Zip LZMA SDK public-domain declaration",
            "seeAlsos": ["https://www.7-zip.org/sdk.html"],
        })
    return document


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--dependency-lock", action="append", required=True,
                        help="ENGINE_ID=PATH (legacy PATH means ppsspp)")
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    locks = {}
    for value in args.dependency_lock:
        engine_id, separator, path = value.partition("=")
        if not separator:
            engine_id, path = "ppsspp", value
        locks[engine_id] = json.loads(Path(path).read_text(encoding="utf-8"))
    result = generate(json.loads(args.registry.read_text(encoding="utf-8")),
                      locks,
                      json.loads(args.artifacts.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
