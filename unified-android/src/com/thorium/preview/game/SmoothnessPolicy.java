package com.thorium.preview.game;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Core options that remove emulator-side stutter without changing the image
 * (owner, 2026-10-10: no choppiness).
 *
 * <p>Dolphin's default "sync" shader compilation stalls a frame while each new
 * pipeline compiles: Thor Mario Kart Wii logged an 83 ms hold (5 frames) on
 * reaching a new area with frame generation off. "async-ubershaders" (Dolphin's
 * hybrid ubershaders) draws with a universal shader while the specialised one
 * compiles in the background: no stall and nothing skipped. Azahar keeps its
 * compiled shaders on disk so a second session does not recompile them.</p>
 */
final class SmoothnessPolicy {
    private SmoothnessPolicy() {}

    static Map<String, String> coreOptionOverrides(String engine) {
        Map<String, String> out = new LinkedHashMap<>();
        if (engine == null) return out;
        switch (engine) {
            case "dolphin":
                out.put("dolphin_shader_compilation_mode", "async-ubershaders");
                break;
            case "azahar":
                out.put("citra_use_disk_shader_cache", "enabled");
                break;
            default:
                break;
        }
        return out;
    }
}
