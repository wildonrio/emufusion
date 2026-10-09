package com.thorium.preview;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.RectF;
import android.os.Environment;
import android.os.SystemClock;
import android.util.Log;

import com.thorium.lucent.metadata.TitleMatcher;
import com.thorium.lucent.metadata.WallpaperAccent;
import com.thorium.preview.game.NativeAdapterPrerequisites;

import org.apache.commons.compress.archivers.sevenz.SevenZArchiveEntry;
import org.apache.commons.compress.archivers.sevenz.SevenZFile;
import org.apache.commons.compress.archivers.sevenz.SevenZFileOptions;
import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.FileReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLDecoder;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.text.Normalizer;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.zip.CRC32;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/**
 * Conservative, non-blocking Downloads importer for the THOR library.
 *
 * A file is moved only after its payload validates as a supported ROM. Ambiguous
 * disc/archive formats are deliberately left in Downloads. Metadata and the
 * registry are written atomically so a killed service cannot corrupt the library.
 */
final class ImportManager {
    private static final String TAG = "ThorImporter";
    private static final String USER_AGENT = "Lucent-Importer/1.0";
    private static final long MAX_ARCHIVE_ENTRY_BYTES = 128L * 1024L * 1024L * 1024L;
    private static final long ARCHIVE_INSPECTION_BYTES = 8L * 1024L * 1024L;
    private static final SevenZFileOptions SEVEN_Z_OPTIONS = SevenZFileOptions.builder()
            .withMaxMemoryLimitInKb(448 * 1024)
            .build();
    private static final File DOWNLOADS = Environment.getExternalStoragePublicDirectory(
            Environment.DIRECTORY_DOWNLOADS);
    private static final File GAMES = new File(Environment.getExternalStorageDirectory(), "Games");
    private static final File PEGASUS = new File(Environment.getExternalStorageDirectory(),
            "pegasus-frontend");
    private static final File PEGASUS_CONFIG = new File(Environment.getExternalStorageDirectory(),
            "Android/data/org.pegasus_frontend.android/files/pegasus-frontend");
    private static final File LUCENT_CONFIG = new File(Environment.getExternalStorageDirectory(),
            "Android/data/com.thorium.preview/files/pegasus-frontend");
    private static final File REGISTRY = new File(PEGASUS, "thorium-imports.json");
    private static final String BACKGROUND_SOURCE_WALLPAPER = "audited-wallpaper";
    private static final String BACKGROUND_SOURCE_LAUNCHBOX = "launchbox-fanart-background";
    private static final String BACKGROUND_SOURCE_OFFICIAL = "official-gallery-image";
    private static final String BACKGROUND_SOURCE_SCREENSHOT = "exact-gameplay-screenshot";
    private static final String BACKGROUND_TRANSFORM = "center-crop-1920x1080-no-stretch";
    private static final Map<String, Boolean> WALLPAPER_QUALITY_CACHE =
            new ConcurrentHashMap<>();
    private static volatile boolean wallpaperQualityCacheLoaded;
    private static final File AUTO_METADATA = new File(new File(PEGASUS_CONFIG, "metafiles"),
            "99-lucent-auto-import.metadata.pegasus.txt");
    private static final File LUCENT_AUTO_METADATA = new File(new File(LUCENT_CONFIG, "metafiles"),
            "99-lucent-auto-import.metadata.pegasus.txt");
    private static final File LEGACY_AUTO_METADATA = new File(PEGASUS,
            "99-lucent-auto-import.metadata.pegasus.txt");
    private static final File THORIUM_LEGACY_AUTO_METADATA = new File(PEGASUS,
            "99-thorium-auto-import.metadata.pegasus.txt");
    private static final File THORIUM_LEGACY_CONFIG_METADATA = new File(
            new File(PEGASUS_CONFIG, "metafiles"),
            "99-thorium-auto-import.metadata.pegasus.txt");
    private static final long RESCAN_THROTTLE_MS = 45_000L;
    private static final long MISS_RETRY_MS = 7L * 24L * 60L * 60L * 1000L;
    /** Where every artwork-driven library removal is written down. */
    private static final String ARTLESS_LEDGER = "removed-without-artwork.json";
    /**
     * The owner's answer for each game whose artwork could not be found.
     * It lives beside the media rather than in app storage so it survives a
     * reinstall, and it is keyed by system and normalized title so it also
     * survives the ROM moving between volumes.
     */
    private static final String ARTWORK_DECISIONS = "artwork-decisions.json";
    /** Games still waiting for an answer, as rendered by the frontend. */
    private static final String ARTWORK_REVIEW_QUEUE = "artwork-review-pending.json";
    /** Keep the game exactly as it is, with no box art. */
    private static final String CHOICE_KEEP = "leave";
    /** Take it out of the menus; the ROM file stays on disk. */
    private static final String CHOICE_HIDE = "hide";
    /** Delete the ROM file itself. The only choice that destroys data. */
    private static final String CHOICE_DELETE = "delete-rom";
    private static final Pattern HREF = Pattern.compile("href=\"([^\"]+\\.(?:png|jpg|jpeg))\"",
            Pattern.CASE_INSENSITIVE);
    private static final Pattern NINTENDO_TITLE = Pattern.compile(
            "<title[^>]*>(.*?) for Nintendo Switch(?:[^<]*)</title>",
            Pattern.CASE_INSENSITIVE | Pattern.DOTALL);
    private static final Pattern NINTENDO_PRODUCT_ASSET = Pattern.compile(
            "store/software/switch/(\\d{14})/([a-f0-9]{40,64})",
            Pattern.CASE_INSENSITIVE);
    private static final Pattern NINTENDO_SQUARE_COVER = Pattern.compile(
            "productImage\\([^)]*square[^)]*\\).*?\"url\":\"(https://assets\\.nintendo\\.com/image/fetch/[^\"]+)",
            Pattern.CASE_INSENSITIVE | Pattern.DOTALL);
    private static final Pattern NINTENDO_GALLERY_ASSET = Pattern.compile(
            "\\\"publicId\\\":\\\"(/?store/software/switch/[^\\\"]+)\\\",\\\"resourceType\\\":\\\"(video|image)\\\"",
            Pattern.CASE_INSENSITIVE);
    private static final byte[] GB_LOGO = new byte[]{
            (byte)0xCE,(byte)0xED,0x66,0x66,(byte)0xCC,0x0D,0x00,0x0B,0x03,0x73,0x00,(byte)0x83,
            0x00,0x0C,0x00,0x0D,0x00,0x08,0x11,0x1F,(byte)0x88,(byte)0x89,0x00,0x0E,(byte)0xDC,
            (byte)0xCC,0x6E,(byte)0xE6,(byte)0xDD,(byte)0xDD,(byte)0xD9,(byte)0x99,(byte)0xBB,
            (byte)0xBB,0x67,0x63,0x6E,0x0E,(byte)0xEC,(byte)0xCC,(byte)0xDD,(byte)0xDC,(byte)0x99,
            (byte)0x9F,(byte)0xBB,(byte)0xB9,0x33,0x3E
    };

    private final Context context;
    private final AtomicBoolean running = new AtomicBoolean(false);
    private final AtomicBoolean initialScanStarted = new AtomicBoolean(false);
    private final android.os.Handler mediaHandler = new android.os.Handler(android.os.Looper.getMainLooper());
    private volatile boolean closed;
    private volatile Thread scanWorker;
    private final Runnable resumeMedia = new Runnable() {
        @Override public void run() {
            if (closed) return;
            if (!running.get() && networkAvailable() && hasPendingMedia()) startScan(false, true);
            mediaHandler.postDelayed(this, 120_000L);
        }
    };
    private final Object statusLock = new Object();
    private volatile long lastScanStarted;
    private volatile String lastDownloadFingerprint = "";
    private JSONObject status = idleStatus();
    private volatile Map<String, GameRankingsRecord> gamerankingsIndex;
    private volatile Map<String, GameRankingsRecord> gamerankingsAliasIndex;
    private volatile Map<String, MobyGamesRecord> mobygamesIndex;
    private volatile Map<String, MobyGamesRecord> mobygamesAliasIndex;
    private volatile Map<String, BundledGameRecord> bundledGameIndex;
    /**
     * Sibling titles per system folder, for the artwork subtitle guard. Built
     * once per scan and dropped at the start of the next one, so a game added
     * during this scan is still seen by the games processed after it.
     */
    private final Map<String, Set<String>> claimedTitleCache = new ConcurrentHashMap<>();

    ImportManager(Context context) {
        this.context = context.getApplicationContext();
    }

    void startScan() {
        startScan(false, false);
    }

    void startInitialScan() {
        if (!ThemeInstaller.hasStorageAccess(context)) {
            setStatus("permission", 0.0,
                    "Grant library access to begin the automatic first scan",
                    Collections.emptyList(), 0, false);
            return;
        }
        if (!initialScanStarted.compareAndSet(false, true)) return;
        if (!running.compareAndSet(false, true)) {
            initialScanStarted.set(false);
            return;
        }
        Thread worker = new Thread(() -> {
            boolean changed = false;
            try {
                changed = bootstrapLocalLibrary();
            } catch (Exception error) {
                initialScanStarted.set(false);
                Log.e(TAG, "Local library discovery failed", error);
                setStatus("error", 1.0, "Could not scan games: " + shortError(error),
                        Collections.emptyList(), 0, false);
            } finally {
                running.set(false);
                Context app = context.getApplicationContext();
                if (app instanceof LucentApplication)
                    ((LucentApplication) app).onInitialLibraryScanFinished(changed);
                // Do not wait for QML, window focus or a legal/permission
                // dialog to be dismissed. Checkpoints survive Qt retirement.
                scheduleMediaResume();
            }
        }, "emufusion-local-library");
        worker.setDaemon(true);
        worker.start();
    }

    /** Local-only bootstrap: never copy/delete ROMs or wait for online catalogs. */
    private boolean bootstrapLocalLibrary() throws Exception {
        boolean hadLibrary = hasUsableFrontendLibrary();
        List<File> roots = libraryRoots();
        StringBuilder storage = new StringBuilder("local-discovery-v2");
        for (File root : roots) storage.append('\n').append(canonical(root.getAbsolutePath()));
        String storageKey = storage.toString();
        android.content.SharedPreferences preferences =
                context.getSharedPreferences("library-discovery", Context.MODE_PRIVATE);
        // A mounted volume is not a library-contents fingerprint. Games can
        // be added anywhere below the same root between launches (including
        // by USB/MTP while EmuFusion is closed). Reconcile locally on each
        // process start; this worker never blocks the menu on network/media.
        // Existing metadata/source identities prevent duplicate entries, and
        // unchanged libraries below cause no rewrite or frontend restart.
        setStatus("discovering", 0.05, "Finding games on internal and removable storage…",
                Collections.emptyList(), 0, false);
        JSONArray registry = readRegistry();
        Set<String> registered = registeredSources(registry);
        List<Candidate> candidates = discoverExistingCandidates();
        List<String> titles = new ArrayList<>();
        int added = 0;
        for (Candidate candidate : candidates) {
            if (!registered.add(candidate.identity)) continue;
            // Do not call importCandidate here: its title canonicalization
            // consults online box-art catalogs even for an in-place game.
            ImportedGame game = new ImportedGame(candidate, candidate.source);
            enrichBundledMetadata(game);
            JSONObject row = game.toJson();
            // Index immediately; the independent, resumable media queue fills
            // artwork and metadata after the frontend can show the library.
            row.put("localDiscovery", true);
            registry.put(row);
            titles.add(game.title);
            added++;
            setStatus("indexing", 0.10 + 0.80 * added / Math.max(1, candidates.size()),
                    "Adding " + game.title + "…", Collections.emptyList(), added, false);
            // Checkpoint large libraries without rewriting every collection
            // for every game (quadratic work on a full SD card).
            if (added % 64 == 0) writeJsonAtomic(REGISTRY, registry);
        }
        if (added > 0 || !hadLibrary) {
            writeJsonAtomic(REGISTRY, registry);
        }
        // Existing registry rows can disappear/reappear when removable storage
        // changes. Reconcile those too, but publish/restart only for a changed
        // library; an unchanged scan must not rewrite every metadata file.
        boolean metadataChanged = writeMetadata(registry);
        boolean usable = hasUsableFrontendLibrary();
        // A cancelled/empty/inaccessible scan must be retried next launch.
        if (usable) preferences.edit().putString("storage", storageKey).commit();
        else initialScanStarted.set(false);
        boolean changed = metadataChanged || (usable && (!hadLibrary || added > 0));
        Log.i(TAG, "Local discovery complete: added=" + added + " usable=" + usable +
                " metadataChanged=" + metadataChanged);
        setStatus("complete", 1.0, usable ? "Game library ready" :
                "No supported games found. Check storage access and your ROM folders.",
                titles, added, false);
        return changed;
    }

    private static boolean hasUsableFrontendLibrary() {
        for (File metadata : metadataFiles()) {
            // Another app's metadata cannot make our empty frontend ready.
            if (!metadata.getParentFile().equals(PEGASUS) &&
                    !metadata.getParentFile().equals(new File(LUCENT_CONFIG, "metafiles"))) continue;
            try {
                for (String stanza : splitStanzas(readText(metadata))) {
                    String path = field(stanza, "file");
                    if (!field(stanza, "game").isEmpty() && !path.isEmpty() &&
                            readableMetadataRom(metadata, path).isFile() &&
                            readableMetadataRom(metadata, path).canRead()) return true;
                }
            } catch (Exception ignored) {}
        }
        return false;
    }

    private static File readableMetadataRom(File metadata, String path) {
        File rom = new File(path);
        return rom.isAbsolute() ? rom : new File(metadata.getParentFile(), path);
    }

    /** User-requested maintenance pass. Unlike the background scan, this is a
     * full storage discovery and is never suppressed by the fingerprint/time
     * throttle. The running guard still prevents two destructive writers from
     * touching the registry at the same time. */
    void startManualScan() {
        context.getSharedPreferences("library-discovery", Context.MODE_PRIVATE).edit()
                .putLong("mediaRefreshAfter", System.currentTimeMillis()).commit();
        startScan(true, true);
    }

    void close() {
        closed = true;
        mediaHandler.removeCallbacks(resumeMedia);
        Thread worker = scanWorker;
        if (worker != null) worker.interrupt();
    }

    private void scheduleMediaResume() {
        if (closed) return;
        mediaHandler.removeCallbacks(resumeMedia);
        mediaHandler.postDelayed(resumeMedia, 1500L);
    }

    private long mediaRefreshAfter() {
        return context.getSharedPreferences("library-discovery", Context.MODE_PRIVATE)
                .getLong("mediaRefreshAfter", 0L);
    }

    private static boolean mediaPending(JSONObject row, long refreshAfter) {
        if (row == null || !new File(row.optString("file")).isFile()) return false;
        if (row.optLong("mediaRefreshCompletedAt", 0L) < refreshAfter) return true;
        if (row.optInt("mediaVersion", 0) < 1) return true;
        // Completion is not permanent proof that files still exist: removable
        // media can disappear or be cleaned after a successful download. Only
        // reopen previously complete rows here; failed providers retain their
        // scheduled backoff instead of being retried on every queue poll.
        if (row.optInt("enrichmentVersion", 0) >= 2 && !mediaComplete(row)) return true;
        return row.optLong("mediaNextRetryAt", Long.MAX_VALUE) <= System.currentTimeMillis();
    }

    private boolean hasPendingMedia() {
        JSONArray rows = readRegistry();
        long refresh = mediaRefreshAfter();
        for (int i = 0; i < rows.length(); i++) if (mediaPending(rows.optJSONObject(i), refresh)) return true;
        return false;
    }

    private boolean networkAvailable() {
        android.net.ConnectivityManager manager = (android.net.ConnectivityManager)
                context.getSystemService(Context.CONNECTIVITY_SERVICE);
        android.net.NetworkInfo network = manager == null ? null : manager.getActiveNetworkInfo();
        return network != null && network.isConnected();
    }

    private void startScan(boolean fullDiscovery, boolean force) {
        long now = SystemClock.elapsedRealtime();
        String fingerprint = downloadFingerprint();
        if (running.get() || (!force && now - lastScanStarted < RESCAN_THROTTLE_MS &&
                fingerprint.equals(lastDownloadFingerprint))) return;
        if (!running.compareAndSet(false, true)) return;
        lastScanStarted = now;
        lastDownloadFingerprint = fingerprint;
        setStatus("scanning", 0.01, "Scanning internal and SD Downloads for verified games…",
                Collections.emptyList(), 0, false);
        Thread worker = new Thread(() -> {
            try {
                runScan(fullDiscovery);
            } catch (Throwable error) {
                Log.e(TAG, "Import failed", error);
                setStatus("error", 1.0, "Import stopped safely: " + shortError(error),
                        Collections.emptyList(), 0, false);
            } finally {
                running.set(false);
                scanWorker = null;
                scheduleMediaResume();
            }
        }, "thor-library-import");
        worker.setDaemon(true);
        scanWorker = worker;
        worker.start();
    }

    String statusJson() {
        synchronized (statusLock) {
            return status.toString();
        }
    }

    /** Atomically acknowledge the one frontend rebuild requested by a
     * completed import. Clearing the bit before relaunch prevents the fresh
     * QML instance from entering a restart loop when it reads status. */
    boolean consumeReloadRequest() {
        synchronized (statusLock) {
            if (!status.optBoolean("needsReload", false)) return false;
            try {
                status.put("needsReload", false);
                status.put("message", "New games indexed • refreshing EmuFusion library…");
                status.put("updatedAt", System.currentTimeMillis());
            } catch (Exception ignored) {}
            return true;
        }
    }

    Set<String> activeSystemFolders() {
        Set<String> systems = new LinkedHashSet<>();
        JSONArray registry = readRegistry();
        for (int index = 0; index < registry.length(); index++) {
            JSONObject row = registry.optJSONObject(index);
            if (row == null || row.optBoolean("archived", false) &&
                    !row.optBoolean("forceInclude", false)) continue;
            String folder = row.optString("system");
            if (GameSystems.byFolder(folder) != null) systems.add(folder);
        }
        // The import registry was added after owner-authored and earlier
        // Lucent metadata already existed.  Treating only registry rows as the
        // settings inventory hides real, indexed games from the route picker
        // forever (PS3 directory dumps are a common example because their
        // launch target is EBOOT.BIN rather than an extension that discovery
        // can identify on its own).  Reconcile every readable metadata game
        // with the live file it names.  Stale metadata never reveals a system:
        // the path must still exist, and the /Games/<system>/ identity must be
        // one of GameSystems' exact folders.
        for (File metadata : metadataFiles()) {
            try {
                for (String stanza : splitStanzas(readText(metadata))) {
                    String title = field(stanza, "game");
                    String path = field(stanza, "file");
                    if (title.isEmpty() || path.isEmpty() || !new File(path).exists())
                        continue;
                    GameSystems.SystemDef system = systemFromRomPath(path);
                    if (system != null) systems.add(system.folder);
                }
            } catch (Exception ignored) {
                // A malformed or unreadable metadata file reveals nothing.
            }
        }
        return systems;
    }

    String archiveJson() {
        JSONObject response = new JSONObject();
        JSONArray archived = new JSONArray();
        JSONArray registry = readRegistry();
        try {
            for (int i = 0; i < registry.length(); i++) {
                JSONObject row = registry.optJSONObject(i);
                if (row == null || !row.optBoolean("archived", false) ||
                        row.optBoolean("forceInclude", false)) continue;
                JSONObject item = new JSONObject();
                item.put("id", row.optString("sourceIdentity"));
                item.put("title", row.optString("title"));
                GameSystems.SystemDef system = GameSystems.byFolder(row.optString("system"));
                item.put("system", system == null ? row.optString("system") : system.collection);
                item.put("reason", "Missing exact box art");
                archived.put(item);
            }
            response.put("count", archived.length());
            response.put("games", archived);
        } catch (Exception ignored) {}
        return response.toString();
    }

    synchronized boolean includeArchived(String identity) {
        if (identity == null || identity.isEmpty()) return false;
        JSONArray registry = readRegistry();
        boolean changed = false;
        for (int i = 0; i < registry.length(); i++) {
            JSONObject row = registry.optJSONObject(i);
            if (row == null || !identity.equals(row.optString("sourceIdentity"))) continue;
            try {
                row.put("forceInclude", true);
                changed = true;
            } catch (Exception ignored) {}
            break;
        }
        if (!changed) return false;
        try {
            writeJsonAtomic(REGISTRY, registry);
            writeMetadata(registry);
            return true;
        } catch (Exception error) {
            Log.e(TAG, "Unable to include archived game", error);
            return false;
        }
    }

    synchronized boolean renameGame(String identity, String requestedTitle) {
        String title = cleanTitle(requestedTitle == null ? "" : requestedTitle);
        if (identity == null || identity.isEmpty() || title.isEmpty()) return false;
        JSONArray registry = readRegistry();
        boolean changed = false;
        File originalRom = null;
        File renamedRom = null;
        for (int i = 0; i < registry.length(); i++) {
            JSONObject row = registry.optJSONObject(i);
            if (row == null || !identity.equals(row.optString("sourceIdentity"))) continue;
            try {
                originalRom = new File(row.optString("file"));
                String extension = extension(originalRom.getName());
                renamedRom = new File(originalRom.getParentFile(), safeFilename(title) +
                        (extension.isEmpty() ? "" : "." + extension));
                if (!originalRom.equals(renamedRom)) {
                    if (renamedRom.exists() || !originalRom.renameTo(renamedRom)) return false;
                    row.put("file", renamedRom.getAbsolutePath());
                }
                row.put("title", title);
                changed = true;
            } catch (Exception ignored) {}
            break;
        }
        if (!changed) return false;
        try {
            writeJsonAtomic(REGISTRY, registry);
            writeMetadata(registry);
            return true;
        } catch (Exception error) {
            if (originalRom != null && renamedRom != null && renamedRom.isFile() &&
                    !originalRom.isFile()) renamedRom.renameTo(originalRom);
            Log.e(TAG, "Unable to rename game", error);
            return false;
        }
    }

    synchronized boolean deleteGame(String identity) {
        if (identity == null || identity.isEmpty()) return false;
        JSONArray registry = readRegistry();
        int found = -1;
        JSONObject row = null;
        for (int i = 0; i < registry.length(); i++) {
            JSONObject candidate = registry.optJSONObject(i);
            if (candidate != null && identity.equals(candidate.optString("sourceIdentity"))) {
                found = i;
                row = candidate;
                break;
            }
        }
        if (found < 0 || row == null) return false;
        File rom = new File(row.optString("file"));
        if (!rom.isFile()) return false;
        File volume = storageVolumeRoot(rom);
        // Stage the file on the same volume first, so a metadata write failure
        // can still restore it atomically. The staged copy is permanently
        // deleted only after Pegasus's registry and metadata commit succeeds.
        File trash = new File(new File(volume, ".LucentTrash"),
                row.optString("system", "unknown"));
        if (!trash.mkdirs() && !trash.isDirectory()) return false;
        File target = uniqueTrashTarget(trash, rom.getName());
        if (!rom.renameTo(target)) return false;
        try {
            registry.remove(found);
            writeJsonAtomic(REGISTRY, registry);
            writeMetadata(registry);
            if (target.delete()) return true;

            // A filesystem refusal must not silently turn a permanent-delete
            // request into an undeclared recoverable trash operation.
            if (!target.renameTo(rom)) return false;
            registry.put(row);
            writeJsonAtomic(REGISTRY, registry);
            writeMetadata(registry);
            return false;
        } catch (Exception error) {
            // Restore the ROM if metadata could not be committed. A failed UI
            // operation must never leave a game silently detached from Pegasus.
            target.renameTo(rom);
            Log.e(TAG, "Unable to permanently delete game", error);
            return false;
        }
    }

    private static File storageVolumeRoot(File file) {
        String path = file.getAbsolutePath();
        // /storage/emulated is a framework mount, not the writable user
        // volume. Trying to create /storage/emulated/.LucentTrash made every
        // delete of an internally stored game fail. The actual shared-storage
        // root is /storage/emulated/0 (Environment's external directory).
        String internal = Environment.getExternalStorageDirectory().getAbsolutePath();
        if (path.equals(internal) || path.startsWith(internal + File.separator))
            return Environment.getExternalStorageDirectory();
        if (path.startsWith("/storage/")) {
            int slash = path.indexOf('/', "/storage/".length());
            if (slash > 0) return new File(path.substring(0, slash));
        }
        return Environment.getExternalStorageDirectory();
    }

    private static File uniqueTrashTarget(File directory, String name) {
        File target = new File(directory, name);
        if (!target.exists()) return target;
        int dot = name.lastIndexOf('.');
        String base = dot > 0 ? name.substring(0, dot) : name;
        String extension = dot > 0 ? name.substring(dot) : "";
        return new File(directory, base + "-" + System.currentTimeMillis() + extension);
    }

