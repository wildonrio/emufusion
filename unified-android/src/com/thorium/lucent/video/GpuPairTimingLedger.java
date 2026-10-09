package com.thorium.lucent.video;

import java.util.Arrays;

/** Bounded ownership join for five estimator stages and their actual midpoint warp. */
public final class GpuPairTimingLedger {
    private static final int ESTIMATOR_MASK = 62; // Stage IDs 1 through 5.
    private final long[] pairs, costs, warpCosts, warpSequences, warpOwners;
    private final int[] masks;
    private final boolean[] warpExpected, warpComplete, reported, warpResults;
    private long unpairedEstimates;

    public GpuPairTimingLedger(int capacity) {
        if (capacity < 1) throw new IllegalArgumentException("invalid ledger capacity");
        pairs = new long[capacity];
        costs = new long[capacity];
        warpCosts = new long[capacity];
        warpSequences = new long[capacity];
        warpOwners = new long[capacity];
        masks = new int[capacity];
        warpExpected = new boolean[capacity];
        warpComplete = new boolean[capacity];
        reported = new boolean[capacity];
        warpResults = new boolean[capacity];
    }

    private int slot(long sequence) { return (int) (sequence % pairs.length); }

    private boolean retain(long sequence) {
        if (sequence <= 0L) return false;
        int slot = slot(sequence);
        if (pairs[slot] == sequence) return true;
        if (pairs[slot] > sequence) return false;
        if (pairs[slot] != 0L && !reported[slot]) {
            // A solve with no requested warp is not a complete generated pair.
            // It may retire, but an expected missing timer must not disappear.
            if (masks[slot] != ESTIMATOR_MASK || warpExpected[slot]) return false;
            ++unpairedEstimates;
        }
        pairs[slot] = sequence;
        costs[slot] = warpCosts[slot] = 0L;
        masks[slot] = 0;
        warpExpected[slot] = warpComplete[slot] = reported[slot] = false;
        return true;
    }

    public boolean recordEstimatorStage(long pairSequence, int stage, long elapsedUs) {
        if (stage < 1 || stage > 5 || elapsedUs <= 0L || !retain(pairSequence)) return false;
        int slot = slot(pairSequence);
        if (reported[slot] || (masks[slot] & (1 << stage)) != 0 ||
                costs[slot] > Long.MAX_VALUE - elapsedUs ||
                warpCosts[slot] > Long.MAX_VALUE - (costs[slot] + elapsedUs)) return false;
        costs[slot] += elapsedUs;
        masks[slot] |= 1 << stage;
        return true;
    }

    /** Called at warp submission, before either timer result can be polled. */
    public boolean expectWarp(long warpSequence, long pairSequence) {
        if (warpSequence <= 0L || !retain(pairSequence)) return false;
        int pairSlot = slot(pairSequence), warpSlot = slot(warpSequence);
        if (warpExpected[pairSlot] || reported[pairSlot] ||
                warpSequences[warpSlot] >= warpSequence ||
                (warpSequences[warpSlot] != 0L && !warpResults[warpSlot])) return false;
        warpExpected[pairSlot] = true;
        warpSequences[warpSlot] = warpSequence;
        warpOwners[warpSlot] = pairSequence;
        warpResults[warpSlot] = false;
        return true;
    }

    public long ownerOfWarp(long warpSequence) {
        if (warpSequence <= 0L) return 0L;
        int slot = slot(warpSequence);
        return warpSequences[slot] == warpSequence ? warpOwners[slot] : 0L;
    }

    public boolean recordWarp(long warpSequence, long elapsedUs) {
        long owner = ownerOfWarp(warpSequence);
        if (owner <= 0L || elapsedUs <= 0L) return false;
        int warpSlot = slot(warpSequence), pairSlot = slot(owner);
        if (warpResults[warpSlot] || pairs[pairSlot] != owner ||
                reported[pairSlot] || warpComplete[pairSlot] ||
                costs[pairSlot] > Long.MAX_VALUE - elapsedUs) return false;
        warpResults[warpSlot] = true;
        warpComplete[pairSlot] = true;
        warpCosts[pairSlot] = elapsedUs;
        return true;
    }

    /** Removes one complete pair from admission; its costs remain readable until slot reuse. */
    public long takeCompletedPair() {
        long selected = 0L;
        for (int slot = 0; slot < pairs.length; ++slot) {
            if (!reported[slot] && masks[slot] == ESTIMATOR_MASK &&
                    warpExpected[slot] && warpComplete[slot] &&
                    (selected == 0L || pairs[slot] < selected)) selected = pairs[slot];
        }
        if (selected > 0L) reported[slot(selected)] = true;
        return selected;
    }

    public long completedTotalUs(long pairSequence) {
        if (pairSequence <= 0L) return 0L;
        int slot = slot(pairSequence);
        if (pairs[slot] != pairSequence || !reported[slot] ||
                costs[slot] > Long.MAX_VALUE - warpCosts[slot]) return 0L;
        return costs[slot] + warpCosts[slot];
    }

    public int pendingPairCount() {
        int count = 0;
        for (int slot = 0; slot < pairs.length; ++slot)
            if (pairs[slot] != 0L && !reported[slot]) ++count;
        return count;
    }

    public long unpairedEstimateCount() { return unpairedEstimates; }

    public void beginEvidenceEpoch() {
        Arrays.fill(pairs, 0L);
        Arrays.fill(costs, 0L);
        Arrays.fill(warpCosts, 0L);
        Arrays.fill(warpSequences, 0L);
        Arrays.fill(warpOwners, 0L);
        Arrays.fill(masks, 0);
        Arrays.fill(warpExpected, false);
        Arrays.fill(warpComplete, false);
        Arrays.fill(reported, false);
        Arrays.fill(warpResults, false);
    }
}
