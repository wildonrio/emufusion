package com.thorium.preview.cheats.sources;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Locale;
import java.util.regex.Pattern;

/** A cheat as a source parser produced it, before it gets an id and a delivery. */
public final class ParsedCheat {
    private static final Pattern WIDESCREEN = Pattern.compile(
            "(?i)(16 ?: ?9|16x9|widescreen|wide screen|wide-screen|aspect ratio|aspect)");
    private static final Pattern ULTRAWIDE = Pattern.compile("(?i)(21 ?: ?9|32 ?: ?9|ultra ?wide)");
    private static final Pattern FPS = Pattern.compile("(?i)(\\b60 ?fps\\b|\\bfps\\b|frame ?rate|60hz|unlock(ed)? fps)");

    public final String name;
    public final String description;
    public final String code;
    public final List<String> tags;

    public ParsedCheat(String name, String description, String code, List<String> tags) {
        this.name = name == null || name.trim().isEmpty() ? "Cheat" : name.trim();
        this.description = description == null ? "" : description.trim();
        this.code = code == null ? "" : code.trim();
        List<String> clean = new ArrayList<>();
        if (tags != null) {
            for (String tag : tags) {
                if (tag == null) continue;
                String value = tag.trim().toLowerCase(Locale.US);
                if (!value.isEmpty() && !clean.contains(value)) clean.add(value);
            }
        }
        this.tags = Collections.unmodifiableList(clean);
    }

    public ParsedCheat(String name, String description, String code) {
        this(name, description, code, null);
    }

    public ParsedCheat withTags(List<String> extra) {
        List<String> merged = new ArrayList<>(tags);
        if (extra != null) merged.addAll(extra);
        return new ParsedCheat(name, description, code, merged);
    }

    /** Tags implied by a name or group label: widescreen, ultrawide, 60fps. */
    public static List<String> impliedTags(String... labels) {
        List<String> tags = new ArrayList<>();
        for (String label : labels) {
            if (label == null) continue;
            if (ULTRAWIDE.matcher(label).find()) tags.add("ultrawide");
            else if (WIDESCREEN.matcher(label).find()) tags.add("widescreen");
            if (FPS.matcher(label).find()) tags.add("60fps");
        }
        return tags;
    }

    /** A source group label as a tag: lower-case, spaces collapsed to '-'. */
    public static String groupTag(String label) {
        if (label == null) return "";
        String clean = label.trim().toLowerCase(Locale.US).replaceAll("[^a-z0-9:]+", "-");
        clean = clean.replaceAll("^-+|-+$", "");
        return clean.length() > 48 ? clean.substring(0, 48) : clean;
    }

    @Override public String toString() { return "ParsedCheat{" + name + "}"; }
}
