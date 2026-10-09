package com.thorium.preview.cheats.sources;

import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.TimeZone;

/**
 * Everything the update step learned about one game's cheats, ready to be
 * written as the per-game file that {@code CheatCatalog} merges at runtime.
 */
public final class DownloadedCheatDocument {
    public static final int SCHEMA_VERSION = 2;

    public final String system;
    public final String title;
    public final Map<String, String> identity = new LinkedHashMap<>();
    public final List<String> sources = new ArrayList<>();
    public String fetchedAt;
    private final List<DownloadedCheat> cheats = new ArrayList<>();

    public DownloadedCheatDocument(String system, String title) {
        this.system = system == null ? "" : system;
        this.title = title == null ? "" : title;
        this.fetchedAt = timestamp(System.currentTimeMillis());
    }

    /** Adds a row unless a row with the same id is already present. */
    public boolean add(DownloadedCheat cheat) {
        if (cheat == null) return false;
        for (DownloadedCheat existing : cheats)
            if (existing.cheat.id.equals(cheat.cheat.id)) return false;
        cheats.add(cheat);
        if (!cheat.source.isEmpty() && !sources.contains(cheat.source)) sources.add(cheat.source);
        return true;
    }

    public void addAll(List<DownloadedCheat> rows) {
        if (rows == null) return;
        for (DownloadedCheat row : rows) add(row);
    }

    public List<DownloadedCheat> cheats() { return Collections.unmodifiableList(cheats); }

    public int size() { return cheats.size(); }

    public boolean isEmpty() { return cheats.isEmpty(); }

    public static String timestamp(long millis) {
        SimpleDateFormat format = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US);
        format.setTimeZone(TimeZone.getTimeZone("UTC"));
        return format.format(new Date(millis));
    }
}
