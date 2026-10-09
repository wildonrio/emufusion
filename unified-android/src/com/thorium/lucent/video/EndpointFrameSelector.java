package com.thorium.lucent.video;

/**
 * Selects emulator callbacks for the temporal endpoint FIFO.
 *
 * <p>Pixel-change detection owns source-tier measurement; this class owns the
 * callback clock. Consequently an unchanged image can still advance a stable
 * source timeline, while a 60-Hz callback stream for a 30-Hz game is
 * deterministically decimated to 30 endpoints. The selector emits at most one
 * endpoint for an input callback and never catches up after a pause.</p>
 */
public final class EndpointFrameSelector {
    private long lastRawTimestampNs;
    private long nextTimestampNs;
    private long selectedTimestampNs;
    private double sourceHz;

    public boolean select(long timestampNs, int requestedSourceFps) {
        return select(timestampNs, (double) requestedSourceFps);
    }

    public boolean select(long timestampNs, double requestedSourceHz) {
        if (timestampNs <= 0L || !Double.isFinite(requestedSourceHz) ||
                requestedSourceHz <= 0.0) return false;
        double fps = Math.max(1.0, requestedSourceHz);
        long periodNs = Math.max(1L,
                Math.round(1_000_000_000.0 / fps));
        long rawDeltaNs = lastRawTimestampNs == 0L ? 0L :
                timestampNs - lastRawTimestampNs;
        lastRawTimestampNs = timestampNs;
        if (Double.doubleToLongBits(sourceHz) != Double.doubleToLongBits(fps) ||
                nextTimestampNs <= 0L || rawDeltaNs <= 0L ||
                rawDeltaNs > Math.max(100_000_000L, periodNs * 4L)) {
            sourceHz = fps;
            selectedTimestampNs = timestampNs;
            nextTimestampNs = saturatingAdd(timestampNs, periodNs);
            return true;
        }
        long toleranceNs = Math.min(8_000_000L,
                Math.max(0L, rawDeltaNs / 2L));
        long selectedTimeNs = saturatingAdd(timestampNs, toleranceNs);
        if (selectedTimeNs < nextTimestampNs) return false;
        // The selected texture owns this immutable producer timestamp.  The
        // deadline decides WHETHER to retain it, never what time it represents.
        // Replacing it with the ideal deadline fabricated adjacency after a
        // missed callback and made temporal phase describe the scheduler
        // rather than the two images actually retained.
        selectedTimestampNs = timestampNs;
        // Consume exactly one source-clock slot for exactly one producer
        // callback. Skipping several ideal deadlines here used to relabel the
        // following retained image as an adjacent endpoint even though its
        // timestamp jumped by 2-13 source periods (physically reproduced on
        // Dolphin/Metroid Prime). The renderer correctly rejected that false
        // adjacency and repeatedly tore down an otherwise healthy 60->120
        // timeline. A short callback delay is instead absorbed by the
        // already-required endpoint FIFO; this selector still emits at most
        // one endpoint per callback and the pause guard above still resets a
        // genuinely discontinued stream, so no visible catch-up burst is
        // authorized.
        nextTimestampNs = saturatingAdd(nextTimestampNs, periodNs);
        return true;
    }

    public void reset() {
        lastRawTimestampNs = 0L;
        nextTimestampNs = 0L;
        selectedTimestampNs = 0L;
        sourceHz = 0.0;
    }

    public double sourceHz() { return sourceHz; }
    public long selectedTimestampNs() { return selectedTimestampNs; }

    private static long saturatingAdd(long left, long right) {
        if (right > 0L && left > Long.MAX_VALUE - right) return Long.MAX_VALUE;
        if (right < 0L && left < Long.MIN_VALUE - right) return Long.MIN_VALUE;
        return left + right;
    }
}
