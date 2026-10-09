package com.thorium.preview.cheats.sources;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Project64 {@code Config/Cheats/<title>.cht}: a {@code [CRC1-CRC2-C:CC]} header,
 * {@code Name=Title}, then either {@code $Cheat Name} blocks with {@code Note=}
 * and {@code ADDR VALUE} lines, or legacy {@code CheatN="Name",ADDR VALUE,...}
 * rows with {@code CheatN_N=note} and {@code CheatN_O=options}.
 */
public final class Project64ChtParser {
    private static final Pattern HEADER = Pattern.compile(
            "(?i)^\\[([0-9A-F]{8}-[0-9A-F]{8}-C:[0-9A-F]{2})\\]\\s*$");
    private static final Pattern LEGACY = Pattern.compile("(?i)^cheat([0-9]+)\\s*=\\s*(.*)$");
    private static final Pattern LEGACY_NOTE = Pattern.compile("(?i)^cheat([0-9]+)_N\\s*=\\s*(.*)$");
    private static final Pattern LEGACY_OPTIONS = Pattern.compile("(?i)^cheat([0-9]+)_O\\s*=.*$");

    public static final class Document {
        public String crc = "";
        public String title = "";
        public final List<ParsedCheat> cheats = new ArrayList<>();
    }

    private Project64ChtParser() {}

    public static Document parse(String text) {
        Document document = new Document();
        String name = null;
        String note = "";
        List<String> codes = new ArrayList<>();
        boolean unresolved = false;
        java.util.Map<Integer, String[]> legacy = new java.util.TreeMap<>();
        java.util.Set<Integer> legacyOptions = new java.util.HashSet<>();
        java.util.Map<Integer, String> legacyNotes = new java.util.HashMap<>();
        for (String raw : CodeText.lines(text)) {
            String line = raw.trim();
            if (line.isEmpty() || line.startsWith("//") || line.startsWith("#")) continue;
            Matcher header = HEADER.matcher(line);
            if (header.matches()) {
                if (document.crc.isEmpty()) document.crc = header.group(1).toUpperCase(Locale.US);
                continue;
            }
            if (line.regionMatches(true, 0, "Name=", 0, 5)) {
                if (document.title.isEmpty()) document.title = line.substring(5).trim();
                continue;
            }
            if (line.startsWith("$")) {
                flush(document, name, note, codes, unresolved);
                name = line.substring(1).trim(); note = ""; codes = new ArrayList<>(); unresolved = false;
                continue;
            }
            Matcher options = LEGACY_OPTIONS.matcher(line);
            if (options.matches()) { legacyOptions.add(Integer.parseInt(options.group(1))); continue; }
            Matcher legacyNote = LEGACY_NOTE.matcher(line);
            if (legacyNote.matches()) {
                legacyNotes.put(Integer.parseInt(legacyNote.group(1)), legacyNote.group(2).trim());
                continue;
            }
            Matcher row = LEGACY.matcher(line);
            if (row.matches()) {
                String body = row.group(2).trim();
                int quote = body.indexOf('"', 1);
                if (body.startsWith("\"") && quote > 0) {
                    String label = body.substring(1, quote);
                    String rest = body.substring(quote + 1).replaceFirst("^\\s*,", "").trim();
                    legacy.put(Integer.parseInt(row.group(1)), new String[] {label, rest});
                }
                continue;
            }
            if (line.regionMatches(true, 0, "Note=", 0, 5)) { note = line.substring(5).trim(); continue; }
            if (name == null) continue;
            String[] parts = line.split("\\s+");
            if (parts.length < 2) continue;
            if (parts[1].contains("?") || parts.length > 2) { unresolved = true; continue; }
            codes.add(parts[0].toUpperCase(Locale.US) + " " + parts[1].toUpperCase(Locale.US));
        }
        flush(document, name, note, codes, unresolved);
        for (java.util.Map.Entry<Integer, String[]> entry : legacy.entrySet()) {
            if (legacyOptions.contains(entry.getKey())) continue;
            List<String> pieces = new ArrayList<>();
            for (String piece : entry.getValue()[1].split(","))
                if (!piece.trim().isEmpty()) pieces.add(piece.trim().toUpperCase(Locale.US));
            String noteText = legacyNotes.get(entry.getKey());
            flush(document, entry.getValue()[0], noteText == null ? "" : noteText, pieces, false);
        }
        return document;
    }

    private static void flush(Document document, String name, String note, List<String> codes,
                              boolean unresolved) {
        if (name == null || codes.isEmpty() || unresolved) return;
        if (document.cheats.size() >= CodeText.MAX_CHEATS_PER_GAME) return;
        String code = CodeText.join(codes, "+");
        if (code.isEmpty() || CodeText.hasUnresolvedVariable(code)) return;
        document.cheats.add(new ParsedCheat(name, note, code, ParsedCheat.impliedTags(name)));
    }
}
