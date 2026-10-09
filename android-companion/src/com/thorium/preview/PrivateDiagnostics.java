package com.thorium.preview;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.SystemClock;
import org.json.JSONObject;
import java.net.URI;
import java.util.ArrayDeque;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.function.LongSupplier;

/** Opt-in, bounded private summaries. Never reads logcat, ROMs, or device identity. */
public final class PrivateDiagnostics {
    // A release may configure this only after the private ingress logging/retention
    // has been verified. No receiver has been deployed. Blank means NO collection/I/O.
    private static final String ENDPOINT = "";
    private static final URI DESTINATION = PrivateDiagnosticsTransport.endpoint(ENDPOINT);
    private static PrivateDiagnostics instance;
    private final SharedPreferences preferences;
    private final int build;
    interface Sender {
        PrivateDiagnosticsTransport.Result send(URI uri, PrivateDiagnosticReport report) throws Exception;
    }
    private final URI destination;
    private final Sender sender;
    private final LongSupplier clock;
    private final LongSupplier wallClock;
    private final int pid;
    private final PrivateDiagnosticsExitRecovery.History exits;
    private final long recoveryBefore;
    private final ExecutorService worker = Executors.newSingleThreadExecutor(task -> {
        Thread thread = new Thread(task, "emufusion-private-diagnostics");
        thread.setDaemon(true);
        return thread;
    });
    private final ArrayDeque<PrivateDiagnosticReport> pending = new ArrayDeque<>();
    private volatile boolean enabled;
    private volatile boolean gameplay;
    private volatile long generation;
    private volatile int pendingCount;
    private boolean loaded;
    private long retryAfter;
    private Object activeSession;

    private PrivateDiagnostics(Context context) {
        this(context.getApplicationContext().getSharedPreferences(
                "private-diagnostics-v1", Context.MODE_PRIVATE), buildCode(context),
                DESTINATION, PrivateDiagnosticsTransport::send, SystemClock::elapsedRealtime,
                System::currentTimeMillis, android.os.Process.myPid(),
                PrivateDiagnosticsExitRecovery.android(context));
    }

    PrivateDiagnostics(SharedPreferences preferences, int code, URI destination,
            Sender sender, LongSupplier clock) {
        this(preferences, code, destination, sender, clock, () -> 0, 0, (pid, start, end) -> null);
    }

    PrivateDiagnostics(SharedPreferences preferences, int code, URI destination,
            Sender sender, LongSupplier clock, LongSupplier wallClock, int pid,
            PrivateDiagnosticsExitRecovery.History exits) {
        this.preferences = preferences;
        this.build = code;
        this.destination = destination;
        this.sender = sender;
        this.clock = clock;
        this.wallClock = wallClock;
        this.pid = pid;
        this.exits = exits;
        recoveryBefore = wallClock.getAsLong();
        enabled = destination != null && code > 0 && preferences.getBoolean("enabled", false);
        if (enabled) worker.execute(this::recoverExit);
    }

    private static int buildCode(Context context) {
        Context app = context.getApplicationContext();
        int code = 0;
        try { code = app.getPackageManager().getPackageInfo(app.getPackageName(), 0).versionCode; }
        catch (Exception ignored) { /* Unavailable release identity disables reports. */ }
        return code;
    }

    private static synchronized PrivateDiagnostics get(Context context) {
        if (instance == null) instance = new PrivateDiagnostics(context);
        return instance;
    }

    public static PrivateDiagnosticsSession session(Context context, String system) {
        if (DESTINATION == null) return new PrivateDiagnosticsSession((event, bucket) -> {});
        // Capture only a fixed system code, never the launch request or its path/title.
        String code = "gc".equals(system) ? "gamecube" : "n3ds".equals(system) ? "3ds" : system;
        PrivateDiagnostics owner = get(context);
        return owner.beginSession(code);
    }

    PrivateDiagnosticsSession beginSession(String system) {
        long consent = generation;
        PrivateDiagnosticsExitRecovery.Marker marker = enabled
                ? PrivateDiagnosticsExitRecovery.Marker.create(build, system, pid, wallClock.getAsLong()) : null;
        String key = marker == null ? "" : marker.key();
        Object sessionToken = new Object();
        if (marker != null) worker.execute(() -> {
            if (!enabled || generation != consent) return;
            activeSession = sessionToken;
            // Commit off the UI thread before subsequent queued events. A crash
            // before this write completes can be missed; gameplay never waits for it.
            preferences.edit().putString("active", key).commit();
        });
        return new PrivateDiagnosticsSession((event, bucket) -> {
            record(PrivateDiagnosticReport.create(build, system, event, bucket), consent);
        }, () -> {
            if (marker == null) return;
            worker.execute(() -> {
                if (generation != consent || activeSession != sessionToken) return;
                activeSession = null;
                preferences.edit().remove("active").commit();
            });
        });
    }

