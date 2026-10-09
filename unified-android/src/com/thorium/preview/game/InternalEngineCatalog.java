package com.thorium.preview.game;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/**
 * Release gate for in-process engines.
 *
 * A registry row is intentionally insufficient on its own. EmuFusion only routes
 * a game internally when every release qualification flag is present and the
 * corresponding core is physically bundled inside the signed APK. Development
 * and license-blocked rows therefore remain unlaunchable until an internal
 * engine passes every gate.
 */
public final class InternalEngineCatalog {
    private static final String ASSET = "engine-registry.json";
    private static final String HASH_CACHE_FILE = "engine-hash-cache.json";
    // Bounds the fail-closed wait a consumer spends on background verification.
    private static final long BOOTSTRAP_WAIT_SECONDS = 30;
    private static volatile Snapshot cached;
    private static volatile Thread bootstrapThread;
    private static final CountDownLatch BOOTSTRAP_GATE = new CountDownLatch(1);
    private static final Object HASH_CACHE_LOCK = new Object();
    private static JSONObject hashCacheEntries;      // guarded by HASH_CACHE_LOCK
    private static long hashCacheInstallTime;        // guarded by HASH_CACHE_LOCK
    private static File hashCachePath;               // guarded by HASH_CACHE_LOCK

    public static final class Entry {
        public final String id;
        public final String displayName;
        public final List<String> systems;
        public final String sourceCommit;
        public final String coreArtifactSha256;
        public final int stateCompatibilityVersion;
        public final boolean firmwareRequired;
        public final List<String> acceptedFirmwareHashes;
        public final File coreFile;
        public final String renderer;
        public final boolean qualificationOnly;
        public final boolean autoSelect;

        Entry(String id, String displayName, List<String> systems, String sourceCommit,
                String coreArtifactSha256,
                int stateCompatibilityVersion, boolean firmwareRequired,
                List<String> acceptedFirmwareHashes, File coreFile,
                String renderer, boolean qualificationOnly, boolean autoSelect) {
            this.id = id;
            this.displayName = displayName;
            this.systems = Collections.unmodifiableList(new ArrayList<>(systems));
            this.sourceCommit = sourceCommit;
            this.coreArtifactSha256 = coreArtifactSha256;
            this.stateCompatibilityVersion = stateCompatibilityVersion;
            this.firmwareRequired = firmwareRequired;
            this.acceptedFirmwareHashes = Collections.unmodifiableList(
                    new ArrayList<>(acceptedFirmwareHashes));
            this.coreFile = coreFile;
            this.renderer = normalize(renderer);
            this.qualificationOnly = qualificationOnly;
            this.autoSelect = autoSelect;
        }

        public boolean supports(String systemId) {
            return systems.contains(normalize(systemId));
        }
    }

    private static final class Snapshot {
        final Map<String, Entry> byId;
        final Map<String, Entry> bySystem;
        Snapshot(Map<String, Entry> byId, Map<String, Entry> bySystem) {
            this.byId = Collections.unmodifiableMap(byId);
            this.bySystem = Collections.unmodifiableMap(bySystem);
        }
    }

    private InternalEngineCatalog() {}

    public static Entry forSystem(Context context, String systemId) {
        return snapshot(context).bySystem.get(normalize(systemId));
    }

    /**
     * Returns only a release-routable engine for normal library launches.
     * Qualification-only cores may be registered for an explicit signed QA
     * intent, but autoSelect=false must keep them out of metadata and inferred
     * routes.  Ignoring that bit would silently expose an experimental core to
     * an ordinary game launch merely because a qualification APK bundled it.
     */
    public static Entry availableForSystem(Context context, String systemId) {
        return forSystem(context, systemId);
    }

    public static Entry byId(Context context, String engineId) {
        return snapshot(context).byId.get(normalize(engineId));
    }

    public static List<Entry> approvedEntries(Context context) {
        return Collections.unmodifiableList(new ArrayList<>(snapshot(context).byId.values()));
    }

    /** Tests and package replacement can force the signed asset to be reread. */
    static void invalidate() { cached = null; }

    /** Called by the bootstrap before its verification thread starts. */
    static void expectBootstrapOn(Thread verifier) { bootstrapThread = verifier; }

    /** Called by the bootstrap once verification and registration finish. */
    static void bootstrapComplete() { BOOTSTRAP_GATE.countDown(); }

