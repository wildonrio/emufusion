#!/usr/bin/env python3
"""Fail-closed policy validation for Lucent's Phase 4 console-coverage research set.

Phase 4 closes the console-coverage gaps left by Phases 1-3. Every row is
research only: all ten qualification gates stay false and ``shipped`` stays
false until an engine is separately qualified.

The checks that matter most here are the ones Phase 1 got wrong. A candidate
engine may not be recorded unless every atom of its SPDX expression is on the
allowlist for a GPL-3.0-only combined distribution, and a Phase 4 row may not
quietly steal a system that an earlier phase already owns.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "engines" / "phase4-registry.schema.json"
REGISTRY_PATH = ROOT / "engines" / "phase4-registry.json"
BUILD_SCRIPT = ROOT / "unified-android" / "build.sh"
PRIOR_REGISTRIES = {
    1: ROOT / "engines" / "registry.json",
    2: ROOT / "engines" / "phase2-registry.json",
    3: ROOT / "engines" / "phase3-registry.json",
}

GATES = {
    "source", "license", "dependencies", "androidArm64", "firmware",
    "legalContent", "renderer", "state", "performance", "device",
}

CATEGORIES = {
    "misaudited", "blocked-replacement", "unpackaged", "unadvertised", "missing",
}

# Only these categories may claim a system an earlier phase already owns, and
# only by naming the exact earlier engine that owns it.
INCUMBENT_CATEGORIES = {"misaudited", "blocked-replacement", "unpackaged"}

# Systems Phase 4 exists to close. Kept here so the registry cannot silently
# grow or shrink its own scope. pcenginecd left the set when Phase 1's
# beetle-pce-fast row gained the system-card firmware contract and began
# advertising it (engines/registry.json).
PHASE_FOUR_SYSTEMS = {
    "atari2600", "atari5200", "atari800", "segacd", "sega32x", "virtualboy",
    "c64", "msx", "amstradcpc", "atarist", "odyssey2", "colecovision",
    "intellivision", "atarilynx", "wonderswan", "neogeopocket",
    "vectrex", "pcfx", "cdi", "x68000",
}

# Inbound licences that may be combined into Lucent's GPL-3.0-only
# distribution. Anything not on this list is rejected, including every
# LicenseRef-* placeholder: "unknown" is not "compatible".
COMPATIBLE_LICENSES = {
    "GPL-3.0-only", "GPL-3.0-or-later", "GPL-2.0-or-later",
    "LGPL-2.0-or-later", "LGPL-2.1-only", "LGPL-2.1-or-later",
    "LGPL-3.0-only", "LGPL-3.0-or-later",
    "MIT", "MIT-0", "X11", "ISC", "BSD-2-Clause", "BSD-3-Clause",
    "Zlib", "libpng-2.0", "curl", "Apache-2.0", "MPL-2.0",
    "Unlicense", "CC0-1.0", "FSFAP",
    # The FSF licence list records both of these as free and GPL-compatible.
    # Only the original, vague Artistic-1.0 is refused, in the denylist below.
    "ClArtistic", "Artistic-2.0",
}

# Named for clear error messages. The allowlist above is the real gate; this
# set only exists so the common mistakes report why they are refused.
INCOMPATIBLE_LICENSES = {
    "GPL-2.0-only": "GPL-2.0-only cannot be relicensed to GPLv3",
    "GPL-1.0-only": "GPL-1.0-only cannot be relicensed to GPLv3",
    "Artistic-1.0": "the original Artistic License is GPL-incompatible",
    "Artistic-1.0-Perl": "the original Artistic License is GPL-incompatible",
    "CC-BY-NC-4.0": "non-commercial terms are GPL-incompatible",
    "SSPL-1.0": "SSPL is not a free software licence",
    "BUSL-1.1": "BUSL is not a free software licence",
    "NOASSERTION": "an unresolved licence is never a compatible candidate",
}

ALLOWED_EXCEPTIONS = {
    "LLVM-exception", "Classpath-exception-2.0", "GCC-exception-3.1",
    "Autoconf-exception-3.0", "Bison-exception-2.2",
}

_OPERATOR = re.compile(r"\s+(?:AND|OR)\s+")


def _license_atoms(expression: str) -> list[str]:
    """Split an SPDX expression into its individual licence terms."""
    flattened = expression.replace("(", " ").replace(")", " ").strip()
    return [part.strip() for part in _OPERATOR.split(flattened) if part.strip()]


def check_license_expression(expression: str, *,
                             allow_audited_refs: bool = False) -> list[str]:
    """Return a reason list; empty means every atom is GPL-3.0-only-compatible.

    ``LicenseRef-*`` atoms name a custom licence that SPDX cannot describe, so
    they are refused by default. They are only tolerated when the caller has
    already confirmed a Lucent licence audit that concluded compatibility, which
    is how an engine such as beetle-cygne carries its permissive V30MZ term.
    """
    problems: list[str] = []
    atoms = _license_atoms(expression)
    if not atoms:
        return ["licence expression is empty"]
    for atom in atoms:
        term, _, exception = atom.partition(" WITH ")
        term, exception = term.strip(), exception.strip()
        if exception and exception not in ALLOWED_EXCEPTIONS:
            problems.append(f"licence exception {exception!r} is not recognised")
        if term in INCOMPATIBLE_LICENSES:
            problems.append(f"{term} is incompatible: {INCOMPATIBLE_LICENSES[term]}")
        elif term.startswith("LicenseRef-"):
            if not allow_audited_refs:
                problems.append(
                    f"{term} is an unresolved custom licence and needs a cited "
                    f"Lucent audit before it can be a compatible candidate")
        elif term not in COMPATIBLE_LICENSES:
            problems.append(
                f"{term} is not on the GPL-3.0-only inbound allowlist")
    return problems


def audit_clears_custom_terms(reference: str, root: Path | None = None) -> list[str]:
    """Confirm a cited Lucent licence audit exists and concluded compatibility."""
    base = root or ROOT
    if not reference.startswith("engines/audits/") or not reference.endswith(".json"):
        return [f"auditRef {reference!r} must name a file under engines/audits/"]
    path = base / reference
    try:
        audit = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read cited licence audit {reference}: {exc}"]
    conclusion = str(audit.get("aggregateConclusion") or audit.get("conclusion") or "")
    verdict = conclusion.lower().lstrip()
    # The verdict is the opening clause. "Blocked." fails; "Not blocked." does
    # not, so a substring search for "blocked" would reject the wrong audits.
    if verdict.startswith("blocked") or "compatible" not in verdict:
        return [f"cited licence audit {reference} does not conclude compatibility"]
    return []


def load_prior_ownership(paths: dict[int, Path] | None = None) -> dict[str, tuple[int, str, bool]]:
    """Map every system an earlier phase already claims to (phase, engine, blocked)."""
    owners: dict[str, tuple[int, str, bool]] = {}
    for phase, path in sorted((paths or PRIOR_REGISTRIES).items()):
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data.get("engines", []):
            status = str(row.get("status", ""))
            gate = str((row.get("license") or {}).get("distributionGate", ""))
            blocked = gate == "blocked" or status.endswith("-blocked")
            for system in row.get("systems", []):
                # An unblocked owner always wins the record for a system, so a
                # system with any compatible owner is never reported as blocked.
                previous = owners.get(system)
                if previous is None or (previous[2] and not blocked):
                    owners[system] = (phase, str(row.get("id", "")), blocked)
    return owners


def load_prior_engines(paths: dict[int, Path] | None = None) -> dict[str, dict]:
    """Map every earlier-phase engine id to its phase, systems, block state and SPDX."""
    engines: dict[str, dict] = {}
    for phase, path in sorted((paths or PRIOR_REGISTRIES).items()):
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data.get("engines", []):
            status = str(row.get("status", ""))
            license_block = row.get("license") or {}
            gate = str(license_block.get("distributionGate", ""))
            engines[str(row.get("id", ""))] = {
                "phase": phase,
                "systems": set(row.get("systems", [])),
                "blocked": gate == "blocked" or status.endswith("-blocked"),
                "spdx": license_block.get("spdx"),
                "repository": (row.get("source") or {}).get("repository"),
            }
    return engines


def load_staged_cores(path: Path | None = None) -> set[str]:
    """Every engine id that unified-android/build.sh actually stages into the APK."""
    text = (path or BUILD_SCRIPT).read_text(encoding="utf-8")
    staged: set[str] = set()
    for line in text.splitlines():
        match = re.search(r"^\s*for \w+ in ([^;]+); do\s*$", line)
        if match and "core" in line:
            staged.update(match.group(1).split())
    return staged


def validate(
    data: object,
    *,
    schema: object | None = None,
    prior_owners: dict[str, tuple[int, str, bool]] | None = None,
    prior_engines: dict[str, tuple[int, set[str], bool]] | None = None,
    staged_cores: set[str] | None = None,
) -> list[str]:
    """Return every policy and schema error; an empty list means the set is valid."""
    errors: list[str] = []

    if schema is None:
        try:
            schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator.check_schema(schema)
        except (OSError, json.JSONDecodeError, jsonschema.SchemaError) as exc:
            return [f"cannot read Phase 4 schema: {exc}"]
    validator = jsonschema.Draft202012Validator(schema)
    for problem in sorted(validator.iter_errors(data), key=lambda item: list(item.path)):
        location = ".".join(str(part) for part in problem.path) or "$"
        # A failed oneOf echoes the whole offending row, which buries the real
        # errors in terminal output. Keep the message, lose the wall of JSON.
        message = problem.message
        if len(message) > 200:
            message = message[:200] + "... (truncated)"
        errors.append(f"schema {location}: {message}")

    if not isinstance(data, dict):
        return errors + ["Phase 4 registry must be an object"]

    if data.get("schemaVersion") != 1:
        errors.append("schemaVersion must be 1")
    if data.get("phase") != 4:
        errors.append("phase must be 4")
    if data.get("oneAppContract") is not True:
        errors.append("oneAppContract must be true")
    if data.get("distributionLicense") != "GPL-3.0-only":
        errors.append("distributionLicense must remain GPL-3.0-only")

    policy = data.get("licensePolicy") or {}
    if set(policy.get("compatible") or []) != COMPATIBLE_LICENSES:
        errors.append("licensePolicy.compatible drifted from the validator allowlist")
    if set(policy.get("incompatible") or []) != set(INCOMPATIBLE_LICENSES):
        errors.append("licensePolicy.incompatible drifted from the validator denylist")

    if set(data.get("categories") or {}) != CATEGORIES:
        errors.append("categories must describe exactly the four Phase 4 categories")

    expected = data.get("expectedSystems")
    if not isinstance(expected, list) or set(expected) != PHASE_FOUR_SYSTEMS:
        errors.append("expectedSystems must exactly match the Phase 4 gap list")

    engines = data.get("engines")
    if not isinstance(engines, list):
        return errors + ["engines must be an array"]

    if prior_owners is None:
        try:
            prior_owners = load_prior_ownership()
        except (OSError, json.JSONDecodeError) as exc:
            return errors + [f"cannot read earlier-phase registries: {exc}"]
    if prior_engines is None:
        try:
            prior_engines = load_prior_engines()
        except (OSError, json.JSONDecodeError) as exc:
            return errors + [f"cannot read earlier-phase registries: {exc}"]
    if staged_cores is None:
        try:
            staged_cores = load_staged_cores()
        except OSError as exc:
            return errors + [f"cannot read the packaging script: {exc}"]

    seen_ids: set[str] = set()
    covered: set[str] = set()

    for row in engines:
        if not isinstance(row, dict):
            errors.append("every engine row must be an object")
            continue
        engine = str(row.get("id", ""))
        if engine in seen_ids:
            errors.append(f"duplicate engine id {engine}")
        seen_ids.add(engine)

        category = row.get("category")
        if category not in CATEGORIES:
            errors.append(f"{engine}: unknown category {category!r}")

        gates = row.get("gates") or {}
        if set(gates) != GATES:
            errors.append(f"{engine}: gate set must match the Lucent qualification gates")
        # The general release rule, stated independently of the research pin so a
        # future promotion still cannot ship on unfinished evidence.
        if row.get("shipped") is True and not all(
                gates.get(name) is True for name in GATES):
            errors.append(f"{engine}: shipped is true while a qualification gate is false")
        if row.get("status") == "research":
            if any(value is not False for value in gates.values()):
                errors.append(f"{engine}: research gates must fail closed")
            if row.get("shipped") is not False:
                errors.append(f"{engine}: research rows must remain unshipped")
        else:
            errors.append(f"{engine}: Phase 4 rows must remain status research")

        has_candidate = isinstance(row.get("candidate"), dict)
        has_none = isinstance(row.get("noCompatibleCandidate"), dict)
        if has_candidate == has_none:
            errors.append(
                f"{engine}: needs exactly one of candidate or noCompatibleCandidate")
        if has_candidate:
            candidate = row["candidate"]
            declared = candidate.get("license") or {}
            expression = str(declared.get("spdx", ""))
            audit_ref = declared.get("auditRef")
            audited = False
            if audit_ref is not None:
                audit_problems = audit_clears_custom_terms(str(audit_ref))
                for reason in audit_problems:
                    errors.append(f"{engine}: {reason}")
                audited = not audit_problems
            for reason in check_license_expression(
                    expression, allow_audited_refs=audited):
                errors.append(f"{engine}: candidate licence {expression!r}: {reason}")

        prior = row.get("priorEngine")
        if prior is not None:
            if prior not in prior_engines:
                errors.append(f"{engine}: priorEngine {prior} is not in any earlier registry")
            else:
                record = prior_engines[prior]
                if row.get("priorPhase") != record["phase"]:
                    errors.append(
                        f"{engine}: priorPhase must be {record['phase']} to match {prior}")
                if category in {"blocked-replacement", "misaudited"} and not record["blocked"]:
                    errors.append(
                        f"{engine}: {prior} is not blocked, so this is not a replacement row")
                if category == "unpackaged":
                    if record["blocked"]:
                        errors.append(
                            f"{engine}: {prior} is licence-blocked, so it is not merely unpackaged")
                    if prior in staged_cores:
                        errors.append(
                            f"{engine}: {prior} is already staged by unified-android/build.sh")
                # A misaudit claim must quote the exact wrong SPDX that the
                # earlier registry still records, so the correction is checkable.
                if category == "misaudited" and has_candidate:
                    corrects = ((row["candidate"].get("license") or {})
                                .get("correctsRecordedSpdx"))
                    if corrects is None:
                        errors.append(
                            f"{engine}: a misaudited row must record correctsRecordedSpdx")
                    elif corrects != record["spdx"]:
                        errors.append(
                            f"{engine}: correctsRecordedSpdx {corrects!r} does not match "
                            f"the {record['spdx']!r} recorded for {prior}")
        elif category != "missing":
            errors.append(f"{engine}: category {category} requires priorEngine")

        if category == "missing" and prior is not None:
            errors.append(f"{engine}: a missing-engine row must not name a priorEngine")

        for system in row.get("systems", []):
            if system in covered:
                errors.append(f"duplicate system owner {system}")
            covered.add(system)
            owner = prior_owners.get(system)
            if owner is None:
                if category in INCUMBENT_CATEGORIES:
                    errors.append(
                        f"{engine}: {system} is not owned by any earlier phase, "
                        f"so category {category} is wrong")
                continue
            owner_phase, owner_id, _ = owner
            if category not in INCUMBENT_CATEGORIES:
                errors.append(
                    f"{engine}: {system} is already owned by phase {owner_phase} "
                    f"engine {owner_id}; only a row that explicitly names it as "
                    f"priorEngine may claim it")
            elif prior != owner_id:
                errors.append(
                    f"{engine}: {system} is owned by {owner_id}, but this row "
                    f"declares priorEngine {prior}")

    if covered != PHASE_FOUR_SYSTEMS:
        missing = ", ".join(sorted(PHASE_FOUR_SYSTEMS - covered)) or "none"
        extra = ", ".join(sorted(covered - PHASE_FOUR_SYSTEMS)) or "none"
        errors.append(f"coverage mismatch (missing: {missing}; unexpected: {extra})")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default=REGISTRY_PATH, type=Path)
    args = parser.parse_args()
    try:
        data = json.loads(args.path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot read Phase 4 registry: {exc}", file=sys.stderr)
        return 1
    errors = validate(data)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Phase 4 registry valid: {args.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
