import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class InternalPcEmulationTest(unittest.TestCase):
    def test_windows_routes_to_packaged_dosbox_pure_not_phase3_winlator(self):
        registry = json.loads((ROOT / "engines/registry.json").read_text())
        row = next(item for item in registry["engines"]
                   if item["id"] == "dosbox-pure")
        self.assertIn("windows", row["systems"])

        matrix = json.loads((ROOT / "unified-android/tools/"
                             "runtime-acceptance-matrix.json").read_text())
        windows = next(item for item in matrix["systems"]
                       if item["folder"] == "windows")
        self.assertEqual(["dosbox-pure"], windows["engines"])
        self.assertEqual(1, windows["phase"])

        closure = (ROOT / "unified-android/tools/verify_menu_route_closure.py").read_text()
        phase3_line = next(line for line in closure.splitlines()
                           if line.startswith("PHASE3_SYSTEMS"))
        self.assertNotIn("windows", phase3_line)

    def test_scanner_extensions_match_the_internal_core(self):
        systems = (ROOT / "android-companion/src/com/thorium/preview/"
                   "GameSystems.java").read_text()
        block = systems[systems.index('add("windows"'):]
        block = block[:block.index('add("switch"')]
        for extension in ("zip", "dosz", "exe", "com", "bat", "iso",
                          "chd", "cue", "ins", "img", "ima", "vhd",
                          "jrc", "m3u", "m3u8", "conf"):
            self.assertIn(extension, block)
        self.assertNotIn(" msi", block)
        self.assertNotIn(" cmd", block)

    def test_aliases_controls_and_qa_fixture_cover_windows(self):
        resolver = (ROOT / "unified-android/src/com/thorium/lucent/metadata/"
                    "EngineSystemIdResolver.java").read_text()
        self.assertIn('alias(aliases, "windows", "win", "windows10", "pc")',
                      resolver)
        controls = (ROOT / "unified-android/src/com/thorium/lucent/input/"
                    "SystemControlLayouts.java").read_text()
        self.assertIn('"dos", "windows", "windows9x", "scummvm"', controls)
        generator = (ROOT / "engines/qa/generate_fixtures.py").read_text()
        core_qa = (ROOT / "engines/qa/run_phase1a_qa.py").read_text()
        activity_qa = (ROOT / "unified-android/tools/"
                       "run_phase1a_activity_qa.py").read_text()
        for source in (generator, core_qa, activity_qa):
            self.assertIn("emufusion-internal-pc-callback-test.zip", source)
            self.assertIn("windows", source)

    def test_documentation_does_not_overclaim_modern_windows(self):
        design = (ROOT / "docs/internal-pc-emulation.md").read_text()
        self.assertIn("single `com.thorium.preview` process", design)
        self.assertIn("Modern Windows boundary", design)
        self.assertIn("Wine + Box64", design)
        self.assertIn("never bundles", design)


if __name__ == "__main__":
    unittest.main()
