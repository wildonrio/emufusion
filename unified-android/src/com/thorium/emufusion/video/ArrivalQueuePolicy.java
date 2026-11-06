package com.thorium.emufusion.video;

/**
 * Queues a paced source's generated image as soon as its pair is formed, in time
 * for the compositor latch after the last vsync callback, without waiting for the
 * GPU to finish it.
 *
 * <p>The Thor's compositor latches unsignaled buffers. In its pipelined state a
 * frame latched at L reaches the panel at L + 10.1 ms, so its GPU work has about
 * 10 ms after the latch. Waiting for the next callback, which comes 5.5 ms before
 * the latch, adds nothing there: Eden's images arrive about 4.5 ms before that
 * callback and reach the panel about 19.4 ms later. An image that arrives just
 * before the latch can take the same latch: the time to encode it, then 10.1 ms.
 * It finishes after the fast state's scan, so the display stays pipelined, a
 * steady state with no moves between the two (each move is a two-scan interval).
 * NSMBU Deluxe leaves the fast state after 0.2-4 s whatever the lead (2026-11-06),
 * so that state is not one a heavy engine can keep anyway.</p>
 *
 * <p>Arrival to the swap's return takes about 2.7 ms and the planner wants 1 ms
 * before the latch, so the source's images must arrive that much plus their jitter
 * before it: a target of 3.5 ms left nearly every image refused (NSMBU Deluxe,
 * 2026-11-06), so the target is a QA value in {@code emufusion_framegen_arrival_queue}.
 * An image with less than {@link #MIN_TO_LATCH_NS} left goes the usual way, through
 * its callback. The target is fixed: following a measured peak locked the first
 * version out for a whole run after one 6.5-ms sample.</p>
 */
public final class ArrivalQueuePolicy {
    public static final long MIN_TO_LATCH_NS = 800_000L;
    private static final double SMOOTHING = 1.0 / 64.0;

    private double workNs = 3_000_000.0;
    private long presents, misses;

    /** Arrival to the swap's return, for the log. */
    public void observeWork(long ns) {
        if (ns > 0L) workNs += SMOOTHING * (ns - workNs);
    }

    /**
     * @param nowNs after the solve's encoding
     * @param callbackNs the last vsync callback
     * @param latchNs the compositor's next latch after nowNs
     * @return whether the image goes to that latch now
     */
    public boolean present(long nowNs, long callbackNs, long latchNs, long periodNs) {
        if (periodNs <= 0L || callbackNs <= 0L || latchNs <= nowNs) return false;
        // The latch must follow the last callback: a later one belongs to the next callback.
        if (latchNs - callbackNs >= periodNs) return false;
        return latchNs - nowNs >= MIN_TO_LATCH_NS;
    }

    public void presented() { ++presents; }
    public void missed() { ++misses; }
    public long presents() { return presents; }
    public long misses() { return misses; }
    public long workNs() { return Math.round(workNs); }
}
