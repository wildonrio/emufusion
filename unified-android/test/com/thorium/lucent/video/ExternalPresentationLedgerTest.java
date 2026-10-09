package com.thorium.lucent.video;

public final class ExternalPresentationLedgerTest {
    public static void main(String[] args) {
        submissionIsNeverPhysicalDelivery();
        exactPhysicalRowsCommitInOrder();
        directVulkanPreservesSeparateDriverAndContentTimes();
        missingPhysicalRowIsRecordedAsDrop();
        explicitTailDropDrainsWithoutDelivery();
        explicitDropIdentityFailsClosed();
        mismatchedOrNonmonotonicRowsFailClosed();
        negativePresentMarginFailsClosed();
        overflowFailsInsteadOfLosingIdentity();
        System.out.println("ExternalPresentationLedgerTest passed");
    }

    private static void explicitTailDropDrainsWithoutDelivery() {
        ExternalPresentationLedger ledger = new ExternalPresentationLedger();
        FrameGenerationPresentationRequest first =
                request(1, 100, 2, 200, 150, 1_000, 7L);
        FrameGenerationPresentationRequest tail =
                request(2, 200, 3, 300, 250, 2_000, 7L);
        ledger.submit(first, 2);
        ledger.submit(tail, 2);
        ledger.physicallyPresented(first, 1, 1_000, 10_000,
                9_000, 100, 8_448, 700, 5_000);
        ExternalPresentationLedger.Drop drop =
                ledger.physicallyDropped(tail, 2, 8_448);
        check(drop.request == tail && drop.presentId == 2L,
                "explicit tail drop preserves exact identity");
        check(drop.scansPerOutput == 2 && drop.presentationEpoch == 7L &&
                        drop.refreshDurationNs == 8_448L,
                "explicit tail drop preserves cadence identity");
        check(ledger.pendingCount() == 0,
                "explicit tail drop drains without a later actual row");
        check(ledger.physicallyPresentedCount() == 1L &&
                        ledger.physicalDroppedCount() == 1L,
                "explicit drop never increments delivery");
    }

    private static void explicitDropIdentityFailsClosed() {
        ExternalPresentationLedger ledger = new ExternalPresentationLedger();
        FrameGenerationPresentationRequest first =
                request(1, 100, 2, 200, 150, 1_000, 7L);
        FrameGenerationPresentationRequest second =
                request(2, 200, 3, 300, 250, 2_000, 7L);
        ledger.submit(first, 2);
        ledger.submit(second, 2);
        expectFailure(() -> ledger.physicallyDropped(second, 1, 8_448));
        expectFailure(() -> ledger.physicallyDropped(first, 2, 8_448));
        check(ledger.pendingCount() == 2,
                "wrong or out-of-order drop does not consume identity");
        ledger.physicallyDropped(first, 1, 8_448);
        expectFailure(() -> ledger.physicallyDropped(first, 2, 8_448));
        check(ledger.pendingCount() == 1,
                "duplicate drop cannot consume the next submission");
    }

    private static void missingPhysicalRowIsRecordedAsDrop() {
        ExternalPresentationLedger ledger = new ExternalPresentationLedger();
        FrameGenerationPresentationRequest dropped =
                request(1, 100, 2, 200, 150, 1_000, 7L);
        FrameGenerationPresentationRequest shown =
                request(2, 200, 3, 300, 250, 2_000, 7L);
        ledger.submit(dropped, 2);
        ledger.submit(shown, 2);
        ExternalPresentationLedger.Commit commit = ledger.physicallyPresented(
                shown, 2, 2_000, 26_896, 25_000, 200,
                8_448, 500, 1_500);
        check(commit.droppedBefore == 1L, "exact missing ID is exposed");
        check(ledger.physicalDroppedCount() == 1L, "physical drop counted");
        check(ledger.physicallyPresentedCount() == 1L,
                "drop is not counted as delivery");
        check(ledger.pendingCount() == 0, "drop and shown row drain in order");
    }

    private static void submissionIsNeverPhysicalDelivery() {
        ExternalPresentationLedger ledger = new ExternalPresentationLedger();
        ledger.submit(request(1, 100, 2, 200, 150, 1_000, 7L), 2);
        check(ledger.submittedCount() == 1, "submission counted");
        check(ledger.physicallyPresentedCount() == 0, "submission is not delivery");
        check(ledger.physicalGeneratedCount() == 0, "generated work is not delivery");
    }

    private static void exactPhysicalRowsCommitInOrder() {
        ExternalPresentationLedger ledger = new ExternalPresentationLedger();
        FrameGenerationPresentationRequest generated =
                request(1, 100, 2, 200, 150, 1_000, 7L);
        FrameGenerationPresentationRequest endpoint =
                request(1, 100, 2, 200, 200, 2_000, 7L);
        ledger.submit(generated, 2);
        ledger.submit(endpoint, 2);
        ExternalPresentationLedger.Commit first = ledger.physicallyPresented(
                generated, 1, 1_000, 10_000, 9_000, 100,
                8_448, 700, 5_000);
        ExternalPresentationLedger.Commit second = ledger.physicallyPresented(
                endpoint, 2, 2_000, 26_896, 25_000, 200,
                8_448, 500, 1_500);
        check(first.generated && !second.generated, "physical kinds preserved");
        check(first.request == generated && first.presentId == 1L,
                "exact request and present identity preserved");
        check(first.enqueueWallNs == 700L && first.gpuWorkNs == 5_000L,
                "exact live deadline evidence preserved");
        check(first.presentationEpoch == 7L,
                "submission presentation epoch preserved");
        check(first.scansPerOutput == 2 && second.scansPerOutput == 2,
                "submission divisor preserved");
        check(ledger.physicallyPresentedCount() == 2, "physical rows counted");
        check(ledger.physicalGeneratedCount() == 1, "generated physical counted");
        check(ledger.physicalEndpointCount() == 1, "endpoint physical counted");
        check(ledger.pendingCount() == 0, "queue drained");
    }

