package com.thorium.preview.game;

import android.content.Context;
import android.content.res.AssetManager;
import android.os.Environment;
import android.os.Build;
import android.system.Os;
import android.system.OsConstants;
import android.util.Log;

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

/** Fail-closed reader for explicitly packaged Phase 2 qualification assets. */
public final class Phase2QualificationCatalog {
    private static final String TAG = "LucentPhase2Catalog";
    private static final String REGISTRY = "phase2-engine-registry.json";
    private static final String OPT_IN = "phase2-qualification-opt-in.json";
    private static final String ARTIFACTS = "phase2-engine-artifacts.json";
    // Bounds the fail-closed wait a consumer spends on background verification.
    private static final long BOOTSTRAP_WAIT_SECONDS = 30;
    private static volatile Map<String, Entry> cached;
    private static volatile Thread bootstrapThread;
    private static final CountDownLatch BOOTSTRAP_GATE = new CountDownLatch(1);

    /** Fixed setup instructions that may be shown instead of a generic core failure. */
    static final class MissingFirmwareException extends IllegalStateException {
        MissingFirmwareException(String message) { super(message); }
    }

    static final class FirmwareFile {
        final String destination;
        final long size;
        final String md5;
        final String sha256;

        FirmwareFile(String destination, long size, String md5, String sha256) {
            this.destination = destination;
            this.size = size;
            this.md5 = md5;
            this.sha256 = sha256;
        }
    }

    static final class FirmwareProfile {
        final String system;
        final String mode;
        final String identity;
        final List<List<FirmwareFile>> alternatives;

        FirmwareProfile(String system, String mode, String identity,
                List<List<FirmwareFile>> alternatives) {
            this.system = system;
            this.mode = mode;
            this.identity = identity;
            ArrayList<List<FirmwareFile>> immutable = new ArrayList<>();
            for (List<FirmwareFile> alternative : alternatives)
                immutable.add(Collections.unmodifiableList(new ArrayList<>(alternative)));
            this.alternatives = Collections.unmodifiableList(immutable);
        }
    }

    static final class RuntimeInstallation {
        final File directory;
        final String firmwareIdentity;

        RuntimeInstallation(File directory, String firmwareIdentity) {
            this.directory = directory;
            this.firmwareIdentity = firmwareIdentity;
        }
    }

    static final class Entry {
        final String id;
        final List<String> systems;
        final String sourceCommit;
        final String coreArtifactSha256;
        final int stateCompatibilityVersion;
        final File coreFile;
        final String runtime;
        final String systemAssetRoot;
        final String systemAssetDestination;
        final String systemAssetProbe;
        final String systemAssetRevision;
        final List<String> systemAssetRequiredFiles;
        final Map<String, FirmwareProfile> firmwareProfiles;
        final List<String> libraryRouteSystems;

        Entry(String id, List<String> systems, String sourceCommit,
                String coreArtifactSha256,
                int stateCompatibilityVersion, File coreFile, String runtime,
                String systemAssetRoot, String systemAssetDestination,
                String systemAssetProbe, String systemAssetRevision,
                List<String> systemAssetRequiredFiles,
                Map<String, FirmwareProfile> firmwareProfiles,
                List<String> libraryRouteSystems) {
            this.id = id;
            this.systems = Collections.unmodifiableList(new ArrayList<>(systems));
            this.sourceCommit = sourceCommit;
            this.coreArtifactSha256 = coreArtifactSha256;
            this.stateCompatibilityVersion = stateCompatibilityVersion;
            this.coreFile = coreFile;
            this.runtime = runtime;
            this.systemAssetRoot = systemAssetRoot;
            this.systemAssetDestination = systemAssetDestination;
            this.systemAssetProbe = systemAssetProbe;
            this.systemAssetRevision = systemAssetRevision;
            this.systemAssetRequiredFiles = Collections.unmodifiableList(
                    new ArrayList<>(systemAssetRequiredFiles));
            this.firmwareProfiles = Collections.unmodifiableMap(
                    new LinkedHashMap<>(firmwareProfiles));
            this.libraryRouteSystems = Collections.unmodifiableList(
                    new ArrayList<>(libraryRouteSystems));
        }

        boolean supports(String system) {
            return systems.contains(normalize(system));
        }