    private static Snapshot snapshot(Context context) {
        // Fail closed: consumers block until the background verification (and
        // engine registration) completes; an expired or interrupted wait yields
        // an uncached empty snapshot, never unverified entries.
        if (!bootstrapSettled())
            return new Snapshot(new LinkedHashMap<String, Entry>(),
                    new LinkedHashMap<String, Entry>());
        Snapshot result = cached;
        if (result != null) return result;
        synchronized (InternalEngineCatalog.class) {
            if (cached == null) cached = load(context.getApplicationContext());
            return cached;
        }
    }

    private static boolean bootstrapSettled() {
        Thread verifier = bootstrapThread;
        if (verifier == null || verifier == Thread.currentThread()) return true;
        try {
            return BOOTSTRAP_GATE.await(BOOTSTRAP_WAIT_SECONDS, TimeUnit.SECONDS);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            return false;
        }
    }

    private static Snapshot load(Context context) {
        LinkedHashMap<String, Entry> byId = new LinkedHashMap<>();
        LinkedHashMap<String, Entry> bySystem = new LinkedHashMap<>();
        try {
            Map<String, QualificationOptIn> optIns = loadQualificationOptIns(context);
            Map<String, ArtifactIdentity> artifacts = loadArtifactIdentities(context);
            JSONObject root = new JSONObject(readAsset(context));
            JSONArray engines = root.optJSONArray("engines");
            if (engines == null) return new Snapshot(byId, bySystem);
            for (int index = 0; index < engines.length(); index++) {
                JSONObject row = engines.optJSONObject(index);
                String id = normalize(row == null ? "" : row.optString("id"));
                Entry entry = approvedEntry(context, row, optIns.get(id), artifacts.get(id));
                if (entry == null || byId.containsKey(entry.id)) continue;
                byId.put(entry.id, entry);
                for (String system : entry.systems) if (entry.autoSelect &&
                        !bySystem.containsKey(system))
                    bySystem.put(system, entry);
            }
        } catch (Exception ignored) {
            // A missing/damaged registry disables internal engines. It never
            // never enables a fallback route outside EmuFusion.
        }
        return new Snapshot(byId, bySystem);
    }

    private static Entry approvedEntry(Context context, JSONObject row,
            QualificationOptIn optIn, ArtifactIdentity artifact) {
        if (row == null) return null;
        boolean releaseApproved = "approved".equals(row.optString("status")) &&
                row.optBoolean("shipped", false);
        JSONObject source = row.optJSONObject("source");
        boolean qualificationOnly = !releaseApproved && optIn != null && source != null &&
                optIn.commit.equals(source.optString("commit")) &&
                "experimental".equals(row.optString("status"));
        if (!releaseApproved && !qualificationOnly) return null;
        JSONObject license = row.optJSONObject("license");
        JSONObject state = row.optJSONObject("state");
        JSONObject build = row.optJSONObject("build");
        if (license == null ||
                !"compatible-candidate".equals(license.optString("distributionGate")) ||
                state == null || build == null) return null;
        if (releaseApproved && (!state.optBoolean("qualified", false) ||
                !build.optBoolean("reproducible", false))) return null;

        String id = normalize(row.optString("id"));
        if (id.isEmpty()) return null;
        File core = findBundledCore(context, id,
                qualificationOnly ? optIn.libraryName : null);
        if (core == null || artifact == null || !artifact.matches(id, source, core)) return null;
        JSONArray rawSystems = row.optJSONArray("systems");
        List<String> systems = new ArrayList<>();
        if (rawSystems != null) for (int i = 0; i < rawSystems.length(); i++) {
            String system = normalize(rawSystems.optString(i));
            if (!system.isEmpty() && !systems.contains(system)) systems.add(system);
        }
        if (systems.isEmpty()) return null;
        JSONObject firmware = row.optJSONObject("firmware");
        boolean firmwareRequired = firmware != null && firmware.optBoolean("required", false);
        List<String> acceptedFirmwareHashes = stringList(
                firmware == null ? null : firmware.optJSONArray("acceptedHashes"));
        // A required BIOS with no audited identity is not a usable release
        // configuration. Qualification must add hashes before this core loads.
        if (firmwareRequired && acceptedFirmwareHashes.isEmpty()) return null;
        return new Entry(id, row.optString("displayName", id), systems,
                source == null ? "unknown" : source.optString("commit", "unknown"),
                artifact.sha256,
                state.optInt("compatibilityVersion", 1),
                firmwareRequired, acceptedFirmwareHashes, core,
                row.optString("renderer", "software"), qualificationOnly,
                !qualificationOnly || optIn.autoSelect);
    }

