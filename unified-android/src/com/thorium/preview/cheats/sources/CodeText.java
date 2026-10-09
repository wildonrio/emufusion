package com.thorium.preview.cheats.sources;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.regex.Pattern;

/** Shared text hygiene for every parser: bounded lines, no control bytes, no placeholders. */
final class CodeText {
    static final int MAX_TEXT_CHARS = 48 * 1024 * 1024;
    static final int MAX_LINES = 2_000_000;
    static final int MAX_CODE_CHARS = 64 * 1024;
    static final int MAX_CHEATS_PER_GAME = 65_536;
    private static final Pattern HEX_PAIR = Pattern.compile(
            "^\\s*(?:0x)?[0-9A-Fa-f]{8}\\s+(?:0x)?[0-9A-Fa-f]{4,8}(?:\\s+(?:0x)?[0-9A-Fa-f]{2,8})*\\s*$");

    private CodeText() {}

    /** Splits on any line ending, drops a BOM, and bounds the count. */
    static List<String> lines(String text) {
        List<String> result = new ArrayList<>();
        if (text == null) return result;
        if (text.length() > MAX_TEXT_CHARS) text = text.substring(0, MAX_TEXT_CHARS);
        if (!text.isEmpty() && text.charAt(0) == '﻿') text = text.substring(1);
        int start = 0;
        for (int i = 0; i < text.length(); i++) {
            char ch = text.charAt(i);
            if (ch == '\n' || ch == '\r') {
                result.add(text.substring(start, i));
                if (ch == '\r' && i + 1 < text.length() && text.charAt(i + 1) == '\n') i++;
                start = i + 1;
                if (result.size() >= MAX_LINES) return result;
            }
        }
        if (start < text.length()) result.add(text.substring(start));
        return result;
    }

    static String clean(String value) {
        if (value == null) return "";
        String code = value.trim();
        if (code.isEmpty() || code.length() > MAX_CODE_CHARS) return "";
        for (int i = 0; i < code.length(); i++) {
            char ch = code.charAt(i);
            if (ch == 0 || (ch < 0x20 && ch != '\t' && ch != '\n' && ch != '\r')) return "";
        }
        return code;
    }

    /** A code whose value the user is expected to fill in cannot be a switch. */
    static boolean hasUnresolvedVariable(String code) {
        if (code == null) return true;
        String upper = code.toUpperCase(Locale.US);
        return upper.contains("??") || upper.matches("(?s).*(^|[^A-Z])X{2,}([^A-Z]|$).*");
    }

    /** Address/value pairs such as {@code 8117A0C0 0009} or {@code 0x20000000 0x00000001}. */
    static boolean isHexPairLine(String line) {
        return line != null && HEX_PAIR.matcher(line).matches();
    }

    static String join(List<String> lines, String separator) {
        StringBuilder out = new StringBuilder();
        for (String line : lines) {
            if (line == null || line.trim().isEmpty()) continue;
            if (out.length() > 0) out.append(separator);
            out.append(line.trim());
        }
        return out.toString();
    }

    static String stripComment(String line, String marker) {
        if (line == null) return "";
        int at = line.indexOf(marker);
        return at < 0 ? line : line.substring(0, at);
    }

    static String unquote(String value) {
        String clean = value == null ? "" : value.trim();
        if (clean.length() >= 2 && ((clean.charAt(0) == '"' && clean.charAt(clean.length() - 1) == '"')
                || (clean.charAt(0) == '\'' && clean.charAt(clean.length() - 1) == '\'')))
            clean = clean.substring(1, clean.length() - 1);
        return clean.replace("\\\"", "\"").replace("\\\\", "\\").trim();
    }
}
