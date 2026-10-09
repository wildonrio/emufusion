package com.thorium.preview.game;

import android.content.Context;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/**
 * Fail-closed reader for explicitly packaged Phase 3 native-adapter engines.
 *
 * A native-adapter engine is only routable internally when ALL of the following
 * hold: a signed phase3 opt-in names the engine, the pinned
 * {@code phase3-engine-registry.json} row for it declares
 * {@code route: native-adapter} at the opted commit, a phase3 artifact manifest
 * records the adapter's SHA-256, and the adapter {@code .so} is physically
 * bundled in the APK with a matching hash.
 *
 * A default/release APK packages none of those assets, so the catalog is empty
 * and every Phase 3 system stays on its external route. Only a qualification
 * build that explicitly opted in has them, and the opt-in is PER ENGINE:
 * Switch/Eden via {@code LUCENT_INCLUDE_PHASE3_EDEN=1}, Wii U/Cemu via
 * {@code LUCENT_INCLUDE_PHASE3_CEMU=1}, and PS3/aPS3e via
 * {@code LUCENT_INCLUDE_PHASE3_APS3E=1}. The adapters are staged independently,
 * so a build that omits a corresponding flag does not fall back to a "not built yet"
 * state -- it silently strips a working internal engine and drops that system
 * onto its external route. Wii U in particular is expected to run INTERNALLY,
 * so {@code LUCENT_INCLUDE_PHASE3_CEMU=1} belongs in every qualification
 * build alongside the Eden flag.
 */
public final class NativeAdapterCatalog {
    private static final String TAG = "LucentPhase3Catalog";
    private static final String REGISTRY = "phase3-engine-registry.json";
    private static final String OPT_IN = "phase3-qualification-opt-in.json";
    private static final String ARTIFACTS = "phase3-engine-artifacts.json";
    // Bounds the fail-closed wait a consumer spends on background verification.
    private static final long BOOTSTRAP_WAIT_SECONDS = 30;
    private static volatile Map<String, Entry> cached;
    private static volatile Thread bootstrapThread;
    private static final CountDownLatch BOOTSTRAP_GATE = new CountDownLatch(1);

    static final class Entry {
        final String id;
        final List<String> systems;
        final String coreArtifactSha256;
        final String sourceCommit;
        final String runtime;
        final List<String> libraryRouteSystems;
        final File coreFile;

        Entry(String id, List<String> systems, String coreArtifactSha256,
                String sourceCommit, String runtime,
                List<String> libraryRouteSystems, File coreFile) {
            this.id = id;
            this.systems = Collections.unmodifiableList(new ArrayList<>(systems));
            this.coreArtifactSha256 = coreArtifactSha256;
            this.sourceCommit = sourceCommit;
            this.runtime = runtime;
            this.libraryRouteSystems = Collections.unmodifiableList(
                    new ArrayList<>(libraryRouteSystems));
            this.coreFile = coreFile;
        }

        boolean supports(String system) {
            return systems.contains(normalize(system));
        }
    }

    private NativeAdapterCatalog() {}

    static List<Entry> entries(Context context) {
        return Collections.unmodifiableList(new ArrayList<>(snapshot(context).values()));
    }

    static Entry byId(Context context, String id) {
        return snapshot(context).get(normalize(id));
    }

    /**
     * Returns the native-adapter engine that owns a system for a normal library
     * launch, or null. Packaging an adapter is not enough: the opt-in must name
     * the system in {@code libraryRouteSystems}, and the catalog has already
     * verified the pinned commit and the bundled adapter's hash. An ambiguous
     * owner fails closed (null).
     */
    static Entry availableForSystem(Context context, String systemId) {
        String system = normalize(systemId);
        Entry match = null;
        for (Entry entry : entries(context)) {
            if (!entry.libraryRouteSystems.contains(system)) continue;
            if (match != null) return null;
            match = entry;
        }
        return match;
    }

    /** The native-adapter engine id that owns a system, or "" (fail closed). */
    public static String libraryEngineIdForSystem(Context context, String systemId) {
        Entry entry = availableForSystem(context, systemId);
        return entry == null ? "" : entry.id;
    }

    static void invalidate() { cached = null; }

    /** Called by the bootstrap before its verification thread starts. */
    static void expectBootstrapOn(Thread verifier) { bootstrapThread = verifier; }

    /** Called by the bootstrap once verification and registration finish. */
    static void bootstrapComplete() { BOOTSTRAP_GATE.countDown(); }

