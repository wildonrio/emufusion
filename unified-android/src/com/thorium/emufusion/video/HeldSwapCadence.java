package com.thorium.emufusion.video;

/**
 * Lets one late pair give back the extra scan of a source whose frames are drawn
 * a scan ahead and queued held (DisplayFrameGenerator.holdSwap).
 *
 * <p>The firmware pins Cemu's images to one phase, so an image that overruns
 * comes a whole scan late and the next one on time. With the extra scan kept,
 * that is 3, 3 and 1 scans between frames (Wind Waker HD, 2026-11-06: 34 of 55
 * off intervals in 33 s). The frame can still make its slot on the rhythm by
 * going without the extra scan: its draw then starts a scan later, the
 * same as a frame with no extra scan.</p>
 *
 * <p>Only one pair at a time. Without the extra scan a frame has no more time
 * than the source that runs at no depth at all, and a source running there is
 * back to one scan off whenever the GPU is busy, so the next pair returns to
 * the extra scan even if that costs one long interval.</p>
 */
public final class HeldSwapCadence {
    private long startedNs;
    private long pairs;

    public long pairs() { return pairs; }

    /** Whether a frame planned for {@code plannedNs} should try for a scan sooner. */
    public boolean wantsSooner(long nowNs, long plannedNs, long lastTargetNs, long outputNs, long panelNs) {
        if (lastTargetNs <= 0L || outputNs <= 0L || panelNs <= 0L) return false;
        if (plannedNs <= lastTargetNs + outputNs + panelNs / 2L) return false;
        if (startedNs == 0L) return true;
        long since = nowNs - startedNs;
        return since <= outputNs + outputNs / 2L || since >= 3L * outputNs;
    }

    /** A frame was queued; {@code sooner} says whether it went without the extra scan. */
    public void committed(long nowNs, boolean sooner, long outputNs) {
        if (!sooner) return;
        if (startedNs == 0L || nowNs - startedNs > outputNs + outputNs / 2L) {
            startedNs = nowNs;
            ++pairs;
        }
    }
}
