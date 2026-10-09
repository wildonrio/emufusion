package com.thorium.preview.game;

import android.content.Context;
import android.content.SharedPreferences;
import android.provider.Settings;
import android.view.Display;

import com.thorium.lucent.video.FrameGenerationBackendPolicy;

import java.lang.reflect.Method;
import java.util.concurrent.atomic.AtomicBoolean;

/** Process-wide owner preference for internal-emulator frame generation. */
public final class FrameGenerationSettings {
    private static final String PREFERENCES = "display-frame-generation";
    private static final String MODE_VERSION = "mode-version";
    // Version 3 deliberately forces one more OFF migration. Version 2 shipped
    // while the UI could display OFF before its asynchronous service write had
    // completed, so carrying that value forward is not trustworthy.
    private static final int CURRENT_MODE_VERSION = 3;
    private static final String ENABLED = "enabled";
    private static final String MODE = "mode";
    private static final AtomicBoolean BACKEND_PREWARM_STARTED = new AtomicBoolean(false);
    private static volatile FrameGenerationBackendPolicy.Assessment builtInAssessment =
            FrameGenerationBackendPolicy.Assessment.unavailable(
                    "RIFE qualification runtime is absent or not prewarmed");

    private FrameGenerationSettings() {}

    /** One explicit owner choice. No package, shell global, or probe may override it. */
    public enum Mode {
        OFF("off"),
        BUILT_IN_ALPHA("built-in-alpha"),
        LSFG("lsfg");

        private final String storedValue;

        Mode(String storedValue) { this.storedValue = storedValue; }

        public String storedValue() { return storedValue; }

        public static Mode parse(String value) {
            if (value != null) {
                String normalized = value.trim().toLowerCase(java.util.Locale.US);
                for (Mode candidate : values())
                    if (candidate.storedValue.equals(normalized)) return candidate;
            }
            return OFF;
        }
    }

    /**
     * Returns the explicit mode. An old Boolean or pre-versioned selector is
     * deliberately migrated to OFF: after the reported Direct-path failure,
     * upgrading the APK must never silently preserve an experimental backend.
     */
    public static synchronized Mode mode(Context context) {
        if (context == null) return Mode.OFF;
        SharedPreferences prefs = preferences(context);
        if (prefs.getInt(MODE_VERSION, 0) != CURRENT_MODE_VERSION) {
            persistMode(prefs, Mode.OFF);
            return Mode.OFF;
        }
        String stored = prefs.getString(MODE, Mode.OFF.storedValue());
        Mode parsed = Mode.parse(stored);
        // Unknown/corrupt strings and a stale legacy Boolean are canonicalized
        // synchronously. A successful service response therefore means the
        // complete durable tuple says OFF, not merely that this reader chose a
        // safe fallback in memory.
        if (!parsed.storedValue().equals(stored) ||
                prefs.getBoolean(ENABLED, false) != (parsed != Mode.OFF)) {
            parsed = Mode.OFF;
            persistMode(prefs, parsed);
        }
        return parsed;
    }

    public static boolean isEnabled(Context context) {
        return mode(context) != Mode.OFF;
    }

    public static synchronized void setMode(Context context, Mode mode) {
        if (context == null) return;
        Mode safe = mode == null ? Mode.OFF : mode;
        persistMode(preferences(context), safe);
        if (safe == Mode.OFF) InWindowGameHost.requestFrameGenerationOff();
        if (safe != Mode.OFF) prewarmOptionalBackends(context);
    }

    private static void persistMode(SharedPreferences prefs, Mode mode) {
        // commit(), rather than apply(), makes the HTTP acknowledgement a real
        // transaction boundary: the frontend may launch only after this tuple
        // is durably visible to every surface/session reader.
        prefs.edit()
                .putInt(MODE_VERSION, CURRENT_MODE_VERSION)
                .putString(MODE, mode.storedValue())
                .putBoolean(ENABLED, mode != Mode.OFF)
                .commit();
    }

    public static void setMode(Context context, String mode) {
        setMode(context, Mode.parse(mode));
    }

    /** Legacy Boolean callers may turn generation off, but can never enable it. */
    public static void setEnabled(Context context, boolean enabled) {
        setMode(context, Mode.OFF);
    }

    /**
     * Freezes the explicitly selected backend at the session boundary. Off is
     * always Direct. Built-in (Alpha) is the user's opt-in experimental arm.
     * LSFG is constructed separately by qualificationTransport() and must pass
     * its in-process capability/deadline checks on this surface; this generic
     * selector cannot authorize a substitute generator when LSFG is absent or
     * rejected. Package presence or a benchmark result is not qualification.
     */
    public static FrameGenerationBackendPolicy.Selection selectBackendForSession(
            Context context) {
        return selectBackendForSession(context, mode(context));
    }

