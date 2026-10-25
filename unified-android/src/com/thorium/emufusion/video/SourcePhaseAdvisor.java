package com.thorium.emufusion.video;

/**
 * How much later a paced source could deliver its images and still have each
 * one taken up by the same panel callback: the wait between an image arriving
 * and the callback that shows its generated frame, which is latency on every
 * generated and real frame.
 *
 * <p>A source we pace (a built-in core) runs on its own clock, locked to the
 * panel's rate but at an arbitrary phase, so its images arrive anywhere in the
 * scan before the callback that takes them up. Thor 3.2.103 trace: Mega Drive
 * waited 1.5-7.2 ms, Ocarina a steady 4.1 ms, on top of 1 ms of work and the
 * compositor. Once a window of waits is steady (the clock is locked: they
 * spread less than {@link #MAX_SPREAD_NS}), the shortest one less
 * {@link #TARGET_WAIT_NS} and less the window's own spread (the arrival
 * jitter: software cores post through a render thread, and SNES frames
 * moved to arrive 1 ms early were then missing their callback by up to a
 * scan) is offered once as a delay for the source's next frame, at most half
 * a scan, and not again for {@link #HOLDOFF_WINDOWS} windows. A
 * drifting clock (a sweep of waits) is left alone. A move must show in the
 * next window (its shortest wait drops by half the move or more); a source
 * whose arrivals are set by something else returns to its old phase (Thor,
 * Ocarina on the hardware-core loop: back to 4.1 ms within seconds of each
 * 3 ms move, with a scan-late frame at some moves), so after
 * {@link #MAX_INEFFECTIVE} moves that did not hold it is left alone.</p>
 *
 * <p>Observed on the renderer thread and taken on the source's thread.</p>
 */
public final class SourcePhaseAdvisor {
    public static final int WINDOW = 60;
    /** The shortest wait kept: arrival to callback covers admission (~1 ms). */
    public static final long TARGET_WAIT_NS = 1_000_000L;
    /** Smaller gains are not worth moving the source. */
    public static final long MIN_SHIFT_NS = 1_000_000L;
    /** Waits spread wider than this are a drifting clock, not a phase. */
    public static final long MAX_SPREAD_NS = 2_500_000L;
    /** Moves the source did not keep before advice stops for good. */
    public static final int MAX_INEFFECTIVE = 2;
    /** Windows after a move before another one may be offered. */
    public static final int HOLDOFF_WINDOWS = 8;

    private final long[] waits = new long[WINDOW];
    private int count;
    private long pendingNs, pendingMinNs;
    // The last move taken and the shortest wait before it, judged on the next window.
    private long movedNs, movedFromMinNs;
    private int ineffective, holdoffWindows;
    private long shifts, shiftedNs;

    /** One newly taken-up image: arrival to the callback that took it up. */
    public synchronized void observe(long waitNs, long panelPeriodNs) {
        if (panelPeriodNs <= 0L || waitNs < 0L || waitNs > panelPeriodNs) {
            // A stall or a held image: not this source's phase.
            count = 0;
            return;
        }
        if (pendingNs > 0L || ineffective >= MAX_INEFFECTIVE) return;
        waits[count++] = waitNs;
        if (count < WINDOW) return;
        long min = Long.MAX_VALUE, max = Long.MIN_VALUE;
        for (long wait : waits) {
            min = Math.min(min, wait);
            max = Math.max(max, wait);
        }
        count = 0;
        if (movedNs > 0L) {
            if (min > movedFromMinNs - movedNs / 2L && ++ineffective >= MAX_INEFFECTIVE) return;
            movedNs = 0L;
        }
        if (holdoffWindows > 0) {
            --holdoffWindows;
            return;
        }
        long shift = Math.min(panelPeriodNs / 2L, min - TARGET_WAIT_NS - (max - min));
        if (max - min <= MAX_SPREAD_NS && shift >= MIN_SHIFT_NS) {
            pendingNs = shift;
            pendingMinNs = min;
        }
    }

    /** The delay to add to the source's next frame once, or zero. */
    public synchronized long take() {
        long delay = pendingNs;
        pendingNs = 0L;
        if (delay > 0L) {
            ++shifts;
            shiftedNs += delay;
            count = 0;
            movedNs = delay;
            movedFromMinNs = pendingMinNs;
            holdoffWindows = HOLDOFF_WINDOWS;
        }
        return delay;
    }

    public synchronized void reset() {
        count = 0;
        pendingNs = 0L;
        movedNs = 0L;
    }

    /** Whether moves stopped holding and advice ended for this source. */
    public synchronized boolean abandoned() { return ineffective >= MAX_INEFFECTIVE; }

    public synchronized long shifts() { return shifts; }
    public synchronized long shiftedNs() { return shiftedNs; }
}
