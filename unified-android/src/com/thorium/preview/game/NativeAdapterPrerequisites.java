package com.thorium.preview.game;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.Environment;

import java.io.File;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;

/**
 * Persisted, fail-closed readiness for native-adapter systems.
 *
 * <p>The preference intentionally stores only {@code READY}/{@code NOT_READY}.
 * It never stores a key filename, firmware filename, source path, or validation
 * failure.  The importer refreshes this state from user-authorized readable
 * storage roots; routing consumes it without doing filesystem work on the UI
 * thread; and {@link NativeAdapterSystemDirectory} independently revalidates
 * and installs the inputs immediately before an adapter loads content.</p>
 */
public final class NativeAdapterPrerequisites {
    private static final String PREFS = "native-adapter-readiness";
    private static final String PREFIX = "readiness.";
    static final String READY = "READY";
    static final String NOT_READY = "NOT_READY";

    private static final class Spec {
        final String system;
        final String engine;

        Spec(String system, String engine) {
            this.system = system;
            this.engine = engine;
        }
    }

    private static final Spec[] SPECS = {
            new Spec("switch", "eden"),
            new Spec("wiiu", "cemu"),
            new Spec("ps3", "aps3e"),
    };

    private NativeAdapterPrerequisites() {}

    /**
     * Refreshes every native-adapter prerequisite state during an update/import
     * scan. Returns true only when a persisted route-affecting state changed.
     */
    public static boolean refresh(Context context) {
        if (context == null) return false;
        Context app = context.getApplicationContext();
        List<File> roots = permittedVolumeRoots();
        boolean changed = false;
        for (Spec spec : SPECS) {
            boolean ready = NativeAdapterSystemDirectory.prerequisitesPresent(
                    app, spec.engine, spec.system, roots);
            changed |= record(app, spec.system, ready);
        }
        return changed;
    }

    /** True only after the importer or a successful launch recorded READY. */
    public static boolean isReady(Context context, String systemId) {
        if (context == null) return false;
        String system = canonicalSystem(systemId);
        if (engineForSystem(system).isEmpty()) return true;
        return READY.equals(context.getApplicationContext()
                .getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .getString(PREFIX + system, NOT_READY));
    }

    /**
     * Records the result of launch-time revalidation. Package-private so only
     * the trusted adapter system-directory boundary can update it outside a
     * full import scan.
     */
    static boolean record(Context context, String systemId, boolean ready) {
        if (context == null) return false;
        String system = canonicalSystem(systemId);
        if (engineForSystem(system).isEmpty()) return false;
        SharedPreferences prefs = context.getApplicationContext()
                .getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        String next = ready ? READY : NOT_READY;
        boolean hadValue = prefs.contains(PREFIX + system);
        String previous = prefs.getString(PREFIX + system, NOT_READY);
        if (hadValue && next.equals(previous)) return false;
        prefs.edit().putString(PREFIX + system, next).apply();
        // The implicit pre-scan state is NOT_READY. Persist it for auditability,
        // but only READY on the first scan changes the effective route.
        return !hadValue ? READY.equals(next) : !next.equals(previous);
    }

    static String engineForSystem(String systemId) {
        String system = canonicalSystem(systemId);
        for (Spec spec : SPECS) if (spec.system.equals(system)) return spec.engine;
        return "";
    }

    /** Internal shared storage plus every readable removable /storage volume. */
    static List<File> permittedVolumeRoots() {
        LinkedHashMap<String, File> roots = new LinkedHashMap<>();
        addReadableRoot(roots, Environment.getExternalStorageDirectory());
        File[] storage = new File("/storage").listFiles();
        if (storage != null) for (File candidate : storage) {
            String name = candidate.getName();
            if ("emulated".equals(name) || "self".equals(name)) continue;
            addReadableRoot(roots, candidate);
        }
        return new ArrayList<>(roots.values());
    }

    private static void addReadableRoot(LinkedHashMap<String, File> roots, File root) {
        if (root == null || !root.isDirectory() || !root.canRead()) return;
        try {
            File canonical = root.getCanonicalFile();
            roots.put(canonical.getPath(), canonical);
        } catch (Exception ignored) {
            // An unresolved volume is not a permitted scan root.
        }
    }

    private static String canonicalSystem(String value) {
        String normalized = value == null ? "" :
                value.trim().toLowerCase(Locale.US).replace("_", "-");
        return "wii-u".equals(normalized) ? "wiiu" : normalized;
    }
}
