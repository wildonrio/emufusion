package com.thorium.preview.cheats.delivery;

import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/**
 * Which delivery path each packaged engine actually has.
 *
 * <p>Live means the session's own retro_cheat_set override exists and is
 * source-audited (mirrors {@code LibretroEngineSession.supportsLiveCheats}
 * and {@code PpssppGlesEngineSession.supportsLiveCheats}; keep the three
 * lists in step). Boot means a {@link BootCheatWriter} exists for the engine.
 * Everything else lists its rows as unsupported so the switch is honest.
 */
public final class CheatDelivery {
    private static final Set<String> LIVE_ENGINES = new HashSet<>(Arrays.asList(
            "mesen", "mesen-s", "sameboy", "mgba", "gearsystem", "swanstation",
            "melonds-ds", "fuse", "virtualjaguar",
            "mupen64plus-next", "ppsspp", "dolphin", "flycast"));
    // flycast is absent from BOOT_ENGINES: engines/patches/
    // flycast-libretro-cheat-support.patch wires retro_cheat_set/reset to the
    // core's own CheatManager::addGameSharkCheat/enableCheat directly (live,
    // above), so a FlycastCheatWriter boot file would never be read anyway --
    // its .cht loading path (core/cheats.cpp, #ifndef LIBRETRO) is compiled
    // out. It keeps a writer only for the non-LIBRETRO desktop core; see
    // test_every_boot_engine_has_its_writer.
    private static final Set<String> BOOT_ENGINES = new HashSet<>(Arrays.asList(
            "dolphin", "ppsspp", "armsx2", "azahar", "eden", "aps3e", "cemu"));
    /** Systems whose boot files are per-game and therefore need the save directory. */
    private static final Set<String> SAVE_DIRECTORY_ENGINES = new HashSet<>(Arrays.asList(
            "dolphin", "ppsspp", "azahar"));
    private static final List<String> WIDESCREEN_BY_CHEAT_SYSTEMS =
            Collections.unmodifiableList(Arrays.asList("gamecube", "wii", "psp"));

    private CheatDelivery() {}

    public static boolean supportsLive(String engineId) {
        return LIVE_ENGINES.contains(normalise(engineId));
    }

    public static boolean supportsBoot(String engineId) {
        return BOOT_ENGINES.contains(normalise(engineId));
    }

    public static boolean needsSaveDirectory(String engineId) {
        return SAVE_DIRECTORY_ENGINES.contains(normalise(engineId));
    }

    /** Systems where the widescreen hack is a catalogue cheat rather than a core option. */
    public static boolean widescreenByCheat(String canonicalSystem) {
        return WIDESCREEN_BY_CHEAT_SYSTEMS.contains(normalise(canonicalSystem));
    }

    /**
     * The delivery a row really gets on this engine. A downloaded row may
     * claim "live" for an engine that has no live bridge, or "boot" for one
     * that has no writer; the engine's capability wins over the claim.
     */
    public static String resolve(String engineId, String claimed) {
        String engine = normalise(engineId);
        String claim = DeliveryCheat.normaliseDelivery(claimed);
        boolean live = LIVE_ENGINES.contains(engine);
        boolean boot = BOOT_ENGINES.contains(engine);
        // The downloader marks a row unsupported when it knows the packaged
        // engine cannot consume that dialect; honouring it keeps the switch honest.
        if (DeliveryCheat.UNSUPPORTED.equals(claim)) return DeliveryCheat.UNSUPPORTED;
        if (DeliveryCheat.BOOT.equals(claim)) {
            if (boot) return DeliveryCheat.BOOT;
            return live ? DeliveryCheat.LIVE : DeliveryCheat.UNSUPPORTED;
        }
        if (live) return DeliveryCheat.LIVE;
        if (boot) return DeliveryCheat.BOOT;
        return DeliveryCheat.UNSUPPORTED;
    }

    /**
     * Coarse answer for the library, which asks before an engine is chosen:
     * the delivery the system's packaged internal route provides.
     */
    public static String defaultForSystem(String canonicalSystem) {
        switch (normalise(canonicalSystem)) {
            case "nes": case "snes": case "gb": case "gbc": case "gba":
            case "mastersystem": case "gamegear": case "sg1000":
            case "psx": case "nds": case "zxspectrum": case "jaguar":
            case "n64": case "psp": case "gamecube": case "wii":
            case "dreamcast":
                return DeliveryCheat.LIVE;
            case "ps2": case "3ds": case "switch": case "ps3": case "wiiu":
                return DeliveryCheat.BOOT;
            default:
                return DeliveryCheat.UNSUPPORTED;
        }
    }

    private static String normalise(String value) {
        return value == null ? "" : value.trim().toLowerCase(Locale.US);
    }
}
