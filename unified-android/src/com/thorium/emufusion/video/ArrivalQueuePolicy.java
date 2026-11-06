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
 * <p>The work here is arrival to the swap's return, on the CPU. The source's target
 * wait covers it and a margin; an image too close to the latch goes the usual way,
 * through its callback.</p>
 */
public final class ArrivalQueuePolicy {
    /** Until measured: arrival to the swap's return. */
    public static final long INITIAL_WORK_NS = 3_000_000L;
    public static final long MARGIN_NS = 700_000L;
    private static final double DECAY = 1.0 / 64.0;

    private double workNs = INITIAL_WORK_NS;
    private long presents, misses;

    /** Arrival to the swap's return: follows peaks at once, falls slowly. */
    public void observeWork(long ns) {
        if (ns <= 0L) return;
        workNs = ns > workNs ? ns : workNs + DECAY * (ns - workNs);
    }

    /** How long before the latch the source's images should arrive. */
    public long targetWaitNs() { return Math.round(workNs) + MARGIN_NS; }

    /**
     * @param arrivedNs the image's arrival
     * @param callbackNs the last vsync callback
     * @param latchNs the compositor's next latch after nowNs
     * @return whether the image goes to that latch now
     */
    public boolean present(long nowNs, long arrivedNs, long callbackNs, long latchNs, long periodNs) {
        if (periodNs <= 0L || arrivedNs <= 0L || callbackNs <= 0L || latchNs <= nowNs) return false;
        // The latch must follow the last callback: a later one belongs to the next callback.
        if (latchNs - callbackNs >= periodNs) return false;
        return latchNs - nowNs >= Math.round(workNs) - (nowNs - arrivedNs) + MARGIN_NS / 2L;
    }

    public void presented() { ++presents; }
    public void missed() { ++misses; }
    public long presents() { return presents; }
    public long misses() { return misses; }
    public long workNs() { return Math.round(workNs); }
}
