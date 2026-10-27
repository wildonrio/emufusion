package com.thorium.emufusion.video;

public final class PacingModeTrialTest {
    private static final long P = 8_333_333L;

    public static void main(String[] args) {
        aJitterySourceKeepsTheContentTimeTimeline();
        aSourceTheTimelineMakesWorseStaysOnArrival();
        aSteadySourceNeverTries();
        stallsAreNotHolds();
        multiScanOutputsAreLeftAlone();
        aBadStartAloneDoesNotTry();
        System.out.println("PacingModeTrialTest passed");
    }

    /** 30 fps doubled to 60 on 120 Hz: two-scan outputs, many held three; no trial. */
    private static void multiScanOutputsAreLeftAlone() {
        PacingModeTrial trial = new PacingModeTrial();
        long t = 1_000_000_000L;
        for (int i = 0; i < 20 * PacingModeTrial.WINDOW_INTERVALS; ++i) {
            t += (i % 8 == 0) ? 3 * P : 2 * P;
            trial.record(t, P, false);
        }
        check(trial.trials() == 0 && !trial.contentTime(), "no trial for multi-scan outputs");
    }

    /** One uneven window at a game's start, then steady: no trial. */
    private static void aBadStartAloneDoesNotTry() {
        PacingModeTrial trial = new PacingModeTrial();
        long t = 1_000_000_000L;
        for (int i = 0; i < 10 * PacingModeTrial.WINDOW_INTERVALS; ++i) {
            boolean start = i < PacingModeTrial.WINDOW_INTERVALS;
            t += (start && i % 10 == 0) ? 2 * P : P;
            trial.record(t, P, false);
        }
        check(trial.trials() == 0, "a bad start alone starts no trial: " + trial.trials());
    }

    /**
     * Feeds {@code windows} windows of one-scan intervals where every
     * {@code arrivalEvery}-th (arrival pacing) or {@code contentEvery}-th
     * (content-time timeline) is held two scans; returns windows spent on
     * the content-time timeline.
     */
    private static int run(PacingModeTrial trial, int windows, int arrivalEvery, int contentEvery) {
        long t = 1_000_000_000L;
        int contentWindows = 0;
        for (int i = 0; i < windows * PacingModeTrial.WINDOW_INTERVALS; ++i) {
            boolean content = trial.contentTime();
            if (i % PacingModeTrial.WINDOW_INTERVALS == 0 && content) ++contentWindows;
            int every = content ? contentEvery : arrivalEvery;
            t += (every > 0 && i % every == 0) ? 2 * P : P;
            trial.record(t, P, false);
        }
        return contentWindows;
    }

    /** SM3DW: 125 per 1000 held with arrival pacing, 20 with the content-time timeline. */
    private static void aJitterySourceKeepsTheContentTimeTimeline() {
        PacingModeTrial trial = new PacingModeTrial();
        int content = run(trial, 60, 8, 50);
        check(trial.trials() == 1 && trial.kept() == 1, "one trial, kept: " + trial.trials() + "/" + trial.kept());
        check(trial.contentTime(), "on the content-time timeline at the end");
        check(content >= 50, "most windows on the content-time timeline: " + content);
        check(trial.rechecks() >= 1 && trial.rechecks() <= 3, "rechecks back off: " + trial.rechecks());
    }

    /** Dread: 61 per 1000 with arrival pacing, 138 with the content-time timeline. */
    private static void aSourceTheTimelineMakesWorseStaysOnArrival() {
        PacingModeTrial trial = new PacingModeTrial();
        int content = run(trial, 60, 16, 7);
        check(trial.kept() == 0, "never kept");
        check(!trial.contentTime(), "arrival pacing at the end");
        check(trial.trials() <= 4, "failed trials back off: " + trial.trials());
        check(content <= trial.trials(), "one window per trial: " + content);
    }

    private static void aSteadySourceNeverTries() {
        PacingModeTrial trial = new PacingModeTrial();
        run(trial, 30, 1000, 1000);
        check(trial.trials() == 0 && !trial.contentTime(), "no trial for a steady source");
    }

    /** Keep-alive re-shows during a load are not holds. */
    private static void stallsAreNotHolds() {
        PacingModeTrial trial = new PacingModeTrial();
        long t = 1_000_000_000L;
        for (int i = 0; i < 3 * PacingModeTrial.WINDOW_INTERVALS; ++i) {
            boolean keepAlive = i % 3 == 0;
            t += keepAlive ? 5 * P : P;
            trial.record(t, P, keepAlive);
        }
        check(trial.trials() == 0, "stalls start no trial: " + trial.trials());
    }

    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
}
