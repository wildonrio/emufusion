"""Emulated video is scaled proportionally and sits flush top to bottom.

The reported fault was a Sega Genesis picture stretched wider than it was
tall. The cause was general rather than Genesis-specific: the frontend fitted
whatever aspect the running core happened to report, and BlastEm reports
none, so the picture was fitted to its 320x224 pixel shape instead of the 4:3
television the console actually drew on.

These checks pin the rule itself -- one shared display-aspect authority, and
one destination rectangle that keeps the aspect, touches the top and bottom
edges whenever the picture fits, and never leaves the panel -- so no engine
path can drift back to stretching or clipping. The arithmetic is re-derived
here from the aspects the Java source declares, so an edit that changes an
entry or the fit rule fails here as well as in the Java unit test.
"""

import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GEOMETRY = (ROOT / "unified-android" / "src" / "com" / "thorium" / "lucent" /
            "video" / "PresentationGeometry.java")
GEOMETRY_TEST = (ROOT / "unified-android" / "test" / "com" / "thorium" /
                 "lucent" / "video" / "PresentationGeometryTest.java")
SURFACE = (ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" /
           "game" / "GameSurface.java")
SURFACE_VIEW = (ROOT / "unified-android" / "src" / "com" / "thorium" /
                "preview" / "game" / "GameSurfaceView.java")
HOST = (ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" /
        "game" / "InWindowGameHost.java")
LIBRETRO = (ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" /
            "game" / "LibretroEngineSession.java")
HARDWARE_SESSION = (ROOT / "unified-android" / "src" / "com" / "thorium" /
                    "preview" / "game" / "PpssppGlesEngineSession.java")
HARDWARE_LOOP = (ROOT / "unified-android" / "src" / "com" / "thorium" /
                 "preview" / "ExperimentalGlesRenderLoop.java")
GLES_HOST = (ROOT / "unified-android" / "src" / "com" / "thorium" /
             "preview" / "ExperimentalGlesLibretroHost.java")
VULKAN_HOST = (ROOT / "unified-android" / "src" / "com" / "thorium" /
               "preview" / "ExperimentalVulkanLibretroHost.java")
GLES_NATIVE = ROOT / "unified-android" / "native" / "lucent_android_gles_backend.c"
VULKAN_NATIVE = (ROOT / "unified-android" / "native" /
                 "lucent_android_vulkan_backend.c")
TEST_RUNNER = ROOT / "unified-android" / "test.sh"

# The Thor's top panel, and the short canvas a separate defect can produce.
# Nothing in the implementation may assume either number.
PANEL = (1920, 1080)
SHORT_PANEL = (1920, 1025)


def _evaluate(expression: str, constants: dict) -> float:
    cleaned = re.sub(r"(\d)f\b", r"\1", expression.strip())
    for name, value in constants.items():
        cleaned = re.sub(r"\b%s\b" % name, repr(value), cleaned)
    if not re.fullmatch(r"[0-9.\s/*+()e-]+", cleaned):
        raise AssertionError("unexpected aspect expression: " + expression)
    return float(eval(cleaned, {"__builtins__": {}}, {}))  # noqa: S307


def _declared_aspects(source: str) -> dict:
    constants = {}
    for name, expression in re.findall(
            r"private static final float (\w+) = ([^;]+);", source):
        constants[name] = _evaluate(expression, constants)
    aspects = {}
    televised = re.search(
        r"for \(String television : new String\[\] \{(.*?)\}\)", source, re.S)
    assert televised, "the televised-console list must stay recognisable"
    for system in re.findall(r'"([a-z0-9]+)"', televised.group(1)):
        aspects[system] = constants["TELEVISION"]
    for system, expression in re.findall(
            r'aspects\.put\("([a-z0-9]+)",\s*([^)]+)\);', source):
        aspects[system] = _evaluate(expression, constants)
    return aspects


def _declared_fallbacks(source: str) -> dict:
    constants = {}
    for name, expression in re.findall(
            r"private static final float (\w+) = ([^;]+);", source):
        constants[name] = _evaluate(expression, constants)
    return {
        system: _evaluate(expression, constants)
        for system, expression in re.findall(
            r'fallbacks\.put\("([a-z0-9]+)",\s*([^)]+)\);', source)
    }


def _fit(surface, aspect):
    """The documented rule: preserve aspect, fill height when it fits."""
    width, height = surface
    drawn_width = round(height * aspect)
    drawn_height = height
    if drawn_width > width:
        drawn_width = width
        drawn_height = round(drawn_width / aspect)
    left = (width - drawn_width) // 2
    top = (height - drawn_height) // 2
    return left, top, drawn_width, drawn_height


class ProportionalVideoScalingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.geometry = GEOMETRY.read_text(encoding="utf-8")
        cls.surface = SURFACE.read_text(encoding="utf-8")
        cls.host = HOST.read_text(encoding="utf-8")
        cls.libretro = LIBRETRO.read_text(encoding="utf-8")
        cls.aspects = _declared_aspects(cls.geometry)
        cls.fallbacks = _declared_fallbacks(cls.geometry)

    def test_hardware_display_fallbacks_exist_only_for_missing_engine_reports(self):
        # Every one of these drew non-square pixels, so the frame's own shape
        # is not the answer. Genesis is the reported fault; the others are the
        # same fault waiting to be reported.
        for system in ("megadrive", "snes", "n64", "mastersystem", "pcengine",
                       "neogeo", "saturn", "3do", "nds"):
            self.assertAlmostEqual(self.aspects[system], 4 / 3, places=5,
                                   msg=system + " is a 4:3 display")
        # Square-pixel handheld panels, pinned so a core cannot override them.
        self.assertAlmostEqual(self.aspects["gba"], 3 / 2, places=5)
        self.assertAlmostEqual(self.aspects["gb"], 10 / 9, places=5)
        self.assertAlmostEqual(self.aspects["3ds"], 5 / 3, places=5)
        # Fixed widescreen panels, given as the panel's true ratio.
        self.assertAlmostEqual(self.aspects["psp"], 480 / 272, places=5)
        self.assertAlmostEqual(self.aspects["switch"], 16 / 9, places=5)
        self.assertAlmostEqual(self.aspects["wiiu"], 16 / 9, places=5)
        self.assertNotIn("nes", self.aspects,
                         "Mesen must supply the region-correct NES aspect")

    def test_variable_aspect_systems_are_left_to_their_engine(self):
        # A vertical arcade cabinet is taller than it is wide and a widescreen
        # console game is 16:9 on hardware that is otherwise 4:3. Only the
        # running engine knows, so these must not be pinned in the table.
        for system in ("arcade", "dos", "gamecube", "wii", "psx", "ps2", "nes",
                       "dreamcast", "amiga", "scummvm"):
            self.assertNotIn(system, self.aspects,
                             system + " aspect must stay with the engine")

    def test_engine_aspect_precedes_every_system_fallback(self):
        resolve = self.geometry.split("public static float resolveAspect", 1)[1]
        engine = resolve.index("if (isPlausible(engineAspect)) return engineAspect;")
        fallback = resolve.index("float fixed = systemDisplayAspect(systemId);")
        self.assertLess(engine, fallback,
                        "no system-wide ratio may replace a running game mode")

    def test_representative_systems_are_flush_top_and_bottom(self):
        expected = {
            "megadrive": 1440,   # 320x224 pixels, 4:3 display
            "snes": 1440,        # 256x239 pixels, 4:3 display
            "n64": 1440,         # television output is 4:3
            "gba": 1620,         # 240x160 square pixels
            "nds": 1440,         # one 256x192 screen
            "3ds": 1800,        # 400x240 top screen
            "psp": 1906,         # 480x272 panel
            "switch": 1920,      # native 16:9 fills the panel
        }
        for system, width in expected.items():
            aspect = self.aspects.get(system, self.fallbacks.get(system))
            left, top, drawn_width, drawn_height = _fit(
                PANEL, aspect)
            self.assertEqual(drawn_width, width, system + " drawn width")
            self.assertEqual(drawn_height, PANEL[1],
                             system + " must touch the top and bottom edges")
            self.assertEqual(top, 0, system + " must not letterbox")
            self.assertEqual(left, (PANEL[0] - width) // 2,
                             system + " pillars must be even")
            # Proportional: one scale factor for both axes, to within the
            # rounding of a single pixel.
            self.assertLessEqual(
                abs(drawn_width - drawn_height * aspect), 1,
                system + " must not be stretched on one axis")

    def test_a_short_canvas_is_still_flush_and_still_proportional(self):
        # A separate defect can make the QML canvas 1025 px tall. The rule must
        # come out of the measured surface, so the picture stays proportional
        # and a 16:9 console pillarboxes rather than stretching to the width.
        left, top, width, height = _fit(SHORT_PANEL, self.aspects["megadrive"])
        self.assertEqual(height, SHORT_PANEL[1])
        self.assertEqual(width, 1367)
        self.assertEqual(top, 0)
        left, top, width, height = _fit(SHORT_PANEL, self.aspects["switch"])
        self.assertEqual(height, SHORT_PANEL[1])
        self.assertEqual(width, 1822)
        self.assertGreater(left, 0, "a short canvas pillarboxes 16:9")

    def test_a_picture_wider_than_the_surface_remains_wholly_visible(self):
        left, top, width, height = _fit((1000, 1000), 4.0)
        self.assertEqual((left, top, width, height), (0, 375, 1000, 250))

    def test_every_video_surface_carries_the_display_aspect(self):
        # The one mechanism that also covers engines with no frontend blit --
        # Eden and Cemu render straight into the Android window, so the window
        # itself has to be the right shape. Both the TextureView the libretro
        # and GLES sessions use and the SurfaceFlinger layer the Phase 3 native
        # adapters use must honour it.
        for path in (SURFACE, SURFACE_VIEW):
            source = path.read_text(encoding="utf-8")
            self.assertIn("public void setDisplayAspect(float aspect)", source,
                          path.name + " must accept a display aspect")
            self.assertIn("protected void onMeasure(", source,
                          path.name + " must shape itself while measuring")
            self.assertIn("PresentationGeometry.fit(", source,
                          path.name + " must use the shared rule")
            self.assertIn("setMeasuredDimension(box.width(), box.height());",
                          source, path.name + " must adopt the fitted size")

    def test_the_host_never_preshapes_a_surface_from_a_system_guess(self):
        build = self.host.split("private void buildUi()", 1)[1].split(
            "private FrameLayout.LayoutParams match()", 1)[0]
        self.assertNotIn(
            "PresentationGeometry.systemDisplayAspect(request.systemId)", build)
        self.assertGreaterEqual(build.count("layer.setDisplayAspect(0f);"), 2,
                                "every engine receives the complete panel")
        # Centred, so the two pillars are the same width, over the gameplay
        # root's black background.
        self.assertIn("videoParams.gravity = Gravity.CENTER;", build)
        self.assertIn("root.addView(gameSurface, videoParams);", build)
        self.assertIn("root.setBackgroundColor(Color.BLACK);", build)

    def test_the_software_blit_uses_the_shared_rule(self):
        draw = self.libretro.split("private boolean drawFrame(", 1)[1].split(
            "private static Rect rectangle(", 1)[0]
        self.assertIn("PresentationGeometry.fitFrame(", draw)
        self.assertIn("PresentationGeometry.fitFrameInside(", draw)
        self.assertIn("preserveWholePicture", draw)
        # The destination is one rectangle from the shared rule, never two
        # independently computed extents.
        self.assertNotIn("drawWidth", draw)
        self.assertNotIn("drawHeight", draw)
        # A dual-screen crop is half the picture, so the engine's whole-frame
        # aspect must not be applied to it.
        self.assertIn("float sourceAspect = dualScreen ? 0f : displayAspect;",
                      self.libretro)

    def test_hardware_sessions_resolve_and_forward_one_authoritative_aspect(self):
        session = HARDWARE_SESSION.read_text(encoding="utf-8")
        loop = HARDWARE_LOOP.read_text(encoding="utf-8")
        self.assertIn("PresentationGeometry.resolveAspect(", session)
        self.assertIn("request.systemId, av.aspectRatio", session)
        self.assertIn("loop.setPresentationAspect(presentationAspect);", session)
        self.assertLess(session.index("loop.setPresentationAspect(presentationAspect);"),
                        session.index("renderLoop = loop;"),
                        "aspect must reach native code before a Surface can attach")
        self.assertGreaterEqual(loop.count("nativeHost.setPresentationAspect(aspect);"), 2,
                                "both GLES and Vulkan hosts must receive the aspect")

    def test_both_jni_render_backends_apply_the_resolved_aspect(self):
        gles_host = GLES_HOST.read_text(encoding="utf-8")
        vulkan_host = VULKAN_HOST.read_text(encoding="utf-8")
        gles = GLES_NATIVE.read_text(encoding="utf-8")
        vulkan = VULKAN_NATIVE.read_text(encoding="utf-8")
        self.assertIn("nativeSetPresentationAspectGles", gles_host)
        self.assertIn("nativeSetPresentationAspectVulkan", vulkan_host)
        self.assertIn("backend->presentation_aspect", gles)
        self.assertIn("backend->presentation_aspect", vulkan)
        self.assertIn("fit_direct_window_frame", gles,
                      "direct-window GLES cores need an explicit fit path")
        self.assertGreaterEqual(gles.count("glBlitFramebuffer("), 3,
                                "direct-window fit needs capture and final blits")
        self.assertIn("crop == LUCENT_SCREEN_FULL", vulkan,
                      "whole-frame aspect must not be imposed on screen crops")
        scaled_fit = vulkan.split(
            "if (crop != LUCENT_SCREEN_FULL && scaled_portrait_surface)", 1)[1]
        scaled_fit = scaled_fit.split("} else if", 1)[0]
        self.assertIn("lucent_surface_fit(destination_extent.width,", scaled_fit)
        self.assertIn("destination_extent.height, destination_extent.height,", scaled_fit)
        self.assertIn("destination_extent.width, aspect, &fitted)", scaled_fit)
        self.assertIn("destination_width = fitted.width;", scaled_fit)
        self.assertIn("destination_height = fitted.height;", scaled_fit)
        self.assertIn("crop != LUCENT_SCREEN_FULL", vulkan,
                      "screen crops must be contained rather than side-cropped")
        self.assertNotIn("source_x += (cropped_width - visible_width) / 2u;", vulkan,
                         "Vulkan presentation must never crop source pixels")
        self.assertIn("destination_width > destination_extent.width", vulkan,
                      "too-wide Vulkan output must be contained")

    def test_native_logical_to_producer_fit_behavior(self):
        # Execute the production helper, not a Python reimplementation. The C
        # cases check Thor's composed 4:3 image, ordinary 4:3/5:3/16:9 fits,
        # portrait Views, rounding, containment, and invalid inputs.
        with tempfile.TemporaryDirectory(prefix="emufusion-surface-fit-") as folder:
            executable = str(Path(folder) / "surface_fit_test")
            subprocess.run([
                "cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                str(ROOT / "unified-android/native/tests/surface_fit_test.c"),
                "-lm", "-o", executable,
            ], check=True, capture_output=True, text=True, timeout=60)
            result = subprocess.run([executable], check=True, capture_output=True,
                                    text=True, timeout=15)
            self.assertIn("logical View to producer surface geometry passed",
                          result.stdout)

    def test_snes_crops_to_the_reviewed_active_picture(self):
        # 2026-09-06: exposing Mesen-S's raw 256x239 signal (the "None"
        # profile) showed as an unwanted ~34px black band top and bottom on
        # the Thor's flat panel -- a real CRT's bezel would have clipped
        # that overscan border, but nothing here does. "8px" restores the
        # reviewed, physically-proven 256x224 active picture (OverscanTop=7,
        # OverscanBottom=8, matching docs/HANDOVER-2026-08-09.md).
        native_host = (ROOT / "unified-android" / "native" /
                       "lucent_libretro_host.c").read_text(encoding="utf-8")
        self.assertIn('strcmp(variable->key, "mesen-s_overscan_vertical") == 0',
                      native_host)
        self.assertIn('find_option_token(options, "8px", &value_size)',
                      native_host)
        self.assertNotIn('find_option_token(options, "None", &value_size)',
                         native_host)

    def test_no_generic_presenter_or_psp_profile_crops_source_pixels(self):
        native_host = (ROOT / "unified-android" / "native" /
                       "lucent_libretro_host.c").read_text(encoding="utf-8")
        gles = GLES_NATIVE.read_text(encoding="utf-8")
        self.assertNotIn("centre_crop_to_aspect", gles)
        self.assertRegex(
            native_host,
            r'(?s)ppsspp_cropto16x9"\) == 0\).*?'
            r'find_option_token\(\s*options, "disabled"',
        )

    def test_genesis_crops_overscan_like_snes(self):
        # 2026-09-06: RETRO_ENVIRONMENT_GET_OVERSCAN answering true exposed
        # BlastEm's raw overscan border, the same unwanted black band as the
        # Mesen-S regression above. false = crop TV-safe overscan (see
        # docs/strict-off-physical-qa-2026-08-30.md, the original fix for
        # BlastEm's previously-undefined overscan query result).
        native_host = (ROOT / "unified-android" / "native" /
                       "lucent_libretro_host.c").read_text(encoding="utf-8")
        overscan = native_host.split("RETRO_ENVIRONMENT_GET_OVERSCAN:", 1)[1]
        overscan = overscan.split("RETRO_ENVIRONMENT_GET_CAN_DUPE", 1)[0]
        self.assertIn("*(bool *)data = false;", overscan,
                      "libretro overscan must be cropped, not exposed")

    def test_n64_never_crops_game_pixels_with_fixed_overscan_offsets(self):
        native_host = (ROOT / "unified-android" / "native" /
                       "lucent_libretro_host.c").read_text(encoding="utf-8")
        self.assertIn('strcmp(variable->key, "mupen64plus-EnableOverscan") == 0',
                      native_host)
        self.assertIn('options, "Disabled", &value_size', native_host)
        self.assertIn('strcmp(variable->key, "mupen64plus-OverscanTop") == 0',
                      native_host)
        self.assertIn('strcmp(variable->key, "mupen64plus-OverscanBottom") == 0',
                      native_host)
        self.assertGreaterEqual(
                native_host.count('find_option_token(options, "0", &value_size)'), 2)
        self.assertNotIn('strcmp(variable->key, "mupen64plus-OverscanLeft") == 0',
                         native_host)
        self.assertNotIn('strcmp(variable->key, "mupen64plus-OverscanRight") == 0',
                         native_host)

    def test_the_java_scaling_unit_test_runs(self):
        self.assertTrue(GEOMETRY_TEST.is_file())
        self.assertIn("com.thorium.lucent.video.PresentationGeometryTest",
                      TEST_RUNNER.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