    private static void directVulkanPreservesSeparateDriverAndContentTimes() {
        ExternalPresentationLedger ledger = new ExternalPresentationLedger();
        FrameGenerationPresentationRequest direct =
                directRequest(1, 100, 2, 200, 150, 1_000, 7L);
        ledger.submit(direct, 2);
        expectFailure(() -> ledger.physicallyPresented(
                direct, 1, direct.desiredPhysicalPresentTimeNs(),
                10_000, 9_000, 100, 8_448, 700, 5_000));
        ExternalPresentationLedger.Commit committed = ledger.physicallyPresented(
                direct, 1, direct.driverDesiredPresentTimeNs(),
                10_000, 9_000, 100, 8_448, 700, 5_000);
        check(committed.desiredPresentTimeNs ==
                        direct.driverDesiredPresentTimeNs(),
                "direct Vulkan preserves the earlier native request");
        check(committed.request.desiredPhysicalPresentTimeNs() >
                        committed.desiredPresentTimeNs,
                "exact content scan remains independently bound");
    }

    private static void mismatchedOrNonmonotonicRowsFailClosed() {
        ExternalPresentationLedger mismatched = new ExternalPresentationLedger();
        FrameGenerationPresentationRequest expected =
                request(3, 300, 4, 400, 350, 3_000, 8L);
        mismatched.submit(expected, 1);
        expectFailure(() -> mismatched.physicallyPresented(
                request(3, 300, 4, 400, 351, 3_000, 8L),
                1, 3_000, 30_000, 29_000, 100,
                8_448, 500, 1_500));
        check(mismatched.pendingCount() == 1,
                "mismatched row does not destroy the expected submission");

        ExternalPresentationLedger nonmonotonic = new ExternalPresentationLedger();
        nonmonotonic.submit(expected, 1);
        nonmonotonic.physicallyPresented(expected, 1, 3_000, 30_000,
                29_000, 100, 8_448, 500, 1_500);
        FrameGenerationPresentationRequest next =
                request(4, 400, 5, 500, 450, 4_000, 8L);
        nonmonotonic.submit(next, 1);
        expectFailure(() -> nonmonotonic.physicallyPresented(
                next, 2, 4_000, 30_000, 29_000, 100,
                8_448, 500, 1_500));

        ExternalPresentationLedger duplicateContent =
                new ExternalPresentationLedger();
        duplicateContent.submit(expected, 1);
        duplicateContent.physicallyPresented(expected, 1, 3_000, 30_000,
                29_000, 100, 8_448, 500, 1_500);
        FrameGenerationPresentationRequest repeated =
                request(4, 300, 5, 500, 350, 4_000, 8L);
        duplicateContent.submit(repeated, 1);
        expectFailure(() -> duplicateContent.physicallyPresented(
                repeated, 2, 4_000, 40_000, 39_000, 100,
                8_448, 500, 1_500));
    }

    private static void overflowFailsInsteadOfLosingIdentity() {
        ExternalPresentationLedger ledger = new ExternalPresentationLedger();
        for (int index = 0; index < 16; ++index) {
            long left = index + 1L;
            ledger.submit(request(left, left * 100, left + 1L,
                    (left + 1L) * 100, left * 100 + 50,
                    10_000 + index, 9L), 1);
        }
        check(!ledger.canSubmit(), "full ledger refuses another submission");
        expectFailure(() -> ledger.submit(
                request(17, 1700, 18, 1800, 1750, 20_000, 9L), 1));
    }

    private static void negativePresentMarginFailsClosed() {
        ExternalPresentationLedger ledger = new ExternalPresentationLedger();
        FrameGenerationPresentationRequest request =
                request(1, 100, 2, 200, 150, 1_000, 7L);
        ledger.submit(request, 2);
        expectFailure(() -> ledger.physicallyPresented(
                request, 1, 1_000, 10_000, 9_000, -1,
                8_448, 700, 5_000));
        check(ledger.pendingCount() == 1,
                "invalid margin does not consume pending identity");
    }

    private static FrameGenerationPresentationRequest request(
            long left, long leftNs, long right, long rightNs,
            long presentationNs, long driverNs, long presentationEpoch) {
        return directRequest(left, leftNs, right, rightNs, presentationNs,
                driverNs, presentationEpoch).withTargetCompositorFrameTimeline(
                        1L, driverNs + 10L, driverNs);
    }

    private static FrameGenerationPresentationRequest directRequest(
            long left, long leftNs, long right, long rightNs,
            long presentationNs, long driverNs, long presentationEpoch) {
        return FrameGenerationPresentationRequest.between(
                1L, presentationEpoch,
                left, leftNs, right, rightNs, presentationNs,
                driverNs + 10L, driverNs, driverNs, 0, 64, 64,
                FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
    }

    private static void expectFailure(Runnable runnable) {
        try {
            runnable.run();
            throw new AssertionError("expected failure");
        } catch (IllegalStateException expected) {
            // expected
        }
    }

    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
}