    /** Resolves a mode already captured at the immutable launch boundary. */
    public static FrameGenerationBackendPolicy.Selection selectBackendForSession(
            Context context, Mode launchMode) {
        Mode selected = launchMode == null ? Mode.OFF : launchMode;
        if (selected == Mode.BUILT_IN_ALPHA)
            return FrameGenerationBackendPolicy.select(true,
                    FrameGenerationBackendPolicy.Assessment.unavailable(
                            "LSFG was not selected"),
                    FrameGenerationBackendPolicy.Assessment.ready());
        // LSFG is created through qualificationTransport(). If its private
        // in-process payload is absent or fails construction, the caller must
        // fall back to the exact direct Surface rather than silently switching
        // to a different generator.
        if (selected == Mode.LSFG)
            return FrameGenerationBackendPolicy.select(false,
                    FrameGenerationBackendPolicy.Assessment.unavailable(
                            "LSFG transport unavailable"),
                    FrameGenerationBackendPolicy.Assessment.unavailable(
                            "Built-in (Alpha) was not selected"));
        return FrameGenerationBackendPolicy.select(false,
                FrameGenerationBackendPolicy.Assessment.unavailable(
                        "frame generation is off"),
                builtInAssessment);
    }

    /**
     * Starts the optional qualification payload gate outside game launch and
     * outside every renderer callback. A normal APK has no reflected class and
     * remains Direct. The current qualification class deliberately reports
     * selfTestPassed=false/deadlineQualified=false, so packaging or model
     * initialization alone can never route product frames.
     */
    public static void prewarmOptionalBackends(Context context) {
        if (context == null || !BACKEND_PREWARM_STARTED.compareAndSet(false, true)) return;
        Context app = context.getApplicationContext();
        Thread worker = new Thread(() -> {
            try {
                Class<?> runtime = Class.forName(
                        "com.thorium.preview.game.RifeQualificationRuntime");
                Method assess = runtime.getMethod("assessPackage", Context.class);
                Object value = assess.invoke(null, app);
                if (value instanceof FrameGenerationBackendPolicy.Assessment)
                    builtInAssessment = (FrameGenerationBackendPolicy.Assessment) value;
            } catch (Throwable absentOrRejected) {
                builtInAssessment = FrameGenerationBackendPolicy.Assessment.unavailable(
                        "RIFE qualification runtime unavailable");
            }
        }, "emufusion-framegen-prewarm");
        worker.setDaemon(true);
        worker.start();
    }

    /**
     * Returns the APK-conditional RIFE transport only for an explicit shell
     * qualification on the top display.
     *
     * <p>This is not a user preference and does not make the quarantined
     * assessment usable. A normal APK lacks the reflected factory, while an
     * unset global keeps the qualification APK on the same automatic Direct
     * decision as production.</p>
     */
    static ExternalFrameGenerationTransport.Factory rifeQualificationTransport(
            Context context, int displayId) {
        QualificationTransport selected = qualificationTransport(context, displayId);
        return selected != null && selected.backend ==
                FrameGenerationBackendPolicy.Backend.BUILT_IN ? selected.factory : null;
    }

    /**
     * Resolves the explicitly selected private LSFG arm at a session boundary.
     *
     * <p>Only the top display is routed through the current private LSFG beta.
     * The lower display remains direct, per the owner's priority. Most
     * importantly, shell qualification globals and package presence cannot
     * activate this path while the stored mode is Off or Built-in (Alpha).</p>
     */
    static QualificationTransport qualificationTransport(
            Context context, int displayId) {
        return qualificationTransport(context, displayId, mode(context));
    }

    /** Resolves an optional transport without re-reading mutable preferences. */
    static QualificationTransport qualificationTransport(
            Context context, int displayId, Mode launchMode) {
        if (context == null || displayId != Display.DEFAULT_DISPLAY ||
                launchMode == null || launchMode == Mode.OFF) return null;
        // Explicit qualification only: the stored Alpha choice remains
        // mandatory, and neither Off nor LSFG can be overridden by this flag.
        if (launchMode == Mode.BUILT_IN_ALPHA) {
            if (Settings.Global.getInt(context.getContentResolver(),
                    "emufusion_framegen_rife_qualification", 0) != 1) return null;
            ExternalFrameGenerationTransport.Factory rife =
                    ExternalFrameGenerationTransportLoader.rifeQualification(context);
            return rife == null ? null : new QualificationTransport(
                    FrameGenerationBackendPolicy.Backend.BUILT_IN,
                    "RIFE qualification", rife);
        }
        if (launchMode != Mode.LSFG) return null;
        ExternalFrameGenerationTransport.Factory factory =
                ExternalFrameGenerationTransportLoader.lsfgQualification(context);
        if (factory == null) return null;
        return new QualificationTransport(
                FrameGenerationBackendPolicy.Backend.LSFG,
                "LSFG private beta", factory);
    }

    static final class QualificationTransport {
        final FrameGenerationBackendPolicy.Backend backend;
        final String label;
        final ExternalFrameGenerationTransport.Factory factory;

        QualificationTransport(FrameGenerationBackendPolicy.Backend backend,
                               String label,
                               ExternalFrameGenerationTransport.Factory factory) {
            if (backend == null || label == null || factory == null)
                throw new IllegalArgumentException(
                        "qualification transport identity is required");
            this.backend = backend;
            this.label = label;
            this.factory = factory;
        }
    }

    private static SharedPreferences preferences(Context context) {
        return context.getApplicationContext()
                .getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE);
    }
}
