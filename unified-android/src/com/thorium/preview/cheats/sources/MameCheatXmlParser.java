package com.thorium.preview.cheats.sources;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * MAME {@code <mamecheat>} XML: one switch per {@code <cheat desc="...">}. The
 * code is the cheat element verbatim so a boot writer can pack it into
 * {@code cheat.7z}/{@code cheat.xml}; a cheat that declares a
 * {@code <parameter>} needs a value and is tagged as such rather than dropped.
 * Parsed with bounded regular expressions; no XML library is involved.
 */
public final class MameCheatXmlParser {
    private static final Pattern CHEAT = Pattern.compile(
            "(?is)<cheat\\b([^>]*)>(.*?)</cheat>");
    private static final Pattern DESC = Pattern.compile("(?is)\\bdesc\\s*=\\s*\"([^\"]*)\"");
    private static final Pattern COMMENT = Pattern.compile("(?is)<comment>(.*?)</comment>");
    private static final Pattern ACTION = Pattern.compile("(?is)<action\\b[^>]*>(.*?)</action>");

    private MameCheatXmlParser() {}

    public static List<ParsedCheat> parse(String text) {
        List<ParsedCheat> result = new ArrayList<>();
        if (text == null) return result;
        if (text.length() > CodeText.MAX_TEXT_CHARS) text = text.substring(0, CodeText.MAX_TEXT_CHARS);
        Matcher cheats = CHEAT.matcher(text);
        while (cheats.find()) {
            if (result.size() >= CodeText.MAX_CHEATS_PER_GAME) break;
            Matcher desc = DESC.matcher(cheats.group(1));
            String name = desc.find() ? unescape(desc.group(1)) : "Cheat " + (result.size() + 1);
            String body = cheats.group(2);
            if (!ACTION.matcher(body).find()) continue;
            Matcher comment = COMMENT.matcher(body);
            String description = comment.find() ? unescape(comment.group(1)).replaceAll("\\s+", " ").trim() : "";
            String code = CodeText.clean(cheats.group(0).trim());
            if (code.isEmpty()) continue;
            List<String> tags = ParsedCheat.impliedTags(name);
            if (body.toLowerCase().contains("<parameter")) tags.add("parameter");
            result.add(new ParsedCheat(name, description, code, tags));
        }
        return result;
    }

    static String unescape(String value) {
        return value == null ? "" : value.replace("&lt;", "<").replace("&gt;", ">")
                .replace("&quot;", "\"").replace("&apos;", "'").replace("&amp;", "&").trim();
    }
}
