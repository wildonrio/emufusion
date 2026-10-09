package com.thorium.lucent.video;

public final class ExternalGeneratedContentEvidenceTest {
    public static void main(String[] args) {
        cleanMovingEvidencePassesNumericComponent();
        exactEndpointPassthroughIsRequired();
        sceneCutRiskFailsClosed();
        generatedDuplicateFailsMovingEvidence();
        epochChangeResetsReservoir();
        privateProofTokensRemainIndependentFromPresentIds();
        appOwnedGeneratedProofsBindPhysicalFrameIds();
        sameEpochTimingRestartClearsContentProofs();
        System.out.println("ExternalGeneratedContentEvidenceTest PASS");
    }

    private static void cleanMovingEvidencePassesNumericComponent() {
        ExternalGeneratedContentEvidence evidence =
                new ExternalGeneratedContentEvidence();
        Harness harness = new Harness();
        for (int index = 0; index < 60; ++index) {
            boolean generated = (index & 1) != 0;
            ExternalPresentationLedger.Commit row = harness.commit(generated, 7L);
            long left = 1000L + index * 3L;
            long right = left + 1L;
            long output = generated ? left + 2L : left;
            evidence.record(row, proof(row.presentId, left, right, output,
                    20_000L, false));
        }
        check(evidence.numericProofPassed(), "clean moving evidence did not pass");
        check(evidence.generatedProofs() == 30L, "generated proof count mismatch");
        check(evidence.endpointProofs() == 30L, "endpoint proof count mismatch");
    }

    private static void exactEndpointPassthroughIsRequired() {
        ExternalGeneratedContentEvidence evidence =
                new ExternalGeneratedContentEvidence();
        Harness harness = new Harness();
        ExternalPresentationLedger.Commit row = harness.commit(false, 3L);
        boolean rejected = false;
        try {
            evidence.record(row, proof(row.presentId, 11L, 12L, 99L,
                    10_000L, false));
        } catch (IllegalStateException expected) {
            rejected = true;
        }
        check(rejected, "non-passthrough endpoint was accepted");
    }

    private static void sceneCutRiskFailsClosed() {
        ExternalGeneratedContentEvidence evidence =
                new ExternalGeneratedContentEvidence();
        Harness harness = new Harness();
        for (int index = 0; index < 30; ++index) {
            ExternalPresentationLedger.Commit row = harness.commit(true, 4L);
            evidence.record(row, proof(row.presentId, 100L + index,
                    200L + index, 300L + index, 400_000L, index == 0));
        }
        check(!evidence.numericProofPassed(), "scene-cut risk was qualified");
    }

    private static void generatedDuplicateFailsMovingEvidence() {
        ExternalGeneratedContentEvidence evidence =
                new ExternalGeneratedContentEvidence();
        Harness harness = new Harness();
        for (int index = 0; index < 30; ++index) {
            ExternalPresentationLedger.Commit row = harness.commit(true, 5L);
            long left = 100L + index;
            evidence.record(row, proof(row.presentId, left, left + 100L,
                    index == 0 ? left : left + 50L, 30_000L, false));
        }
        check(!evidence.numericProofPassed(), "generated endpoint duplicate passed");
    }

    private static void epochChangeResetsReservoir() {
        ExternalGeneratedContentEvidence evidence =
                new ExternalGeneratedContentEvidence();
        Harness harness = new Harness();
        for (int index = 0; index < 30; ++index) {
            ExternalPresentationLedger.Commit row = harness.commit(true, 8L);
            evidence.record(row, proof(row.presentId, 10L + index,
                    100L + index, 1000L + index, 20_000L, false));
        }
        check(evidence.numericProofPassed(), "first epoch did not pass");
        ExternalPresentationLedger.Commit next = harness.commit(false, 9L);
        evidence.record(next, proof(next.presentId, 700L, 701L, 700L,
                10_000L, false));
        check(evidence.presentationEpoch() == 9L, "epoch did not change");
        check(evidence.proofs() == 1L, "epoch reservoir did not reset");
        check(!evidence.numericProofPassed(), "fresh epoch inherited proof");
    }

    private static void privateProofTokensRemainIndependentFromPresentIds() {
        ExternalGeneratedContentEvidence evidence =
                new ExternalGeneratedContentEvidence();
        Harness harness = new Harness();
        ExternalPresentationLedger.Commit endpoint = harness.commit(false, 12L);
        // Endpoint WSI may consume a newer native proof token while a private
        // generated output, prepared earlier, retains an older one.
        evidence.record(endpoint, proof(9L, 31L, 32L, 31L,
                10_000L, false));
        ExternalPresentationLedger.Commit generated = harness.commit(true, 12L);
        evidence.record(generated, proof(8L, 41L, 42L, 43L,
                20_000L, false));
        check(evidence.proofs() == 2L,
                "independent native proof tokens were rejected");

        boolean rejected = false;
        try {
            evidence.record(generated, proof(10L, 41L, 42L, 43L,
                    20_000L, false));
        } catch (IllegalStateException expected) {
            rejected = true;
        }
        check(rejected, "duplicate physical presentation was accepted");
    }

