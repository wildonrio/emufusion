package com.thorium.preview.cheats.delivery;

import java.util.Locale;

/** The boot writer for a packaged engine, or null when it has none. */
public final class BootCheatWriters {
    private BootCheatWriters() {}

    public static BootCheatWriter forEngine(String engineId) {
        switch (engineId == null ? "" : engineId.trim().toLowerCase(Locale.US)) {
            case "dolphin": return new DolphinGameSettingsWriter();
            case "ppsspp": return new PpssppCheatWriter();
            case "armsx2": return new Pcsx2PnachWriter();
            case "azahar": return new AzaharCheatWriter();
            case "eden": return new EdenCheatWriter();
            case "aps3e": return new Aps3ePatchWriter();
            case "cemu": return new CemuGraphicPackWriter();
            case "flycast": return new FlycastCheatWriter();
            default: return null;
        }
    }
}
