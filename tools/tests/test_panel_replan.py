"""A variable source launched on the fastest panel mode is re-planned once its rate is known.

Behaviour is unit-tested in PanelRefreshPlannerTest (bestForVariable,
PanelModeReplanner); this pins the host wiring: generated, variable-clock
launches on fixed modes only, fed by the generator's sustained source rate.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
HOST = (ROOT / "unified-android/src/com/thorium/preview/game/InWindowGameHost.java").read_text()
REPLANNER = (ROOT / "unified-android/src/com/thorium/emufusion/timing/PanelModeReplanner.java").read_text()


class PanelReplanTest(unittest.TestCase):
    def test_replanner_is_created_only_for_generated_variable_sources(self):
        self.assertIn("if (generating && !(source > 0.0) && !plan.variableRefresh && panelReplanner == null)",
                      HOST)

    def test_host_feeds_the_sustained_source_rate_and_requests_the_mode(self):
        self.assertIn("observeSourceForPanelReplan(source);", HOST)
        body = HOST.split("private void observeSourceForPanelReplan(double sourceHz) {", 1)[1].split("\n    }", 1)[0]
        self.assertIn("panelReplanner.observe(sourceHz, android.os.SystemClock.uptimeMillis())", body)
        self.assertIn("requestNativePanelMode((float) next);", body)
        self.assertIn("plannedPanelHz = (float) next;", body)

    def test_replanner_is_conservative(self):
        for pin in ("STEADY_MS = 8_000L", "MIN_OUTPUT_GAIN = 1.15", "COOLDOWN_MS = 30_000L",
                    "MAX_SWITCHES = 2",
                    "if (!(then >= now * MIN_OUTPUT_GAIN) && !fitsDoubling) return 0.0;"):
            self.assertIn(pin, REPLANNER)


if __name__ == "__main__":
    unittest.main()
