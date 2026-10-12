#!/usr/bin/env python3
"""Verify ScummVM's actual external object closure and emit exact notices."""

import argparse
import hashlib
import json
import pathlib
import shutil
import sys


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fail(message):
    raise SystemExit("ScummVM compliance gate: " + message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=pathlib.Path)
    parser.add_argument("--objects", required=True, type=pathlib.Path)
    parser.add_argument("--artifact", required=True, type=pathlib.Path)
    parser.add_argument("--audit", required=True, type=pathlib.Path)
    parser.add_argument("--repository", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()

    audit = json.loads(args.audit.read_text())
    if sha256(args.artifact) != audit["coreArtifactSha256"]:
        fail("core artifact does not match the audited binary")

    prefix = "deps/"
    objects = []
    counts = {}
    for path in sorted(args.objects.rglob("*.o")):
        normalized = path.as_posix()
        marker = normalized.find(prefix)
        if marker < 0:
            continue
        relative = normalized[marker + len(prefix):]
        parts = relative.split("/")
        if len(parts) < 3 or parts[0] not in ("libretro-common", "libretro-deps"):
            fail("unrecognized external object path: " + relative)
        component = "libretro-common" if parts[0] == "libretro-common" else parts[1]
        counts[component] = counts.get(component, 0) + 1
        objects.append({"path": relative, "sha256": sha256(path)})

    expected = {entry["id"]: entry["objectCount"] for entry in audit["components"]}
    if len(objects) != audit["externalObjectCount"]:
        fail("expected %d external objects, found %d" %
             (audit["externalObjectCount"], len(objects)))
    if counts != expected:
        fail("linked component counts differ: expected %r, found %r" %
             (expected, counts))

    all_object_paths = [path.as_posix() for path in args.objects.rglob("*.o")]
    for component in audit.get("embeddedComponents", []):
        needle = "/" + component["objectPrefix"].strip("/") + "/"
        found = sum(1 for path in all_object_paths if needle in path)
        if found != component["objectCount"]:
            fail("embedded component %s expected %d objects, found %d" %
                 (component["id"], component["objectCount"], found))

    evidence = []
    for component in audit["components"]:
        records = [component] + component.get("additionalEvidence", [])
        for index, record in enumerate(records):
            if "evidencePath" in record:
                path = args.source / record["evidencePath"]
            else:
                path = args.repository / record["repositoryEvidencePath"]
            if not path.is_file():
                fail("missing license evidence for %s: %s" % (component["id"], path))
            actual = sha256(path)
            if actual != record["evidenceSha256"]:
                fail("license evidence changed for %s" % component["id"])
            evidence.append((component, index, path))
    for component in audit.get("embeddedComponents", []):
        path = args.source / component["evidencePath"]
        if not path.is_file() or sha256(path) != component["evidenceSha256"]:
            fail("embedded license evidence changed for %s" % component["id"])
        evidence.append((component, 0, path))

    if args.output.exists():
        shutil.rmtree(args.output)
    licenses = args.output / "licenses"
    licenses.mkdir(parents=True)
    shutil.copy2(args.source / "COPYING", licenses / "ScummVM-GPL-3.0.txt")
    shutil.copy2(args.source / "COPYRIGHT", licenses / "ScummVM-COPYRIGHT.txt")
    shutil.copytree(args.source / "LICENSES", licenses / "ScummVM-LICENSES")
    for component, index, path in evidence:
        suffix = path.suffix if path.suffix else ".txt"
        label = component["id"] + ("" if index == 0 else "-additional-%d" % index)
        shutil.copy2(path, licenses / (label + suffix))

    manifest = {
        "schemaVersion": 1,
        "artifact": {"path": args.artifact.name, "sha256": sha256(args.artifact)},
        "externalObjectCount": len(objects),
        "components": audit["components"],
        "embeddedComponents": audit.get("embeddedComponents", []),
        "objects": objects,
    }
    manifest_path = args.output / "scummvm-linked-objects.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    lines = [
        "ScummVM lite-profile core: exact linked-component notices",
        "",
        "Artifact SHA-256: " + manifest["artifact"]["sha256"],
        "External object files audited: " + str(len(objects)),
        "ScummVM and EmuFusion core changes: GPL-3.0-or-later.",
        "Complete corresponding pinned source/build scripts are supplied by EmuFusion's source offer.",
        "",
        "Linked external components:",
    ]
    for component in audit["components"]:
        lines.append("- %s: %s (%d objects; evidence SHA-256 %s)" % (
            component["id"], component["spdx"], component["objectCount"],
            component["evidenceSha256"]))
    lines.append("")
    lines.append("Linked embedded subcomponents within the ScummVM source tree:")
    for component in audit.get("embeddedComponents", []):
        lines.append("- %s: %s (%d objects; evidence SHA-256 %s)" % (
            component["id"], component["spdx"], component["objectCount"],
            component["evidenceSha256"]))
    lines.extend([
        "",
        "Full and component-specific license evidence is in licenses/.",
        "The exact object inventory and hashes are in scummvm-linked-objects.json.",
        "No unlisted external component is accepted by this generator.",
    ])
    (args.output / "SCUMMVM-CORE-NOTICES.txt").write_text("\n".join(lines) + "\n")
    print(json.dumps({"artifactSha256": manifest["artifact"]["sha256"],
                      "externalObjects": len(objects),
                      "components": len(expected),
                      "embeddedComponents": len(audit.get("embeddedComponents", []))},
                     sort_keys=True))


if __name__ == "__main__":
    main()
