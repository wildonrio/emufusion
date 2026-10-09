package com.thorium.preview.cheats.sources;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

/**
 * Atmosphère dmnt / Gateway text: {@code [Name]} (or {@code {Master}}) headers
 * followed by lines of hex words. Used for Switch build-id files and 3DS
 * Gateway lists alike; the code keeps its original lines so a boot writer can
 * emit the file back verbatim.
 */
public final class DmntCheatParser {
    private static final Pattern OPCODE_LINE = Pattern.compile(
            "^\\s*(?:[0-9A-Fa-f]{8}\\s*)+$");

    private DmntCheatParser() {}

    public static List<ParsedCheat> parse(String text) {
        List<ParsedCheat> result = new ArrayList<>();
        String name = null;
        boolean master = false;
        List<String> lines = new ArrayList<>();
        for (String raw : CodeText.lines(text)) {
            String line = raw.trim();
            if (line.isEmpty() || line.startsWith("#") || line.startsWith("//")) continue;
            if ((line.startsWith("[") && line.endsWith("]")) || (line.startsWith("{") && line.endsWith("}"))) {
                flush(result, name, master, lines);
                name = line.substring(1, line.length() - 1).trim();
                master = line.startsWith("{");
                lines = new ArrayList<>();
                continue;
            }
            if (name != null && OPCODE_LINE.matcher(line).matches()) lines.add(line.toUpperCase());
        }
        flush(result, name, master, lines);
        return result;
    }

    /** Parses a whole file into one row (a Sharkive-style "cheat = list of lines"). */
    public static ParsedCheat single(String name, List<String> lines) {
        List<String> clean = new ArrayList<>();
        if (lines != null) for (String line : lines) {
            String trimmed = line == null ? "" : line.trim();
            if (!trimmed.isEmpty()) clean.add(trimmed.toUpperCase());
        }
        String code = CodeText.join(clean, "\n");
        if (code.isEmpty() || CodeText.hasUnresolvedVariable(code)) return null;
        return new ParsedCheat(name, "", code, ParsedCheat.impliedTags(name));
    }

    private static void flush(List<ParsedCheat> into, String name, boolean master, List<String> lines) {
        if (name == null || lines.isEmpty() || into.size() >= CodeText.MAX_CHEATS_PER_GAME) return;
        String code = CodeText.join(lines, "\n");
        if (code.isEmpty() || CodeText.hasUnresolvedVariable(code)) return;
        List<String> tags = ParsedCheat.impliedTags(name);
        if (master) tags.add("master");
        into.add(new ParsedCheat(name, master ? "master code" : "", code, tags));
    }
}