    private void runScan(boolean fullDiscovery) throws Exception {
        PEGASUS.mkdirs();
        // Sibling titles are a snapshot of the library. Take a fresh one per
        // scan so games added by the previous run take part in the guard.
        claimedTitleCache.clear();
        // Thorium's retired combined metafile can coexist with EmuFusion's
        // per-system files after an in-place upgrade. Pegasus then exposes a
        // second, stale copy of every imported game; most of those old rows do
        // not contain video paths. Remove only our generated legacy files.
        THORIUM_LEGACY_AUTO_METADATA.delete();
        THORIUM_LEGACY_CONFIG_METADATA.delete();
        File metadataParent = AUTO_METADATA.getParentFile();
        if (metadataParent != null) metadataParent.mkdirs();
        File emuFusionMetadataParent = LUCENT_AUTO_METADATA.getParentFile();
        if (emuFusionMetadataParent != null) emuFusionMetadataParent.mkdirs();
        GAMES.mkdirs();
        File mediaRoot = mediaRoot();
        File cacheRoot = new File(PEGASUS, ".thorium-import-cache");
        cacheRoot.mkdirs();

        // Read-only, bounded readiness discovery belongs to the explicit
        // update/import lifecycle, never app startup or UI routing. Persisted
        // state contains only READY/NOT_READY; no source names or paths.
        boolean prerequisiteRoutesChanged = NativeAdapterPrerequisites.refresh(context);

        setStatus("scanning", 0.03, "Scanning internal and SD Downloads for verified games…",
                Collections.emptyList(), 0, false);
        List<Candidate> candidates = discoverCandidates(cacheRoot);
        if (fullDiscovery) {
            setStatus("discovering", 0.06,
                    "Finding existing game libraries on internal and removable storage…",
                    Collections.emptyList(), 0, false);
            candidates.addAll(discoverExistingCandidates());
        }
        // A full discovery also walks the Download roots scanned above. Keep
        // the first occurrence of each durable source identity so an in-place
        // PS3 folder dump (or any overlapping storage root) is never imported
        // twice during the same pass.
        candidates = uniqueCandidates(candidates);
        List<String> titles = new ArrayList<>();
        for (Candidate candidate : candidates) titles.add(candidate.title);

        if (!candidates.isEmpty()) {
            setStatus("identified", 0.12,
                    candidates.size() == 1 ? "1 new game identified" :
                            candidates.size() + " new games identified",
                    titles, 0, false);
        }

        JSONArray registry = readRegistry();
        Set<String> registeredSources = registeredSources(registry);
        List<ImportedGame> imported = new ArrayList<>();
        boolean localIndexChanged = false;
        Map<File, Integer> archiveTotals = new HashMap<>();
        Map<File, Integer> archiveSuccesses = new HashMap<>();
        for (Candidate candidate : candidates) {
            if (candidate.zipEntry != null)
                archiveTotals.put(candidate.source, archiveTotals.getOrDefault(candidate.source, 0) + 1);
        }
        int index = 0;
        for (Candidate candidate : candidates) {
            index++;
            double base = 0.12 + (0.38 * (index - 1) / Math.max(1, candidates.size()));
            setStatus("transferring", base, "Adding " + candidate.title + "…",
                    titles, imported.size(), false);
            if (registeredSources.contains(candidate.identity)) {
                JSONObject saved = registeredGame(registry, candidate.identity);
                // A previous scan may have been interrupted after the durable
                // registry write but before media enrichment and metadata
                // generation. Resume that exact ROM instead of permanently
                // treating the half-finished row as complete.
                if (mediaPending(saved, mediaRefreshAfter())) {
                    ImportedGame pending = ImportedGame.fromJson(saved);
                    if (pending != null) {
                        enrichBundledMetadata(pending);
                        imported.add(pending);
                    }
                }
                if (candidate.zipEntry != null)
                    archiveSuccesses.put(candidate.source,
                            archiveSuccesses.getOrDefault(candidate.source, 0) + 1);
                continue;
            }
            ImportedGame game = importCandidate(candidate, mediaRoot, cacheRoot);
            if (game != null) {
                // Text metadata is packaged with EmuFusion and becomes visible in
                // Pegasus before any slower media or network work begins.
                enrichBundledMetadata(game);
                imported.add(game);
                registry.put(game.toJson());
                writeJsonAtomic(REGISTRY, registry);
                // Pegasus must never have an empty library merely because a
                // long artwork/video pass is interrupted. Publish the ROM
                // record immediately, then enrich it in place below.
                writeMetadata(registry);
                localIndexChanged = true;
                // Only now that the registry row and metadata are durable is
                // the plain-file Downloads source safe to remove. In-place
                // games are their own source and must never be deleted.
                if (candidate.zipEntry == null && !candidate.inPlace &&
                        !candidate.source.equals(game.rom))
                    candidate.source.delete();
                if (candidate.zipEntry != null)
                    archiveSuccesses.put(candidate.source,
                            archiveSuccesses.getOrDefault(candidate.source, 0) + 1);
            }
        }
        for (Map.Entry<File, Integer> archive : archiveTotals.entrySet()) {
            if (archive.getValue().equals(archiveSuccesses.get(archive.getKey())))
                archive.getKey().delete();
        }

        // Pending rows must resume even when the one-time full filesystem
        // discovery flag is already set. Otherwise an interrupted first scan
        // has no candidates on later launches and can never finish media.
        Set<String> queuedIdentities = new HashSet<>();
        for (ImportedGame game : imported) queuedIdentities.add(game.sourceIdentity);
        for (int rowIndex = 0; rowIndex < registry.length(); rowIndex++) {
            JSONObject row = registry.optJSONObject(rowIndex);
            if (row == null || queuedIdentities.contains(row.optString("sourceIdentity"))) continue;
            ImportedGame pending = ImportedGame.fromJson(row);
            if (pending != null && mediaPending(row, mediaRefreshAfter())) {
                enrichBundledMetadata(pending);
                imported.add(pending);
                queuedIdentities.add(pending.sourceIdentity);
            }
        }

        // Rebuild from the durable registry on every scan. This is the
        // recovery path for versions that could save registry rows without
        // ever regenerating 99-thorium-auto-import.metadata.pegasus.txt.
        localIndexChanged |= writeMetadata(registry);
        if (prerequisiteRoutesChanged) {
            // Also normalize hand-authored/on-disk collections so a newly
            // ready (or no-longer-ready) internal route is applied everywhere.
            LaunchMetadataRouter.normalize(context);
        }

        // The frontend reads metadata into its own model. Publishing files
        // alone does not reveal a newly copied ROM in an already-open menu.
        // Request the guarded Qt refresh BEFORE the optional media queue:
        // that queue can wait indefinitely for network access. Pending media
        // rows alone must not request another restart on every process start.
        if (localIndexChanged || prerequisiteRoutesChanged) {
            Context app = context.getApplicationContext();
            if (app instanceof LucentApplication)
                ((LucentApplication) app).onLibraryIndexChanged();
        }

        if (!imported.isEmpty() && !enrichMediaQueue(imported, registry, cacheRoot, mediaRoot)) return;

        // Keep provenance current for the games processed in this scan. This
        // is a local manifest write; it does not search or download old media.
        writeBackgroundProvenanceManifest(readRegistry(), mediaRoot);

        // Searching every catalog is slow, so it belongs to the user-requested
        // maintenance pass. It only ever builds a list; nothing is removed
        // here, and nothing is removed anywhere until the owner answers.
        int waiting = 0;
        if (fullDiscovery) {
            setStatus("artless", 0.95, "Checking every catalog for missing box art…",
                    titles, imported.size(), false);
            try (LibraryHttp.Scope audit = LibraryHttp.begin(30_000L, 0L, null)) {
                waiting = Math.max(0, reviewArtlessGames(cacheRoot, mediaRoot));
            }

            // Games already in the library never go through the per-game
            // download above (that only runs for newly imported/resumed
            // rows), so the full-discovery maintenance pass is the only
            // opportunity to backfill cheats for the existing library.
            setStatus("cheats-refresh", 0.97, "Refreshing cheats for the library…",
                    titles, imported.size(), false);
            try {
                GameCheatDownloader.refreshLibrary(context, cacheRoot);
            } catch (Throwable failed) {
                Log.w(TAG, "Library cheat refresh unavailable: " + failed);
            }
        }

        String message;
        boolean reload = !imported.isEmpty() || prerequisiteRoutesChanged;
        if (!imported.isEmpty()) {
            int incomplete = 0;
            for (ImportedGame game : imported)
                if (!mediaComplete(registeredGame(registry, game.sourceIdentity))) incomplete++;
            message = imported.size() + " games checked • " + incomplete +
                    " with unavailable media/ratings; retries scheduled";
        } else if (prerequisiteRoutesChanged) {
            message = "Library scan complete • emulator readiness updated";
        } else {
            message = "Library scan complete • no new games";
        }
        if (waiting > 0)
            message += " • " + waiting + (waiting == 1 ? " game has" : " games have") +
                    " no box art • choose what to do in Settings";
        setStatus("complete", 1.0, message, titles, imported.size(), reload);
    }

    private static boolean mediaComplete(JSONObject row) {
        return row != null && readableMedia(row.optString("boxArt")) &&
                readableMedia(row.optString("background")) && readableMedia(row.optString("video")) &&
                (row.optDouble("critic", 0) > 0 || row.optDouble("user", 0) > 0);
    }

    private static boolean readableMedia(String path) {
        File file = new File(path);
        return file.isFile() && file.canRead() && file.length() > 512;
    }

    private static void mergeObject(JSONObject target, JSONObject source) throws Exception {
        java.util.Iterator<String> keys = source.keys();
        while (keys.hasNext()) { String key = keys.next(); target.put(key, source.get(key)); }
    }

    /** Durable, small per-game checkpoints avoid rewriting a huge library per download. */
    private boolean enrichMediaQueue(List<ImportedGame> games, JSONArray registry,
                                     File cacheRoot, File mediaRoot) throws Exception {
        long refresh = mediaRefreshAfter();
        long lastPublished = SystemClock.elapsedRealtime();
        String[] stages = {"Ratings", "Box art", "Wallpaper", "Video", "Cheats"};
        long[] budgets = {30_000L, 40_000L, 60_000L, 150_000L, 30_000L};
        for (int index = 0; index < games.size(); index++) {
            ImportedGame queued = games.get(index);
            JSONObject row = registeredGame(registry, queued.sourceIdentity);
            if (row == null) { row = queued.toJson(); registry.put(row); }
            File checkpoint = new File(cacheRoot, "media-queue/" + sha1(queued.sourceIdentity) + ".json");
            if (checkpoint.isFile()) {
                try {
                    JSONObject saved = new JSONObject(readText(checkpoint));
                    if (saved.optLong("mediaUpdatedAt", 0) > row.optLong("mediaUpdatedAt", 0))
                        mergeObject(row, saved);
                } catch (Exception ignored) {} // A bad checkpoint retries this game, not the library.
            }
            ImportedGame game = ImportedGame.fromJson(row);
            if (game == null) continue;
            if (row.optLong("mediaRefreshEpoch", 0) < refresh ||
                    row.optInt("mediaVersion", 0) >= 1 && mediaPending(row, refresh)) {
                row.put("mediaStage", 0).put("mediaVersion", 0).put("mediaLastError", "");
            }
            row.put("mediaRefreshEpoch", refresh);
            final int current = index + 1;
            for (int stage = row.optInt("mediaStage", 0); stage < stages.length; stage++) {
                if (closed || Thread.currentThread().isInterrupted() || !networkAvailable()) {
                    writeJsonAtomic(REGISTRY, registry);
                    writeMetadata(registry);
                    setDetailedStatus("waiting", index / (double) games.size(),
                            "Downloads paused • waiting for network", "Progress saved; resumes automatically",
                            current, games.size(), Collections.singletonList(game.title), index, false);
                    return false;
                }
                final String title = game.title;
                final String label = stages[stage];
                final double progress = (index + stage / (double) stages.length) / games.size();
                setDetailedStatus("media", progress, current + "/" + games.size() + " • " + title,
                        label, current, games.size(), Collections.singletonList(title), index, false);
                android.os.PowerManager manager = (android.os.PowerManager)
                        context.getSystemService(Context.POWER_SERVICE);
                android.os.PowerManager.WakeLock wake = manager.newWakeLock(
                        android.os.PowerManager.PARTIAL_WAKE_LOCK, "EmuFusion:LibraryDownload");
                wake.acquire(budgets[stage] + 10_000L);
                LibraryHttp.Scope transfer = LibraryHttp.begin(budgets[stage], refresh,
                        (host, bytes, total) -> setDetailedStatus("media", progress,
                                current + "/" + games.size() + " • " + title,
                                label + " • " + host + " • " + bytes / 1024 + " KB" +
                                        (total > 0 ? " / " + total / 1024 + " KB" : ""),
                                current, games.size(), Collections.singletonList(title), current - 1, false));
                try {
                    if (stage == 0) {
                        enrichBundledMetadata(game);
                        if (refresh > 0 || !hasCompleteBundledMetadata(game)) enrichMetacritic(game, cacheRoot);
                        enrichGameRankings(game);
                        enrichMobyGames(game);
                        calculateCriticComposite(game);
                    } else if (stage == 1) enrichBoxArt(game, cacheRoot, mediaRoot);
                    else if (stage == 2) enrichBackground(game, cacheRoot, mediaRoot);
                    else if (stage == 3) enrichVideo(game, cacheRoot, mediaRoot);
                    else game.cheats = GameCheatDownloader.fetch(context, game.system.folder,
                            game.title, game.rom, game.sourceIdentity, cacheRoot,
                            SystemClock.elapsedRealtime() + 15_000L);
                } finally {
                    transfer.close();
                    if (wake.isHeld()) wake.release();
                }
                mergeObject(row, game.toJson());
                row.put("mediaStage", stage + 1).put("mediaUpdatedAt", System.currentTimeMillis());
                if (!transfer.error.isEmpty()) row.put("mediaLastError", transfer.error);
                writeTextAtomic(checkpoint, row.toString(2));
                Log.i(TAG, "Media checkpoint " + current + "/" + games.size() + " " + title +
                        " stage=" + label + " error=" + transfer.error);
            }
            boolean complete = mediaComplete(row);
            row.put("mediaVersion", 1).put("enrichmentVersion", complete ? 2 : 0)
                    .put("mediaRefreshCompletedAt", refresh)
                    .put("mediaUpdatedAt", System.currentTimeMillis())
                    .put("mediaNextRetryAt", complete ? Long.MAX_VALUE : System.currentTimeMillis() +
                            (row.optString("mediaLastError").isEmpty() ? 86_400_000L : 900_000L));
            writeTextAtomic(checkpoint, row.toString(2));
            // Small checkpoint after every stage, full publication periodically
            // and at completion. No quadratic full-library rewrite per asset.
            if (current % 10 == 0 || SystemClock.elapsedRealtime() - lastPublished > 20_000L) {
                writeJsonAtomic(REGISTRY, registry);
                writeMetadata(registry);
                lastPublished = SystemClock.elapsedRealtime();
            }
        }
        writeJsonAtomic(REGISTRY, registry);
        writeMetadata(registry);
        return true;
    }

    private List<Candidate> discoverCandidates(File cacheRoot) throws Exception {
        List<Candidate> found = new ArrayList<>();
        List<File> files = new ArrayList<>();
        for (File downloadRoot : downloadRoots()) {
            Log.i(TAG, "Scanning download root " + downloadRoot.getAbsolutePath());
            File[] entries = downloadRoot.listFiles();
            if (entries != null) Collections.addAll(files, entries);
        }
        files.sort(Comparator.comparing(File::getAbsolutePath, String.CASE_INSENSITIVE_ORDER));
        for (File file : files) {
            if (file.isDirectory()) {
                // aPS3e boots a decrypted title root, but Pegasus needs one
                // concrete launch file. Recognize only the verified standard
                // shape and index its EBOOT.BIN in place; never copy or delete
                // one executable out of the title directory that owns it.
                File eboot = new File(file, "PS3_GAME/USRDIR/EBOOT.BIN");
                File titleRoot = ps3TitleRoot(eboot);
                if (titleRoot != null && canonical(titleRoot.getAbsolutePath())
                        .equals(canonical(file.getAbsolutePath()))) {
                    GameSystems.SystemDef ps3 = GameSystems.byFolder("ps3");
                    found.add(new Candidate(eboot, null, ps3,
                            cleanTitle(titleRoot.getName()),
                            canonical(eboot.getAbsolutePath()) + ":" + eboot.length(), true));
                }
                continue;
            }
            if (!file.isFile() || file.getName().startsWith(".") || isPartial(file.getName())) continue;
            String extension = extension(file.getName());
            if ("zip".equals(extension) || "7z".equals(extension)) {
                if (isSwitchSupplementalName(file.getName())) continue;
                found.addAll("zip".equals(extension) ? inspectZip(file, cacheRoot) :
                        inspectSevenZip(file, cacheRoot));
                continue;
            }
            if (isSwitchExtension(extension) && isSwitchSupplementalName(file.getAbsolutePath()))
                continue;
            GameSystems.SystemDef system = identify(file, extension);
            if (system == null) continue;
            String title = cleanTitle(stem(file.getName()));
            found.add(new Candidate(file, null, system, title,
                    canonical(file.getAbsolutePath()) + ":" + file.length()));
        }
        return found;
    }

    private static List<Candidate> uniqueCandidates(List<Candidate> candidates) {
        LinkedHashMap<String, Candidate> unique = new LinkedHashMap<>();
        for (Candidate candidate : candidates) {
            if (!unique.containsKey(candidate.identity))
                unique.put(candidate.identity, candidate);
        }
        return new ArrayList<>(unique.values());
    }

    private List<Candidate> discoverExistingCandidates() {
        List<Candidate> found = new ArrayList<>();
        Set<String> referenced = existingMetadataPaths();
        Set<String> knownGames = existingMetadataGameIdentities();
        Log.i(TAG, "Full discovery baseline: " + metadataFiles().size() +
                " metadata files, " + referenced.size() + " ROM paths, " +
                knownGames.size() + " system/title identities");
        Set<String> visited = new HashSet<>();
        List<File> roots = libraryRoots();
        roots.addAll(downloadRoots());
        int[] inspected = new int[]{0};
        for (File root : roots)
            scanLibraryRoot(root, 0, found, referenced, knownGames, visited, inspected);
        return found;
    }

    private void scanLibraryRoot(File directory, int depth, List<Candidate> found,
                                 Set<String> referenced, Set<String> knownGames,
                                 Set<String> visited, int[] inspected) {
        if (directory == null || depth > 12 || inspected[0] > 250000) return;
        String canonical = canonical(directory.getAbsolutePath());
        if (shouldSkipLibraryDirectory(directory) && depth > 0) return;
        if (!visited.add(canonical)) return;
        File[] entries = directory.listFiles();
        if (entries == null) return;
        Arrays.sort(entries, Comparator.comparing(File::getName, String.CASE_INSENSITIVE_ORDER));
        for (File entry : entries) {
            if (inspected[0]++ > 250000) return;
            if (entry.isDirectory()) {
                scanLibraryRoot(entry, depth + 1, found, referenced, knownGames, visited, inspected);
                continue;
            }
            if (!entry.isFile() || entry.getName().startsWith(".") || isPartial(entry.getName()))
                continue;
            String path = canonical(entry.getAbsolutePath());
            if (referenced.contains(path)) continue;
            String ext = extension(entry.getName());
            if (isSwitchExtension(ext) && isSwitchSupplementalName(entry.getAbsolutePath()))
                continue;
            File ps3Root = ps3TitleRoot(entry);
            GameSystems.SystemDef system = ps3Root == null ? null :
                    GameSystems.byFolder("ps3");
            if (system == null) system = identify(entry, ext);
            if (system == null) system = GameSystems.unambiguousByExtension(ext);
            if (system == null) continue;
            String title = cleanTitle(ps3Root == null
                    ? stem(entry.getName()) : ps3Root.getName());
            // Storage migrations and backups frequently change an absolute
            // path without changing the actual game. Pegasus already owns the
            // canonical system/title identity, so do not generate a second
            // entry merely because another copy exists somewhere else.
            Set<String> candidateIdentities = new HashSet<>();
            addGameIdentities(candidateIdentities, system.folder, title);
            addGameIdentities(candidateIdentities, system.folder, stem(entry.getName()));
            File parent = entry.getParentFile();
            if (parent != null && !GameSystems.isKnownSystemDirectory(parent))
                addGameIdentities(candidateIdentities, system.folder, parent.getName());
            if (!Collections.disjoint(knownGames, candidateIdentities)) continue;
            knownGames.addAll(candidateIdentities);
            found.add(new Candidate(entry, null, system, title,
                    path + ":" + entry.length(), true));
        }
    }

    /** Returns the decrypted title root for the one executable aPS3e can boot. */
    private static File ps3TitleRoot(File file) {
        if (file == null || !file.isFile() ||
                !"EBOOT.BIN".equalsIgnoreCase(file.getName())) return null;
        File usrdir = file.getParentFile();
        File ps3Game = usrdir == null ? null : usrdir.getParentFile();
        File titleRoot = ps3Game == null ? null : ps3Game.getParentFile();
        if (usrdir == null || ps3Game == null || titleRoot == null ||
                !"USRDIR".equalsIgnoreCase(usrdir.getName()) ||
                !"PS3_GAME".equalsIgnoreCase(ps3Game.getName()) ||
                !new File(ps3Game, "PARAM.SFO").isFile()) return null;
        return titleRoot;
    }

    private List<File> libraryRoots() {
        LinkedHashMap<String, File> roots = new LinkedHashMap<>();
        List<File> volumes = new ArrayList<>();
        volumes.add(Environment.getExternalStorageDirectory());
        // Some Android builds prohibit listing /storage itself. Public volume
        // directories remain discoverable through the platform storage API.
        if (android.os.Build.VERSION.SDK_INT >= 30) {
            android.os.storage.StorageManager manager =
                    context.getSystemService(android.os.storage.StorageManager.class);
            if (manager != null) for (android.os.storage.StorageVolume volume : manager.getStorageVolumes()) {
                File directory = volume.getDirectory();
                if (directory != null) volumes.add(directory);
            }
        }
        File[] storage = new File("/storage").listFiles();
        if (storage != null) {
            for (File candidate : storage) {
                String name = candidate.getName();
                if (candidate.isDirectory() && !"emulated".equals(name) && !"self".equals(name))
                    volumes.add(candidate);
            }
        }
        for (File volume : volumes) {
            // First-run discovery must not depend on user folder naming. Scan
            // each readable storage volume itself; the recursive scanner only
            // accepts verified ROM formats and skips Android/app/media trees.
            if (volume.isDirectory() && volume.canRead() && volume.listFiles() != null) {
                roots.put(canonical(volume.getAbsolutePath()), volume);
                // Walk real directory entries once. On Android's case-folded
                // storage ROMs/Roms/roms can all resolve to the SAME folder,
                // despite File.getCanonicalPath retaining each spelling.
                continue;
            }
            for (String common : new String[]{"Games", "games", "ROMs", "Roms", "roms",
                    "Emulation", "emulation", "RetroArch", "retropie", "recalbox", "batocera"}) {
                File root = new File(volume, common);
                if (root.isDirectory() && root.canRead()) roots.put(canonical(root.getAbsolutePath()), root);
            }
            File[] children = volume.listFiles();
            if (children != null) {
                for (File child : children) {
                    if (child.isDirectory() && child.canRead() && GameSystems.isKnownSystemDirectory(child))
                        roots.put(canonical(child.getAbsolutePath()), child);
                }
            }
        }
        return new ArrayList<>(roots.values());
    }

    private static boolean shouldSkipLibraryDirectory(File directory) {
        String name = directory.getName().toLowerCase(Locale.US);
        return name.startsWith(".") || name.contains("backup") || name.contains("quarantine") ||
                name.contains("trash") ||
                "saves".equals(name) || "save".equals(name) ||
                "update".equals(name) || "updates".equals(name) ||
                "dlc".equals(name) || "add-on".equals(name) || "add-ons".equals(name) ||
                "android".equals(name) || "download".equals(name) ||
                "downloads".equals(name) || "pegasusmedia".equals(name) ||
                "pegasus-frontend".equals(name) || "dcim".equals(name) ||
                "pictures".equals(name) || "movies".equals(name) || "music".equals(name) ||
                "alarms".equals(name) || "audiobooks".equals(name) ||
                "notifications".equals(name) || "podcasts".equals(name) ||
                "recordings".equals(name) || "ringtones".equals(name) ||
                "pegasusbackups".equals(name) || "pegasusquarantine".equals(name) ||
                "thorbackups".equals(name) || "dolphinforhandheld".equals(name) ||
                "retroarch".equals(name) || "winlator".equals(name) ||
                "citra-emu".equals(name) || "azahar".equals(name);
    }

    private static Set<String> existingMetadataPaths() {
        Set<String> paths = new HashSet<>();
        for (File file : metadataFiles()) {
            try {
                for (String stanza : splitStanzas(readText(file))) {
                    String path = field(stanza, "file");
                    if (!path.isEmpty()) {
                        File rom = readableMetadataRom(file, path);
                        if (rom.isFile() && rom.canRead()) paths.add(canonical(rom.getAbsolutePath()));
                    }
                }
            } catch (Exception ignored) {}
        }
        return paths;
    }

    private static Set<String> existingMetadataGameIdentities() {
        Set<String> identities = new HashSet<>();
        for (File file : metadataFiles()) {
            try {
                for (String stanza : splitStanzas(readText(file))) {
                    String title = field(stanza, "game");
                    String path = field(stanza, "file");
                    if (title.isEmpty() || path.isEmpty()) continue;
                    File readable = readableMetadataRom(file, path);
                    if (!readable.isFile() || !readable.canRead()) continue;
                    path = readable.getAbsolutePath();
                    GameSystems.SystemDef system = systemFromRomPath(path);
                    if (system != null) {
                        addGameIdentities(identities, system.folder, title);
                        File rom = new File(path);
                        addGameIdentities(identities, system.folder, stem(rom.getName()));
                        File parent = rom.getParentFile();
                        if (parent != null && !GameSystems.isKnownSystemDirectory(parent))
                            addGameIdentities(identities, system.folder, parent.getName());
                    }
                }
            } catch (Exception ignored) {}
        }
        return identities;
    }

    private static void addGameIdentities(Set<String> identities, String folder, String value) {
        String normalized = normalize(value);
        if (normalized.isEmpty()) return;
        identities.add(folder + "|" + normalized);
        String alias = scoreAlias(normalized);
        if (!alias.isEmpty()) identities.add(folder + "|" + alias);
    }

    private static List<File> metadataFiles() {
        LinkedHashMap<String, File> files = new LinkedHashMap<>();
        // Pegasus loads the first three; the native library index also reads
        // the `metadata` directories. A pass that edited only one side would
        // leave the frontend and the index disagreeing about what exists.
        List<File> roots = Arrays.asList(PEGASUS,
                new File(PEGASUS_CONFIG, "metafiles"),
                new File(LUCENT_CONFIG, "metafiles"),
                new File(PEGASUS_CONFIG, "metadata"),
                new File(LUCENT_CONFIG, "metadata"));
        for (File root : roots) {
            File[] metadata = root.listFiles((dir, name) ->
                    name.endsWith(".metadata.pegasus.txt") ||
                            name.equals("metadata.pegasus.txt"));
            if (metadata == null) continue;
            for (File file : metadata)
                files.put(canonical(file.getAbsolutePath()), file);
        }
        return new ArrayList<>(files.values());
    }

    private List<Candidate> inspectZip(File archive, File cacheRoot) {
        List<Candidate> found = new ArrayList<>();
        File staging = new File(cacheRoot, "zip-inspect");
        staging.mkdirs();
        try (ZipFile zip = new ZipFile(archive)) {
            zip.stream().filter(entry -> !entry.isDirectory()).forEach(entry -> {
                String ext = extension(entry.getName());
                if (isSwitchExtension(ext) && (isSwitchSupplementalName(archive.getName()) ||
                        isSwitchSupplementalName(entry.getName()))) return;
                if (GameSystems.unambiguousByExtension(ext) == null &&
                        !isPotentialAmbiguous(ext)) return;
                File temporary = new File(staging, sha1(archive.getAbsolutePath() + "!" + entry.getName()) +
                        "." + ext);
                try {
                    extract(zip, entry, temporary, ARCHIVE_INSPECTION_BYTES);
                    GameSystems.SystemDef system = identify(temporary, ext);
                    if (system != null) {
                        String title = cleanTitle(stem(new File(entry.getName()).getName()));
                        found.add(new Candidate(archive, entry.getName(), system, title,
                                canonical(archive.getAbsolutePath()) + "!" + entry.getName() +
                                        ":" + entry.getCrc()));
                    }
                } catch (Exception ignored) {
                    // Malformed and encrypted archives are ignored without touching Downloads.
                } finally {
                    temporary.delete();
                }
            });
        } catch (Exception ignored) {
        }
        return found;
    }

