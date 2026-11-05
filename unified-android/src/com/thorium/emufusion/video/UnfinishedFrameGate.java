package com.thorium.emufusion.video;

/**
 * Decides whether a frame still on the GPU at its compositor latch stays out
 * of that latch.
 *
 * <p>The Thor's compositor latches unsignaled buffers
 * (debug.sf.latch_unsignaled=1) and its display has two steady states: fast,
 * where a frame latched at L is on the panel at the next scan (L + 1.8 ms),
 * and pipelined, a scan later. A frame whose GPU work ends after that next
 * scan holds the display's commit past it, so the commit lands a scan late
 * and every later commit queues behind it: one late frame leaves all frames
 * 8.3 ms later until a refresh passes with nothing new (42-265 frames per
 * stall in Eden play, 3.2.153). Kept out of the latch, the late frame costs one
 * two-scan interval and no lasting latency.
 *
 * <p>In the pipelined state a late frame has a whole scan more and nothing is
 * withheld. A frame that is late every time cannot be withheld every time:
 * half the output would go, so withheld frames are spaced and the spacing
 * grows while they keep coming; past it the frame is queued as before.
 */
public final class UnfinishedFrameGate {
    public static final long MIN_SPACING_NS = 2_000_000_000L;
    public static final long MAX_SPACING_NS = 32_000_000_000L;

    /** The pipelined state lasts this long before a generated frame is left out to end it. */
    public static final long DRAIN_AFTER_NS = 2_000_000_000L;
    /** At most one such frame in this time: each is a two-scan interval. */
    public static final long DRAIN_SPACING_NS = 16_000_000_000L;

    private boolean fast;
    private boolean known;
    private long pipelinedSinceNs;
    private long lastDrainNs = Long.MIN_VALUE;
    private long drains;
    private long spacingNs = MIN_SPACING_NS;
    private long lastWithheldNs = Long.MIN_VALUE;
    private long withheld, refused;

    /** A frame reached the panel: was it shown in the scan right after its latch? */
    public void observe(long latchNs, long actualNs, long periodNs) {
        if (latchNs <= 0L || actualNs <= 0L || periodNs <= 0L) return;
        boolean now = actualNs - latchNs < periodNs * 3L / 4L;
        if (!now && (fast || !known)) pipelinedSinceNs = actualNs;
        fast = now;
        known = true;
    }

    /**
     * A frame about to be queued while the display is in the pipelined state:
     * whether it stays out, so a refresh passes with nothing new and the
     * display returns to the fast state, a scan sooner for every later frame.
     */
    public boolean drain(long nowNs) {
        if (fast || !known || nowNs - pipelinedSinceNs < DRAIN_AFTER_NS ||
                (lastDrainNs != Long.MIN_VALUE && nowNs - lastDrainNs < DRAIN_SPACING_NS))
            return false;
        lastDrainNs = nowNs;
        ++drains;
        return true;
    }

    public long drains() { return drains; }

    /** Frames wait for their GPU work only while a late one would change the state. */
    public boolean fast() { return fast; }

    /**
     * A frame is still on the GPU at its latch.
     * @return whether it stays out of the latch
     */
    public boolean withhold(long nowNs) {
        if (lastWithheldNs != Long.MIN_VALUE && nowNs - lastWithheldNs < spacingNs) {
            ++refused;
            return false;
        }
        if (lastWithheldNs != Long.MIN_VALUE) {
            long since = nowNs - lastWithheldNs;
            if (since < 2L * spacingNs) spacingNs = Math.min(MAX_SPACING_NS, 2L * spacingNs);
            else if (since >= 8L * spacingNs) spacingNs = Math.max(MIN_SPACING_NS, spacingNs / 2L);
        }
        lastWithheldNs = nowNs;
        ++withheld;
        return true;
    }

    public long withheld() { return withheld; }
    public long refused() { return refused; }
    public long spacingNs() { return spacingNs; }
}
