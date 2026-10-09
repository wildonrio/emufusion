package com.thorium.lucent.video;

public final class PhysicalPresentationCadenceTest {
    public static void main(String[] args) {
        exactDivisorQualifiesOnlyAfterPhysicalHistory();
        compositorDropIsNeverCountedAsDelivered();
        expiredCompositorHistoryResetsButRecovers();
        alternatingOrMissedIntervalsNeverQualify();
        targetClockChangeStartsFreshEvidence();
        invalidOrNonmonotonicTimestampFailsClosed();
    }

    private static void exactDivisorQualifiesOnlyAfterPhysicalHistory() {
        PhysicalPresentationCadence cadence = new PhysicalPresentationCadence();
        long panel = 8_448_000L;
        long time = 1_000_000_000L;
        for (int index = 0; index < 90; ++index) {
            check(cadence.recordPresented(time, 3, panel), "exact timestamp");
            time += 3L * panel;
        }
        near(1_000_000_000.0 / (3L * panel), cadence.actualHz(3, panel), .001,
                "actual physical divisor rate");
        check(cadence.qualified(3, panel), "two clean seconds qualify");
        check(!cadence.qualified(2, panel), "wrong divisor cannot inherit proof");
    }

    private static void compositorDropIsNeverCountedAsDelivered() {
        PhysicalPresentationCadence cadence = new PhysicalPresentationCadence();
        long panel = 8_448_000L;
        long time = 1_000_000_000L;
        for (int index = 0; index < 250; ++index) {
            cadence.recordPresented(time, 1, panel);
            time += panel;
        }
        check(cadence.qualified(1, panel), "clean scanout qualifies");
        cadence.recordDropped(1, panel);
        check(!cadence.qualified(1, panel), "drop invalidates immediately");
        time += panel; // the missing physical present creates a two-scan gap
        cadence.recordPresented(time, 1, panel);
        check(!cadence.qualified(1, panel), "drop gap remains in rolling proof");
        long recoveryStart = time;
        while (time - recoveryStart < 2_300_000_000L) {
            time += panel;
            cadence.recordPresented(time, 1, panel);
        }
        check(cadence.qualified(1, panel),
                "two clean seconds after a drop may requalify");
        check(cadence.droppedPresents() == 1, "drop counted separately");
        check(cadence.successfulPresents() > 251, "drop is not a success");
    }

    private static void alternatingOrMissedIntervalsNeverQualify() {
        PhysicalPresentationCadence cadence = new PhysicalPresentationCadence();
        long panel = 8_448_000L;
        long time = 1_000_000_000L;
        for (int index = 0; index < 100; ++index) {
            cadence.recordPresented(time, 2, panel);
            time += (index & 1) == 0 ? panel : 3L * panel;
        }
        check(!cadence.qualified(2, panel), "alternating one/three scans reject");
    }

    private static void expiredCompositorHistoryResetsButRecovers() {
        // 2026-09-01: an expired compositor history is an UNVERIFIABLE frame,
        // not a drop.  It is bridged by the next verified present (its scans
        // must still be accounted for), it is never a successful present,
        // and a window that is more than a quarter unverifiable cannot
        // qualify.  Compositor drops keep their fail-closed recovery.
        PhysicalPresentationCadence cadence = new PhysicalPresentationCadence();
        long panel = 8_448_000L;
        long time = 1_000_000_000L;
        for (int index = 0; index < 250; ++index) {
            cadence.recordPresented(time, 1, panel);
            time += panel;
        }
        check(cadence.qualified(1, panel), "pre-expiry cadence qualifies");
        long successes = cadence.successfulPresents();
        cadence.recordUnavailable(1, panel);
        time += panel; // the unverifiable frame occupied its scan
        check(cadence.sampleCount() == 250, "expired history keeps evidence");
        check(cadence.successfulPresents() == successes,
                "expired frame is not a successful present");
        check(cadence.unavailablePresents() == 1,
                "expired frame counted separately");
        cadence.recordPresented(time, 1, panel);
        time += panel;
        check(cadence.qualified(1, panel),
                "one bridged unverifiable frame keeps the proven cadence");
        // A verified present arriving on the WRONG scan after an expiry is
        // still a cadence failure: the bridge accounts for exactly the
        // missing scans, never for a slip.
        cadence.recordUnavailable(1, panel);
        time += panel * 2L; // one unverifiable frame but two scans elapsed
        cadence.recordPresented(time, 1, panel);
        time += panel;
        check(!cadence.qualified(1, panel),
                "a slipped scan behind an expiry does not qualify");
        // Mostly-unverifiable windows cannot qualify.
        PhysicalPresentationCadence dense = new PhysicalPresentationCadence();
        time = 5_000_000_000L;
        for (int index = 0; index < 400; ++index) {
            if (index % 3 != 0) dense.recordUnavailable(1, panel);
            else dense.recordPresented(time, 1, panel);
            time += panel;
        }
        check(!dense.qualified(1, panel),
                "two thirds unverifiable cannot qualify");
    }

    private static void targetClockChangeStartsFreshEvidence() {
        PhysicalPresentationCadence cadence = new PhysicalPresentationCadence();
        long first = 8_333_333L;
        long second = 8_448_000L;
        long time = 1_000_000_000L;
        for (int index = 0; index < 250; ++index) {
            cadence.recordPresented(time, 1, first);
            time += first;
        }
        check(cadence.qualified(1, first), "first panel clock qualifies");
        cadence.recordPresented(time, 1, second);
        check(cadence.sampleCount() == 1, "new measured clock resets history");
        check(!cadence.qualified(1, second), "new clock needs fresh evidence");
    }

    private static void invalidOrNonmonotonicTimestampFailsClosed() {
        PhysicalPresentationCadence cadence = new PhysicalPresentationCadence();
        check(!cadence.recordPresented(0L, 1, 8_333_333L), "zero rejected");
        check(cadence.recordPresented(100L, 1, 8_333_333L), "first accepted");
        check(!cadence.recordPresented(100L, 1, 8_333_333L),
                "duplicate timestamp rejected");
        check(!cadence.recordPresented(99L, 1, 8_333_333L),
                "backward timestamp rejected");
    }

    private static void near(double expected, double actual, double tolerance,
                             String message) {
        if (Math.abs(expected - actual) > tolerance)
            throw new AssertionError(message + " expected=" + expected +
                    " actual=" + actual);
    }

    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
}
