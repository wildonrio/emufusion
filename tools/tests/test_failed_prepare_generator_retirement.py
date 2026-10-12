"""A refused disc image must not leak its frame generator (Thor, 2026-10-11).

The disc preflight can reject a GameCube/Wii image before any render loop
exists. The gameplay Surface and generator may still attach afterwards; when
that Surface is retired the never-prepared session must acknowledge, or the
generator stays alive (and logging) for the rest of the process.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
GAME = ROOT / "unified-android/src/com/thorium/preview/game"
SESSION = (GAME / "PpssppGlesEngineSession.java").read_text()
HOST = (GAME / "InWindowGameHost.java").read_text()


class FailedPrepareGeneratorRetirementTest(unittest.TestCase):
    def test_failed_prepare_acknowledges_surface_retirement(self):
        body = SESSION[SESSION.index("public boolean quiesceForSurfaceRetirement()"):]
        guard = body.index("if (prepareFailed && renderLoop == null) {")
        self.assertLess(guard, body.index("return quiesceForPresentationRecovery();"))
        self.assertIn("return true;", body[guard:guard + 400])
        catch = SESSION.index('"Unable to prepare engine="')
        self.assertIn("prepareFailed = true;", SESSION[catch - 200:catch])

    def test_switching_session_is_a_retirement_producer(self):
        body = HOST[HOST.index("public void retireSurfaceRenderer("):]
        self.assertIn("switchingSession != null ? switchingSession", body[:700])


if __name__ == "__main__":
    unittest.main()
