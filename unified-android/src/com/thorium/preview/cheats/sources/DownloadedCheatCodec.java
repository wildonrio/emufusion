package com.thorium.preview.cheats.sources;

import com.thorium.lucent.cheats.Cheat;
import com.thorium.lucent.cheats.CheatDatabase;
import com.thorium.lucent.metadata.EngineSystemIdResolver;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Reads and writes the per-game downloaded cheat file.
 *
 * <p>The layout is the {@code CheatCatalog} JSON shape ({@code games[].cheats[]}
 * with {@code id/name/description/code}) plus provenance fields that older
 * readers ignore: a top-level {@code identity} map, {@code fetchedAt},
 * {@code sources}, and per-row {@code source/delivery/tags/engineFormat}.
 * Absence and corruption both read as "no cheats"; the file is advisory and
 * must never keep a game from starting.
 */
public final class DownloadedCheatCodec {
    static final long MAX_FILE_BYTES = 16L * 1024L * 1024L;
    static final String BOOT_NOTE = "applies on next launch";
    static final String UNSUPPORTED_NOTE = "not applied by the packaged engine yet";

    private DownloadedCheatCodec() {}

    /**
     * {@code <downloadedDirectory>/<canonical system>/<CheatDatabase.normalise(stem)>.json}.
     * The stem is normalised because that is the key both the running engine and
     * the library use to find a game; an alias system id resolves to the same file.
     */
    public static File pathFor(File downloadedDirectory, String canonicalSystem, String titleOrStem) {
        String system = EngineSystemIdResolver.canonical(canonicalSystem);
        if (system.isEmpty()) system = "unknown";
        String stem = CheatDatabase.normalise(titleOrStem);
        if (stem.isEmpty()) stem = "untitled";
        if (stem.length() > 160) stem = stem.substring(0, 160);
        return new File(new File(downloadedDirectory, system), stem + ".json");
    }

    public static void write(File file, DownloadedCheatDocument document) throws IOException {
        if (file == null || document == null) throw new IOException("nothing to write");
        File parent = file.getParentFile();
        if (parent != null && !parent.isDirectory() && !parent.mkdirs() && !parent.isDirectory())
            throw new IOException("cannot create " + parent);
        byte[] bytes = toJson(document).getBytes(StandardCharsets.UTF_8);
        File part = new File(file.getAbsolutePath() + ".part");
        try (FileOutputStream out = new FileOutputStream(part)) {
            out.write(bytes);
            out.getFD().sync();
        }
        if (file.exists() && !file.delete() && file.exists()) {
            part.delete();
            throw new IOException("cannot replace " + file);
        }
        if (!part.renameTo(file)) {
            part.delete();
            throw new IOException("cannot rename " + part + " to " + file);
        }
    }

    public static String toJson(DownloadedCheatDocument document) {
        Map<String, Object> root = new LinkedHashMap<>();
        root.put("schemaVersion", (long) DownloadedCheatDocument.SCHEMA_VERSION);
        root.put("system", document.system);
        root.put("title", document.title);
        root.put("identity", new LinkedHashMap<String, Object>(document.identity));
        root.put("fetchedAt", document.fetchedAt == null ? "" : document.fetchedAt);
        root.put("sources", new ArrayList<Object>(document.sources));
        List<Object> rows = new ArrayList<>();
        for (DownloadedCheat row : document.cheats()) {
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("id", row.cheat.id);
            entry.put("name", row.cheat.name);
            entry.put("description", row.cheat.description);
            entry.put("code", row.cheat.code);
            entry.put("source", row.source);
            entry.put("delivery", row.delivery);
            entry.put("tags", new ArrayList<Object>(row.tags));
            entry.put("engineFormat", row.engineFormat);
            rows.add(entry);
        }
        Map<String, Object> game = new LinkedHashMap<>();
        game.put("system", document.system);
        game.put("title", document.title);
        game.put("cheats", rows);
        List<Object> games = new ArrayList<>();
        games.add(game);
        root.put("games", games);
        return JsonLite.write(root);
    }

