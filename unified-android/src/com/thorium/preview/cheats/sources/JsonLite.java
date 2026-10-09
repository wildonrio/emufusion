package com.thorium.preview.cheats.sources;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * A tiny JSON reader/writer with no Android or org.json dependency.
 *
 * <p>The cheat sources are parsed on the host test classpath, which carries
 * neither {@code android.jar} nor {@code org.json}; the same code then runs
 * unchanged on the device. Objects are {@link LinkedHashMap}, arrays are
 * {@link ArrayList}, numbers are {@link Long} or {@link Double}, and JSON
 * {@code null} is Java {@code null}. Depth and size are bounded so a hostile
 * download cannot recurse the parser into a stack overflow.
 */
public final class JsonLite {
    private static final int MAX_DEPTH = 64;

    private final String text;
    private int position;

    private JsonLite(String text) { this.text = text; }

    /** Parses a JSON document; throws {@link IllegalArgumentException} on malformed input. */
    public static Object parse(String text) {
        if (text == null) throw new IllegalArgumentException("no json");
        JsonLite parser = new JsonLite(text);
        parser.skipWhitespace();
        Object value = parser.readValue(0);
        parser.skipWhitespace();
        if (parser.position != text.length())
            throw new IllegalArgumentException("trailing characters at " + parser.position);
        return value;
    }

    /** Parses and returns an object, or an empty map when the text is not a JSON object. */
    @SuppressWarnings("unchecked")
    public static Map<String, Object> parseObject(String text) {
        try {
            Object value = parse(text);
            if (value instanceof Map) return (Map<String, Object>) value;
        } catch (RuntimeException malformed) {
            // fall through
        }
        return new LinkedHashMap<String, Object>();
    }

    @SuppressWarnings("unchecked")
    public static Map<String, Object> object(Object value) {
        return value instanceof Map ? (Map<String, Object>) value : new LinkedHashMap<String, Object>();
    }

    @SuppressWarnings("unchecked")
    public static List<Object> array(Object value) {
        return value instanceof List ? (List<Object>) value : new ArrayList<Object>();
    }

    public static String string(Object value) {
        if (value == null) return "";
        if (value instanceof String) return (String) value;
        return String.valueOf(value);
    }

    public static long number(Object value, long fallback) {
        if (value instanceof Number) return ((Number) value).longValue();
        if (value instanceof String) {
            try { return Long.parseLong(((String) value).trim()); }
            catch (NumberFormatException ignored) { return fallback; }
        }
        return fallback;
    }

    public static boolean bool(Object value, boolean fallback) {
        if (value instanceof Boolean) return (Boolean) value;
        if (value instanceof String) {
            String clean = ((String) value).trim().toLowerCase(Locale.US);
            if ("true".equals(clean) || "1".equals(clean) || "on".equals(clean)) return true;
            if ("false".equals(clean) || "0".equals(clean) || "off".equals(clean)) return false;
        }
        return fallback;
    }

    private Object readValue(int depth) {
        if (depth > MAX_DEPTH) throw new IllegalArgumentException("json nests too deeply");
        if (position >= text.length()) throw new IllegalArgumentException("unexpected end of json");
        char ch = text.charAt(position);
        switch (ch) {
            case '{': return readObject(depth);
            case '[': return readArray(depth);
            case '"': return readString();
            case 't': expect("true"); return Boolean.TRUE;
            case 'f': expect("false"); return Boolean.FALSE;
            case 'n': expect("null"); return null;
            default: return readNumber();
        }
    }

    private Map<String, Object> readObject(int depth) {
        Map<String, Object> result = new LinkedHashMap<>();
        position++;
        skipWhitespace();
        if (peek() == '}') { position++; return result; }
        while (true) {
            skipWhitespace();
            if (peek() != '"') throw new IllegalArgumentException("object key expected at " + position);
            String key = readString();
            skipWhitespace();
            if (peek() != ':') throw new IllegalArgumentException("':' expected at " + position);
            position++;
            skipWhitespace();
            result.put(key, readValue(depth + 1));
            skipWhitespace();
            char next = peek();
            position++;
            if (next == '}') return result;
            if (next != ',') throw new IllegalArgumentException("',' expected at " + position);
        }
    }

    private List<Object> readArray(int depth) {
        List<Object> result = new ArrayList<>();
        position++;
        skipWhitespace();
        if (peek() == ']') { position++; return result; }
        while (true) {
            skipWhitespace();
            result.add(readValue(depth + 1));
            skipWhitespace();
            char next = peek();
            position++;
            if (next == ']') return result;
            if (next != ',') throw new IllegalArgumentException("',' expected at " + position);
        }
    }

