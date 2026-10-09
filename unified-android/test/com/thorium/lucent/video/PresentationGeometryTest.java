package com.thorium.lucent.video;

import com.thorium.lucent.TestSupport;

/**
 * The scaling contract: proportional, flush with the top and bottom, black
 * pillars at the sides, never distorted, and never placed outside its surface.
 */
public final class PresentationGeometryTest {
    private static final int PANEL_WIDTH = 1920;
    private static final int PANEL_HEIGHT = 1080;
    // Deliberately not 1080: the QML canvas can report a short window, and no
    // part of the rule may depend on a particular panel size.
    private static final int SHORT_PANEL_HEIGHT = 1025;

    public static void main(String[] args) {
        engineAspectAlwaysWinsOverSystemFallback();
        representativeSystemsFillTheHeight();
        aShortWindowIsStillFlush();
        aspectAuthorityOrder();
        widePicturesRemainWhollyVisible();
        secondaryScreensAreContainedWithoutCropping();
        dolphinTransportSizeDoesNotOverrideGameAspect();
        degenerateInputsAreSafe();
        System.out.println("PresentationGeometryTest passed");
    }

    private static void dolphinTransportSizeDoesNotOverrideGameAspect() {
        for (String system : new String[] {"wii", "gamecube"}) {
            for (int transportHeight : new int[] {480, 528, 576}) {
                for (float aspect : new float[] {4f / 3f, 16f / 9f}) {
                    PresentationGeometry.Rectangle box = PresentationGeometry.fitFrame(
                            PANEL_WIDTH, PANEL_HEIGHT, system, aspect, 640, transportHeight);
                    TestSupport.equal(aspect > 1.5f ? 1920 : 1440, box.width(),
                            system + " uses the declared aspect, not EFB transport pixels");
                    TestSupport.equal(1080, box.height(), "Dolphin image fills available height");
                    TestSupport.equal(0, box.top, "Dolphin image is not clipped above");
                    TestSupport.equal(1080, box.bottom, "Dolphin image is not clipped below");
                }
            }
        }
    }

    /** A frontend fallback can never replace a running game's declared mode. */
    private static void engineAspectAlwaysWinsOverSystemFallback() {
        PresentationGeometry.Rectangle fallback = PresentationGeometry.fitFrame(
                PANEL_WIDTH, PANEL_HEIGHT, "megadrive", 0f, 320, 224);
        TestSupport.equal(1440, fallback.width(),
                "missing engine aspect uses the hardware fallback");

        PresentationGeometry.Rectangle reported = PresentationGeometry.fitFrame(
                PANEL_WIDTH, PANEL_HEIGHT, "megadrive", 320f / 224f, 320, 224);
        TestSupport.equal(1543, reported.width(),
                "engine-declared Genesis mode is not replaced by 4:3");
        TestSupport.equal(PANEL_HEIGHT, reported.height(),
                "engine-declared mode remains full height when it fits");

        PresentationGeometry.Rectangle changed = PresentationGeometry.fitFrame(
                PANEL_WIDTH, PANEL_HEIGHT, "megadrive", 1.549f, 320, 224);
        TestSupport.equal(1673, changed.width(),
                "runtime geometry change remains authoritative");
        // The frontend alias must resolve to the same answer as the canonical
        // id: library metadata says "genesis", engines say "megadrive".
        TestSupport.equal(
                PresentationGeometry.systemDisplayAspect("megadrive"),
                PresentationGeometry.systemDisplayAspect("genesis"),
                "genesis alias resolves to megadrive");
        // With no report, even a different backing size uses only the fallback.
        PresentationGeometry.Rectangle uncropped = PresentationGeometry.fitFrame(
                PANEL_WIDTH, PANEL_HEIGHT, "genesis", 0f, 347, 243);
        TestSupport.equal(1440, uncropped.width(), "Genesis full-border width");
        TestSupport.equal(1080, uncropped.height(), "Genesis full-border height");
    }

