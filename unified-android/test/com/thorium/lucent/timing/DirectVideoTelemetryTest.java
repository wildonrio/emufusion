package com.thorium.lucent.timing;

import com.thorium.lucent.TestSupport;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;

public final class DirectVideoTelemetryTest {
    public static void main(String[] ignored) throws Exception {
        keepsCompoundEventsInsideOneWindow();
        distinguishesUpstreamSkipsFromToleratedOverruns();
        conservesConcurrentEventsAcrossWindowBoundaries();
        System.out.println("DirectVideoTelemetryTest passed");
    }

    private static void keepsCompoundEventsInsideOneWindow() {
        DirectVideoTelemetry telemetry = new DirectVideoTelemetry();
        telemetry.recordMailboxOffer(false);
        telemetry.recordMailboxOffer(true);
        telemetry.recordPresentation(true);
        telemetry.recordPresentation(false);
        assertCoherent(telemetry.snapshotAndReset(), 2L, 1L, 2L, 1L, 1L,
                "first bounded window");
        assertCoherent(telemetry.snapshotAndReset(), 0L, 0L, 0L, 0L, 0L,
                "snapshot resets the bounded window");
        telemetry.recordPresentation(true);
        assertCoherent(telemetry.snapshotAndReset(), 0L, 0L, 1L, 1L, 0L,
                "event after boundary belongs wholly to the next window");
    }

    private static void distinguishesUpstreamSkipsFromToleratedOverruns() {
        DirectVideoTelemetry telemetry = new DirectVideoTelemetry();
        telemetry.recordSourceDecision(false, true, true);
        telemetry.recordSourceDecision(true, true, true);
        telemetry.recordSourceDecision(true, false, true);
        telemetry.recordSourceDecision(true, false, false);
        DirectVideoTelemetry.Snapshot window = telemetry.snapshotAndReset();
        TestSupport.equal(1L, window.sourceNoVideo, "missing source image counted once");
        TestSupport.equal(1L, window.sourceCoalesced, "catch-up discard counted once");
        TestSupport.equal(1L, window.sourceBriefOverruns, "tolerated overrun is not a discard");
        window = telemetry.snapshotAndReset();
        TestSupport.equal(0L, window.sourceNoVideo, "missing count resets");
        TestSupport.equal(0L, window.sourceCoalesced, "coalesced count resets");
        TestSupport.equal(0L, window.sourceBriefOverruns, "overrun count resets");
    }

    private static void conservesConcurrentEventsAcrossWindowBoundaries()
            throws Exception {
        final int threadPairs = 4;
        final int eventsPerThread = 10_000;
        DirectVideoTelemetry telemetry = new DirectVideoTelemetry();
        CountDownLatch start = new CountDownLatch(1);
        CountDownLatch done = new CountDownLatch(threadPairs * 2);
        List<Thread> workers = new ArrayList<>();
        for (int threadIndex = 0; threadIndex < threadPairs; threadIndex++) {
            final int index = threadIndex;
            workers.add(new Thread(() -> {
                await(start);
                for (int event = 0; event < eventsPerThread; event++)
                    telemetry.recordMailboxOffer(((event + index) & 1) == 0);
                done.countDown();
            }));
            workers.add(new Thread(() -> {
                await(start);
                for (int event = 0; event < eventsPerThread; event++)
                    telemetry.recordPresentation(((event + index) & 3) != 0);
                done.countDown();
            }));
        }
        for (Thread worker : workers) worker.start();
        start.countDown();

        long offers = 0L;
        long busyDrops = 0L;
        long attempts = 0L;
        long successes = 0L;
        long failures = 0L;
        while (done.getCount() != 0L) {
            DirectVideoTelemetry.Snapshot window = telemetry.snapshotAndReset();
            assertWindowInvariants(window);
            offers += window.mailboxOffers;
            busyDrops += window.mailboxBusyDrops;
            attempts += window.presentAttempts;
            successes += window.presentSuccesses;
            failures += window.presentFailures;
            Thread.yield();
        }
        for (Thread worker : workers) worker.join();
        DirectVideoTelemetry.Snapshot tail = telemetry.snapshotAndReset();
        assertWindowInvariants(tail);
        offers += tail.mailboxOffers;
        busyDrops += tail.mailboxBusyDrops;
        attempts += tail.presentAttempts;
        successes += tail.presentSuccesses;
        failures += tail.presentFailures;

        TestSupport.equal((long) threadPairs * eventsPerThread, offers,
                "all concurrent mailbox offers survive window resets");
        TestSupport.equal((long) threadPairs * eventsPerThread / 2L, busyDrops,
                "all concurrent replacements survive window resets");
        TestSupport.equal((long) threadPairs * eventsPerThread, attempts,
                "all concurrent presentation attempts survive window resets");
        TestSupport.equal(attempts, successes + failures,
                "concurrent outcomes exactly partition attempts");
    }

    private static void await(CountDownLatch latch) {
        try { latch.await(); }
        catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw new AssertionError(interrupted);
        }
    }

    private static void assertWindowInvariants(DirectVideoTelemetry.Snapshot window) {
        TestSupport.truth(window.mailboxBusyDrops <= window.mailboxOffers,
                "a window cannot replace more frames than it offers");
        TestSupport.equal(window.presentAttempts,
                window.presentSuccesses + window.presentFailures,
                "a window's outcomes exactly partition its attempts");
    }

    private static void assertCoherent(DirectVideoTelemetry.Snapshot value,
                                       long offers, long busyDrops, long attempts,
                                       long successes, long failures, String label) {
        TestSupport.equal(offers, value.mailboxOffers, label + " offers");
        TestSupport.equal(busyDrops, value.mailboxBusyDrops, label + " replacements");
        TestSupport.equal(attempts, value.presentAttempts, label + " attempts");
        TestSupport.equal(successes, value.presentSuccesses, label + " successes");
        TestSupport.equal(failures, value.presentFailures, label + " failures");
        assertWindowInvariants(value);
    }
}
