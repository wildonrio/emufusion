package com.thorium.lucent.video;

public final class MidpointPairBudgetTest {
    public static void main(String[] args) {
        exactPairOwnsOneMidpointAcrossEpochs();
        fractionsAndEndpointsCannotPretendToBeMidpoints();
        advancingSequencesCannotReuseTimestampPairs();
        longSequencesKeepOneMidpointPerPair();
        oddAndLargeTimestampsKeepTheirExactMidpoint();
        noOpTransportDeferralDoesNotSpendMidpoint();
        System.out.println("MidpointPairBudgetTest passed");
    }

    private static void exactPairOwnsOneMidpointAcrossEpochs() {
        MidpointPairBudget budget = new MidpointPairBudget();
        check(budget.admit(pair(1, 1, 100, 200, 150)), "first midpoint rejected");
        check(!budget.admit(pair(1, 1, 100, 200, 150)), "same pair admitted twice");
        check(!budget.admit(pair(2, 1, 100, 200, 150)), "epoch reset renewed pair budget");
        check(budget.admit(pair(2, 2, 200, 300, 250)), "successor midpoint rejected");
        check(budget.admitted() == 2 && budget.rejected() == 2, "lifetime counters lost");
    }

    private static void fractionsAndEndpointsCannotPretendToBeMidpoints() {
        MidpointPairBudget budget = new MidpointPairBudget();
        for (long target : new long[] {100, 125, 133, 149, 151, 167, 175, 200})
            check(!budget.admit(pair(1, 1, 100, 200, target)), "non-midpoint admitted: " + target);
        check(budget.admit(pair(1, 1, 100, 200, 150)), "bad requests consumed a valid pair");
        check(!budget.admit(null), "null request admitted");
        check(!budget.admit(FrameGenerationPresentationRequest.endpoint(
                1, 1, 10, 100, 500, 450, 450, 1, 16, 16,
                FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM)), "real endpoint admitted");
    }

    private static void advancingSequencesCannotReuseTimestampPairs() {
        MidpointPairBudget budget = new MidpointPairBudget();
        check(budget.admit(pair(1, 1, 100, 200, 150)), "first midpoint rejected");
        check(!budget.admit(pair(2, 2, 100, 200, 150)), "relabelled pixels renewed budget");
        check(!budget.admit(pair(2, 3, 50, 150, 100)), "backward source time admitted");
        check(budget.admit(pair(2, 4, 400, 500, 450)), "safe skipped-pair successor rejected");
        check(!budget.admit(pair(3, 2, 500, 600, 550)), "backward pair sequence admitted");
    }

    private static void longSequencesKeepOneMidpointPerPair() {
        for (int fps : new int[] {20, 30, 60}) {
            MidpointPairBudget budget = new MidpointPairBudget();
            for (long sequence = 1; sequence <= fps * 600L; ++sequence) {
                long left = 1_000_000_000L + (sequence - 1) * 1_000_000_000L / fps;
                long right = 1_000_000_000L + sequence * 1_000_000_000L / fps;
                long middle = left + (right - left) / 2;
                FrameGenerationPresentationRequest request = pair(1 + sequence / 1000,
                        sequence, left, right, middle);
                check(budget.admit(request), "exact interval rejected at " + fps + ":" + sequence);
                check(!budget.admit(request), "pair reused at " + fps + ":" + sequence);
            }
            check(budget.admitted() == fps * 600L && budget.rejected() == fps * 600L,
                    "ten-minute ownership ledger is not conserved");
        }
    }

    private static void oddAndLargeTimestampsKeepTheirExactMidpoint() {
        MidpointPairBudget budget = new MidpointPairBudget();
        check(budget.admit(pair(1, 1, 100, 201, 150)), "odd span floor midpoint rejected");
        check(!new MidpointPairBudget().admit(pair(1, 1, 100, 201, 151)),
                "opposite rounding generated a second possible midpoint");
        check(new MidpointPairBudget().admit(pair(1, 1, Long.MAX_VALUE - 101,
                Long.MAX_VALUE, Long.MAX_VALUE - 51)), "midpoint sum overflowed");
        check(!new MidpointPairBudget().admit(pair(1, 1, 100, 101, 100)),
                "one-nanosecond pair has no interior midpoint");
    }

    private static FrameGenerationPresentationRequest pair(long epoch, long sequence,
            long left, long right, long target) {
        return FrameGenerationPresentationRequest.between(1, epoch,
                sequence, left, sequence + 1, right, target,
                500, 450, 450, 1, 16, 16,
                FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
    }

    private static void noOpTransportDeferralDoesNotSpendMidpoint() {
        MidpointPairBudget budget = new MidpointPairBudget();
        FrameGenerationPresentationRequest request = pair(1, 1, 100, 200, 150);
        // Both DEFERRED (retry same slot) and NOT_READY (drop this slot) have
        // a zero-submission transport contract. Neither commits admission.
        for (int callback = 0; callback < 1200; ++callback) {
            check(budget.canAdmit(request), "no-op deferral froze next callback");
            check(budget.admitted() == 0, "no-op deferral spent budget");
        }
        check(budget.canAdmit(request) && budget.admit(request), "submission rejected");
        check(!budget.canAdmit(request), "submitted pair passed preflight again");
        check(budget.admitted() == 1, "submitted midpoint lost lifetime budget");
        check(!budget.canAdmit(pair(2, 1, 100, 200, 150)), "epoch renewed submitted budget");
    }

    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
}