    /** Inspect every plausible payload in a 7z archive rather than trusting
     * the archive filename. This mirrors ZIP handling: EmuFusion only accepts an
     * entry after its extracted bytes validate as a ROM for a known system. */
    private List<Candidate> inspectSevenZip(File archive, File cacheRoot) {
        List<Candidate> found = new ArrayList<>();
        File staging = new File(cacheRoot, "7z-inspect");
        staging.mkdirs();
        try (SevenZFile sevenZ = new SevenZFile(archive, SEVEN_Z_OPTIONS)) {
            SevenZArchiveEntry entry;
            while ((entry = sevenZ.getNextEntry()) != null) {
                if (entry.isDirectory() || !entry.hasStream() || entry.getSize() <= 0 ||
                        entry.getSize() > MAX_ARCHIVE_ENTRY_BYTES) continue;
                String ext = extension(entry.getName());
                if (isSwitchExtension(ext) && (isSwitchSupplementalName(archive.getName()) ||
                        isSwitchSupplementalName(entry.getName()))) continue;
                if (GameSystems.unambiguousByExtension(ext) == null &&
                        !isPotentialAmbiguous(ext)) continue;
                File temporary = new File(staging,
                        sha1(archive.getAbsolutePath() + "!" + entry.getName()) + "." + ext);
                try {
                    extract(sevenZ, entry, temporary, ARCHIVE_INSPECTION_BYTES);
                    GameSystems.SystemDef system = identify(temporary, ext);
                    if (system != null) {
                        String title = cleanTitle(stem(new File(entry.getName()).getName()));
                        long signature = entry.getHasCrc() ? entry.getCrcValue() : entry.getSize();
                        found.add(new Candidate(archive, entry.getName(), system, title,
                                canonical(archive.getAbsolutePath()) + "!" + entry.getName() +
                                        ":" + signature));
                    }
                } catch (Exception ignored) {
                    // Malformed, unsupported, and encrypted archives remain untouched.
                } finally {
                    temporary.delete();
                }
            }
        } catch (Exception error) {
            Log.w(TAG, "Unable to inspect 7z archive " + archive.getAbsolutePath(), error);
        }
        return found;
    }

    private ImportedGame importCandidate(Candidate candidate, File mediaRoot, File cacheRoot)
            throws Exception {
        String extension = candidate.zipEntry == null ? extension(candidate.source.getName()) :
                extension(candidate.zipEntry);
        String canonicalTitle = canonicalTitle(candidate.system, candidate.title, cacheRoot);
        if (!canonicalTitle.isEmpty()) candidate.title = canonicalTitle;
        if (candidate.inPlace) return new ImportedGame(candidate, candidate.source);
        File systemFolder = new File(GAMES, candidate.system.folder);
        systemFolder.mkdirs();
        File target = new File(systemFolder, safeFilename(candidate.title) + "." + extension);

        if (target.isFile()) {
            if (candidate.zipEntry == null && sameContent(candidate.source, target)) {
                // The verified payload already lives in the library, but its
                // registry row may be missing (interrupted earlier scan, lost
                // registry). Republish the row; the caller deletes the
                // duplicate Downloads source only after that row and its
                // metadata have committed.
                return new ImportedGame(candidate, target);
            }
            // Crash-safe archive recovery: Android may stop the service in
            // the tiny interval after the verified payload is renamed but
            // before its registry row is committed. On the next scan, accept
            // that target only when its full size and CRC exactly match the
            // same ZIP/7z member, then publish metadata before deleting the
            // source archive. A title match alone is never sufficient.
            if (candidate.zipEntry != null && archiveEntryMatchesTarget(candidate, target))
                return new ImportedGame(candidate, target);
            // Never overwrite an existing game or silently rename a different payload.
            return null;
        }

        File partial = new File(systemFolder, "." + target.getName() + ".importing");
        if (candidate.zipEntry == null) {
            copy(candidate.source, partial);
        } else if ("7z".equals(extension(candidate.source.getName()))) {
            extractSevenZipEntry(candidate.source, candidate.zipEntry, partial);
        } else {
            try (ZipFile zip = new ZipFile(candidate.source)) {
                ZipEntry entry = zip.getEntry(candidate.zipEntry);
                if (entry == null) return null;
                extract(zip, entry, partial);
            }
        }
        GameSystems.SystemDef verified = identify(partial, extension);
        if (verified == null || !verified.folder.equals(candidate.system.folder)) {
            partial.delete();
            return null;
        }
        if (!partial.renameTo(target)) {
            partial.delete();
            return null;
        }
        // The Downloads source is deleted by the caller only after this ROM's
        // registry row and metadata have committed, mirroring the archive
        // sweep. Deleting here would lose the game if the service dies before
        // the commit: the source would be gone and no row would exist.
        return new ImportedGame(candidate, target);
    }

    private static boolean archiveEntryMatchesTarget(Candidate candidate, File target) {
        if (candidate == null || candidate.zipEntry == null || target == null || !target.isFile())
            return false;
        try {
            long expectedSize = -1L;
            long expectedCrc = -1L;
            if ("7z".equals(extension(candidate.source.getName()))) {
                try (SevenZFile sevenZ = new SevenZFile(candidate.source, SEVEN_Z_OPTIONS)) {
                    SevenZArchiveEntry entry;
                    while ((entry = sevenZ.getNextEntry()) != null) {
                        if (candidate.zipEntry.equals(entry.getName())) {
                            expectedSize = entry.getSize();
                            if (entry.getHasCrc()) expectedCrc = entry.getCrcValue();
                            break;
                        }
                    }
                }
            } else {
                try (ZipFile zip = new ZipFile(candidate.source)) {
                    ZipEntry entry = zip.getEntry(candidate.zipEntry);
                    if (entry != null) {
                        expectedSize = entry.getSize();
                        expectedCrc = entry.getCrc();
                    }
                }
            }
            if (expectedSize < 0 || expectedSize != target.length() || expectedCrc < 0)
                return false;
            CRC32 crc = new CRC32();
            try (InputStream input = new BufferedInputStream(new FileInputStream(target))) {
                byte[] buffer = new byte[1024 * 1024];
                int count;
                while ((count = input.read(buffer)) >= 0) crc.update(buffer, 0, count);
            }
            return crc.getValue() == expectedCrc;
        } catch (Exception error) {
            Log.w(TAG, "Unable to verify staged archive recovery for " + target, error);
            return false;
        }
    }

    private void enrichBoxArt(ImportedGame game, File cacheRoot, File mediaRoot) {
        try {
            CatalogMatch match = null;
            NintendoMedia official = nintendoMedia(game.system, game.title, cacheRoot);
            if (official != null && !official.cover.isEmpty())
                match = new CatalogMatch(official.cover, game.title);
            if (match == null) match = boxArtMatch(game.system, game.title, cacheRoot);
            if (match == null) return;
            File folder = new File(mediaRoot, "boxfront/" + game.system.folder);
            folder.mkdirs();
            String ext = extension(match.url);
            File target = new File(folder, sha1(game.rom.getAbsolutePath()) + "." +
                    (ext.isEmpty() ? "png" : ext));
            if (download(match.url, target, 64L * 1024L * 1024L)) game.boxArt = target.getAbsolutePath();
        } catch (Exception error) {
            Log.w(TAG, "Box art unavailable for " + game.title, error);
        }
    }

    private void enrichBackground(ImportedGame game, File cacheRoot, File mediaRoot) {
        resolveBackground(game, cacheRoot, mediaRoot);
        // Derive the accent here, while the importer already owns the file, so
        // the theme can select a game with zero image work. An empty value is
        // durable state too: it records "evaluated, no usable hue" and lets the
        // theme fall back to the system accent without ever retrying.
        game.accentSource = accentSourceKey(game.background);
        game.accent = wallpaperAccent(game.background);
    }

    /**
     * Identity of the wallpaper an accent was derived from. Including size and
     * modified time means a wallpaper replaced at the same path re-derives,
     * while an untouched library never decodes anything twice.
     */
    private static String accentSourceKey(String wallpaperPath) {
        if (wallpaperPath == null || wallpaperPath.isEmpty()) return "";
        File wallpaper = new File(wallpaperPath);
        if (!wallpaper.isFile()) return wallpaperPath;
        return wallpaperPath + ':' + wallpaper.length() + ':' + wallpaper.lastModified();
    }

    /**
     * Deterministic complementary accent for one wallpaper file, or an empty
     * string when the image is missing, unreadable, or carries no usable hue.
     */
    private static String wallpaperAccent(String wallpaperPath) {
        if (wallpaperPath == null || wallpaperPath.isEmpty()) return "";
        File wallpaper = new File(wallpaperPath);
        if (!wallpaper.isFile() || wallpaper.length() <= 512) return "";
        Bitmap sample = null;
        try {
            BitmapFactory.Options bounds = new BitmapFactory.Options();
            bounds.inJustDecodeBounds = true;
            BitmapFactory.decodeFile(wallpaper.getAbsolutePath(), bounds);
            if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return "";
            // Power-of-two subsampling is exact and identical on every decoder
            // version, so a rescan cannot produce a different accent for an
            // unchanged file. WallpaperAccent strides the rest of the way down.
            BitmapFactory.Options options = new BitmapFactory.Options();
            options.inPreferredConfig = Bitmap.Config.ARGB_8888;
            options.inSampleSize = 1;
            int longest = Math.max(bounds.outWidth, bounds.outHeight);
            while (longest / (options.inSampleSize * 2) >= WallpaperAccent.SAMPLE_EDGE)
                options.inSampleSize *= 2;
            sample = BitmapFactory.decodeFile(wallpaper.getAbsolutePath(), options);
            if (sample == null) return "";
            int width = sample.getWidth();
            int height = sample.getHeight();
            if (width <= 0 || height <= 0) return "";
            int[] pixels = new int[width * height];
            sample.getPixels(pixels, 0, width, 0, 0, width, height);
            String accent = WallpaperAccent.fromPixels(pixels, width, height);
            return accent == null ? "" : accent;
        } catch (Throwable error) {
            Log.w(TAG, "Unable to derive a wallpaper accent for " + wallpaperPath, error);
            return "";
        } finally {
            if (sample != null) sample.recycle();
        }
    }

    private void resolveBackground(ImportedGame game, File cacheRoot, File mediaRoot) {
        try {
            File pipelineFolder = new File(mediaRoot, "game-wallpapers/" + game.system.folder);
            String digestPrefix = sha1(game.rom.getAbsolutePath());
            File pipeline = new File(pipelineFolder, digestPrefix + ".jpg");
            if (!pipeline.isFile()) {
                File[] longerDigest = pipelineFolder.listFiles((directory, name) ->
                        name.startsWith(digestPrefix) && name.toLowerCase(Locale.US).endsWith(".jpg"));
                if (longerDigest != null && longerDigest.length == 1) pipeline = longerDigest[0];
            }
            if (LibraryHttp.reusable(pipeline) && wallpaperCanvasIsValid(pipeline)) {
                game.background = pipeline.getAbsolutePath();
                if (game.backgroundSource.isEmpty())
                    game.backgroundSource = BACKGROUND_SOURCE_WALLPAPER;
                return;
            }

            // LaunchBox exposes exact per-game Fanart - Background assets. The
            // result page is matched by both normalized title and platform;
            // only the dedicated fanart class is accepted (never box fronts,
            // banners, or a fuzzy title result).
            CatalogMatch launchBox = null;
            try { launchBox = launchBoxFanartMatch(game.system, game.title, cacheRoot); }
            catch (Exception unavailable) { Log.w(TAG, "Fanart source unavailable; trying fallback"); }
            if (launchBox != null) {
                File folder = new File(mediaRoot,
                        "game-wallpapers-launchbox-fanart/" + game.system.folder);
                File target = new File(folder, sha1(game.rom.getAbsolutePath()) + ".jpg");
                if (acceptWallpaper(downloadAndCrop16x9(launchBox.url, target, cacheRoot,
                        64L * 1024L * 1024L), target)) {
                    game.background = target.getAbsolutePath();
                    game.backgroundSource = BACKGROUND_SOURCE_LAUNCHBOX;
                    game.backgroundSourceUrl = launchBox.url;
                    game.backgroundTransform = BACKGROUND_TRANSFORM;
                    return;
                }
            }

            // Prefer an exact, first-party gallery image before falling back
            // to gameplay. The Nintendo adapter validates the product title
            // and NSUID, so cross-title artwork can never leak into a game.
            NintendoMedia official = nintendoMedia(game.system, game.title, cacheRoot);
            if (official != null && !official.background.isEmpty()) {
                File folder = new File(mediaRoot,
                        "game-wallpapers-official-gallery/" + game.system.folder);
                File target = new File(folder, sha1(game.rom.getAbsolutePath()) + ".jpg");
                if (acceptWallpaper(downloadAndCrop16x9(official.background, target, cacheRoot,
                        64L * 1024L * 1024L), target)) {
                    game.background = target.getAbsolutePath();
                    game.backgroundSource = BACKGROUND_SOURCE_OFFICIAL;
                    game.backgroundSourceUrl = official.background;
                    game.backgroundTransform = BACKGROUND_TRANSFORM;
                    return;
                }
            }

            // Last resort: an exact-title libretro gameplay snap. It is kept
            // in a dedicated tree and tagged in both registry and Pegasus
            // metadata, so it can always be audited or replaced separately
            // from real wallpaper. catalogMatch rejects fuzzy/cross-platform
            // matches and chooses region variants deterministically.
            CatalogMatch screenshot = catalogMatch(game.system, game.title, cacheRoot,
                    "Named_Snaps");
            if (screenshot != null) {
                File folder = new File(mediaRoot,
                        "game-wallpapers-screenshot-fallback/" + game.system.folder);
                File target = new File(folder, sha1(game.rom.getAbsolutePath()) + ".jpg");
                if (acceptWallpaper(downloadAndCrop16x9(screenshot.url, target, cacheRoot,
                        64L * 1024L * 1024L), target)) {
                    game.background = target.getAbsolutePath();
                    game.backgroundSource = BACKGROUND_SOURCE_SCREENSHOT;
                    game.backgroundSourceUrl = screenshot.url;
                    game.backgroundTransform = BACKGROUND_TRANSFORM;
                    return;
                }
            }

            // An empty field is intentional: the theme shows a neutral system
            // backdrop rather than retaining the previous game's wallpaper.
            if (!readableMedia(game.background)) {
                game.background = "";
                game.backgroundSource = "";
                game.backgroundSourceUrl = "";
                game.backgroundTransform = "";
            }
            return;
        } catch (Exception error) {
            Log.w(TAG, "Wallpaper unavailable for " + game.title, error);
        }
    }

    private static boolean acceptWallpaper(boolean downloaded, File target) {
        if (!downloaded) return false;
        if (wallpaperCanvasIsValid(target)) return true;
        // Never let a dimensionally correct but visually padded canvas become
        // durable state. Leaving it in place would make every later scan
        // detect and "repair" the same file again.
        if (target.isFile() && !target.delete())
            Log.w(TAG, "Unable to remove rejected wallpaper " + target);
        return false;
    }

