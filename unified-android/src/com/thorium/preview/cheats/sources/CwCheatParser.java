package com.thorium.preview.cheats.sources;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * CWCheat {@code cheat.db}: {@code _S SERIAL}, {@code _G Title}, {@code _C0 Name}
 * (or {@code _C1} when shipped enabled) and {@code _L 0xADDR 0xVALUE} lines.
 * The code keeps its {@code _L} lines joined by '+', which PPSSPP's libretro
 * front end splits and rewrites into its own cheat file verbatim.
 */
public final class CwCheatParser {
    public static final class Game {
        public final String serial;
        public String title = "";
        public final List<ParsedCheat> cheats = new ArrayList<>();
        Game(String serial) { this.serial = serial; }
    }

    private CwCheatParser() {}

    public static Map<String, Game> parse(String text) {
        Map<String, Game> games = new LinkedHashMap<>();
        Game game = null;
        String name = null;
        List<String> lines = new ArrayList<>();
        for (String raw : CodeText.lines(text)) {
            String line = raw.trim();
            if (line.isEmpty()) continue;
            if (line.startsWith("_S")) {
                flush(game, name, lines);
                name = null; lines = new ArrayList<>();
                String serial = normaliseSerial(line.substring(2).trim());
                if (serial.isEmpty() || serial.startsWith(".")) { game = null; continue; }
                game = games.get(serial);
                if (game == null) { game = new Game(serial); games.put(serial, game); }
                continue;
            }
            if (game == null) continue;
            if (line.startsWith("_G")) {
                if (game.title.isEmpty()) game.title = line.substring(2).trim();
                continue;
            }
            if (line.startsWith("_C")) {
                flush(game, name, lines);
                name = line.replaceFirst("^_C[0-9]*\\s*", "").trim();
                lines = new ArrayList<>();
                continue;
            }
            if (line.startsWith("_L") && name != null) {
                String body = line.substring(2).trim();
                String cleaned = CodeText.clean(body);
                if (!cleaned.isEmpty()) lines.add("_L " + cleaned);
            }
        }
        flush(game, name, lines);
        return games;
    }

    /** {@code ULUS-10041}, {@code ULUS10041} and {@code ulus_10041} all become {@code ULUS-10041}. */
    public static String normaliseSerial(String value) {
        if (value == null) return "";
        String clean = value.trim().toUpperCase(Locale.US);
        java.util.regex.Matcher match = java.util.regex.Pattern
                .compile("([A-Z]{4})[-_ ]?([0-9]{5})").matcher(clean);
        if (match.find()) return match.group(1) + "-" + match.group(2);
        return clean;
    }

    private static void flush(Game game, String name, List<String> lines) {
        if (game == null || name == null || lines.isEmpty()) return;
        if (game.cheats.size() >= CodeText.MAX_CHEATS_PER_GAME) return;
        String code = CodeText.join(lines, "+");
        if (code.isEmpty() || CodeText.hasUnresolvedVariable(code)) return;
        game.cheats.add(new ParsedCheat(name, "", code, ParsedCheat.impliedTags(name)));
    }
}
