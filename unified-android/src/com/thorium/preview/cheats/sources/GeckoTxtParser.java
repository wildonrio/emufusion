package com.thorium.preview.cheats.sources;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.regex.Pattern;

/**
 * The GameHacking.org / rc24 per-game text: line 1 game ID, line 2 title, then
 * blank-line separated blocks of {@code Name [Author]}, code lines
 * ({@code XXXXXXXX YYYYYYYY}), and optional note lines. Codes are joined by '+'
 * in Dolphin's serialized form so they can be matched against its INI.
 *
 * <p>Some rc24 code lists (e.g. button-activator codes) spell an
 * unresolved-variable line with placeholder letters instead of hex digits,
 * such as {@code 2834XXXX YYYYZZZZ}. Those must still be recognised as code
 * lines -- not silently demoted to a note, which would ship a code missing a
 * line from its middle -- so {@link CodeText#hasUnresolvedVariable} sees the
 * run of X's and drops the whole cheat.
 */
public final class GeckoTxtParser {
    private static final Pattern CODE_LINE = Pattern.compile(
            "^\\s*[0-9A-Fa-fXYZ]{8}\\s+[0-9A-Fa-fXYZ]{8}\\s*$");
    private static final Pattern GAME_ID = Pattern.compile("^[A-Z0-9]{4,6}$");

    public static final class Document {
        public String gameId = "";
        public String title = "";
        public final List<ParsedCheat> cheats = new ArrayList<>();
    }

    private GeckoTxtParser() {}

    public static Document parse(String text) {
        Document document = new Document();
        List<String> lines = CodeText.lines(text);
        int index = 0;
        while (index < lines.size() && lines.get(index).trim().isEmpty()) index++;
        if (index < lines.size() && GAME_ID.matcher(lines.get(index).trim().toUpperCase(Locale.US)).matches()) {
            document.gameId = lines.get(index).trim().toUpperCase(Locale.US);
            index++;
            if (index < lines.size() && !CODE_LINE.matcher(lines.get(index)).matches()) {
                document.title = lines.get(index).trim();
                index++;
            }
        }
        String name = null;
        List<String> codes = new ArrayList<>();
        List<String> notes = new ArrayList<>();
        for (; index < lines.size(); index++) {
            String line = lines.get(index).trim();
            if (line.isEmpty()) {
                flush(document, name, codes, notes);
                name = null; codes = new ArrayList<>(); notes = new ArrayList<>();
                continue;
            }
            if (CODE_LINE.matcher(line).matches()) {
                if (name == null) name = "Code";
                codes.add(line.toUpperCase(Locale.US));
                continue;
            }
            if (name == null) name = line;
            else notes.add(line);
        }
        flush(document, name, codes, notes);
        return document;
    }

    private static void flush(Document document, String name, List<String> codes, List<String> notes) {
        if (name == null || codes.isEmpty()) return;
        if (document.cheats.size() >= CodeText.MAX_CHEATS_PER_GAME) return;
        String code = CodeText.join(codes, "+");
        if (code.isEmpty() || CodeText.hasUnresolvedVariable(code)) return;
        String author = "";
        String label = name;
        int bracket = name.lastIndexOf('[');
        if (bracket > 0 && name.endsWith("]")) {
            author = name.substring(bracket + 1, name.length() - 1).trim();
            label = name.substring(0, bracket).trim();
        }
        String note = CodeText.join(notes, " ");
        if (!author.isEmpty()) note = note.isEmpty() ? "by " + author : note + " (by " + author + ")";
        document.cheats.add(new ParsedCheat(label, note, code, ParsedCheat.impliedTags(label)));
    }
}
