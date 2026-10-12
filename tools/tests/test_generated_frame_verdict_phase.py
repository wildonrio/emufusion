"""The honest frame counter compares each generated frame with the fade at its own phase."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java").read_text()


class GeneratedFrameVerdictPhaseTest(unittest.TestCase):
    def test_shader_blends_at_the_generated_phase(self):
        shader = SOURCE.split("private static final String VERIFY_SHADER =", 1)[1].split(";\n", 1)[0]
        self.assertIn("uniform float uPhase;", shader)
        self.assertIn("abs(g-mix(a,b,uPhase))", shader)
        self.assertNotIn("0.5*(a+b)", shader)

    def test_verification_binds_the_presented_phase(self):
        body = SOURCE.split("private void enqueueGeneratedVerification(float phase) {", 1)[1]
        body = body.split("\n    }\n", 1)[0]
        draw = body.index("drawMotionFrame(phase);")
        uniform = re.search(r'glGetUniformLocation\(verifyProgram, "uPhase"\), phase\)', body)
        self.assertIsNotNone(uniform)
        self.assertLess(draw, uniform.start())
        self.assertLess(uniform.start(), body.index("glDrawArrays"))
        self.assertIn("enqueueGeneratedVerification(proofPhase);", SOURCE)

    def test_evidence_needs_six_times_the_equality_tolerance(self):
        # Cells changing by less than 8/255 cannot tell a correct frame from a
        # blend (hold-out scoring, 2026-10-12); fewer, stronger cells suffice.
        self.assertIn("VERIFY_MOVING_MIN = 32;", SOURCE)
        self.assertIn("VERIFY_EQUAL_MAX = 5;", SOURCE)
        self.assertIn("VERIFY_MIN_MOVING_CELLS = 24;", SOURCE)


if __name__ == "__main__":
    unittest.main()
