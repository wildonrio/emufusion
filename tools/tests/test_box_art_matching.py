"""Guards for box-art matching and the artwork-driven library prune.

The owner reported artwork attached to games it did not belong to on Sega
Genesis. The cause was in `ImportManager.catalogMatch`: it built a pool of
alias spellings for the requested title, accepted any catalog entry matching
*any* of them, and then ordered the pool by region tag alone. A subtitled
edition therefore tied with the base game and lost the tiebreak to it, so
"Bass Masters Classic: Pro Edition" wore "Bass Masters Classic"'s box while
its own box sat in the same listing.

Ranking now lives in `TitleMatcher`, which is platform-neutral and pinned by
`TitleMatcherTest` against the device's real titles and real libretro file
names. What this file guards is everything that test cannot see: that the
importer actually delegates to it, that the ranking cannot quietly revert to a
flat alias pool, and that the prune's brakes are all still bolted on. A
deletion pass that loses one of those brakes still passes every unit test and
still eats somebody's library.
"""

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
IMPORTER = ROOT / "android-companion" / "src" / "com" / "thorium" / "preview" / "ImportManager.java"
MATCHER = (ROOT / "unified-android" / "src" / "com" / "thorium" / "lucent" / "metadata"
           / "TitleMatcher.java")
MATCHER_TEST = (ROOT / "unified-android" / "test" / "com" / "thorium" / "lucent" / "metadata"
                / "TitleMatcherTest.java")
TEST_SCRIPT = ROOT / "unified-android" / "test.sh"
THEME = ROOT / "theme" / "theme.qml"
SERVICE = ROOT / "android-companion" / "src" / "com" / "thorium" / "preview" / "PreviewService.java"


class BoxArtMatchingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.importer = IMPORTER.read_text(encoding="utf-8")
        cls.matcher = MATCHER.read_text(encoding="utf-8")
        cls.matcher_test = MATCHER_TEST.read_text(encoding="utf-8")
        cls.script = TEST_SCRIPT.read_text(encoding="utf-8")

    # ---- the matcher is reachable, tested, and host-testable ----------------

    def test_the_matcher_carries_no_android_dependency(self):
        # test.sh compiles this package without an SDK. One android.* import
        # would take the whole matching layer out of host coverage.
        for line in self.matcher.splitlines():
            self.assertFalse(line.startswith("import android."),
                             f"TitleMatcher must stay platform-neutral: {line}")
        self.assertNotIn("androidx.", self.matcher)

    def test_the_host_suite_runs_the_matcher_test(self):
        self.assertIn("com.thorium.lucent.metadata.TitleMatcherTest", self.script,
                      "TitleMatcherTest is not wired into unified-android/test.sh")

    def test_the_reported_failures_are_pinned_as_fixtures(self):
        # These are the two entries the owner named, plus the pairings that
        # reproduce the fault. If a fixture is dropped the regression is free
        # to come back silently.
        for fixture in ("Aladdin II", "Action Replay Max",
                        "Bass Masters Classic: Pro Edition",
                        "Jurassic Park: Rampage Edition",
                        "Mighty Morphin Power Rangers: The Movie"):
            self.assertIn(fixture, self.matcher_test,
                          f"{fixture} is no longer covered by TitleMatcherTest")

    # ---- the importer delegates instead of pooling aliases ------------------

    def test_the_importer_asks_the_matcher_to_choose(self):
        self.assertIn("TitleMatcher.select(", self.importer,
                      "catalogMatch must delegate the choice to TitleMatcher")
        self.assertIn("claimedTitles(system)", self.importer,
                      "the subtitle guard needs the collection's other titles")

    def test_catalog_matching_no_longer_pools_aliases_by_region_alone(self):
        body = self._method("private CatalogMatch catalogMatch")
        # The old shape: collect every alias hit into one list, sort by region,
        # take the first. Any of these reappearing means the ranking was lost.
        self.assertNotIn("keys.contains(", body)
        self.assertNotIn("mediaAliases(title)", body)
        self.assertNotIn("regionRank(", body)

    def test_a_weak_match_names_both_sides_in_the_log(self):
        body = self._method("private CatalogMatch catalogMatch")
        self.assertIn("TIER_EXACT", body,
                      "only the weaker tiers should be logged, so the tier must be read")
        self.assertIn("match.reason()", body,
                      "a logged pairing must say which alias produced it")

    def test_normalization_has_exactly_one_implementation(self):
        # Two copies of normalize() drifting apart is how the catalog and the
        # library stopped agreeing on what a title is in the first place.
        self.assertIn("private static String normalize(String value) { "
                      "return TitleMatcher.normalize(value); }", self.importer)
        self.assertIn("return TitleMatcher.compact(normalized);", self.importer)

    # ---- the review asks; it never acts on its own --------------------------

    def test_the_scan_only_builds_a_list(self):
        run = self._method("private void runScan")
        match = re.search(r"if \(fullDiscovery\) \{[^}]*reviewArtlessGames", run, re.S)
        self.assertIsNotNone(
            match, "the catalog sweep belongs to the manual maintenance pass")
        body = self._method("private int reviewArtlessGames")
        # Everything destructive lives behind decideArtwork(), which only runs
        # when the owner has answered. The sweep may only write the queue.
        self.assertNotIn("deleteRomFile(", body,
                         "a scan must never delete a ROM on its own")
        self.assertIn("writeReviewQueue(", body)

    def test_an_unreachable_catalog_never_reads_as_an_absent_game(self):
        body = self._method("private Map<String, List<String>> readArtworkCatalogs")
        self.assertIn("catalogs.size() * 2 < attempted", body,
                      "a mostly-unreachable thumbnail server must abandon the pass")
        self.assertIn("return null;", body)
        review = self._method("private int reviewArtlessGames")
        self.assertIn("if (catalogs == null) return -1;", review,
                      "no catalogs means no conclusion, not an empty library")

    def test_a_matcher_gap_never_reaches_the_owner_as_a_deletion_offer(self):
        body = self._method("private int reviewArtlessGames")
        self.assertIn("TitleMatcher.hasAnyCandidate(title, own)", body,
                      "the game's own platform decides whether its artwork exists")
        probe = self._method("public static boolean hasAnyCandidate", source=self.matcher)
        self.assertNotIn("claimedTitles", probe,
                         "the probe must not apply the matcher's caution guards")
        self.assertNotIn("isUtilityTitle", probe)

    def test_the_three_answers_are_exactly_what_the_owner_was_offered(self):
        self.assertIn('CHOICE_KEEP = "leave"', self.importer)
        self.assertIn('CHOICE_HIDE = "hide"', self.importer)
        self.assertIn('CHOICE_DELETE = "delete-rom"', self.importer)
        decide = self._method("synchronized String decideArtwork")
        self.assertIn("!CHOICE_KEEP.equals(choice) && !CHOICE_HIDE.equals(choice) &&", decide,
                      "an unknown answer must be refused, not guessed at")

    def test_only_the_delete_answer_touches_a_file(self):
        decide = self._method("synchronized String decideArtwork")
        self.assertIn("CHOICE_DELETE.equals(choice) && !deleteRomFile(romPath)", decide)
        # Hiding must leave the file alone, so the delete call may only ever
        # appear inside the delete-rom branch.
        self.assertEqual(1, decide.count("deleteRomFile("))
        hide = self._method("private void removeLibraryRows")
        self.assertNotIn("rom.delete()", hide,
                         "removing a menu row must not remove the ROM")

    def test_a_refused_delete_is_not_recorded_as_done(self):
        decide = self._method("synchronized String decideArtwork")
        deleted = decide.index("deleteRomFile(romPath)")
        recorded = decide.index("writeDecisions(mediaRoot, decisions)")
        self.assertLess(deleted, recorded,
                        "the ROM must be gone before the answer is remembered")
        self.assertIn('return "";', decide[deleted:recorded],
                      "a failed delete must abandon the answer entirely")

    # ---- the answer is remembered, per game --------------------------------

    def test_the_answer_is_stored_beside_the_media_not_in_app_storage(self):
        # App storage is wiped by a reinstall; PegasusMedia is not.
        self.assertIn('ARTWORK_DECISIONS = "artwork-decisions.json"', self.importer)
        reader = self._method("private static JSONObject readDecisions")
        self.assertIn("new File(mediaRoot, ARTWORK_DECISIONS)", reader)

    def test_the_key_survives_a_rescan_and_a_moved_rom(self):
        key = self._method("private static String decisionKey")
        self.assertIn("system.folder", key)
        self.assertIn("normalize(title)", key)
        self.assertNotIn("getAbsolutePath", key,
                         "keying on a path would re-ask after the ROM moved volume")

    def test_an_answered_game_is_never_offered_again(self):
        body = self._method("private int reviewArtlessGames")
        self.assertIn("JSONObject decision = decisions.optJSONObject(key);", body)
        self.assertIn("if (decision == null) {", body,
                      "only an unanswered game may join the review queue")
        # "Leave as is" keeps the row in the library and out of the queue.
        self.assertIn("if (CHOICE_KEEP.equals(choice)) { keep.add(stanza); continue; }", body)

    def test_a_game_that_gains_artwork_is_released_from_its_answer(self):
        body = self._method("private int reviewArtlessGames")
        self.assertIn("decisions.remove(key)", body,
                      "artwork arriving must retire the answer that assumed none")
        restore = self._method("private boolean restoreGamesThatGainedArtwork")
        self.assertIn("CHOICE_HIDE.equals(decision.optString(\"choice\"))", restore)
        self.assertIn("restoreStanza(", restore)
        self.assertIn("unarchiveRegistryRow(", restore)
        self.assertNotIn("CHOICE_DELETE", restore,
                         "a deleted ROM has nothing left to restore")

    def test_every_removal_is_written_down_and_reversible(self):
        self.assertIn('ARTLESS_LEDGER = "removed-without-artwork.json"', self.importer)
        record = self._method("private JSONObject ledgerRecord")
        for field in ("title", "system", "romPath", "reason", "choice", "romDeleted", "stanza"):
            self.assertIn(f'"{field}"', record,
                          f"the ledger must record {field} so a removal can be traced")
        decide = self._method("synchronized String decideArtwork")
        self.assertIn("writeJsonAtomic(new File(mediaRoot, ARTLESS_LEDGER), ledger)", decide)
        self.assertIn("archiveRegistryRow(romPath)", decide,
                      "an imported game is archived, not erased, so it can be restored")

    # ---- the UI ------------------------------------------------------------

    def test_the_review_is_reachable_and_driveable_with_a_dpad(self):
        theme = THEME.read_text(encoding="utf-8")
        self.assertIn("openArtworkReview()", theme)
        self.assertIn("} else if (artworkReviewOpen) {", theme,
                      "the overlay needs its own key branch, not touch alone")
        for key in ("Qt.Key_Up", "Qt.Key_Down", "Qt.Key_Left", "Qt.Key_Right"):
            self.assertIn(key, theme)
        branch = theme.split("} else if (artworkReviewOpen) {", 1)[1]
        branch = branch.split("} else if (coverOrderEditorOpen) {", 1)[0]
        self.assertIn("artworkReviewMoveRow(", branch)
        self.assertIn("artworkReviewMoveChoice(", branch)
        self.assertIn("submitArtworkChoice()", branch)

    def test_the_destructive_answer_asks_twice(self):
        theme = THEME.read_text(encoding="utf-8")
        submit = theme.split("function submitArtworkChoice()", 1)[1].split("\n    }", 1)[0]
        self.assertIn("artworkReviewChoice === 2 && !artworkReviewConfirming", submit,
                      "deleting a ROM must require a second press")
        move = theme.split("function artworkReviewMoveChoice(", 1)[1].split("\n    }", 1)[0]
        self.assertIn("artworkReviewConfirming = false", move,
                      "moving off the delete option must disarm it")

    def test_the_review_list_bottoms_out_on_the_content_floor(self):
        theme = THEME.read_text(encoding="utf-8")
        listing = theme.split("id: artworkReviewList", 1)[1].split("delegate:", 1)[0]
        self.assertIn("root.listRowHeight(", listing)
        self.assertIn("root.listRowCount(", listing)
        self.assertIn("root.contentBottom - y", listing)

    def test_the_endpoints_exist_and_only_the_writer_is_guarded(self):
        service = SERVICE.read_text(encoding="utf-8")
        self.assertIn('"/artwork/missing".equals(path)', service)
        self.assertIn('"/artwork/decide".equals(path)', service)
        # Reading the list changes nothing; answering can delete a ROM and so
        # belongs with the other mutating endpoints.
        self.assertIn('"/artwork/decide"', service.split("MUTATING_ENDPOINTS", 1)[1]
                      .split("));", 1)[0])
        self.assertNotIn('"/artwork/missing"', service.split("MUTATING_ENDPOINTS", 1)[1]
                         .split("));", 1)[0])

    # ---- helpers -----------------------------------------------------------

    def _method(self, signature, source=None):
        """The body of one Java method, by brace balance."""
        text = self.importer if source is None else source
        start = text.index(signature)
        depth = 0
        for index in range(start, len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    return text[start:index + 1]
        raise AssertionError(f"unbalanced braces after {signature}")


if __name__ == "__main__":
    unittest.main()
