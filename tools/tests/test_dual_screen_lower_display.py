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

    def test_lower_surface_format_matches_the_frame_generator_egl_config(self):
        # The generator selects RGBA8888.  Letting SurfaceView default to the
        # Thor's RGB565 display-4 format produced successful swaps and cadence
        # on a physically black layer.
        self.assertIn(
            "gameplaySurface.getHolder().setFormat(PixelFormat.RGBA_8888);",
            self.show_code)

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
        self.assertIn("SecondaryGameplaySurfaceRouter.surfaceAvailable(surfaceGeneration,",
                      self.show_code)
        self.assertIn("SecondaryGameplaySurfaceRouter.surfaceDestroyed(surfaceGeneration);",
                      self.show_code)

    def test_surface_changed_preserves_the_generator_input_surface(self):
        helper = body(self.preview,
                      "private void ensureGameplayGenerator(Surface output",
                      "private void releaseGameplayGenerator")
        self.assertIn(
            "if (gameplayFrameGenerator != null || gameplayEngineSurface != null) return;",
            code(helper))
        self.assertNotIn("releaseGameplayGenerator();", code(helper))
        self.assertIn("gameplayFrameGenerator.resize", self.show_code)

    def test_stale_surface_destroy_cannot_release_new_generation(self):
        self.assertIn("final long surfaceGeneration = generation;", self.show_code)
        self.assertIn("releaseGameplayGenerator(surfaceGeneration);", self.show_code)
        guarded = body(self.preview,
                       "private void releaseGameplayGenerator(long ownerGeneration)",
                       "private void releaseGameplayGenerator()")
        self.assertIn("ownerGeneration != gameplayGeneratorGeneration", guarded)
        self.assertIn("Ignoring stale gameplay surface destruction", guarded)


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

    def test_a_stale_preview_blank_cannot_evict_the_live_game(self):
        # Preview hide/blank and the gameplay request are posted independently.
        # The older preview command must not tear down a generation which has
        # already become current.
        blank = code(body(self.preview, "private void blankScreen() {",
                          "private void showGameplaySurface"))
        self.assertIn(
            "gameplaySurface != null && SecondaryGameplaySurfaceRouter.isCurrent(gameplayGeneration)",
            " ".join(blank.split()))
        self.assertLess(blank.index("SecondaryGameplaySurfaceRouter.isCurrent"),
                        blank.index("leaveGameplaySurface(false);"))

    def test_router_release_invalidates_before_the_real_teardown_blank(self):
        # ACTION_BLANK from router release is different from a stale preview
        # command: release advances the generation first, so blankScreen's
        # ownership guard opens and previews can return.
        router = ROUTER.read_text(encoding="utf-8")
        release = code(body(router,
                            "public static synchronized void release(",
                            "static synchronized boolean isCurrent"))
        self.assertLess(release.index("++generation;"),
                        release.index("PreviewService.ACTION_BLANK"))
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
        self.assertIn("SecondaryGameplaySurfaceRouter.touch(surfaceGeneration,", listener)
        self.assertIn("float normalizedX = event.getX() / width;", listener)
        self.assertIn("normalizedY = event.getY() / height;", listener)
        self.assertIn("normalizedX, normalizedY, pressed);", listener)
        self.assertIn("return true;", listener)
        self.assertIn("listener.onSecondaryTouch(clamp(normalizedX), clamp(normalizedY), pressed)",
                      self.router)
        self.assertIn("DualScreenLayout.lowerScreenPointerY(normalizedY)",
                      PPSSPP.read_text(encoding="utf-8"))
        self.assertIn("DualScreenLayout.lowerScreenPointerY(point.y)",
                      LIBRETRO.read_text(encoding="utf-8"))
        mapping = body(LAYOUT.read_text(encoding="utf-8"),
                       "public static short lowerScreenPointerY(float normalized)", "}")
        self.assertIn("pointerCoordinate(0.5f + clamped * 0.5f);", mapping)

    def test_ds_touch_matches_contained_canvas_crop_and_releases_bars(self):
        session = LIBRETRO.read_text(encoding="utf-8")
        touch = body(session, "@Override public void onSecondaryTouch(",
                     "@Override public void resume()")
        self.assertIn("int width = secondarySurfaceWidth;", touch)
        self.assertIn("int height = secondarySurfaceHeight;", touch)
        self.assertIn("DualScreenLayout.dsTouchPoint(", touch)
        self.assertIn("dispatchDsPanelTouch(false, normalizedX * width, normalizedY * height,", touch)
        self.assertIn("DualScreenLayout.dsTouchPoint(x, y, width, height)", touch)
        self.assertIn("DualScreenLayout.pointerCoordinate(point.x)", touch)
        self.assertIn("DualScreenLayout.lowerScreenPointerY(point.y)", touch)
        self.assertIn("pressed && point.inside", touch)
        self.assertNotIn("if (!point.inside) return", touch)
        route_touch = body(self.router, "static synchronized void touch(",
                           "static boolean supports(")
        self.assertIn('"nds".equals(requestedSystem) || "ds".equals(requestedSystem)',
                      route_touch)
        self.assertIn("!Float.isFinite(normalizedX) || !Float.isFinite(normalizedY)",
                      route_touch)
        self.assertIn("normalizedX < 0f || normalizedX >= 1f", route_touch)
        self.assertIn("normalizedY < 0f || normalizedY >= 1f", route_touch)
        self.assertLess(route_touch.index("pressed = false"),
                        route_touch.index("listener.onSecondaryTouch("))
        # The dedicated 3DS listener retains its SideScreen-aware path;
        # the shared PreviewActivity listener also serves Wii U and is unchanged.
        clockwise = body(self.preview, "private void showClockwiseGameplaySurface()",
                         "private void postClockwiseSurfaceTransform")
        self.assertIn("DualScreenLayout.threeDsTouchPoint(", clockwise)
        self.assertIn("point.inside && action != MotionEvent.ACTION_UP", clockwise)

    def test_libretro_crops_correct_melonds_video_row_origin(self):
        source = LIBRETRO.read_text(encoding="utf-8")
        present = body(source, "private void presentVideo(",
                       "private boolean drawFrame(")
        # Native TopBottom stays unchanged. A per-game choice selects both
        # destinations from one snapshot; executable DualScreenLayoutTest
        # checks native/swapped halves and matching input at several sizes.
        self.assertIn("boolean touchOnPrimary = dsTouchOnPrimary;", present)
        self.assertIn(
            "DualScreenLayout.dsScreenTop(frame.height, true, touchOnPrimary)",
            present,
        )
        self.assertIn(
            "DualScreenLayout.dsScreenTop(frame.height, false, touchOnPrimary)",
            present,
        )
        self.assertIn("primarySourceRect.set(0, primaryTop, frame.width, primaryTop + frame.height / 2);", present)
        self.assertIn("secondarySourceRect.set(0, secondaryTop, frame.width, secondaryTop + frame.height / 2);", present)
        self.assertIn('DEFAULT_DS_TOUCH_ON_PRIMARY = false;', source)
        self.assertEqual(source.count(
            '.getBoolean(dsLayoutPreferenceKey, DEFAULT_DS_TOUCH_ON_PRIMARY)'), 2)
        self.assertNotIn('.getBoolean(dsLayoutPreferenceKey, false)', source)
        self.assertIn('!DualScreenLayout.dsPanelIsTouch(primary, dsTouchOnPrimary)', source)
        self.assertIn('running && pressed && point.inside', source)

    def test_single_screen_ds_retains_both_images_and_stylus(self):
        source = LIBRETRO.read_text(encoding="utf-8")
        present = body(source, "private void presentVideo(", "private boolean drawFrame(")
        self.assertIn("boolean splitScreens = dualScreen && hasSecondaryDsSurface();", present)
        self.assertIn("boolean phoneDs = dualScreen && !splitScreens", present)
        self.assertIn("DualScreenLayout.dsSideBySide(frameColors, dsPhoneColors", present)
        self.assertIn("float sourceAspect = phoneDs ? 8f / 3f", present)
        self.assertIn("frameBitmap.setPixels(presentationColors", present)
        self.assertIn("primaryGenerator.submitSoftwareFrame(presentationColors", present)
        touch = body(source, "private void dispatchDsPanelTouch(", "@Override public void resume()")
        self.assertIn("DualScreenLayout.dsSideBySideTouchPoint(x, y, width, height)", touch)
        self.assertNotIn("!secondaryGameplayRequested", touch)
        self.assertIn("active.setPointer(0, (short) 0, (short) 0, false)", touch)

    def test_vulkan_ds_crop_accounts_for_image_coordinate_origin(self):
        backend = (ROOT / "unified-android" / "native" /
                   "lucent_android_vulkan_backend.c").read_text(encoding="utf-8")
        resolver = body(backend, "static bool resolve_source_region(",
                        "static bool record_present_commands_for_target(")
        # The Vulkan transfer image follows the software path: top-first, so
        # the secondary (touch) crop selects the second Y half and the primary
        # crop y=0.  (melonds-ds is pinned to the software renderer; this
        # path is unverified on a device.)
        self.assertIn(
            "region->y = crop == LUCENT_SCREEN_BOTTOM ? source_height / 2u : 0u;",
            resolver,
        )
        # Azahar uses an independently reviewed horizontal SideScreen split
        # and must not inherit the DS-specific vertical correction.
        self.assertIn("if (backend->secondary_clockwise_quarter_turn)", resolver)
        self.assertIn(
            "region->x = crop == LUCENT_SCREEN_BOTTOM ? top_width : 0u;",
            resolver,
        )


