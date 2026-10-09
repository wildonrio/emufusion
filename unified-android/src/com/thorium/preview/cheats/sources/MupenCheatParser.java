package com.thorium.preview.cheats.sources;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Mupen64Plus {@code mupencheat.txt}: {@code crc CRC1-CRC2-C:CC}, {@code gn Title},
 * {@code cn Name}, {@code cd Note}, then indented {@code ADDR VALUE} lines.
 * A line whose value is {@code ????} lists options and is not a switch.
 */
public final class MupenCheatParser {
    private static final Pattern CRC = Pattern.compile(
            "(?i)^crc\\s+([0-9A-F]{8}-[0-9A-F]{8}-C:[0-9A-F]{2})\\s*$");

    /** One game block keyed by its CRC line. */
    public static final class Game {
        public final String crc;
        public String title = "";
        public final List<ParsedCheat> cheats = new ArrayList<>();
        Game(String crc) { this.crc = crc; }
    }

    private MupenCheatParser() {}

    public static Map<String, Game> parse(String text) {
        Map<String, Game> games = new LinkedHashMap<>();
        Game game = null;
        String name = null;
        String note = "";
        List<String> codes = new ArrayList<>();
        boolean unresolved = false;
        for (String raw : CodeText.lines(text)) {
            String line = raw.trim();
            if (line.isEmpty() || line.startsWith("#") || line.startsWith("//")) continue;
            Matcher crc = CRC.matcher(line);
            if (crc.matches()) {
                flush(game, name, note, codes, unresolved);
                game = new Game(crc.group(1).toUpperCase(Locale.US));
                games.put(game.crc, game);
                name = null; note = ""; codes = new ArrayList<>(); unresolved = false;
                continue;
            }
            if (game == null) continue;
            if (line.startsWith("gn ")) { game.title = line.substring(3).trim(); continue; }
            if (line.startsWith("cn ")) {
                flush(game, name, note, codes, unresolved);
                name = line.substring(3).trim(); note = ""; codes = new ArrayList<>(); unresolved = false;
                continue;
            }
            if (line.startsWith("cd ")) { note = line.substring(3).trim(); continue; }
            if (name == null) continue;
            String[] parts = line.split("\\s+", 3);
            if (parts.length < 2) continue;
            if (parts[1].contains("?") || parts.length > 2) { unresolved = true; continue; }
            codes.add(parts[0].toUpperCase(Locale.US) + " " + parts[1].toUpperCase(Locale.US));
        }
        flush(game, name, note, codes, unresolved);
        return games;
    }

    private static void flush(Game game, String name, String note, List<String> codes,
                              boolean unresolved) {
        if (game == null || name == null || codes.isEmpty() || unresolved) return;
        if (game.cheats.size() >= CodeText.MAX_CHEATS_PER_GAME) return;
        String code = CodeText.join(codes, "+");
        if (code.isEmpty() || CodeText.hasUnresolvedVariable(code)) return;
        game.cheats.add(new ParsedCheat(name, note, code, ParsedCheat.impliedTags(name)));
    }
}
