package com.thorium.emufusion.video;

/**
 * Whether the built-in path asks for a frame's present time just after its
 * slot instead of just before it, so a compositor that presents as soon as a
 * frame is ready cannot show it a scan early.
 *
 * <p>The Thor at 120 Hz (SurfaceFlinger dump, 2026-10-25): SF duration
 * 10.33 ms, longer than the 8.33 ms scan, and HWC minimum duration 0. Each
 * composition runs ~2 ms before a scan and takes buffers whose desired time
 * is before the scan after next, but the composer presents at the first scan
 * its buffers are ready for. A frame requested at its slot minus the 2 ms
 * driver lead is taken by the composition ~10 ms before the slot; if its
 * render fence has already signalled, it shows a whole scan early. Wind Waker
 * HD (Cemu, no screen recorder): 44.5% of frames early, 72.6% of intervals on
 * their two scans. A desired time half a scan after the slot is only reached
 * by the composition ~2 ms before the slot, so the frame shows in its slot
 * when ready and never earlier; frames that were on time are unchanged.</p>
 *
 * <p>A compositor that holds frames to their desired time would show every
 * frame a scan late with that request, so it is made only after frames are
 * seen early ({@link #EARLY_SHARE} of a {@link #WINDOW}-frame window), and
 * dropped for good if most frames then land late. Only early frames mixed
 * with on-time ones turn it on ({@link #SWITCH_SHARE} of the window's frames
 * change between the two): that alternation is the judder. A run of frames
 * all shown a scan early is even and sooner, and the guard would only add a
 * scan to it (SNES on the Thor: 1-2 s runs of every frame early, 99.7% of
 * intervals on their scan; Wind Waker HD: "EE.." every other source frame).</p>
 */
public final class CompositorEarlyGuard {
    public static final int WINDOW = 120;
    /** This share of a window shown a whole scan early turns the guard on. */
    public static final double EARLY_SHARE = 0.10;
    /** This share shown a whole scan late with the guard on turns it off for good. */
    public static final double LATE_SHARE = 0.50;
    /** And this share of frames must differ from the previous one (early or not). */
    public static final double SWITCH_SHARE = 0.10;

    private boolean active, disabled, previousEarly;
    private int frames, early, late, switches;
    private long activations;

    public boolean active() { return active; }
    public boolean disabled() { return disabled; }
    public long activations() { return activations; }

    /**
     * The present time to hand the driver for a frame planned for
     * {@code targetNs}: the plan's own lead-time request, or half a scan
     * after the target while the guard is on.
     */
    public long driverDesiredNs(long targetNs, long plannedDesiredNs, long panelPeriodNs) {
        return active && panelPeriodNs > 0L && targetNs > 0L ?
                targetNs + panelPeriodNs / 2L : plannedDesiredNs;
    }

    /**
     * One frame's physical result against its planned slot.
     *
     * @return whether the guard changed
     */
    public boolean observe(long desiredNs, long actualNs, long panelPeriodNs) {
        if (disabled || desiredNs <= 0L || actualNs <= 0L || panelPeriodNs <= 0L) return false;
        long off = actualNs - desiredNs;
        boolean isEarly = off <= -panelPeriodNs / 2L;
        if (isEarly) ++early;
        else if (off >= panelPeriodNs / 2L) ++late;
        if (isEarly != previousEarly) ++switches;
        previousEarly = isEarly;
        if (++frames < WINDOW) return false;
        boolean changed = false;
        if (!active && early >= EARLY_SHARE * WINDOW && switches >= SWITCH_SHARE * WINDOW) {
            active = true;
            ++activations;
            changed = true;
        } else if (active && late >= LATE_SHARE * WINDOW) {
            active = false;
            disabled = true;
            changed = true;
        }
        frames = 0;
        early = 0;
        late = 0;
        switches = 0;
        return changed;
    }
}