    private static File findBundledCore(Context context, String id, String exactName) {
        File root = new File(context.getApplicationInfo().nativeLibraryDir);
        String normalized = id.replace('-', '_');
        String[] names = {
                exactName == null ? "" : exactName,
                "liblucent_core_" + normalized + ".so",
                id + "_libretro.so", normalized + "_libretro.so",
                "lib" + id + "_libretro.so", "lib" + normalized + "_libretro.so"
        };
        try {
            File canonicalRoot = root.getCanonicalFile();
            for (String name : names) {
                File candidate = new File(canonicalRoot, name).getCanonicalFile();
                if (candidate.isFile() && candidate.getParentFile().equals(canonicalRoot))
                    return candidate;
            }
        } catch (Exception ignored) {}
        return null;
    }

    private static final class QualificationOptIn {
        final String commit;
        final String libraryName;
        final boolean autoSelect;
        QualificationOptIn(String commit, String libraryName, boolean autoSelect) {
            this.commit = commit;
            this.libraryName = libraryName;
            this.autoSelect = autoSelect;
        }
    }

    private static final class ArtifactIdentity {
        final Context context;
        final String engineId;
        final String fileName;
        final String sha256;
        final String sourceCommit;

        ArtifactIdentity(Context context, String engineId, String fileName,
                String sha256, String sourceCommit) {
            this.context = context;
            this.engineId = engineId;
            this.fileName = fileName;
            this.sha256 = sha256;
            this.sourceCommit = sourceCommit;
        }

        boolean matches(String expectedId, JSONObject source, File core) {
            if (!engineId.equals(expectedId) || !fileName.equals(core.getName()) ||
                    source == null || !sourceCommit.equals(source.optString("commit"))) return false;
            try { return sha256.equals(verifiedSha256(context, core)); }
            catch (Exception ignored) { return false; }
        }
    }

    private static Map<String, QualificationOptIn> loadQualificationOptIns(Context context) {
        LinkedHashMap<String, QualificationOptIn> result = new LinkedHashMap<>();
        try {
            JSONObject root = new JSONObject(readAsset(context,
                    "engine-qualification-opt-in.json"));
            if (!root.optBoolean("qualificationOnly", false)) return result;
            boolean autoSelect = root.optBoolean("autoSelect", false);
            JSONArray engines = root.optJSONArray("engines");
            if (engines == null) return result;
            for (int i = 0; i < engines.length(); i++) {
                JSONObject row = engines.optJSONObject(i);
                if (row == null) continue;
                String id = normalize(row.optString("id"));
                String commit = row.optString("commit");
                String library = row.optString("libraryName");
                if (!id.isEmpty() && commit.matches("[0-9a-f]{40}") &&
                        library.matches("liblucent_core_[a-z0-9_]+\\.so"))
                    result.put(id, new QualificationOptIn(commit, library, autoSelect));
            }
        } catch (Exception ignored) {
            // The release APK intentionally has no opt-in asset.
        }
        return result;
    }

    private static Map<String, ArtifactIdentity> loadArtifactIdentities(Context context) {
        LinkedHashMap<String, ArtifactIdentity> result = new LinkedHashMap<>();
        try {
            JSONObject root = new JSONObject(readAsset(context, "engine-artifacts.json"));
            if (root.optInt("schemaVersion", 0) != 1) return result;
            JSONArray artifacts = root.optJSONArray("artifacts");
            if (artifacts == null) return result;
            for (int i = 0; i < artifacts.length(); i++) {
                JSONObject row = artifacts.optJSONObject(i);
                if (row == null) continue;
                String id = normalize(row.optString("engineId"));
                String filename = row.optString("fileName");
                String hash = row.optString("sha256").toLowerCase(Locale.US);
                String commit = row.optString("sourceCommit").toLowerCase(Locale.US);
                if (!id.isEmpty() && filename.matches("[A-Za-z0-9_.-]+\\.so") &&
                        hash.matches("[0-9a-f]{64}") && commit.matches("[0-9a-f]{40}"))
                    result.put(id, new ArtifactIdentity(context, id, filename, hash, commit));
            }
        } catch (Exception ignored) {
            // Missing or malformed signed provenance disables internal cores.
        }
        return result;
    }

    private static List<String> stringList(JSONArray values) {
        List<String> result = new ArrayList<>();
        if (values != null) for (int i = 0; i < values.length(); i++) {
            String value = values.optString(i).toLowerCase(Locale.US);
            if (value.matches("[0-9a-f]{64}") && !result.contains(value)) result.add(value);
        }
        return result;
    }

