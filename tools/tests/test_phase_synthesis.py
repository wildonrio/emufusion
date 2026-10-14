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


def shader_constant(name):
    """A shader constant up to its terminating ';' (for shaders whose last
    line does not end in a bare closing brace)."""
    start = GENERATOR.index("private static final String %s =" % name)
    end = GENERATOR.index('\\n";', start) + 4
    text = ""
    for line in GENERATOR[start:end].split("\n"):
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
    @unittest.skipUnless(shutil.which("glslangValidator") or Path("/opt/homebrew/bin/glslangValidator").exists(),
                         "glslangValidator not installed")
    def test_phase_and_interpolate_shaders_compile_as_gles2(self):
        variants = {
            "phase": shader("DENSE_PHASE_SHADER"),
            "median": shader("PHASE_MEDIAN_SHADER"),
            "holdout": shader("HOLDOUT_SHADER"),
            "cut": shader_constant("DENSE_GLOBAL_CUT_SHADER"),
            "interpolate": shader("MOTION_INTERPOLATE_SHADER"),
            "synth": "#define PHASE_SYNTHESIS\n" + shader("MOTION_INTERPOLATE_SHADER"),
            "neighbors": "#define PHASE_SYNTHESIS\n#define PHASE_NEIGHBORS\n" +
                         shader("MOTION_INTERPOLATE_SHADER"),
            "warp-prep": "#define WARP_PREP\n" + shader("MOTION_INTERPOLATE_SHADER"),
            "prepared": "#define PREPARED_WARP\n" + shader("MOTION_INTERPOLATE_SHADER"),
            "prepared-synth": "#define PHASE_SYNTHESIS\n#define PREPARED_WARP\n" +
                              shader("MOTION_INTERPOLATE_SHADER"),
            "prepared-neighbors": "#define PHASE_SYNTHESIS\n#define PHASE_NEIGHBORS\n"
                                  "#define PREPARED_WARP\n" + shader("MOTION_INTERPOLATE_SHADER"),
        }
        with tempfile.TemporaryDirectory(prefix="phase-synthesis-") as temporary:
            for name, source in variants.items():
                path = Path(temporary, name + ".frag")
                path.write_text("#version 100\n" + source)
                result = subprocess.run([shutil.which("glslangValidator") or "/opt/homebrew/bin/glslangValidator", str(path)],
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, name + "\n" + result.stdout + result.stderr)

    def test_static_structure_takes_the_zero_motion_blend(self):
        # Fixed menu text whose highlight changed was erased by a warp that
        # sampled background from elsewhere; where both endpoints keep the
        # same two-ring rank pattern at zero motion, a warp of two sampling
        # steps or more takes the unwarped blend (synthesis 15). The census
        # runs once per pair in its own pass (inlined, register pressure
        # doubled Sonic Superstars' warp time even when off).
        mask = shader_constant("STRUCTURE_MASK_SHADER")
        self.assertIn("for(int r=1;r<=2;r++){", mask)
        self.assertIn("if(disagree>1.5)return 0.0;", mask)
        self.assertIn("if(textured<2.5)return 0.0;", mask)
        self.assertIn("if(maxDiff(ra,rb)<6.0/255.0)return 0.0;", mask)
        interpolate = shader("MOTION_INTERPOLATE_SHADER")
        self.assertIn("float staticStructure(float motionPx){", interpolate)
        self.assertIn("return texture2D(uStructureMask,vTexCoord).r;", interpolate)
        self.assertNotIn("for(int r=1;r<=2;r++){", interpolate)
        self.assertIn("finalColor=mix(finalColor,mix(rawPrevious,rawCurrent,uPhase),"
                      "staticStructure(structureMotionPx));", interpolate)
        draw = method("private void drawMotionFrame(float phase)")
        self.assertIn("boolean structure = synthesisLevel == 15 && maxFragmentTextureUnits >= 14 &&", draw)
        self.assertLess(draw.index("renderStructureMask()"),
                        draw.index("GLES20.glUseProgram(interpolateProgram);"))
        self.assertIn('bindTexture(interpolateProgram, "uStructureMask", structureMaskTexture, 13);', draw)
        render = method("private boolean renderStructureMask()")
        self.assertIn("structureMaskPromotion == densePromotions", render)
        self.assertIn("GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, structureMaskState[0]);", render)

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
        # The early phase-blend exit still yields to static structure.
        self.assertIn("gl_FragColor=vec4(mix(qp,mix(qra,qrb,uPhase),staticStructure(length(qv*uDenseSeedSourceSize))),1.0);return;}", interpolate)
        draw = method("private void drawMotionFrame(float phase)")
        self.assertLess(draw.index("boolean phaseField = renderPhaseField(phase);"),
                        draw.index("GLES20.glUseProgram(interpolateProgram);"))
        self.assertIn("final int interpolateProgram = prepared ?\n"
                      "                (phaseField ? (neighbours ? preparedNeighborsProgram : preparedSynthProgram) :\n"
                      "                        preparedProgram) :\n"
                      "                !phaseField ? this.interpolateProgram :\n"
                      "                synthesisLevel == 7 ? interpolateSharpNeighborsProgram :\n"
                      "                synthesisLevel == 2 || synthesisLevel == 3 || synthesisLevel == 6 ||\n"
                      "                        synthesisLevel == 14 || synthesisLevel == 15 ? interpolateNeighborsProgram :\n"
                      "                interpolateSynthProgram;", draw)
        self.assertIn('"uPhaseFlow",\n                phaseField ? densePhaseBoundTexture : '
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
        self.assertIn("DEFAULT_SYNTHESIS_LEVEL = 15;", SWITCH)
        # 5 (QA): level 4 matched on the quarter-resolution pyramid images.
        # 6/7 (QA): level 5 with per-pixel neighbour selection, soft and sharp.
        # 21 (QA): GPU dense inverse search (test_dis_framegen).
        self.assertIn("synthesisLevel = level == DIS_SYNTHESIS_LEVEL || level == DIS_MOTION_SYNTHESIS_LEVEL ||\n"
                      "                level == DIS_PHASE_SYNTHESIS_LEVEL ? level : Math.max(0, Math.min(15, level));", SWITCH)
        # Hold-out variants are a QA setting; 100+ adds the prepared warp.
        self.assertIn("static final int[] DEFAULT_HOLDOUT_LEVELS = {14, 15, 115};", SWITCH)
        self.assertIn("holdoutPreparedOverride = holdoutLevelIds[level] >= 100;", GENERATOR)
        self.assertIn("synthesisLevel = holdoutLevelIds[level] % 100;", GENERATOR)
        self.assertIn("private boolean phaseMatchesQuarterImages() { return synthesisLevel >= 5; }", GENERATOR)
        # The finest solve uses the same quarter-resolution images by default.
        self.assertIn("private static volatile boolean solveQuarter = true;", SWITCH)
        self.assertIn("SOLVE_QUARTER_GLOBAL, 1) != 0;", SWITCH)
        self.assertIn("boolean quarter = solveMatchesQuarterImages && denseQuarterImagesAvailable();", GENERATOR)
        self.assertIn("int ref = level == 0 ? (quarter ? denseBoxTextures[direction == 0 ? 0 : 1][0] : reference) :", GENERATOR)
        self.assertIn("synthesisEnabled = synthesisLevel > 0;", GENERATOR)
        self.assertIn('"#define PHASE_SYNTHESIS\\n#define PHASE_NEIGHBORS\\n" + MOTION_INTERPOLATE_SHADER', GENERATOR)


if __name__ == "__main__":
    unittest.main()


class PhaseSearchTest(unittest.TestCase):
    """The default synthesis searches around a poorly matched phase winner."""

    def test_default_searches_only_poorly_matched_cells(self):
        generator = (Path(__file__).resolve().parents[2] / "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java").read_text()
        self.assertIn('" if(uPhaseSearch>0.5&&best>uPhaseSearchAbove){\\n" +', generator)
        self.assertIn("boolean search = synthesisLevel == 3 || synthesisLevel >= 8;", generator)
        self.assertIn("if (thresholdedSearch) { searchStart = 16f; searchRounds = 4f; }", generator)
        self.assertIn("thresholdedSearch ? 0.15f : -1f);", generator)