class DsFrameGenerationGeometryTest(unittest.TestCase):
    """Low-resolution DS crops cannot use a near-half-screen motion radius."""

    @classmethod
    def setUpClass(cls):
        cls.generator = (GAME / "DisplayFrameGenerator.java").read_text(
            encoding="utf-8"
        )

    def test_motion_limit_is_relative_below_full_resolution(self):
        self.assertIn("MAX_FLOW_SOURCE_FRACTION = 0.20f", self.generator)
        self.assertIn("shorterSide * MAX_FLOW_SOURCE_FRACTION", self.generator)
        self.assertIn("Math.min(MAX_FLOW_PIXELS", self.generator)
        self.assertIn("float flowLimit = flowLimitPixels(historyWidth, historyHeight);",
                      self.generator)
        self.assertNotIn(
            "MAX_FLOW_PIXELS / Math.max(1f, historyWidth)", self.generator
        )

    def test_qualification_logs_the_exact_motion_bound(self):
        self.assertIn('"Motion bounds generator="', self.generator)
        self.assertIn('" maxFlowPixels="', self.generator)
        self.assertIn('" maxFlowFraction="', self.generator)


class ThreeDsLowerScreenRotationTest(unittest.TestCase):
    """Azahar's portrait producer crop is rotated into the landscape panel."""

    @classmethod
    def setUpClass(cls):
        cls.preview = PREVIEW_ACTIVITY.read_text(encoding="utf-8")
        cls.router = ROUTER.read_text(encoding="utf-8")
        cls.session = PPSSPP.read_text(encoding="utf-8")
        cls.backend = (ROOT / "unified-android" / "native" /
                       "lucent_android_vulkan_backend.c").read_text(encoding="utf-8")

    def test_3ds_side_crop_selects_the_clockwise_android_layer(self):
        predicate = body(self.router,
                         "static synchronized boolean isClockwiseQuarterTurn",
                         "}")
        self.assertIn('"3ds".equals(requestedSystem)', predicate)
        self.assertIn('"n3ds".equals(requestedSystem)', predicate)
        request = body(self.session, "@Override public void prepare(",
                       "@Override public void attachSurface")
        # The native flag selects the exact SideScreen crop, while the Android
        # layer performs the physical clockwise quarter-turn.
        self.assertIn("if (isThreeDsSystem(request.systemId))", request)
        self.assertIn("loop.setSecondaryPresentationRotation(90);", request)
        self.assertLess(request.index("loop.setSecondaryPresentationRotation(90);"),
                        request.index("SecondaryGameplaySurfaceRouter.request("))

    def test_clockwise_surface_is_selected_for_3ds(self):
        show = body(self.preview, "private void showGameplaySurface(long generation)",
                    "private void leaveGameplaySurface")
        self.assertIn("showClockwiseGameplaySurface();", show)
        self.assertIn('"3ds".equals(requestedSystem)', self.router)
        self.assertIn("LUCENT_SCREEN_BOTTOM,\n                "
                      "backend->secondary_clockwise_quarter_turn,", self.backend)

    def test_clockwise_surface_rotates_the_buffer_not_only_the_view(self):
        clockwise = body(self.preview,
                         "private void showClockwiseGameplaySurface()",
                         "private void ensureGameplayGenerator")
        self.assertIn("int portraitWidth = Math.min(panelWidth, panelHeight);", clockwise)
        self.assertIn("int portraitHeight = Math.max(panelWidth, panelHeight);", clockwise)
        self.assertIn("setFixedSize(portraitWidth, portraitHeight)", clockwise)
        self.assertIn("SurfaceControl.BUFFER_TRANSFORM_ROTATE_90", clockwise)
        self.assertIn("postClockwiseSurfaceTransform(surfaceOwner, surfaceGeneration)",
                      clockwise)
        self.assertIn("setBufferTransform(control,", clockwise)
        self.assertNotIn("gameplaySurface.setRotation(90f)", clockwise)

    def test_touch_uses_the_normal_landscape_surface_coordinates(self):
        surface = body(self.preview, "private void showGameplaySurface(long generation)",
                       "private void showClockwiseGameplaySurface()")
        self.assertIn("float normalizedX = event.getX() / width;", surface)
        self.assertIn("float normalizedY = event.getY() / height;", surface)
        self.assertNotIn("setRotation(90f)", surface)

    def test_vulkan_crops_native_320x240_panel_and_fits_logical_view(self):
        present = body(self.backend, "static bool record_present_commands_for_target(",
                       "static bool record_present_commands(")
        self.assertIn("bool scaled_portrait_surface", present)
        self.assertNotIn("prepare_clockwise_surface", present)
        resolver = body(self.backend, "static bool resolve_source_region(",
                        "static bool record_present_commands_for_target(")
        self.assertIn("source_height * 3u", resolver)
        self.assertIn("source_width * 5u", resolver)
        self.assertIn("source_width - top_width", resolver)
        self.assertIn("lucent_surface_fit(destination_extent.width,", present)
        self.assertIn("destination_extent.height, destination_extent.height,", present)
        self.assertIn("destination_extent.width, aspect, &fitted)", present)
        self.assertIn("destination_width = fitted.width;", present)
        self.assertIn("destination_height = fitted.height;", present)
        # SurfaceControl keeps the working orientation. The native helper
        # compensates only the portrait-buffer to landscape-View axis scales;
        # it must not rotate or exchange the ordinary source blit's axes.
        self.assertIn("blit.srcOffsets[0].x = (int32_t)source_x;", present)
        self.assertIn("blit.srcOffsets[0].y = (int32_t)source_y;", present)
        self.assertIn("LUCENT_SCREEN_BOTTOM,\n                "
                      "backend->secondary_clockwise_quarter_turn,", self.backend)
        primary = body(self.backend, "static bool record_present_commands(",
                       "lucent_android_vulkan_backend *lucent_android_vulkan_create(")
        self.assertIn("source_width, source_height, crop, false,", primary)
        secondary_swapchain = body(
            self.backend, "static bool create_secondary_swapchain(",
            "static void destroy_secondary_swapchain")
        self.assertIn("VK_SURFACE_TRANSFORM_IDENTITY_BIT_KHR",
                      secondary_swapchain)
        self.assertIn("capabilities.supportedTransforms", secondary_swapchain)
        self.assertIn("secondary swapchain window=%dx%d extent=%ux%u logical=%ux%u",
                      secondary_swapchain)
        primary_swapchain = body(
            self.backend, "static bool create_swapchain(",
            "static void destroy_swapchain")
        self.assertIn("VK_SURFACE_TRANSFORM_IDENTITY_BIT_KHR",
                      primary_swapchain)
        self.assertIn("primary surface lacks identity pre-transform",
                      primary_swapchain)
        self.assertNotIn("info.preTransform = capabilities.currentTransform",
                         primary_swapchain)

    def test_3ds_touch_targets_the_exact_side_by_side_viewport(self):
        mapping = LAYOUT.read_text(encoding="utf-8")
        self.assertIn("threeDsSideBySidePointerX", mapping)
        self.assertIn("(5f + clamped * 4f) / 9f", mapping)
        self.assertIn("threeDsSideBySidePointerY", mapping)
        touch = body(self.session, "@Override public void onSecondaryTouch(",
                     "@Override public void resume()")
        self.assertIn("threeDsSideBySidePointerX(normalizedX)", touch)
        self.assertIn("threeDsSideBySidePointerY(normalizedY)", touch)


