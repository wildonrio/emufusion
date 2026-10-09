#!/usr/bin/env python3
"""Generate deterministic Phase 1 qualification provenance and notices.

This is deliberately derived from the release-gated registry and the exact
libraries staged for an APK.  It does not turn a qualification core into an
approved component; it makes an accidentally or deliberately packaged core
auditable without trusting a hand-maintained notice list.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def generate(registry_path: Path, opt_in_path: Path, library_dir: Path) -> tuple[dict, dict, str]:
    registry = load_json(registry_path)
    opt_in = load_json(opt_in_path)
    by_id = {
        row["id"]: row for row in registry.get("engines", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    requested = opt_in.get("engines")
    if not isinstance(requested, list) or not requested:
        raise ValueError("qualification opt-in must contain engines")

    packages: list[dict] = []
    artifacts: list[dict] = []
    notices = [
        "Lucent Phase 1 qualification core notices",
        "",
        "These components are qualification-only and remain subject to the",
        "release gates recorded in engines/registry.json. Inclusion here is",
        "not evidence that a component is approved or shipped.",
        "",
    ]
    seen: set[str] = set()
    for item in requested:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("qualification engine entries must have an id")
        engine_id = item["id"]
        if engine_id in seen:
            raise ValueError(f"duplicate qualification engine: {engine_id}")
        seen.add(engine_id)
        row = by_id.get(engine_id)
        if row is None:
            raise ValueError(f"qualification engine is absent from registry: {engine_id}")
        if row.get("phase") != 1 or row.get("shipped") is not False:
            raise ValueError(f"qualification engine is not an unshipped Phase 1 row: {engine_id}")
        source = row.get("source") or {}
        license_info = row.get("license") or {}
        declared_license = license_info.get("spdx")
        if (not isinstance(declared_license, str) or not declared_license.strip() or
                declared_license == "NOASSERTION"):
            raise ValueError(
                f"qualification license conclusion is absent: {engine_id}"
            )
        archive_sha = source.get("archiveSha256")
        if not isinstance(archive_sha, str) or not SHA256_RE.fullmatch(archive_sha):
            raise ValueError(f"qualification source archive is not SHA-256 pinned: {engine_id}")
        if item.get("commit") != source.get("commit"):
            raise ValueError(f"qualification commit does not match registry: {engine_id}")
        library_name = item.get("libraryName")
        if not isinstance(library_name, str):
            raise ValueError(f"qualification library is missing: {engine_id}")
        library = library_dir / library_name
        if not library.is_file():
            raise ValueError(f"qualification library is absent: {library}")
        artifact_sha = sha256(library)
        spdx_id = "SPDXRef-Package-" + re.sub(r"[^A-Za-z0-9.-]", "-", engine_id)
        package = {
            "SPDXID": spdx_id,
            "name": row.get("displayName", engine_id),
            "versionInfo": source["commit"],
            "downloadLocation": source["archive"],
            "filesAnalyzed": False,
            "checksums": [{"algorithm": "SHA256", "checksumValue": archive_sha}],
            # Phase 1 qualification requires a configuration-specific source
            # and dependency audit before an engine can enter the opt-in set.
            # Therefore the reviewed SPDX expression is both the declared and
            # concluded license for this exact packaged configuration.
            "licenseConcluded": declared_license,
            "licenseDeclared": declared_license,
            "copyrightText": "NOASSERTION",
            "comment": (
                "Qualification-only; shipping status is false. "
                + str(license_info.get("auditNote", ""))
            ).strip(),
        }
        packages.append(package)
        artifacts.append({
            "engineId": engine_id,
            "fileName": library_name,
            "sha256": artifact_sha,
            "sourceArchiveSha256": archive_sha,
            "sourceCommit": source["commit"],
            "sourceRepository": source["repository"],
            "licenseDeclared": declared_license,
            "distributionGate": license_info.get("distributionGate", "blocked"),
            "buildRecipe": (row.get("build") or {}).get("recipe"),
            "qualificationOnly": True,
            "shipped": False,
        })
        notices.extend([
            row.get("displayName", engine_id),
            f"  Engine id: {engine_id}",
            f"  Project: {source['repository']}",
            f"  Exact source commit: {source['commit']}",
            f"  Source archive SHA-256: {archive_sha}",
            f"  Packaged library SHA-256: {artifact_sha}",
            f"  Declared license: {declared_license}",
            f"  Build recipe: {(row.get('build') or {}).get('recipe') or 'not recorded'}",
            f"  Release status: qualification-only; shipped=false",
            f"  Outstanding audit: {license_info.get('auditNote', 'not recorded')}",
            "",
        ])

    artifacts.sort(key=lambda row: row["engineId"])
    packages.sort(key=lambda row: row["SPDXID"])
    registry_digest = hashlib.sha256(registry_path.read_bytes()).hexdigest()
    manifest = {
        "schemaVersion": 1,
        "qualificationOnly": True,
        "registrySha256": registry_digest,
        "artifacts": artifacts,
    }
    namespace_seed = hashlib.sha256(canonical_json(manifest)).hexdigest()
    sbom = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "Lucent-Phase1-qualification-cores",
        "documentNamespace": f"https://github.com/wildonrio/emufusion/spdx/{namespace_seed}",
        "creationInfo": {
            "created": "2026-08-06T00:00:00Z",
            "creators": ["Tool: Lucent-generate_phase1_compliance_bundle"],
        },
        "documentDescribes": [row["SPDXID"] for row in packages],
        "packages": packages,
    }
    return manifest, sbom, "\n".join(notices).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--opt-in", required=True, type=Path)
    parser.add_argument("--library-dir", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--sbom", required=True, type=Path)
    parser.add_argument("--notice", required=True, type=Path)
    args = parser.parse_args()
    manifest, sbom, notice = generate(args.registry, args.opt_in, args.library_dir)
    for path, payload in (
        (args.manifest, canonical_json(manifest)),
        (args.sbom, canonical_json(sbom)),
        (args.notice, notice.encode("utf-8")),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