    private void recoverExit() {
        long consent = generation;
        if (!enabled) return;
        PrivateDiagnosticsExitRecovery.Marker marker = PrivateDiagnosticsExitRecovery.Marker.parse(
                preferences.getString("active", ""));
        PrivateDiagnosticReport report = marker == null ? null : marker.recover(exits, recoveryBefore);
        if (!enabled || generation != consent) return;
        load();
        if (report != null) {
            if (pending.size() == 64) pending.removeFirst();
            pending.addLast(report);
        }
        // One atomic preference transaction consumes the local marker and queues
        // the summary. No upload or extra Android history read happens here.
        preferences.edit().remove("active").putString("pending", serializedPending()).commit();
    }

    void record(PrivateDiagnosticReport report) {
        record(report, generation);
    }

    private void record(PrivateDiagnosticReport report, long consent) {
        if (!enabled || generation != consent || report == null) return;
        worker.execute(() -> {
            if (!enabled || generation != consent) return;
            load();
            if (pending.size() == 64) pending.removeFirst();
            pending.addLast(report);
            persist();
        });
    }

    public static JSONObject status(Context context) {
        PrivateDiagnostics owner = get(context);
        JSONObject result = new JSONObject();
        try {
            result.put("configured", DESTINATION != null && owner.build > 0);
            result.put("enabled", owner.enabled);
            result.put("pending", owner.pendingCount);
        } catch (org.json.JSONException ignored) { /* Only fixed non-null keys/primitive values. */ }
        return result;
    }

    public static synchronized void setEnabled(Context context, boolean requested) {
        get(context).setConsent(requested);
    }

    synchronized void setConsent(boolean requested) {
        enabled = requested && destination != null && build > 0;
        long consent = ++generation;
        preferences.edit().putBoolean("enabled", enabled).apply();
        worker.execute(() -> {
            if (generation != consent) return;
            // A consent change always discards older pending data. Turning it back
            // on cannot upload anything collected before the new consent.
            pending.clear();
            activeSession = null;
            loaded = true;
            retryAfter = 0;
            preferences.edit().remove("active").putString("pending", serializedPending()).commit();
        });
    }

    public static void gameplay(Context context, boolean active) {
        if (DESTINATION == null) return;
        get(context).setGameplay(active);
    }

    void setGameplay(boolean active) {
        gameplay = active;
        if (!active && enabled) worker.execute(this::flush);
    }

    private void load() {
        if (loaded) return;
        loaded = true;
        String saved = preferences.getString("pending", "");
        if (saved == null || saved.length() > 6464) return;
        for (String line : saved.split("\n")) {
            PrivateDiagnosticReport report = PrivateDiagnosticReport.fromKey(line);
            // Old releases are not silently relabelled with the current build.
            if (report != null && pending.size() < 64) pending.addLast(report);
        }
        pendingCount = pending.size();
    }

    private void persist() {
        preferences.edit().putString("pending", serializedPending()).apply();
    }

    private String serializedPending() {
        StringBuilder saved = new StringBuilder();
        for (PrivateDiagnosticReport report : pending) saved.append(report.key()).append('\n');
        pendingCount = pending.size();
        return saved.toString();
    }

    private void flush() {
        if (!enabled || gameplay || clock.getAsLong() < retryAfter) return;
        load();
        long consent = generation;
        for (int sent = 0; sent < 8 && !pending.isEmpty(); ++sent) {
            if (!enabled || gameplay || generation != consent) return;
            PrivateDiagnosticsTransport.Result result;
            try { result = sender.send(destination, pending.peekFirst()); }
            catch (Exception ignored) { result = PrivateDiagnosticsTransport.Result.RETRY; }
            if (result == PrivateDiagnosticsTransport.Result.RETRY) {
                retryAfter = clock.getAsLong() + 120000L;
                return;
            }
            // Reports have no ID: an interrupted response can result in duplicate
            // aggregate counts on retry. These are report counts, not unique devices.
            pending.removeFirst();
            persist();
        }
    }
}
