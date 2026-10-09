package com.thorium.lucent.metadata;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;

/** Converts frontend/library names into the canonical IDs used by engines. */
public final class EngineSystemIdResolver {
    private static final Map<String, String> ALIASES;

    static {
        LinkedHashMap<String, String> aliases = new LinkedHashMap<>();
        alias(aliases, "gamecube", "gc", "ngc", "nintendogamecube");
        alias(aliases, "3ds", "n3ds", "nintendo3ds");
        alias(aliases, "megadrive", "genesis", "segagenesis", "segamegadrive");
        alias(aliases, "nds", "ds", "nintendods");
        alias(aliases, "psx", "ps1", "playstation", "sonyplaystation");
        alias(aliases, "dreamcast", "dc", "segadreamcast");
        alias(aliases, "mastersystem", "sms", "segamastersystem", "markiii");
        alias(aliases, "pcengine", "tg16", "turbografx16");
        alias(aliases, "arcade", "mame", "fbneo", "fba", "finalburnneo");
        alias(aliases, "snes", "supernintendo", "superfamicom");
        alias(aliases, "nes", "famicom", "fc");
        alias(aliases, "windows", "win", "windows10", "pc");
        ALIASES = Collections.unmodifiableMap(aliases);
    }

    private EngineSystemIdResolver() {}

    public static String canonical(String value) {
        String normalized = normalize(value);
        String alias = ALIASES.get(normalized);
        return alias == null ? normalized : alias;
    }

    private static void alias(Map<String, String> aliases, String canonical,
                              String... values) {
        aliases.put(canonical, canonical);
        for (String value : values) aliases.put(normalize(value), canonical);
    }

    private static String normalize(String value) {
        return value == null ? "" : value.trim().toLowerCase(Locale.US)
                .replaceAll("[^a-z0-9]+", "");
    }
}
