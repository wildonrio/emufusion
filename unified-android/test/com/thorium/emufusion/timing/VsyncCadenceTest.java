package com.thorium.emufusion.timing;

import com.thorium.emufusion.TestSupport;

public final class VsyncCadenceTest {
    public static void main(String[] ignored) {
        tracksMeasuredTicksWithoutNominalDrift();
        dividesWithoutUnevenHolds();
        retainsMissingCallbackGuestSteps();
        toleratesBriefOverrunsButCoalescesLongCatchUp();
        rejectsUnsafeRatesAndResetsAcrossSleep();
        followsFractionalPanels();
        System.out.println("VsyncCadenceTest passed");
    }

    /** 59.94 and 119.88 Hz panels lock a 60.0 source to their own scans. */
    private static void followsFractionalPanels() {
        long period59 = 16_683_350L;
        VsyncCadence one = warm(60.0, 59.94, period59);
        for (int i = 9; i < 600; i++) {
            long actual = 1_000_000_000L + i * period59;
            one.onVsync(actual);
            TestSupport.equal(actual, one.takeDueTimeNs(), "one source frame per 59.94 Hz scan");
        }
        long period119 = 8_341_675L;
        VsyncCadence two = warm(60.0, 119.88, period119);
        for (int i = 1; i <= 200; i++) {
            two.onVsync(1_000_000_000L + (8 + i) * period119);
            TestSupport.truth(two.hasPending() == (i % 2 == 0), "every second 119.88 Hz scan");
            if (two.hasPending()) two.takeDueTimeNs();
        }
        VsyncCadence pal = new VsyncCadence();
        pal.configure(50.0, 50.0, 59.94);
        for (int i = 0; i <= 20; i++) pal.onVsync(1_000_000_000L + i * period59);
        TestSupport.truth(!pal.ready(), "50 Hz PAL is not pulled to a 60 Hz panel");
    }

    private static VsyncCadence warm(double source, double panel, long period) {
        VsyncCadence clock = new VsyncCadence();
        clock.configure(source, source, panel);
        for (int i = 0; i <= 8; i++) clock.onVsync(1_000_000_000L + i * period);
        TestSupport.truth(clock.ready(), "display clock warmed");
        clock.takeDueTimeNs();
        return clock;
    }

    private static void tracksMeasuredTicksWithoutNominalDrift() {
        long period = 16_662_300L;
        VsyncCadence clock = warm(60, 60, period);
        for (int i = 9; i < 36_000; i++) {
            long actual = 1_000_000_000L + i * period;
            clock.onVsync(actual);
            TestSupport.equal(actual, clock.takeDueTimeNs(), "no free-running phase drift");
            TestSupport.truth(!clock.hasPending(), "one guest step per display tick");
        }
        TestSupport.truth(Math.abs(clock.measuredSourceHz() - 1e9 / period) < 0.0001,
                "audio receives measured rather than nominal clock");
    }

    private static void dividesWithoutUnevenHolds() {
        for (int divisor : new int[] {1, 2, 3, 4, 5, 6}) {
            long period = 8_333_333L;
            VsyncCadence clock = warm(120.0 / divisor, 120, period);
            for (int i = 1; i <= divisor * 100; i++) {
                clock.onVsync(1_000_000_000L + (8 + i) * period);
                TestSupport.truth(clock.hasPending() == (i % divisor == 0),
                        "source advances on an integer number of actual scans");
                if (clock.hasPending()) clock.takeDueTimeNs();
            }
        }
    }

    private static void retainsMissingCallbackGuestSteps() {
        long period = 16_666_667L;
        VsyncCadence clock = warm(60, 60, period);
        clock.onVsync(1_000_000_000L + 10 * period);
        TestSupport.equal(1_000_000_000L + 9 * period, clock.takeDueTimeNs(),
                "missed callback still owes its guest/audio step");
        TestSupport.truth(clock.hasPending(), "obsolete visual may be coalesced");
        TestSupport.equal(1_000_000_000L + 10 * period, clock.takeDueTimeNs(),
                "latest endpoint remains available");
    }

    private static void toleratesBriefOverrunsButCoalescesLongCatchUp() {
        for (int divisor : new int[] {1, 2, 3, 4, 6}) {
            long period = 8_333_333L;
            VsyncCadence clock = warm(120.0 / divisor, 120, period);
            long tick = 8;
            // The next source tick arrives just before this completed frame
            // reaches the mailbox. A future frame is due, but not yet rendered.
            for (int i = 0; i < divisor; i++)
                clock.onVsync(1_000_000_000L + ++tick * period);
            TestSupport.truth(clock.hasPending(), "one next source step is due");
            TestSupport.truth(!clock.coalescingCatchUpPresentation(),
                    "a brief overrun must not discard a completed image");
            // Two owed steps mean a full extra period of lateness. Coalesce
            // this catch-up burst until it reaches the newest endpoint.
            for (int i = 0; i < divisor; i++)
                clock.onVsync(1_000_000_000L + ++tick * period);
            TestSupport.truth(clock.coalescingCatchUpPresentation(),
                    "whole-period lateness starts catch-up coalescing");
            clock.takeDueTimeNs();
            TestSupport.truth(clock.coalescingCatchUpPresentation(),
                    "one-step tail of an existing burst stays coalesced");
            clock.takeDueTimeNs();
            TestSupport.truth(!clock.coalescingCatchUpPresentation(),
                    "newest endpoint is presented when caught up");
            for (int i = 0; i < divisor * 2; i++)
                clock.onVsync(1_000_000_000L + ++tick * period);
            TestSupport.truth(clock.coalescingCatchUpPresentation(),
                    "second burst is active before suspend");
            clock.reset();
            TestSupport.truth(!clock.coalescingCatchUpPresentation(),
                    "suspend/reset clears the catch-up latch");
        }
    }

    private static void rejectsUnsafeRatesAndResetsAcrossSleep() {
        for (double[] rates : new double[][] {{40,40,60}, {60,40,120}, {50,50,60}}) {
            VsyncCadence clock = new VsyncCadence();
            clock.configure(rates[0], rates[1], rates[2]);
            for (int i=0; i<30; i++) clock.onVsync(1_000_000_000L + i*16_666_667L);
            TestSupport.truth(!clock.ready(), "never force unsupported timing");
        }
        VsyncCadence clock = warm(60,60,16_666_667L);
        clock.onVsync(20_000_000_000L);
        TestSupport.truth(!clock.ready() && !clock.hasPending(), "sleep cannot enqueue a burst");
        clock.configure(60,60,120);
        TestSupport.truth(!clock.ready(), "mode changes require fresh timing");
    }
}
