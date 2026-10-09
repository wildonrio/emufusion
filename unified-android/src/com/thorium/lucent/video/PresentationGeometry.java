package com.thorium.lucent.video;

import com.thorium.lucent.metadata.EngineSystemIdResolver;

import java.util.Collections;
import java.util.HashMap;
import java.util.Map;

/**
 * Where an emulated picture is drawn inside the space EmuFusion gives it.
 *
 * <p>One rule, for every engine: the picture keeps its real display aspect and
 * is scaled uniformly until it is <em>flush with the top and bottom edges</em>,
 * with black pillars filling whatever is left at the sides. It is never
 * stretched unevenly and no source pixel is placed outside the surface. Every
 * supported top-panel aspect is at most 16:9, so it remains full-height on the
 * Thor. If a future engine reports something wider than the physical panel,
 * containment wins over cropping: the complete picture remains visible.
 *
 * <h2>Aspect authority</h2>
 *
 * <p>The running engine's display aspect is authoritative because it is the
 * only component that can know the current game's region and video mode. The
 * frontend never replaces a plausible engine report with a system-wide ratio.
 * A small hardware table exists only as a last-resort display-aspect fallback
 * for a core that reports no aspect at all; raw frame dimensions remain the
 * final fallback.
 *
 * <ul>
 *   <li><b>The frame's pixel dimensions.</b> Wrong for most consoles. Console
 *       pixels are rarely square: a Mega Drive frame is 320x224 but the machine
 *       drew it on a 4:3 television, so scaling by 320/224 makes the picture
 *       7% too wide -- stretched left and right relative to up and down, which
 *       is exactly the fault this class exists to prevent. The SNES (256x239)
 *       and NES (256x240) are 25% out the other way.</li>
 *   <li><b>The aspect the engine reports.</b> This wins whenever plausible,
 *       including when a game changes modes at runtime.</li>
 *   <li><b>The display the hardware normally drove.</b> Used only when the
 *       engine supplies no usable answer.</li>
 * </ul>
 *
 * <p>All scaling is uniform and contained. Neither the table nor the fit code
 * authorizes cropping, stretching, or forcing a widescreen mode.
 */
public final class PresentationGeometry {
    /** An axis-aligned destination rectangle in surface pixels. */
    public static final class Rectangle {
        public final int left;
        public final int top;
        public final int right;
        public final int bottom;

        Rectangle(int left, int top, int right, int bottom) {
            this.left = left;
            this.top = top;
            this.right = right;
            this.bottom = bottom;
        }

        public int width() { return right - left; }
        public int height() { return bottom - top; }

        @Override public boolean equals(Object other) {
            if (this == other) return true;
            if (!(other instanceof Rectangle)) return false;
            Rectangle that = (Rectangle) other;
            return left == that.left && top == that.top &&
                    right == that.right && bottom == that.bottom;
        }

        @Override public int hashCode() {
            return ((left * 31 + top) * 31 + right) * 31 + bottom;
        }

        @Override public String toString() {
            return "Rectangle[" + left + "," + top + " " + width() + "x" +
                    height() + "]";
        }
    }

    /** Below this an engine's report is noise; above it, a decoding mistake. */
    private static final float MINIMUM_PLAUSIBLE_ASPECT = 0.1f;
    private static final float MAXIMUM_PLAUSIBLE_ASPECT = 10f;

    private static final float TELEVISION = 4f / 3f;
    private static final float WIDESCREEN = 16f / 9f;

