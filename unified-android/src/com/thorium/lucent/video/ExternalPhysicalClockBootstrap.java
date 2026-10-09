package com.thorium.lucent.video;

/**
 * One-way bootstrap barrier between unanchored Direct presents and exact
 * physical-lattice presentation evidence.
 *
 * <p>An external swapchain cannot expose its first actual-present anchor until
 * something has been presented. Those endpoint-only rows are calibration,
 * never qualification. Once any actual timestamp establishes the clock, new
 * endpoint-only calibration continues through the transport's ordinary
 * bounded queue until GOOGLE_display_timing releases its first row. A guessed
 * fixed depth is incorrect on Thor: the release latency varies, and the newest
 * queued present can itself need a successor. Once the first actual timestamp
 * arrives, the owner commits a fresh presentation epoch. Any still-pending
 * request from the old epoch remains explicitly calibration-only when it is
 * later retired; it can never enter post-boundary cadence or content
 * evidence.</p>
 */
public final class ExternalPhysicalClockBootstrap {
    private boolean complete;
    private long calibrationPresents;
    private long calibrationPresentationEpoch;

    public boolean complete() { return complete; }
    public boolean calibrationRow(long presentationEpoch) {
        if (presentationEpoch <= 0L)
            throw new IllegalArgumentException(
                    "physical-clock calibration epoch is invalid");
        return !complete || presentationEpoch == calibrationPresentationEpoch;
    }
    public long calibrationPresents() { return calibrationPresents; }
    public long calibrationPresentationEpoch() {
        return calibrationPresentationEpoch;
    }

    public void recordCalibrationPresent(boolean generated,
                                         long presentationEpoch) {
        if (presentationEpoch <= 0L)
            throw new IllegalArgumentException(
                    "physical-clock calibration epoch is invalid");
        if (generated)
            throw new IllegalStateException(
                    "physical-clock calibration must be endpoint-only");
        if (calibrationPresentationEpoch == 0L)
            calibrationPresentationEpoch = presentationEpoch;
        if (presentationEpoch != calibrationPresentationEpoch)
            throw new IllegalStateException(
                    "physical-clock calibration crossed presentation epochs");
        ++calibrationPresents;
    }

    public boolean ready(boolean clockAvailable, int ledgerPending,
                         int transportPending) {
        requirePending(ledgerPending, transportPending);
        return !complete && clockAvailable && calibrationPresents > 0L &&
                calibrationPresentationEpoch > 0L;
    }

    public void commit(boolean clockAvailable, int ledgerPending,
                       int transportPending) {
        if (!ready(clockAvailable, ledgerPending, transportPending))
            throw new IllegalStateException(
                    "physical-clock bootstrap boundary is not established");
        complete = true;
    }

    private static void requirePending(int ledgerPending,
                                       int transportPending) {
        if (ledgerPending < 0 || transportPending < 0 ||
                ledgerPending != transportPending)
            throw new IllegalStateException(
                    "physical-clock bootstrap queue conservation failed");
    }
}
