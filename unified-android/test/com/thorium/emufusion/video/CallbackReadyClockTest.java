package com.thorium.emufusion.video;

public final class CallbackReadyClockTest {
    private static final long PERIOD = 8_333_333L;
    private static final long RUN_DELAY = 700_000L;

    public static void main(String[] args) {
        firstCallbackAfterAdmission();
        admittedDuringTheCurrentCallback();
        sixtyFpsPhaseNoLongerDecidesLateStarts();
        aSkippedCallbackIsStillLate();
        oldAdmissionsAndUnknowns();
        System.out.println("CallbackReadyClockTest passed");
    }

    private static void firstCallbackAfterAdmission() {
        CallbackReadyClock clock = new CallbackReadyClock();
        long vsync = 1_000_000_000L;
        for (int i = 0; i < 4; ++i) clock.callback(vsync + i * PERIOD, vsync + i * PERIOD + RUN_DELAY);
        long current = vsync + 3 * PERIOD;
        // Admitted between the second and third callbacks' starts.
        eq(vsync + 2 * PERIOD, clock.readyNs(vsync + PERIOD + RUN_DELAY + 1, current), "third callback");
        // Admitted after the third vsync but before its callback ran: that callback could see it.
        eq(vsync + 2 * PERIOD, clock.readyNs(vsync + 2 * PERIOD + 100_000L, current), "same callback");
    }

    private static void admittedDuringTheCurrentCallback() {
        CallbackReadyClock clock = new CallbackReadyClock();
        long vsync = 2_000_000_000L;
        clock.callback(vsync, vsync + RUN_DELAY);
        // pollSignatureOnVsync commits inside the running callback.
        eq(vsync, clock.readyNs(vsync + RUN_DELAY + 300_000L, vsync), "the current callback takes it up");
    }

    private static void sixtyFpsPhaseNoLongerDecidesLateStarts() {
        // 60 -> 120: images arrive 1.5-7.5 ms after a callback started; each
        // is taken up at the next callback. Time since admission ran to 7 ms
        // (late at the old 4.2 ms threshold); counted from readyNs it is 0.
        long span = 2 * PERIOD, threshold = span / 2L - PERIOD / 2L;
        for (long phase = 1_500_000L; phase <= 7_500_000L; phase += 500_000L) {
            CallbackReadyClock clock = new CallbackReadyClock();
            long vsync = 3_000_000_000L;
            clock.callback(vsync, vsync + RUN_DELAY);
            long admitted = vsync + RUN_DELAY + phase - RUN_DELAY;
            long next = vsync + PERIOD;
            clock.callback(next, next + RUN_DELAY);
            long waited = next - clock.readyNs(admitted, next);
            check(waited == 0L, "taken up at the first callback that could see it, phase " + phase);
            check(next - admitted <= threshold == phase >= PERIOD - threshold,
                    "the old measure depended on the phase");
        }
    }

    private static void aSkippedCallbackIsStillLate() {
        // An image admitted as its predecessor's real image is due waits a
        // callback: NSMBU Deluxe's one-scan offset must still catch up.
        CallbackReadyClock clock = new CallbackReadyClock();
        long vsync = 4_000_000_000L;
        clock.callback(vsync, vsync + RUN_DELAY);
        long admitted = vsync + 300_000L; // before that callback ran: it could have seen it
        clock.callback(vsync + PERIOD, vsync + PERIOD + RUN_DELAY);
        long waited = vsync + PERIOD - clock.readyNs(admitted, vsync + PERIOD);
        eq(PERIOD, waited, "one whole scan");
        check(waited > 2 * PERIOD / 2L - PERIOD / 2L, "late at 60 -> 120");
    }

    private static void oldAdmissionsAndUnknowns() {
        CallbackReadyClock clock = new CallbackReadyClock();
        eq(0L, clock.readyNs(0L, 5L), "unknown admission stays unknown");
        eq(7L, clock.readyNs(3L, 7L), "no callbacks recorded: the current one");
        long vsync = 5_000_000_000L;
        for (int i = 0; i < 40; ++i) clock.callback(vsync + i * PERIOD, vsync + i * PERIOD + RUN_DELAY);
        eq(vsync + 24 * PERIOD, clock.readyNs(vsync, vsync + 39 * PERIOD), "older than the ring: its oldest callback");
        clock.reset();
        eq(9L, clock.readyNs(vsync, 9L), "reset forgets callbacks");
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    private static void eq(long expected, long actual, String message) {
        if (expected != actual) throw new AssertionError(message + ": expected " + expected + " got " + actual);
    }
}