    private static final Map<String, Float> DISPLAY_ASPECTS;
    static {
        Map<String, Float> aspects = new HashMap<>();
        // Consoles that were plugged into a television and predate widescreen
        // entirely. Every one of these drew a non-square pixel and was
        // displayed 4:3 whatever its line count or video mode was, so the
        // frame's own dimensions must be ignored. A console that can select
        // true widescreen per game does not belong here -- see the class
        // comment.
        for (String television : new String[] {
                "n64", "snes", "megadrive", "segacd", "sega32x", "mastersystem",
                "sg1000", "colecovision", "intellivision", "odyssey2",
                "atari2600", "atari5200", "atari7800", "pcengine", "pcenginecd",
                "neogeo", "neogeocd", "msx", "saturn", "3do", "jaguar", "cdi",
                "pcfx" })
            aspects.put(television, TELEVISION);
        // Handheld panels. Their pixels are square, so the panel aspect and the
        // pixel aspect agree -- these entries exist so that a core reporting
        // something else (a 4:3 "television" default, say) cannot stretch a
        // handheld that never had a television to be displayed on.
        aspects.put("gb", 10f / 9f);          // 160x144
        aspects.put("gbc", 10f / 9f);         // 160x144
        aspects.put("gamegear", 10f / 9f);    // 160x144
        aspects.put("gba", 3f / 2f);          // 240x160
        // A DS frame is two 256x192 screens stacked into one image. The aspect
        // fallback is one screen's. A single-screen device explicitly supplies
        // the 8:3 aspect of its side-by-side composite instead.
        aspects.put("nds", TELEVISION);       // 256x192 per screen
        aspects.put("3ds", 5f / 3f);          // 400x240 top panel (n3ds alias)
        // Fixed widescreen panels. Given as the panel's own ratio rather than
        // rounded to 16:9, because the PSP and Vita panels are 30:17 and being
        // truthful costs nothing.
        aspects.put("psp", 480f / 272f);
        aspects.put("psvita", 960f / 544f);
        aspects.put("switch", WIDESCREEN);    // 1280x720 handheld, 1080p docked
        aspects.put("wiiu", WIDESCREEN);
        DISPLAY_ASPECTS = Collections.unmodifiableMap(aspects);

        // These entries are fallbacks only. A plausible per-game engine report
        // always wins. NES is deliberately absent: Mesen's Auto mode reports the corrected
        // NTSC/PAL display aspect for the running region; forcing a universal
        // 4:3 box makes NTSC titles visibly too wide. N64 stays at its native
        // 4:3 default until EmuFusion has an audited per-title allow-list for
        // games whose own menus enable a genuine anamorphic widescreen mode.
    }

    private PresentationGeometry() {}

    /**
     * The display aspect that belongs to a system's hardware, or {@code 0} when
     * the system has no single answer and the running engine must be asked.
     *
     * @param systemId a canonical or frontend-alias system id ("genesis" and
     *                 "megadrive" both resolve)
     */
    public static float systemDisplayAspect(String systemId) {
        Float aspect = DISPLAY_ASPECTS.get(EngineSystemIdResolver.canonical(systemId));
        return aspect == null ? 0f : aspect;
    }

    /** True when {@link #systemDisplayAspect} answers for this system. */
    public static boolean hasFixedDisplayAspect(String systemId) {
        return systemDisplayAspect(systemId) > 0f;
    }

    /**
     * Picks the aspect a frame must be drawn at.
     *
     * <p>The engine's own report wins, then the hardware fallback table, then
     * the frame's pixel dimensions.
     *
     * @param systemId     canonical or alias system id
     * @param engineAspect the display aspect the running engine reported for
     *                     <em>this exact source rectangle</em>, or 0 for none.
     *                     Pass 0 when the source is a crop of a larger frame:
     *                     an engine reports the aspect of the whole picture,
     *                     which is not the aspect of half of it.
     * @param pixelWidth   width of the source rectangle in pixels
     * @param pixelHeight  height of the source rectangle in pixels
     */
    public static float resolveAspect(String systemId, float engineAspect,
                                      int pixelWidth, int pixelHeight) {
        if (isPlausible(engineAspect)) return engineAspect;
        float fixed = systemDisplayAspect(systemId);
        if (fixed > 0f) return fixed;
        if (pixelWidth > 0 && pixelHeight > 0)
            return (float) pixelWidth / (float) pixelHeight;
        return 0f;
    }

    private static boolean isPlausible(float aspect) {
        return aspect > MINIMUM_PLAUSIBLE_ASPECT && aspect < MAXIMUM_PLAUSIBLE_ASPECT
                && !Float.isNaN(aspect) && !Float.isInfinite(aspect);
    }

