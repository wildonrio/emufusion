package com.thorium.preview.game;

import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * The pure, Android-free half of {@link WidescreenHackPolicy}: which
 * mechanism produces true widescreen geometry for a system, and which
 * libretro core options select it on the packaged engine.
 *
 * <p>The table is section 7 of
 * {@code docs/cheats-everywhere-and-widescreen-design.md}. Every option key
 * and token below was verified against the vendored core sources in
 * {@code engines/build/sources} (mupen64plus-next
 * {@code libretro_core_options.h}, swanstation, armsx2 {@code Main.cpp},
 * flycast, Dolphin {@code Options.h}, PPSSPP). The native host applies an
 * override only when the token exists in the core's declared option list, so
 * a drifted key here degrades to "no change", never to a wrong value.</p>
 */
public final class WidescreenHackTable {
    /** Console renders 16:9 natively; nothing to enable. */
    public static final String NATIVE = "native";
    /** A projection/FOV hack (or a per-game patch table) in the core. */
    public static final String HACK = "hack";
    /** Only per-game 16:9 cheat codes from the catalog (owner B enables them). */
    public static final String CHEATS = "cheats";
    /** No 3D geometry to extend (2D consoles, DS, 3DS). */
    public static final String UNAVAILABLE = "unavailable";

    /** Systems the settings endpoint and theme enumerate, in display order. */
    public static final List<String> SYSTEMS = Collections.unmodifiableList(Arrays.asList(
            "n64", "psx", "ps2", "gamecube", "wii", "dreamcast", "psp",
            "wiiu", "switch", "ps3", "3ds", "nds"));

    /**
     * Systems whose widescreen comes from per-game cheat codes as well: the
     * launch hooks auto-enable "16:9"/"widescreen" catalog rows for these when
     * the hack is on (contract 3 in the design).
     */
    public static final List<String> WIDESCREEN_BY_CHEAT_SYSTEMS =
            Collections.unmodifiableList(Arrays.asList("gamecube", "wii", "psp"));

    private WidescreenHackTable() {}

    public static String normaliseSystem(String systemId) {
        return systemId == null ? "" : systemId.trim().toLowerCase(Locale.US);
    }

    public static String normaliseEngine(String engineId) {
        return engineId == null ? "" : engineId.trim().toLowerCase(Locale.US);
    }

    /** Honest availability per system; unknown systems are unavailable. */
    public static String availability(String systemId) {
        String system = normaliseSystem(systemId);
        switch (system) {
            case "n64":
            case "psx":
            case "ps2":
            case "gamecube":
            case "wii":
            case "dreamcast":
                return HACK;
            case "psp":
                return CHEATS;
            case "wiiu":
            case "switch":
            case "ps3":
                return NATIVE;
            default:
                return UNAVAILABLE;
        }
    }

    /** True when turning the hack on changes anything for this system. */
    public static boolean isHackApplicable(String systemId) {
        String availability = availability(systemId);
        return HACK.equals(availability) || CHEATS.equals(availability);
    }

    /**
     * Core-option overrides for one launch, in the order they are written.
     *
     * @param hackOn whether the widescreen hack is on for {@code systemId}
     * @return the {@code key=value} pairs; empty when the engine needs none
     */
    public static Map<String, String> coreOptionOverrides(
            String systemId, String engineId, boolean hackOn) {
        return coreOptionOverrides(systemId, engineId, hackOn, false);
    }

    /**
     * As {@link #coreOptionOverrides(String, String, boolean)}, with a flag the
     * cheat launch hooks may set when they have already enabled a per-game
     * 16:9 code for this title. Dolphin's generic projection hack is then
     * omitted so the game's own widescreen code is not widened twice.
     */
    public static Map<String, String> coreOptionOverrides(
            String systemId, String engineId, boolean hackOn,
            boolean perGameWidescreenCodeSelected) {
        LinkedHashMap<String, String> overrides = new LinkedHashMap<>();
        String system = normaliseSystem(systemId);
        String engine = normaliseEngine(engineId);
        boolean on = hackOn && isHackApplicable(system);
        switch (engine) {
            case "mupen64plus-next":
                if (on && "n64".equals(system)) {
                    // GLideN64 "adjust" mode widens the 3D projection to the
                    // 16:9 viewport and scales screen-space 2D back to 4:3.
                    overrides.put("mupen64plus-aspect", "16:9 adjusted");
                    overrides.put("mupen64plus-169screensize", "1920x1080");
                }
                break;
            case "swanstation":
                if (on && "psx".equals(system)) {
                    // GTE projection is widened to the display aspect.
                    overrides.put("swanstation_GPU_WidescreenHack", "true");
                    overrides.put("swanstation_Display_AspectRatio", "16:9");
                }
                break;
            case "armsx2":
                // The core maps armsx2_cheats to EmuCore/EnableCheats (default
                // disabled); without it owner B's per-game pnach output never
                // applies. Unconditional, like the dolphin/ppsspp cases.
                overrides.put("armsx2_cheats", "enabled");
                if (on && "ps2".equals(system)) {
                    // Per-game FOV pnach from the shipped patches.zip; the core
                    // documents 16:9 as the pairing for widescreen patches.
                    overrides.put("armsx2_widescreen_patches", "enabled");
                    overrides.put("armsx2_aspect_ratio", "16:9");
                }
                break;
            case "dolphin":
                // Live Gecko/AR toggles are refused unless internal cheats are
                // enabled; owner B's launch hooks rely on this being present.
                overrides.put("dolphin_cheats_enabled", "enabled");
                if (on && ("gamecube".equals(system) || "wii".equals(system)) &&
                        !perGameWidescreenCodeSelected)
                    overrides.put("dolphin_widescreen_hack", "enabled");
                break;
            case "flycast":
                if (on && "dreamcast".equals(system)) {
                    // The per-game table pokes each game's own FOV/aspect; the
                    // viewport expansion itself is the "hack" switch, and both
                    // are required for the table's games to render correctly.
                    // Games outside the table get the generic projection only.
                    overrides.put("reicast_widescreen_cheats", "enabled");
                    overrides.put("reicast_widescreen_hack", "enabled");
                }
                break;
            case "ppsspp":
                // CWCheat codes run once unless internal cheats stay enabled.
                overrides.put("ppsspp_cheats", "enabled");
                break;
            default:
                break;
        }
        return overrides;
    }
}
