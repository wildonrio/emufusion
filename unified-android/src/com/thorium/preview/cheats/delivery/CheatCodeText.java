package com.thorium.preview.cheats.delivery;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Text helpers the boot writers share: code line splitting and safe names. */
final class CheatCodeText {
    static final Pattern HEX8 = Pattern.compile("(?:0[xX])?([0-9A-Fa-f]{8})");
    static final Pattern HEX_PAIR = Pattern.compile(
            "^\\s*(?:0[xX])?([0-9A-Fa-f]{8})[\\s:]+(?:0[xX])?([0-9A-Fa-f]{8})\\s*$");
    static final Pattern SERIAL = Pattern.compile("([A-Z]{4})-?([0-9]{5})");
    static final Pattern TITLE_ID16 = Pattern.compile("(?<![0-9A-Fa-f])([0-9A-Fa-f]{16})(?![0-9A-Fa-f])");

    private CheatCodeText() {}

    /**
     * The lines of a code. The catalogue joins multi-line codes with '+';
     * a downloader that kept real newlines is honoured as well.
     */
    static List<String> lines(String code) {
        List<String> lines = new ArrayList<>();
        if (code == null) return lines;
        String[] parts = code.indexOf('\n') >= 0 ? code.split("\\r?\\n") : code.split("\\+");
        for (String part : parts) {
            String line = part.trim();
            if (!line.isEmpty()) lines.add(line);
        }
        return lines;
    }

    /** "AAAAAAAA VVVVVVVV" in upper case, or null when the line is not a pair. */
    static String hexPair(String line) {
        Matcher matcher = HEX_PAIR.matcher(line == null ? "" : line);
        if (!matcher.matches()) return null;
        return matcher.group(1).toUpperCase(Locale.US) + " " + matcher.group(2).toUpperCase(Locale.US);
    }

    /** Every 8-hex word on the line, upper case; null when anything else is present. */
    static List<String> hexWords(String line) {
        if (line == null) return null;
        List<String> words = new ArrayList<>();
        for (String token : line.trim().split("[\\s,]+")) {
            if (token.isEmpty()) continue;
            Matcher matcher = HEX8.matcher(token);
            if (!matcher.matches()) return null;
            words.add(matcher.group(1).toUpperCase(Locale.US));
        }
        return words.isEmpty() ? null : words;
    }

    /** A display name that cannot break the line-oriented formats it lands in. */
    static String safeName(String name, int maxLength) {
        String value = name == null ? "" : name;
        StringBuilder out = new StringBuilder(value.length());
        for (int i = 0; i < value.length(); i++) {
            char ch = value.charAt(i);
            if (ch < 0x20 || ch == 0x7f || ch == '[' || ch == ']' || ch == '{' || ch == '}'
                    || ch == '$' || ch == '*' || ch == '"' || ch == '\\')
                out.append(' ');
            else out.append(ch);
        }
        String cleaned = out.toString().replaceAll("\\s+", " ").trim();
        if (cleaned.isEmpty()) cleaned = "Cheat";
        return cleaned.length() > maxLength ? cleaned.substring(0, maxLength).trim() : cleaned;
    }

    /** Distinct names in a file whose entries are addressed by name. */
    static String uniqueName(String name, Set<String> used) {
        String candidate = name;
        for (int suffix = 2; used.contains(candidate.toLowerCase(Locale.US)); suffix++)
            candidate = name + " (" + suffix + ")";
        used.add(candidate.toLowerCase(Locale.US));
        return candidate;
    }

    /** "ULUS-10041" from any spelling of a PSP/PS1/PS2 serial, or "". */
    static String serialWithHyphen(String value) {
        Matcher matcher = SERIAL.matcher(value == null ? "" : value.toUpperCase(Locale.US));
        return matcher.find() ? matcher.group(1) + "-" + matcher.group(2) : "";
    }

    /** "ULUS10041" from any spelling, or "". */
    static String serialCompact(String value) {
        String hyphenated = serialWithHyphen(value);
        return hyphenated.isEmpty() ? "" : hyphenated.replace("-", "");
    }

    /** A 16-hex title id in upper case, or "". */
    static String titleId16(String value) {
        Matcher matcher = TITLE_ID16.matcher(value == null ? "" : value);
        return matcher.find() ? matcher.group(1).toUpperCase(Locale.US) : "";
    }

    /** Comma-separated identity values, trimmed, in order, without repeats. */
    static List<String> csv(String value) {
        Set<String> seen = new LinkedHashSet<>();
        if (value != null)
            for (String part : value.split("[,;\\s]+")) {
                String item = part.trim();
                if (!item.isEmpty()) seen.add(item);
            }
        return new ArrayList<>(seen);
    }

    static String tagValue(DeliveryCheat cheat, String key) {
        String prefix = key.toLowerCase(Locale.US);
        for (String tag : cheat.tags) {
            if (tag.startsWith(prefix + "=")) return tag.substring(prefix.length() + 1).trim();
            if (tag.startsWith(prefix + ":")) return tag.substring(prefix.length() + 1).trim();
        }
        return "";
    }

    /** Text for a single-line field: no line breaks, bounded. */
    static String singleLine(String value, int maxLength) {
        String cleaned = (value == null ? "" : value).replaceAll("[\\r\\n\\t]+", " ")
                .replaceAll("\\s+", " ").trim();
        return cleaned.length() > maxLength ? cleaned.substring(0, maxLength).trim() : cleaned;
    }
}
