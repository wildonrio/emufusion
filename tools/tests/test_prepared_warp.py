"""The warp's motion logic runs per phase-grid cell (WARP_PREP) and the 1080p pass reads it back."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = (ROOT / "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java").read_text()
SWITCH = (ROOT / "unified-android/src/com/thorium/preview/game/TimelineSchedulerSwitch.java").read_text()


def shader_text():
    body = GENERATOR.split("private static final String MOTION_INTERPOLATE_SHADER =", 1)[1].split('";\n', 1)[0] + '"'
    code = "\n".join(line for line in body.splitlines() if not line.strip().startswith("//"))
    return "".join(eval(m) for m in re.findall(r'"(?:[^"\\]|\\.)*"', code))


class PreparedWarpTest(unittest.TestCase):
    def test_shader_has_prep_and_prepared_variants(self):
        text = shader_text()
        self.assertIn("#ifdef PREPARED_WARP\nuniform sampler2D uWarp0,uWarp1,uWarp2;", text)
        prepared = text.split("#ifdef PREPARED_WARP\n vec4 pw0", 1)[1].split("#else", 1)[0]
        for name in ("warpForward", "warpBackward", "forward", "backward", "previousReliability",
                     "currentReliability", "previousGate", "currentGate"):
            self.assertIn(name, prepared)
        prep = text.split("#ifdef WARP_PREP\n vec2 pxs", 1)[1].split("#endif", 1)[0]
        self.assertIn("vec4(warpForward*pxs,warpBackward*pxs)", prep)
        self.assertIn("vec4(forward*pxs,backward*pxs)", prep)
        self.assertIn("vec4(previousReliability,currentReliability,previousGate,currentGate)", prep)
        self.assertIn("return;", prep)

    def test_targets_are_half_float_at_the_phase_grid_and_cached(self):
        self.assertIn("GLES30.GL_RGBA16F,\n                    densePhaseWidth, densePhaseHeight, 0, GLES20.GL_RGBA, GLES30.GL_HALF_FLOAT, null);",
                      GENERATOR)
        prep = GENERATOR.split("private boolean renderWarpPrep(float phase, boolean seedsReady) {", 1)[1].split("\n    }\n", 1)[0]
        self.assertIn("warpPrepKeyPromotion == densePromotions && warpPrepKeyPhaseBits == bits", prep)
        self.assertIn("GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, warpPrepState[0]);", prep)

    def test_default_on_with_qa_override_and_unit_check(self):
        self.assertIn("static final boolean DEFAULT_PREPARED_WARP = true;", SWITCH)
        self.assertIn('PREPARED_WARP_GLOBAL = "emufusion_framegen_prepared_warp"', SWITCH)
        draw = GENERATOR.split("private void drawMotionFrame(float phase) {", 1)[1].split("\n    }\n", 1)[0]
        self.assertIn("maxFragmentTextureUnits >= 13 && renderWarpPrep(phase, prepSeeds);", draw)
        self.assertIn('bindTexture(interpolateProgram, "uWarp2", warpPrepTextures[2], 12);', draw)


if __name__ == "__main__":
    unittest.main()