        RuntimeInstallation installRuntimeAssets(Context context, String systemId)
                throws Exception {
            File system = new File(context.getDir("engine-system", Context.MODE_PRIVATE), id);
            if (!system.isDirectory() && !system.mkdirs())
                throw new IllegalStateException("Cannot create engine system directory");
            if (!systemAssetRoot.isEmpty()) {
                File runtimeAssets = systemAssetDestination.isEmpty() ? system :
                        new File(system, systemAssetDestination);
                File marker = new File(system, ".lucent-runtime-assets");
                String installed = marker.isFile() ? readFile(marker).trim() : "";
                String expectedMarker = sourceCommit + ":" + systemAssetRevision;
                if (!expectedMarker.equals(installed) || !runtimeAssetsComplete(system)) {
                    copyAssetTree(context.getAssets(), systemAssetRoot, runtimeAssets);
                    writeAtomic(marker, expectedMarker.getBytes(StandardCharsets.US_ASCII));
                }
                if (!runtimeAssetsComplete(system))
                    throw new IllegalStateException("Engine runtime assets are incomplete");
            }
            if ("armsx2".equals(id)) installUserPs2Bios(system);
            FirmwareProfile profile = firmwareProfiles.get(normalize(systemId));
            String identity = profile == null ? "firmware:none" :
                    installFirmwareProfile(profile, system);
            return new RuntimeInstallation(system, identity);
        }

        private static String installFirmwareProfile(FirmwareProfile profile, File system)
                throws Exception {
            if ("builtin".equals(profile.mode)) return "firmware:" + profile.identity;
            if (!"user-files".equals(profile.mode) || profile.alternatives.isEmpty())
                throw new IllegalStateException("No audited firmware profile is available");
            for (List<FirmwareFile> alternative : profile.alternatives) {
                ArrayList<File> sources = new ArrayList<>();
                boolean complete = true;
                for (FirmwareFile expected : alternative) {
                    File installed = new File(system, expected.destination);
                    File source = validFirmware(installed, expected) ? installed :
                            findUserFirmware(profile.system, expected);
                    if (source == null) { complete = false; break; }
                    sources.add(source);
                }
                if (!complete) continue;
                MessageDigest identity = MessageDigest.getInstance("SHA-256");
                for (int index = 0; index < alternative.size(); index++) {
                    FirmwareFile expected = alternative.get(index);
                    File destination = new File(system, expected.destination);
                    if (!validFirmware(destination, expected)) copyFile(sources.get(index), destination);
                    if (!validFirmware(destination, expected))
                        throw new IllegalStateException("Firmware copy failed identity verification");
                    identity.update(expected.destination.getBytes(StandardCharsets.US_ASCII));
                    identity.update(expected.md5.getBytes(StandardCharsets.US_ASCII));
                    identity.update(expected.sha256.getBytes(StandardCharsets.US_ASCII));
                }
                return "firmware:" + hex(identity.digest());
            }
            throw new IllegalStateException("Required user firmware was not found or did not match an audited identity");
        }

        private static File findUserFirmware(String systemId, FirmwareFile expected)
                throws Exception {
            for (File root : firmwareSearchRoots(systemId)) {
                File match = findMatchingFirmware(root, expected, 0);
                if (match != null) return match;
            }
            return null;
        }

        private static List<File> firmwareSearchRoots(String systemId) {
            ArrayList<File> result = new ArrayList<>();
            ArrayList<File> volumes = new ArrayList<>();
            volumes.add(Environment.getExternalStorageDirectory());
            File storage = new File("/storage");
            File[] children = storage.listFiles(File::isDirectory);
            if (children != null) for (File child : children) {
                String name = child.getName();
                if (!"emulated".equals(name) && !"self".equals(name) &&
                        !volumes.contains(child)) volumes.add(child);
            }
            for (File volume : volumes) {
                result.add(new File(volume, "Games/" + systemId + "/BIOS"));
                result.add(new File(volume, "ROMs/" + systemId + "/BIOS"));
                result.add(new File(volume, "BIOS/" + systemId));
                result.add(new File(volume, "Games/" + systemId));
                result.add(new File(volume, "ROMs/" + systemId));
                result.add(new File(volume, "BIOS"));
            }
            return result;
        }

        private static File findMatchingFirmware(File root, FirmwareFile expected, int depth)
                throws Exception {
            if (root == null || depth > 2 || !root.isDirectory()) return null;
            File[] entries = root.listFiles();
            if (entries == null) return null;
            java.util.Arrays.sort(entries, (left, right) ->
                    left.getName().compareToIgnoreCase(right.getName()));
            for (File entry : entries) if (validFirmware(entry, expected)) return entry;
            for (File entry : entries) if (entry.isDirectory()) {
                File match = findMatchingFirmware(entry, expected, depth + 1);
                if (match != null) return match;
            }
            return null;
        }

