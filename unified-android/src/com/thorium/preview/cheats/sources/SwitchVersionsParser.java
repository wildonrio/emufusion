package com.thorium.preview.cheats.sources;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * switch-cheats-db {@code versions.json}: {@code {titleId: {version: buildId}}}.
 * Every build id of a title is returned, because the running executable's
 * build id is only known to the emulator; the boot writer emits one file per
 * build id and Eden picks the one that matches.
 */
public final class SwitchVersionsParser {
    private static final Pattern BUILD_ID = Pattern.compile("(?i)^[0-9A-F]{16}$");

    private SwitchVersionsParser() {}

    public static List<String> buildIdsFor(String text, String titleId) {
        List<String> result = new ArrayList<>();
        if (titleId == null || titleId.isEmpty()) return result;
        Map<String, Object> root = JsonLite.parseObject(text);
        for (Map.Entry<String, Object> title : root.entrySet()) {
            if (!title.getKey().equalsIgnoreCase(titleId)) continue;
            collect(title.getValue(), result);
        }
        return result;
    }

    private static void collect(Object value, List<String> into) {
        if (value instanceof Map) {
            for (Object nested : JsonLite.object(value).values()) collect(nested, into);
        } else if (value instanceof List) {
            for (Object nested : JsonLite.array(value)) collect(nested, into);
        } else {
            String text = JsonLite.string(value).trim().toUpperCase(Locale.US);
            if (BUILD_ID.matcher(text).matches() && !into.contains(text)) into.add(text);
        }
    }
}
