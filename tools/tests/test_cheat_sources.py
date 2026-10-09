"""Pins for the device-fetched cheat sources and the per-game download hook.

The Java registry (`CheatSourceRegistry`) and the reviewed table in
`engines/cheats/sources.json` ("deviceFetched") must describe the same
sources with the same URLs: the JSON is what a licence review reads, the Java
is what the device runs. Neither may be bundled or redistributed, every URL
must be https, and the ImportManager hook must stay a guarded, per-game call
that can never stop a scan.
"""

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCES = ROOT / "engines" / "cheats" / "sources.json"
REGISTRY = (ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" / "cheats"
            / "sources" / "CheatSourceRegistry.java")
IMPORTER = ROOT / "android-companion" / "src" / "com" / "thorium" / "preview" / "ImportManager.java"
DOWNLOADER = ROOT / "android-companion" / "src" / "com" / "thorium" / "preview" / "GameCheatDownloader.java"
FETCHER = REGISTRY.parent / "CheatSourceFetcher.java"
TEST_SH = ROOT / "unified-android" / "test.sh"
DOCS = ROOT / "docs" / "cheat-system.md"

# Every CheatSource(...) constructor call: id, name, url, aux, license, ...
# The systems literal may be several "..." fragments joined with '+'.
SOURCE_ROW = re.compile(
    r'new CheatSource\(\s*([A-Z0-9_]+),\s*"[^"]*",\s*"([^"]*)",\s*"([^"]*)",\s*"([^"]*)",\s*"([^"]*)",\s*"([^"]*)",'
    r'\s*((?:"[^"]*"\s*\+?\s*)+)',
    re.S)
CONSTANT = re.compile(r'public static final String ([A-Z0-9_]+) = "([^"]+)";')


class CheatSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = json.loads(SOURCES.read_text(encoding="utf-8"))
        cls.registry = REGISTRY.read_text(encoding="utf-8")
        constants = dict(CONSTANT.findall(cls.registry))
        cls.java_rows = {}
        for constant, url, aux, license_, keyed_by, fmt, systems in SOURCE_ROW.findall(cls.registry):
            cls.java_rows[constants[constant]] = {
                "url": url, "aux": aux, "license": license_, "keyedBy": keyed_by,
                "format": fmt, "systems": " ".join(re.findall(r'"([^"]*)"', systems)).split(),
            }

    def test_existing_review_entries_are_intact(self):
        included = {row["id"] for row in self.sources["included"]}
        excluded = {row["id"] for row in self.sources["reviewedButExcluded"]}
        self.assertEqual({"libretro-database", "dolphin-game-settings"}, included)
        for pinned in ("wiird-code-database", "pcsx2-patches", "cemu-graphic-packs",
                       "community-ppsspp-and-switch-dumps"):
            self.assertIn(pinned, excluded)

    def test_device_fetched_table_matches_the_java_registry(self):
        fetched = {row["id"]: row for row in self.sources["deviceFetched"]}
        self.assertGreaterEqual(len(fetched), 16)
        java_fetched = {sid: row for sid, row in self.java_rows.items() if sid != "libretro-database"}
        self.assertEqual(set(fetched), set(java_fetched))
        for sid, row in fetched.items():
            java = java_fetched[sid]
            self.assertEqual(row["url"], java["url"], sid)
            self.assertEqual(row["license"], java["license"], sid)
            self.assertEqual(row["keyedBy"], java["keyedBy"], sid)
            self.assertEqual(row["format"], java["format"], sid)
            self.assertEqual(row["systems"], java["systems"], sid)
            self.assertIs(row["bundled"], False, sid)
            self.assertIs(row["redistribution"], False, sid)
            self.assertTrue(row["url"].startswith("https://"), sid)
            self.assertTrue(row["license"].strip(), sid)

    def test_every_java_url_is_https_and_the_archive_stays_installed_not_fetched(self):
        for sid, row in self.java_rows.items():
            self.assertTrue(row["url"].startswith("https://"), sid)
            self.assertTrue(row["aux"] == "" or row["aux"].startswith("https://"), sid)
        self.assertIn('"https://buildbot.libretro.com/assets/frontend/cheats.zip"', self.registry)
        self.assertIn("this.bundled = false;", (REGISTRY.parent / "CheatSource.java").read_text(encoding="utf-8"))
        self.assertIn("this.redistribution = false;", (REGISTRY.parent / "CheatSource.java").read_text(encoding="utf-8"))

    def test_design_systems_are_covered(self):
        covered = set()
        for row in self.java_rows.values():
            covered.update(row["systems"])
        for system in ("nes", "snes", "gb", "gbc", "gba", "megadrive", "n64", "psx", "ps2", "psp",
                       "gamecube", "wii", "wiiu", "nds", "3ds", "switch", "ps3", "dreamcast",
                       "arcade", "neogeo"):
            self.assertIn(system, covered, system)

    def test_fetcher_is_bounded_cached_and_https_only(self):
        source = FETCHER.read_text(encoding="utf-8")
        self.assertIn('startsWith("https://")', source)
        self.assertIn('setRequestProperty("User-Agent"', source)
        self.assertIn("setConnectTimeout(", source)
        self.assertIn("setReadTimeout(", source)
        self.assertIn("REFRESH_MS = 7L * 24L * 60L * 60L * 1000L", source)
        self.assertIn('"If-None-Match"', source)
        self.assertIn('"If-Modified-Since"', source)
        self.assertIn('".part"', source)
        self.assertIn('".miss"', source)
        self.assertIn("download exceeds", source)

    def test_fetcher_never_memoises_a_transient_failure_as_a_miss(self):
        # Only a definitive "does not exist" (404/410) may cost the URL a
        # seven-day miss; a timeout/reset/DNS blip must be retried next scan,
        # not silently starve every game behind it for a week.
        source = FETCHER.read_text(encoding="utf-8")
        catch_block = source[source.index("} catch (IOException | RuntimeException failed) {"):]
        self.assertNotIn("touch(miss)", catch_block[:catch_block.index("} finally")])
        self.assertIn("HTTP_NOT_FOUND || status == HttpURLConnection.HTTP_GONE", source)
        self.assertIn("recordHostFailure(host)", source)
        self.assertIn("HOST_FAILURE_THRESHOLD", source)
        self.assertIn("isPlausiblePayload(url, head)", source,
                      "a captive-portal (or otherwise wrong-shaped) 2xx body must not be cached as the payload")
        self.assertIn("part.delete();\n                throw copyFailed;", source,
                      "a dropped mid-download connection must not leave a .part file behind")

    def test_import_manager_hook_is_guarded_and_per_game(self):
        source = IMPORTER.read_text(encoding="utf-8")
        # The per-game download is now the last stage of the checkpointed,
        # per-game media queue (reported as a "media" status with the
        # "Cheats" stage label) instead of a separate "cheats" pass.
        queue = source[source.index("private boolean enrichMediaQueue("):
                       source.index("private List<Candidate> discoverCandidates(")]
        self.assertIn('String[] stages = {"Ratings", "Box art", "Wallpaper", "Video", "Cheats"};',
                      queue)
        self.assertIn("for (int index = 0; index < games.size(); index++) {", queue)
        hook = queue.index("game.cheats = GameCheatDownloader.fetch(context, game.system.folder")
        self.assertGreater(hook, queue.index("calculateCriticComposite(game);"))
        attempt = queue.rindex("try {", 0, hook)
        self.assertIn("if (stage == 0) {", queue[attempt:hook])
        call = queue[hook:].split(";", 1)[0]
        self.assertIn("SystemClock.elapsedRealtime() + 15_000L", call,
                      "the per-game cheat stage must be time-bounded")
        cleanup = queue[hook:].split("} finally {", 1)[1].split("}", 1)[0]
        self.assertIn("transfer.close();", cleanup)
        # The guard moved into the bounded fetch overload the importer calls:
        # every failure is logged and reported as zero cheats, never thrown.
        downloader = DOWNLOADER.read_text(encoding="utf-8")
        bounded = downloader[downloader.index(
            "String originalName, File cacheRoot, long deadlineElapsedRealtime) {"):]
        bounded = bounded[:bounded.index("\n    }\n")]
        self.assertIn("try {", bounded)
        self.assertIn("catch (Throwable failed)", bounded)
        self.assertTrue(bounded.rstrip().endswith("return 0;\n        }"),
                        "bounded cheat fetch must swallow failures as zero cheats")
        self.assertIn('out.append("x-lucent-cheats: ")', source)
        self.assertIn('value.put("cheats", cheats);', source)
        self.assertIn('game.cheats = value.optInt("cheats", 0);', source)

    def test_full_discovery_backfills_the_existing_library(self):
        # A game already in the library never goes through the per-game hook
        # above (only newly imported/resumed rows do), so the full-discovery
        # maintenance pass must be the one place that calls refreshLibrary --
        # otherwise files/cheats/downloaded/ never gets written for it.
        source = IMPORTER.read_text(encoding="utf-8")
        artless = source.index("reviewArtlessGames(cacheRoot, mediaRoot)")
        refresh = source.index("GameCheatDownloader.refreshLibrary(context, cacheRoot)")
        self.assertGreater(refresh, artless)
        full_discovery = source.index("if (fullDiscovery) {")
        self.assertGreater(artless, full_discovery)
        self.assertLess(refresh, source.index("String message;"))
        window = source[refresh - 200:refresh + 200]
        self.assertIn("try {", window)
        self.assertIn("catch (Throwable failed)", window)

    def test_downloader_writes_under_both_stems_and_never_throws(self):
        source = DOWNLOADER.read_text(encoding="utf-8")
        self.assertIn("public static int fetch(Context context, String systemFolder, String title, File rom,", source)
        self.assertIn("public static int refreshLibrary(Context context, File cacheRoot)", source)
        self.assertIn("DownloadedCheatFile.pathFor(context, canonical, rom.getName())", source)
        self.assertIn("DownloadedCheatFile.pathFor(context, canonical, originalStem)", source)
        self.assertIn("catch (Throwable failed)", source)
        self.assertIn("CheatControl.downloadedArchive(context)", source,
                      "libretro rows come from the installed archive, never a second download")

    def test_refresh_library_is_bounded_and_resumable(self):
        # A manual Rescan (or a routine full-discovery pass) must return
        # promptly even for a library of thousands of ROMs: refreshLibrary
        # processes a bounded, round-robin slice per call and persists a
        # cursor so the rest of the library is covered by later rescans
        # rather than blocking the current one.
        source = DOWNLOADER.read_text(encoding="utf-8")
        self.assertIn("private static final int REFRESH_BATCH_LIMIT = 150;", source)
        self.assertIn("private static final long REFRESH_TIME_BUDGET_MS = 45_000L;", source)
        self.assertIn('private static final String REFRESH_CURSOR_FILE = "cheats-refresh-cursor.txt";',
                      source)
        refresh = source.index("public static int refreshLibrary(Context context, File cacheRoot)")
        body = source[refresh:source.index("private static int readCursor")]
        self.assertIn("processed < REFRESH_BATCH_LIMIT", body)
        self.assertIn("SystemClock.elapsedRealtime() < deadline", body)
        self.assertIn("writeCursor(cursorFile, index)", body)
        self.assertIn("catch (Throwable failed)", body)
        # The deadline must also reach each game's own fetch() call: the
        # outer loop above only re-checks the wall clock between whole
        # games, so a single game with several enabled sources stalling on
        # different hosts could otherwise blow through the whole budget
        # before the next deadline check ever runs.
        self.assertIn("fetch(context, system, row.optString(\"title\", \"\"), rom,\n"
                      "                                row.optString(\"sourceIdentity\", \"\"), cacheRoot, deadline)",
                      body)
        fetch_with_deadline = source.index(
            "static int fetch(Context context, String systemFolder, String title, File rom,\n"
            "                      String originalName, File cacheRoot, long deadlineElapsedRealtime)")
        fetch_body = source[fetch_with_deadline:source.index("private static void writeCursor")]
        self.assertIn("for (CheatSource source : sources) {\n"
                      "                if (SystemClock.elapsedRealtime() >= deadlineElapsedRealtime) break;",
                      fetch_body,
                      "each enabled source must be skipped once the caller's deadline has passed, "
                      "not only checked between whole games")
        # The cursor read/write are each best-effort and never propagate a
        # failure into the scan.
        self.assertIn("readCursor(File file)", source)
        self.assertIn("writeCursor(File file, int index)", source)
        cursor_write = source[source.index("private static void writeCursor"):]
        self.assertIn("catch (Exception ignored)", cursor_write)

    def test_host_suite_runs_the_source_tests(self):
        script = TEST_SH.read_text(encoding="utf-8")
        for test in ("CheatParsersTest", "CheatGameIdentityTest", "DownloadedCheatFileTest",
                     "CheatSourceSlicerTest", "ChdIdentityTest", "CheatIdentityCrcTest"):
            self.assertIn("com.thorium.preview.cheats.sources." + test, script)
        self.assertIn("! -name 'DownloadedCheatFile.java'", script)

    def test_docs_describe_the_device_fetch_posture(self):
        docs = DOCS.read_text(encoding="utf-8")
        for heading in ("## Sources per system", "## Identity", "## Per-game file",
                        "## Device-fetch legal posture"):
            self.assertIn(heading, docs)
        self.assertIn("files/cheats/downloaded/", docs)
        self.assertIn("files/cheats/sources.json", docs)


if __name__ == "__main__":
    unittest.main()
