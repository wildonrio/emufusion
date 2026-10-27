package com.thorium.emufusion.video;

public final class PresentRhythmTest {
    private static final long P = 8_333_333L;

    public static void main(String[] args) {
        anEvenDoubledStreamHasNoHitches();
        aHeldFrameIsOneHitch();
        aHitchTheSchedulerAskedForIsOnIntended();
        pausesAreGapsNotHitches();
        aShortWindowPublishesNothing();
        System.out.println("PresentRhythmTest passed");
    }

    /** 60 -> 120 doubling, every frame one refresh, with a few hundred us of jitter. */
    private static void anEvenDoubledStreamHasNoHitches() {
        PresentRhythm r = new PresentRhythm();
        long t = 1_000_000_000L;
        boolean published = false;
        for (int i = 0; i < 3700; ++i, t += P)
            published |= r.record(t, t + (i % 3) * 200_000L, P);
        check(published, "a window");
        eq(1, r.usualScans(), "one refresh each");
        eq(0, r.hitches(), "no hitches");
        check(r.onIntendedPercent() > 99.9, "on intended");
        check(r.intervals() >= 3590, "intervals counted");
    }

    /** A frame the compositor showed a refresh late: two refreshes, then back on the lattice. */
    private static void aHeldFrameIsOneHitch() {
        PresentRhythm r = new PresentRhythm();
        long t = 1_000_000_000L;
        boolean published = false;
        for (int i = 0; i < 3700 && !published; ++i, t += P) {
            long actual = t;
            if (i == 500) actual = t + P;            // shown one scan late
            if (i == 501) continue;                  // its successor never got a refresh
            published = r.record(t, actual, P);
        }
        check(published, "a window");
        eq(1, r.hitches(), "one hitch");
        eq(1, r.shownForScans(2), "one frame shown two refreshes");
        check(r.onIntendedPercent() < 100.0, "not what was asked");
    }

    private static void aHitchTheSchedulerAskedForIsOnIntended() {
        PresentRhythm r = new PresentRhythm();
        long t = 1_000_000_000L;
        boolean published = false;
        for (int i = 0; i < 3700 && !published; ++i, t += P) {
            if (i == 900) t += P;                    // a planned hold: asked two refreshes
            published = r.record(t, t, P);
        }
        check(published, "a window");
        eq(1, r.hitches(), "still a hitch on screen");
        check(r.onIntendedPercent() > 99.9, "but the one asked for");
    }

    private static void pausesAreGapsNotHitches() {
        PresentRhythm r = new PresentRhythm();
        long t = 1_000_000_000L;
        boolean published = false;
        for (int i = 0; i < 4000 && !published; ++i, t += P) {
            if (i == 1000) t += 2_000_000_000L;      // a two-second menu pause
            published = r.record(t, t, P);
        }
        check(published, "a window");
        eq(0, r.hitches(), "a pause is not a hitch");
        eq(1, r.gaps(), "one gap");
    }

    private static void aShortWindowPublishesNothing() {
        PresentRhythm r = new PresentRhythm();
        long t = 1_000_000_000L;
        boolean published = false;
        // Thirty seconds that are mostly a stall: too few intervals to judge.
        for (int i = 0; i < 40; ++i, t += P) published |= r.record(t, t, P);
        published |= r.record(t + PresentRhythm.WINDOW_NS, t + PresentRhythm.WINDOW_NS, P);
        check(!published, "nothing published");
        eq(0L, r.windows(), "no window");
    }

    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    private static void eq(long expected, long actual, String message) {
        if (expected != actual)
            throw new AssertionError(message + ": expected " + expected + " got " + actual);
    }
}