class DualScreenStartOrderTest(unittest.TestCase):
    """A Phase 3 engine learns about its second window ONLY at start().

    Cemu binds canvas_pad, sets pad_open and builds the GamePad swapchain inside
    adapter_start, from the lower window it was handed there. Nothing about the
    render loop guarantees that window exists yet: the primary Surface belongs
    to this window's SurfaceView while the secondary belongs to a SurfaceView in
    the lower display's Activity, and the request for the second one is only
    posted to that Activity's UI thread as prepare() finishes. Measured on the
    Thor it lands about 9 ms later — inside the window start() itself occupies.

    Lose that race and the failure is silent and permanent: start() takes its
    single-window branch and the GamePad view never shows guest output again for
    the whole session, because onSecondarySurfaceAvailable forwards nothing
    while `started` is still false. These tests pin the ordering rule that makes
    it deterministic, and the bound that keeps it from ever hanging a launch.
    """

    @classmethod
    def setUpClass(cls):
        cls.source = NATIVE_ADAPTER.read_text(encoding="utf-8")
        cls.loop = body(cls.source, "private void renderLoop()", "@Override public void attachSurface")
        cls.loop_code = code(cls.loop)

    def test_start_waits_for_an_accepted_secondary_surface(self):
        # The gate must be checked BEFORE start(), not after it.
        gate = self.loop_code.index("secondaryReadyToStart()")
        start = self.loop_code.index("active.start(")
        self.assertLess(gate, start,
                        "start() no longer waits for the GamePad view")
        ready = code(body(self.source, "private boolean secondaryReadyToStart()",
                          "private String describeSecondary"))
        # Single-screen sessions must not pay for this at all.
        self.assertIn("if (!secondaryDisplayRequested) return true;", ready,
                      "the wait must apply only when a second display was accepted")
        self.assertIn("lower.isValid()", ready,
                      "an invalid Surface must not satisfy the wait")

    def test_the_wait_is_bounded_and_falls_back_to_a_single_window(self):
        # A second display that never produces a Surface must never hang a
        # launch; it must degrade to exactly the old single-window behaviour.
        self.assertRegex(self.source,
                         r"SECONDARY_SURFACE_WAIT_MS\s*=\s*[0-9_]+L;",
                         "the wait for the GamePad view is unbounded")
        ready = code(body(self.source, "private boolean secondaryReadyToStart()",
                          "private String describeSecondary"))
        self.assertIn("SECONDARY_SURFACE_WAIT_MS) return false;", ready,
                      "the wait no longer expires")
        # After the bound, the answer is yes — never a permanent park.
        self.assertTrue(ready.rstrip().rstrip("}").rstrip().endswith("return true;"),
                        "an expired wait must start the session single-window")

    def test_a_surface_arriving_during_start_is_still_bound(self):
        # start() reads the lower Surface once, and it is a long call (Vulkan
        # device, swapchains, title launch). A Surface published while it ran
        # would otherwise be dropped: the callback forwards nothing until
        # `started` is true, and by then start() has taken its copy.
        self.assertIn("Surface lower = secondarySurface;", self.loop_code)
        self.assertIn("active.start(current, lower);", self.loop_code,
                      "start() must use the surface the wait actually observed")
        reconcile = self.loop_code.split("started = true;", 1)[1]
        self.assertIn("Surface latest = secondarySurface;", reconcile)
        self.assertIn("if (latest != lower", reconcile)
        self.assertIn("rebindNativeSurface(active, current, latest);", reconcile,
                      "a Surface that arrived during start() is never bound")

    def test_a_late_surface_is_still_delivered_once_started(self):
        # The other half of the same guarantee, for a Surface that arrives after
        # the bound expired and the session already started single-window.
        available = code(body(self.source,
                              "public void onSecondarySurfaceAvailable(",
                              "public void onSecondarySurfaceDestroyed"))
        self.assertIn("secondarySurface = value;", available)
        self.assertIn("rebindNativeSurface(active, current, value)", available,
                      "a late GamePad Surface would never reach the engine")