    /** Every representative system: proportional and flush top to bottom. */
    private static void representativeSystemsFillTheHeight() {
        // {system, pixel width, pixel height, expected drawn width}
        Object[][] cases = {
                // 256x239 pixels, 4:3 display. Scaling by pixels would draw it
                // 1157 wide -- far too narrow, the opposite fault.
                {"snes", 256, 239, 1440},
                // Mesen Auto's corrected NTSC ratio is 128:105. The previous
                // forced 4:3 destination made every NTSC NES game too wide.
                {"nes", 256, 240, 1317},
                {"n64", 320, 240, 1440},
                // Square-pixel handheld: 240x160 is genuinely 3:2.
                {"gba", 240, 160, 1620},
                // One DS screen. The stacked 256x384 composite is never shown
                // as such; each 256x192 screen is 4:3 on its own display.
                {"nds", 256, 192, 1440},
                {"n3ds", 400, 240, 1800},
                // 480x272 panel, square pixels, so 30:17 rather than 16:9.
                {"psp", 480, 272, 1906},
                // Native widescreen: fills the panel with no pillars at all.
                {"switch", 1280, 720, 1920},
                {"wiiu", 854, 480, 1920},
        };
        for (Object[] row : cases) {
            String system = (String) row[0];
            int pixelWidth = (Integer) row[1];
            int pixelHeight = (Integer) row[2];
            int expectedWidth = (Integer) row[3];
            float engineAspect = "nes".equals(system) ? 128f / 105f : 0f;
            PresentationGeometry.Rectangle box = PresentationGeometry.fitFrame(
                    PANEL_WIDTH, PANEL_HEIGHT, system, engineAspect,
                    pixelWidth, pixelHeight);
            TestSupport.equal(expectedWidth, box.width(), system + " drawn width");
            TestSupport.equal(PANEL_HEIGHT, box.height(),
                    system + " is flush with the top and bottom");
            TestSupport.equal(0, box.top, system + " touches the top edge");
            TestSupport.equal(PANEL_HEIGHT, box.bottom, system + " touches the bottom edge");
            TestSupport.truth(box.left >= 0 && box.right <= PANEL_WIDTH,
                    system + " stays inside the surface");
            TestSupport.truth(Math.abs(box.left - (PANEL_WIDTH - box.right)) <= 1,
                    system + " pillars are centred to the nearest pixel");
            // Nothing may be scaled unevenly: the drawn shape must match the
            // system's display aspect to within a rounded pixel.
            float aspect = PresentationGeometry.resolveAspect(
                    system, engineAspect, pixelWidth, pixelHeight);
            TestSupport.truth(
                    Math.abs(box.width() - box.height() * aspect) <= 1f,
                    system + " keeps its aspect exactly");
        }
    }

    /**
     * The window is whatever was measured, not 1080. A short canvas must still
     * produce a flush, undistorted picture rather than a stretched one.
     */
    private static void aShortWindowIsStillFlush() {
        PresentationGeometry.Rectangle genesis = PresentationGeometry.fitFrame(
                PANEL_WIDTH, SHORT_PANEL_HEIGHT, "genesis", 0f, 320, 224);
        TestSupport.equal(SHORT_PANEL_HEIGHT, genesis.height(),
                "short window is still flush top to bottom");
        TestSupport.equal(1367, genesis.width(), "short window Genesis width");
        // 1920x1025 is wider than 16:9, so even a Switch picture pillarboxes
        // rather than stretching to the extra width.
        PresentationGeometry.Rectangle console = PresentationGeometry.fitFrame(
                PANEL_WIDTH, SHORT_PANEL_HEIGHT, "switch", 0f, 1280, 720);
        TestSupport.equal(SHORT_PANEL_HEIGHT, console.height(),
                "widescreen console is flush in a short window");
        TestSupport.equal(1822, console.width(),
                "widescreen console pillarboxes rather than stretching");
        TestSupport.truth(console.left > 0, "a short window pillarboxes 16:9");
    }

