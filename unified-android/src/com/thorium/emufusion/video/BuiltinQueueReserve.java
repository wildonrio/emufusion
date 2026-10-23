package com.thorium.emufusion.video;

/**
 * How far ahead the built-in path queues its frames: the earliest compositor
 * deadline it can make, or one or two scans later, learned from what reached
 * the panel.
 *
 * <p>On the Thor at 120 Hz the compositor latches ~10 ms before a frame's
 * display time and the emulator shares the GPU: 3DS frames finished 3-6 ms
 * before their slot still landed one scan late (2026-10-11), so under load the
 * path targets a scan later instead of missing unevenly.</p>
 *
 * <p>3.2.89 replaces the old continuous reserve (+1 ms per late frame, -0.5 ms
 * per 1200 on-time frames) after Thor runs on 2026-10-23. A short disturbance
 * -- the QA screen recorder starting, in play a notification or volume overlay
 * composed on the GPU -- raised it to 5.5 ms in half a second and the slow
 * decay then kept every frame a scan (8.3 ms) later for most of a minute
 * (Ocarina of Time: 20.3 -> 26-29 ms to the first generated image). Two
 * isolated misses six seconds apart left NSMBU Deluxe at 3 ms, where the
 * callback's own timing decided each frame's scan: depth alternated and so
 * did latency (19 / 27 ms). Now:</p>
 * <ul>
 * <li>Depth is a whole number of scans counted from the vsync callback
 * ({@link #reserveNs}), so callback jitter cannot move a frame between
 * scans.</li>
 * <li>It deepens on a burst ({@link #MISSES_TO_DEEPEN} late frames within
 * {@link #MISS_WINDOW_NS}), not on isolated misses, and ignores the frames
 * already queued when it changed.</li>
 * <li>It gives a scan back when frames show they would have met the latch a
 * scan earlier: rendering is submitted at the same callback whatever the
 * target, so a frame that finished well before the previous latch would have
 * been shown a scan sooner. A late frame soon after that restores the depth at
 * once and doubles the evidence the next recovery needs, so the depth cannot
 * flip-flop under a lasting load.</li>
 * </ul>
 */
public final class BuiltinQueueReserve {
    /** Queue handoff margin before the compositor's deadline. */
    public static final long MIN_NS = 1_000_000L;
    public static final int MAX_EXTRA_SCANS = 2;
    public static final int MISSES_TO_DEEPEN = 3;
    public static final long MISS_WINDOW_NS = 2_000_000_000L;
    /** Frames shown within this time of a change were planned before it. */
    public static final long SETTLE_NS = 250_000_000L;
    /** Rendering must finish this far ahead of the previous latch to count. */
    public static final long EARLY_MARGIN_NS = 1_000_000L;
    /** ~2 s of frames at 120 Hz. */
    public static final int RECOVERY_FRAMES = 240;
    public static final int MAX_RECOVERY_FRAMES = 3840;
    /** Without latch timestamps, on-time frames alone (~20 s) recover a scan. */
    public static final int BLIND_RECOVERY_FRAMES = 2400;
    /** A late frame within this time of a recovery means it did not hold. */
    public static final long RECOVERY_HOLD_NS = 10_000_000_000L;

    public enum Change { NONE, DEEPENED, RECOVERED, RESTORED }

    private int extraScans;
    private final long[] missNs = new long[MISSES_TO_DEEPEN];
    private int misses;
    private long changedAtNs, deepenedAtNs;
    private int earlierFrames;
    private int recoveryFrames = RECOVERY_FRAMES;
    private long recoveredAtNs;
    private long deepenings, recoveries, failedRecoveries;

    public int extraScans() { return extraScans; }
    public long deepenings() { return deepenings; }
    public long recoveries() { return recoveries; }
    public long failedRecoveries() { return failedRecoveries; }
    public int recoveryFrames() { return recoveryFrames; }

