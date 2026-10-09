package com.thorium.preview;

import java.util.Locale;

/** Allowlisted automatic feedback fields. Never accepts log text or device data. */
final class FeedbackDiagnostics {
    private FeedbackDiagnostics() {}

    static String systemCode(String value) {
        if (value == null) return "unknown";
        switch (value.trim().toLowerCase(Locale.ROOT)) {
            case "switch": case "nintendo switch": return "switch";
            case "wiiu": case "wii u": case "nintendo wii u": return "wiiu";
            case "ps3": case "playstation 3": return "ps3";
            case "wii": case "nintendo wii": return "wii";
            case "gamecube": case "nintendo gamecube": return "gamecube";
            case "ps2": case "playstation 2": return "ps2";
            case "psp": case "playstation portable": return "psp";
            case "dreamcast": case "sega dreamcast": return "dreamcast";
            case "3ds": case "nintendo 3ds": return "3ds";
            case "psx": case "playstation": return "psx";
            case "nds": case "ds": case "nintendo ds": return "nds";
            case "n64": case "nintendo 64": return "n64";
            case "snes": case "super nintendo": case "super nintendo entertainment system": return "snes";
            case "nes": case "nintendo entertainment system": return "nes";
            case "gb": case "game boy": return "gb";
            case "gbc": case "game boy color": return "gbc";
            case "gba": case "game boy advance": return "gba";
            case "megadrive": case "mega drive": case "sega mega drive": case "sega genesis": return "megadrive";
            case "gamegear": case "game gear": case "sega game gear": return "gamegear";
            case "pcenginecd": case "pc engine cd": return "pcenginecd";
            default: return "unknown";
        }
    }

    static String markdown(String version, long code, String system) {
        // Even unexpected metadata must not turn into an arbitrary-text channel.
        String safeVersion = version != null &&
                version.matches("[0-9]{1,6}(\\.[0-9]{1,6}){1,3}") ? version : "unknown";
        long safeCode = code >= 0 && code <= Integer.MAX_VALUE ? code : -1;
        return "- EmuFusion: " + safeVersion + " (version code " + safeCode + ")\n" +
                "- Emulated system: " + systemCode(system) + "\n";
    }
}
