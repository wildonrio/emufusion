package com.thorium.preview.cheats.sources;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.regex.Pattern;

/**
 * bucanero/dreamcast-cheats Markdown: a {@code # Title} heading, then
 * {@code ## Cheat name} headings (bold lines are accepted too) with raw
 * CodeBreaker/Xploder lines, fenced or not. Those files spell a code as a
 * single 16-hex-digit token ({@code BD976840C06E50C1}), not the
 * space-separated {@code XXXXXXXX YYYYYYYY} pair other sources use, and a
 * multi-word code continues on its own bare 8-hex-digit line
 * ({@code C8845C2D}); all three shapes are accepted as code lines.
 */
public final class DreamcastMarkdownParser {
    private static final Pattern CODE_LINE = Pattern.compile(
            "^\\s*(?:[0-9A-Fa-f]{16}|[0-9A-Fa-f]{8}(?:\\s+[0-9A-Fa-f]{8})?)\\s*$");

    public static final class Document {
        public String title = "";
        public final List<ParsedCheat> cheats = new ArrayList<>();
    }

    private DreamcastMarkdownParser() {}

    public static Document parse(String text) {
        Document document = new Document();
        String name = null;
        List<String> codes = new ArrayList<>();
        List<String> notes = new ArrayList<>();
        for (String raw : CodeText.lines(text)) {
            String line = raw.trim();
            if (line.isEmpty() || line.startsWith("```") || line.startsWith("---")) continue;
            if (line.startsWith("# ")) {
                if (document.title.isEmpty()) document.title = line.substring(2).trim();
                continue;
            }
            boolean heading = line.startsWith("##") ||
                    (line.startsWith("**") && line.endsWith("**") && line.length() > 4);
            if (heading) {
                flush(document, name, codes, notes);
                name = line.replaceFirst("^#+\\s*", "").replaceAll("^\\*\\*|\\*\\*$", "").trim();
                codes = new ArrayList<>(); notes = new ArrayList<>();
                continue;
            }
            if (CODE_LINE.matcher(line).matches()) {
                if (name == null) name = "Code";
                codes.add(line.toUpperCase(Locale.US));
                continue;
            }
            if (name != null && !line.startsWith("|") && !line.startsWith("<")) notes.add(line);
        }
        flush(document, name, codes, notes);
        return document;
    }

    private static void flush(Document document, String name, List<String> codes, List<String> notes) {
        if (name == null || codes.isEmpty() || document.cheats.size() >= CodeText.MAX_CHEATS_PER_GAME) return;
        String code = CodeText.join(codes, "+");
        if (code.isEmpty() || CodeText.hasUnresolvedVariable(code)) return;
        document.cheats.add(new ParsedCheat(name, CodeText.join(notes, " "), code,
                ParsedCheat.impliedTags(name)));
    }
}
