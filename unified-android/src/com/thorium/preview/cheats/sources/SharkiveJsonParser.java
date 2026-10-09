package com.thorium.preview.cheats.sources;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * FlagBrew Sharkive bundles: {@code 3ds.json} is {@code {titleId: {name: [lines]}}}
 * and {@code switch.json} is {@code {titleId: {buildId: {name: [lines]}}}}.
 * Title and build ids are compared upper-case.
 */
public final class SharkiveJsonParser {
    private SharkiveJsonParser() {}

    /** 3DS: title id → cheats. */
    public static Map<String, List<ParsedCheat>> parse3ds(String text) {
        Map<String, List<ParsedCheat>> result = new LinkedHashMap<>();
        Map<String, Object> root = JsonLite.parseObject(text);
        for (Map.Entry<String, Object> title : root.entrySet()) {
            List<ParsedCheat> cheats = cheatsOf(JsonLite.object(title.getValue()));
            if (!cheats.isEmpty()) result.put(title.getKey().toUpperCase(Locale.US), cheats);
        }
        return result;
    }

    /** Only the one title, without materialising the others. */
    public static List<ParsedCheat> for3dsTitle(String text, String titleId) {
        if (titleId == null || titleId.isEmpty()) return new ArrayList<>();
        Map<String, Object> root = JsonLite.parseObject(text);
        for (Map.Entry<String, Object> title : root.entrySet())
            if (title.getKey().equalsIgnoreCase(titleId))
                return cheatsOf(JsonLite.object(title.getValue()));
        return new ArrayList<>();
    }

    /** Switch: build id → cheats for one title. */
    public static Map<String, List<ParsedCheat>> forSwitchTitle(String text, String titleId) {
        Map<String, List<ParsedCheat>> result = new LinkedHashMap<>();
        if (titleId == null || titleId.isEmpty()) return result;
        Map<String, Object> root = JsonLite.parseObject(text);
        for (Map.Entry<String, Object> title : root.entrySet()) {
            if (!title.getKey().equalsIgnoreCase(titleId)) continue;
            for (Map.Entry<String, Object> build : JsonLite.object(title.getValue()).entrySet()) {
                List<ParsedCheat> cheats = cheatsOf(JsonLite.object(build.getValue()));
                if (!cheats.isEmpty()) result.put(build.getKey().toUpperCase(Locale.US), cheats);
            }
        }
        return result;
    }

    private static List<ParsedCheat> cheatsOf(Map<String, Object> byName) {
        List<ParsedCheat> cheats = new ArrayList<>();
        for (Map.Entry<String, Object> entry : byName.entrySet()) {
            List<String> lines = new ArrayList<>();
            if (entry.getValue() instanceof String) {
                lines.addAll(CodeText.lines((String) entry.getValue()));
            } else {
                for (Object line : JsonLite.array(entry.getValue())) lines.add(JsonLite.string(line));
            }
            ParsedCheat cheat = DmntCheatParser.single(entry.getKey(), lines);
            if (cheat != null) cheats.add(cheat);
            if (cheats.size() >= CodeText.MAX_CHEATS_PER_GAME) break;
        }
        return cheats;
    }
}
