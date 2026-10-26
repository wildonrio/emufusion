"""The held-panel notice trusts the compositor's scan rate, not an SDK-30 mode report."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.tests.test_framegen_startup_fallback import method, JAVA

ROOT = Path(__file__).resolve().parents[2]
HOST = ROOT / "unified-android/src/com/thorium/preview/game/InWindowGameHost.java"


class PanelHeldNoticeTest(unittest.TestCase):
    def test_override_divisor_is_not_a_held_panel(self):
        source = HOST.read_text()
        body = (method(source, "    static double heldPanelEvidenceHz(") + "\n" +
                method(source, "    static boolean panelHeld("))
        fixture = "public class HeldProbe {\n" + body + r'''
    public static void main(String[] args) {
        // Owner, 2026-10-26: the panel at 120, Display.getMode() at 60 (a
        // per-app override on an SDK-30 app). Without compositor evidence a
        // divisor of the planned mode is unknown, never "held".
        assert heldPanelEvidenceHz(120, 60, 0) == 0.0;
        assert heldPanelEvidenceHz(120, 40, 0) == 0.0;
        assert heldPanelEvidenceHz(144, 72, 0) == 0.0;
        // The compositor's scan rate wins over any mode report.
        assert heldPanelEvidenceHz(120, 60, 119.9) == 119.9;
        assert !panelHeld(120, heldPanelEvidenceHz(120, 60, 119.9), 60);
        // A real held panel (60 Hz setting) is still explained.
        assert heldPanelEvidenceHz(120, 60, 60.0) == 60.0;
        assert panelHeld(120, 60.0, 60);
        // A mode that cannot be a divisor is a real mode (90 of 120).
        assert heldPanelEvidenceHz(120, 90, 0) == 90.0;
        assert !panelHeld(120, 90, 60);   // 1.5x room is the existing rule
        assert panelHeld(120, 90, 61);
        assert panelHeld(144, 90, 70);
        // Room above the game's rate: a 30 fps game at 60 is not held.
        assert !panelHeld(120, 60, 30);
        assert !panelHeld(0, 60, 60);
        assert !panelHeld(120, 0, 60);
    }
}'''
        with tempfile.TemporaryDirectory(prefix="panel-held-") as directory:
            out = Path(directory)
            java = out / "HeldProbe.java"
            java.write_text(fixture)
            subprocess.run([str(JAVA / "javac"), "-d", str(out), str(java)], check=True)
            subprocess.run([str(JAVA / "java"), "-ea", "-cp", str(out), "HeldProbe"],
                           check=True)

    def test_notice_waits_and_uses_compositor_rate(self):
        notice = method(HOST.read_text(), "    private String panelHeldNotice(double real)")
        self.assertIn("compositorPanelHz()", notice)
        self.assertIn("heldPanelEvidenceHz(plannedPanelHz, modeHz, compositorHz)", notice)
        self.assertLess(notice.index("PANEL_HELD_CONFIRM_MS"), notice.index("Toast.makeText"))
        self.assertIn("Per-app frame-rate override", notice)


if __name__ == "__main__":
    unittest.main()
