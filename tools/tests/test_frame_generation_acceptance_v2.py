"""Validate the September 4 acceptance baseline, not emulator performance.

Run from the repository root with:
    python3 -m unittest tools.tests.test_frame_generation_acceptance_v2

This revision is deliberately an initial UNVERIFIED snapshot. It is not a
permanent ban on acceptance: after new immutable evidence exists under this
standard, promotion requires a deliberate revision of the initial-state
assertions below and evidence validation for the proposed status. Historical
summaries alone cannot promote this baseline. These tests validate inventory
and policy consistency; they do not certify emulator performance.
"""

import copy
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "unified-android/tools/frame-generation-acceptance-v2.json"
MATRIX = ROOT / "unified-android/tools/runtime-acceptance-matrix.json"
CONSOLE_ORDER = (
    "switch", "wiiu", "n3ds", "wii", "ps3", "psp", "nds", "gc", "gba",
    "ps2", "dreamcast", "gbc", "n64", "psx", "snes", "gamegear", "gb",
    "megadrive", "nes",
)
BACKENDS = {"direct", "builtin", "lsfgPrivate"}
EVIDENCE_GROUPS = {
    "identity", "physicalPresentation", "guestClockAudio", "generatedContent",
    "adaptation", "geometryAndOled",
}
ROUTES = {
    "libretro-software", "libretro-gles", "libretro-vulkan",
    "libretro-vulkan-or-gles", "native-adapter-vulkan",
}


def validate_manifest(manifest, matrix, root=ROOT):
    """Raise ValueError for missing scope, unsupported claims or policy drift."""
    def require(condition, message):
        if not condition:
            raise ValueError(message)

    require(manifest.get("schemaVersion") == 2, "schemaVersion must be 2")
    require(manifest.get("acceptanceStandard") == "exact-2x-2026-09-04",
            "wrong acceptance standard")
    require(manifest.get("status") == "UNVERIFIED", "baseline cannot claim PASS")
    status_policy = manifest.get("statusPolicy", {})
    require(status_policy.get("kind") == "initial-unverified-snapshot",
            "this validator applies to the initial snapshot only")
    require(bool(status_policy.get("advancement")) and
            bool(status_policy.get("sourceChanges")),
            "status advancement and source/device separation must be documented")
    require(manifest.get("goalDocument") == "docs/FRAME-GENERATION-GOAL-2026-09-04.md",
            "goal document is required")
    require(manifest.get("runtimeMatrix") == str(MATRIX.relative_to(ROOT)),
            "runtime matrix reference is required")
    scope = manifest.get("scope", {})
    require(scope.get("consoleCount") == 19, "scope must contain 19 consoles")
    require(scope.get("order") == "newest-first-commercial-hardware-release",
            "newest-first order is required")
    for field in ("primaryPanel", "secondaryPanelDirectGeometryAndInput",
                  "secondaryPanelGeneration", "historicalEvidence", "deviceScope"):
        require(isinstance(scope.get(field), str) and scope[field].strip(),
                f"missing scope field: {field}")
    require(scope["primaryPanel"] == "required", "primary panel must be required")
    require(scope["secondaryPanelGeneration"] == "optional",
            "secondary generation must remain optional")

    policy = manifest.get("policy", {})
    require(policy.get("allowedGenerationMultipliers") == [1, 2],
            "only 1x and 2x are permitted")
    require(policy.get("maximumSyntheticFramesPerAdjacentChangingPair") == 1,
            "only one synthetic midpoint is permitted")
    require(policy.get("syntheticTimeFraction") == 0.5, "midpoint must be at 0.5")
    require(policy.get("maximumClockCorrectionRelativeToDeclared") == 0.0075,
            "declared-clock correction limit must be 0.75 percent")
    require(policy.get("overload") ==
            "preserve-guest-speed; reduce-rendering-cost-or-disable-generation",
            "overload must preserve guest speed")
    for field in ("outputCadence", "unsupportedCadence", "sourceIdentity",
                  "unsafeMidpoint", "direct", "aspect", "lsfgPrivate"):
        require(isinstance(policy.get(field), str) and policy[field].strip(),
                f"missing policy field: {field}")
    for refresh in (60, 120):
        examples = policy.get(f"fixed{refresh}HzExamples", {})
        require(set(examples) == {"20", "30", "40", "60"},
                "canonical rate examples are required")
        for source_text, output in examples.items():
            source = int(source_text)
            allowed = [rate for rate in (source, 2 * source) if refresh % rate == 0]
            expected = max(allowed) if allowed else None
            require(output == expected,
                    f"nonuniform or non-maximal example: {source}->{output}@{refresh}")

    requirements = manifest.get("backendRequirements", {})
    require(requirements.get("direct") == "required", "Direct evidence is required")
    for backend in ("builtin", "lsfgPrivate"):
        require(requirements.get(backend) == "required-when-supported",
                f"missing backend gate: {backend}")
    require(requirements.get("independentEvidence") is True,
            "backends need independent evidence")
    require(bool(requirements.get("unsupportedBackend")),
            "unsupported backends need explicit handling")
    evidence = manifest.get("requiredEvidence", {})
    require(set(evidence) == EVIDENCE_GROUPS, "all evidence groups are required")
    for group, rows in evidence.items():
        require(isinstance(rows, list) and len(rows) >= 3 and
                all(isinstance(row, str) and row.strip() for row in rows),
                f"incomplete evidence requirements: {group}")

    findings = manifest.get("sourceFindings", [])
    require(isinstance(findings, list) and findings, "source findings are required")
    finding_ids = [item.get("id") for item in findings]
    require(all(finding_ids) and len(set(finding_ids)) == len(finding_ids),
            "source finding IDs must be unique")
    for finding in findings:
        require(bool(finding.get("summary")), "finding summary is required")
        require(bool(finding.get("sources")), "finding sources are required")
        for source in finding["sources"]:
            path = source.get("path")
            require(isinstance(path, str) and bool(path), "source path is required")
            resolved = (root / path).resolve()
            require(resolved.is_relative_to(root.resolve()) and resolved.is_file(),
                    f"source must be an existing repository file: {path}")
            line = source.get("line")
            require(isinstance(line, int) and not isinstance(line, bool) and line > 0,
                    f"positive source line is required: {path}")

    systems = manifest.get("systems", [])
    additional = manifest.get("additionalPlatforms", [])
    require([row.get("id") for row in systems] == list(CONSOLE_ORDER),
            "console inventory must be unique and newest first")
    require([row.get("id") for row in additional] == ["windows"],
            "Windows/DOS is an additional platform, not a twentieth console")
    require(additional[0].get("console") is False,
            "Windows/DOS must explicitly not count as a console")
    registry = {row["folder"]: row for row in matrix["systems"]}
    entries = systems + additional
    ids = [row["id"] for row in entries]
    require(len(set(ids)) == len(ids) and set(ids) == set(registry),
            "inventory must match the runtime registry without duplicates")
    for entry in entries:
        system_id = entry["id"]
        require(entry.get("status") == "UNVERIFIED",
                f"{system_id}: historical results cannot claim acceptance")
        require(entry.get("backendStatus") ==
                {backend: "UNVERIFIED" for backend in BACKENDS},
                f"{system_id}: all backend statuses must begin UNVERIFIED")
        require(entry.get("engines") == registry[system_id]["engines"],
                f"{system_id}: engine inventory differs from runtime registry")
        require(entry.get("dualScreen") is bool(registry[system_id].get("dualScreen")),
                f"{system_id}: dual-screen flag differs from runtime registry")
        require(entry.get("route") in ROUTES, f"{system_id}: unknown route")
        for field in ("name", "clockControl"):
            require(isinstance(entry.get(field), str) and entry[field].strip(),
                    f"{system_id}: missing {field}")
        require(isinstance(entry.get("blockers"), list) and entry["blockers"] and
                all(isinstance(item, str) and item.strip() for item in entry["blockers"]),
                f"{system_id}: concrete blockers are required")
        references = entry.get("findingRefs", [])
        require(isinstance(references, list) and references and
                set(references).issubset(finding_ids),
                f"{system_id}: valid source finding references are required")