    private String readString() {
        position++;
        StringBuilder out = new StringBuilder();
        while (true) {
            if (position >= text.length()) throw new IllegalArgumentException("unterminated string");
            char ch = text.charAt(position++);
            if (ch == '"') return out.toString();
            if (ch != '\\') { out.append(ch); continue; }
            if (position >= text.length()) throw new IllegalArgumentException("unterminated escape");
            char escaped = text.charAt(position++);
            switch (escaped) {
                case '"': out.append('"'); break;
                case '\\': out.append('\\'); break;
                case '/': out.append('/'); break;
                case 'b': out.append('\b'); break;
                case 'f': out.append('\f'); break;
                case 'n': out.append('\n'); break;
                case 'r': out.append('\r'); break;
                case 't': out.append('\t'); break;
                case 'u':
                    if (position + 4 > text.length()) throw new IllegalArgumentException("bad unicode escape");
                    out.append((char) Integer.parseInt(text.substring(position, position + 4), 16));
                    position += 4;
                    break;
                default: throw new IllegalArgumentException("bad escape at " + position);
            }
        }
    }

    private Object readNumber() {
        int start = position;
        while (position < text.length()) {
            char ch = text.charAt(position);
            if ((ch >= '0' && ch <= '9') || ch == '-' || ch == '+' || ch == '.' || ch == 'e' || ch == 'E')
                position++;
            else break;
        }
        String token = text.substring(start, position);
        if (token.isEmpty()) throw new IllegalArgumentException("unexpected character at " + position);
        try {
            if (token.indexOf('.') < 0 && token.indexOf('e') < 0 && token.indexOf('E') < 0)
                return Long.parseLong(token);
            return Double.parseDouble(token);
        } catch (NumberFormatException bad) {
            throw new IllegalArgumentException("bad number '" + token + "'");
        }
    }

    private void expect(String literal) {
        if (!text.startsWith(literal, position))
            throw new IllegalArgumentException("'" + literal + "' expected at " + position);
        position += literal.length();
    }

    private char peek() {
        if (position >= text.length()) throw new IllegalArgumentException("unexpected end of json");
        return text.charAt(position);
    }

    private void skipWhitespace() {
        while (position < text.length()) {
            char ch = text.charAt(position);
            if (ch == ' ' || ch == '\t' || ch == '\n' || ch == '\r') position++;
            else break;
        }
    }

    /** Serialises maps, lists, strings, numbers, booleans and null. */
    public static String write(Object value) {
        StringBuilder out = new StringBuilder();
        write(out, value, 0);
        return out.toString();
    }

    @SuppressWarnings("unchecked")
    private static void write(StringBuilder out, Object value, int depth) {
        if (depth > MAX_DEPTH) throw new IllegalArgumentException("value nests too deeply");
        if (value == null) { out.append("null"); return; }
        if (value instanceof String) { quote(out, (String) value); return; }
        if (value instanceof Boolean) { out.append(((Boolean) value) ? "true" : "false"); return; }
        if (value instanceof Number) {
            if (value instanceof Double || value instanceof Float) {
                double number = ((Number) value).doubleValue();
                if (Double.isNaN(number) || Double.isInfinite(number)) out.append("null");
                else out.append(number);
            } else out.append(((Number) value).longValue());
            return;
        }
        if (value instanceof Map) {
            out.append('{');
            boolean first = true;
            for (Map.Entry<String, Object> entry : ((Map<String, Object>) value).entrySet()) {
                if (!first) out.append(',');
                first = false;
                quote(out, entry.getKey());
                out.append(':');
                write(out, entry.getValue(), depth + 1);
            }
            out.append('}');
            return;
        }
        if (value instanceof Iterable) {
            out.append('[');
            boolean first = true;
            for (Object item : (Iterable<Object>) value) {
                if (!first) out.append(',');
                first = false;
                write(out, item, depth + 1);
            }
            out.append(']');
            return;
        }
        quote(out, String.valueOf(value));
    }

    private static void quote(StringBuilder out, String value) {
        out.append('"');
        for (int i = 0; i < value.length(); i++) {
            char ch = value.charAt(i);
            switch (ch) {
                case '"': out.append("\\\""); break;
                case '\\': out.append("\\\\"); break;
                case '\n': out.append("\\n"); break;
                case '\r': out.append("\\r"); break;
                case '\t': out.append("\\t"); break;
                default:
                    if (ch < 0x20) out.append(String.format(Locale.US, "\\u%04x", (int) ch));
                    else out.append(ch);
            }
        }
        out.append('"');
    }
}
