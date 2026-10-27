package com.thorium.emufusion.video;

/**
 * Pixel shifting for static overlays on OLED panels: where the corner frame
 * rate counter sits, by time, so its edges never stay on the same pixels.
 *
 * <p>Each axis follows its own triangle wave, a pixel at a time, within
 * {@link #AMPLITUDE_DP} of the overlay's place. The two periods share no
 * common factor, so over {@link #PERIOD_X_MS} x {@link #PERIOD_Y_MS} the
 * path covers the whole box instead of retracing one diagonal (the same idea
 * as Android's burn-in protection for the always-on display). Steps are a
 * few seconds apart, far too small and slow to see while playing.</p>
 */
public final class BurnInShift {
    /** Furthest the overlay moves from its place on each axis. */
    public static final int AMPLITUDE_DP = 4;
    public static final long PERIOD_X_MS = 127_000L;
    public static final long PERIOD_Y_MS = 331_000L;

    private BurnInShift() {}

    /** Horizontal offset in whole pixels at {@code uptimeMs}. */
    public static int x(long uptimeMs, int amplitudePx) {
        return triangle(uptimeMs, PERIOD_X_MS, amplitudePx);
    }

    /** Vertical offset in whole pixels at {@code uptimeMs}. */
    public static int y(long uptimeMs, int amplitudePx) {
        return triangle(uptimeMs, PERIOD_Y_MS, amplitudePx);
    }

    /**
     * A triangle wave from -amplitude to +amplitude and back once per period,
     * rounded to whole pixels (a sub-pixel offset blurs text instead of
     * moving it).
     */
    static int triangle(long uptimeMs, long periodMs, int amplitudePx) {
        if (amplitudePx <= 0 || periodMs <= 0L) return 0;
        double phase = (double) Math.floorMod(uptimeMs, periodMs) / periodMs;
        double wave = phase < 0.5 ? 4.0 * phase - 1.0 : 3.0 - 4.0 * phase;
        return (int) Math.round(wave * amplitudePx);
    }
}