        private static boolean validFirmware(File file, FirmwareFile expected)
                throws Exception {
            return file != null && file.isFile() && file.length() == expected.size &&
                    expected.md5.equals(digest(file, "MD5")) &&
                    (expected.sha256.isEmpty() ||
                     expected.sha256.equals(digest(file, "SHA-256")));
        }

        private boolean runtimeAssetsComplete(File system) {
            if (!new File(system, systemAssetProbe).isFile()) return false;
            for (String relative : systemAssetRequiredFiles)
                if (!new File(system, relative).isFile()) return false;
            return true;
        }

        private static void installUserPs2Bios(File system) throws Exception {
            File destination = new File(system, "pcsx2/bios");
            File[] installed = destination.listFiles();
            if (installed != null) for (File candidate : installed)
                if (validPs2Bios(candidate)) return;
            // The portable library often lives entirely on a removable card.
            // Use the same readable-volume enumeration as other native setup;
            // searching only the internal volume worked on Thor but failed on
            // a new device with its BIOS beside the ROMs on SD/USB storage.
            List<File> roots = new ArrayList<>();
            for (File volume : NativeAdapterPrerequisites.permittedVolumeRoots()) {
                roots.add(new File(volume, "Games/ps2/BIOS"));
                roots.add(new File(volume, "ROMs/ps2/BIOS"));
                roots.add(new File(volume, "BIOS/ps2"));
            }
            File source = null;
            for (File root : roots) {
                source = findPs2Bios(root, 0);
                if (source != null) break;
            }
            if (source == null)
                throw new MissingFirmwareException("A user-dumped PS2 BIOS is required. " +
                        "Place it in ROMs/ps2/BIOS on internal or removable storage, then try again.");
            if (!destination.isDirectory() && !destination.mkdirs())
                throw new IllegalStateException("Cannot create private PS2 BIOS directory");
            copyFile(source, new File(destination, source.getName()));
        }

        private static File findPs2Bios(File root, int depth) {
            if (root == null || depth > 2 || !root.isDirectory()) return null;
            File[] entries = root.listFiles();
            if (entries == null) return null;
            java.util.Arrays.sort(entries, (left, right) ->
                    left.getName().compareToIgnoreCase(right.getName()));
            for (File entry : entries) if (validPs2Bios(entry)) return entry;
            for (File entry : entries) if (entry.isDirectory()) {
                File found = findPs2Bios(entry, depth + 1);
                if (found != null) return found;
            }
            return null;
        }

        private static boolean validPs2Bios(File file) {
            if (file == null || !file.isFile()) return false;
            long size = file.length();
            return size >= 4L * 1024 * 1024 && size <= 8L * 1024 * 1024 &&
                    file.getName().toLowerCase(Locale.US).endsWith(".bin");
        }
    }

    private Phase2QualificationCatalog() {}

    static List<Entry> entries(Context context) {
        return Collections.unmodifiableList(new ArrayList<>(snapshot(context).values()));
    }

    static Entry byId(Context context, String id) {
        return snapshot(context).get(normalize(id));
    }

    static Entry ppsspp(Context context) { return byId(context, "ppsspp"); }

