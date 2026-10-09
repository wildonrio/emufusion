package com.thorium.preview.game;

import com.thorium.lucent.video.PhysicalPresentationCadence;

import java.util.ArrayDeque;

/** Nonblocking owner of EGL_ANDROID_get_frame_timestamps evidence. */
final class PhysicalPresentationTracker implements AutoCloseable {
    private static final int NATIVE_READY = 1;
    private static final int NATIVE_DROPPED = 2;
    private static final int NATIVE_UNAVAILABLE = 3;
    private static final int MAX_POLLS_PER_CALLBACK = 8;

    private static boolean libraryLoaded;

    private final long[] nextRow = new long[1];
    private final long[] pollRow = new long[10];
    private final PhysicalPresentationCadence cadence =
            new PhysicalPresentationCadence();
    private final ArrayDeque<Event> completed = new ArrayDeque<>();
    private long handle;
    private long preparedFrameId;
    private boolean prepared;
    private boolean readyTimingEnabled;
    private int lastNativeFailure;

    static synchronized PhysicalPresentationTracker create() {
        if (!libraryLoaded) {
            System.loadLibrary("lucent_framegen_timer");
            libraryLoaded = true;
        }
        long value = nativeCreate();
        return value == 0L ? null : new PhysicalPresentationTracker(value);
    }

    private PhysicalPresentationTracker(long value) { handle = value; }

    /** Must be called immediately before the matching eglSwapBuffers. */
    boolean prepareFrame() {
        prepared = false;
        if (handle == 0L) return false;
        int status = nativeNext(handle, nextRow);
        if (status != NATIVE_READY) {
            fail(status);
            return false;
        }
        preparedFrameId = nextRow[0];
        prepared = true;
        return true;
    }

    /** Exact EGL frame ID reserved for the next matching swap. */
    long preparedFrameId() { return prepared ? preparedFrameId : 0L; }

    /** Commits the prepared ID only after eglSwapBuffers succeeds. */
    boolean commitPrepared(int scansPerOutput, long measuredPanelPeriodNs) {
        if (!prepared || handle == 0L) return false;
        prepared = false;
        int status = nativeCommit(handle, preparedFrameId, scansPerOutput,
                measuredPanelPeriodNs);
        if (status == NATIVE_READY) return true;
        fail(status);
        return false;
    }

    void cancelPrepared() { prepared = false; }

    /** Dense-only opt-in: Off and external presentation avoid optional per-frame queries. */
    void setReadyTimingEnabled(boolean enabled) {
        if (handle == 0L || readyTimingEnabled == enabled) return;
        if (nativeSetReadyTimingEnabled(handle, enabled)) readyTimingEnabled = enabled;
    }

    /** Polls already-submitted frames only; native never waits for scanout. */
    void poll() {
        if (handle == 0L) return;
        for (int count = 0; count < MAX_POLLS_PER_CALLBACK; ++count) {
            int status = nativePoll(handle, pollRow);
            if (status == 0) return;
            if (status < 0) {
                fail(status);
                return;
            }
            int scans = exactInt(pollRow[2]);
            long panelPeriodNs = pollRow[3];
            if (status == NATIVE_DROPPED) {
                cadence.recordDropped(scans, panelPeriodNs);
                completed.addLast(Event.dropped(
                        pollRow[0], scans, panelPeriodNs));
                continue;
            }
            if (status == NATIVE_UNAVAILABLE) {
                cadence.recordUnavailable(scans, panelPeriodNs);
                completed.addLast(Event.unavailable(
                        pollRow[0], scans, panelPeriodNs));
                continue;
            }
            if (status != NATIVE_READY ||
                    !cadence.recordPresented(pollRow[1], scans, panelPeriodNs)) {
                fail(status == NATIVE_READY ? -6 : status);
                return;
            }
            completed.addLast(Event.presented(
                    pollRow[0], pollRow[1], scans, panelPeriodNs,
                    exactInt(pollRow[5]), pollRow[6], pollRow[7], pollRow[8], pollRow[9]));
        }
    }

    /** Optional [next composition deadline, interval, composition-to-present latency]. */
    boolean compositorTiming(long[] output) {
        return handle != 0L && output != null && output.length >= 3 &&
                nativeCompositorTiming(handle, output);
    }

    Event takeCompletedEvent() { return completed.pollFirst(); }

    double actualHz(int scansPerOutput, long measuredPanelPeriodNs) {
        return handle == 0L ? 0.0 :
                cadence.actualHz(scansPerOutput, measuredPanelPeriodNs);
    }

    boolean cadenceQualified(int scansPerOutput, long measuredPanelPeriodNs) {
        return handle != 0L &&
                cadence.qualified(scansPerOutput, measuredPanelPeriodNs);
    }

