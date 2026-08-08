"""The DS/3DS/Wii U bottom screen has to be *visible* on the Thor's lower display.

This pins a bug that reproduced four times and looked, from every log the app
emitted, like a success. melonDS rendered its 256x192 bottom crop into a valid,
correctly sized 1240x1080 Surface, drawFrame returned true, and SurfaceFlinger
had that gameplay layer opaque, buffered and composited on display 4 — while the
physical lower screen read a uniform #000000.

PreviewActivity hosted the Surface with:

    gameplaySurface.setBackgroundColor(Color.BLACK);
    gameplaySurface.setZOrderMediaOverlay(true);

setZOrderMediaOverlay puts a SurfaceView at sublayer -1: above other media
Surfaces but *below* its own Activity's window. The window therefore has to keep
a transparent hole punched wherever the SurfaceView sits. Giving a View a
background clears PFLAG_SKIP_DRAW, which moves SurfaceView's hole punch out of
dispatchDraw() and into draw() — and draw() punches the hole and then calls
View.draw(), which repaints that exact rectangle with the background. The window
came out opaque black directly over the gameplay Surface. Uniform #000000 rather
than the root gradient is the fingerprint: the hole was punched, then refilled.

Both halves are pinned below, because either one alone brings the black back.
DS, 3DS (azahar) and Wii U all route their lower screen through this single
host, so all three shared the bug and share the fix.
"""

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPANION = ROOT / "android-companion" / "src" / "com" / "thorium" / "preview"
PREVIEW_ACTIVITY = COMPANION / "PreviewActivity.java"
ROUTER = COMPANION / "SecondaryGameplaySurfaceRouter.java"
GAME = ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" / "game"
LIBRETRO = GAME / "LibretroEngineSession.java"
PPSSPP = GAME / "PpssppGlesEngineSession.java"
NATIVE_ADAPTER = GAME / "NativeAdapterEngineSession.java"
LAYOUT = (ROOT / "unified-android" / "src" / "com" / "thorium" / "lucent"
          / "video" / "DualScreenLayout.java")


def body(source: str, start: str, end: str) -> str:
    """The text between two anchors, so a test reads one method, not a file."""
    assert start in source, f"missing anchor {start!r}"
    remainder = source.split(start, 1)[1]
    assert end in remainder, f"missing anchor {end!r} after {start!r}"
    return remainder.split(end, 1)[0]


def code(source: str) -> str:
    """The source without comments.

    Every "this call must not appear" assertion runs on this. The comment above
    the fix deliberately names setZOrderMediaOverlay and the background to
    explain why they are forbidden, and that prose must not satisfy — or fail —
    the tests that ban them.
    """
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", " ", source, flags=re.S))


class LowerScreenCompositionTest(unittest.TestCase):
    """The frame is drawn correctly; this is about it reaching the panel."""

    @classmethod
    def setUpClass(cls):
        cls.preview = PREVIEW_ACTIVITY.read_text(encoding="utf-8")
        cls.show = body(cls.preview, "private void showGameplaySurface(long generation)",
                        "private void leaveGameplaySurface")
        cls.show_code = code(cls.show)

    def test_the_gameplay_surface_is_composed_above_the_window(self):
        # The whole bug in one line. Sublayer -1 makes visibility depend on a
        # transparency hole surviving in the window; sublayer +1 does not.
        self.assertIn("gameplaySurface.setZOrderOnTop(true);", self.show_code)

    def test_the_gameplay_surface_is_never_a_mere_media_overlay(self):
        # Below the window is exactly where it was invisible.
        self.assertNotIn("setZOrderMediaOverlay", code(self.preview))

    def test_the_gameplay_surface_carries_no_view_background(self):
        # A background on a SurfaceView repaints the punched hole. SurfaceView
        # already keeps its own black colour layer *behind* the Surface, so
        # there is nothing to gain and a black screen to lose.
        self.assertNotIn("gameplaySurface.setBackgroundColor", code(self.preview))
        self.assertNotIn("gameplaySurface.setBackground(", code(self.preview))
        self.assertNotIn("setBackgroundColor", self.show_code)

    def test_the_z_order_is_chosen_before_the_surface_is_attached(self):
        # setZOrderOnTop only takes effect while the SurfaceView has no window;
        # after addView the Surface already exists at the old sublayer.
        self.assertLess(self.show_code.index("gameplaySurface.setZOrderOnTop(true);"),
                        self.show_code.index("root.addView(gameplaySurface"))

    def test_the_gameplay_surface_is_the_last_child_of_the_root(self):
        self.assertIn("root.addView(gameplaySurface, fill());", self.show_code)
        self.assertIn("gameplaySurface.bringToFront();", self.show_code)
        self.assertLess(self.show_code.index("root.addView(gameplaySurface"),
                        self.show_code.index("gameplaySurface.bringToFront();"))

    def test_every_preview_view_is_hidden_behind_the_gameplay_surface(self):
        # Belt to the z-order's braces: nothing opaque is left showing even if
        # a future change puts the Surface back under the window.
        for view in ("artwork", "eyebrow", "titleView", "scoreView", "launchButton"):
            self.assertIn(f"{view}.setVisibility(View.GONE);", self.show_code,
                          f"{view} is still visible over the gameplay surface")
        self.assertIn("blackout.setVisibility(View.GONE);", self.show_code)
        self.assertIn("stopPlayers();", self.show_code)

    def test_the_surface_size_is_reported_to_the_engine_as_it_changes(self):
        # The lower panel is 1240x1080; the engine scales its 256x192 crop to
        # whatever this reports, so a stale size is a stretched bottom screen.
        for callback in ("surfaceCreated", "surfaceChanged"):
            self.assertIn(callback, self.show_code)
        self.assertIn("SecondaryGameplaySurfaceRouter.surfaceAvailable(gameplayGeneration,",
                      self.show_code)
        self.assertIn("SecondaryGameplaySurfaceRouter.surfaceDestroyed(gameplayGeneration);",
                      self.show_code)


