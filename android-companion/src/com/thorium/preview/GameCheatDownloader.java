package com.thorium.preview;

import android.content.Context;
import android.os.SystemClock;
import android.util.Log;

import com.thorium.lucent.metadata.EngineSystemIdResolver;
import com.thorium.preview.cheats.CheatControl;
import com.thorium.preview.cheats.sources.CheatFetch;
import com.thorium.preview.cheats.sources.CheatGameIdentity;
import com.thorium.preview.cheats.sources.CheatSource;
import com.thorium.preview.cheats.sources.CheatSourceFetcher;
import com.thorium.preview.cheats.sources.CheatSourceRegistry;
import com.thorium.preview.cheats.sources.CheatSourceSlicer;
import com.thorium.preview.cheats.sources.DownloadedCheat;
import com.thorium.preview.cheats.sources.DownloadedCheatCodec;
import com.thorium.preview.cheats.sources.DownloadedCheatDocument;
import com.thorium.preview.cheats.sources.DownloadedCheatFile;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * The per-game "download every cheat" step of the metadata update.
 *
 * <p>Called by {@code ImportManager.runScan} for each newly imported game
 * (and by the manual library refresh): resolves the canonical system, reads
 * the game's identity from the ROM, walks the enabled sources for that
 * system, slices the game's rows out of each bulk archive (cached seven days
 * under {@code <cacheRoot>/cheats/}), and writes the per-game file that
 * {@code CheatCatalog.forGame} merges at runtime. The file is written under
 * the ROM's on-disk stem and, when the import renamed the file, under the
 * original stem too, so both the launch path and the library resolve it.
 *
 * <p>Nothing here blocks or fails a game: every failure is logged and the
 * game keeps whatever file it already had.
 */
public final class GameCheatDownloader {
    private static final String TAG = "LucentCheatFetch";
    /** {@code ImportManager.REGISTRY}; duplicated because that constant is private. */
    private static final File REGISTRY = new File(
            "/storage/emulated/0/pegasus-frontend/thorium-imports.json");

    private GameCheatDownloader() {}

    /**
     * @param originalName the candidate's original file name (or the import's
     *                     {@code sourceIdentity}, whose path is used); serial
     *                     and title-id regexes keep working after a rename
     * @return the number of cheats now on file for the game
     */
    public static int fetch(Context context, String systemFolder, String title, File rom,
                            String originalName, File cacheRoot) {
        return fetch(context, systemFolder, title, rom, originalName, cacheRoot, Long.MAX_VALUE);
    }