    int sampleCount() { return cadence.sampleCount(); }
    String lastRejection() { return cadence.lastRejection(); }
    long physicallyPresentedCount() { return cadence.successfulPresents(); }
    long compositorDroppedCount() { return cadence.droppedPresents(); }
    long unavailablePresentationCount() {
        return cadence.unavailablePresents();
    }
    int pendingCount() { return handle == 0L ? 0 : nativePending(handle); }
    boolean available() { return handle != 0L; }
    int lastNativeFailure() { return lastNativeFailure; }

    @Override public void close() {
        long value = handle;
        handle = 0L;
        prepared = false;
        completed.clear();
        if (value != 0L) nativeDestroy(value);
    }

    private void fail(int status) {
        lastNativeFailure = status;
        close();
    }

    private static int exactInt(long value) {
        if (value < Integer.MIN_VALUE || value > Integer.MAX_VALUE)
            return -1;
        return (int)value;
    }

    static final class Event {
        enum Kind { PRESENTED, DROPPED, UNAVAILABLE }

        final Kind kind;
        final long frameId;
        final long actualPresentTimeNs;
        final int scansPerOutput;
        final long panelPeriodNs;
        // Same-frame EGL driver timestamps. -2 is pending, -1 invalid; only
        // supported compositorGpuFinishedTimeNs may validly be zero (display
        // composition). Missing optional data never changes cadence accounting.
        final int readyTimestampSupportedMask;
        final long renderingCompleteTimeNs;
        final long compositionLatchTimeNs;
        final long compositionStartTimeNs;
        final long compositorGpuFinishedTimeNs;

        private Event(Kind kind, long frameId, long actualPresentTimeNs,
                      int scansPerOutput, long panelPeriodNs, int supportedMask,
                      long renderingCompleteTimeNs, long compositionLatchTimeNs,
                      long compositionStartTimeNs, long compositorGpuFinishedTimeNs) {
            if (kind == null || frameId <= 0L || scansPerOutput < 0 ||
                    panelPeriodNs <= 0L ||
                    (kind == Kind.PRESENTED) != (actualPresentTimeNs > 0L))
                throw new IllegalArgumentException(
                        "physical presentation event is invalid");
            this.kind = kind;
            this.frameId = frameId;
            this.actualPresentTimeNs = actualPresentTimeNs;
            this.scansPerOutput = scansPerOutput;
            this.panelPeriodNs = panelPeriodNs;
            this.readyTimestampSupportedMask = supportedMask;
            this.renderingCompleteTimeNs = renderingCompleteTimeNs;
            this.compositionLatchTimeNs = compositionLatchTimeNs;
            this.compositionStartTimeNs = compositionStartTimeNs;
            this.compositorGpuFinishedTimeNs = compositorGpuFinishedTimeNs;
        }

        static Event presented(long frameId, long actualPresentTimeNs,
                               int scansPerOutput, long panelPeriodNs) {
            return new Event(Kind.PRESENTED, frameId, actualPresentTimeNs,
                    scansPerOutput, panelPeriodNs, 0, -1L, -1L, -1L, -1L);
        }

        static Event presented(long frameId, long actualPresentTimeNs,
                               int scansPerOutput, long panelPeriodNs, int supportedMask,
                               long renderingCompleteTimeNs, long compositionLatchTimeNs,
                               long compositionStartTimeNs, long compositorGpuFinishedTimeNs) {
            return new Event(Kind.PRESENTED, frameId, actualPresentTimeNs,
                    scansPerOutput, panelPeriodNs, supportedMask, renderingCompleteTimeNs,
                    compositionLatchTimeNs, compositionStartTimeNs, compositorGpuFinishedTimeNs);
        }

        static Event dropped(long frameId, int scansPerOutput,
                             long panelPeriodNs) {
            return new Event(Kind.DROPPED, frameId, 0L,
                    scansPerOutput, panelPeriodNs, 0, -1L, -1L, -1L, -1L);
        }

        static Event unavailable(long frameId, int scansPerOutput,
                                 long panelPeriodNs) {
            return new Event(Kind.UNAVAILABLE, frameId, 0L,
                    scansPerOutput, panelPeriodNs, 0, -1L, -1L, -1L, -1L);
        }
    }

    private static native long nativeCreate();
    private static native boolean nativeCompositorTiming(long handle, long[] output);
    private static native int nativeNext(long handle, long[] output);
    private static native int nativeCommit(long handle, long frameId,
            int scansPerOutput, long measuredPanelPeriodNs);
    private static native int nativePoll(long handle, long[] output);
    private static native int nativePending(long handle);
    private static native boolean nativeSetReadyTimingEnabled(long handle, boolean enabled);
    private static native void nativeDestroy(long handle);
}
