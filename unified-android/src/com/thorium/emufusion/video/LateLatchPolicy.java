package com.thorium.emufusion.video;

/**
 * Presents a paced source's generated image as soon as it is finished, in
 * time for the compositor latch after the last vsync callback, instead of at
 * the next callback.
 *
 * <p>The app's vsync comes about 5.5 ms before the Thor's latch at 120 Hz, a
 * lead for work a prepared frame no longer has to do at its callback. A core
 * whose phase the source lock controls can deliver each image a little before
 * the latch rather than a little before the callback: the image is then on the
 * panel the work plus 1.8 ms after it arrives, against about 9 ms at the
 * callback. The real image follows a scan later as before.</p>
 *
 * <p>Only when the work has been finishing in time: a miss is a two-scan
 * interval, so the source's target wait covers the measured work plus a margin
 * and an image too close to the latch goes the usual way, through its callback.</p>
 */
public final class LateLatchPolicy {
    /** Until measured: a generated image at the panel's size, arrival to GPU done. */
    public static final long INITIAL_WORK_NS = 3_000_000L;
    public static final long MARGIN_NS = 700_000L;
    private static final double DECAY = 1.0 / 64.0;

    private double workNs = INITIAL_WORK_NS;
    private long presents, misses, samples;

    /** Arrival to the generated image's GPU work done: follows peaks at once, falls slowly. */
    public void observeWork(long ns) {
        if (ns <= 0L) return;
        ++samples;
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
        return nowNs - arrivedNs + (latchNs - nowNs) >= targetWaitNs() - MARGIN_NS / 2L &&
                latchNs - nowNs >= Math.round(workNs) - (nowNs - arrivedNs) + MARGIN_NS / 2L;
    }

    public void presented() { ++presents; }
    public void missed() { ++misses; }
    public long presents() { return presents; }
    public long misses() { return misses; }
    public long workNs() { return Math.round(workNs); }
}