    private static void appOwnedGeneratedProofsBindPhysicalFrameIds() {
        ExternalGeneratedContentEvidence evidence =
                new ExternalGeneratedContentEvidence();
        for (int index = 0; index < 30; ++index) {
            long sequence = index + 1L;
            FrameGenerationPresentationRequest request =
                    FrameGenerationPresentationRequest.between(
                            1L, 14L, sequence,
                            10_000_000_000L + index * 20_000_000L,
                            sequence + 1L,
                            10_020_000_000L + index * 20_000_000L,
                            10_010_000_000L + index * 20_000_000L,
                            2_000_000_000L + index * 16_896_000L,
                            1_998_000_000L + index * 16_896_000L,
                            1_998_000_000L + index * 16_896_000L,
                            0, 128, 72,
                            FrameGenerationPresentationRequest.
                                    FORMAT_RGBA8_UNORM);
            evidence.recordAppOwnedGenerated(
                    14L, sequence, request,
                    proof(sequence, 100L + index, 200L + index,
                            300L + index, 20_000L, false));
        }
        check(evidence.numericProofPassed(),
                "clean app-owned generated proofs did not pass");
        check(evidence.proofs() == 30L &&
                        evidence.endpointProofs() == 0L &&
                        evidence.generatedProofs() == 30L,
                "app-owned generated proof conservation mismatch");
        boolean rejected = false;
        try {
            FrameGenerationPresentationRequest stale =
                    FrameGenerationPresentationRequest.between(
                            1L, 14L, 31L, 20_000_000_000L,
                            32L, 20_020_000_000L, 20_010_000_000L,
                            3_000_000_000L, 2_998_000_000L,
                            2_998_000_000L, 0, 128, 72,
                            FrameGenerationPresentationRequest.
                                    FORMAT_RGBA8_UNORM);
            evidence.recordAppOwnedGenerated(14L, 30L, stale,
                    proof(31L, 1L, 2L, 3L, 20_000L, false));
        } catch (IllegalStateException expected) {
            rejected = true;
        }
        check(rejected,
                "duplicate app-owned physical frame ID was accepted");
    }

    private static void sameEpochTimingRestartClearsContentProofs() {
        ExternalGeneratedContentEvidence evidence =
                new ExternalGeneratedContentEvidence();
        FrameGenerationPresentationRequest request =
                FrameGenerationPresentationRequest.between(
                        1L, 15L, 1L, 30_000_000_000L,
                        2L, 30_020_000_000L, 30_010_000_000L,
                        4_000_000_000L, 3_998_000_000L,
                        3_998_000_000L, 0, 128, 72,
                        FrameGenerationPresentationRequest.
                                FORMAT_RGBA8_UNORM);
        evidence.recordAppOwnedGenerated(15L, 1L, request,
                proof(1L, 10L, 20L, 30L, 20_000L, false));
        evidence.restartWindow(15L);
        check(evidence.identityMatches(15L),
                "content restart preserves scheduler epoch");
        check(evidence.proofs() == 0L &&
                        evidence.generatedProofs() == 0L &&
                        !evidence.numericProofPassed(),
                "content proof crossed a physical timing-window restart");
    }

    private static ExternalGeneratedContentProof proof(
            long sequence, long left, long right, long output,
            long endpointMadPpm, boolean sceneCut) {
        return new ExternalGeneratedContentProof(
                left, right, output, endpointMadPpm,
                10_000L, 11_000L, 20_000L,
                2, 240, sceneCut, 50_000L,
                48, 27, 1296L, sequence, 11664L);
    }

    private static final class Harness {
        final ExternalPresentationLedger ledger = new ExternalPresentationLedger();
        long sequence;
        long desired = 1_000_000_000L;
        long actual = 1_002_000_000L;
        long content = 2_000_000_000L;

        ExternalPresentationLedger.Commit commit(boolean generated, long epoch) {
            ++sequence;
            FrameGenerationPresentationRequest request = generated ?
                    request(epoch, desired, sequence, content,
                            content + 10_000_000L) :
                    request(epoch, desired, sequence, content, content);
            ledger.submit(request, 1);
            ExternalPresentationLedger.Commit row = ledger.physicallyPresented(
                    request, sequence,
                    request.driverDesiredPresentTimeNs(), actual,
                    actual - 1_000_000L,
                    0L, 8_333_333L, 100_000L, 5_000_000L);
            desired += 8_333_333L;
            actual += 8_333_333L;
            content += 20_000_000L;
            return row;
        }

        private static FrameGenerationPresentationRequest request(
                long epoch, long driverNs, long sequence, long leftNs,
                long presentationNs) {
            return FrameGenerationPresentationRequest.between(
                    1L, epoch, sequence, leftNs, sequence + 1L,
                    leftNs + 20_000_000L, presentationNs,
                    driverNs + 2_000_000L, driverNs, driverNs,
                    0, 128, 72,
                    FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
        }
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