    /**
     * The full-height centred rectangle of the given aspect.
     *
     * <p>Flush with the top and bottom edges, pillarboxed at the sides, for
     * every aspect no wider than the surface. A picture wider than the surface
     * is instead fitted to the width so the complete source remains visible.
     * The surface dimensions are always the real ones measured at runtime;
     * nothing here assumes 1920x1080.
     *
     * @param aspect display aspect (width / height); a non-positive value means
     *               "unknown", and fills the surface rather than guessing
     */
    public static Rectangle fit(int surfaceWidth, int surfaceHeight, float aspect) {
        if (surfaceWidth < 1 || surfaceHeight < 1)
            return new Rectangle(0, 0, Math.max(0, surfaceWidth),
                    Math.max(0, surfaceHeight));
        if (!isPlausible(aspect))
            return new Rectangle(0, 0, surfaceWidth, surfaceHeight);
        int height = surfaceHeight;
        int width = Math.round(height * aspect);
        if (width > surfaceWidth) {
            width = surfaceWidth;
            height = Math.round(width / aspect);
        }
        if (width < 1) width = 1;
        if (height < 1) height = 1;
        int left = (surfaceWidth - width) / 2;
        int top = (surfaceHeight - height) / 2;
        return new Rectangle(left, top, left + width, top + height);
    }

    /**
     * Fits the complete picture inside the surface without cropping either
     * axis.  This is intentionally reserved for a secondary physical display:
     * unlike the primary panel's full-height presentation rule, losing the
     * left and right edges of a DS/3DS touch screen makes controls and gameplay
     * inaccessible.  Any unused pixels remain black and the aspect is exact.
     */
    public static Rectangle fitInside(int surfaceWidth, int surfaceHeight,
                                      float aspect) {
        if (surfaceWidth < 1 || surfaceHeight < 1)
            return new Rectangle(0, 0, Math.max(0, surfaceWidth),
                    Math.max(0, surfaceHeight));
        if (!isPlausible(aspect))
            return new Rectangle(0, 0, surfaceWidth, surfaceHeight);
        int width = surfaceWidth;
        int height = Math.round(width / aspect);
        if (height > surfaceHeight) {
            height = surfaceHeight;
            width = Math.round(height * aspect);
        }
        width = Math.max(1, width);
        height = Math.max(1, height);
        int left = (surfaceWidth - width) / 2;
        int top = (surfaceHeight - height) / 2;
        return new Rectangle(left, top, left + width, top + height);
    }

    public static Rectangle fitFrameInside(int surfaceWidth, int surfaceHeight,
                                           String systemId, float engineAspect,
                                           int pixelWidth, int pixelHeight) {
        // The 3DS has unlike physical panels: 400x240 (5:3) on top and
        // 320x240 (4:3) below.  This method is used only for the secondary
        // physical display, so the system-wide top-panel entry must not win
        // over the exact lower-frame dimensions.  DS panels are both 4:3 and
        // naturally take the same path.
        if ("3ds".equals(EngineSystemIdResolver.canonical(systemId)) &&
                pixelWidth > 0 && pixelHeight > 0)
            return fitInside(surfaceWidth, surfaceHeight,
                    (float) pixelWidth / (float) pixelHeight);
        return fitInside(surfaceWidth, surfaceHeight,
                resolveAspect(systemId, engineAspect, pixelWidth, pixelHeight));
    }

    /**
     * Convenience for the common case: resolve the aspect, then fit it.
     *
     * @see #resolveAspect(String, float, int, int)
     * @see #fit(int, int, float)
     */
    public static Rectangle fitFrame(int surfaceWidth, int surfaceHeight,
                                     String systemId, float engineAspect,
                                     int pixelWidth, int pixelHeight) {
        return fit(surfaceWidth, surfaceHeight,
                resolveAspect(systemId, engineAspect, pixelWidth, pixelHeight));
    }
}