    /**
     * The reserve to plan a frame with (PhysicalPresentationDeadline.nextEgl):
     * the handoff margin, and each extra scan counted from the callback rather
     * than from when planning happened to run.
     */
    public long reserveNs(long callbackNs, long planNowNs, long intervalNs) {
        if (extraScans == 0 || intervalNs <= 0L) return MIN_NS;
        if (callbackNs <= 0L || planNowNs < callbackNs) return MIN_NS + extraScans * intervalNs;
        return Math.max(MIN_NS, callbackNs + MIN_NS + extraScans * intervalNs - planNowNs);
    }

    /**
     * One frame's physical result.
     *
     * @param late the frame reached the panel after its slot
     * @param renderCompleteNs its GPU completion, 0 when unknown
     * @param latchNs the compositor's latch of it, 0 when unknown
     */
    public Change observe(boolean late, long desiredNs, long actualNs, long renderCompleteNs,
                          long latchNs, long panelPeriodNs) {
        if (panelPeriodNs <= 0L) return Change.NONE;
        long nowNs = actualNs > 0L ? actualNs : desiredNs;
        if (late) {
            earlierFrames = 0;
            // Shown late, and rendering finished close enough to the slot that
            // more lead would have made it: a frame rendered long before its
            // slot and still late is the compositor's miss, not ours.
            boolean fromRendering = renderCompleteNs > 0L && actualNs > 0L &&
                    actualNs - desiredNs >= panelPeriodNs / 2L &&
                    renderCompleteNs > desiredNs - 2L * panelPeriodNs;
            // Frames queued at the shallower depth before a deepening.
            if (!fromRendering || within(deepenedAtNs, nowNs)) return Change.NONE;
            if (recoveredAtNs != 0L) {
                boolean failed = nowNs - recoveredAtNs < RECOVERY_HOLD_NS;
                recoveredAtNs = 0L;
                if (failed && extraScans < MAX_EXTRA_SCANS) {
                    ++failedRecoveries;
                    recoveryFrames = Math.min(MAX_RECOVERY_FRAMES, 2 * recoveryFrames);
                    change(nowNs, 1);
                    return Change.RESTORED;
                }
            }
            int kept = 0;
            for (int i = 0; i < misses; ++i)
                if (nowNs - missNs[i] < MISS_WINDOW_NS) missNs[kept++] = missNs[i];
            misses = kept;
            if (misses == MISSES_TO_DEEPEN) {
                System.arraycopy(missNs, 1, missNs, 0, MISSES_TO_DEEPEN - 1);
                --misses;
            }
            missNs[misses++] = nowNs;
            if (misses < MISSES_TO_DEEPEN || extraScans >= MAX_EXTRA_SCANS) return Change.NONE;
            ++deepenings;
            change(nowNs, 1);
            return Change.DEEPENED;
        }
        if (recoveredAtNs != 0L && nowNs - recoveredAtNs >= RECOVERY_HOLD_NS) {
            recoveredAtNs = 0L;
            recoveryFrames = RECOVERY_FRAMES;
        }
        // Frames queued at the previous depth are no evidence for this one.
        if (extraScans == 0 || within(changedAtNs, nowNs)) {
            earlierFrames = 0;
            return Change.NONE;
        }
        boolean timestamps = renderCompleteNs > 0L && latchNs > 0L;
        boolean earlierScanMet = !timestamps ||
                latchNs - panelPeriodNs - renderCompleteNs >= EARLY_MARGIN_NS;
        if (!earlierScanMet) {
            earlierFrames = 0;
            return Change.NONE;
        }
        if (++earlierFrames < (timestamps ? recoveryFrames : BLIND_RECOVERY_FRAMES))
            return Change.NONE;
        ++recoveries;
        recoveredAtNs = nowNs;
        change(nowNs, -1);
        return Change.RECOVERED;
    }

    private static boolean within(long changeNs, long nowNs) {
        return changeNs != 0L && nowNs - changeNs < SETTLE_NS;
    }

    private void change(long nowNs, int scans) {
        extraScans = Math.max(0, Math.min(MAX_EXTRA_SCANS, extraScans + scans));
        changedAtNs = nowNs;
        if (scans > 0) deepenedAtNs = nowNs;
        misses = 0;
        earlierFrames = 0;
    }
}
