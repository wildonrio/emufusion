"""Frame generation must run on GPUs other than the Thor's Adreno.

Every GLSL string constant compiles as GLSL ES 1.00 and never names a variable
after a GLSL ES keyword or reserved word. Adreno accepted `vec2 smooth`, but
ANGLE (the Android emulator) rejected it and failed generation closed; other
vendors' compilers are as strict. Generation also keeps running without
EXT_disjoint_timer_query (native-fence stage timing) and without
EGL_ANDROID_get_frame_timestamps (vsync panel clock).
"""
import ast
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "unified-android" / "src"
NATIVE = ROOT / "unified-android" / "native" / "emufusion_framegen_timer_jni.c"
GENERATOR = SRC / "com" / "thorium" / "preview" / "game" / "DisplayFrameGenerator.java"
GLSLANG = shutil.which("glslangValidator") or "/opt/homebrew/bin/glslangValidator"

RESERVED = set("""
smooth flat centroid layout uniform buffer shared coherent volatile restrict readonly
writeonly patch sample subroutine invariant precise input output filter common partition
active noperspective superp resource atomic_uint char long short double half fixed
unsigned sizeof cast namespace using union enum typedef template this goto switch default
case inline noinline public static extern external interface class asm packed precision
lowp mediump highp in out inout attribute varying discard struct texture
""".split())
DECLARATION = re.compile(
    r"\b(?:float|int|bool|vec[234]|ivec[234]|bvec[234]|mat[234])\s+([A-Za-z_]\w*)")


def shader_constants():
    """(file, name, GLSL text) for every String constant whose name contains SHADER."""
    found = []
    for java in sorted(SRC.rglob("*.java")):
        source = java.read_text()
        for match in re.finditer(r"\bString (\w*SHADER\w*) =", source):
            text, done = "", False
            for line in source[match.end():].split("\n"):
                if line.strip().startswith("//"):
                    continue
                in_string = escaped = False
                literal = ""
                for index, char in enumerate(line):
                    if in_string:
                        if escaped:
                            escaped = False
                            literal += char
                        elif char == "\\":
                            escaped = True
                            literal += char
                        elif char == '"':
                            in_string = False
                            text += ast.literal_eval('"' + literal + '"')
                            literal = ""
                        else:
                            literal += char
                    elif char == '"':
                        in_string = True
                    elif char == ";" or line[index:index + 2] == "//":
                        done = char == ";"
                        break
                if done:
                    break
            if "void main" in text:
                found.append((java.name, match.group(1), text))
    return found


class ShaderPortabilityTest(unittest.TestCase):
    def test_every_generator_shader_is_found(self):
        names = {name for _, name, _ in shader_constants()}
        for required in ("DENSE_SOLVE_SHADER", "DENSE_CYCLE_SHADER", "DENSE_PHASE_SHADER",
                         "MOTION_INTERPOLATE_SHADER", "DENSE_PYRAMID_SHADER"):
            self.assertIn(required, names)

    def test_no_shader_names_a_variable_after_a_glsl_keyword(self):
        for file, name, text in shader_constants():
            for declared in DECLARATION.findall(text):
                with self.subTest(shader=name, identifier=declared):
                    self.assertNotIn(declared, RESERVED, f"{file}:{name}")

    @unittest.skipUnless(Path(GLSLANG).exists(), "glslangValidator not installed")
    def test_every_shader_compiles_as_gles2(self):
        defines = {"": ""}
        with tempfile.TemporaryDirectory(prefix="shader-portability-") as temporary:
            for file, name, text in shader_constants():
                variants = dict(defines)
                if "PHASE_SYNTHESIS" in text:
                    variants.update({
                        "synth": "#define PHASE_SYNTHESIS\n",
                        "neighbors": "#define PHASE_SYNTHESIS\n#define PHASE_NEIGHBORS\n",
                        "prepared": "#define PHASE_SYNTHESIS\n#define PHASE_NEIGHBORS\n"
                                    "#define PREPARED_WARP\n",
                        "prep": "#define WARP_PREP\n",
                    })
                kind = "vert" if "gl_Position" in text else "frag"
                for variant, prefix in variants.items():
                    body = prefix + text
                    extensions = [l for l in body.split("\n") if l.startswith("#extension")]
                    rest = [l for l in body.split("\n") if not l.startswith("#extension")]
                    path = Path(temporary, f"{name}-{variant or 'base'}.{kind}")
                    path.write_text("\n".join(["#version 100"] + extensions + rest))
                    result = subprocess.run([GLSLANG, str(path)], capture_output=True,
                                            text=True, timeout=30)
                    with self.subTest(shader=name, variant=variant):
                        self.assertEqual(result.returncode, 0,
                                         f"{file}:{name}\n{result.stdout}{result.stderr}")


class GenerationFallbackTest(unittest.TestCase):
    def test_stage_timing_falls_back_to_native_fences(self):
        native = NATIVE.read_text()
        create = native[native.index("DenseGpuTimer_nativeCreate("):]
        create = create[:create.index("\n}\n")]
        self.assertIn('if (force_fences || !has_extension(extensions, "GL_EXT_disjoint_timer_query")) {', create)
        self.assertIn("enable_fence_timing(timer)", create)
        self.assertIn("timer->timing_source = TIMING_SOURCE_FENCES;", create)
        self.assertIn('has_extension(egl, "EGL_ANDROID_native_fence_sync")', native)
        self.assertIn("SYNC_IOC_FILE_INFO", native)
        # Each fence is flushed where it stands; the emulator signalled an
        # unflushed begin fence after the stage's end fence.
        self.assertIn("slot->begin_fd = insert_fence(timer);", native)
        self.assertIn("slot->end_fd = insert_fence(timer);", native)
        self.assertIn("FENCE_MIN_ELAPSED_NS", native)

    def test_panel_clock_falls_back_to_vsync_callbacks(self):
        generator = GENERATOR.read_text()
        poll = generator[generator.index("private void pollPhysicalPresentations()"):]
        poll = poll[:poll.index("tracker.poll();")]
        self.assertIn("if (tracker == null) {\n            recordVsyncPanelClock();", poll)
        vsync = generator[generator.index("private void recordVsyncPanelClock()"):]
        vsync = vsync[:vsync.index("\n    }\n")]
        self.assertIn("builtInPhysicalClock.record(frameNs,", vsync)
        self.assertIn("qualifyBuiltInPhysicalClock();", vsync)
        # The scanout path and the vsync path share one qualification rule.
        self.assertEqual(generator.count("qualifyBuiltInPhysicalClock();"), 2)


if __name__ == "__main__":
    unittest.main()