    /** The rows as plain cheats; boot/unsupported rows say so in their description. */
    public static List<Cheat> read(File file) {
        List<DownloadedCheat> detailed = readDetailed(file);
        List<Cheat> result = new ArrayList<>(detailed.size());
        for (DownloadedCheat row : detailed) result.add(annotated(row));
        return Collections.unmodifiableList(result);
    }

    public static Cheat annotated(DownloadedCheat row) {
        String note = DownloadedCheat.DELIVERY_BOOT.equals(row.delivery) ? BOOT_NOTE
                : DownloadedCheat.DELIVERY_UNSUPPORTED.equals(row.delivery) ? UNSUPPORTED_NOTE : "";
        if (note.isEmpty() || row.cheat.description.contains(note)) return row.cheat;
        String description = row.cheat.description.isEmpty() ? note
                : row.cheat.description + " • " + note;
        return new Cheat(row.cheat.id, row.cheat.name, description, row.cheat.code);
    }

    public static List<DownloadedCheat> readDetailed(File file) {
        DownloadedCheatDocument document = readDocument(file);
        return document == null ? Collections.<DownloadedCheat>emptyList() : document.cheats();
    }

    public static Map<String, String> readIdentity(File file) {
        DownloadedCheatDocument document = readDocument(file);
        return document == null ? Collections.<String, String>emptyMap()
                : Collections.unmodifiableMap(new LinkedHashMap<>(document.identity));
    }

    /** @return null when the file is absent, unreadable, oversized or malformed */
    public static DownloadedCheatDocument readDocument(File file) {
        if (file == null || !file.isFile() || file.length() <= 0 || file.length() > MAX_FILE_BYTES)
            return null;
        String text;
        try (InputStream input = new FileInputStream(file)) {
            text = readAll(input, MAX_FILE_BYTES);
        } catch (IOException unreadable) {
            return null;
        }
        return fromJson(text);
    }

    public static DownloadedCheatDocument fromJson(String text) {
        Map<String, Object> root;
        try {
            Object parsed = JsonLite.parse(text);
            if (!(parsed instanceof Map)) return null;
            root = JsonLite.object(parsed);
        } catch (RuntimeException malformed) {
            return null;
        }
        DownloadedCheatDocument document = new DownloadedCheatDocument(
                JsonLite.string(root.get("system")), JsonLite.string(root.get("title")));
        document.fetchedAt = JsonLite.string(root.get("fetchedAt"));
        for (Map.Entry<String, Object> entry : JsonLite.object(root.get("identity")).entrySet())
            if (entry.getValue() != null)
                document.identity.put(entry.getKey(), JsonLite.string(entry.getValue()));
        for (Object source : JsonLite.array(root.get("sources"))) {
            String value = JsonLite.string(source);
            if (!value.isEmpty() && !document.sources.contains(value)) document.sources.add(value);
        }
        for (Object gameValue : JsonLite.array(root.get("games"))) {
            Map<String, Object> game = JsonLite.object(gameValue);
            for (Object rowValue : JsonLite.array(game.get("cheats"))) {
                Map<String, Object> row = JsonLite.object(rowValue);
                List<String> tags = new ArrayList<>();
                for (Object tag : JsonLite.array(row.get("tags"))) tags.add(JsonLite.string(tag));
                try {
                    Cheat cheat = new Cheat(JsonLite.string(row.get("id")),
                            JsonLite.string(row.get("name")),
                            JsonLite.string(row.get("description")),
                            JsonLite.string(row.get("code")));
                    document.add(new DownloadedCheat(cheat, JsonLite.string(row.get("source")),
                            JsonLite.string(row.get("delivery")), tags,
                            JsonLite.string(row.get("engineFormat"))));
                } catch (IllegalArgumentException unusable) {
                    // One bad row must not cost the game its other cheats.
                }
            }
        }
        return document;
    }

    static String readAll(InputStream input, long cap) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] chunk = new byte[8192];
        int read;
        long total = 0;
        while ((read = input.read(chunk)) > 0) {
            total += read;
            if (total > cap) throw new IOException("file exceeds " + cap + " bytes");
            out.write(chunk, 0, read);
        }
        return new String(out.toByteArray(), StandardCharsets.UTF_8);
    }
}
