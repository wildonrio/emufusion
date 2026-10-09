package com.thorium.preview.cheats.sources;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * RetroArch {@code .cht}: {@code cheatN_desc = "..."} / {@code cheatN_code = "..."}.
 * Mirrors {@code CheatArchive}'s reader, which is package-private there.
 */
public final class RetroArchChtParser {
    private static final Pattern FIELD = Pattern.compile(
            "^\\s*cheat([0-9]+)_(desc|code)\\s*=\\s*(.*?)\\s*$", Pattern.CASE_INSENSITIVE);

    private RetroArchChtParser() {}

    public static List<ParsedCheat> parse(String text) {
        Map<Integer, String> descriptions = new HashMap<>();
        Map<Integer, String> codes = new HashMap<>();
        for (String line : CodeText.lines(text)) {
            Matcher match = FIELD.matcher(line);
            if (!match.matches()) continue;
            int index;
            try { index = Integer.parseInt(match.group(1)); }
            catch (NumberFormatException ignored) { continue; }
            String value = CodeText.unquote(match.group(3));
            if ("desc".equalsIgnoreCase(match.group(2))) descriptions.put(index, value);
            else codes.put(index, value);
        }
        List<Integer> order = new ArrayList<>(codes.keySet());
        Collections.sort(order);
        List<ParsedCheat> result = new ArrayList<>();
        for (Integer index : order) {
            String code = CodeText.clean(codes.get(index));
            if (code.isEmpty() || CodeText.hasUnresolvedVariable(code)) continue;
            String name = descriptions.get(index);
            if (name == null || name.trim().isEmpty()) name = "Cheat " + (index + 1);
            result.add(new ParsedCheat(name, "", code, ParsedCheat.impliedTags(name)));
            if (result.size() >= CodeText.MAX_CHEATS_PER_GAME) break;
        }
        return result;
    }
}
