package com.thorium.emufusion.video;

/**
 * Ends the compositor's pipelined state where that lasts.
 *
 * <p>The Thor's compositor latches unsignaled buffers and its display has two
 * steady states: fast, where a frame latched at L is on the panel at the next
 * scan (L + 1.8 ms), and pipelined, a scan later. One frame still on the GPU
 * after its scan moves the display to pipelined, and only a refresh with nothing
 * new moves it back, so a perfectly smooth run stays 8.3 ms late for good
 * (Thor, 2026-11-06: NES 100% on cadence at 17.4 / 25.7 ms, against 9.1 / 17.4 ms
 * in the fast state; which of the two a run gets is chance).</p>
 *
 * <p>Leaving out one generated frame gives that refresh, at the price of one
 * two-scan interval, and the move back to pipelined costs another. It pays only
 * if the fast state then lasts: NSMBU Deluxe's lasted 0.2-4 s (2026-11-06, without
 * a late frame at the moves, so its compositor may be what misses), NES's 5-11 s.
 * So the spacing starts at {@link #MIN_SPACING_NS}, which keeps a full cycle to
 * four two-scan intervals in 30 s, doubles when the fast state lasted under
 * {@link #SHORT_STAY_NS}, and halves when it lasted longer. Halving only after a
 * stay as long as the spacing left a game that stays 5-11 s at a 60-s spacing
 * earned at its start, late for most of the minute (Mega Drive, NES, 2026-11-07).</p>
 */
public final class CompositorStateDrain {
    /** The pipelined state lasts this long before a frame is left out. */
    public static final long DRAIN_AFTER_NS = 2_000_000_000L;
    public static final long MIN_SPACING_NS = 15_000_000_000L;
    public static final long MAX_SPACING_NS = 240_000_000_000L;
    public static final long SHORT_STAY_NS = 4_000_000_000L;
    /** Still pipelined this long after a drain: it did nothing. */
    public static final long VERDICT_NS = 2_000_000_000L;

    private boolean fast, known;
    private long pipelinedSinceNs, fastSinceNs;
    private long lastDrainNs = Long.MIN_VALUE;
    private long spacingNs = MIN_SPACING_NS;
    private boolean awaitingVerdict, retried;
    private long drains;

    /** A frame reached the panel: was it shown in the scan right after its latch? */
    public void observe(long latchNs, long actualNs, long periodNs) {
        if (latchNs <= 0L || actualNs <= 0L || periodNs <= 0L) return;
        boolean now = actualNs - latchNs < periodNs * 3L / 4L;
        if (known && now && !fast) fastSinceNs = actualNs;
        if (!now && (fast || !known)) {
            pipelinedSinceNs = actualNs;
            if (known && awaitingVerdict) {
                awaitingVerdict = false;
                retried = false;
                long lasted = actualNs - fastSinceNs;
                if (lasted < SHORT_STAY_NS) spacingNs = Math.min(MAX_SPACING_NS, spacingNs * 2L);
                else spacingNs = Math.max(MIN_SPACING_NS, spacingNs / 2L);
            }
        }
        fast = now;
        known = true;
    }

    /**
     * A generated frame about to be queued: whether it stays out, ending the pipelined state.
     * One that brings no fast state within {@link #VERDICT_NS} is tried once more straight
     * away; only a second failure doubles the spacing. Doubling at once left NES slow for whole
     * 16-s windows after a drain early in a run that did nothing, while the next, 30 s later,
     * worked (Thor, 2026-11-07, system trace).
     */
    public boolean drain(long nowNs) {
        if (fast || !known || nowNs - pipelinedSinceNs < DRAIN_AFTER_NS) return false;
        if (awaitingVerdict) {
            if (nowNs - lastDrainNs < VERDICT_NS) return false;
            // The last one never reached the fast state.
            awaitingVerdict = false;
            if (!retried) {
                retried = true;
                return leaveOut(nowNs);
            }
            retried = false;
            spacingNs = Math.min(MAX_SPACING_NS, spacingNs * 2L);
            return false;
        }
        if (lastDrainNs != Long.MIN_VALUE && nowNs - lastDrainNs < spacingNs) return false;
        return leaveOut(nowNs);
    }

    private boolean leaveOut(long nowNs) {
        lastDrainNs = nowNs;
        awaitingVerdict = true;
        ++drains;
        return true;
    }

    public boolean fast() { return fast; }
    public long drains() { return drains; }
    public long spacingNs() { return spacingNs; }
}