    /**
     * Returns the SHA-256 of a packaged core, consulting a persistent cache
     * keyed by APK install time plus file path and size. Native libraries only
     * change with the APK, so a hit skips re-reading hundreds of megabytes on
     * every cold start; a missing or corrupt cache re-hashes everything.
     * Phase2QualificationCatalog shares this cache for its bundled cores.
     */
    static String verifiedSha256(Context context, File file) throws Exception {
        String key = file.getAbsolutePath() + "|" + file.length();
        synchronized (HASH_CACHE_LOCK) {
            loadHashCacheLocked(context);
            String cachedHash = hashCacheEntries.optString(key);
            if (cachedHash.matches("[0-9a-f]{64}")) return cachedHash;
        }
        String computed = fileSha256(file);
        synchronized (HASH_CACHE_LOCK) {
            try {
                hashCacheEntries.put(key, computed);
                persistHashCacheLocked();
            } catch (Exception ignored) {
                // An unwritable cache only costs a re-hash next cold start.
            }
        }
        return computed;
    }

    private static void loadHashCacheLocked(Context context) {
        long installTime = apkLastUpdateTime(context);
        if (hashCacheEntries != null && hashCacheInstallTime == installTime) return;
        hashCachePath = new File(context.getFilesDir(), HASH_CACHE_FILE);
        hashCacheInstallTime = installTime;
        hashCacheEntries = new JSONObject();
        try {
            JSONObject root = new JSONObject(readFile(hashCachePath));
            JSONObject hashes = root.optJSONObject("hashes");
            // Any mismatch — including an unreadable install time — discards
            // the cache so a replaced APK is always fully re-verified.
            if (installTime > 0 && hashes != null &&
                    root.optLong("apkLastUpdateTime", -1) == installTime)
                hashCacheEntries = hashes;
        } catch (Exception ignored) {
            // Missing or corrupt cache: every core is re-hashed.
        }
    }

    private static void persistHashCacheLocked() throws Exception {
        JSONObject root = new JSONObject();
        root.put("apkLastUpdateTime", hashCacheInstallTime);
        root.put("hashes", hashCacheEntries);
        byte[] bytes = root.toString().getBytes(StandardCharsets.UTF_8);
        File temporary = new File(hashCachePath.getParentFile(),
                HASH_CACHE_FILE + ".tmp");
        FileOutputStream output = new FileOutputStream(temporary);
        try {
            output.write(bytes);
            output.flush();
            output.getFD().sync();
        } finally { output.close(); }
        if (!temporary.renameTo(hashCachePath)) temporary.delete();
    }

    private static long apkLastUpdateTime(Context context) {
        try {
            return context.getPackageManager()
                    .getPackageInfo(context.getPackageName(), 0).lastUpdateTime;
        } catch (Exception ignored) { return 0; }
    }

    private static String readFile(File file) throws Exception {
        InputStream input = new FileInputStream(file);
        try {
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            byte[] buffer = new byte[16 * 1024];
            int count;
            while ((count = input.read(buffer)) >= 0)
                if (count > 0) output.write(buffer, 0, count);
            return new String(output.toByteArray(), StandardCharsets.UTF_8);
        } finally { input.close(); }
    }

    private static String fileSha256(File file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        InputStream input = new java.io.FileInputStream(file);
        try {
            byte[] buffer = new byte[64 * 1024];
            int count;
            while ((count = input.read(buffer)) >= 0)
                if (count > 0) digest.update(buffer, 0, count);
        } finally { input.close(); }
        StringBuilder result = new StringBuilder(64);
        for (byte value : digest.digest())
            result.append(String.format(Locale.US, "%02x", value & 0xff));
        return result.toString();
    }

    private static String readAsset(Context context) throws Exception {
        return readAsset(context, ASSET);
    }

    private static String readAsset(Context context, String name) throws Exception {
        InputStream input = context.getAssets().open(name);
        try {
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            byte[] buffer = new byte[16 * 1024];
            int count;
            while ((count = input.read(buffer)) >= 0)
                if (count > 0) output.write(buffer, 0, count);
            return new String(output.toByteArray(), StandardCharsets.UTF_8);
        } finally { input.close(); }
    }

    private static String normalize(String value) {
        return value == null ? "" : value.trim().toLowerCase(Locale.US);
    }
}