    private static boolean downloadAndCrop16x9(String url, File target, File cacheRoot,
                                                long maxBytes) throws Exception {
        if (LibraryHttp.reusable(target) && isExact1080p(target)) return true;
        File source = new File(cacheRoot, "background-sources/" + sha1(url) + ".image");
        if (!download(url, source, maxBytes)) return false;

        BitmapFactory.Options bounds = new BitmapFactory.Options();
        bounds.inJustDecodeBounds = true;
        BitmapFactory.decodeFile(source.getAbsolutePath(), bounds);
        if (bounds.outWidth < 1 || bounds.outHeight < 1) return false;

        BitmapFactory.Options decode = new BitmapFactory.Options();
        decode.inPreferredConfig = Bitmap.Config.ARGB_8888;
        int sample = 1;
        while (bounds.outWidth / (sample * 2) >= 1920 &&
                bounds.outHeight / (sample * 2) >= 1080) sample *= 2;
        decode.inSampleSize = sample;
        Bitmap input = BitmapFactory.decodeFile(source.getAbsolutePath(), decode);
        if (input == null) return false;

        Bitmap output = null;
        File part = new File(target.getAbsolutePath() + ".part");
        try {
            output = Bitmap.createBitmap(1920, 1080, Bitmap.Config.ARGB_8888);
            Canvas canvas = new Canvas(output);
            float scale = Math.max(1920f / input.getWidth(), 1080f / input.getHeight());
            float width = input.getWidth() * scale;
            float height = input.getHeight() * scale;
            RectF destination = new RectF((1920f - width) / 2f, (1080f - height) / 2f,
                    (1920f + width) / 2f, (1080f + height) / 2f);
            Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG | Paint.FILTER_BITMAP_FLAG |
                    Paint.DITHER_FLAG);
            canvas.drawBitmap(input, null, destination, paint);
            target.getParentFile().mkdirs();
            try (FileOutputStream stream = new FileOutputStream(part)) {
                if (!output.compress(Bitmap.CompressFormat.JPEG, 92, stream)) return false;
                stream.getFD().sync();
            }
            if (!wallpaperCanvasIsValid(part)) return false;
            java.nio.file.Files.move(part.toPath(), target.toPath(),
                    java.nio.file.StandardCopyOption.REPLACE_EXISTING);
            return isExact1080p(target);
        } finally {
            if (output != null) output.recycle();
            input.recycle();
            if (part.exists() && !target.equals(part)) part.delete();
        }
    }

    private static boolean isExact1080p(File file) {
        if (file == null || !file.isFile() || file.length() <= 512) return false;
        BitmapFactory.Options bounds = new BitmapFactory.Options();
        bounds.inJustDecodeBounds = true;
        BitmapFactory.decodeFile(file.getAbsolutePath(), bounds);
        return bounds.outWidth == 1920 && bounds.outHeight == 1080;
    }

    /**
     * Reject a common false-positive: a 16:9 file that merely embeds narrower
     * cover/key art between blurred or flat padding bands. Dimensions alone
     * cannot distinguish it from a real wallpaper. This deliberately analyzes
     * a tiny sampled bitmap and memoizes by path/size/mtime so library audits do
     * not turn navigation into image-decoding work.
     */
    private static boolean wallpaperCanvasIsValid(File file) {
        if (!isExact1080p(file)) return false;
        loadWallpaperQualityCache();
        String cacheKey = file.getAbsolutePath() + ':' + file.length() + ':' + file.lastModified();
        Boolean cached = WALLPAPER_QUALITY_CACHE.get(cacheKey);
        if (cached != null) return cached;

        Bitmap sample = null;
        boolean valid = true;
        try {
            BitmapFactory.Options options = new BitmapFactory.Options();
            options.inPreferredConfig = Bitmap.Config.RGB_565;
            options.inSampleSize = 16;
            sample = BitmapFactory.decodeFile(file.getAbsolutePath(), options);
            if (sample == null || sample.getWidth() < 80 || sample.getHeight() < 45) {
                valid = false;
            } else {
                int width = sample.getWidth();
                int height = sample.getHeight();
                float[] rowDetail = new float[height];
                float[] rowSeam = new float[Math.max(1, height - 1)];
                int[] row = new int[width];
                int[] previousLuma = new int[width];
                for (int y = 0; y < height; y++) {
                    sample.getPixels(row, 0, width, 0, y, width, 1);
                    long activity = 0L;
                    long verticalActivity = 0L;
                    for (int x = 1; x < width; x++) {
                        int left = row[x - 1];
                        int right = row[x];
                        int leftLuma = (77 * ((left >> 16) & 255) +
                                150 * ((left >> 8) & 255) + 29 * (left & 255)) >> 8;
                        int rightLuma = (77 * ((right >> 16) & 255) +
                                150 * ((right >> 8) & 255) + 29 * (right & 255)) >> 8;
                        activity += Math.abs(rightLuma - leftLuma);
                        if (y > 0) verticalActivity += Math.abs(rightLuma - previousLuma[x]);
                        previousLuma[x] = rightLuma;
                    }
                    if (width > 0) {
                        int first = row[0];
                        int firstLuma = (77 * ((first >> 16) & 255) +
                                150 * ((first >> 8) & 255) + 29 * (first & 255)) >> 8;
                        if (y > 0) verticalActivity += Math.abs(firstLuma - previousLuma[0]);
                        previousLuma[0] = firstLuma;
                    }
                    rowDetail[y] = activity / (float) Math.max(1, width - 1);
                    if (y > 0) rowSeam[y - 1] = verticalActivity / (float) Math.max(1, width);
                }
                float top = mean(rowDetail, 0.04f, 0.22f);
                float center = mean(rowDetail, 0.36f, 0.64f);
                float bottom = mean(rowDetail, 0.78f, 0.96f);
                float paddingRatio = (top + bottom) / (2f * Math.max(0.01f, center));
                int topSeam = maxIndex(rowSeam, 0.12f, 0.42f);
                int bottomSeam = maxIndex(rowSeam, 0.58f, 0.88f);
                float seamMean = mean(rowSeam, 0f, 1f);
                float seamStrength = (rowSeam[topSeam] + rowSeam[bottomSeam]) /
                        (2f * Math.max(0.01f, seamMean));
                int symmetry = Math.abs((topSeam + bottomSeam) - (rowSeam.length - 1));
                boolean extremelyFlatOuterBands = center > 4.5f && paddingRatio < 0.20f;
                boolean pairedPaddingSeams = paddingRatio < 0.55f &&
                        seamStrength > 4.0f && symmetry < Math.max(3, height * 0.08f);
                valid = !(extremelyFlatOuterBands || pairedPaddingSeams);
            }
        } catch (Exception error) {
            Log.w(TAG, "Wallpaper canvas audit failed for " + file, error);
            valid = false;
        } finally {
            if (sample != null) sample.recycle();
        }
        WALLPAPER_QUALITY_CACHE.put(cacheKey, valid);
        return valid;
    }

    private static synchronized void loadWallpaperQualityCache() {
        if (wallpaperQualityCacheLoaded) return;
        wallpaperQualityCacheLoaded = true;
        File cache = new File(new File(PEGASUS, ".thorium-import-cache"),
                "wallpaper-quality.json");
        if (!cache.isFile()) return;
        try {
            JSONObject saved = new JSONObject(readText(cache));
            java.util.Iterator<String> keys = saved.keys();
            while (keys.hasNext()) {
                String key = keys.next();
                WALLPAPER_QUALITY_CACHE.put(key, saved.optBoolean(key, false));
            }
        } catch (Exception error) {
            Log.w(TAG, "Unable to read wallpaper quality cache", error);
        }
    }

    private static void persistWallpaperQualityCache(File cacheRoot) {
        try {
            JSONObject saved = new JSONObject();
            for (Map.Entry<String, Boolean> entry : WALLPAPER_QUALITY_CACHE.entrySet())
                saved.put(entry.getKey(), entry.getValue());
            writeTextAtomic(new File(cacheRoot, "wallpaper-quality.json"),
                    saved.toString(2) + "\n");
        } catch (Exception error) {
            Log.w(TAG, "Unable to persist wallpaper quality cache", error);
        }
    }

    private static float mean(float[] values, float from, float to) {
        int start = Math.max(0, Math.min(values.length - 1,
                Math.round((values.length - 1) * from)));
        int end = Math.max(start + 1, Math.min(values.length,
                Math.round(values.length * to)));
        float sum = 0f;
        for (int i = start; i < end; i++) sum += values[i];
        return sum / Math.max(1, end - start);
    }

    private static int maxIndex(float[] values, float from, float to) {
        int start = Math.max(0, Math.min(values.length - 1,
                Math.round((values.length - 1) * from)));
        int end = Math.max(start + 1, Math.min(values.length,
                Math.round(values.length * to)));
        int result = start;
        for (int i = start + 1; i < end; i++)
            if (values[i] > values[result]) result = i;
        return result;
    }

    private void enrichVideo(ImportedGame game, File cacheRoot, File mediaRoot) {
        try {
            File existing = existingVideo(mediaRoot, game.system, game.title);
            if (existing != null && LibraryHttp.reusable(existing)) {
                game.video = existing.getAbsolutePath();
                return;
            }
            VideoMatch match = null;
            NintendoMedia official = nintendoMedia(game.system, game.title, cacheRoot);
            if (official != null && !official.video.isEmpty())
                match = new VideoMatch(official.video);
            if (match == null && !game.system.videoArchive.isEmpty()) {
                try { match = videoMatch(game.system, game.title, cacheRoot); }
                catch (Exception unavailable) { Log.w(TAG, "Video catalog unavailable; trying fallback"); }
            }
            if (match == null)
                match = archiveSearchVideo(game.system, game.title, cacheRoot);
            if (match == null) return;
            File folder = new File(mediaRoot, "internet-archive/" + game.system.folder + "/videos");
            folder.mkdirs();
            File target = new File(folder, safeFilename(game.title) + ".mp4");
            if (download(match.url, target, 192L * 1024L * 1024L)) game.video = target.getAbsolutePath();
        } catch (Exception error) {
            Log.w(TAG, "Video unavailable for " + game.title, error);
        }
    }

    private static File existingVideo(File mediaRoot, GameSystems.SystemDef system, String title) {
        String key = normalize(title);
        File[] folders = new File[]{
                new File(mediaRoot, "upscaled-1080p/" + system.folder + "/videos"),
                new File(mediaRoot, "screenscraper/" + system.folder + "/videos"),
                new File(mediaRoot, "internet-archive/" + system.folder + "/videos")
        };
        for (File folder : folders) {
            File[] files = folder.listFiles((dir, name) -> name.toLowerCase(Locale.US).endsWith(".mp4"));
            if (files == null) continue;
            for (File file : files)
                if (normalize(stem(file.getName())).equals(key) && file.length() > 512) return file;
        }
        return null;
    }

    private void enrichBundledMetadata(ImportedGame game) {
        BundledGameRecord record = bundledGameRecord(game.system.folder, game.title);
        if (record == null) return;
        if (record.critic > 0) game.critic = (int)Math.round(record.critic * 10.0);
        if (record.user > 0) game.user = record.user;
        if (!record.release.isEmpty()) game.release = record.release;
        addUnique(game.developers, record.developer);
        addUnique(game.publishers, record.publisher);
        if (!record.criticSources.isEmpty()) game.criticSources = record.criticSources;
        if (!record.userSources.isEmpty()) game.userSources = record.userSources;
        if (game.critic > 0 || game.user > 0)
            game.scoreSource = "EmuFusion bundled catalog";
    }

    private static boolean hasCompleteBundledMetadata(ImportedGame game) {
        return "EmuFusion bundled catalog".equals(game.scoreSource) && game.critic > 0 &&
                game.user > 0 && !game.release.isEmpty();
    }

    private BundledGameRecord bundledGameRecord(String folder, String title) {
        return bundledGameIndex().get(folder + "\t" + normalize(title));
    }

    private synchronized Map<String, BundledGameRecord> bundledGameIndex() {
        if (bundledGameIndex != null) return bundledGameIndex;
        Map<String, BundledGameRecord> index = new HashMap<>();
        int resourceId = context.getResources().getIdentifier(
                "lucent_game_metadata", "raw", context.getPackageName());
        if (resourceId == 0) {
            bundledGameIndex = index;
            return index;
        }
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(
                context.getResources().openRawResource(resourceId), StandardCharsets.UTF_8))) {
            String line;
            boolean header = true;
            while ((line = reader.readLine()) != null) {
                if (header) { header = false; continue; }
                String[] fields = line.split("\t", -1);
                if (fields.length < 3) continue;
                double critic = numeric(fieldAt(fields, 3));
                double user = numeric(fieldAt(fields, 4));
                BundledGameRecord record = new BundledGameRecord(fieldAt(fields, 2),
                        critic, user, fieldAt(fields, 5), fieldAt(fields, 6),
                        fieldAt(fields, 7), fieldAt(fields, 8), fieldAt(fields, 9));
                index.put(fieldAt(fields, 0) + "\t" + fieldAt(fields, 1), record);
            }
        } catch (Exception error) {
            Log.e(TAG, "Unable to load bundled Lucent game metadata", error);
        }
        bundledGameIndex = index;
        return index;
    }

    private static double numeric(String value) {
        try { return Double.parseDouble(value); }
        catch (NumberFormatException ignored) { return 0; }
    }

    private static String fieldAt(String[] fields, int index) {
        return index >= 0 && index < fields.length ? fields[index] : "";
    }

    private void enrichMetacritic(ImportedGame game, File cacheRoot) {
        if (game.system.metacriticPlatform.isEmpty()) return;
        try {
            String encoded = URLEncoder.encode(game.title, "UTF-8").replace("+", "%20");
            String query = "?offset=0&limit=30&mcoTypeId=13&componentName=search" +
                    "&componentDisplayName=Search&componentType=SearchResults";
            JSONObject root = new JSONObject(new String(fetchBytes(
                    "https://backend.metacritic.com/finder/metacritic/search/" + encoded +
                            "/web" + query, 12L * 1024L * 1024L), StandardCharsets.UTF_8));
            JSONArray items = root.optJSONObject("data") == null ? null :
                    root.optJSONObject("data").optJSONArray("items");
            if (items == null) return;
            String expected = normalize(game.title);
            for (int i = 0; i < items.length(); i++) {
                JSONObject item = items.optJSONObject(i);
                if (item == null || !normalize(item.optString("title")).equals(expected)) continue;
                if (!hasPlatform(item.optJSONArray("platforms"), game.system.metacriticPlatform)) continue;
                JSONObject critic = item.optJSONObject("criticScoreSummary");
                JSONObject user = item.optJSONObject("userScore");
                if (critic != null && critic.optDouble("score", 0) > 0) {
                    game.metacriticCritic = critic.optInt("score");
                    game.metacriticReviews = critic.optInt("reviewCount", 0);
                }
                if (user != null && user.optDouble("score", 0) > 0)
                    game.user = user.optDouble("score");
                game.release = item.optString("releaseDate", "");
                game.metacriticSlug = item.optString("slug", "");
                enrichMetacriticDetails(game);
                return;
            }
        } catch (Exception error) {
            Log.w(TAG, "Metacritic unavailable for " + game.title, error);
        }
    }

    private void enrichMetacriticDetails(ImportedGame game) {
        if (game.metacriticSlug.isEmpty()) return;
        try {
            String slug = encodePath(game.metacriticSlug);
            String productQuery = "?componentName=product&componentDisplayName=Product" +
                    "&componentType=Product";
            JSONObject productRoot = new JSONObject(new String(fetchBytes(
                    "https://backend.metacritic.com/games/metacritic/" + slug +
                            "/web" + productQuery, 12L * 1024L * 1024L), StandardCharsets.UTF_8));
            JSONObject product = productRoot.optJSONObject("data") == null ? null :
                    productRoot.optJSONObject("data").optJSONObject("item");
            if (product != null) {
                JSONObject production = product.optJSONObject("production");
                JSONArray companies = production == null ? null : production.optJSONArray("companies");
                if (companies != null) {
                    for (int i = 0; i < companies.length(); i++) {
                        JSONObject company = companies.optJSONObject(i);
                        if (company == null || company.optString("name").trim().isEmpty()) continue;
                        if ("Developer".equalsIgnoreCase(company.optString("typeName")))
                            addUnique(game.developers, company.optString("name"));
                        else if ("Publisher".equalsIgnoreCase(company.optString("typeName")))
                            addUnique(game.publishers, company.optString("name"));
                    }
                }
                JSONArray platforms = product.optJSONArray("platforms");
                if (platforms != null) {
                    for (int i = 0; i < platforms.length(); i++) {
                        JSONObject platform = platforms.optJSONObject(i);
                        if (platform == null || !platform.optString("name").equalsIgnoreCase(
                                game.system.metacriticPlatform)) continue;
                        JSONObject critic = platform.optJSONObject("criticScoreSummary");
                        if (critic != null && critic.optDouble("score", 0) > 0) {
                            game.metacriticCritic = critic.optInt("score");
                            game.metacriticReviews = critic.optInt("reviewCount", 0);
                        }
                        String release = platform.optString("releaseDate", "");
                        if (!release.isEmpty()) game.release = release;
                        break;
                    }
                }
            }
            String userQuery = "?platform=" + encodePath(game.system.metacriticSlug) +
                    "&componentName=user-score-summary&componentDisplayName=User%20Score%20Summary" +
                    "&componentType=MetaScoreSummary";
            JSONObject userRoot = new JSONObject(new String(fetchBytes(
                    "https://backend.metacritic.com/reviews/metacritic/user/games/" + slug +
                            "/stats/web" + userQuery, 8L * 1024L * 1024L), StandardCharsets.UTF_8));
            JSONObject user = userRoot.optJSONObject("data") == null ? null :
                    userRoot.optJSONObject("data").optJSONObject("item");
            if (user != null && user.optDouble("score", 0) > 0) {
                game.user = user.optDouble("score");
                game.metacriticUser = game.user;
            }
        } catch (Exception error) {
            // Search-level data is retained if a detail endpoint is unavailable.
            Log.w(TAG, "Metacritic detail unavailable for " + game.title, error);
        }
    }

    private void enrichGameRankings(ImportedGame game) {
        GameRankingsRecord record = gameRankingsRecord(game.system.folder, game.title);
        if (record == null) return;
        game.gamerankingsScore = record.score;
        game.gamerankingsReviews = record.reviews;
        game.gamerankingsUrl = record.url;
        if (game.release.isEmpty() && !record.year.isEmpty())
            game.release = record.year + "-01-01";
    }

    private void enrichMobyGames(ImportedGame game) {
        MobyGamesRecord record = mobygamesRecord(game.system.folder, game.title);
        if (record == null) return;
        game.mobygamesScore = record.score;
        game.mobygamesUrl = record.url;
        if (game.release.isEmpty() && !record.year.isEmpty())
            game.release = record.year + "-01-01";
        addUnique(game.developers, record.developer);
    }

    private static void calculateCriticComposite(ImportedGame game) {
        double weighted = 0;
        int weight = 0;
        if (game.metacriticCritic > 0) {
            int reviews = Math.max(1, game.metacriticReviews);
            weighted += game.metacriticCritic * reviews;
            weight += reviews;
        }
        if (game.gamerankingsScore > 0) {
            int reviews = Math.max(1, game.gamerankingsReviews);
            weighted += game.gamerankingsScore * reviews;
            weight += reviews;
        }
        if (game.mobygamesScore > 0) {
            // The public MobyGames browser guarantees at least five critic
            // ratings for every packaged record. Use that documented lower
            // bound rather than inventing a review count.
            weighted += game.mobygamesScore * 5;
            weight += 5;
        }
        // Preserve EmuFusion's bundled composite when no external component was
        // available. This keeps offline imports from losing known scores.
        if (weight == 0) return;
        game.critic = (int)Math.round(weighted / weight);
        List<String> sources = new ArrayList<>();
        if (game.metacriticCritic > 0) sources.add("Metacritic");
        if (game.gamerankingsScore > 0) sources.add("GameRankings");
        if (game.mobygamesScore > 0) sources.add("MobyGames");
        game.scoreSource = join(sources, " + ");
    }

    private int repairMissingScores() {
        File[] files = PEGASUS.listFiles((dir, name) -> name.endsWith(".metadata.pegasus.txt") &&
                !name.equals(AUTO_METADATA.getName()));
        if (files == null) return 0;
        int repaired = 0;
        for (File metadata : files) {
            try {
                List<String> stanzas = splitStanzas(readText(metadata));
                boolean changed = false;
                for (int i = 0; i < stanzas.size(); i++) {
                    String stanza = stanzas.get(i);
                    if (!stanza.startsWith("game:") || !field(stanza, "x-critic").isEmpty() ||
                            !field(stanza, "x-metacritic-critic").isEmpty()) continue;
                    String title = field(stanza, "game");
                    GameSystems.SystemDef system = systemFromRomPath(field(stanza, "file"));
                    if (system == null) continue;
                    GameRankingsRecord record = gameRankingsRecord(system.folder, title);
                    if (record == null) continue;
                    StringBuilder scored = new StringBuilder(removeField(stanza, "rating").trim());
                    scored.append("\nrating: ").append(String.format(Locale.US, "%.4f", record.score / 100.0));
                    scored.append("\nx-critic: ").append(format(record.score / 10.0));
                    scored.append("\nx-critic-composite: ").append(format(record.score / 10.0));
                    scored.append("\nx-gamerankings-score: ").append(formatScore(record.score));
                    scored.append("\nx-gamerankings-reviews: ").append(record.reviews);
                    if (!record.url.isEmpty())
                        scored.append("\nx-gamerankings-url: ").append(metadataSafe(record.url));
                    scored.append("\nx-gamerankings-snapshot: 2019-12-08");
                    scored.append("\nx-score-source: GameRankings");
                    scored.append("\nx-critic-sources: GameRankings=")
                            .append(format(record.score / 10.0));
                    stanzas.set(i, scored.toString());
                    changed = true;
                    repaired++;
                }
                if (changed) writeTextAtomic(metadata, joinStanzas(stanzas));
            } catch (Exception error) {
                Log.w(TAG, "Historical score audit skipped " + metadata, error);
            }
        }
        return repaired;
    }

    private GameRankingsRecord gameRankingsRecord(String folder, String title) {
        Map<String, GameRankingsRecord> index = gameRankingsIndex();
        String normalized = normalize(title);
        GameRankingsRecord exact = index.get(folder + "\t" + normalized);
        if (exact != null) return exact;
        return gamerankingsAliasIndex.get(folder + "\t" + scoreAlias(normalized));
    }

    private synchronized Map<String, GameRankingsRecord> gameRankingsIndex() {
        if (gamerankingsIndex != null) return gamerankingsIndex;
        Map<String, GameRankingsRecord> index = new HashMap<>();
        Map<String, GameRankingsRecord> aliases = new HashMap<>();
        Set<String> ambiguousAliases = new HashSet<>();
        int resourceId = context.getResources().getIdentifier(
                "gamerankings_scores", "raw", context.getPackageName());
        if (resourceId == 0) {
            gamerankingsAliasIndex = aliases;
            gamerankingsIndex = index;
            return index;
        }
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(
                context.getResources().openRawResource(resourceId), StandardCharsets.UTF_8))) {
            String line;
            boolean header = true;
            while ((line = reader.readLine()) != null) {
                if (header) { header = false; continue; }
                String[] fields = line.split("\t", -1);
                if (fields.length < 8) continue;
                double score;
                int reviews;
                try {
                    score = Double.parseDouble(fields[3]);
                    reviews = Integer.parseInt(fields[4]);
                } catch (NumberFormatException ignored) { continue; }
                GameRankingsRecord record = new GameRankingsRecord(
                        score, reviews, fields[5], fields[6], fields[7]);
                index.put(fields[0] + "\t" + fields[1], record);

                // The archived catalog and ROM sets often differ only in logo
                // spacing (Mega Man/Megaman), Roman numerals, or a filename
                // truncated near 40 characters. Add only aliases that resolve
                // to exactly one game on the same platform; ambiguous aliases
                // are removed rather than guessed.
                putUniqueAlias(aliases, ambiguousAliases,
                        fields[0] + "\t" + scoreAlias(fields[1]), record);
                if (fields[1].length() > 35) {
                    int firstPrefix = Math.max(35, fields[1].length() - 6);
                    for (int length = firstPrefix; length < fields[1].length(); length++)
                        putUniqueAlias(aliases, ambiguousAliases,
                                fields[0] + "\t" + scoreAlias(fields[1].substring(0, length)), record);
                }
            }
        } catch (Exception error) {
            Log.e(TAG, "Unable to load packaged GameRankings index", error);
        }
        for (String key : ambiguousAliases) aliases.remove(key);
        gamerankingsAliasIndex = aliases;
        gamerankingsIndex = index;
        return index;
    }

    private MobyGamesRecord mobygamesRecord(String folder, String title) {
        String normalized = normalize(title);
        MobyGamesRecord exact = mobygamesIndex().get(folder + "\t" + normalized);
        if (exact != null) return exact;
        Set<MobyGamesRecord> candidates = new HashSet<>();
        for (String alias : historicalAliases(normalized)) {
            MobyGamesRecord record = mobygamesAliasIndex.get(folder + "\t" + alias);
            if (record != null) candidates.add(record);
        }
        return candidates.size() == 1 ? candidates.iterator().next() : null;
    }

    private synchronized Map<String, MobyGamesRecord> mobygamesIndex() {
        if (mobygamesIndex != null) return mobygamesIndex;
        Map<String, MobyGamesRecord> index = new HashMap<>();
        Map<String, MobyGamesRecord> aliases = new HashMap<>();
        Set<String> ambiguousAliases = new HashSet<>();
        int resourceId = context.getResources().getIdentifier(
                "mobygames_historical", "raw", context.getPackageName());
        if (resourceId == 0) {
            mobygamesAliasIndex = aliases;
            mobygamesIndex = index;
            return index;
        }
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(
                context.getResources().openRawResource(resourceId), StandardCharsets.UTF_8))) {
            String line;
            boolean header = true;
            while ((line = reader.readLine()) != null) {
                if (header) { header = false; continue; }
                String[] fields = line.split("\t", -1);
                if (fields.length < 7) continue;
                double score;
                try { score = Double.parseDouble(fields[3]); }
                catch (NumberFormatException ignored) { continue; }
                MobyGamesRecord record = new MobyGamesRecord(
                        score, fields[4], fields[5], fields[6]);
                index.put(fields[0] + "\t" + fields[1], record);
                for (String alias : historicalAliases(fields[1]))
                    putUniqueMobyAlias(aliases, ambiguousAliases,
                            fields[0] + "\t" + alias, record);
            }
        } catch (Exception error) {
            Log.e(TAG, "Unable to load packaged MobyGames historical index", error);
        }
        for (String key : ambiguousAliases) aliases.remove(key);
        mobygamesAliasIndex = aliases;
        mobygamesIndex = index;
        return index;
    }

    private static void putUniqueMobyAlias(Map<String, MobyGamesRecord> aliases,
            Set<String> ambiguous, String key, MobyGamesRecord record) {
        if (key.endsWith("\t") || ambiguous.contains(key)) return;
        MobyGamesRecord previous = aliases.putIfAbsent(key, record);
        if (previous != null && previous != record) {
            aliases.remove(key);
            ambiguous.add(key);
        }
    }

    private static Set<String> historicalAliases(String normalized) {
        Set<String> expanded = new HashSet<>();
        expanded.add(normalized);
        String[] words = normalized.split(" ");
        if (words.length > 1 && ("the".equals(words[0]) || "a".equals(words[0]) || "an".equals(words[0])))
            expanded.add(joinWords(words, 1, words.length));
        if (words.length > 1 && ("the".equals(words[words.length - 1]) ||
                "a".equals(words[words.length - 1]) || "an".equals(words[words.length - 1]))) {
            expanded.add(joinWords(words, 0, words.length - 1));
            expanded.add(words[words.length - 1] + " " + joinWords(words, 0, words.length - 1));
        }
        for (String value : new ArrayList<>(expanded))
            expanded.add(value.replaceAll("(?:^|\\s)and(?:\\s|$)", " ").trim().replaceAll("\\s+", " "));
        Set<String> result = new HashSet<>();
        for (String value : expanded) {
            result.add(value);
            result.add(scoreAlias(value));
        }
        result.remove("");
        return result;
    }

    private static String joinWords(String[] words, int start, int end) {
        StringBuilder result = new StringBuilder();
        for (int i = start; i < end; i++) {
            if (result.length() > 0) result.append(' ');
            result.append(words[i]);
        }
        return result.toString();
    }

    private static void putUniqueAlias(Map<String, GameRankingsRecord> aliases,
            Set<String> ambiguous, String key, GameRankingsRecord record) {
        if (key.endsWith("\t") || ambiguous.contains(key)) return;
        GameRankingsRecord previous = aliases.putIfAbsent(key, record);
        if (previous != null && previous != record) {
            aliases.remove(key);
            ambiguous.add(key);
        }
    }

    private static String scoreAlias(String normalized) {
        return TitleMatcher.compact(normalized);
    }

    private static Set<String> mediaAliases(String title) {
        Set<String> values = new HashSet<>();
        String key = normalize(title);
        values.add(key);
        values.add(scoreAlias(key));
        String relaxed = key.replaceAll(
                        "\\b(?:fan translation|english translation|translation|prototype|beta|demo)\\b",
                        " ")
                .replaceAll("\\s+", " ").trim()
                .replace(" the the ", " the ");
        values.add(relaxed);
        values.add(scoreAlias(relaxed));
        String articleless = relaxed.replaceAll("\\b(?:the|a|an)\\b", " ")
                .replaceAll("\\s+", " ").trim();
        values.add(articleless);
        values.add(scoreAlias(articleless));
        String sourceTitle = cleanTitle(title);
        int sourceColon = sourceTitle.indexOf(':');
        if (sourceColon > 3) {
            String shortTitle = normalize(sourceTitle.substring(0, sourceColon)
                    .replaceAll(",\\s*(The|A|An)$", ""));
            if (shortTitle.contains(" ")) {
                values.add(shortTitle);
                values.add(scoreAlias(shortTitle));
            }
        }
        if (relaxed.startsWith("castlevania rondo of blood")) {
            values.add("akumajou dracula x chi no rondo");
            values.add(scoreAlias("akumajou dracula x chi no rondo"));
        }
        // The PS2 archive catalogs the North American KOF 2002 disc under
        // the retail 2002/2003 two-disc compilation name.
        if (relaxed.startsWith("king of fighters 2002"))
            values.add("kingoffighters20022003usadisc1");
        if (relaxed.startsWith("the ")) {
            values.add(relaxed.substring(4));
            values.add(scoreAlias(relaxed.substring(4)));
        }
        return values;
    }

    private static String nintendoSlug(String title) {
        switch (normalize(title)) {
            case "blasphemous ii": return "blasphemous-2-switch";
            case "mega man 11": return "mega-man-11-switch";
            case "metroid dread": return "metroid-dread-switch";
            case "new super mario bros u deluxe": return "new-super-mario-bros-u-deluxe-switch";
            case "prince of persia the lost crown":
                return "prince-of-persia-the-lost-crown-switch";
            case "super mario 3d world bowsers fury":
                return "super-mario-3d-world-plus-bowsers-fury-switch";
            case "the legend of zelda links awakening":
                return "the-legend-of-zelda-links-awakening-switch";
            default:
                String slug = normalize(title).replace(' ', '-');
                return slug.isEmpty() ? "" : slug + "-switch";
        }
    }

    private static boolean nintendoTitlesEquivalent(String requested, String official) {
        String left = scoreAlias(normalize(requested));
        String right = scoreAlias(normalize(official.replace("&trade;", "")
                .replace("&reg;", "").replace("&#39;", "'")
                .replace("™", "").replace("®", "").replace("©", "")));
        return left.equals(right);
    }

    private static int archiveCandidateScore(String requested, GameSystems.SystemDef system,
                                             String candidateTitle) {
        String candidate = normalize(candidateTitle);
        String compactCandidate = scoreAlias(candidate);
        String lower = " " + candidateTitle.toLowerCase(Locale.US) + " ";
        String[] rejected = new String[]{"soundtrack", " ost ", "music", "podcast", "reaction",
                "speedrun", "tournament", "walkthrough", "longplay", "let s play", "parody",
                "ending", "mod showcase", "full game"};
        for (String token : rejected) if (lower.contains(token)) return -1000;
        if (!normalize(requested).contains(" vs ") && lower.matches(".*\\bvs\\b.*"))
            return -1000;
        if (lower.contains("disaster")) return -1000;
        if (lower.matches(".*\\bin\\s+\\d{1,3}:\\d{2}.*")) return -1000;
        int score = 0;
        // A series prefix is not this game. In particular, dropping the
        // subtitle from Mario Kart: Super Circuit matched Mario Kart Tour.
        for (String alias : TitleMatcher.fullTitleForms(requested)) {
            if (alias.isEmpty()) continue;
            if (candidate.equals(alias)) score = Math.max(score, 140);
            else if (candidate.contains(alias)) score = Math.max(score, 115);
            String compact = scoreAlias(alias);
            if (!compact.isEmpty() && compactCandidate.contains(compact))
                score = Math.max(score, 110);
        }
        if (score == 0) return -1000;
        String[] preferred = new String[]{"official", "trailer", "gameplay", "intro",
                "commercial", "review", "in brief", "in breif"};
        for (String token : preferred) if (lower.contains(token)) score += 4;
        if (system != null) {
            String platform = normalize(system.collection);
            if (!platform.isEmpty() && candidate.contains(platform)) score += 8;
        }
        return score;
    }

    private static String jsonUnescape(String value) {
        if (value == null) return "";
        return value.replace("\\u0026", "&").replace("\\/", "/");
    }

    private static long parseLong(String value) {
        try { return Long.parseLong(value); }
        catch (Exception ignored) { return 0L; }
    }

    private static boolean missingMediaFile(String path) {
        return path == null || path.isEmpty() || !new File(path).isFile();
    }

    private static boolean needsMediaRepair(ImportedGame game) {
        return missingMediaFile(game.boxArt) || missingMediaFile(game.background) ||
                !wallpaperCanvasIsValid(new File(game.background)) ||
                missingMediaFile(game.video);
    }

    private int repairMissingMedia(File cacheRoot, File mediaRoot, List<String> statusTitles,
                                   int added, boolean needsReload) {
        File[] files = PEGASUS.listFiles((dir, name) -> name.endsWith(".metadata.pegasus.txt") &&
                !name.startsWith("99-lucent-auto-") &&
                !name.startsWith("99-thorium-auto-"));
        if (files == null) return 0;
        int repaired = 0;
        for (int fileIndex = 0; fileIndex < files.length; fileIndex++) {
            File metadata = files[fileIndex];
            try {
                List<String> stanzas = splitStanzas(readText(metadata));
                boolean changed = false;
                for (int i = 0; i < stanzas.size(); i++) {
                    String stanza = stanzas.get(i);
                    if (!stanza.startsWith("game:")) continue;
                    String title = field(stanza, "game");
                    String romPath = field(stanza, "file");
                    if (i <= 1 || i % 20 == 0) {
                        double fileFraction = stanzas.isEmpty() ? 1.0 :
                                Math.min(1.0, (double)(i + 1) / stanzas.size());
                        double overall = (fileIndex + fileFraction) / Math.max(1, files.length);
                        setDetailedStatus("artwork", 0.93 + 0.035 * overall,
                                "Auditing the full library media…",
                                metadata.getName() + "  •  " + cleanTitle(title),
                                fileIndex + 1, files.length, statusTitles, added, needsReload);
                    }
                    String artPath = field(stanza, "assets.boxFront");
                    String backgroundPath = field(stanza, "assets.background");
                    String videoPath = field(stanza, "assets.video");
                    boolean needsArt = missingMediaFile(artPath);
                    boolean needsBackground = missingMediaFile(backgroundPath) ||
                            !wallpaperCanvasIsValid(new File(backgroundPath));
                    boolean needsVideo = missingMediaFile(videoPath);
                    if (!needsArt && !needsBackground && !needsVideo) continue;
                    GameSystems.SystemDef system = systemFromRomPath(romPath);
                    File rom = new File(romPath);
                    if (system == null || !rom.isFile()) continue;
                    ImportedGame game = new ImportedGame(system,
                            "metadata:" + romPath, cleanTitle(title), rom);
                    game.boxArt = artPath;
                    game.background = backgroundPath;
                    game.video = videoPath;
                    game.backgroundSource = field(stanza, "x-background-source");
                    game.backgroundSourceUrl = field(stanza, "x-background-source-url");
                    game.backgroundTransform = field(stanza, "x-background-transform");
                    game.inferBackgroundProvenance();

                    if (needsArt && !recentlyMissed(cacheRoot, system, title)) {
                        enrichBoxArt(game, cacheRoot, mediaRoot);
                        if (missingMediaFile(game.boxArt)) recordMiss(cacheRoot, system, title);
                    }
                    if (needsBackground) enrichBackground(game, cacheRoot, mediaRoot);
                    if (needsVideo) enrichVideo(game, cacheRoot, mediaRoot);

                    String updated = stanza;
                    if (needsArt && !missingMediaFile(game.boxArt)) {
                        updated = removeField(updated, "assets.boxFront").trim() +
                                "\nassets.boxFront: " + game.boxArt;
                        repaired++;
                    }
                    if (needsBackground && !missingMediaFile(game.background)) {
                        updated = removeField(updated, "assets.background");
                        updated = removeField(updated, "x-background-source");
                        updated = removeField(updated, "x-background-source-url");
                        updated = removeField(updated, WallpaperAccent.METADATA_FIELD);
                        updated = removeField(updated, "x-background-transform").trim() +
                                "\nassets.background: " + game.background +
                                "\nx-background-source: " + game.backgroundSource;
                        if (!game.backgroundSourceUrl.isEmpty())
                            updated += "\nx-background-source-url: " + game.backgroundSourceUrl;
                        if (!game.backgroundTransform.isEmpty())
                            updated += "\nx-background-transform: " + game.backgroundTransform;
                        // Hand-authored collections are repaired in place, so
                        // the accent has to travel with the new wallpaper.
                        if (!game.accent.isEmpty())
                            updated += "\n" + WallpaperAccent.METADATA_FIELD + ": " + game.accent;
                        repaired++;
                    }
                    if (needsVideo && !missingMediaFile(game.video)) {
                        updated = removeField(updated, "assets.video").trim() +
                                "\nassets.video: " + game.video;
                        repaired++;
                    }
                    if (!updated.equals(stanza)) {
                        stanzas.set(i, updated);
                        changed = true;
                    }
                }
                if (changed) writeTextAtomic(metadata, joinStanzas(stanzas));
            } catch (Exception error) {
                Log.w(TAG, "Media audit skipped " + metadata, error);
            }
        }
        // Persist the content audit keyed by path, size, and mtime. Subsequent
        // launches reuse it immediately and only decode changed/new artwork.
        persistWallpaperQualityCache(cacheRoot);
        return repaired;
    }

    private CatalogMatch boxArtMatch(GameSystems.SystemDef system, String title, File cacheRoot)
            throws Exception {
        return catalogMatch(system, title, cacheRoot, "Named_Boxarts");
    }

    private CatalogMatch launchBoxFanartMatch(GameSystems.SystemDef system, String title,
                                               File cacheRoot) throws Exception {
        File searchCache = new File(cacheRoot,
                "launchbox-search-" + system.folder + '-' + sha1(normalize(title)) + ".html");
        String results = cachedText(searchCache,
                "https://gamesdb.launchbox-app.com/games/results?id=" +
                        URLEncoder.encode(title, "UTF-8"),
                30L * 24L * 60L * 60L * 1000L, 12L * 1024L * 1024L);
        Pattern card = Pattern.compile(
                "href=\"/games/details/(\\d+)-[^\"]+\".*?" +
                        "<h3[^>]*>(.*?)</h3>\\s*<p[^>]*>(.*?)</p>",
                Pattern.CASE_INSENSITIVE | Pattern.DOTALL);
        Matcher cards = card.matcher(results);
        String gameId = "";
        // Full-title spellings only. The pooled alias set also contained the
        // title with its subtitle removed, which is the same thing that put
        // the base game's box on a subtitled edition — here it would have
        // fetched the base game's fanart as this game's wallpaper.
        Set<String> requestedAliases = TitleMatcher.fullTitleForms(title);
        while (cards.find()) {
            String candidateTitle = htmlText(cards.group(2));
            String platform = htmlText(cards.group(3));
            boolean exactTitle = false;
            String normalizedCandidate = normalize(candidateTitle);
            for (String alias : requestedAliases) {
                if (normalizedCandidate.equals(alias)) {
                    exactTitle = true;
                    break;
                }
            }
            if (!exactTitle || !launchBoxPlatformMatches(system, platform)) continue;
            gameId = cards.group(1);
            break;
        }
        if (gameId.isEmpty()) return null;

        File imagesCache = new File(cacheRoot, "launchbox-images-" + gameId + ".html");
        String images = cachedText(imagesCache,
                "https://gamesdb.launchbox-app.com/games/images/" + gameId,
                30L * 24L * 60L * 60L * 1000L, 24L * 1024L * 1024L);
        Pattern fanart = Pattern.compile(
                "<a\\b[^>]*href=\"(https://images\\.launchbox-app\\.com/[^\"]+)\"" +
                        "[^>]*data-title=\"[^\"]*Fanart - Background[^\"]*\"" +
                        "[^>]*data-footer=\"(\\d+)\\s*x\\s*(\\d+)[^\"]*\"",
                Pattern.CASE_INSENSITIVE | Pattern.DOTALL);
        Matcher candidates = fanart.matcher(images);
        String bestUrl = "";
        long bestPixels = 0L;
        while (candidates.find()) {
            int width = Integer.parseInt(candidates.group(2));
            int height = Integer.parseInt(candidates.group(3));
            if (width < 960 || height < 540) continue;
            float aspect = width / (float) height;
            if (aspect < 1.35f || aspect > 2.35f) continue;
            long pixels = (long) width * height;
            if (pixels > bestPixels) {
                bestPixels = pixels;
                bestUrl = htmlText(candidates.group(1));
            }
        }
        return bestUrl.isEmpty() ? null : new CatalogMatch(bestUrl, cleanTitle(title));
    }

    private static boolean launchBoxPlatformMatches(GameSystems.SystemDef system,
                                                    String platform) {
        String candidate = normalize(platform);
        if (candidate.equals(normalize(system.collection))) return true;
        for (String alias : system.aliases)
            if (candidate.equals(normalize(alias))) return true;
        // LaunchBox uses these shorter official labels for a few collections.
        if ("megadrive".equals(system.folder)) return candidate.equals("sega genesis");
        if ("psx".equals(system.folder)) return candidate.equals("sony playstation");
        if ("gba".equals(system.folder)) return candidate.equals("nintendo game boy advance");
        return false;
    }

    private static String htmlText(String value) {
        if (value == null) return "";
        return value.replaceAll("<[^>]+>", " ")
                .replace("&#x27;", "'").replace("&#39;", "'")
                .replace("&quot;", "\"").replace("&amp;", "&")
                .replace("&nbsp;", " ").replaceAll("\\s+", " ").trim();
    }

    /**
     * The catalog entry that belongs to one title, or null.
     *
     * <p>Ranking lives in {@link TitleMatcher}: a full-title match always
     * beats a subtitle-stripped one, and a subtitle-stripped one is refused
     * when another game in the same collection already carries that shorter
     * name. Pooling those aliases and ordering the pool by region tag is what
     * put "Bass Masters Classic"'s box on "Bass Masters Classic: Pro Edition"
     * and plain "Jurassic Park"'s on "Jurassic Park: Rampage Edition".
     */
    private CatalogMatch catalogMatch(GameSystems.SystemDef system, String title, File cacheRoot,
                                      String category) throws Exception {
        List<String> candidates = catalogEntries(system, cacheRoot, category);
        if (candidates.isEmpty()) return null;
        TitleMatcher.Match match = TitleMatcher.select(title, candidates,
                claimedTitles(system));
        if (match == null) return null;
        // An exact-title hit is the normal case and says nothing useful. The
        // weaker tiers are the ones that used to attach the wrong box, so
        // every one of them leaves a line naming both sides of the pairing.
        if (match.tier != TitleMatcher.TIER_EXACT)
            Log.i(TAG, "Artwork match (" + match.reason() + ") " + system.folder + " • \"" +
                    title + "\" -> " + decode(match.name) + " [" + category + "]");
        String base = "https://thumbnails.libretro.com/" + encodePath(system.libretro) +
                "/" + category + "/";
        return new CatalogMatch(base + encodeHref(match.name),
                cleanTitle(stem(decode(match.name))));
    }

    /** Every thumbnail file name one catalog publishes, in listing order. */
    private List<String> catalogEntries(GameSystems.SystemDef system, File cacheRoot,
                                        String category) throws Exception {
        List<String> hrefs = new ArrayList<>();
        if (system == null || system.libretro.isEmpty()) return hrefs;
        File cache = new File(cacheRoot, "libretro-" + system.folder + "-" + category + ".html");
        String html = cachedText(cache,
                "https://thumbnails.libretro.com/" + encodePath(system.libretro) + "/" + category + "/",
                7L * 24L * 60L * 60L * 1000L, 32L * 1024L * 1024L);
        Matcher matcher = HREF.matcher(html);
        while (matcher.find()) hrefs.add(matcher.group(1));
        return hrefs;
    }

    /**
     * The normalized titles of every other game already known on one system.
     *
     * <p>The subtitle guard needs this: when the library already contains a
     * game literally called "Bass Masters Classic", that name's artwork is
     * that game's, and "Bass Masters Classic: Pro Edition" may not borrow it.
     * Built once per scan from the Pegasus metafiles plus the import registry.
     */
    private Set<String> claimedTitles(GameSystems.SystemDef system) {
        if (system == null) return Collections.emptySet();
        if (claimedTitleCache.isEmpty()) buildClaimedTitles();
        Set<String> claimed = claimedTitleCache.get(system.folder);
        return claimed == null ? Collections.emptySet() : claimed;
    }

    /**
     * Reads every metafile once and indexes the titles by system. Doing this
     * per system instead would re-read several megabytes of metadata for each
     * of the fifty-odd platforms.
     */
    private synchronized void buildClaimedTitles() {
        if (!claimedTitleCache.isEmpty()) return;
        Map<String, List<String>> byFolder = new LinkedHashMap<>();
        try {
            for (File metadata : metadataFiles()) {
                String collection = "";
                for (String stanza : splitStanzas(readText(metadata))) {
                    String declared = field(stanza, "collection");
                    if (!declared.isEmpty()) collection = declared;
                    String title = field(stanza, "game");
                    if (title.isEmpty()) continue;
                    GameSystems.SystemDef owner = systemFromRomPath(field(stanza, "file"));
                    if (owner == null) owner = GameSystems.byAlias(collection);
                    if (owner == null) continue;
                    byFolder.computeIfAbsent(owner.folder, key -> new ArrayList<>()).add(title);
                }
            }
            JSONArray registry = readRegistry();
            for (int index = 0; index < registry.length(); index++) {
                JSONObject row = registry.optJSONObject(index);
                if (row == null) continue;
                String folder = row.optString("system");
                if (GameSystems.byFolder(folder) == null) continue;
                byFolder.computeIfAbsent(folder, key -> new ArrayList<>())
                        .add(row.optString("title"));
            }
        } catch (Exception error) {
            Log.w(TAG, "Unable to index sibling titles for the artwork guard", error);
        }
        for (GameSystems.SystemDef system : GameSystems.all()) {
            List<String> titles = byFolder.get(system.folder);
            claimedTitleCache.put(system.folder, TitleMatcher.claimedTitles(
                    titles == null ? Collections.<String>emptyList() : titles));
        }
    }

    /**
     * Finds every library entry whose game has no box art anywhere and puts it
     * in front of the owner, rather than acting on it.
     *
     * <p>Nothing here removes anything. The pass answers one question per
     * entry — "does artwork for this game exist in any platform catalog?" —
     * and turns a "no" into a row the owner can answer once. Their answer is
     * remembered forever, so an entry is only ever presented a single time.
     *
     * <p>The detection stays deliberately generous. A false "no artwork
     * exists" now surfaces as an offer to delete somebody's ROM, which is
     * worse than a silent skip, so the probe is
     * {@link TitleMatcher#hasAnyCandidate} with every matcher guard switched
     * off, the game's own platform is asked first and every other platform
     * after it, and a mostly-unreachable thumbnail server abandons the pass
     * outright.
     *
     * @return the number of entries now waiting for an answer, or -1 when the
     *         catalogs could not be read and no conclusion was reached
     */
    private int reviewArtlessGames(File cacheRoot, File mediaRoot) {
        Map<String, List<String>> catalogs = readArtworkCatalogs(cacheRoot);
        if (catalogs == null) return -1;

        JSONObject decisions = readDecisions(mediaRoot);
        JSONArray ledger = readLedger(mediaRoot);
        JSONArray pending = new JSONArray();
        Set<String> seen = new LinkedHashSet<>();
        Set<String> regained = new LinkedHashSet<>();
        boolean ledgerChanged = false;
        boolean decisionsChanged = false;

        for (File metadata : metadataFiles()) {
            try {
                List<String> stanzas = splitStanzas(readText(metadata));
                List<String> keep = new ArrayList<>();
                List<String> droppedPaths = new ArrayList<>();
                boolean changed = false;
                for (String stanza : stanzas) {
                    if (!stanza.startsWith("game:")) { keep.add(stanza); continue; }
                    String title = field(stanza, "game");
                    String romPath = field(stanza, "file");
                    GameSystems.SystemDef system = systemFromRomPath(romPath);
                    if (system == null || title.isEmpty()) { keep.add(stanza); continue; }
                    String key = decisionKey(system, title);
                    JSONObject decision = decisions.optJSONObject(key);

                    if (!missingMediaFile(field(stanza, "assets.boxFront"))) {
                        // The reason for the question has gone away. Forget the
                        // answer too, so a game that gains artwork is never
                        // held hostage by a choice made when it had none.
                        if (decision != null && !"delete-rom".equals(decision.optString("choice"))) {
                            decisions.remove(key);
                            decisionsChanged = true;
                            regained.add(title);
                        }
                        keep.add(stanza);
                        continue;
                    }

                    // A platform with no catalog offers no evidence either way.
                    List<String> own = catalogs.get(system.folder);
                    if (own == null) { keep.add(stanza); continue; }
                    if (TitleMatcher.hasAnyCandidate(title, own)) {
                        // Artwork exists and simply is not attached yet. That is
                        // a matcher gap, and it is never the owner's problem.
                        if (decision != null &&
                                !"delete-rom".equals(decision.optString("choice"))) {
                            decisions.remove(key);
                            decisionsChanged = true;
                        }
                        keep.add(stanza);
                        continue;
                    }

                    if (decision == null) {
                        if (seen.add(key))
                            pending.put(pendingEntry(key, system, title, romPath, stanza,
                                    metadata, artworkExistsIn(title, catalogs)));
                        keep.add(stanza);
                        continue;
                    }

                    String choice = decision.optString("choice");
                    if (CHOICE_KEEP.equals(choice)) { keep.add(stanza); continue; }
                    // Hidden and deleted entries lose their row. A hidden game
                    // keeps its ROM and its stanza text, both recorded, so the
                    // restore below can put it back the moment artwork turns up.
                    rememberStanza(decision, stanza, metadata, romPath);
                    decisionsChanged = true;
                    droppedPaths.add(romPath);
                    changed = true;
                    ledger.put(ledgerRecord(system, title, romPath, stanza, catalogs.size(),
                            choice, metadata, decision.optString("similarEntryOn")));
                    ledgerChanged = true;
                    Log.i(TAG, "Applying the owner's remembered choice for \"" + title +
                            "\" (" + system.folder + "): " + choice);
                }
                if (!changed) continue;
                for (int index = 0; index < keep.size(); index++)
                    keep.set(index, removeFileEntries(keep.get(index), droppedPaths));
                writeTextAtomic(metadata, joinStanzas(keep));
            } catch (Exception error) {
                Log.w(TAG, "Artwork review skipped " + metadata, error);
            }
        }

        if (restoreGamesThatGainedArtwork(decisions, catalogs, cacheRoot, mediaRoot, regained))
            decisionsChanged = true;
        if (decisionsChanged) writeDecisions(mediaRoot, decisions);
        if (ledgerChanged) {
            try { writeJsonAtomic(new File(mediaRoot, ARTLESS_LEDGER), ledger); }
            catch (Exception error) { Log.w(TAG, "Unable to write the artwork ledger", error); }
            try { writeMetadata(readRegistry()); }
            catch (Exception error) { Log.w(TAG, "Unable to rebuild metadata", error); }
        }
        writeReviewQueue(mediaRoot, pending);
        for (String title : regained)
            Log.i(TAG, "\"" + title + "\" has artwork again; its missing-artwork choice " +
                    "has been forgotten and it is visible");
        Log.i(TAG, "Artwork review: " + pending.length() + " entries are waiting for an answer");
        return pending.length();
    }

    /**
     * Puts back a hidden game once its artwork can be found again.
     *
     * <p>The owner hid it <em>because</em> nothing could be found for it, so
     * the choice is conditional on that being true. A better matcher or a new
     * catalog entry retires the choice and restores the stanza verbatim.
     * A deleted ROM is not revisited: there is nothing left to restore.
     */
    private boolean restoreGamesThatGainedArtwork(JSONObject decisions,
            Map<String, List<String>> catalogs, File cacheRoot, File mediaRoot,
            Set<String> regained) {
        boolean changed = false;
        for (String key : new ArrayList<>(jsonKeys(decisions))) {
            JSONObject decision = decisions.optJSONObject(key);
            if (decision == null || !CHOICE_HIDE.equals(decision.optString("choice"))) continue;
            String stanza = decision.optString("stanza");
            String title = decision.optString("title");
            GameSystems.SystemDef system = GameSystems.byFolder(decision.optString("system"));
            if (stanza.isEmpty() || system == null) continue;
            List<String> own = catalogs.get(system.folder);
            if (own == null || !TitleMatcher.hasAnyCandidate(title, own)) continue;
            File metadata = new File(decision.optString("metadataFile"));
            if (restoreStanza(metadata, stanza, decision.optString("romPath"))) {
                unarchiveRegistryRow(decision.optString("romPath"));
                decisions.remove(key);
                regained.add(title);
                changed = true;
            }
        }
        return changed;
    }

    /** Appends a stored stanza and its ROM path back into a metafile. */
    private static boolean restoreStanza(File metadata, String stanza, String romPath) {
        try {
            if (!metadata.isFile()) return false;
            List<String> stanzas = splitStanzas(readText(metadata));
            for (String existing : stanzas)
                if (romPath.equals(field(existing, "file"))) return true;
            if (!romPath.isEmpty()) {
                for (int index = 0; index < stanzas.size(); index++) {
                    String value = stanzas.get(index);
                    if (!value.startsWith("collection:") || !value.contains("\nfiles:")) continue;
                    stanzas.set(index, value + "\n  " + romPath);
                    break;
                }
            }
            stanzas.add(stanza);
            writeTextAtomic(metadata, joinStanzas(stanzas));
            return true;
        } catch (Exception error) {
            Log.w(TAG, "Unable to restore " + romPath + " to " + metadata, error);
            return false;
        }
    }

    /**
     * Every platform's thumbnail listing, or null when too few were readable.
     *
     * <p>Offering to delete somebody's games because a network fetch failed
     * would be inexcusable, so half the shelf missing abandons the pass.
     */
    private Map<String, List<String>> readArtworkCatalogs(File cacheRoot) {
        Map<String, List<String>> catalogs = new LinkedHashMap<>();
        int attempted = 0;
        for (GameSystems.SystemDef system : GameSystems.all()) {
            if (system.libretro.isEmpty()) continue;
            attempted++;
            try {
                List<String> entries = catalogEntries(system, cacheRoot, "Named_Boxarts");
                if (entries.isEmpty()) {
                    Log.w(TAG, "Artwork review: the " + system.folder +
                            " catalog listed nothing and is being skipped");
                    continue;
                }
                catalogs.put(system.folder, entries);
            } catch (Exception error) {
                Log.w(TAG, "Artwork review: the " + system.folder +
                        " catalog could not be read and is being skipped", error);
            }
        }
        Log.i(TAG, "Artwork review read " + catalogs.size() + " of " + attempted +
                " platform catalogs");
        if (catalogs.isEmpty() || catalogs.size() * 2 < attempted) {
            Log.w(TAG, "Artwork review abandoned: too few catalogs were reachable");
            return null;
        }
        return catalogs;
    }

    /** One row of the review list, annotated so the choice is an easy one. */
    private JSONObject pendingEntry(String key, GameSystems.SystemDef system, String title,
                                    String romPath, String stanza, File metadata,
                                    String similarOn) {
        JSONObject entry = new JSONObject();
        put(entry, "key", key);
        put(entry, "title", title);
        put(entry, "system", system.folder);
        put(entry, "collection", system.collection);
        put(entry, "romPath", romPath);
        put(entry, "romName", new File(romPath).getName());
        put(entry, "metadataFile", metadata.getAbsolutePath());
        put(entry, "stanza", stanza);
        boolean romPresent = !romPath.isEmpty() && new File(romPath).isFile();
        try { entry.put("romPresent", romPresent); } catch (Exception ignored) {}
        put(entry, "note", artlessNote(title, romPath, romPresent, similarOn));
        if (similarOn != null) put(entry, "similarEntryOn", similarOn);
        return entry;
    }

    /**
     * A one-line hint about what the entry actually is. These used to be the
     * removal's corroborating evidence; now that the owner decides, they are
     * kept as annotations, because "the ROM file is already missing" or "this
     * is a cheat cartridge" is exactly what makes the choice obvious.
     */
    private static String artlessNote(String title, String romPath, boolean romPresent,
                                      String similarOn) {
        if (!romPresent) return "The ROM file is already gone from storage";
        if (TitleMatcher.isUtilityTitle(title))
            return "Not a game — a cheat cartridge, BIOS, or service cart";
        if (TitleMatcher.isBootlegDump(new File(romPath).getName()))
            return "Dump tagged unlicensed, pirate, or hacked";
        if (similarOn != null)
            return "Nothing on this platform; a similar name exists under " + similarOn;
        return "No catalog on any platform lists this title";
    }

    /** The remembered answer for one game, stable across rescans and reinstalls. */
    private static String decisionKey(GameSystems.SystemDef system, String title) {
        return system.folder + "|" + normalize(title);
    }

    /**
     * Records the owner's answer for one game and carries it out at once.
     *
     * @param choice one of {@code leave}, {@code hide}, {@code delete-rom}
     */
    synchronized String decideArtwork(String key, String choice) {
        if (key == null || key.isEmpty()) return "";
        if (!CHOICE_KEEP.equals(choice) && !CHOICE_HIDE.equals(choice) &&
                !CHOICE_DELETE.equals(choice)) return "";
        File mediaRoot = mediaRoot();
        JSONArray queue = readReviewQueue(mediaRoot);
        JSONObject entry = null;
        JSONArray remaining = new JSONArray();
        for (int index = 0; index < queue.length(); index++) {
            JSONObject row = queue.optJSONObject(index);
            if (row == null) continue;
            if (key.equals(row.optString("key")) && entry == null) entry = row;
            else remaining.put(row);
        }
        if (entry == null) return "";

        String title = entry.optString("title");
        String romPath = entry.optString("romPath");
        GameSystems.SystemDef system = GameSystems.byFolder(entry.optString("system"));
        if (system == null) return "";

        if (CHOICE_DELETE.equals(choice) && !deleteRomFile(romPath)) {
            Log.e(TAG, "Refused to record a delete for \"" + title +
                    "\": the ROM file could not be removed");
            return "";
        }

        JSONObject decisions = readDecisions(mediaRoot);
        JSONObject decision = new JSONObject();
        put(decision, "choice", choice);
        put(decision, "title", title);
        put(decision, "system", system.folder);
        put(decision, "romPath", romPath);
        put(decision, "romName", entry.optString("romName"));
        put(decision, "metadataFile", entry.optString("metadataFile"));
        put(decision, "decidedAt", String.valueOf(System.currentTimeMillis()));
        if (!CHOICE_KEEP.equals(choice)) put(decision, "stanza", entry.optString("stanza"));
        try { decisions.put(key, decision); } catch (Exception ignored) {}
        writeDecisions(mediaRoot, decisions);
        writeReviewQueue(mediaRoot, remaining);

        if (!CHOICE_KEEP.equals(choice)) {
            removeLibraryRows(romPath);
            archiveRegistryRow(romPath);
            JSONArray ledger = readLedger(mediaRoot);
            ledger.put(ledgerRecord(system, title, romPath, entry.optString("stanza"), 0,
                    choice, new File(entry.optString("metadataFile")),
                    entry.optString("similarEntryOn")));
            try { writeJsonAtomic(new File(mediaRoot, ARTLESS_LEDGER), ledger); }
            catch (Exception error) { Log.w(TAG, "Unable to write the artwork ledger", error); }
            try { writeMetadata(readRegistry()); }
            catch (Exception error) { Log.w(TAG, "Unable to rebuild metadata", error); }
            // Pegasus has to re-read the metafiles before the row disappears.
            synchronized (statusLock) {
                try { status.put("needsReload", true); } catch (Exception ignored) {}
            }
        }
        Log.i(TAG, "Missing artwork for \"" + title + "\" (" + system.folder + "): the owner " +
                "chose " + choice + (CHOICE_DELETE.equals(choice) ?
                " and the ROM was deleted from " + romPath :
                " and the ROM is untouched at " + romPath));
        return choice;
    }

    /** The review list the frontend renders, newest scan first. */
    String artworkReviewJson() {
        JSONObject response = new JSONObject();
        try {
            JSONArray queue = readReviewQueue(mediaRoot());
            JSONArray games = new JSONArray();
            for (int index = 0; index < queue.length(); index++) {
                JSONObject row = queue.optJSONObject(index);
                if (row == null) continue;
                JSONObject item = new JSONObject();
                item.put("key", row.optString("key"));
                item.put("title", row.optString("title"));
                item.put("system", row.optString("system"));
                item.put("collection", row.optString("collection"));
                item.put("romName", row.optString("romName"));
                item.put("romPresent", row.optBoolean("romPresent", true));
                item.put("note", row.optString("note"));
                games.put(item);
            }
            response.put("count", games.length());
            response.put("games", games);
        } catch (Exception ignored) {}
        return response.toString();
    }

    /** Drops every metafile row that points at one ROM. */
    private void removeLibraryRows(String romPath) {
        if (romPath == null || romPath.isEmpty()) return;
        List<String> dropped = Collections.singletonList(romPath);
        for (File metadata : metadataFiles()) {
            try {
                List<String> stanzas = splitStanzas(readText(metadata));
                List<String> keep = new ArrayList<>();
                boolean changed = false;
                for (String stanza : stanzas) {
                    if (stanza.startsWith("game:") && romPath.equals(field(stanza, "file"))) {
                        changed = true;
                        continue;
                    }
                    keep.add(stanza);
                }
                if (!changed) continue;
                for (int index = 0; index < keep.size(); index++)
                    keep.set(index, removeFileEntries(keep.get(index), dropped));
                writeTextAtomic(metadata, joinStanzas(keep));
            } catch (Exception error) {
                Log.w(TAG, "Unable to drop " + romPath + " from " + metadata, error);
            }
        }
    }

    /**
     * Permanently removes one ROM, staging it on the same volume first so a
     * refusal cannot leave the library pointing at a half-deleted file.
     */
    private boolean deleteRomFile(String romPath) {
        if (romPath == null || romPath.isEmpty()) return false;
        File rom = new File(romPath);
        // Already gone is the outcome the owner asked for.
        if (!rom.isFile()) return true;
        File trash = new File(storageVolumeRoot(rom), ".LucentTrash");
        if (!trash.mkdirs() && !trash.isDirectory()) return rom.delete();
        File staged = uniqueTrashTarget(trash, rom.getName());
        if (!rom.renameTo(staged)) return rom.delete();
        if (staged.delete()) return true;
        staged.renameTo(rom);
        return false;
    }

    private boolean unarchiveRegistryRow(String romPath) {
        if (romPath == null || romPath.isEmpty()) return false;
        JSONArray registry = readRegistry();
        boolean changed = false;
        for (int index = 0; index < registry.length(); index++) {
            JSONObject row = registry.optJSONObject(index);
            if (row == null || !romPath.equals(row.optString("file"))) continue;
            if (!row.optBoolean("archived", false)) return false;
            try {
                row.put("archived", false);
                row.put("archiveReason", "");
                changed = true;
            } catch (Exception ignored) {}
            break;
        }
        if (!changed) return false;
        try {
            writeJsonAtomic(REGISTRY, registry);
            writeMetadata(registry);
            return true;
        } catch (Exception error) {
            Log.w(TAG, "Unable to restore the registry row for " + romPath, error);
            return false;
        }
    }

    private static void rememberStanza(JSONObject decision, String stanza, File metadata,
                                       String romPath) {
        if (decision.optString("stanza").isEmpty()) put(decision, "stanza", stanza);
        if (decision.optString("metadataFile").isEmpty())
            put(decision, "metadataFile", metadata.getAbsolutePath());
        if (decision.optString("romPath").isEmpty()) put(decision, "romPath", romPath);
    }

    private static List<String> jsonKeys(JSONObject value) {
        List<String> keys = new ArrayList<>();
        java.util.Iterator<String> iterator = value.keys();
        while (iterator.hasNext()) keys.add(iterator.next());
        return keys;
    }

    private static JSONObject readDecisions(File mediaRoot) {
        try {
            File file = new File(mediaRoot, ARTWORK_DECISIONS);
            return file.isFile() ? new JSONObject(readText(file)) : new JSONObject();
        } catch (Exception ignored) {
            return new JSONObject();
        }
    }

    private static void writeDecisions(File mediaRoot, JSONObject decisions) {
        try {
            writeTextAtomic(new File(mediaRoot, ARTWORK_DECISIONS),
                    decisions.toString(2) + "\n");
        } catch (Exception error) {
            Log.w(TAG, "Unable to save the missing-artwork choices", error);
        }
    }

    private static JSONArray readReviewQueue(File mediaRoot) {
        try {
            File file = new File(mediaRoot, ARTWORK_REVIEW_QUEUE);
            return file.isFile() ? new JSONArray(readText(file)) : new JSONArray();
        } catch (Exception ignored) {
            return new JSONArray();
        }
    }

    private static void writeReviewQueue(File mediaRoot, JSONArray queue) {
        try {
            writeJsonAtomic(new File(mediaRoot, ARTWORK_REVIEW_QUEUE), queue);
        } catch (Exception error) {
            Log.w(TAG, "Unable to save the missing-artwork review list", error);
        }
    }

    /**
     * The first platform whose catalog carries something resembling a title,
     * or null when none of them does. The platform is named in the review row
     * so a surprising entry can be traced to the catalog that vouched.
     */
    private static String artworkExistsIn(String title, Map<String, List<String>> catalogs) {
        for (Map.Entry<String, List<String>> entry : catalogs.entrySet())
            if (TitleMatcher.hasAnyCandidate(title, entry.getValue())) return entry.getKey();
        return null;
    }

    private JSONObject ledgerRecord(GameSystems.SystemDef system, String title, String romPath,
                                    String stanza, int catalogsSearched, String choice,
                                    File metadata, String similarOn) {
        JSONObject record = new JSONObject();
        put(record, "removedAt", String.valueOf(System.currentTimeMillis()));
        put(record, "title", title);
        put(record, "system", system.folder);
        put(record, "collection", system.collection);
        put(record, "romPath", romPath);
        put(record, "reason", "no box art in any catalog");
        put(record, "choice", choice);
        put(record, "romDeleted", String.valueOf(CHOICE_DELETE.equals(choice)));
        if (catalogsSearched > 0)
            put(record, "catalogsSearched", String.valueOf(catalogsSearched));
        if (similarOn != null && !similarOn.isEmpty()) put(record, "similarEntryOn", similarOn);
        if (metadata != null) put(record, "metadataFile", metadata.getAbsolutePath());
        // Verbatim, so a removal can be pasted straight back into the metafile.
        put(record, "stanza", stanza);
        return record;
    }

    private static void put(JSONObject target, String key, String value) {
        try { target.put(key, value); } catch (Exception ignored) {}
    }

    private static JSONArray readLedger(File mediaRoot) {
        try {
            File file = new File(mediaRoot, ARTLESS_LEDGER);
            return file.isFile() ? new JSONArray(readText(file)) : new JSONArray();
        } catch (Exception ignored) {
            return new JSONArray();
        }
    }

    /**
     * Archives the registry row owning one ROM, if there is one. Archived rows
     * stay in the registry, are excluded from generated metadata, and the
     * frontend's archive list can put them back.
     */
    private boolean archiveRegistryRow(String romPath) {
        if (romPath == null || romPath.isEmpty()) return false;
        JSONArray registry = readRegistry();
        boolean changed = false;
        for (int index = 0; index < registry.length(); index++) {
            JSONObject row = registry.optJSONObject(index);
            if (row == null || !romPath.equals(row.optString("file"))) continue;
            try {
                row.put("archived", true);
                row.put("archiveReason", "no-box-art-in-any-catalog");
                row.put("forceInclude", false);
                changed = true;
            } catch (Exception ignored) {}
            break;
        }
        if (!changed) return false;
        try {
            writeJsonAtomic(REGISTRY, registry);
            return true;
        } catch (Exception error) {
            Log.w(TAG, "Unable to archive the registry row for " + romPath, error);
            return false;
        }
    }

    /** Drops removed ROM paths from a collection stanza's {@code files:} list. */
    private static String removeFileEntries(String stanza, List<String> romPaths) {
        if (romPaths.isEmpty() || !stanza.startsWith("collection:")) return stanza;
        StringBuilder out = new StringBuilder();
        for (String line : stanza.split("\\n")) {
            if (romPaths.contains(line.trim())) continue;
            if (out.length() > 0) out.append('\n');
            out.append(line);
        }
        return out.toString();
    }

    private String canonicalTitle(GameSystems.SystemDef system, String title, File cacheRoot) {
        try {
            CatalogMatch match = boxArtMatch(system, title, cacheRoot);
            if (match == null) return "";
            String canonical = cleanTitle(match.title);
            String source = cleanTitle(title);
            // Catalogs occasionally expose a ROM-dat filename rather than a
            // display title. Keep the source title's punctuation when both
            // identities match exactly and only the catalog added dump tags.
            if (looksLikeDumpTitle(match.title) &&
                    normalize(source).equals(normalize(canonical))) return source;
            return canonical;
        } catch (Exception ignored) {
            return "";
        }
    }

    private VideoMatch videoMatch(GameSystems.SystemDef system, String title, File cacheRoot)
            throws Exception {
        File cache = new File(cacheRoot, "archive-" + system.folder + ".json");
        String json = cachedText(cache, "https://archive.org/metadata/" + system.videoArchive,
                30L * 24L * 60L * 60L * 1000L, 96L * 1024L * 1024L);
        JSONObject root = new JSONObject(json);
        JSONArray files = root.optJSONArray("files");
        if (files == null) return null;
        Set<String> aliases = mediaAliases(title);
        String selected = null;
        for (int i = 0; i < files.length(); i++) {
            JSONObject item = files.optJSONObject(i);
            String name = item == null ? "" : item.optString("name", "");
            if (!name.toLowerCase(Locale.US).endsWith(".mp4") ||
                    name.toLowerCase(Locale.US).endsWith(".ia.mp4")) continue;
            String candidate = normalize(stem(name));
            String compact = scoreAlias(candidate);
            String articleless = candidate.replaceAll("\\b(?:the|a|an)\\b", " ")
                    .replaceAll("\\s+", " ").trim();
            // EmuMovies-style archive filenames commonly append a packed
            // region/disc marker (for example TonyHawksProSkater3usa.mp4).
            String withoutArchiveSuffix = compact.replaceFirst(
                    "(?:usa|us|world|europe|eu|japan)(?:disc[0-9]+)?$", "");
            if (aliases.contains(candidate) || aliases.contains(compact) ||
                    aliases.contains(articleless) || aliases.contains(scoreAlias(articleless)) ||
                    aliases.contains(withoutArchiveSuffix)) {
                if (selected == null || regionRank(name) < regionRank(selected)) selected = name;
            }
        }
        if (selected == null) return null;
        String base;
        if (!root.optString("d1").isEmpty() && !root.optString("dir").isEmpty())
            base = "https://" + root.optString("d1") + root.optString("dir") + "/";
        else base = "https://archive.org/download/" + system.videoArchive + "/";
        return new VideoMatch(base + encodeHref(selected));
    }

    /**
     * Nintendo's own product pages provide an exact cover, full-width gallery
     * images, and MP4 gallery videos. This is both more accurate and more
     * resilient for Switch than treating a single community archive as the
     * entire catalog. A page is accepted only when its title matches the ROM.
     */
    private NintendoMedia nintendoMedia(GameSystems.SystemDef system, String title, File cacheRoot) {
        if (system == null || !"switch".equals(system.folder)) return null;
        String slug = nintendoSlug(title);
        if (slug.isEmpty()) return null;
        try {
            File cache = new File(cacheRoot, "nintendo/" + slug + ".html");
            String html = cachedText(cache,
                    "https://www.nintendo.com/us/store/products/" + slug + "/",
                    30L * 24L * 60L * 60L * 1000L, 4L * 1024L * 1024L);
            Matcher titleMatcher = NINTENDO_TITLE.matcher(html);
            if (!titleMatcher.find() || !nintendoTitlesEquivalent(title, titleMatcher.group(1)))
                return null;

            // The first Nintendo software asset belongs to the primary product
            // (the rest of this large page may contain many cross-sells). Its
            // NSUID lets us reject every unrelated gallery item precisely.
            Matcher productAsset = NINTENDO_PRODUCT_ASSET.matcher(html);
            if (!productAsset.find()) return null;
            String productId = productAsset.group(1);
            String coverHash = productAsset.group(2);
            String cover = "https://assets.nintendo.com/image/upload/q_auto/f_auto/" +
                    "store/software/switch/" + productId + "/" + coverHash;
            String background = "", video = "";

            String decoded = html.replace("\\\"", "\"");
            String sku = "71" + productId.substring(6);
            int productAt = decoded.indexOf("Product:{\"sku\":\"" + sku +
                    "\"}\":{\"__typename\":\"Product\"");
            if (productAt >= 0) {
                int productEnd = Math.min(decoded.length(), productAt + 250_000);
                Matcher square = NINTENDO_SQUARE_COVER.matcher(
                        decoded.substring(productAt, productEnd));
                if (square.find()) cover = jsonUnescape(square.group(1));
            }
            Matcher asset = NINTENDO_GALLERY_ASSET.matcher(decoded);
            while (asset.find()) {
                String publicId = asset.group(1);
                if (publicId.startsWith("/")) publicId = publicId.substring(1);
                if (!publicId.contains("/" + productId + "/")) continue;
                String type = asset.group(2).toLowerCase(Locale.US);
                if ("video".equals(type) && video.isEmpty())
                    video = "https://assets.nintendo.com/video/upload/q_auto/f_auto/" +
                            publicId + ".mp4";
                else if ("image".equals(type) && background.isEmpty() &&
                        !publicId.endsWith("/" + coverHash))
                    background = "https://assets.nintendo.com/image/upload/q_auto:best/f_auto/" +
                            publicId;
            }
            if (cover.isEmpty() && background.isEmpty() && video.isEmpty()) return null;
            return new NintendoMedia(cover, background, video);
        } catch (Exception error) {
            Log.w(TAG, "Official Nintendo media unavailable for " + title, error);
            return null;
        }
    }

    private VideoMatch archiveSearchVideo(GameSystems.SystemDef system, String title, File cacheRoot) {
        try {
            String queryTitle = normalize(title);
            String query = "title:(\"" + queryTitle + "\") AND mediatype:(movies)";
            String url = "https://archive.org/advancedsearch.php?q=" +
                    URLEncoder.encode(query, "UTF-8") +
                    "&fl%5B%5D=identifier&fl%5B%5D=title&rows=75&page=1&output=json";
            File cache = new File(cacheRoot, "archive-search-v4/" + system.folder + "/" +
                    sha1(normalize(title)) + ".json");
            JSONObject root = new JSONObject(cachedText(cache, url,
                    14L * 24L * 60L * 60L * 1000L, 4L * 1024L * 1024L));
            JSONObject response = root.optJSONObject("response");
            JSONArray docs = response == null ? null : response.optJSONArray("docs");
            if (docs == null) return null;
            List<JSONObject> ranked = new ArrayList<>();
            for (int i = 0; i < docs.length(); i++) {
                JSONObject doc = docs.optJSONObject(i);
                if (doc != null) ranked.add(doc);
            }
            ranked.sort((left, right) -> Integer.compare(
                    archiveCandidateScore(title, system,
                            right.optString("title") + " " + right.optString("identifier")),
                    archiveCandidateScore(title, system,
                            left.optString("title") + " " + left.optString("identifier"))));
            // A high-scoring Archive item can still contain no usable MP4 (or
            // only a multi-gigabyte longplay). Keep trying the remaining exact
            // candidates instead of treating that first dead end as final.
            for (JSONObject candidate : ranked) {
                int score = archiveCandidateScore(title, system,
                        candidate.optString("title") + " " + candidate.optString("identifier"));
                if (score < 90) break;
                VideoMatch match = archiveItemVideo(candidate.optString("identifier"),
                        title, system, cacheRoot);
                if (match != null) return match;
            }
            return null;
        } catch (Exception error) {
            Log.w(TAG, "Archive fallback unavailable for " + title, error);
            return null;
        }
    }

    private VideoMatch archiveItemVideo(String identifier, String title,
                                       GameSystems.SystemDef system, File cacheRoot) throws Exception {
        if (identifier == null || identifier.isEmpty()) return null;
        File metadataCache = new File(cacheRoot, "archive-items/" + sha1(identifier) + ".json");
        JSONObject metadata = new JSONObject(cachedText(metadataCache,
                "https://archive.org/metadata/" + encodePath(identifier),
                30L * 24L * 60L * 60L * 1000L, 16L * 1024L * 1024L));
        JSONArray files = metadata.optJSONArray("files");
        if (files == null) return null;
        String selected = "";
        int selectedQuality = Integer.MIN_VALUE;
        for (int i = 0; i < files.length(); i++) {
            JSONObject file = files.optJSONObject(i);
            String name = file == null ? "" : file.optString("name");
            String lower = name.toLowerCase(Locale.US);
            if (!lower.endsWith(".mp4") || lower.contains("sample") ||
                    lower.contains("thumb") || lower.contains("spectrogram")) continue;
            // An Archive item can bundle trailers for several unrelated
            // games, even when the item title matches perfectly. Validate
            // the actual file before preferring its resolution or size.
            if (archiveCandidateScore(title, system, name) < 90) continue;
            long size = parseLong(file.optString("size"));
            if (size > 0 && (size < 256L * 1024L || size > 192L * 1024L * 1024L)) continue;
            String format = file.optString("format").toLowerCase(Locale.US);
            int quality = 0;
            if (lower.contains("720") || lower.contains("1080")) quality += 25;
            if (format.contains("h.264") || format.contains("mpeg4")) quality += 20;
            if (lower.contains("512kb")) quality += 8;
            if (lower.endsWith(".ia.mp4")) quality -= 5;
            if (size > 0) quality += Math.min(20, (int)(size / (8L * 1024L * 1024L)));
            if (quality > selectedQuality) { selectedQuality = quality; selected = name; }
        }
        if (selected.isEmpty()) return null;
        return new VideoMatch("https://archive.org/download/" + encodePath(identifier) + "/" +
                encodeHref(selected));
    }

    private boolean writeMetadata(JSONArray registry) throws Exception {
        // Generated metadata is rebuilt frequently (startup, media repair, and
        // imports). Older builds treated the registry as the only source of
        // truth and silently discarded exact historical enrichment that had
        // subsequently been added to the Pegasus metafiles. Hydrate missing
        // registry fields from the current stanza with the same canonical ROM
        // path before rendering. The ROM path is deliberately the only join
        // key: similarly named regional releases must never borrow metadata.
        boolean registryChanged = hydrateRegistryFromExistingMetadata(registry);
        registryChanged |= refreshWallpaperAccents(registry);
        for (int i = 0; i < registry.length(); i++) {
            JSONObject row = registry.optJSONObject(i);
            if (row == null || row.optLong("addedAt", 0L) > 0L) continue;
            File rom = new File(row.optString("file"));
            long addedAt = rom.isFile() && rom.lastModified() > 0L ?
                    rom.lastModified() : System.currentTimeMillis();
            row.put("addedAt", addedAt);
            registryChanged = true;
        }
        if (registryChanged)
            writeJsonAtomic(REGISTRY, registry);
        Map<String, LinkedHashMap<String, JSONObject>> groups = new LinkedHashMap<>();
        for (int i = 0; i < registry.length(); i++) {
            JSONObject row = registry.optJSONObject(i);
            if (row == null || !new File(row.optString("file")).isFile()) continue;
            if (row.optBoolean("archived", false) &&
                    !row.optBoolean("forceInclude", false)) continue;
            String folder = row.optString("system");
            String identity = dedupeGameIdentity(row.optString("title"));
            LinkedHashMap<String, JSONObject> games = groups.computeIfAbsent(
                    folder, key -> new LinkedHashMap<>());
            JSONObject previous = games.get(identity);
            if (previous == null || metadataQuality(row) > metadataQuality(previous))
                games.put(identity, row);
        }
        boolean metadataChanged = false;
        Set<String> activeGeneratedFiles = new HashSet<>();
        for (Map.Entry<String, LinkedHashMap<String, JSONObject>> group : groups.entrySet()) {
            GameSystems.SystemDef system = GameSystems.byFolder(group.getKey());
            if (system == null) continue;
            List<JSONObject> games = new ArrayList<>(group.getValue().values());
            games.sort(Comparator.comparing(value -> value.optString("title"),
                    String.CASE_INSENSITIVE_ORDER));
            StringBuilder out = new StringBuilder(
                    "# Generated atomically by Lucent Library Importer.\n");
            // The owner's library intentionally groups the lone PC Engine CD
            // title with Windows instead of exposing a one-game platform card.
            String displayCollection = "pcenginecd".equals(system.folder) ?
                    "Microsoft Windows" : system.collection;
            out.append("\ncollection: ").append(displayCollection).append('\n');
            out.append("shortname: ").append(system.folder).append('\n');
            String launch = launchCommand(system.folder);
            if (!launch.isEmpty()) out.append("launch: ").append(launch).append('\n');
            out.append("files:\n");
            for (JSONObject row : games)
                out.append("  ").append(metadataSafe(row.optString("file"))).append('\n');
            for (JSONObject row : games) {
                String displayTitle = cleanTitle(row.optString("title"));
                out.append("\ngame: ").append(metadataSafe(displayTitle)).append('\n');
                double userScore = row.optDouble("user", 0);
                int userKey = userScore > 0 ? Math.max(0, 10000 - (int)Math.round(userScore * 1000)) : 99999;
                out.append("sort-by: ").append(String.format(Locale.US, "%05d", userKey))
                        .append(' ').append(metadataSafe(displayTitle.toLowerCase(Locale.US)))
                        .append('\n');
                int criticScore = row.optInt("critic", 0);
                if (criticScore > 0)
                    out.append("rating: ").append(String.format(Locale.US, "%.4f", criticScore / 100.0))
                            .append('\n');
                else
                    out.append("rating: 0%\n");
                out.append("file: ").append(metadataSafe(row.optString("file"))).append('\n');
                out.append("x-lucent-id: ")
                        .append(metadataSafe(row.optString("sourceIdentity"))).append('\n');
                out.append("x-added-at: ").append(row.optLong("addedAt", 0L)).append('\n');
                appendMetadataList(out, "developer", row.optJSONArray("developers"));
                appendMetadataList(out, "publisher", row.optJSONArray("publishers"));
                if (userScore > 0) {
                    out.append("x-user-score: ").append(format(userScore)).append('\n');
                    out.append("x-user-composite: ").append(format(userScore)).append('\n');
                    double metacriticUser = row.optDouble("metacriticUser", 0);
                    double gamefaqsUser = row.optDouble("gamefaqsUser", 0);
                    if (metacriticUser > 0)
                        out.append("x-metacritic-user: ").append(format(metacriticUser)).append('\n');
                    if (gamefaqsUser > 0) {
                        out.append("x-gamefaqs-user: ").append(format(gamefaqsUser)).append('\n');
                        if (!row.optString("gamefaqsUrl").isEmpty())
                            out.append("x-gamefaqs-url: ")
                                    .append(metadataSafe(row.optString("gamefaqsUrl"))).append('\n');
                    }
                    String preservedUserSources = row.optString("userSources");
                    if (!preservedUserSources.isEmpty())
                        out.append("x-user-sources: ").append(metadataSafe(preservedUserSources)).append('\n');
                    else if (metacriticUser > 0)
                        out.append("x-user-sources: Metacritic users=")
                                .append(format(metacriticUser)).append('\n');
                }
                if (criticScore > 0) {
                    double normalizedCritic = criticScore / 10.0;
                    out.append("x-critic: ").append(format(normalizedCritic)).append('\n');
                    out.append("x-critic-composite: ").append(format(normalizedCritic)).append('\n');
                    List<String> criticSources = new ArrayList<>();
                    int metacriticCritic = row.optInt("metacriticCritic", 0);
                    if (metacriticCritic > 0) {
                        int reviews = row.optInt("metacriticReviews", 0);
                        out.append("x-metacritic-critic: ").append(metacriticCritic).append('\n');
                        if (reviews > 0)
                            out.append("x-metacritic-reviews: ").append(reviews).append('\n');
                        criticSources.add("Metacritic=" + format(metacriticCritic / 10.0) +
                                (reviews > 0 ? " (n=" + reviews + ")" : ""));
                    }
                    if (row.optDouble("gamerankingsScore", 0) > 0) {
                        out.append("x-gamerankings-score: ")
                                .append(formatScore(row.optDouble("gamerankingsScore"))).append('\n');
                        out.append("x-gamerankings-reviews: ")
                                .append(row.optInt("gamerankingsReviews")).append('\n');
                        if (!row.optString("gamerankingsUrl").isEmpty())
                            out.append("x-gamerankings-url: ")
                                    .append(metadataSafe(row.optString("gamerankingsUrl"))).append('\n');
                        out.append("x-gamerankings-snapshot: 2019-12-08\n");
                        criticSources.add("GameRankings=" +
                                format(row.optDouble("gamerankingsScore") / 10.0) +
                                " (n=" + row.optInt("gamerankingsReviews") + ")");
                    }
                    if (row.optDouble("mobygamesScore", 0) > 0) {
                        out.append("x-mobygames-critic: ")
                                .append(format(row.optDouble("mobygamesScore") / 10.0)).append('\n');
                        out.append("x-mobygames-critic-count-min: 5\n");
                        if (!row.optString("mobygamesUrl").isEmpty())
                            out.append("x-mobygames-url: ")
                                    .append(metadataSafe(row.optString("mobygamesUrl"))).append('\n');
                        criticSources.add("MobyGames=" +
                                format(row.optDouble("mobygamesScore") / 10.0) + " (n=5 min)");
                    }
                    out.append("x-score-source: weighted composite\n");
                    String preservedCriticSources = row.optString("criticSources");
                    out.append("x-critic-sources: ")
                            .append(criticSources.isEmpty() && !preservedCriticSources.isEmpty() ?
                                    metadataSafe(preservedCriticSources) : join(criticSources, " | "))
                            .append('\n');
                }
                if (!row.optString("release").isEmpty())
                    out.append("release: ").append(metadataSafe(row.optString("release"))).append('\n');
                if (!row.optString("metacriticSlug").isEmpty())
                    out.append("x-metacritic-url: https://www.metacritic.com/game/")
                            .append(row.optString("metacriticSlug")).append("/\n");
                if (row.optInt("cheats", 0) > 0)
                    out.append("x-lucent-cheats: ").append(row.optInt("cheats", 0)).append('\n');
                if (!row.optString("boxArt").isEmpty())
                    out.append("assets.boxFront: ").append(metadataSafe(row.optString("boxArt"))).append('\n');
                if (!row.optString("background").isEmpty())
                    out.append("assets.background: ").append(metadataSafe(row.optString("background"))).append('\n');
                if (!row.optString("backgroundSource").isEmpty())
                    out.append("x-background-source: ")
                            .append(metadataSafe(row.optString("backgroundSource"))).append('\n');
                if (!row.optString("backgroundSourceUrl").isEmpty())
                    out.append("x-background-source-url: ")
                            .append(metadataSafe(row.optString("backgroundSourceUrl"))).append('\n');
                if (!row.optString("backgroundTransform").isEmpty())
                    out.append("x-background-transform: ")
                            .append(metadataSafe(row.optString("backgroundTransform"))).append('\n');
                // Precomputed "by wallpaper" accent. The theme reads it as
                // game.extra["lucent-accent"] and never derives a color itself.
                String accent = WallpaperAccent.sanitize(
                        row.optString(WallpaperAccent.REGISTRY_FIELD));
                if (!accent.isEmpty())
                    out.append(WallpaperAccent.METADATA_FIELD).append(": ")
                            .append(accent).append('\n');
                if (!row.optString("video").isEmpty())
                    out.append("assets.video: ").append(metadataSafe(row.optString("video"))).append('\n');
            }
            String generatedName = "99-lucent-auto-" + system.folder +
                    ".metadata.pegasus.txt";
            activeGeneratedFiles.add(generatedName);
            metadataChanged |= writeGeneratedMetadataIfChanged(
                    new File(LUCENT_AUTO_METADATA.getParentFile(), generatedName),
                    out.toString());
            writeCompatibilityMirror(new File(AUTO_METADATA.getParentFile(), generatedName),
                    out.toString());
        }
        cleanupGeneratedMetadata(AUTO_METADATA.getParentFile(), activeGeneratedFiles);
        metadataChanged |= cleanupGeneratedMetadata(
                LUCENT_AUTO_METADATA.getParentFile(), activeGeneratedFiles);
        // Both Android package variants have their own canonical `metafiles`
        // directory. Early builds also mirrored the same generated files into
        // the shared Pegasus root, so each ROM was parsed twice and the second
        // pass emitted ownership conflicts. Remove those redundant mirrors.
        metadataChanged |= cleanupGeneratedMetadata(PEGASUS, Collections.emptySet());
        // A Pegasus metafile represents one collection. Older EmuFusion builds
        // placed several collection headers in this combined file, causing
        // every imported game to appear in every system. Leave a harmless
        // marker at the old path while the per-system files above own games.
        String retired = "# Retired combined Lucent metadata; per-system files are authoritative.\n";
        metadataChanged |= writeGeneratedMetadataIfChanged(LUCENT_AUTO_METADATA, retired);
        writeCompatibilityMirror(AUTO_METADATA, retired);
        metadataChanged |= writeGeneratedMetadataIfChanged(LEGACY_AUTO_METADATA, retired);
        return metadataChanged;
    }

    private static boolean writeGeneratedMetadataIfChanged(File target, String value)
            throws Exception {
        if (target.isFile() && value.equals(readText(target))) return false;
        writeTextAtomic(target, value);
        return true;
    }

    /**
     * Precompute the "by wallpaper" accent for every registry row whose
     * wallpaper has not been evaluated yet.
     *
     * The accent is keyed by the wallpaper path it was derived from, so a
     * library update decodes an image exactly once: later scans, renames, and
     * deletions all fall straight through. Selecting a game in the theme must
     * never cost image work, so nothing here is deferred to browse time.
     */
    private static boolean refreshWallpaperAccents(JSONArray registry) {
        boolean changed = false;
        for (int index = 0; index < registry.length(); index++) {
            JSONObject row = registry.optJSONObject(index);
            if (row == null) continue;
            String background = row.optString("background");
            String key = accentSourceKey(background);
            // The recorded source, not the accent, is the "already evaluated"
            // marker: a greyscale wallpaper legitimately resolves to nothing
            // and must not be decoded again on every later scan.
            if (row.has(WallpaperAccent.REGISTRY_SOURCE_FIELD) &&
                    key.equals(row.optString(WallpaperAccent.REGISTRY_SOURCE_FIELD)))
                continue;
            try {
                row.put(WallpaperAccent.REGISTRY_FIELD, wallpaperAccent(background));
                row.put(WallpaperAccent.REGISTRY_SOURCE_FIELD, key);
                changed = true;
            } catch (Exception ignored) {}
        }
        return changed;
    }

    private static boolean hydrateRegistryFromExistingMetadata(JSONArray registry) {
        Map<String, String> stanzaByPath = new HashMap<>();
        Set<String> registryPaths = new HashSet<>();
        for (int index = 0; index < registry.length(); index++) {
            JSONObject row = registry.optJSONObject(index);
            if (row != null && !row.optString("file").isEmpty())
                registryPaths.add(canonical(row.optString("file")));
        }
        boolean addedRows = false;
        for (File metadata : metadataFiles()) {
            try {
                for (String stanza : splitStanzas(readText(metadata))) {
                    String path = field(stanza, "file");
                    if (path.isEmpty()) continue;
                    String key = canonical(path);
                    String previous = stanzaByPath.get(key);
                    if (previous == null || metadataStanzaRichness(stanza) >
                            metadataStanzaRichness(previous))
                        stanzaByPath.put(key, stanza);
                }
            } catch (Exception ignored) {}
        }
        // A verified ROM may predate the registry while still having a valid
        // per-system EmuFusion metafile. Never delete that game merely because a
        // newer scan rebuilds generated files from the registry. Reconcile
        // only Lucent-owned auto metafiles; hand-authored/core collections are
        // intentionally not duplicated into the importer registry.
        for (File metadata : metadataFiles()) {
            String name = metadata.getName();
            if (!name.startsWith("99-lucent-auto-") ||
                    name.equals("99-lucent-auto-import.metadata.pegasus.txt")) continue;
            try {
                for (String stanza : splitStanzas(readText(metadata))) {
                    String path = field(stanza, "file");
                    String title = field(stanza, "game");
                    if (path.isEmpty() || title.isEmpty() || !new File(path).isFile()) continue;
                    String canonicalPath = canonical(path);
                    if (registryPaths.contains(canonicalPath)) continue;
                    GameSystems.SystemDef system = systemFromRomPath(path);
                    if (system == null) continue;
                    JSONObject row = new JSONObject();
                    row.put("sourceIdentity", field(stanza, "x-lucent-id").isEmpty() ?
                            canonicalPath + ":" + new File(path).length() :
                            field(stanza, "x-lucent-id"));
                    row.put("system", system.folder);
                    row.put("title", cleanTitle(title));
                    row.put("file", path);
                    row.put("boxArt", field(stanza, "assets.boxFront"));
                    row.put("background", field(stanza, "assets.background"));
                    row.put("backgroundSource", field(stanza, "x-background-source"));
                    row.put("backgroundSourceUrl", field(stanza, "x-background-source-url"));
                    row.put("backgroundTransform", field(stanza, "x-background-transform"));
                    row.put("video", field(stanza, "assets.video"));
                    String recoveredAccent = WallpaperAccent.sanitize(
                            field(stanza, WallpaperAccent.METADATA_FIELD));
                    if (!recoveredAccent.isEmpty()) {
                        row.put(WallpaperAccent.REGISTRY_FIELD, recoveredAccent);
                        row.put(WallpaperAccent.REGISTRY_SOURCE_FIELD,
                                accentSourceKey(field(stanza, "assets.background")));
                    }
                    row.put("enrichmentVersion", 2);
                    row.put("archived", false);
                    row.put("forceInclude", false);
                    ensureBackgroundProvenance(row);
                    registry.put(row);
                    registryPaths.add(canonicalPath);
                    addedRows = true;
                }
            } catch (Exception ignored) {}
        }
        for (int index = 0; index < registry.length(); index++) {
            JSONObject row = registry.optJSONObject(index);
            if (row == null) continue;
            String stanza = stanzaByPath.get(canonical(row.optString("file")));
            if (stanza == null) continue;
            try {
                String exactTitle = field(stanza, "game");
                if (!exactTitle.isEmpty()) row.put("title", cleanTitle(exactTitle));
                putNumericIfMissing(row, "user", field(stanza, "x-user-score"), 1.0);
                putNumericIfMissing(row, "critic", field(stanza, "x-critic"), 10.0);
                putNumericIfMissing(row, "metacriticUser", field(stanza, "x-metacritic-user"), 1.0);
                putNumericIfMissing(row, "gamefaqsUser", field(stanza, "x-gamefaqs-user"), 1.0);
                putNumericIfMissing(row, "metacriticCritic", field(stanza, "x-metacritic-critic"), 1.0);
                putNumericIfMissing(row, "gamerankingsScore", field(stanza, "x-gamerankings-score"), 10.0);
                putNumericIfMissing(row, "gamerankingsReviews", field(stanza, "x-gamerankings-reviews"), 1.0);
                putNumericIfMissing(row, "mobygamesScore", field(stanza, "x-mobygames-critic"), 10.0);
                putStringIfMissing(row, "release", field(stanza, "release"));
                putStringIfMissing(row, "gamerankingsUrl", field(stanza, "x-gamerankings-url"));
                putStringIfMissing(row, "mobygamesUrl", field(stanza, "x-mobygames-url"));
                putStringIfMissing(row, "gamefaqsUrl", field(stanza, "x-gamefaqs-url"));
                putStringIfMissing(row, "userSources", field(stanza, "x-user-sources"));
                putStringIfMissing(row, "criticSources", field(stanza, "x-critic-sources"));
                // Media repairs are applied to the exact ROM stanza after a
                // deeper provider audit. Preserve those paths just like the
                // enriched scores; otherwise a later startup scan can rebuild
                // an auto metafile from a thinner registry and erase them.
                putStringIfMissing(row, "boxArt", field(stanza, "assets.boxFront"));
                putStringIfMissing(row, "background", field(stanza, "assets.background"));
                putStringIfMissing(row, "backgroundSource", field(stanza, "x-background-source"));
                putStringIfMissing(row, "backgroundSourceUrl", field(stanza, "x-background-source-url"));
                putStringIfMissing(row, "backgroundTransform", field(stanza, "x-background-transform"));
                putStringIfMissing(row, "video", field(stanza, "assets.video"));
                // Recover a previously derived accent instead of decoding the
                // wallpaper again after a registry loss. Recording the source
                // alongside it keeps the refresh pass a no-op.
                String storedAccent = WallpaperAccent.sanitize(
                        field(stanza, WallpaperAccent.METADATA_FIELD));
                if (!storedAccent.isEmpty() &&
                        row.optString(WallpaperAccent.REGISTRY_FIELD).isEmpty()) {
                    row.put(WallpaperAccent.REGISTRY_FIELD, storedAccent);
                    row.put(WallpaperAccent.REGISTRY_SOURCE_FIELD,
                            accentSourceKey(row.optString("background")));
                }
                if (ensureBackgroundProvenance(row)) addedRows = true;
            } catch (Exception ignored) {}
        }
        return addedRows;
    }

    private static boolean ensureBackgroundProvenance(JSONObject row) {
        String background = row.optString("background");
        if (background.isEmpty() || !row.optString("backgroundSource").isEmpty()) return false;
        String source = inferBackgroundSource(background);
        try {
            row.put("backgroundSource", source);
            if ((BACKGROUND_SOURCE_SCREENSHOT.equals(source) ||
                    BACKGROUND_SOURCE_OFFICIAL.equals(source)) &&
                    row.optString("backgroundTransform").isEmpty())
                row.put("backgroundTransform", BACKGROUND_TRANSFORM);
            return true;
        } catch (Exception ignored) {
            return false;
        }
    }

    private static String inferBackgroundSource(String background) {
        String normalized = background.replace('\\', '/').toLowerCase(Locale.US);
        if (normalized.contains("/game-wallpapers-screenshot-fallback/"))
            return BACKGROUND_SOURCE_SCREENSHOT;
        if (normalized.contains("/game-wallpapers-official-gallery/"))
            return BACKGROUND_SOURCE_OFFICIAL;
        if (normalized.contains("/game-wallpapers-launchbox-fanart/"))
            return BACKGROUND_SOURCE_LAUNCHBOX;
        if (normalized.contains("/game-wallpapers/"))
            return BACKGROUND_SOURCE_WALLPAPER;
        return "unclassified-existing-background";
    }

    private static void putNumericIfMissing(JSONObject row, String key, String raw, double scale) {
        if (row.optDouble(key, 0) > 0 || raw == null || raw.trim().isEmpty()) return;
        try {
            double value = Double.parseDouble(raw.trim().replace("%", "")) * scale;
            if (value > 0) row.put(key, value);
        } catch (Exception ignored) {}
    }

    private static void putStringIfMissing(JSONObject row, String key, String value) {
        if (!row.optString(key).isEmpty() || value == null || value.trim().isEmpty()) return;
        try { row.put(key, value.trim()); } catch (Exception ignored) {}
    }

    private static int metadataStanzaRichness(String stanza) {
        int score = 0;
        String[] valuable = {"x-critic", "x-user-score", "release", "x-gamefaqs-user",
                "x-gamerankings-score", "x-mobygames-critic", "x-metacritic-critic",
                "assets.boxFront", "assets.background", "x-background-source",
                "x-background-source-url", "assets.video"};
        for (String name : valuable)
            if (!field(stanza, name).isEmpty()) score++;
        return score;
    }

    private static boolean cleanupGeneratedMetadata(File directory, Set<String> keep) {
        File[] files = directory.listFiles((dir, name) ->
                name.startsWith("99-lucent-auto-") &&
                        name.endsWith(".metadata.pegasus.txt") &&
                        !name.equals(AUTO_METADATA.getName()));
        if (files == null) return false;
        boolean changed = false;
        for (File file : files)
            if (!keep.contains(file.getName())) changed |= file.delete();
        return changed;
    }

    private static int metadataQuality(JSONObject value) {
        int quality = value.optInt("enrichmentVersion", 0) * 100;
        if (!value.optString("boxArt").isEmpty()) quality += 20;
        if (!value.optString("background").isEmpty()) quality += 12;
        if (!value.optString("video").isEmpty()) quality += 10;
        if (value.optInt("critic", 0) > 0) quality += 5;
        if (value.optDouble("user", 0) > 0) quality += 3;
        if (!value.optString("release").isEmpty()) quality += 2;
        return quality;
    }

    private static String dedupeGameIdentity(String title) {
        // Catalogs disagree about leading articles, ampersands, and whether a
        // subtitle separator is rendered as ':' or '&'. Those presentation
        // differences must not produce two cards for the same game. This key
        // is used only inside one platform; launch paths remain untouched.
        String relaxed = normalize(title)
                .replaceAll("\\b(?:the|a|an|and)\\b", " ")
                .replaceAll("\\s+", " ").trim();
        return scoreAlias(relaxed);
    }

    private String launchCommand(String system) {
        // EngineRouteStore is the single source of truth: internal by default
        // where a bundled engine exists, external as a per-system user choice or
        // automatically for a system with no internal engine. It fails closed
        // (returns "") only when neither an internal engine nor any supported
        // external emulator exists for the system.
        return EngineRouteStore.launchCommand(context, system);
    }

    /**
     * Re-emits every system's collection launch command after a route change.
     * Fresh metadata is regenerated from the registry (picking up the new route
     * via {@link #launchCommand}) and any on-disk metadata is normalized, then a
     * library reload is requested so Pegasus reads the new {@code launch:} lines.
     */
    synchronized boolean rewriteLaunchRoutes() {
        try {
            JSONArray registry = readRegistry();
            writeMetadata(registry);
            LaunchMetadataRouter.normalize(context);
            requestLibraryReload();
            return true;
        } catch (Exception error) {
            Log.e(TAG, "Unable to rewrite launch routes after a route change", error);
            return false;
        }
    }

    /** Flags the current status so the next /import/reload refreshes EmuFusion. */
    private void requestLibraryReload() {
        synchronized (statusLock) {
            try {
                status.put("needsReload", true);
                status.put("message", "Launch route updated • refreshing EmuFusion library…");
                status.put("updatedAt", System.currentTimeMillis());
            } catch (Exception ignored) {}
        }
    }

    private boolean installed(String packageName) {
        try {
            context.getPackageManager().getPackageInfo(packageName, 0);
            return true;
        } catch (Exception ignored) {
            return false;
        }
    }

    private static void appendMetadataList(StringBuilder out, String field, JSONArray values) {
        if (values == null) return;
        Set<String> seen = new HashSet<>();
        for (int i = 0; i < values.length(); i++) {
            String value = values.optString(i, "").trim();
            String identity = normalizeCompany(value);
            if (value.isEmpty() || identity.isEmpty() || !seen.add(identity)) continue;
            // Pegasus explicitly permits developer/publisher fields to appear
            // multiple times. Keep one company per field so legal commas in
            // names such as "Tecmo Co., Ltd." are never split incorrectly.
            out.append(field).append(": ").append(metadataSafe(value)).append('\n');
        }
    }

    private static GameSystems.SystemDef identify(File file, String extension) {
        try {
            String ext = extension.toLowerCase(Locale.US);
            GameSystems.SystemDef pathMatch = GameSystems.byPath(file);
            if (pathMatch != null) return pathMatch;
            long size = file.length();
            if (size < 32) return null;
            byte[] head = readRange(file, 0, 0x200);
            if ("nes".equals(ext) && starts(head, new byte[]{0x4e,0x45,0x53,0x1a})) return GameSystems.byFolder("nes");
            if (("unf".equals(ext) || "unif".equals(ext)) && starts(head, "UNIF".getBytes())) return GameSystems.byFolder("nes");
            if ("fds".equals(ext) && (starts(head, new byte[]{0x46,0x44,0x53,0x1a}) || size % 65500 == 0)) return GameSystems.byFolder("nes");
            if (("gb".equals(ext) || "gbc".equals(ext)) && matchesAt(head, 0x104, GB_LOGO)) {
                int cgb = head.length > 0x143 ? head[0x143] & 0xff : 0;
                return ("gbc".equals(ext) || cgb == 0x80 || cgb == 0xc0) ?
                        GameSystems.byFolder("gbc") : GameSystems.byFolder("gb");
            }
            if ("gba".equals(ext) && matchesAt(head, 0x04,
                    new byte[]{0x24,(byte)0xff,(byte)0xae,0x51,0x69,(byte)0x9a,(byte)0xa2,0x21}))
                return GameSystems.byFolder("gba");
            if ("nds".equals(ext) && size >= 0x4000 && printable(head, 0x0c, 4)) return GameSystems.byFolder("nds");
            if (("z64".equals(ext) || "n64".equals(ext) || "v64".equals(ext)) && n64Magic(head)) return GameSystems.byFolder("n64");
            if (("gen".equals(ext) || "md".equals(ext) || "bin".equals(ext)) && containsAt(head, 0x100, "SEGA")) return GameSystems.byFolder("megadrive");
            if ("gg".equals(ext) && gameGearMagic(file)) return GameSystems.byFolder("gamegear");
            if (("sfc".equals(ext) || "smc".equals(ext) || "fig".equals(ext)) && validSnes(file)) return GameSystems.byFolder("snes");
            if ("xci".equals(ext) && containsAt(readRange(file, 0x100, 0x20), 0, "HEAD")) return GameSystems.byFolder("switch");
            if ("nsp".equals(ext) && starts(head, "PFS0".getBytes())) return GameSystems.byFolder("switch");
            if (("3ds".equals(ext) || "cci".equals(ext)) && containsAt(head, 0x100, "NCSD")) return GameSystems.byFolder("n3ds");
            if ("cia".equals(ext) && little32(head, 0) >= 0x2020 && little32(head, 0) < 0x10000) return GameSystems.byFolder("n3ds");
            if ("vpk".equals(ext) && validVitaPackage(file)) return GameSystems.byFolder("psvita");
            if ("pbp".equals(ext) && starts(head, new byte[]{0x00,0x50,0x42,0x50})) return GameSystems.byFolder("psp");
            if ("cso".equals(ext) && starts(head, "CISO".getBytes())) return GameSystems.byFolder("psp");
            if ("wbfs".equals(ext) && starts(head, "WBFS".getBytes())) return GameSystems.byFolder("wii");
            if ("rvz".equals(ext) && starts(head, "RVZ".getBytes())) {
                byte[] id = readRange(file, 88, 6);
                if (id.length == 6 && id[0] == 'G') return GameSystems.byFolder("gc");
                if (id.length == 6 && (id[0] == 'R' || id[0] == 'S'))
                    return GameSystems.byFolder("wii");
            }
            if ("wux".equals(ext) && starts(head, "WUX0".getBytes())) return GameSystems.byFolder("wiiu");
            if ("wua".equals(ext) && (starts(head, "WUA".getBytes()) || starts(head, "ZSTD".getBytes()))) return GameSystems.byFolder("wiiu");
            if ("iso".equals(ext)) return identifyIso(file);
            return null;
        } catch (Exception ignored) {
            return null;
        }
    }

    private static GameSystems.SystemDef identifyIso(File file) throws Exception {
        byte[] head = readRange(file, 0, 4 * 1024 * 1024);
        if (containsAt(head, 0x18, new byte[]{0x5d,0x1c,(byte)0x9e,(byte)0xa3})) return GameSystems.byFolder("wii");
        if (containsAt(head, 0x1c, new byte[]{(byte)0xc2,0x33,(byte)0x9f,0x3d})) return GameSystems.byFolder("gc");
        String text = new String(head, StandardCharsets.ISO_8859_1);
        if (text.contains("PS3_GAME")) return GameSystems.byFolder("ps3");
        if (text.contains("PSP_GAME")) return GameSystems.byFolder("psp");
        if (text.contains("BOOT2") && text.contains("SYSTEM.CNF")) return GameSystems.byFolder("ps2");
        return null;
    }

    private static boolean validVitaPackage(File file) {
        try (ZipFile zip = new ZipFile(file)) {
            return zip.getEntry("sce_sys/param.sfo") != null;
        } catch (Exception ignored) { return false; }
    }

    private static boolean validSnes(File file) throws Exception {
        long size = file.length();
        if (size < 0x8000 || size > 16L * 1024L * 1024L) return false;
        int copier = size % 0x8000 == 512 ? 512 : 0;
        for (int offset : new int[]{0x7fc0 + copier, 0xffc0 + copier, 0x40ffc0 + copier}) {
            if (offset + 32 > size) continue;
            byte[] header = readRange(file, offset, 32);
            int complement = little16(header, 0x1c);
            int checksum = little16(header, 0x1e);
            if ((complement ^ checksum) == 0xffff && printableRatio(header, 0, 21) > 0.70) return true;
        }
        return false;
    }

    private static boolean gameGearMagic(File file) throws Exception {
        for (int offset : new int[]{0x1ff0, 0x3ff0, 0x7ff0}) {
            if (file.length() >= offset + 8 && containsAt(readRange(file, offset, 8), 0, "TMR SEGA")) return true;
        }
        return false;
    }

    private static File mediaRoot() {
        File storage = new File("/storage");
        File[] roots = storage.listFiles();
        if (roots != null) {
            for (File root : roots) {
                if (!root.isDirectory() || root.getName().equals("emulated") || root.getName().equals("self")) continue;
                File media = new File(root, "PegasusMedia");
                if ((media.isDirectory() || media.mkdirs()) && writable(media)) return media;
            }
        }
        File fallback = new File(Environment.getExternalStorageDirectory(), "PegasusMedia");
        fallback.mkdirs();
        return fallback;
    }

    private static JSONArray readRegistry() {
        try {
            if (!REGISTRY.isFile()) return new JSONArray();
            return new JSONArray(readText(REGISTRY));
        } catch (Exception ignored) { return new JSONArray(); }
    }

    private static void writeBackgroundProvenanceManifest(JSONArray registry, File mediaRoot) {
        LinkedHashMap<String, JSONObject> byRomPath = new LinkedHashMap<>();
        try {
            for (int index = 0; index < registry.length(); index++) {
                JSONObject row = registry.optJSONObject(index);
                if (row == null || row.optString("background").isEmpty()) continue;
                ensureBackgroundProvenance(row);
                putBackgroundProvenance(byRomPath, row.optString("file"),
                        row.optString("system"), row.optString("title"),
                        row.optString("background"), row.optString("backgroundSource"),
                        row.optString("backgroundSourceUrl"),
                        row.optString("backgroundTransform"));
            }
            // Include hand-authored/core collection metadata too. Registry
            // rows cover automatic imports, while Pegasus metafiles are the
            // final source of truth for the owner's entire collection.
            for (File metadata : metadataFiles()) {
                for (String stanza : splitStanzas(readText(metadata))) {
                    String romPath = field(stanza, "file");
                    String background = field(stanza, "assets.background");
                    if (romPath.isEmpty() || background.isEmpty()) continue;
                    GameSystems.SystemDef system = systemFromRomPath(romPath);
                    putBackgroundProvenance(byRomPath, romPath,
                            system == null ? "" : system.folder, field(stanza, "game"),
                            background, field(stanza, "x-background-source"),
                            field(stanza, "x-background-source-url"),
                            field(stanza, "x-background-transform"));
                }
            }
            JSONArray records = new JSONArray();
            for (JSONObject record : byRomPath.values()) records.put(record);
            writeJsonAtomic(new File(mediaRoot, "background-provenance.json"), records);
        } catch (Exception error) {
            Log.w(TAG, "Unable to write background provenance manifest", error);
        }
    }

    private static void putBackgroundProvenance(Map<String, JSONObject> records,
            String romPath, String system, String title, String background, String source,
            String sourceUrl, String transform) throws Exception {
        if (romPath.isEmpty() || background.isEmpty()) return;
        if (source.isEmpty()) source = inferBackgroundSource(background);
        JSONObject record = new JSONObject();
        record.put("romPath", romPath);
        record.put("system", system);
        record.put("title", cleanTitle(title));
        record.put("backgroundPath", background);
        record.put("source", source);
        record.put("sourceUrl", sourceUrl);
        record.put("transform", transform);
        record.put("filePresent", new File(background).isFile());
        records.put(canonical(romPath), record);
    }

    private static Set<String> registeredSources(JSONArray registry) {
        Set<String> result = new HashSet<>();
        for (int i = 0; i < registry.length(); i++) {
            JSONObject row = registry.optJSONObject(i);
            if (row != null) result.add(row.optString("sourceIdentity"));
        }
        return result;
    }

    private static JSONObject registeredGame(JSONArray registry, String identity) {
        for (int i = 0; i < registry.length(); i++) {
            JSONObject row = registry.optJSONObject(i);
            if (row != null && identity.equals(row.optString("sourceIdentity"))) return row;
        }
        return null;
    }

    private static JSONArray mergeRegistry(JSONArray registry, List<ImportedGame> games) {
        Map<String, JSONObject> byIdentity = new LinkedHashMap<>();
        for (int i = 0; i < registry.length(); i++) {
            JSONObject row = registry.optJSONObject(i);
            if (row != null) byIdentity.put(row.optString("sourceIdentity"), row);
        }
        for (ImportedGame game : games) {
            JSONObject row = byIdentity.get(game.sourceIdentity);
            if (row == null) row = game.toJson();
            else try { mergeObject(row, game.toJson()); } catch (Exception ignored) {}
            byIdentity.put(game.sourceIdentity, row);
        }
        JSONArray result = new JSONArray();
        for (JSONObject row : byIdentity.values()) result.put(row);
        return result;
    }

    private void setStatus(String state, double progress, String message, List<String> titles,
                           int added, boolean needsReload) {
        setDetailedStatus(state, progress, message, "", 0, 0, titles, added, needsReload);
    }

    private void setDetailedStatus(String state, double progress, String message, String detail,
                                   int current, int total, List<String> titles,
                                   int added, boolean needsReload) {
        JSONObject next = new JSONObject();
        try {
            next.put("state", state);
            next.put("progress", Math.max(0, Math.min(1, progress)));
            next.put("message", message);
            next.put("detail", detail == null ? "" : detail);
            next.put("current", Math.max(0, current));
            next.put("total", Math.max(0, total));
            next.put("titles", new JSONArray(titles));
            next.put("identified", titles.size());
            next.put("added", added);
            next.put("needsReload", needsReload);
            next.put("running", !"complete".equals(state) && !"error".equals(state) && !"idle".equals(state));
            next.put("updatedAt", System.currentTimeMillis());
        } catch (Exception ignored) {}
        synchronized (statusLock) { status = next; }
    }

    private static JSONObject idleStatus() {
        JSONObject value = new JSONObject();
        try {
            value.put("state", "idle"); value.put("progress", 0);
            value.put("message", "Library importer ready"); value.put("titles", new JSONArray());
            value.put("detail", ""); value.put("current", 0); value.put("total", 0);
            value.put("identified", 0); value.put("added", 0);
            value.put("needsReload", false); value.put("running", false);
        } catch (Exception ignored) {}
        return value;
    }

    private static final class Candidate {
        final File source;
        final String zipEntry;
        final GameSystems.SystemDef system;
        String title;
        final String identity;
        final boolean inPlace;
        Candidate(File source, String zipEntry, GameSystems.SystemDef system, String title, String identity) {
            this(source, zipEntry, system, title, identity, false);
        }
        Candidate(File source, String zipEntry, GameSystems.SystemDef system, String title,
                  String identity, boolean inPlace) {
            this.source = source; this.zipEntry = zipEntry; this.system = system;
            this.title = title; this.identity = identity; this.inPlace = inPlace;
        }
    }

    private static final class ImportedGame {
        final GameSystems.SystemDef system;
        final String sourceIdentity;
        final String title;
        final File rom;
        String boxArt = "";
        String background = "";
        String backgroundSource = "";
        String backgroundSourceUrl = "";
        String backgroundTransform = "";
        // Precomputed complementary accent and the wallpaper it came from.
        String accent = "";
        String accentSource = "";
        String video = "";
        String release = "";
        String metacriticSlug = "";
        String scoreSource = "";
        String gamerankingsUrl = "";
        String mobygamesUrl = "";
        String gamefaqsUrl = "";
        String userSources = "";
        String criticSources = "";
        final List<String> developers = new ArrayList<>();
        final List<String> publishers = new ArrayList<>();
        double user;
        double metacriticUser;
        double gamefaqsUser;
        double gamerankingsScore;
        double mobygamesScore;
        int critic;
        int metacriticCritic;
        int metacriticReviews;
        int cheats;
        int gamerankingsReviews;
        boolean archived;
        boolean enriched;
        long addedAt;
        ImportedGame(Candidate candidate, File rom) {
            this.system = candidate.system; this.sourceIdentity = candidate.identity;
            this.title = candidate.title; this.rom = rom;
            this.addedAt = System.currentTimeMillis();
        }

        private ImportedGame(GameSystems.SystemDef system, String sourceIdentity,
                             String title, File rom) {
            this.system = system; this.sourceIdentity = sourceIdentity;
            this.title = title; this.rom = rom;
            this.addedAt = rom.isFile() && rom.lastModified() > 0L ?
                    rom.lastModified() : System.currentTimeMillis();
        }

        static ImportedGame fromJson(JSONObject value) {
            GameSystems.SystemDef system = GameSystems.byFolder(value.optString("system"));
            File rom = new File(value.optString("file"));
            if (system == null || !rom.isFile()) return null;
            ImportedGame game = new ImportedGame(system,
                    value.optString("sourceIdentity"), cleanTitle(value.optString("title")), rom);
            game.boxArt = value.optString("boxArt");
            game.background = value.optString("background");
            game.backgroundSource = value.optString("backgroundSource");
            game.backgroundSourceUrl = value.optString("backgroundSourceUrl");
            game.backgroundTransform = value.optString("backgroundTransform");
            game.accent = WallpaperAccent.sanitize(
                    value.optString(WallpaperAccent.REGISTRY_FIELD));
            game.accentSource = value.optString(WallpaperAccent.REGISTRY_SOURCE_FIELD);
            game.inferBackgroundProvenance();
            game.video = value.optString("video");
            game.release = value.optString("release");
            game.metacriticSlug = value.optString("metacriticSlug");
            game.scoreSource = value.optString("scoreSource");
            game.gamerankingsUrl = value.optString("gamerankingsUrl");
            game.mobygamesUrl = value.optString("mobygamesUrl");
            game.gamefaqsUrl = value.optString("gamefaqsUrl");
            game.userSources = value.optString("userSources");
            game.criticSources = value.optString("criticSources");
            game.user = value.optDouble("user", 0);
            game.metacriticUser = value.has("metacriticUser") ?
                    value.optDouble("metacriticUser", 0) : game.user;
            game.gamefaqsUser = value.optDouble("gamefaqsUser", 0);
            game.gamerankingsScore = value.optDouble("gamerankingsScore", 0);
            game.mobygamesScore = value.optDouble("mobygamesScore", 0);
            game.critic = value.optInt("critic", 0);
            game.metacriticCritic = value.optInt("metacriticCritic", 0);
            game.metacriticReviews = value.optInt("metacriticReviews", 0);
            game.cheats = value.optInt("cheats", 0);
            game.gamerankingsReviews = value.optInt("gamerankingsReviews", 0);
            game.archived = value.optBoolean("archived", false);
            game.addedAt = value.optLong("addedAt", game.addedAt);
            game.enriched = value.optInt("enrichmentVersion", 0) >= 2;
            copyJsonStrings(value.optJSONArray("developers"), game.developers);
            copyJsonStrings(value.optJSONArray("publishers"), game.publishers);
            return game;
        }

        private static void copyJsonStrings(JSONArray values, List<String> destination) {
            if (values == null) return;
            for (int i = 0; i < values.length(); i++) {
                String value = values.optString(i, "").trim();
                if (!value.isEmpty()) destination.add(value);
            }
        }

        JSONObject toJson() {
            JSONObject value = new JSONObject();
            try {
                value.put("sourceIdentity", sourceIdentity); value.put("system", system.folder);
                value.put("title", title); value.put("file", rom.getAbsolutePath());
                value.put("addedAt", addedAt);
                value.put("boxArt", boxArt); value.put("background", background);
                value.put("backgroundSource", backgroundSource);
                value.put("backgroundSourceUrl", backgroundSourceUrl);
                value.put("backgroundTransform", backgroundTransform);
                value.put(WallpaperAccent.REGISTRY_FIELD, accent);
                value.put(WallpaperAccent.REGISTRY_SOURCE_FIELD, accentSource);
                value.put("video", video);
                value.put("user", user); value.put("critic", critic);
                value.put("metacriticUser", metacriticUser);
                value.put("gamefaqsUser", gamefaqsUser);
                value.put("release", release); value.put("metacriticSlug", metacriticSlug);
                value.put("scoreSource", scoreSource);
                value.put("userSources", userSources);
                value.put("criticSources", criticSources);
                value.put("metacriticCritic", metacriticCritic);
                value.put("metacriticReviews", metacriticReviews);
                value.put("cheats", cheats);
                value.put("gamerankingsScore", gamerankingsScore);
                value.put("gamerankingsReviews", gamerankingsReviews);
                value.put("gamerankingsUrl", gamerankingsUrl);
                value.put("mobygamesScore", mobygamesScore);
                value.put("mobygamesUrl", mobygamesUrl);
                value.put("gamefaqsUrl", gamefaqsUrl);
                value.put("enrichmentVersion", enriched ? 2 : 0);
                value.put("archived", archived);
                value.put("archiveReason", archived ? "missing-box-art" : "");
                value.put("forceInclude", false);
                value.put("developers", new JSONArray(developers));
                value.put("publishers", new JSONArray(publishers));
            } catch (Exception ignored) {}
            return value;
        }

        void inferBackgroundProvenance() {
            if (background.isEmpty() || !backgroundSource.isEmpty()) return;
            backgroundSource = inferBackgroundSource(background);
            if ((BACKGROUND_SOURCE_SCREENSHOT.equals(backgroundSource) ||
                    BACKGROUND_SOURCE_OFFICIAL.equals(backgroundSource)) &&
                    backgroundTransform.isEmpty()) backgroundTransform = BACKGROUND_TRANSFORM;
        }
    }

    private static final class CatalogMatch {
        final String url; final String title;
        CatalogMatch(String url, String title) { this.url = url; this.title = title; }
    }
    private static final class VideoMatch {
        final String url;
        VideoMatch(String url) { this.url = url; }
    }
    private static final class NintendoMedia {
        final String cover;
        final String background;
        final String video;
        NintendoMedia(String cover, String background, String video) {
            this.cover = cover == null ? "" : cover;
            this.background = background == null ? "" : background;
            this.video = video == null ? "" : video;
        }
    }
    private static final class GameRankingsRecord {
        final double score;
        final int reviews;
        final String year;
        final String id;
        final String url;
        GameRankingsRecord(double score, int reviews, String year, String id, String url) {
            this.score = score; this.reviews = reviews; this.year = year; this.id = id; this.url = url;
        }
    }
    private static final class MobyGamesRecord {
        final double score;
        final String year;
        final String developer;
        final String url;
        MobyGamesRecord(double score, String year, String developer, String url) {
            this.score = score; this.year = year; this.developer = developer; this.url = url;
        }
    }
    private static final class BundledGameRecord {
        final String title;
        final double critic;
        final double user;
        final String release;
        final String developer;
        final String publisher;
        final String criticSources;
        final String userSources;
        BundledGameRecord(String title, double critic, double user, String release,
                          String developer, String publisher, String criticSources,
                          String userSources) {
            this.title = title;
            this.critic = critic;
            this.user = user;
            this.release = release;
            this.developer = developer;
            this.publisher = publisher;
            this.criticSources = criticSources;
            this.userSources = userSources;
        }
    }

    // ----- Small, defensive IO/string helpers -----

    private static boolean isPartial(String name) {
        String lower = name.toLowerCase(Locale.US);
        return lower.endsWith(".part") || lower.endsWith(".partial") || lower.endsWith(".crdownload") ||
                lower.endsWith(".tmp") || lower.endsWith(".download");
    }
    private static String downloadFingerprint() {
        List<String> parts = new ArrayList<>();
        for (File downloadRoot : downloadRoots()) {
            File[] entries = downloadRoot.listFiles();
            if (entries == null) continue;
            for (File file : entries) {
                if (file.isFile())
                    parts.add(canonical(file.getAbsolutePath()) + ":" + file.length() +
                            ":" + file.lastModified());
            }
        }
        Collections.sort(parts);
        return sha1(parts.toString());
    }

    /** Returns the standard internal Download folder and every readable
     * removable-storage Download/Downloads folder, with canonical deduping. */
    private static List<File> downloadRoots() {
        LinkedHashMap<String, File> roots = new LinkedHashMap<>();
        addDownloadRoot(roots, DOWNLOADS);

        File[] storageRoots = new File("/storage").listFiles();
        if (storageRoots != null) {
            List<File> sorted = new ArrayList<>();
            Collections.addAll(sorted, storageRoots);
            sorted.sort(Comparator.comparing(File::getName, String.CASE_INSENSITIVE_ORDER));
            for (File storageRoot : sorted) {
                String name = storageRoot.getName();
                if (!storageRoot.isDirectory() || "emulated".equals(name) || "self".equals(name))
                    continue;
                addDownloadRoot(roots, new File(storageRoot, "Download"));
                addDownloadRoot(roots, new File(storageRoot, "Downloads"));
            }
        }
        return new ArrayList<>(roots.values());
    }

    private static void addDownloadRoot(Map<String, File> roots, File directory) {
        if (directory == null || !directory.isDirectory() || !directory.canRead()) return;
        roots.put(canonical(directory.getAbsolutePath()), directory);
    }
    private static boolean isPotentialAmbiguous(String ext) {
        return "iso".equals(ext) || "bin".equals(ext) || "rvz".equals(ext);
    }
    private static String extension(String name) {
        int query = name.indexOf('?'); if (query >= 0) name = name.substring(0, query);
        int slash = name.lastIndexOf('/');
        int dot = name.lastIndexOf('.');
        return dot < 0 || dot < slash ? "" : name.substring(dot + 1).toLowerCase(Locale.US);
    }
    private static String stem(String name) {
        int slash = Math.max(name.lastIndexOf('/'), name.lastIndexOf(File.separatorChar));
        if (slash >= 0) name = name.substring(slash + 1);
        int dot = name.lastIndexOf('.'); return dot > 0 ? name.substring(0, dot) : name;
    }
    private static String cleanTitle(String value) {
        String title = value.replaceAll("\\s*_+\\s*", ": ").trim();
        title = title.replaceAll("(?i)(?:\\s*[:\\-]\\s*)copy$", "").trim();
        // Switch dumps commonly append a 16-digit title ID and version tag.
        // They are identifiers, not part of the display title, and prevent
        // exact media/score matching if retained.
        title = title.replaceAll("(?i)[.\\s-]*[0-9a-f]{16}(?:[.\\s-]*v\\d+)?$", "")
                .replaceAll("(?i)\\s*\\[[0-9a-f]{16}\\]", "")
                .replaceAll("(?i)\\s*\\[v\\d+\\]", "")
                .replaceAll("(?i)\\s+v\\d+(?:[ .]\\d+)+$", "")
                .replaceAll("(?i)\\s+[—:-]\\s+disc\\s+\\d+(?:\\s+of\\s+\\d+)?$", "")
                .replaceAll("(?i)\\s*\\((?:USA|US|U|Europe|EU|E|Japan|JP|J|W|UE)\\b.*$", "")
                .trim();
        // Dot-separated scene/download names are filenames, not display
        // titles. Canonical catalog matching can restore legitimate internal
        // punctuation after this normalization.
        if (!title.contains(" ") && title.matches(".*[A-Za-z0-9]\\.[A-Za-z0-9].*"))
            title = title.replace('.', ' ');
        title = title.replaceFirst(
                "(?i)\\s*\\((?:19|20)[0-9x]{2}(?:[-.][0-9x]{1,2}){0,2}\\).*$", "");
        String previous;
        do {
            previous = title;
            title = title.replaceAll(
                    "(?i)\\s*[\\[(](?:USA|US|U|Europe|EU|E|Japan|JP|J|World|" +
                    "En(?:,[A-Za-z]+)*|Rev[^\\])]*|v?\\d+(?:[ .]\\d+)*|!|b|h|n|p|" +
                    "t[^\\])]*|Unl(?:icensed)?|Beta|Proto(?:type)?|Demo|" +
                    "Kiosk|Bonus Disc|Virtual Console|NTSC|PAL|" +
                    "Disc\\s+\\d+(?:\\s+of\\s+\\d+)?)[\\])]\\s*$",
                    "").trim();
        } while (!title.equals(previous));
        title = title.replaceAll("\\s+-\\s+", ": ").replaceAll("\\s+", " ").trim();
        Matcher embeddedArticle = Pattern.compile("^(.+), (The|A|An)(\\s*[:\\-].*)$",
                Pattern.CASE_INSENSITIVE).matcher(title);
        if (embeddedArticle.matches())
            title = embeddedArticle.group(2) + " " + embeddedArticle.group(1) +
                    embeddedArticle.group(3);
        Matcher article = Pattern.compile("^(.+), (The|A|An)$", Pattern.CASE_INSENSITIVE).matcher(title);
        if (article.matches()) title = article.group(2) + " " + article.group(1);
        Matcher zeldaSubtitle = Pattern.compile(
                "^(The Legend of Zelda) (Collector's Edition|Four Swords Adventures)$",
                Pattern.CASE_INSENSITIVE).matcher(title);
        if (zeldaSubtitle.matches())
            title = zeldaSubtitle.group(1) + ": " + zeldaSubtitle.group(2);
        return title.isEmpty() ? "Untitled Game" : title;
    }

    private static boolean looksLikeDumpTitle(String value) {
        return value != null && (value.matches("(?is).*\\((?:19|20)[0-9x]{2}.*") ||
                value.matches("(?is).*[\\[(](?:USA|US|U|Europe|EU|E|Japan|JP|J|World|" +
                        "Beta|Proto(?:type)?|Unl(?:icensed)?|Rev[^\\])]*|T-En[^\\])]*)" +
                        "[\\])].*"));
    }

    private static boolean isSwitchExtension(String extension) {
        return "nsp".equals(extension) || "xci".equals(extension);
    }

    private static boolean isSwitchSupplementalName(String value) {
        String normalized = value == null ? "" : value.replace('\\', '/').toLowerCase(Locale.US);
        if (normalized.matches(".*/(?:updates?|dlc|add-ons?)/.*")) return true;
        String words = normalized.replaceAll("[^a-z0-9]+", " ").trim();
        if (words.matches(".*(?:^| )(?:update|upd|dlc)(?: |$).*") ||
                words.contains("downloadable content")) return true;
        Matcher ids = Pattern.compile("(?i)([0-9a-f]{16})").matcher(value == null ? "" : value);
        while (ids.find()) {
            // Nintendo Switch update title IDs use the 0x800 program suffix.
            if (ids.group(1).toLowerCase(Locale.US).endsWith("800")) return true;
        }
        return false;
    }
    private static void addUnique(List<String> values, String value) {
        String clean = value == null ? "" : value.trim();
        String identity = normalizeCompany(clean);
        if (clean.isEmpty() || identity.isEmpty()) return;
        for (String existing : values)
            if (normalizeCompany(existing).equals(identity)) return;
        values.add(clean);
    }
    private static String normalizeCompany(String value) {
        String key = Normalizer.normalize(value == null ? "" : value, Normalizer.Form.NFKD)
                .replaceAll("\\p{M}+", "").toLowerCase(Locale.US)
                .replace("&", " and ").replaceAll("[^a-z0-9]+", " ").trim();
        for (int pass = 0; pass < 3; pass++)
            key = key.replaceAll("\\s+(incorporated|inc|corporation|corp|company|co|limited|ltd|pty|sa)$", "");
        return key;
    }
    // Title normalization and region preference are shared with the artwork
    // matcher. They live in TitleMatcher so the host tests exercise the same
    // code the device runs, rather than a copy that can drift away from it.
    private static String normalize(String value) { return TitleMatcher.normalize(value); }
    private static int regionRank(String value) { return TitleMatcher.regionRank(value); }
    private static String safeFilename(String value) {
        String clean = value.replaceAll("[\\x00-\\x1f/:*?\"<>|]", " ").replaceAll("\\s+", " ").trim();
        return clean.length() > 180 ? clean.substring(0, 180).trim() : clean;
    }
    private static String metadataSafe(String value) { return value.replace('\n', ' ').replace('\r', ' ').trim(); }
    private static String canonical(String path) { try { return new File(path).getCanonicalPath(); } catch (Exception e) { return path; } }
    private static String decode(String value) { try { return URLDecoder.decode(value, "UTF-8"); } catch (Exception e) { return value; } }
    private static String encodePath(String value) { try { return URLEncoder.encode(value, "UTF-8").replace("+", "%20"); } catch (Exception e) { return value; } }
    private static String encodeHref(String value) {
        String[] parts = value.split("/", -1); StringBuilder out = new StringBuilder();
        for (int i = 0; i < parts.length; i++) { if (i > 0) out.append('/'); out.append(encodePath(decode(parts[i]))); }
        return out.toString();
    }
    private static String sha1(String value) {
        try { MessageDigest md = MessageDigest.getInstance("SHA-1"); byte[] digest = md.digest(value.getBytes(StandardCharsets.UTF_8));
            StringBuilder out = new StringBuilder(); for (byte b : digest) out.append(String.format(Locale.US, "%02x", b)); return out.substring(0, 16);
        } catch (Exception e) { return Integer.toHexString(value.hashCode()); }
    }
    private static String format(double value) { return value == Math.rint(value) ? String.valueOf((long)value) : String.format(Locale.US, "%.1f", value); }
    private static String formatScore(double value) { String result=String.format(Locale.US,"%.2f",value); return result.replaceAll("0+$","").replaceAll("\\.$",""); }
    private static String join(List<String> values, String separator) { StringBuilder out=new StringBuilder(); for(String value:values){if(out.length()>0)out.append(separator);out.append(value);}return out.toString(); }
    private static String shortError(Throwable error) { String value = error.getMessage(); return value == null ? error.getClass().getSimpleName() : value; }

    private static byte[] readRange(File file, long offset, int length) throws Exception {
        byte[] data = new byte[length]; int total = 0;
        try (FileInputStream input = new FileInputStream(file)) {
            long skipped = 0; while (skipped < offset) { long value = input.skip(offset - skipped); if (value <= 0) break; skipped += value; }
            while (total < length) { int count = input.read(data, total, length - total); if (count < 0) break; total += count; }
        }
        if (total == data.length) return data;
        byte[] shortData = new byte[total]; System.arraycopy(data, 0, shortData, 0, total); return shortData;
    }
    private static boolean starts(byte[] data, byte[] expected) { return matchesAt(data, 0, expected); }
    private static boolean containsAt(byte[] data, int offset, String value) { return matchesAt(data, offset, value.getBytes(StandardCharsets.ISO_8859_1)); }
    private static boolean containsAt(byte[] data, int offset, byte[] value) { return matchesAt(data, offset, value); }
    private static boolean matchesAt(byte[] data, int offset, byte[] expected) {
        if (offset < 0 || offset + expected.length > data.length) return false;
        for (int i = 0; i < expected.length; i++) if (data[offset + i] != expected[i]) return false;
        return true;
    }
    private static boolean n64Magic(byte[] h) { return starts(h,new byte[]{(byte)0x80,0x37,0x12,0x40}) || starts(h,new byte[]{0x37,(byte)0x80,0x40,0x12}) || starts(h,new byte[]{0x40,0x12,0x37,(byte)0x80}); }
    private static boolean printable(byte[] data, int offset, int length) { return printableRatio(data, offset, length) > 0.75; }
    private static double printableRatio(byte[] data, int offset, int length) { if (offset + length > data.length) return 0; int count=0; for(int i=offset;i<offset+length;i++){int c=data[i]&0xff;if(c>=0x20&&c<=0x7e)count++;} return count/(double)length; }
    private static int little16(byte[] data, int offset) { return offset+1<data.length ? (data[offset]&0xff)|((data[offset+1]&0xff)<<8) : 0; }
    private static int little32(byte[] data, int offset) { return offset+3<data.length ? (data[offset]&0xff)|((data[offset+1]&0xff)<<8)|((data[offset+2]&0xff)<<16)|((data[offset+3]&0xff)<<24) : 0; }

    private static void copy(File source, File target) throws Exception {
        target.getParentFile().mkdirs();
        try (InputStream in = new BufferedInputStream(new FileInputStream(source)); OutputStream out = new BufferedOutputStream(new FileOutputStream(target))) {
            byte[] buffer = new byte[1024 * 1024]; int count; while ((count = in.read(buffer)) >= 0) out.write(buffer, 0, count);
        }
        if (target.length() != source.length()) throw new java.io.IOException("copy verification failed");
    }
    private static void extract(ZipFile zip, ZipEntry entry, File target) throws Exception {
        extract(zip, entry, target, Long.MAX_VALUE);
    }
    private static void extract(ZipFile zip, ZipEntry entry, File target, long limit)
            throws Exception {
        if (entry.getSize() > MAX_ARCHIVE_ENTRY_BYTES)
            throw new java.io.IOException("archive entry is too large");
        target.getParentFile().mkdirs();
        try (InputStream in = new BufferedInputStream(zip.getInputStream(entry)); OutputStream out = new BufferedOutputStream(new FileOutputStream(target))) {
            byte[] buffer = new byte[1024 * 1024]; int count; long total=0;
            while (total < limit && (count=in.read(buffer, 0,
                    (int)Math.min(buffer.length, limit - total)))>=0){out.write(buffer,0,count);total+=count;}
            if (limit == Long.MAX_VALUE && entry.getSize() >= 0 && total != entry.getSize())
                throw new java.io.IOException("archive extraction verification failed");
        }
    }
    private static void extract(SevenZFile sevenZ, SevenZArchiveEntry entry, File target,
                                long limit) throws Exception {
        if (entry.getSize() < 0 || entry.getSize() > MAX_ARCHIVE_ENTRY_BYTES)
            throw new java.io.IOException("archive entry has an unsafe size");
        target.getParentFile().mkdirs();
        try (OutputStream out = new BufferedOutputStream(new FileOutputStream(target))) {
            byte[] buffer = new byte[1024 * 1024]; int count; long total = 0;
            while (total < limit && (count = sevenZ.read(buffer, 0,
                    (int)Math.min(buffer.length, limit - total))) >= 0) {
                out.write(buffer, 0, count);
                total += count;
            }
            if (limit == Long.MAX_VALUE && total != entry.getSize())
                throw new java.io.IOException("7z extraction verification failed");
        }
    }
    private static void extractSevenZipEntry(File archive, String entryName, File target)
            throws Exception {
        try (SevenZFile sevenZ = new SevenZFile(archive, SEVEN_Z_OPTIONS)) {
            SevenZArchiveEntry entry;
            while ((entry = sevenZ.getNextEntry()) != null) {
                if (!entry.isDirectory() && entryName.equals(entry.getName())) {
                    extract(sevenZ, entry, target, Long.MAX_VALUE);
                    return;
                }
            }
        }
        throw new java.io.IOException("7z entry is missing");
    }
    private static boolean sameContent(File left, File right) {
        if (left.length() != right.length()) return false;
        try (InputStream a = new BufferedInputStream(new FileInputStream(left));
             InputStream b = new BufferedInputStream(new FileInputStream(right))) {
            byte[] ab = new byte[1024 * 1024], bb = new byte[1024 * 1024];
            while (true) {
                int an = a.read(ab), bn = b.read(bb);
                if (an != bn) return false;
                if (an < 0) return true;
                for (int i = 0; i < an; i++) if (ab[i] != bb[i]) return false;
            }
        } catch (Exception ignored) { return false; }
    }
    private static String readText(File file) throws Exception { StringBuilder out=new StringBuilder(); try(BufferedReader r=new BufferedReader(new FileReader(file))){String line;while((line=r.readLine())!=null)out.append(line).append('\n');} return out.toString(); }
    private static void writeTextAtomic(File target, String value) throws Exception {
        target.getParentFile().mkdirs();
        File temp = new File(target.getParentFile(), "." + target.getName() + ".writing");
        File backup = new File(target.getParentFile(), target.getName() + ".bak");
        try (FileOutputStream out = new FileOutputStream(temp)) {
            out.write(value.getBytes(StandardCharsets.UTF_8));
            out.getFD().sync();
        }
        if (backup.exists()) backup.delete();
        if (target.exists() && !target.renameTo(backup)) {
            temp.delete();
            throw new java.io.IOException("cannot back up " + target);
        }
        if (!temp.renameTo(target)) {
            if (backup.exists()) backup.renameTo(target);
            throw new java.io.IOException("cannot commit " + target);
        }
    }
    private static void writeCompatibilityMirror(File target, String value) {
        try {
            writeTextAtomic(target, value);
        } catch (Exception inaccessibleLegacyPackageDirectory) {
            // Android 11+ forbids writing another package's Android/data tree,
            // even with broad shared-storage access. The com.thorium.preview
            // metadata above is authoritative; this mirror exists only for
            // in-place migrations from the retired Pegasus package.
            Log.i(TAG, "Legacy Pegasus metadata mirror is unavailable: " + target);
        }
    }
    private static void writeJsonAtomic(File target, JSONArray value) throws Exception { writeTextAtomic(target, value.toString(2)+"\n"); }
    private static List<String> splitStanzas(String text) {
        List<String> values = new ArrayList<>();
        // Hand-authored and older generated Pegasus metadata commonly starts
        // the next game immediately after the previous asset field, without a
        // blank separator. Treat every column-zero `game:` as a record boundary
        // in addition to accepting conventional blank-line stanzas.
        for (String item : text.split("(?m)(?=^game:)|\\n\\s*\\n"))
            if (!item.trim().isEmpty()) values.add(item.trim());
        return values;
    }
    private static String joinStanzas(List<String> values) { StringBuilder out=new StringBuilder(); for(String value:values){if(out.length()>0)out.append("\n\n");out.append(value.trim());}return out.append('\n').toString(); }
    private static String field(String stanza, String key) { String prefix=key+":"; for(String line:stanza.split("\\n"))if(line.startsWith(prefix))return line.substring(prefix.length()).trim(); return ""; }
    private static String removeField(String stanza, String key) { String prefix=key+":"; StringBuilder out=new StringBuilder(); for(String line:stanza.split("\\n")){if(line.startsWith(prefix))continue;if(out.length()>0)out.append('\n');out.append(line);}return out.toString(); }
    private static GameSystems.SystemDef systemFromRomPath(String path) {
        return GameSystems.byPath(new File(path));
    }

    private static String cachedText(File cache, String url, long maxAge, long maxBytes) throws Exception {
        if (LibraryHttp.reusable(cache) && System.currentTimeMillis() - cache.lastModified() < maxAge) return readText(cache);
        byte[] bytes = fetchBytes(url, maxBytes); String value = new String(bytes, StandardCharsets.UTF_8); writeTextAtomic(cache, value); return value;
    }
    private static byte[] fetchBytes(String url, long maxBytes) throws Exception {
        return LibraryHttp.fetch(url, maxBytes);
    }
    private static boolean download(String url, File target, long maxBytes) throws Exception {
        return LibraryHttp.download(url, target, maxBytes);
    }
    private static boolean hasPlatform(JSONArray platforms, String expected) { if(platforms==null)return false; for(int i=0;i<platforms.length();i++){JSONObject p=platforms.optJSONObject(i);if(p!=null&&p.optString("name").equalsIgnoreCase(expected))return true;}return false; }
    private static boolean writable(File directory) {
        File probe = new File(directory, ".thorium-write-test");
        try { if (!probe.createNewFile()) return false; return probe.delete(); }
        catch (Exception ignored) { return false; }
    }
    private static boolean recentlyMissed(File cacheRoot, GameSystems.SystemDef system, String title) { File f=new File(cacheRoot,"misses/"+system.folder+"/"+sha1(normalize(title)));return f.isFile()&&System.currentTimeMillis()-f.lastModified()<MISS_RETRY_MS; }
    private static void recordMiss(File cacheRoot, GameSystems.SystemDef system, String title) { try { File f=new File(cacheRoot,"misses/"+system.folder+"/"+sha1(normalize(title)));f.getParentFile().mkdirs();new FileOutputStream(f).close(); } catch(Exception ignored){} }
}
