package com.thorium.preview.game;

import android.content.Context;
import android.view.Display;
import android.view.WindowManager;

import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;

/**
 * Internal render resolution matched to the screen (owner, 2026-10-10: "the
 * resolution of the games needs to match the resolution of the screen").
 *
 * <p>3.2.17 reset every hardware core to its console-native resolution
 * (Dolphin 1x, PPSSPP 480x272, Flycast/Mupen64Plus 640x480, Azahar 1x), so a
 * 1440p phone upscaled a 528-line Wii picture with a bilinear blit. Each core
 * now renders at the smallest advertised resolution that is at least the
 * panel's short side, capped at {@link #MAX_TARGET_LINES}. Values are written
 * to the launch-time core-option override file; the native host applies a
 * value only when the core advertises that exact token.
 */
final class RenderResolutionPolicy {
    /** Beyond 1440 lines the extra shading is not visible on a phone panel. */
    static final int MAX_TARGET_LINES = 1440;
    /** PS2 rendering is the heaviest per pixel; 3x keeps it smooth. */
    static final int MAX_PS2_SCALE = 3;

    private static final String[] FOUR_BY_THREE = {
            "640x480", "960x720", "1280x960", "1440x1080", "1920x1440", "2560x1920"};
    private static final String[] SIXTEEN_BY_NINE = {
            "1280x720", "1920x1080", "2560x1440", "3840x2160"};

    private RenderResolutionPolicy() {}

    static Map<String, String> coreOptionOverrides(Context context, String engineId) {
        return forScreen(engineId, screenLines(context));
    }

    /** Pure mapping, unit-tested on the host. */
    static Map<String, String> forScreen(String engineId, int screenLines) {
        Map<String, String> out = new LinkedHashMap<>();
        if (engineId == null || screenLines <= 0) return out;
        int target = Math.max(480, Math.min(MAX_TARGET_LINES, screenLines));
        switch (engineId.toLowerCase(Locale.US)) {
            case "dolphin":
                // 1x is 640x528; Dolphin's own labels: 2x for 720p, 3x for 1080p.
                out.put("dolphin_efb_scale", Integer.toString(scale(target, 528, 4)));
                break;
            case "ppsspp": {
                int k = scale(target, 272, 8);
                out.put("ppsspp_internal_resolution", (480 * k) + "x" + (272 * k));
                break;
            }
            case "flycast":
                out.put("reicast_internal_resolution", atLeast(FOUR_BY_THREE, target));
                break;
            case "mupen64plus-next":
                out.put("mupen64plus-43screensize", atLeast(FOUR_BY_THREE, target));
                out.put("mupen64plus-169screensize", atLeast(SIXTEEN_BY_NINE, target));
                break;
            case "azahar":
                // 1x is 400x240 per 3DS screen.
                out.put("citra_resolution_factor", Integer.toString(scale(target, 240, 10)));
                break;
            case "armsx2":
                // 1x is 448 lines on most titles.
                out.put("armsx2_upscale", scale(target, 448, MAX_PS2_SCALE) + "x");
                break;
            default:
                break;
        }
        return out;
    }

    /**
     * Within this fraction of the panel counts as matching it: 2x Dolphin is
     * 1056 lines on a 1080-line panel (2% short, indistinguishable), while 3x
     * shades 2.25 times as many pixels and made heavy Wii scenes miss frames
     * on the Thor.
     */
    static final double MATCH_TOLERANCE = 0.06;

    private static int scale(int target, int nativeLines, int max) {
        double needed = target * (1.0 - MATCH_TOLERANCE) / nativeLines;
        return Math.max(1, Math.min(max, (int) Math.ceil(needed)));
    }

    private static String atLeast(String[] sizes, int target) {
        double needed = target * (1.0 - MATCH_TOLERANCE);
        for (String size : sizes)
            if (Integer.parseInt(size.substring(size.indexOf('x') + 1)) >= needed) return size;
        return sizes[sizes.length - 1];
    }

    /** Short side of the display mode currently driving the main panel. */
    static int screenLines(Context context) {
        try {
            WindowManager windows = context == null ? null :
                    (WindowManager) context.getSystemService(Context.WINDOW_SERVICE);
            Display display = windows == null ? null : windows.getDefaultDisplay();
            if (display == null) return 0;
            Display.Mode mode = display.getMode();
            return Math.min(mode.getPhysicalWidth(), mode.getPhysicalHeight());
        } catch (RuntimeException unavailable) {
            return 0;
        }
    }
}
