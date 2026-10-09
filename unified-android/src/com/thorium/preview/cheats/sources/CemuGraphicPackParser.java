package com.thorium.preview.cheats.sources;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.TreeMap;

/**
 * Cemu graphic pack {@code rules.txt}: the {@code [Definition]} block names
 * the pack, its path and the {@code titleIds} it applies to. A pack is one
 * switch: its code is the pack's files concatenated with {@code #### file: <name>}
 * separators (rules.txt first) so a boot writer can lay the directory back
 * down under {@code graphicPacks/}. Only packs naming the running title are
 * offered.
 */
public final class CemuGraphicPackParser {
    public static final String FILE_MARKER = "#### file: ";

    public static final class Pack {
        public String name = "";
        public String path = "";
        public String description = "";
        public String version = "";
        public final List<String> titleIds = new ArrayList<>();
    }

    private CemuGraphicPackParser() {}

    public static Pack parseRules(String text) {
        Pack pack = new Pack();
        String section = "";
        for (String raw : CodeText.lines(text)) {
            String line = raw.trim();
            if (line.isEmpty() || line.startsWith("#") || line.startsWith(";")) continue;
            if (line.startsWith("[") && line.endsWith("]")) {
                section = line.substring(1, line.length() - 1).trim().toLowerCase(Locale.US);
                continue;
            }
            if (!"definition".equals(section)) continue;
            int eq = line.indexOf('=');
            if (eq <= 0) continue;
            String key = line.substring(0, eq).trim().toLowerCase(Locale.US);
            String value = CodeText.unquote(line.substring(eq + 1).trim());
            if ("titleids".equals(key)) {
                for (String id : value.split("[,\\s]+")) {
                    String clean = id.trim().toUpperCase(Locale.US);
                    if (clean.matches("[0-9A-F]{16}") && !pack.titleIds.contains(clean))
                        pack.titleIds.add(clean);
                }
            } else if ("name".equals(key)) pack.name = value;
            else if ("path".equals(key)) pack.path = value;
            else if ("description".equals(key)) pack.description = value.replace("|", " ").trim();
            else if ("version".equals(key)) pack.version = value;
        }
        return pack;
    }

    public static boolean covers(Pack pack, String titleId) {
        if (pack == null || titleId == null) return false;
        String wanted = titleId.trim().toUpperCase(Locale.US);
        if (pack.titleIds.contains(wanted)) return true;
        // Packs list the base title; a title id for an update/DLC of the same
        // game shares the low 32 bits.
        if (wanted.length() == 16) {
            String low = wanted.substring(8);
            for (String id : pack.titleIds) if (id.endsWith(low)) return true;
        }
        return false;
    }

    /**
     * @param files pack-relative file name → content, rules.txt included
     */
    public static ParsedCheat toParsed(String packDirectory, Pack pack, Map<String, String> files) {
        Map<String, String> ordered = new TreeMap<>(files);
        StringBuilder code = new StringBuilder();
        String rules = ordered.remove("rules.txt");
        if (rules != null) code.append(FILE_MARKER).append("rules.txt\n").append(rules.trim()).append('\n');
        for (Map.Entry<String, String> file : ordered.entrySet())
            code.append(FILE_MARKER).append(file.getKey()).append('\n')
                    .append(file.getValue().trim()).append('\n');
        String name = pack.name.isEmpty() ? (pack.path.isEmpty() ? packDirectory : pack.path) : pack.name;
        List<String> tags = ParsedCheat.impliedTags(name, pack.path, pack.description);
        tags.add("pack:" + ParsedCheat.groupTag(packDirectory));
        String category = category(pack.path.isEmpty() ? packDirectory : pack.path);
        if (!category.isEmpty()) tags.add(ParsedCheat.groupTag(category));
        String cleaned = CodeText.clean(code.toString());
        if (cleaned.isEmpty()) return null;
        return new ParsedCheat(name, pack.description, cleaned, tags);
    }

    /** "Game/Cheats/Infinite Hearts" → "Cheats". */
    static String category(String path) {
        if (path == null) return "";
        String[] parts = path.replace("\\", "/").split("/");
        return parts.length >= 3 ? parts[parts.length - 2].trim() : "";
    }

    /** Splits a stored code back into files; the inverse of {@link #toParsed}. */
    public static Map<String, String> filesOf(String code) {
        Map<String, String> files = new TreeMap<>();
        if (code == null) return files;
        String name = null;
        StringBuilder body = new StringBuilder();
        for (String line : CodeText.lines(code)) {
            if (line.startsWith(FILE_MARKER)) {
                if (name != null) files.put(name, body.toString().trim() + "\n");
                name = line.substring(FILE_MARKER.length()).trim();
                body.setLength(0);
                continue;
            }
            if (name != null) body.append(line).append('\n');
        }
        if (name != null) files.put(name, body.toString().trim() + "\n");
        return Collections.unmodifiableMap(files);
    }
}