class FrameGenerationAcceptanceV2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.matrix = json.loads(MATRIX.read_text(encoding="utf-8"))

    def test_manifest_matches_new_scope_and_runtime_inventory(self):
        validate_manifest(self.manifest, self.matrix)

    def test_historical_pass_cannot_promote_a_system_or_backend(self):
        for location in ("system", "backend"):
            with self.subTest(location=location):
                candidate = copy.deepcopy(self.manifest)
                row = candidate["systems"][0]
                if location == "system":
                    row["status"] = "PASS"
                else:
                    row["backendStatus"]["lsfgPrivate"] = "PASS"
                with self.assertRaises(ValueError):
                    validate_manifest(candidate, self.matrix)

    def test_unrealizable_40_to_80_on_120_is_rejected(self):
        candidate = copy.deepcopy(self.manifest)
        candidate["policy"]["fixed120HzExamples"]["40"] = 80
        with self.assertRaisesRegex(ValueError, "nonuniform"):
            validate_manifest(candidate, self.matrix)

    def test_extra_synthetic_frame_and_large_slowdown_are_rejected(self):
        changes = (("allowedGenerationMultipliers", [1, 2, 3]),
                   ("maximumSyntheticFramesPerAdjacentChangingPair", 2),
                   ("maximumClockCorrectionRelativeToDeclared", 0.34),
                   ("overload", "slow-guest-to-lower-tier"))
        for field, value in changes:
            with self.subTest(field=field):
                candidate = copy.deepcopy(self.manifest)
                candidate["policy"][field] = value
                with self.assertRaises(ValueError):
                    validate_manifest(candidate, self.matrix)

    def test_order_duplicates_registry_drift_and_missing_proof_are_rejected(self):
        for mutation in ("order", "duplicate", "engine", "evidence", "windows"):
            with self.subTest(mutation=mutation):
                candidate = copy.deepcopy(self.manifest)
                if mutation == "order":
                    candidate["systems"].reverse()
                elif mutation == "duplicate":
                    candidate["systems"][1] = candidate["systems"][0]
                elif mutation == "engine":
                    candidate["systems"][0]["engines"] = ["external"]
                elif mutation == "evidence":
                    del candidate["requiredEvidence"]["generatedContent"]
                else:
                    candidate["systems"].append(candidate["additionalPlatforms"].pop())
                with self.assertRaises(ValueError):
                    validate_manifest(candidate, self.matrix)


if __name__ == "__main__":
    unittest.main()
