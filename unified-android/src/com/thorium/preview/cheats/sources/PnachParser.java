package com.thorium.preview.cheats.sources;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * PCSX2 {@code .pnach}, group-aware.
 *
 * <p>A {@code [Section]} header starts a switch named after the section
 * (PCSX2 patches use "Widescreen 16:9", "No Interlacing", ...); a
 * {@code description=} inside it becomes the description. Community cheat
 * files use {@code //Cheat name} comment lines followed by {@code patch=}
 * rows, so a comment line immediately preceding patch rows also starts a
 * switch -- but only outside a {@code [Section]}: PCSX2 applies a whole
 * bracketed section as a single toggle, and real {@code pcsx2_patches}
 * files routinely interleave comments (e.g. {@code // 16:9}) between its
 * patch lines, so once a section has been opened by a {@code [Section]}
 * header a later comment is folded into the description instead of
 * splitting the section into multiple switches. The switch's code is the
 * verbatim {@code patch=} lines joined by newlines, which is exactly what
 * gets written back into a pnach file. Group names survive as tags so a
 * policy can find every "widescreen" row.
 */
public final class PnachParser {
    private PnachParser() {}

    public static List<ParsedCheat> parse(String text) {
        return parse(text, "");
    }

    /** @param defaultName used for a file with patch rows but no section or comment names */
    public static List<ParsedCheat> parse(String text, String defaultName) {
        List<ParsedCheat> result = new ArrayList<>();
        String gameTitle = "";
        String fileDescription = "";
        String name = null;
        String description = "";
        String aspect = "";
        boolean named = false;
        boolean bracketSection = false;
        List<String> patches = new ArrayList<>();
        for (String raw : CodeText.lines(text)) {
            String line = raw.trim();
            if (line.isEmpty()) continue;
            if (line.startsWith("[") && line.endsWith("]")) {
                flush(result, name, description, aspect, patches, defaultName, gameTitle, fileDescription);
                name = line.substring(1, line.length() - 1).trim();
                named = true; description = ""; aspect = ""; patches = new ArrayList<>();
                bracketSection = true;
                continue;
            }
            if (line.startsWith("//") || line.startsWith("#") || line.startsWith(";")) {
                String comment = line.replaceFirst("^(//|#|;)+\\s*", "").trim();
                if (comment.isEmpty()) continue;
                if (!patches.isEmpty() && !bracketSection) {
                    flush(result, name, description, aspect, patches, defaultName, gameTitle, fileDescription);
                    name = comment; named = true; description = ""; aspect = ""; patches = new ArrayList<>();
                } else if (!named || name == null) {
                    name = comment; named = true;
                } else {
                    description = description.isEmpty() ? comment : description + " " + comment;
                }
                continue;
            }
            int eq = line.indexOf('=');
            if (eq <= 0) continue;
            String key = line.substring(0, eq).trim().toLowerCase(Locale.US);
            String value = line.substring(eq + 1).trim();
            if ("gametitle".equals(key)) { gameTitle = value; continue; }
            if ("comment".equals(key)) { fileDescription = value; continue; }
            if ("description".equals(key)) {
                if (name == null && patches.isEmpty()) fileDescription = value; else description = value;
                continue;
            }
            if ("author".equals(key)) continue;
            if ("gsaspectratio".equals(key)) { aspect = value; continue; }
            if ("patch".equals(key) || "dpatch".equals(key)) {
                String cleaned = CodeText.clean(line);
                if (!cleaned.isEmpty()) patches.add(cleaned);
            }
        }
        flush(result, name, description, aspect, patches, defaultName, gameTitle, fileDescription);
        return result;
    }

    private static void flush(List<ParsedCheat> into, String name, String description, String aspect,
                              List<String> patches, String defaultName, String gameTitle,
                              String fileDescription) {
        if (patches.isEmpty() || into.size() >= CodeText.MAX_CHEATS_PER_GAME) return;
        String label = name;
        if (label == null || label.isEmpty()) {
            label = !defaultName.isEmpty() ? defaultName
                    : !fileDescription.isEmpty() ? fileDescription
                    : !gameTitle.isEmpty() ? gameTitle + " patch" : "Patch";
        }
        String code = CodeText.join(patches, "\n");
        if (code.isEmpty() || CodeText.hasUnresolvedVariable(code)) return;
        List<String> tags = ParsedCheat.impliedTags(label, description, aspect);
        if (name != null && !name.isEmpty()) tags.add(ParsedCheat.groupTag(name));
        if (!aspect.isEmpty()) tags.add("aspect:" + aspect.replaceAll("\\s+", ""));
        String detail = description.isEmpty() ? fileDescription : description;
        into.add(new ParsedCheat(label, detail, code, tags));
    }
}
