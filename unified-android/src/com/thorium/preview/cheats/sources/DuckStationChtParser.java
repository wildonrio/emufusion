package com.thorium.preview.cheats.sources;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * DuckStation chtdb {@code SERIAL.cht}: {@code [Name]} sections with
 * {@code Type = Gameshark}, {@code Activation = EndFrame|Manual},
 * {@code Author}, {@code Description}, optional {@code Option}/{@code OptionRange}
 * and raw {@code 8009XXXX 0001} code lines (legacy files carry {@code Codes = ...}).
 * A code that needs an option value is skipped: it is not a switch.
 */
public final class DuckStationChtParser {
    private DuckStationChtParser() {}

    public static List<ParsedCheat> parse(String text) {
        List<ParsedCheat> result = new ArrayList<>();
        String name = null;
        String type = "";
        String description = "";
        String group = "";
        boolean hasOptions = false;
        List<String> codes = new ArrayList<>();
        for (String raw : CodeText.lines(text)) {
            String line = raw.trim();
            if (line.isEmpty() || line.startsWith("#") || line.startsWith(";")) continue;
            if (line.startsWith("[") && line.endsWith("]")) {
                flush(result, name, type, description, group, hasOptions, codes);
                name = line.substring(1, line.length() - 1).trim();
                type = ""; description = ""; group = ""; hasOptions = false;
                codes = new ArrayList<>();
                continue;
            }
            int eq = line.indexOf('=');
            if (eq > 0 && !CodeText.isHexPairLine(line)) {
                String key = line.substring(0, eq).trim().toLowerCase(Locale.US);
                String value = line.substring(eq + 1).trim();
                if ("type".equals(key)) type = value;
                else if ("description".equals(key)) description = value;
                else if ("group".equals(key)) group = value;
                else if ("codes".equals(key)) {
                    for (String piece : value.split("\\s*[+,]\\s*|\\s{2,}"))
                        if (!piece.trim().isEmpty()) codes.add(piece.trim());
                } else if ("option".equals(key) || "optionrange".equals(key)) hasOptions = true;
                continue;
            }
            if (name != null && CodeText.clean(line).length() > 0) codes.add(line);
        }
        flush(result, name, type, description, group, hasOptions, codes);
        return result;
    }

    private static void flush(List<ParsedCheat> into, String name, String type, String description,
                              String group, boolean hasOptions, List<String> codes) {
        if (name == null || codes.isEmpty() || hasOptions) return;
        if (into.size() >= CodeText.MAX_CHEATS_PER_GAME) return;
        String code = CodeText.join(codes, "+");
        if (code.isEmpty() || CodeText.hasUnresolvedVariable(code)) return;
        List<String> tags = ParsedCheat.impliedTags(name, group);
        if (!type.isEmpty()) tags.add(type.toLowerCase(Locale.US));
        if (!group.isEmpty()) tags.add(ParsedCheat.groupTag(group));
        into.add(new ParsedCheat(name, description, code, tags));
    }
}