    private static Map<String, Entry> snapshot(Context context) {
        // Fail closed: consumers block until the background verification (and
        // engine registration) completes; an expired or interrupted wait yields
        // an uncached empty catalog, never unverified entries.
        if (!bootstrapSettled()) return Collections.<String, Entry>emptyMap();
        Map<String, Entry> result = cached;
        if (result != null) return result;
        synchronized (NativeAdapterCatalog.class) {
            if (cached == null)
                cached = Collections.unmodifiableMap(load(context.getApplicationContext()));
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

    private static Map<String, Entry> load(Context context) {
        LinkedHashMap<String, Entry> result = new LinkedHashMap<>();
        try {
            // The release APK intentionally has no opt-in asset; its absence
            // keeps every native-adapter system on its external route.
            String optInRaw = readAssetOrNull(context, OPT_IN);
            if (optInRaw == null) return result;
            JSONObject optIn = new JSONObject(optInRaw);
            if (optIn.optInt("schemaVersion", 0) != 1 ||
                    !optIn.optBoolean("qualificationOnly", false) ||
                    optIn.optBoolean("autoSelect", true)) return result;
            JSONObject registry = new JSONObject(readAsset(context, REGISTRY));
            JSONObject manifest = new JSONObject(readAsset(context, ARTIFACTS));
            if (registry.optInt("schemaVersion", 0) != 1 ||
                    manifest.optInt("schemaVersion", 0) != 1) return result;

            JSONArray opted = optIn.optJSONArray("engines");
            if (opted == null) return result;
            for (int index = 0; index < opted.length(); index++) {
                JSONObject enabled = opted.optJSONObject(index);
                String candidateId = enabled == null ? "<invalid>" :
                        normalize(enabled.optString("id"));
                try {
                    Entry entry = loadEntry(context, enabled, registry, manifest);
                    if (entry == null) {
                        Log.e(TAG, "Rejected Phase 3 adapter: " + candidateId);
                        continue;
                    }
                    if (result.containsKey(entry.id)) {
                        Log.e(TAG, "Rejected duplicate Phase 3 adapter: " + entry.id);
                        result.remove(entry.id);
                        continue;
                    }
                    result.put(entry.id, entry);
                    Log.i(TAG, "Registered Phase 3 adapter: " + entry.id);
                } catch (Exception candidateFailure) {
                    // Adapters are independent. Fail the affected one closed
                    // without disabling other hash-verified adapters.
                    Log.e(TAG, "Rejected Phase 3 adapter: " + candidateId,
                            candidateFailure);
                }
            }
        } catch (Exception catalogFailure) {
            Log.e(TAG, "Cannot load Phase 3 catalog", catalogFailure);
            result.clear();
        }
        return result;
    }

    private static Entry loadEntry(Context context, JSONObject enabled,
            JSONObject registry, JSONObject manifest) throws Exception {
        if (enabled == null) return null;
        String runtime = enabled.optString("runtime");
        if (!"native-adapter".equals(runtime)) return null;
        String id = normalize(enabled.optString("id"));
        String commit = enabled.optString("commit").toLowerCase(Locale.US);
        String libraryName = enabled.optString("libraryName");
        String expectedName = "liblucent_native_adapter_" +
                id.replace('-', '_') + ".so";
        List<String> libraryRouteSystems = strings(
                enabled.optJSONArray("libraryRouteSystems"));
        if (id.isEmpty() || !commit.matches("[0-9a-f]{40}") ||
                !expectedName.equals(libraryName) ||
                libraryRouteSystems.isEmpty()) return null;

        JSONObject row = find(registry.optJSONArray("engines"), id, "id");
        JSONObject source = row == null ? null : row.optJSONObject("source");
        if (row == null || source == null ||
                !"native-adapter".equals(row.optString("route")) ||
                row.optBoolean("shipped", true) ||
                !commit.equals(source.optString("commit"))) return null;
        List<String> systems = strings(row.optJSONArray("systems"));
        if (systems.isEmpty() || !systems.containsAll(libraryRouteSystems)) return null;

        JSONObject artifact = find(manifest.optJSONArray("artifacts"), id, "engineId");
        if (artifact == null || !libraryName.equals(artifact.optString("fileName")) ||
                !commit.equals(artifact.optString("sourceCommit"))) return null;
        String expectedHash = artifact.optString("sha256").toLowerCase(Locale.US);
        if (!expectedHash.matches("[0-9a-f]{64}")) return null;

        // Present + hash gate: the adapter must be bundled in the APK's native
        // library dir and hash exactly to the signed manifest, or fail closed.
        File libraryRoot = new File(context.getApplicationInfo().nativeLibraryDir)
                .getCanonicalFile();
        File core = new File(libraryRoot, libraryName).getCanonicalFile();
        if (!core.isFile() || !libraryRoot.equals(core.getParentFile()) ||
                !expectedHash.equals(
                        InternalEngineCatalog.verifiedSha256(context, core))) return null;

        return new Entry(id, systems, expectedHash, commit, runtime,
                libraryRouteSystems, core);
    }

    private static JSONObject find(JSONArray rows, String id, String key) {
        if (rows == null) return null;
        JSONObject match = null;
        for (int i = 0; i < rows.length(); i++) {
            JSONObject row = rows.optJSONObject(i);
            if (row != null && id.equals(normalize(row.optString(key)))) {
                if (match != null) return null;
                match = row;
            }
        }
        return match;
    }

    private static List<String> strings(JSONArray values) {
        ArrayList<String> result = new ArrayList<>();
        if (values != null) for (int i = 0; i < values.length(); i++) {
            String value = normalize(values.optString(i));
            if (!value.isEmpty() && !result.contains(value)) result.add(value);
        }
        return result;
    }

    private static String readAssetOrNull(Context context, String name) {
        try {
            return readAsset(context, name);
        } catch (Exception missing) {
            return null;
        }
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
