package com.thorium.preview.cheats.sources;

import java.io.File;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Games listed in hand-written Pegasus metadata ({@code collection:} blocks
 * with {@code files:}, {@code game:} blocks with {@code file:}). They never
 * pass through an import, so the cheat downloader would otherwise never see
 * them. Pure parsing, provable on the host.
 */
public final class CuratedLibraryGames {
    private static final Pattern LAUNCH_SYSTEM = Pattern.compile("--es\\s+system\\s+\"?([A-Za-z0-9_-]+)");

    private CuratedLibraryGames() {}

    public static final class Game {
        public final String system;
        public final File file;
        public final String title;

        Game(String system, File file, String title) {
            this.system = system;
            this.file = file;
            this.title = title;
        }
    }

    /** Every listed file with its system (from the launch line or shortname) and title. */
    public static List<Game> parse(String text, File metadataDirectory) {
        Map<String, Game> games = new LinkedHashMap<>();
        Map<String, String> titles = new LinkedHashMap<>();
        String system = "";
        String key = "";
        String title = null;
        boolean inCollection = false;
        for (String raw : text.split("\n", -1)) {
            String line = raw.replace("\r", "");
            if (line.trim().isEmpty() || line.trim().startsWith("#")) continue;
            boolean continuation = Character.isWhitespace(line.charAt(0));
            if (!continuation) {
                int colon = line.indexOf(':');
                if (colon <= 0) { key = ""; continue; }
                key = line.substring(0, colon).trim().toLowerCase(Locale.US);
                String value = line.substring(colon + 1).trim();
                if (key.equals("collection")) {
                    system = "";
                    title = null;
                    inCollection = true;
                } else if (key.equals("game")) {
                    title = value;
                    inCollection = false;
                } else if (key.equals("shortname") && inCollection && system.isEmpty()) {
                    system = value;
                } else if (key.equals("launch") && inCollection) {
                    Matcher matcher = LAUNCH_SYSTEM.matcher(value);
                    if (matcher.find()) system = matcher.group(1);
                } else if ((key.equals("file") || key.equals("files")) && !value.isEmpty()) {
                    add(games, titles, system, resolve(value, metadataDirectory), inCollection ? null : title);
                }
            } else if (key.equals("files") || key.equals("file")) {
                add(games, titles, system, resolve(line.trim(), metadataDirectory), inCollection ? null : title);
            }
        }
        List<Game> result = new ArrayList<>();
        for (Game game : games.values()) {
            String named = titles.get(game.file.getPath());
            result.add(named == null ? game : new Game(game.system, game.file, named));
        }
        return result;
    }

    private static void add(Map<String, Game> games, Map<String, String> titles, String system,
                            File file, String title) {
        if (file == null) return;
        String path = file.getPath();
        if (title != null && !title.isEmpty()) titles.put(path, title);
        Game existing = games.get(path);
        if (existing == null || existing.system.isEmpty())
            games.put(path, new Game(system == null ? "" : system, file,
                    CheatGameIdentity.stem(file.getName())));
    }

    private static File resolve(String value, File directory) {
        String path = value.trim();
        if (path.isEmpty() || path.contains("://")) return null;
        File file = new File(path);
        if (!file.isAbsolute()) file = directory == null ? null : new File(directory, path);
        return file;
    }
}
