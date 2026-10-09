package com.thorium.preview.cheats.sources;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * FBNeo {@code cheats/<romset>.ini}:
 * <pre>
 * cheat "Infinite Lives"
 * default 0
 * 0 "Disabled"
 * 1 "Enabled", 0, 0x00E0B4, 0x03
 * </pre>
 * Every non-default option that carries actions becomes a switch; a cheat
 * with several live options yields "Name: Label" rows. The code is the
 * option line verbatim, which is what a future FBNeo boot writer needs.
 */
public final class FbNeoIniParser {
    private static final Pattern CHEAT = Pattern.compile("(?i)^cheat\\s+\"(.*)\"\\s*$");
    private static final Pattern DEFAULT = Pattern.compile("(?i)^default\\s+([0-9]+)\\s*$");
    private static final Pattern OPTION = Pattern.compile("^([0-9]+)\\s+\"([^\"]*)\"\\s*(.*)$");

    private static final class Option {
        final int index; final String label; final List<String> lines = new ArrayList<>();
        Option(int index, String label, String first) {
            this.index = index; this.label = label; lines.add(first);
        }
    }

    private FbNeoIniParser() {}

    public static List<ParsedCheat> parse(String text) {
        List<ParsedCheat> result = new ArrayList<>();
        String name = null;
        int defaultIndex = 0;
        List<Option> options = new ArrayList<>();
        Option current = null;
        for (String raw : CodeText.lines(text)) {
            String line = raw.trim();
            if (line.isEmpty() || line.startsWith(";") || line.startsWith("#") || line.startsWith("//")) continue;
            Matcher cheat = CHEAT.matcher(line);
            if (cheat.matches()) {
                flush(result, name, defaultIndex, options);
                name = cheat.group(1).trim(); defaultIndex = 0; options = new ArrayList<>(); current = null;
                continue;
            }
            if (name == null) continue;
            Matcher def = DEFAULT.matcher(line);
            if (def.matches()) { defaultIndex = Integer.parseInt(def.group(1)); continue; }
            Matcher option = OPTION.matcher(line);
            if (option.matches()) {
                current = new Option(Integer.parseInt(option.group(1)), option.group(2).trim(), line);
                options.add(current);
                continue;
            }
            if (current != null && line.startsWith(",")) current.lines.add(line);
        }
        flush(result, name, defaultIndex, options);
        return result;
    }

    private static void flush(List<ParsedCheat> into, String name, int defaultIndex, List<Option> options) {
        if (name == null || options.isEmpty()) return;
        List<Option> live = new ArrayList<>();
        for (Option option : options) {
            if (option.index == defaultIndex) continue;
            String actions = option.lines.get(0).replaceFirst("^[0-9]+\\s+\"[^\"]*\"\\s*", "").trim();
            if (actions.isEmpty() && option.lines.size() == 1) continue;
            live.add(option);
        }
        for (Option option : live) {
            if (into.size() >= CodeText.MAX_CHEATS_PER_GAME) return;
            String label = live.size() == 1 ? name : name + ": " + option.label;
            String code = CodeText.join(option.lines, "\n");
            if (code.isEmpty() || CodeText.hasUnresolvedVariable(code)) continue;
            into.add(new ParsedCheat(label, "", code, ParsedCheat.impliedTags(label)));
        }
    }
}
