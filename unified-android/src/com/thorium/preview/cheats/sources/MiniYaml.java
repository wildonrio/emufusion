package com.thorium.preview.cheats.sources;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Just enough YAML for RPCS3 patch files: indentation-nested maps, block
 * sequences ({@code - item}), flow sequences ({@code [ a, b ]}), quoted keys and
 * scalars, comments, and literal/folded block scalars ({@code |}, {@code >})
 * kept as text. Anything else is preserved as a string rather than rejected.
 */
public final class MiniYaml {
    private static final int MAX_DEPTH = 32;

    private final List<String> lines;
    private int index;

    private MiniYaml(List<String> lines) { this.lines = lines; }

    /** @return a Map, List or String; an empty map for empty input */
    public static Object parse(String text) {
        List<String> raw = CodeText.lines(text);
        List<String> kept = new ArrayList<>(raw.size());
        for (String line : raw) {
            String stripped = stripComment(line);
            if (stripped.trim().isEmpty() || stripped.trim().equals("---")) {
                kept.add(null); // keep line numbering stable inside block scalars
            } else kept.add(stripped);
        }
        MiniYaml parser = new MiniYaml(kept);
        parser.skipBlank();
        if (parser.index >= kept.size()) return new LinkedHashMap<String, Object>();
        return parser.readNode(parser.indentOf(kept.get(parser.index)), 0);
    }

    /** Emits a Map/List/String tree in the style RPCS3 reads back. */
    public static String write(Object value) {
        StringBuilder out = new StringBuilder();
        write(out, value, 0);
        return out.toString();
    }

    private Object readNode(int indent, int depth) {
        if (depth > MAX_DEPTH) return "";
        skipBlank();
        if (index >= lines.size()) return "";
        String line = lines.get(index);
        String body = line.trim();
        if (body.startsWith("- ") || body.equals("-")) return readSequence(indent, depth);
        return readMapping(indent, depth);
    }

    private Map<String, Object> readMapping(int indent, int depth) {
        Map<String, Object> map = new LinkedHashMap<>();
        while (true) {
            skipBlank();
            if (index >= lines.size()) return map;
            String line = lines.get(index);
            int lineIndent = indentOf(line);
            if (lineIndent < indent) return map;
            if (lineIndent > indent) { index++; continue; } // stray deeper line
            String body = line.trim();
            if (body.startsWith("- ")) return map;
            int colon = keyColon(body);
            if (colon < 0) { index++; continue; }
            String key = CodeText.unquote(body.substring(0, colon));
            String rest = body.substring(colon + 1).trim();
            index++;
            if (rest.isEmpty()) {
                skipBlank();
                if (index < lines.size() && indentOf(lines.get(index)) > indent)
                    map.put(key, readNode(indentOf(lines.get(index)), depth + 1));
                else if (index < lines.size() && indentOf(lines.get(index)) == indent
                        && lines.get(index).trim().startsWith("- "))
                    map.put(key, readSequence(indent, depth + 1));
                else map.put(key, "");
            } else if (rest.equals("|") || rest.equals(">") || rest.equals("|-") || rest.equals(">-")) {
                map.put(key, readBlockScalar(indent));
            } else {
                map.put(key, scalar(rest));
            }
        }
    }

    private List<Object> readSequence(int indent, int depth) {
        List<Object> list = new ArrayList<>();
        while (true) {
            skipBlank();
            if (index >= lines.size()) return list;
            String line = lines.get(index);
            int lineIndent = indentOf(line);
            if (lineIndent < indent) return list;
            String body = line.trim();
            if (lineIndent > indent || !(body.startsWith("- ") || body.equals("-"))) {
                if (lineIndent > indent) { index++; continue; }
                return list;
            }
            String rest = body.length() > 1 ? body.substring(2).trim() : "";
            index++;
            if (rest.isEmpty()) {
                skipBlank();
                if (index < lines.size() && indentOf(lines.get(index)) > indent)
                    list.add(readNode(indentOf(lines.get(index)), depth + 1));
                else list.add("");
            } else if (keyColon(rest) >= 0 && !rest.startsWith("[") && !rest.startsWith("\"")) {
                // "- key: value" inline mapping: re-read with a synthetic indent.
                int inner = lineIndent + 2;
                lines.set(index - 1, repeat(' ', inner) + rest);
                index--;
                list.add(readMapping(inner, depth + 1));
            } else {
                list.add(scalar(rest));
            }
        }
    }

    private String readBlockScalar(int parentIndent) {
        StringBuilder out = new StringBuilder();
        while (index < lines.size()) {
            String line = lines.get(index);
            if (line == null) { out.append('\n'); index++; continue; }
            if (indentOf(line) <= parentIndent) break;
            if (out.length() > 0 && out.charAt(out.length() - 1) != '\n') out.append('\n');
            out.append(line.trim());
            index++;
        }
        return out.toString().trim();
    }