    /** Plausible engine report, then hardware fallback, then pixels. */
    private static void aspectAuthorityOrder() {
        TestSupport.truth(PresentationGeometry.hasFixedDisplayAspect("megadrive"),
                "a televised console has a fixed display aspect");
        // Arcade cabinets are the reason the table is not universal: a vertical
        // cabinet is taller than it is wide, and only the engine knows.
        TestSupport.truth(!PresentationGeometry.hasFixedDisplayAspect("arcade"),
                "arcade aspect stays with the engine");
        TestSupport.truth(!PresentationGeometry.hasFixedDisplayAspect("dos"),
                "home computer aspect stays with the engine");
        TestSupport.truth(!PresentationGeometry.hasFixedDisplayAspect("gamecube"),
                "widescreen-capable 3D consoles stay with the engine");
        TestSupport.truth(PresentationGeometry.hasFixedDisplayAspect("n64"),
                "N64 stays native 4:3 without a per-title official override");
        TestSupport.equal(4f / 3f,
                PresentationGeometry.resolveAspect("n64", 0f, 320, 240),
                "ordinary N64 is fixed at 4:3");
        TestSupport.equal(16f / 9f,
                PresentationGeometry.resolveAspect("n64", 16f / 9f, 960, 540),
                "a running N64 mode cannot be replaced by a frontend ratio");
        TestSupport.truth(!PresentationGeometry.hasFixedDisplayAspect("nes"),
                "NES uses Mesen's region-correct pixel aspect");
        TestSupport.equal(128f / 105f,
                PresentationGeometry.resolveAspect("nes", 128f / 105f, 256, 240),
                "NTSC NES keeps Mesen's corrected native aspect");
        TestSupport.equal(0f, PresentationGeometry.systemDisplayAspect(""),
                "an unknown system has no fixed aspect");
        TestSupport.equal(0f, PresentationGeometry.systemDisplayAspect(null),
                "a null system has no fixed aspect");
        // A vertical arcade board: the engine's 3:4 report must be honoured and
        // must letterbox rather than fill the width.
        PresentationGeometry.Rectangle vertical = PresentationGeometry.fitFrame(
                PANEL_WIDTH, PANEL_HEIGHT, "arcade", 3f / 4f, 224, 288);
        TestSupport.equal(810, vertical.width(), "vertical cabinet width");
        TestSupport.equal(1080, vertical.height(), "vertical cabinet is flush");
        // No table entry and no engine report: the frame's own shape is all
        // that is left, and it must still be honoured proportionally.
        TestSupport.equal(4f / 3f,
                PresentationGeometry.resolveAspect("arcade", 0f, 320, 240),
                "pixel dimensions are the last resort");
        // Nonsense from an engine is ignored rather than obeyed.
        TestSupport.equal(4f / 3f,
                PresentationGeometry.resolveAspect("arcade", 0f, 320, 240),
                "zero engine aspect falls through");
        TestSupport.equal(1f,
                PresentationGeometry.resolveAspect("arcade", 40f, 100, 100),
                "an implausible engine aspect falls through");
        TestSupport.equal(1f,
                PresentationGeometry.resolveAspect("arcade", Float.NaN, 100, 100),
                "NaN falls through");
        // The engine outranks the table even when a fallback exists.
        TestSupport.equal(16f / 9f,
                PresentationGeometry.resolveAspect("snes", 16f / 9f, 256, 239),
                "the running game outranks the hardware fallback");
    }

    /** Wider than the surface: contain the complete picture without distortion. */
    private static void widePicturesRemainWhollyVisible() {
        PresentationGeometry.Rectangle box =
                PresentationGeometry.fit(1000, 1000, 4f);
        TestSupport.equal(1000, box.width(), "ultrawide fits the panel width");
        TestSupport.equal(250, box.height(), "ultrawide keeps its exact aspect");
        TestSupport.equal(0, box.left, "ultrawide starts on-screen");
        TestSupport.equal(1000, box.right, "ultrawide ends on-screen");
        TestSupport.equal(375, box.top, "ultrawide is vertically centred");
        TestSupport.equal(625, box.bottom, "ultrawide remains wholly visible");
    }

    private static void secondaryScreensAreContainedWithoutCropping() {
        PresentationGeometry.Rectangle ds = PresentationGeometry.fitFrameInside(
                1240, 1080, "nds", 0f, 256, 192);
        TestSupport.equal(1240, ds.width(), "DS lower screen uses full panel width");
        TestSupport.equal(930, ds.height(), "DS lower screen preserves 4:3");
        TestSupport.equal(0, ds.left, "DS lower screen is not side-cropped");
        TestSupport.equal(75, ds.top, "DS lower bars are vertically centred");

        PresentationGeometry.Rectangle threeDs = PresentationGeometry.fitFrameInside(
                1240, 1080, "n3ds", 5f / 3f, 320, 240);
        TestSupport.equal(ds, threeDs,
                "3DS lower 320x240 panel uses the same complete 4:3 fit");
    }

    private static void degenerateInputsAreSafe() {
        PresentationGeometry.Rectangle unknown =
                PresentationGeometry.fit(PANEL_WIDTH, PANEL_HEIGHT, 0f);
        TestSupport.equal(PANEL_WIDTH, unknown.width(),
                "an unknown aspect fills rather than guesses");
        TestSupport.equal(PANEL_HEIGHT, unknown.height(),
                "an unknown aspect fills rather than guesses");
        PresentationGeometry.Rectangle empty =
                PresentationGeometry.fit(0, 0, 4f / 3f);
        TestSupport.equal(0, empty.width(), "an empty surface draws nothing");
        TestSupport.equal(0, empty.height(), "an empty surface draws nothing");
        PresentationGeometry.Rectangle sliver =
                PresentationGeometry.fit(1, 4000, 4f / 3f);
        TestSupport.truth(sliver.width() >= 1 && sliver.height() >= 1,
                "a sliver surface still yields a drawable rectangle");
        TestSupport.equal(1, sliver.height(),
                "a sliver contains the picture rather than cropping it");
        TestSupport.equal(0, sliver.left, "a sliver never starts off-screen");
        TestSupport.equal(1, sliver.right, "a sliver never ends off-screen");
    }
}