if __name__ == "__main__":
    unittest.main()


class LowerPanelCadenceTest(unittest.TestCase):
    """The lower-panel generator receives the core cadence at surface attach
    and on every pacing change, and goes direct the moment the clock arrives."""

    def test_session_publishes_lower_cadence_and_generator_goes_direct(self):
        session = LIBRETRO.read_text(encoding="utf-8")
        attach = body(session, "public void onSecondarySurfaceAvailable(",
                      "public void onSecondarySurfaceDestroyed(")
        self.assertIn("publishLowerSourceCadence();", attach)
        publish = body(session, "private void publishLowerSourceCadence(",
                       "public void onSecondarySurfaceDestroyed(")
        self.assertIn("FrameGenerationRendererRegistry.find(lower)", publish)
        self.assertIn("generator.setAuthoritativeSourceHz(hz)", publish)
        self.assertGreaterEqual(session.count("publishLowerSourceCadence();"), 3)
        generator = (ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" /
                     "game" / "DisplayFrameGenerator.java").read_text(encoding="utf-8")
        hz = body(generator, "public void setAuthoritativeSourceHz(", "resetEndpointFifo();")
        self.assertIn("if (displayId > 0) {", hz)
        self.assertIn("frameRate.setGenerationAvailable(false);", hz)
        adapter = (GAME / "NativeAdapterEngineSession.java").read_text(encoding="utf-8")
        self.assertIn("publishLowerSourceCadence();", body(adapter,
                      "public void onSecondarySurfaceAvailable(", "public void onSecondarySurfaceDestroyed("))
        adapter_publish = body(adapter, "private void publishLowerSourceCadence(",
                               "public void onSecondarySurfaceDestroyed(")
        # Native VI/submission counters are not image-linked source authority.
        self.assertIn("generator.setAuthoritativeSourceHz(0.0)", adapter_publish)
        self.assertIn("generator.setProducerTimelineHz(producerTimelineHz)", adapter_publish)
        self.assertIn("generator.setSlotLatticeProducer(producerTimelineHz > 0.0)", adapter_publish)
        self.assertNotIn("declaredVideoHz()", adapter_publish)
