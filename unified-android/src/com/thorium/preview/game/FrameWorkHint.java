package com.thorium.preview.game;

import android.content.Context;
import android.os.Build;
import android.os.PerformanceHintManager;
import android.provider.Settings;
import android.util.Log;

/**
 * Tells Android how long one frame's work may take on the calling thread
 * (Android Dynamic Performance Framework, API 31+).
 *
 * <p>Without it the CPU governor sees a thread that works a few milliseconds
 * and sleeps for the rest of the frame, so it lowers that core's clock or
 * moves the thread to a small core; the next busier frame then overruns and
 * is shown a refresh late. On phones whose governors ramp slowly that is a
 * random micro-stutter in every system. A session only raises the clock floor
 * when the reported work approaches its target: it never runs a thread slower
 * than it would run without one. Below API 31, or where the device offers no
 * session, every call is a no-op.</p>
 *
 * <p>One instance belongs to the thread that created it. QA:
 * {@code emufusion_work_hint=0} turns sessions off for comparisons.</p>
 */
final class FrameWorkHint {
    static final String GLOBAL = "emufusion_work_hint";
    private static final String TAG = "EmuFusionWorkHint";
    /** Retarget only on a real rate change, not measurement noise. */
    private static final double RETARGET_RELATIVE = 0.02;
    static final FrameWorkHint NONE = new FrameWorkHint(null, null, 0L);

    private static volatile Context appContext;
    private static volatile boolean enabled = true;

    private final String label;
    private Object session;
    private long targetNs;

    private FrameWorkHint(String label, Object session, long targetNs) {
        this.label = label;
        this.session = session;
        this.targetNs = targetNs;
    }

    /** Records the application context and reads the QA switch. */
    static void configure(Context context) {
        if (context == null) return;
        Context application = context.getApplicationContext();
        appContext = application != null ? application : context;
        boolean on = true;
        try {
            on = Settings.Global.getInt(context.getContentResolver(), GLOBAL, 1) != 0;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        enabled = on;
    }

    /** A session for the calling thread, or {@link #NONE}. */
    static FrameWorkHint forCurrentThread(String label, long targetNs) {
        Context context = appContext;
        if (!enabled || context == null || targetNs <= 0L ||
                Build.VERSION.SDK_INT < 31) return NONE;
        int tid = android.os.Process.myTid();
        Object created = Api31.create(context, tid, targetNs);
        if (created == null) {
            Log.i(TAG, "Work hint unavailable thread=" + label + " sdk=" +
                    Build.VERSION.SDK_INT);
            return NONE;
        }
        Log.i(TAG, "Work hint session thread=" + label + " tid=" + tid +
                " targetUs=" + targetNs / 1000L);
        return new FrameWorkHint(label, created, targetNs);
    }

    /**
     * This thread's CPU time, or -1. Work is reported as CPU time: a swap or
     * fence wait on a busy GPU, or an audio write that blocks, is not work a
     * faster CPU clock would shorten, and counting it would hold the clock
     * up for nothing (heat and fan noise).
     */
    static long threadCpuNs() {
        return android.os.Debug.threadCpuTimeNanos();
    }

    /** CPU time since {@link #threadCpuNs()} returned {@code startNs}, or 0. */
    static long cpuSince(long startNs) {
        if (startNs < 0L) return 0L;
        long now = android.os.Debug.threadCpuTimeNanos();
        return now > startNs ? now - startNs : 0L;
    }

    /** Follows a new frame budget; small drifts keep the current target. */
    void retarget(long ns) {
        Object current = session;
        if (current == null || ns <= 0L) return;
        if (Math.abs((double) ns / targetNs - 1.0) < RETARGET_RELATIVE) return;
        if (Api31.target(current, ns)) {
            targetNs = ns;
        } else {
            drop("retarget");
        }
    }

    /** Reports one frame's CPU work on this thread. */
    void report(long actualNs) {
        Object current = session;
        if (current == null || actualNs <= 0L) return;
        if (!Api31.report(current, actualNs)) drop("report");
    }

    void close() {
        Object current = session;
        session = null;
        if (current != null) Api31.close(current);
    }

    private void drop(String operation) {
        Object current = session;
        session = null;
        if (current != null) Api31.close(current);
        Log.w(TAG, "Work hint session dropped thread=" + label + " after=" + operation);
    }

    /** Keeps API-31 types out of the min-21 outer class. */
    private static final class Api31 {
        static Object create(Context context, int tid, long targetNs) {
            try {
                PerformanceHintManager manager =
                        context.getSystemService(PerformanceHintManager.class);
                if (manager == null) return null;
                return manager.createHintSession(new int[]{tid}, targetNs);
            } catch (RuntimeException unavailable) {
                return null;
            }
        }

        static boolean target(Object session, long ns) {
            try {
                ((PerformanceHintManager.Session) session).updateTargetWorkDuration(ns);
                return true;
            } catch (RuntimeException failure) {
                return false;
            }
        }

        static boolean report(Object session, long ns) {
            try {
                ((PerformanceHintManager.Session) session).reportActualWorkDuration(ns);
                return true;
            } catch (RuntimeException failure) {
                return false;
            }
        }

        static void close(Object session) {
            try { ((PerformanceHintManager.Session) session).close(); }
            catch (RuntimeException ignored) {}
        }
    }
}