class LowerScreenOwnershipTest(unittest.TestCase):
    """A live dual-screen session keeps the display until it gives it back."""

    @classmethod
    def setUpClass(cls):
        cls.preview = PREVIEW_ACTIVITY.read_text(encoding="utf-8")

    def test_a_preview_selection_cannot_evict_a_live_gameplay_surface(self):
        # The Pegasus heartbeat, the 750 ms watchdog and a late ACTION_UPDATE
        # all land here. Any of them tearing the Surface down leaves the engine
        # rendering a lower screen nobody can see for the rest of the session.
        selection = code(body(self.preview, "private void showSelection(String video",
                              "private void raiseVideoBelowChrome"))
        self.assertIn("if (gameplaySurface != null) return;", selection)
        self.assertLess(selection.index("if (gameplaySurface != null) return;"),
                        selection.index("leaveGameplaySurface(true);"))

    def test_an_explicit_blank_still_hands_the_display_back(self):
        # ACTION_BLANK is how SecondaryGameplaySurfaceRouter.release ends a
        # session. If this stopped tearing down, previews would never return.
        blank = code(body(self.preview, "private void blankScreen() {",
                          "private void showGameplaySurface"))
        self.assertIn("leaveGameplaySurface(false);", blank)

    def test_the_gameplay_flag_tracks_the_surface_exactly(self):
        show = code(body(self.preview, "private void showGameplaySurface(long generation)",
                         "private void leaveGameplaySurface"))
        self.assertIn("gameplaySurfaceActive = true;", show)
        leave = code(body(self.preview,
                          "private void leaveGameplaySurface(boolean restorePreviewViews)",
                          "private static String safe(String value)"))
        self.assertIn("gameplaySurfaceActive = false;", leave)


class LowerScreenRoutingTest(unittest.TestCase):
    """One host serves DS, 3DS and Wii U — so one fix covers all three."""

    @classmethod
    def setUpClass(cls):
        cls.router = ROUTER.read_text(encoding="utf-8")
        cls.preview = PREVIEW_ACTIVITY.read_text(encoding="utf-8")

    def test_every_dual_screen_system_reaches_the_one_fixed_host(self):
        supports = body(self.router, "static boolean supports(String systemId)", "}")
        for system in ("nds", "ds", "3ds", "n3ds", "wiiu", "wii-u"):
            self.assertIn(f'"{system}".equals(value)', supports,
                          f"{system} no longer routes to the lower display")
        # All three engine families implement the same listener, so they all
        # render into the SurfaceView whose z-order is pinned above.
        for source in (LIBRETRO, PPSSPP, NATIVE_ADAPTER):
            self.assertIn("SecondaryGameplaySurfaceRouter.Listener",
                          source.read_text(encoding="utf-8"),
                          f"{source.name} no longer uses the shared lower-display host")

    def test_the_router_only_talks_to_the_current_generation(self):
        for method in ("surfaceAvailable", "surfaceDestroyed", "touch"):
            self.assertIn("generation == candidate",
                          body(self.router, f"void {method}(", "}"),
                          f"{method} would address a stale session")

    def test_touch_on_the_lower_panel_reaches_the_lower_half_of_the_frame(self):
        # The panel is the bottom screen, so a tap at its top edge is the
        # midpoint of the stacked composite the cores actually see.
        listener = code(body(self.preview, "gameplaySurface.setOnTouchListener(",
                             "root.addView(gameplaySurface"))
        self.assertIn("SecondaryGameplaySurfaceRouter.touch(gameplayGeneration,", listener)
        self.assertIn("event.getX() / width, event.getY() / height, pressed);", listener)
        self.assertIn("return true;", listener)
        self.assertIn("listener.onSecondaryTouch(clamp(normalizedX), clamp(normalizedY), pressed)",
                      self.router)
        for source in (LIBRETRO, PPSSPP):
            self.assertIn("DualScreenLayout.lowerScreenPointerY(normalizedY)",
                          source.read_text(encoding="utf-8"),
                          f"{source.name} maps lower-panel touch to the wrong screen")
        mapping = body(LAYOUT.read_text(encoding="utf-8"),
                       "public static short lowerScreenPointerY(float normalized)", "}")
        self.assertIn("pointerCoordinate(0.5f + clamped * 0.5f);", mapping)


if __name__ == "__main__":
    unittest.main()
