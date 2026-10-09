package com.thorium.preview;

import android.os.Environment;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/** Builds compact, native-speed per-system indexes for EmuFusion's game rails. */
final class LibraryIndexManager {
    private static final File CONFIG = new File(Environment.getExternalStorageDirectory(),
            "Android/data/com.thorium.preview/files/pegasus-frontend");

    private String cached = "";
    private long cachedFingerprint;

    synchronized String json() {
        try {
            List<File> files = metadataFiles();
            long fingerprint = fingerprint(files);
            if (!cached.isEmpty() && fingerprint == cachedFingerprint) return cached;
            cached = build(files).toString();
            cachedFingerprint = fingerprint;
            return cached;
        } catch (Exception error) {
            return "{\"systems\":{},\"error\":\"index unavailable\"}";
        }
    }

    synchronized void invalidate() {
        cached = "";
        cachedFingerprint = 0L;
    }

    private static JSONObject build(List<File> files) throws Exception {
        Map<String, Map<String, Row>> bySystem = new LinkedHashMap<>();
        for (File file : files) parse(file, bySystem);
        JSONObject systems = new JSONObject();
        for (Map.Entry<String, Map<String, Row>> entry : bySystem.entrySet()) {
            List<Row> rows = new ArrayList<>(entry.getValue().values());
            JSONObject modes = new JSONObject();
            modes.put("critic", keys(sorted(rows, (left, right) -> {
                int value = Double.compare(right.critic, left.critic);
                return value != 0 ? value : left.key.compareTo(right.key);
            })));
            modes.put("user", keys(sorted(rows, (left, right) -> {
                int value = left.userSort.compareTo(right.userSort);
                return value != 0 ? value : left.key.compareTo(right.key);
            })));
            modes.put("alpha", keys(sorted(rows, Comparator.comparing(row -> row.key))));
            modes.put("release", keys(sorted(rows, (left, right) -> {
                int value = right.release.compareTo(left.release);
                return value != 0 ? value : left.key.compareTo(right.key);
            })));
            systems.put(entry.getKey(), modes);
        }
        JSONObject out = new JSONObject();
        out.put("systems", systems);
        return out;
    }

    private static void parse(File file, Map<String, Map<String, Row>> bySystem)
            throws Exception {
        String collection = "";
        Row current = null;
        try (BufferedReader reader = new BufferedReader(new FileReader(file))) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.startsWith("collection:")) {
                    commit(current, bySystem);
                    current = null;
                    collection = value(line);
                } else if (line.startsWith("game:")) {
                    commit(current, bySystem);
                    current = new Row(folderForCollection(collection), value(line));
                } else if (current != null && line.startsWith("rating:")) {
                    String raw = value(line).replace("%", "").trim();
                    try { current.critic = Double.parseDouble(raw); }
                    catch (NumberFormatException ignored) {}
                } else if (current != null && line.startsWith("sort-by:")) {
                    current.userSort = value(line).toLowerCase(Locale.US);
                } else if (current != null && line.startsWith("release:")) {
                    current.release = value(line);
                }
            }
        }
        commit(current, bySystem);
    }

    private static void commit(Row row, Map<String, Map<String, Row>> bySystem) {
        if (row == null || row.folder.isEmpty() || row.title.isEmpty()) return;
        Map<String, Row> system = bySystem.computeIfAbsent(row.folder,
                ignored -> new LinkedHashMap<>());
        Row existing = system.get(row.key);
        if (existing == null) {
            system.put(row.key, row);
            return;
        }
        if (row.critic > existing.critic) existing.critic = row.critic;
        if (!row.release.isEmpty()) existing.release = row.release;
        if (!row.userSort.startsWith("99999")) existing.userSort = row.userSort;
    }

    private static String folderForCollection(String collection) {
        for (GameSystems.SystemDef system : GameSystems.all()) {
            if (system.collection.equalsIgnoreCase(collection)) return system.folder;
        }
        return "";
    }

    private static String value(String line) {
        int colon = line.indexOf(':');
        return colon < 0 ? "" : line.substring(colon + 1).trim();
    }

    private static String key(String folder, String title) {
        return folder + "|" + title.toLowerCase(Locale.US).trim().replaceAll("\\s+", " ");
    }

    private static List<Row> sorted(List<Row> source, Comparator<Row> comparator) {
        List<Row> copy = new ArrayList<>(source);
        copy.sort(comparator);
        return copy;
    }

    private static JSONArray keys(List<Row> rows) {
        JSONArray values = new JSONArray();
        for (Row row : rows) values.put(row.key);
        return values;
    }

    private static List<File> metadataFiles() {
        List<File> files = new ArrayList<>();
        collect(new File(CONFIG, "metadata"), files);
        collect(new File(CONFIG, "metafiles"), files);
        Collections.sort(files, Comparator.comparing(File::getAbsolutePath));
        return files;
    }

    private static void collect(File directory, List<File> files) {
        File[] children = directory.listFiles();
        if (children == null) return;
        for (File child : children) {
            if (child.isDirectory()) collect(child, files);
            else if (child.getName().endsWith(".metadata.pegasus.txt")) files.add(child);
        }
    }

    private static long fingerprint(List<File> files) {
        long value = files.size();
        for (File file : files)
            value = value * 31L + file.length() * 17L + file.lastModified();
        return value;
    }

    private static final class Row {
        final String folder;
        final String title;
        final String key;
        double critic = -1.0;
        String userSort = "99999";
        String release = "0000-00-00";

        Row(String folder, String title) {
            this.folder = folder == null ? "" : folder;
            this.title = title == null ? "" : title;
            this.key = key(this.folder, this.title);
        }
    }
}