    /**
     * Returns the one explicitly approved qualification engine for a normal
     * EmuFusion library launch. Merely packaging a Phase 2 candidate is not
     * enough: the opt-in must name the system in libraryRouteSystems, and the
     * catalog has already verified the registry commit and bundled ELF hash.
     * Ambiguous routes fail closed.
     */
    public static String libraryEngineIdForSystem(Context context, String systemId) {
        String system = normalize(systemId);
        String match = "";
        for (Entry entry : entries(context)) {
            if (!entry.libraryRouteSystems.contains(system)) continue;
            if (!match.isEmpty()) return "";
            match = entry.id;
        }
        return match;
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
        synchronized (Phase2QualificationCatalog.class) {
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
            JSONObject optIn = new JSONObject(readAsset(context, OPT_IN));
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
                        Log.e(TAG, "Rejected Phase 2 candidate: " + candidateId);
                        continue;
                    }
                    if (result.containsKey(entry.id)) {
                        Log.e(TAG, "Rejected duplicate Phase 2 candidate: " + entry.id);
                        result.remove(entry.id);
                        continue;
                    }
                    result.put(entry.id, entry);
                    Log.i(TAG, "Registered Phase 2 candidate: " + entry.id);
                } catch (Exception candidateFailure) {
                    // Qualification candidates are independent. Fail the affected
                    // engine closed without disabling other hash-verified cores.
                    Log.e(TAG, "Rejected Phase 2 candidate: " + candidateId,
                            candidateFailure);
                }
            }
        } catch (Exception catalogFailure) {
            Log.e(TAG, "Cannot load Phase 2 catalog", catalogFailure);
            result.clear();
        }
        return result;
    }

    private static Entry loadEntry(Context context, JSONObject enabled,
            JSONObject registry, JSONObject manifest) throws Exception {
        if (enabled == null) return null;
        String runtime = enabled.optString("runtime");
        if (!"gles-libretro".equals(runtime) && !"vulkan-libretro".equals(runtime))
            return null;
        String id = normalize(enabled.optString("id"));
        String commit = enabled.optString("commit").toLowerCase(Locale.US);
        String libraryName = enabled.optString("libraryName");
        String expectedName = "liblucent_core_" + id.replace('-', '_') + ".so";
        String assetRoot = enabled.optString("systemAssetRoot");
        String assetDestination = enabled.optString("systemAssetDestination");
        String assetProbe = enabled.optString("systemAssetProbe");
        String assetRevision = enabled.optString("systemAssetRevision")
                .toLowerCase(Locale.US);
        List<String> assetRequiredFiles = stringsPreservingPaths(
                enabled.optJSONArray("systemAssetRequiredFiles"));
        Map<String, FirmwareProfile> firmwareProfiles = firmwareProfiles(
                enabled.optJSONArray("firmwareProfiles"));
        List<String> libraryRouteSystems = strings(
                enabled.optJSONArray("libraryRouteSystems"));
        if (id.isEmpty() || !commit.matches("[0-9a-f]{40}") ||
                !expectedName.equals(libraryName) ||
                (!assetRoot.isEmpty() && (!assetRoot.startsWith("phase2-system/") ||
                 assetRoot.contains(".."))) ||
                !safeRelative(assetDestination) || !safeRelative(assetProbe) ||
                (!assetDestination.isEmpty() && !assetProbe.startsWith(
                        assetDestination + "/")) ||
                (assetRoot.isEmpty() != assetProbe.isEmpty()) ||
                (!assetRoot.isEmpty() &&
                 (!assetRevision.matches("[0-9a-f]{64}") ||
                  assetRequiredFiles.isEmpty())) ||
                (assetRoot.isEmpty() &&
                 (!assetRevision.isEmpty() || !assetRequiredFiles.isEmpty()))) return null;
        for (String relative : assetRequiredFiles)
            if (!safeRelative(relative) ||
                    (!assetDestination.isEmpty() && !relative.startsWith(
                            assetDestination + "/"))) return null;

        JSONObject row = find(registry.optJSONArray("engines"), id, "id");
        JSONObject source = row == null ? null : row.optJSONObject("source");
        JSONObject renderer = row == null ? null : row.optJSONObject("renderer");
        JSONObject state = row == null ? null : row.optJSONObject("state");
        JSONObject android = row == null ? null : row.optJSONObject("android");
        if (row == null || source == null || renderer == null || state == null ||
                android == null ||
                !"experimental".equals(row.optString("status")) ||
                row.optBoolean("shipped", true) ||
                !"libretro-core".equals(row.optString("route")) ||
                !commit.equals(source.optString("commit")) ||
                renderer.optBoolean("qualified", true)) return null;
        int minimumApi = android.optInt("minApi", Integer.MAX_VALUE);
        if (minimumApi < 21 || Build.VERSION.SDK_INT < minimumApi) return null;
        List<String> systems = strings(row.optJSONArray("systems"));
        if (systems.isEmpty()) return null;
        if (!systems.containsAll(libraryRouteSystems)) return null;
        for (String firmwareSystem : firmwareProfiles.keySet())
            if (!systems.contains(firmwareSystem)) return null;
        JSONObject firmware = row.optJSONObject("firmware");
        List<String> requiredFirmwareSystems = strings(firmware == null ? null :
                firmware.optJSONArray("requiredForSystems"));
        if (firmware != null && firmware.optBoolean("required", false) &&
                !"armsx2".equals(id) &&
                !firmwareProfiles.keySet().containsAll(requiredFirmwareSystems)) return null;

        JSONObject artifact = find(manifest.optJSONArray("artifacts"), id, "engineId");
        if (artifact == null || !libraryName.equals(artifact.optString("fileName")) ||
                !commit.equals(artifact.optString("sourceCommit"))) return null;
        artifact = selectPageSizeArtifact(id, artifact, Os.sysconf(OsConstants._SC_PAGESIZE));
        if (artifact == null) return null;
        libraryName = artifact.optString("fileName");
        String expectedHash = artifact.optString("sha256").toLowerCase(Locale.US);
        if (!expectedHash.matches("[0-9a-f]{64}")) return null;

        File libraryRoot = new File(context.getApplicationInfo().nativeLibraryDir)
                .getCanonicalFile();
        File core = new File(libraryRoot, libraryName).getCanonicalFile();
        if (!core.isFile() || !libraryRoot.equals(core.getParentFile()) ||
                !expectedHash.equals(
                        InternalEngineCatalog.verifiedSha256(context, core))) return null;
        if (!assetRoot.isEmpty()) {
            InputStream probe = context.getAssets().open(assetRoot + "/" +
                    assetProbe.substring(assetDestination.isEmpty() ? 0 :
                            assetDestination.length() + 1));
            try { if (probe.read() < 0) return null; }
            finally { probe.close(); }
        }
        return new Entry(id, systems, commit, expectedHash,
                Math.max(1, state.optInt("compatibilityVersion", 1)), core,
                runtime, assetRoot, assetDestination, assetProbe, assetRevision,
                assetRequiredFiles, firmwareProfiles, libraryRouteSystems);
    }

    // ARMSX2's page geometry is compiled into its memory manager. Both cores
    // are bundled; selecting the wrong one is not a recoverable renderer choice.
    // Keep the upstream exact-page check intact and verify the selected binary
    // with the same manifest hash/path checks as every other core.
    static JSONObject selectPageSizeArtifact(String id, JSONObject base, long pageSize) {
        if (!"armsx2".equals(id)) return base;
        if (pageSize == 4096 && base.optInt("hostPageSize", 4096) == 4096) return base;
        if (pageSize != 16384) return null;
        JSONObject variant = find(base.optJSONArray("pageSizeVariants"), "16384", "hostPageSize");
        if (variant == null ||
                !"liblucent_core_armsx2_16k.so".equals(variant.optString("fileName")) ||
                !base.optString("sourceCommit").equals(variant.optString("sourceCommit"))) return null;
        Log.i(TAG, "Selected PS2 host-page variant bytes=" + pageSize +
                " library=" + variant.optString("fileName"));
        return variant;
    }

    private static Map<String, FirmwareProfile> firmwareProfiles(JSONArray rows) {
        LinkedHashMap<String, FirmwareProfile> result = new LinkedHashMap<>();
        if (rows == null) return result;
        for (int index = 0; index < rows.length(); index++) {
            JSONObject row = rows.optJSONObject(index);
            if (row == null) return new LinkedHashMap<>();
            String system = normalize(row.optString("system"));
            String mode = row.optString("mode");
            String identity = row.optString("identity");
            ArrayList<List<FirmwareFile>> alternatives = new ArrayList<>();
            JSONArray rawAlternatives = row.optJSONArray("alternatives");
            if (rawAlternatives != null) for (int altIndex = 0;
                    altIndex < rawAlternatives.length(); altIndex++) {
                JSONArray rawFiles = rawAlternatives.optJSONArray(altIndex);
                ArrayList<FirmwareFile> files = new ArrayList<>();
                if (rawFiles != null) for (int fileIndex = 0;
                        fileIndex < rawFiles.length(); fileIndex++) {
                    JSONObject raw = rawFiles.optJSONObject(fileIndex);
                    String destination = raw == null ? "" : raw.optString("destination");
                    long size = raw == null ? 0 : raw.optLong("size");
                    String md5 = raw == null ? "" : raw.optString("md5")
                            .toLowerCase(Locale.US);
                    String sha256 = raw == null ? "" : raw.optString("sha256")
                            .toLowerCase(Locale.US);
                    if (!safeRelative(destination) || destination.isEmpty() ||
                            destination.contains("/") || size <= 0 ||
                            !md5.matches("[0-9a-f]{32}") ||
                            (!sha256.isEmpty() && !sha256.matches("[0-9a-f]{64}")))
                        return new LinkedHashMap<>();
                    files.add(new FirmwareFile(destination, size, md5, sha256));
                }
                if (files.isEmpty()) return new LinkedHashMap<>();
                alternatives.add(files);
            }
            boolean builtinValid = "builtin".equals(mode) &&
                    identity.matches("[a-z0-9._-]{16,128}") && alternatives.isEmpty();
            boolean filesValid = "user-files".equals(mode) && identity.isEmpty() &&
                    !alternatives.isEmpty();
            if (system.isEmpty() || result.containsKey(system) ||
                    (!builtinValid && !filesValid)) return new LinkedHashMap<>();
            result.put(system, new FirmwareProfile(system, mode, identity, alternatives));
        }
        return result;
    }

    private static boolean safeRelative(String value) {
        return value.isEmpty() || (!value.startsWith("/") &&
                !value.contains("..") && !value.contains("\\"));
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

    private static List<String> stringsPreservingPaths(JSONArray values) {
        ArrayList<String> result = new ArrayList<>();
        if (values != null) for (int i = 0; i < values.length(); i++) {
            String value = values.optString(i).trim();
            if (!value.isEmpty() && !result.contains(value)) result.add(value);
        }
        return result;
    }

    private static void copyAssetTree(AssetManager assets, String source,
                                      File destination) throws Exception {
        String[] children = assets.list(source);
        if (children != null && children.length > 0) {
            if (!destination.isDirectory() && !destination.mkdirs())
                throw new IllegalStateException("Cannot create runtime asset directory");
            for (String child : children) {
                if (child.isEmpty() || child.contains("/") || ".".equals(child) ||
                        "..".equals(child)) throw new IllegalStateException("Unsafe asset path");
                copyAssetTree(assets, source + "/" + child, new File(destination, child));
            }
            return;
        }
        InputStream input = assets.open(source);
        try {
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            byte[] buffer = new byte[64 * 1024];
            int count;
            while ((count = input.read(buffer)) >= 0)
                if (count > 0) output.write(buffer, 0, count);
            writeAtomic(destination, output.toByteArray());
        } finally { input.close(); }
    }

    private static void writeAtomic(File destination, byte[] bytes) throws Exception {
        File parent = destination.getParentFile();
        if (!parent.isDirectory() && !parent.mkdirs())
            throw new IllegalStateException("Cannot create runtime asset parent");
        File temporary = new File(parent, destination.getName() + ".pending");
        FileOutputStream output = new FileOutputStream(temporary);
        try {
            output.write(bytes);
            output.flush();
            output.getFD().sync();
        } finally { output.close(); }
        Os.rename(temporary.getPath(), destination.getPath());
    }

    private static void copyFile(File source, File destination) throws Exception {
        File parent = destination.getParentFile();
        if (parent != null && !parent.isDirectory() && !parent.mkdirs())
            throw new IllegalStateException("Cannot create runtime file directory");
        File pending = new File(parent, destination.getName() + ".pending");
        try (FileInputStream input = new FileInputStream(source);
             FileOutputStream output = new FileOutputStream(pending)) {
            byte[] buffer = new byte[64 * 1024];
            int count;
            while ((count = input.read(buffer)) >= 0)
                if (count > 0) output.write(buffer, 0, count);
            output.getFD().sync();
        }
        if (!pending.renameTo(destination)) {
            pending.delete();
            throw new IllegalStateException("Cannot install runtime file");
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

    private static String readFile(File file) throws Exception {
        InputStream input = new FileInputStream(file);
        try {
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            byte[] buffer = new byte[4096];
            int count;
            while ((count = input.read(buffer)) >= 0)
                if (count > 0) output.write(buffer, 0, count);
            return new String(output.toByteArray(), StandardCharsets.US_ASCII);
        } finally { input.close(); }
    }

    private static String digest(File file, String algorithm) throws Exception {
        MessageDigest digest = MessageDigest.getInstance(algorithm);
        InputStream input = new FileInputStream(file);
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

    private static String hex(byte[] bytes) {
        StringBuilder result = new StringBuilder(bytes.length * 2);
        for (byte value : bytes)
            result.append(String.format(Locale.US, "%02x", value & 0xff));
        return result.toString();
    }

    private static String normalize(String value) {
        return value == null ? "" : value.trim().toLowerCase(Locale.US);
    }
}