    /**
     * @param deadlineElapsedRealtime a {@link SystemClock#elapsedRealtime()} value past which no
     *     further enabled source is attempted for this game (each remaining source is simply
     *     skipped, exactly as if it had found nothing this round); {@code Long.MAX_VALUE} for no
     *     bound. {@link #refreshLibrary} passes its own budget through here: without this, its
     *     round-robin loop only re-checks the wall clock between whole games, so one game whose
     *     several enabled sources each stall against a different host (a captive portal, flaky
     *     mobile data) could by itself run well past the budget before the loop ever looked again.
     *     The remaining time before this deadline is also threaded into
     *     {@link CheatGameIdentity#identify(String, File, String, long)} as its CRC32 budget, so a
     *     large NES/SNES/N64/NDS dump's whole-file hash -- the one identity read that is not a
     *     bounded header read -- cannot by itself consume the rest of a refresh batch either.
     */
    static int fetch(Context context, String systemFolder, String title, File rom,
                      String originalName, File cacheRoot, long deadlineElapsedRealtime) {
        if (context == null || rom == null) return 0;
        try {
            String canonical = EngineSystemIdResolver.canonical(systemFolder);
            if (canonical.isEmpty()) return 0;
            String original = originalFileName(originalName);
            File cheatDirectory = CheatControl.directory(context);
            File preferences = CheatSourceRegistry.preferencesFile(cheatDirectory);
            List<CheatSource> sources = CheatSourceRegistry.enabledForSystem(preferences, canonical);
            File primary = DownloadedCheatFile.pathFor(context, canonical, rom.getName());
            if (sources.isEmpty()) return existingCount(primary);

            long crcBudgetMillis = deadlineElapsedRealtime == Long.MAX_VALUE ? -1L
                    : Math.max(0L, deadlineElapsedRealtime - SystemClock.elapsedRealtime());
            Map<String, String> identity = CheatGameIdentity.identify(canonical, rom, original, crcBudgetMillis);
            CheatFetch fetcher = new CheatSourceFetcher(cacheRoot == null
                    ? new File(cheatDirectory, "cache") : cacheRoot);
            CheatSourceSlicer slicer = new CheatSourceSlicer(fetcher,
                    CheatControl.downloadedArchive(context));
            String stem = CheatGameIdentity.stem(rom.getName());
            DownloadedCheatDocument document = new DownloadedCheatDocument(canonical, stem);
            document.identity.putAll(identity);
            for (CheatSource source : sources) {
                if (SystemClock.elapsedRealtime() >= deadlineElapsedRealtime) break;
                List<DownloadedCheat> rows = slicer.slice(source, canonical, identity,
                        title == null ? stem : title, rom.getName(), original);
                document.addAll(rows);
            }
            document.identity.clear();
            document.identity.putAll(identity);

            int existing = existingCount(primary);
            if (document.isEmpty() && existing > 0) {
                Log.i(TAG, "Kept " + existing + " previously downloaded cheats for " + stem);
                return existing;
            }
            DownloadedCheatFile.write(primary, document);
            String originalStem = CheatGameIdentity.stem(original);
            if (!originalStem.isEmpty()) {
                File alias = DownloadedCheatFile.pathFor(context, canonical, originalStem);
                if (!alias.getAbsolutePath().equals(primary.getAbsolutePath()))
                    DownloadedCheatFile.write(alias, document);
            }
            Log.i(TAG, "Downloaded " + document.size() + " cheats for " + canonical + " " + stem
                    + " from " + document.sources);
            return document.size();
        } catch (Throwable failed) {
            Log.w(TAG, "Cheat download unavailable for " + title + ": " + failed);
            return 0;
        }
    }

    /**
     * A library refresh is not allowed to make a manual "Rescan" (or a
     * routine full-discovery pass) block for minutes: a few thousand ROMs
     * would each cost an identity read plus a cheat-archive slice. Bound one
     * call to a batch of games and a wall-clock budget, whichever is hit
     * first, and remember where it stopped ({@link #REFRESH_CURSOR_FILE}) so
     * the next scan resumes there instead of restarting from the front --
     * every game reaches its turn within a handful of rescans, and no single
     * rescan is slowed down by the size of the library. The budget is also
     * threaded into each game's own {@link #fetch} call (see its
     * {@code deadlineElapsedRealtime} parameter), so a single game whose
     * several enabled sources each stall against a different host cannot by
     * itself blow through the whole budget between deadline checks.
     */
    private static final int REFRESH_BATCH_LIMIT = 150;
    private static final long REFRESH_TIME_BUDGET_MS = 45_000L;
    private static final String REFRESH_CURSOR_FILE = "cheats-refresh-cursor.txt";

