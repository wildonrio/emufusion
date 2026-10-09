package com.thorium.lucent.timing;

/**
 * Coherent bounded-window counters for the direct software presentation path.
 *
 * <p>Each compound event is recorded while holding the same monitor used by
 * {@link #snapshotAndReset()}. An attempt can therefore never land in one QA
 * window while its success or failure lands in the next one.</p>
 */
public final class DirectVideoTelemetry {
    private long mailboxOffers;
    private long mailboxBusyDrops;
    private long presentAttempts;
    private long presentSuccesses;
    private long presentFailures;
    private long sourceNoVideo, sourceCoalesced, sourceBriefOverruns;

    public synchronized void recordSourceDecision(
            boolean hasVideo, boolean coalesced, boolean briefOverrun) {
        if (!hasVideo) ++sourceNoVideo;
        else if (coalesced) ++sourceCoalesced;
        else if (briefOverrun) ++sourceBriefOverruns;
    }

    public synchronized void recordMailboxOffer(boolean replacedOlder) {
        ++mailboxOffers;
        if (replacedOlder) ++mailboxBusyDrops;
    }

    public synchronized void recordPresentation(boolean succeeded) {
        ++presentAttempts;
        if (succeeded) ++presentSuccesses;
        else ++presentFailures;
    }

    public synchronized void resetWindow() {
        mailboxOffers = 0L;
        mailboxBusyDrops = 0L;
        presentAttempts = 0L;
        presentSuccesses = 0L;
        presentFailures = 0L;
        sourceNoVideo = sourceCoalesced = sourceBriefOverruns = 0L;
    }

    public synchronized Snapshot snapshotAndReset() {
        Snapshot snapshot = new Snapshot(mailboxOffers, mailboxBusyDrops,
                presentAttempts, presentSuccesses, presentFailures,
                sourceNoVideo, sourceCoalesced, sourceBriefOverruns);
        resetWindow();
        return snapshot;
    }

    public static final class Snapshot {
        public final long mailboxOffers;
        public final long mailboxBusyDrops;
        public final long presentAttempts;
        public final long presentSuccesses;
        public final long presentFailures;
        public final long sourceNoVideo, sourceCoalesced, sourceBriefOverruns;

        private Snapshot(long mailboxOffers, long mailboxBusyDrops,
                         long presentAttempts, long presentSuccesses,
                         long presentFailures, long sourceNoVideo,
                         long sourceCoalesced, long sourceBriefOverruns) {
            this.mailboxOffers = mailboxOffers;
            this.mailboxBusyDrops = mailboxBusyDrops;
            this.presentAttempts = presentAttempts;
            this.presentSuccesses = presentSuccesses;
            this.presentFailures = presentFailures;
            this.sourceNoVideo = sourceNoVideo;
            this.sourceCoalesced = sourceCoalesced;
            this.sourceBriefOverruns = sourceBriefOverruns;
        }
    }
}