    private static Object scalar(String value) {
        String text = value.trim();
        if (text.startsWith("[") && text.endsWith("]")) {
            List<Object> items = new ArrayList<>();
            String inner = text.substring(1, text.length() - 1).trim();
            if (inner.isEmpty()) return items;
            for (String piece : splitFlow(inner)) items.add(CodeText.unquote(piece));
            return items;
        }
        return CodeText.unquote(text);
    }

    private static List<String> splitFlow(String inner) {
        List<String> pieces = new ArrayList<>();
        StringBuilder current = new StringBuilder();
        boolean quoted = false;
        char quote = 0;
        for (int i = 0; i < inner.length(); i++) {
            char ch = inner.charAt(i);
            if (quoted) {
                current.append(ch);
                if (ch == quote) quoted = false;
                continue;
            }
            if (ch == '"' || ch == '\'') { quoted = true; quote = ch; current.append(ch); continue; }
            if (ch == ',') { pieces.add(current.toString().trim()); current.setLength(0); continue; }
            current.append(ch);
        }
        if (current.toString().trim().length() > 0) pieces.add(current.toString().trim());
        return pieces;
    }

    private static int keyColon(String body) {
        boolean quoted = false;
        char quote = 0;
        for (int i = 0; i < body.length(); i++) {
            char ch = body.charAt(i);
            if (quoted) { if (ch == quote) quoted = false; continue; }
            if (ch == '"' || ch == '\'') { quoted = true; quote = ch; continue; }
            if (ch == ':' && (i + 1 == body.length() || body.charAt(i + 1) == ' ')) return i;
        }
        return -1;
    }

    private static String stripComment(String line) {
        if (line == null) return "";
        boolean quoted = false;
        char quote = 0;
        for (int i = 0; i < line.length(); i++) {
            char ch = line.charAt(i);
            if (quoted) { if (ch == quote) quoted = false; continue; }
            if (ch == '"' || ch == '\'') { quoted = true; quote = ch; continue; }
            if (ch == '#' && (i == 0 || Character.isWhitespace(line.charAt(i - 1))))
                return line.substring(0, i);
        }
        return line;
    }

    private void skipBlank() {
        while (index < lines.size() && lines.get(index) == null) index++;
    }

    private static int indentOf(String line) {
        int count = 0;
        while (count < line.length() && line.charAt(count) == ' ') count++;
        return count;
    }

    private static String repeat(char ch, int count) {
        StringBuilder out = new StringBuilder();
        for (int i = 0; i < count; i++) out.append(ch);
        return out.toString();
    }

    @SuppressWarnings("unchecked")
    private static void write(StringBuilder out, Object value, int indent) {
        String pad = repeat(' ', indent);
        if (value instanceof Map) {
            for (Map.Entry<String, Object> entry : ((Map<String, Object>) value).entrySet()) {
                Object item = entry.getValue();
                out.append(pad).append(quoteKey(entry.getKey())).append(':');
                if (item instanceof Map && !((Map<?, ?>) item).isEmpty()) {
                    out.append('\n');
                    write(out, item, indent + 2);
                } else if (item instanceof List && !((List<?>) item).isEmpty()
                        && containsNested((List<Object>) item)) {
                    out.append('\n');
                    write(out, item, indent + 2);
                } else if (item instanceof List) {
                    out.append(' ').append(flow((List<Object>) item)).append('\n');
                } else {
                    out.append(' ').append(quoteScalar(JsonLite.string(item))).append('\n');
                }
            }
        } else if (value instanceof List) {
            for (Object item : (List<Object>) value) {
                if (item instanceof List) out.append(pad).append("- ").append(flow((List<Object>) item)).append('\n');
                else if (item instanceof Map) {
                    out.append(pad).append("-\n");
                    write(out, item, indent + 2);
                } else out.append(pad).append("- ").append(quoteScalar(JsonLite.string(item))).append('\n');
            }
        } else {
            out.append(pad).append(quoteScalar(JsonLite.string(value))).append('\n');
        }
    }

    private static boolean containsNested(List<Object> list) {
        for (Object item : list) if (item instanceof Map || item instanceof List) return true;
        return false;
    }

    @SuppressWarnings("unchecked")
    private static String flow(List<Object> list) {
        StringBuilder out = new StringBuilder("[ ");
        boolean first = true;
        for (Object item : list) {
            if (!first) out.append(", ");
            first = false;
            out.append(item instanceof List ? flow((List<Object>) item) : quoteScalar(JsonLite.string(item)));
        }
        return out.append(" ]").toString();
    }

    private static String quoteKey(String key) {
        if (key.matches("[A-Za-z0-9_][A-Za-z0-9_ .-]*") && !key.contains(": ")) return key;
        return "\"" + key.replace("\\", "\\\\").replace("\"", "\\\"") + "\"";
    }

    private static String quoteScalar(String value) {
        if (value.isEmpty()) return "\"\"";
        if (value.matches("[A-Za-z0-9_][A-Za-z0-9_ .,/+()-]*") && !value.matches("(?i)true|false|null|yes|no|~"))
            return value;
        return "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n") + "\"";
    }
}