    /**
     * Re-runs the per-game step for a bounded, round-robin slice of the
     * import registry (see the constants above); never fails the scan.
     */
    public static int refreshLibrary(Context context, File cacheRoot) {
        int total = 0;
        File cursorFile = cacheRoot == null ? null : new File(cacheRoot, REFRESH_CURSOR_FILE);
        try {
            if (!REGISTRY.isFile() || REGISTRY.length() > 64L * 1024L * 1024L) return 0;
            String text;
            try (InputStream input = new FileInputStream(REGISTRY)) {
                text = readAll(input, 64L * 1024L * 1024L);
            }
            JSONArray rows = new JSONArray(text);
            int count = rows.length();
            if (count == 0) return 0;
            int index = Math.abs(readCursor(cursorFile)) % count;
            long deadline = SystemClock.elapsedRealtime() + REFRESH_TIME_BUDGET_MS;
            int processed = 0;
            while (processed < count && processed < REFRESH_BATCH_LIMIT
                    && SystemClock.elapsedRealtime() < deadline) {
                JSONObject row = rows.optJSONObject(index);
                if (row != null) {
                    File rom = new File(row.optString("file", ""));
                    String system = row.optString("system", "");
                    if (!system.isEmpty() && (rom.isFile() || rom.isDirectory())) {
                        total += fetch(context, system, row.optString("title", ""), rom,
                                row.optString("sourceIdentity", ""), cacheRoot, deadline);
                    }
                }
                processed++;
                index = (index + 1) % count;
            }
            writeCursor(cursorFile, index);
            Log.i(TAG, "Library cheat refresh processed " + processed + " of " + count +
                    " games, next cursor=" + index);
        } catch (Throwable failed) {
            Log.w(TAG, "Library cheat refresh stopped: " + failed);
        }
        return total;
    }

    /** 0 for a missing, unreadable or corrupt cursor: the round-robin just starts over. */
    private static int readCursor(File file) {
        if (file == null || !file.isFile()) return 0;
        try (InputStream input = new FileInputStream(file)) {
            String text = readAll(input, 64L).trim();
            return text.isEmpty() ? 0 : Integer.parseInt(text);
        } catch (Exception unreadable) {
            return 0;
        }
    }

    /** Best effort: a lost cursor merely restarts the round-robin at 0 next time. */
    private static void writeCursor(File file, int index) {
        if (file == null) return;
        try {
            File parent = file.getParentFile();
            if (parent != null) parent.mkdirs();
            File tmp = new File(parent, file.getName() + ".tmp");
            try (java.io.FileOutputStream out = new java.io.FileOutputStream(tmp)) {
                out.write(Integer.toString(index).getBytes(StandardCharsets.UTF_8));
            }
            if (!tmp.renameTo(file)) tmp.delete();
        } catch (Exception ignored) {
            // Best effort only; refreshLibrary must never fail the scan over this.
        }
    }

    /**
     * Accepts a bare file name, a path, or an import identity: {@code path:length}
     * for loose files, {@code archive.zip!entry/name.ext:crc} for archive entries.
     */
    static String originalFileName(String value) {
        if (value == null) return "";
        String clean = value.trim();
        if (clean.startsWith("metadata:")) clean = clean.substring("metadata:".length());
        if (clean.matches("(?s).*:[A-Za-z0-9_-]+$")) clean = clean.substring(0, clean.lastIndexOf(':'));
        int bang = clean.lastIndexOf('!');
        if (bang >= 0) clean = clean.substring(bang + 1);
        int slash = Math.max(clean.lastIndexOf('/'), clean.lastIndexOf('\\'));
        if (slash >= 0) clean = clean.substring(slash + 1);
        return clean;
    }

    private static int existingCount(File file) {
        return DownloadedCheatCodec.readDetailed(file).size();
    }

    private static String readAll(InputStream input, long cap) throws IOException {
        java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
        byte[] chunk = new byte[16 * 1024];
        int read;
        long total = 0;
        while ((read = input.read(chunk)) > 0) {
            total += read;
            if (total > cap) throw new IOException("registry too large");
            out.write(chunk, 0, read);
        }
        return new String(out.toByteArray(), StandardCharsets.UTF_8);
    }

    /** Convenience for a control-plane listing of the sources and their switches. */
    public static String describeSources(Context context) {
        return CheatSourceRegistry.describe(
                CheatSourceRegistry.preferencesFile(CheatControl.directory(context)));
    }

    /** The per-game files for a system, for maintenance listings. */
    public static List<File> downloadedFiles(Context context, String systemFolder) {
        List<File> result = new ArrayList<>();
        File directory = new File(DownloadedCheatFile.directory(context),
                EngineSystemIdResolver.canonical(systemFolder));
        File[] files = directory.listFiles();
        if (files != null) for (File file : files) if (file.getName().endsWith(".json")) result.add(file);
        return result;
    }
}
