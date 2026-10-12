"""Phase-centred motion pass and four-candidate synthesis: shader validity and wiring."""
import ast
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
GAME = ROOT / "unified-android/src/com/thorium/preview/game"
GENERATOR = (GAME / "DisplayFrameGenerator.java").read_text()
SWITCH = (GAME / "TimelineSchedulerSwitch.java").read_text()


def shader(name):
    start = GENERATOR.index("private static final String %s =" % name)
    end = GENERATOR.index('"}\\n";', start)
    text = ""
    for line in GENERATOR[start:end + 6].split("\n"):
        if line.strip().startswith("//"):
            continue
        for part in re.findall(r'"((?:[^"\\]|\\.)*)"', line):
            text += ast.literal_eval('"' + part + '"')
    return text


def method(signature):
    start = GENERATOR.index(signature)
    brace = GENERATOR.index("{", start)
    depth = 0
    for index in range(brace, len(GENERATOR)):
        if GENERATOR[index] == "{":
            depth += 1
        elif GENERATOR[index] == "}":
            depth -= 1
            if depth == 0:
                return GENERATOR[start:index + 1]
    raise AssertionError(signature)


class PhaseSynthesisTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("glslangValidator"), "glslangValidator not installed")
    def test_phase_and_interpolate_shaders_compile_as_gles2(self):
        variants = {
            "phase": shader("DENSE_PHASE_SHADER"),
            "holdout": shader("HOLDOUT_SHADER"),
            "interpolate": shader("MOTION_INTERPOLATE_SHADER"),
            "synth": "#define PHASE_SYNTHESIS\n" + shader("MOTION_INTERPOLATE_SHADER"),
            "neighbors": "#define PHASE_SYNTHESIS\n#define PHASE_NEIGHBORS\n" +
                         shader("MOTION_INTERPOLATE_SHADER"),
        }
        with tempfile.TemporaryDirectory(prefix="phase-synthesis-") as temporary:
            for name, source in variants.items():
                path = Path(temporary, name + ".frag")
                path.write_text("#version 100\n" + source)
                result = subprocess.run(["glslangValidator", str(path)],
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, name + "\n" + result.stdout + result.stderr)

    def test_phase_shader_matches_symmetrically_around_the_generated_time(self):
        phase = shader("DENSE_PHASE_SHADER")
        self.assertIn("vec2 pa=vTexCoord-uPhase*v;vec2 pb=vTexCoord+(1.0-uPhase)*v;", phase)
        # Both endpoint fields, zero motion and a sub-pixel refinement compete.
        for candidate in ("c=cost(vb);", "c=cost(f0);", "c=cost(b0);", "c=cost(vec2(0.0));",
                          "n=base+vec2(st.x,0.0);"):
            self.assertIn(candidate, phase)
        self.assertIn("float conf=exp(-best/0.45);", phase)

    def test_interpolate_blends_four_candidates_only_when_the_phase_field_is_bound(self):
        interpolate = shader("MOTION_INTERPOLATE_SHADER")
        self.assertIn("uniform sampler2D uPhaseFlow;", interpolate)
        # Level 0 compiles without any synthesis code; the fast path and the
        # four-candidate blend exist only in the PHASE_SYNTHESIS programs.
        self.assertEqual(interpolate.count("#ifdef PHASE_SYNTHESIS"), 2)
        self.assertEqual(interpolate.count("#ifdef PHASE_NEIGHBORS"), 1)
        self.assertIn("{gl_FragColor=vec4(qp,1.0);return;}", interpolate)
        draw = method("private void drawMotionFrame(float phase)")
        self.assertLess(draw.index("boolean phaseField = renderPhaseField(phase);"),
                        draw.index("GLES20.glUseProgram(interpolateProgram);"))
        self.assertIn("final int interpolateProgram = !phaseField ? this.interpolateProgram :\n"
                      "                synthesisLevel >= 2 ? interpolateNeighborsProgram : "
                      "interpolateSynthProgram;", draw)
        self.assertIn('"uPhaseFlow",\n                phaseField ? densePhaseTexture : '
                      "historyTextures[previousIndex], phaseField ? 9 : 0);", draw)
        self.assertIn('"uPhaseFieldEnabled"), phaseField ? 1f : 0f);', draw)

    def test_phase_pass_restores_target_and_needs_a_tenth_sampler_unit(self):
        render = method("private boolean renderPhaseField(float phase)")
        self.assertIn("if (!synthesisEnabled || !densePyramidEnabled", render)
        self.assertIn("if (maxFragmentTextureUnits < 10) return false;", render)
        self.assertIn("GLES20.glGetIntegerv(GLES20.GL_FRAMEBUFFER_BINDING, state, 0);", render)
        self.assertIn("GLES20.glGetIntegerv(GLES20.GL_VIEWPORT, state, 1);", render)
        self.assertTrue(render.rstrip("}\n ").endswith("return true;"))
        self.assertIn("GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, state[0]);", render)
        self.assertIn("GLES20.glViewport(state[1], state[2], state[3], state[4]);", render)
        self.assertIn("GLES20.glDeleteFramebuffers(1, new int[] {densePhaseFramebuffer}, 0);",
                      GENERATOR)

    def test_synthesis_defaults_on_with_a_qa_only_override(self):
        self.assertIn('SYNTH_GLOBAL = "emufusion_framegen_synth"', SWITCH)
        self.assertIn("DEFAULT_SYNTHESIS_LEVEL = 1;", SWITCH)
        self.assertIn("synthesisLevel = Math.max(0, Math.min(3, level));", SWITCH)
        self.assertIn("synthesisEnabled = synthesisLevel > 0;", GENERATOR)
        self.assertIn('"#define PHASE_SYNTHESIS\\n#define PHASE_NEIGHBORS\\n" + MOTION_INTERPOLATE_SHADER', GENERATOR)


if __name__ == "__main__":
    unittest.main()
