"""Fail-closed gates for the downloaded and Dolphin cheat catalogues."""

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "release-manifest.json"
SOURCES = ROOT / "engines" / "cheats" / "sources.json"
DOLPHIN = ROOT / "engines" / "cheats" / "dolphin-cheats.json"
PHASE2 = ROOT / "engines" / "phase2-registry.json"
UPDATER = ROOT / "android-companion" / "src" / "com" / "thorium" / "preview" / "UpdateManager.java"
BUILD = ROOT / "unified-android" / "build.sh"
SOFTWARE = ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" / "game" / "LibretroEngineSession.java"
HARDWARE = ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" / "game" / "PpssppGlesEngineSession.java"
NOTICE = ROOT / "THIRD_PARTY_NOTICES.md"


class CheatCatalogUpdateTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.sources = json.loads(SOURCES.read_text(encoding="utf-8"))
        self.dolphin = json.loads(DOLPHIN.read_text(encoding="utf-8"))

    def test_release_manifest_pins_the_official_download(self):
        included = {row["id"]: row for row in self.sources["included"]}
        libretro = included["libretro-database"]
        self.assertEqual(libretro["distribution"], self.manifest["cheatCatalogUrl"])
        self.assertEqual(libretro["snapshotSha256"], self.manifest["cheatCatalogSha256"])
        self.assertEqual("CC-BY-SA-4.0", self.manifest["cheatCatalogLicense"])
        self.assertEqual(libretro["source"], self.manifest["cheatCatalogSource"])
        self.assertRegex(self.manifest["cheatCatalogSha256"], r"^[0-9a-f]{64}$")

    def test_update_session_verifies_and_atomically_installs_the_archive(self):
        source = UPDATER.read_text(encoding="utf-8")
        for required in (
            'setStatus("cheats"',
            'download(manifest.optString("cheatCatalogUrl", "")',
            "CheatArchive.verify(staged)",
            "installCheatArchive(staged, installedCheatArchive)",
            'new File(target.getAbsolutePath() + ".previous")',
        ):
            self.assertIn(required, source)
        self.assertIn("MAX_CHEATS = CheatArchive.MAX_ARCHIVE_BYTES", source)
        self.assertIn('"cheats".equals(previous)', source,
                      "a killed catalogue update must resume as interrupted, not complete")

    def test_dolphin_catalog_is_exact_source_generated_and_deduplicated(self):
        registry = json.loads(PHASE2.read_text(encoding="utf-8"))
        pinned = next(row for row in registry["engines"] if row["id"] == "dolphin")
        self.assertEqual(pinned["source"]["commit"], self.dolphin["sourceCommit"])
        self.assertEqual("GPL-2.0-or-later", self.dolphin["license"])
        self.assertGreaterEqual(len(self.dolphin["games"]), 250)
        self.assertGreaterEqual(sum(len(g["cheats"]) for g in self.dolphin["games"]), 4000)
        for game in self.dolphin["games"]:
            codes = [c["code"].strip().upper() for c in game["cheats"]]
            self.assertEqual(len(codes), len(set(codes)), game["gameId"])
            self.assertTrue(all(code and "\n" not in code for code in codes))

    def test_both_starting_catalogues_are_in_the_apk(self):
        build = BUILD.read_text(encoding="utf-8")
        self.assertIn("engines/cheats/cheat-database.json", build)
        self.assertIn("engines/cheats/dolphin-cheats.json", build)

    def test_no_op_cores_are_not_advertised_as_live(self):
        software = SOFTWARE.read_text(encoding="utf-8")
        hardware = HARDWARE.read_text(encoding="utf-8")
        for core in ("mesen", "mesen-s", "sameboy", "mgba", "gearsystem",
                     "swanstation", "melonds-ds", "fuse", "virtualjaguar"):
            self.assertIn(f'"{core}".equals(engineId)', software)
        # flycast's retro_cheat_set/reset were a no-op stub until
        # engines/patches/flycast-libretro-cheat-support.patch wired them to
        # the core's own (non-LIBRETRO-gated) CheatManager; it is genuinely
        # live now, so it moved out of the still-a-no-op list below and into
        # the hardware session's advertised set alongside dolphin/ppsspp.
        for core in ("dolphin", "ppsspp", "mupen64plus-next", "flycast"):
            self.assertIn(f'"{core}".equals(engineId)', hardware)
        for source in (software, hardware):
            for no_op in ("armsx2", "azahar", "dosbox-pure", "mame"):
                self.assertNotIn(f'"{no_op}".equals(engineId)', source)

    def test_unlicensed_public_dumps_are_excluded_and_notices_are_present(self):
        excluded = {row["id"] for row in self.sources["reviewedButExcluded"]}
        self.assertIn("wiird-code-database", excluded)
        self.assertIn("pcsx2-patches", excluded)
        self.assertIn("community-ppsspp-and-switch-dumps", excluded)
        notice = NOTICE.read_text(encoding="utf-8")
        self.assertIn("Libretro Database", notice)
        self.assertIn("Creative Commons Attribution-ShareAlike 4.0", notice)
        self.assertIn("GameCube/Wii catalogue", notice)


if __name__ == "__main__":
    unittest.main()
