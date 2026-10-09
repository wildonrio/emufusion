import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "unified-android/tools/run_n64_top_display_manual_qa.sh"


class N64ManualVisualQaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = HARNESS.read_text(encoding="utf-8")

    def test_requires_explicit_live_owner_observer_before_light(self):
        gate = self.source.index("EMUFUSION_OWNER_WATCHING_TOP")
        trap = self.source.index("trap cleanup EXIT INT TERM HUP")
        light = self.source.index(
            "device shell settings put system screen_brightness 8"
        )
        self.assertLess(gate, light)
        self.assertLess(trap, light)
        self.assertIn("Refusing to light Thor", self.source)

    def test_safe_sleep_wake_transition_proves_top_lit(self):
        stored = self.source.index(
            "device shell settings put system screen_brightness 8"
        )
        wake = self.source.index("device shell input keyevent 224", stored)
        verify = self.source.index("verify_top_lit", wake)
        runner = self.source.index("run_runtime_acceptance_qa.py")
        self.assertLess(stored, wake)
        self.assertLess(wake, verify)
        self.assertLess(verify, runner)
        self.assertIn("initial-oled-lit-state.txt", self.source)
        self.assertIn('[ "$p0" -gt 0 ]', self.source)
        self.assertIn("device shell input keyevent 223", self.source)
        self.assertIn("press Thor physical POWER once now", self.source)
        self.assertIn("for unused in $(seq 1 600)", self.source)
        self.assertNotIn("cmd display set-brightness", self.source)
        self.assertNotIn("set-user-preferred-display-mode", self.source)

    def test_cleanup_blacks_and_verifies_both_oled_panels(self):
        cleanup = self.source.split("cleanup() {", 1)[1].split("}", 1)[0]
        self.assertIn("blacken", cleanup)
        self.assertIn("verify_black", cleanup)
        self.assertIn("panel0-backlight/actual_brightness", self.source)
        self.assertIn("panel1-backlight/actual_brightness", self.source)
        self.assertIn("screen_brightness 0", self.source)

    def test_runs_the_complete_top_screen_n64_rate_family(self):
        self.assertIn("runtime-acceptance-matrix.json", self.source)
        self.assertIn("--system n64", self.source)
        self.assertIn("--titles-per-system 3", self.source)
        self.assertIn("--allow-physical-thor", self.source)
        matrix = json.loads((
            ROOT / "unified-android/tools/runtime-acceptance-matrix.json"
        ).read_text(encoding="utf-8"))
        n64 = next(row for row in matrix["systems"] if row["folder"] == "n64")
        self.assertEqual(n64["requiredSourceTiers"], [20, 30, 60])
        self.assertEqual(n64["requiredTitles"], [
            "The Legend of Zelda: Ocarina of Time",
            "007: The World Is Not Enough",
            "F-Zero X",
        ])

    def test_never_manufactures_a_manual_pass(self):
        self.assertIn(
            "PENDING: no manual visual verdict is created", self.source
        )
        self.assertNotIn("manualPassed=true", self.source)
        self.assertNotIn("qualified=true", self.source)


if __name__ == "__main__":
    unittest.main()
