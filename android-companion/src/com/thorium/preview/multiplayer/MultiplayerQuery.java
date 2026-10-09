package com.thorium.preview.multiplayer;

import java.net.URLDecoder;
import java.util.HashMap;
import java.util.Map;

/**
 * Shared query-string parsing for the {@code /multiplayer/*} companion HTTP
 * endpoints. Mirrors {@code WidescreenHackEndpoint}'s own {@code parseQuery}
 * (same decode-per-pair, drop-malformed-pairs behavior) with one deliberate
 * difference: keys keep their original case. The widescreen-hack endpoint's
 * params are single lowercase words, so lower-casing keys is harmless there;
 * this API's contract uses camelCase params ({@code gameKey}, {@code
 * minPlayers}, {@code scheduleId}, ...) that must round-trip exactly.
 */
final class MultiplayerQuery {
    private MultiplayerQuery() {}

    static Map<String, String> parse(String query) {
        Map<String, String> values = new HashMap<>();
        if (query == null || query.isEmpty()) return values;
        for (String pair : query.split("&")) {
            if (pair.isEmpty()) continue;
            String[] item = pair.split("=", 2);
            try {
                String key = URLDecoder.decode(item[0], "UTF-8").trim();
                String value = item.length > 1 ? URLDecoder.decode(item[1], "UTF-8") : "";
                values.put(key, value);
            } catch (Exception ignored) {
                // A malformed pair is dropped; the remaining pairs still apply.
            }
        }
        return values;
    }

    static int parseInt(Map<String, String> values, String key, int fallback) {
        String raw = values.get(key);
        if (raw == null || raw.trim().isEmpty()) return fallback;
        try {
            return Integer.parseInt(raw.trim());
        } catch (NumberFormatException notNumeric) {
            return fallback;
        }
    }

    static boolean parseBool(Map<String, String> values, String key, boolean fallback) {
        String raw = values.get(key);
        if (raw == null || raw.isEmpty()) return fallback;
        return !"0".equals(raw) && !"false".equalsIgnoreCase(raw);
    }
}
