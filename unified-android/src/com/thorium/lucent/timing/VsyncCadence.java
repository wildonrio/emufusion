package com.thorium.lucent.timing;

/** Counts real display ticks, rather than sleeping on an unrelated nominal clock. */
public final class VsyncCadence {
    private static final int WARMUP_TICKS = 8;
    private double declaredHz, sourceHz, panelHz;
    private int divisor;
    private long previousNs, measuredTicks, measurementStartNs;
    private long produced, consumed, latestDueNs;
    private int phase;
    private double measuredPanelPeriodNs;
    private boolean ready;
    private boolean coalescingCatchUp;

    public void configure(double declared, double source, double panel) {
        if (declaredHz == declared && sourceHz == source && panelHz == panel) return;
        declaredHz = declared;
        sourceHz = source;
        panelHz = panel;
        divisor = 0;
        if (Double.isFinite(source) && source > 1 &&
                Double.isFinite(panel) && panel > 1) {
            double scans = panel / source;
            int rounded = (int) Math.round(scans);
            if (rounded >= 1 && rounded <= 12 && Math.abs(scans - rounded) < 0.001 &&
                    DisplaySyncPolicy.permitsCoreClockCorrection(declared, panel / rounded))
                divisor = rounded;
        }
        reset();
    }

    public void reset() {
        previousNs = measurementStartNs = measuredTicks = 0;
        produced = consumed = latestDueNs = 0;
        phase = 0;
        measuredPanelPeriodNs = 0;
        ready = false;
        coalescingCatchUp = false;
    }

    public void onVsync(long timestampNs) {
        if (divisor == 0 || timestampNs <= 0) return;
        if (previousNs == 0) {
            previousNs = measurementStartNs = timestampNs;
            return;
        }
        long delta = timestampNs - previousNs;
        double nominalPeriod = 1_000_000_000.0 / panelHz;
        int ticks = (int) Math.round(delta / nominalPeriod);
        // Lost callbacks can owe several guest steps, but sleep/stale events
        // must never enqueue seconds of emulation when the device wakes.
        if (ticks < 1 || ticks > 4 ||
                Math.abs(delta - ticks * nominalPeriod) > nominalPeriod * 0.10) {
            reset();
            previousNs = measurementStartNs = timestampNs;
            return;
        }
        previousNs = timestampNs;
        measuredTicks += ticks;
        if (measuredTicks >= WARMUP_TICKS) {
            double observedPeriod = (timestampNs - measurementStartNs) / (double) measuredTicks;
            double observedSource = 1_000_000_000.0 / (observedPeriod * divisor);
            if (!DisplaySyncPolicy.permitsCoreClockCorrection(declaredHz, observedSource)) {
                reset();
                previousNs = measurementStartNs = timestampNs;
                return;
            }
            measuredPanelPeriodNs = observedPeriod;
            if (!ready) {
                ready = true;
                phase = 0;
                produced = 1;
                latestDueNs = timestampNs;
                return;
            }
            if (measuredTicks >= 240) {
                measurementStartNs = timestampNs;
                measuredTicks = 0;
            }
        }
        if (!ready) return;
        phase += ticks;
        int due = phase / divisor;
        phase %= divisor;
        if (due > 0) {
            produced += due;
            latestDueNs = timestampNs - Math.round(phase * measuredPanelPeriodNs);
        }
        if (produced - consumed > 4) reset();
    }

    public boolean ready() { return ready; }
    public boolean hasPending() { return ready && produced > consumed; }
    public boolean coalescingCatchUpPresentation() {
        long pending = ready ? produced - consumed : 0;
        // Match the absolute pacer's tolerance: being just past the next
        // source tick is not a full-period stall. Do not discard a completed
        // image simply because its successor is due but not yet rendered.
        // Once genuinely behind, collapse the whole zero-wait catch-up tail.
        if (pending >= 2) coalescingCatchUp = true;
        else if (pending == 0) coalescingCatchUp = false;
        return coalescingCatchUp;
    }
    public double measuredSourceHz() {
        return ready ? 1_000_000_000.0 / (measuredPanelPeriodNs * divisor) : 0;
    }
    public long takeDueTimeNs() {
        if (!hasPending()) return 0;
        ++consumed;
        return latestDueNs - Math.round((produced - consumed) *
                divisor * measuredPanelPeriodNs);
    }
}
