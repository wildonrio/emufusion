"""Fail-closed tests for the Phase 4 console-coverage research registry."""

import copy
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location(
    "phase4", ROOT / "tools/validate_phase4_registry.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

REGISTRY_PATH = ROOT / "engines/phase4-registry.json"
SCHEMA_PATH = ROOT / "engines/phase4-registry.schema.json"


class PhaseFourRegistryTest(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        self.rows = {row["id"]: row for row in self.data["engines"]}

    # --- the checked-in registry -------------------------------------------

    def test_checked_in_registry_is_fail_closed_and_complete(self):
        self.assertEqual([], MODULE.validate(self.data))

    def test_registry_parses_and_declares_its_own_schema(self):
        self.assertEqual("./phase4-registry.schema.json", self.data["$schema"])
        self.assertEqual(4, self.data["phase"])
        self.assertEqual("GPL-3.0-only", self.data["distributionLicense"])

    def test_schema_is_a_valid_draft_2020_12_schema_matching_the_registry(self):
        import jsonschema
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(schema)
        self.assertEqual([], list(validator.iter_errors(self.data)))

    def test_every_row_records_a_candidate_or_an_explicit_absence(self):
        for engine_id, row in self.rows.items():
            with self.subTest(engine=engine_id):
                has_candidate = "candidate" in row
                has_absence = "noCompatibleCandidate" in row
                self.assertNotEqual(
                    has_candidate, has_absence,
                    "a row must record exactly one of candidate/noCompatibleCandidate")
                if has_candidate:
                    candidate = row["candidate"]
                    self.assertTrue(candidate["repository"].startswith("https://"))
                    declared = candidate["license"]
                    audit_ref = declared.get("auditRef")
                    audited = bool(audit_ref) and not MODULE.audit_clears_custom_terms(
                        audit_ref)
                    self.assertEqual(
                        [], MODULE.check_license_expression(
                            declared["spdx"], allow_audited_refs=audited))
                else:
                    self.assertIn(
                        row["noCompatibleCandidate"]["productDecision"],
                        {"drop-system", "needs-product-decision",
                         "defer-pending-upstream", "user-supplied-firmware-only"})
                    self.assertTrue(
                        row["noCompatibleCandidate"]["rejectedAlternatives"],
                        "an absent candidate must show what was evaluated")

    def test_every_row_is_research_with_all_gates_closed(self):
        for engine_id, row in self.rows.items():
            with self.subTest(engine=engine_id):
                self.assertEqual("research", row["status"])
                self.assertFalse(row["shipped"])
                self.assertEqual(MODULE.GATES, set(row["gates"]))
                self.assertFalse(any(row["gates"].values()))

    def test_every_declared_category_is_exercised(self):
        self.assertEqual(
            MODULE.CATEGORIES,
            {row["category"] for row in self.data["engines"]})
        self.assertEqual(MODULE.CATEGORIES, set(self.data["categories"]))

    # --- policy the validator must enforce ---------------------------------

    def test_shipped_with_closed_gates_is_rejected(self):
        data = copy.deepcopy(self.data)
        data["engines"][0]["shipped"] = True
        errors = MODULE.validate(data)
        self.assertTrue(any("shipped is true while a qualification gate is false"
                            in error for error in errors), errors)

    def test_an_open_gate_alone_is_rejected(self):
        data = copy.deepcopy(self.data)
        data["engines"][0]["gates"]["license"] = True
        errors = MODULE.validate(data)
        self.assertTrue(any("gates must fail closed" in error for error in errors),
                        errors)

    def test_duplicate_engine_ids_are_rejected(self):
        data = copy.deepcopy(self.data)
        clone = copy.deepcopy(data["engines"][0])
        clone["systems"] = ["duplicateprobe"]
        data["engines"].append(clone)
        errors = MODULE.validate(data)
        self.assertTrue(any("duplicate engine id" in error for error in errors),
                        errors)

    def test_duplicate_systems_are_rejected(self):
        data = copy.deepcopy(self.data)
        clone = copy.deepcopy(data["engines"][0])
        clone["id"] = clone["id"] + "-clone"
        data["engines"].append(clone)
        errors = MODULE.validate(data)
        self.assertTrue(any("duplicate system owner" in error for error in errors),
                        errors)

    def test_a_row_needs_exactly_one_of_candidate_or_absence(self):
        data = copy.deepcopy(self.data)
        data["engines"][0].pop("candidate")
        errors = MODULE.validate(data)
        self.assertTrue(any("needs exactly one of candidate" in error
                            for error in errors), errors)
        # Schema errors stay readable rather than echoing the whole row.
        for error in errors:
            self.assertLessEqual(len(error), 400, error)

    def test_coverage_must_match_the_declared_gap_list(self):
        data = copy.deepcopy(self.data)
        data["engines"].pop()
        errors = MODULE.validate(data)
        self.assertTrue(any("coverage mismatch" in error for error in errors),
                        errors)

    # --- the mistake Phase 1 actually made ---------------------------------

    def test_incompatible_candidate_licences_are_refused(self):
        for expression in ("GPL-2.0-only", "Artistic-1.0",
                           "LicenseRef-PicoDrive-MAME", "NOASSERTION",
                           "GPL-2.0-or-later AND GPL-2.0-only"):
            with self.subTest(expression=expression):
                self.assertTrue(MODULE.check_license_expression(expression))

    def test_compatible_candidate_licences_are_accepted(self):
        for expression in ("GPL-3.0-only", "GPL-3.0-or-later",
                           "GPL-2.0-or-later", "MIT", "Zlib",
                           "GPL-3.0-or-later AND Zlib",
                           "Apache-2.0 WITH LLVM-exception"):
            with self.subTest(expression=expression):
                self.assertEqual([], MODULE.check_license_expression(expression))

    def test_a_candidate_licence_that_is_not_compatible_fails_the_registry(self):
        data = copy.deepcopy(self.data)
        for row in data["engines"]:
            if "candidate" in row:
                row["candidate"]["license"]["spdx"] = "GPL-2.0-only"
                break
        errors = MODULE.validate(data)
        self.assertTrue(any("GPL-2.0-only is incompatible" in error
                            for error in errors), errors)

    def test_a_custom_licence_term_needs_a_cited_compatible_audit(self):
        expression = "GPL-2.0-or-later AND LicenseRef-V30MZ-Permissive"
        self.assertTrue(MODULE.check_license_expression(expression))
        self.assertEqual(
            [], MODULE.check_license_expression(expression,
                                                allow_audited_refs=True))
        self.assertEqual(
            [], MODULE.audit_clears_custom_terms(
                "engines/audits/beetle-cygne-license.json"))
        # The Virtual Boy audit concluded "Blocked", so it can never clear one.
        self.assertTrue(MODULE.audit_clears_custom_terms(
            "engines/audits/beetle-vb-license.json"))
        self.assertTrue(MODULE.audit_clears_custom_terms("engines/audits/nope.json"))
        self.assertTrue(MODULE.audit_clears_custom_terms("/etc/passwd"))

    def test_audit_verdict_reads_the_opening_clause_not_a_substring(self):
        """"Not blocked." must clear; a substring search for "blocked" would not."""
        audits = ROOT / "engines/audits"
        if (audits / "mame-license.json").is_file():
            self.assertEqual(
                [], MODULE.audit_clears_custom_terms("engines/audits/mame-license.json"),
                "an audit whose verdict opens 'Not blocked' must still clear")
        blocked = json.loads(
            (audits / "beetle-vb-license.json").read_text(encoding="utf-8"))
        self.assertTrue(blocked["aggregateConclusion"].lower().startswith("blocked"))

    def test_a_custom_licence_without_an_audit_fails_the_registry(self):
        data = copy.deepcopy(self.data)
        for row in data["engines"]:
            if "candidate" in row:
                row["candidate"]["license"]["spdx"] = "LicenseRef-Unknown-Terms"
                row["candidate"]["license"].pop("auditRef", None)
                break
        errors = MODULE.validate(data)
        self.assertTrue(any("needs a cited Lucent audit" in error
                            for error in errors), errors)

    def test_declared_licence_policy_cannot_drift_from_the_validator(self):
        data = copy.deepcopy(self.data)
        data["licensePolicy"]["compatible"].append("GPL-2.0-only")
        errors = MODULE.validate(data)
        self.assertTrue(any("licensePolicy.compatible drifted" in error
                            for error in errors), errors)

    # --- no silent collision with an earlier phase -------------------------

    def test_a_system_owned_by_an_earlier_phase_needs_an_explicit_replacement(self):
        data = copy.deepcopy(self.data)
        row = next(r for r in data["engines"] if r["category"] == "missing")
        row["systems"] = ["nes"]
        errors = MODULE.validate(data)
        self.assertTrue(any("already owned by phase 1 engine mesen" in error
                            for error in errors), errors)

    def test_a_replacement_row_must_name_the_engine_that_owns_the_system(self):
        data = copy.deepcopy(self.data)
        row = next(r for r in data["engines"]
                   if r["category"] == "blocked-replacement")
        row["priorEngine"] = "hatari"
        row["priorPhase"] = 1
        errors = MODULE.validate(data)
        self.assertTrue(any("declares priorEngine hatari" in error
                            for error in errors), errors)

    def test_a_replacement_row_must_point_at_a_genuinely_blocked_engine(self):
        data = copy.deepcopy(self.data)
        row = next(r for r in data["engines"] if r["category"] == "unpackaged")
        row["category"] = "blocked-replacement"
        errors = MODULE.validate(data)
        self.assertTrue(any("is not blocked, so this is not a replacement row"
                            in error for error in errors), errors)

    def test_priorengine_must_exist_in_an_earlier_registry(self):
        data = copy.deepcopy(self.data)
        row = next(r for r in data["engines"] if "priorEngine" in r)
        row["priorEngine"] = "not-a-real-engine"
        errors = MODULE.validate(data)
        self.assertTrue(any("is not in any earlier registry" in error
                            for error in errors), errors)

    # --- the claims the registry makes about the rest of the repository ----

    def test_incumbent_rows_match_the_earlier_registries(self):
        owners = MODULE.load_prior_ownership()
        engines = MODULE.load_prior_engines()
        for engine_id, row in self.rows.items():
            if row["category"] not in {"blocked-replacement", "misaudited"}:
                continue
            with self.subTest(engine=engine_id):
                prior = row["priorEngine"]
                self.assertIn(prior, engines)
                self.assertTrue(engines[prior]["blocked"],
                                f"{prior} is not blocked in its own registry")
                for system in row["systems"]:
                    self.assertEqual(prior, owners[system][1])

    def test_misaudited_rows_quote_the_exact_wrong_spdx_still_on_record(self):
        engines = MODULE.load_prior_engines()
        rows = [row for row in self.data["engines"]
                if row["category"] == "misaudited"]
        self.assertTrue(rows, "the misaudited category must be exercised")
        for row in rows:
            with self.subTest(engine=row["id"]):
                recorded = row["candidate"]["license"]["correctsRecordedSpdx"]
                self.assertEqual(engines[row["priorEngine"]]["spdx"], recorded)
                # The corrected reading must itself be compatible, and it must
                # differ from the record it replaces.
                self.assertNotEqual(recorded, row["candidate"]["license"]["spdx"])
                self.assertEqual(
                    [], MODULE.check_license_expression(
                        row["candidate"]["license"]["spdx"]))

    def test_a_misaudit_claim_must_match_the_earlier_registry(self):
        data = copy.deepcopy(self.data)
        row = next(r for r in data["engines"] if r["category"] == "misaudited")
        row["candidate"]["license"]["correctsRecordedSpdx"] = "MIT"
        errors = MODULE.validate(data)
        self.assertTrue(any("does not match the" in error for error in errors),
                        errors)

    def test_unpackaged_rows_are_genuinely_absent_from_the_apk(self):
        staged = MODULE.load_staged_cores()
        unpackaged = {row["priorEngine"] for row in self.data["engines"]
                      if row["category"] == "unpackaged"}
        self.assertTrue(unpackaged)
        self.assertEqual(set(), unpackaged & staged)
        # Sanity: the parser really does see the staged Phase 1 core list.
        self.assertIn("mesen", staged)
        self.assertIn("blastem", staged)

    def test_unadvertised_rows_name_an_engine_that_already_emulates_the_hardware(self):
        engines = MODULE.load_prior_engines()
        owners = MODULE.load_prior_ownership()
        rows = [row for row in self.data["engines"]
                if row["category"] == "unadvertised"]
        self.assertTrue(rows)
        for row in rows:
            with self.subTest(engine=row["id"]):
                self.assertIn(row["priorEngine"], engines)
                self.assertFalse(engines[row["priorEngine"]]["blocked"])
                for system in row["systems"]:
                    self.assertNotIn(system, owners)

    def test_the_coverage_document_stays_in_step_with_the_registry(self):
        doc = (ROOT / "docs/phase4-console-coverage.md").read_text(encoding="utf-8")
        for system in MODULE.PHASE_FOUR_SYSTEMS:
            with self.subTest(system=system):
                self.assertIn(system, doc,
                              f"{system} is in the registry but not documented")
        for category in MODULE.CATEGORIES:
            with self.subTest(category=category):
                self.assertIn(category, doc)
        # The "cannot be covered" scope boundary must stay explicit.
        for absent in ("PlayStation 4", "PlayStation 5", "Xbox One",
                       "Xbox Series", "Switch 2"):
            with self.subTest(absent=absent):
                self.assertIn(absent, doc)

    def test_missing_rows_are_genuinely_uncovered(self):
        owners = MODULE.load_prior_ownership()
        for engine_id, row in self.rows.items():
            if row["category"] != "missing":
                continue
            with self.subTest(engine=engine_id):
                self.assertNotIn("priorEngine", row)
                for system in row["systems"]:
                    self.assertNotIn(system, owners)


if __name__ == "__main__":
    unittest.main()
