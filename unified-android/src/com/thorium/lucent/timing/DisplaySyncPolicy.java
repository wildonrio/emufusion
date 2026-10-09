package com.thorium.lucent.timing;

/**
 * Maps a console's nominal scan clock to a cadence the Thor can present
 * uniformly. The physical panels expose only 60 and 120 Hz; every direct
 * source clock therefore has to be an exact divisor of 120 or it will acquire
 * a recurring long/short hold pattern.
 *
 * <p>Only sub-one-percent corrections are automatic. That covers the normal
 * NTSC-family clocks (59.7275, 59.8261, 59.9227, 60.0988, and their 20/30 Hz
 * divisions) without turning a genuine 50 Hz PAL title into a 60 Hz title.
 * A rate outside this narrow neighborhood remains authentic and is explicitly
 * reported as non-uniform; it needs a proved interpolation path or a matching
 * panel mode, never a misleading average-FPS label.</p>
 */
public final class DisplaySyncPolicy {
    public static final double MAX_RELATIVE_CORRECTION = 0.0075;
    private static final double[] UNIFORM_SOURCE_RATES = {
            120.0, 60.0, 40.0, 30.0, 24.0, 20.0, 15.0, 12.0, 10.0
    };

    private DisplaySyncPolicy() {}

    /** Returns the exact synchronized source clock, or the original rate. */
    public static double synchronizedSourceHz(double declaredHz) {
        if (!Double.isFinite(declaredHz) || declaredHz <= 1.0 || declaredHz >= 1000.0)
            return declaredHz;
        double best = declaredHz;
        double bestError = Double.POSITIVE_INFINITY;
        for (double candidate : UNIFORM_SOURCE_RATES) {
            double error = Math.abs(declaredHz - candidate) / declaredHz;
            if (error < bestError) {
                bestError = error;
                best = candidate;
            }
        }
        return permitsCoreClockCorrection(declaredHz, best) ? best : declaredHz;
    }

    /**
     * A presentation clock trim must remain near the original guest clock,
     * never near a previously slowed tier. Load, unique-image FPS and panel
     * divisibility do not authorize changing gameplay speed by 10-50 percent.
     * The zero/reset sentinel is handled separately by the session APIs.
     */
    public static boolean permitsCoreClockCorrection(double declaredHz, double targetHz) {
        return Double.isFinite(declaredHz) && declaredHz > 1.0 && declaredHz < 1000.0 &&
                Double.isFinite(targetHz) && targetHz > 1.0 && targetHz < 1000.0 &&
                Math.abs(targetHz / declaredHz - 1.0) <= MAX_RELATIVE_CORRECTION + 1.0e-12;
    }

    /** Closest physical divisor inside the original guest-clock budget; zero refuses. */
    public static double physicalSourceHz(double declaredHz, double panelHz) {
        if (!Double.isFinite(panelHz) || panelHz < 20.0 || panelHz > 1000.0 ||
                !Double.isFinite(declaredHz) || declaredHz <= 1.0) return 0.0;
        long scans = Math.round(panelHz / declaredHz);
        if (scans < 1 || scans > 1000) return 0.0;
        double target = panelHz / scans;
        return permitsCoreClockCorrection(declaredHz, target) ? target : 0.0;
    }

    public static boolean isUniformOnThor(double sourceHz) {
        double synchronizedHz = synchronizedSourceHz(sourceHz);
        for (double candidate : UNIFORM_SOURCE_RATES)
            if (Math.abs(synchronizedHz - candidate) < 1.0e-9) return true;
        return false;
    }

    /**
     * Thor presentation policy: preserve its native 120 Hz scan for every
     * source. Canonical 60/40/30/24/20 Hz clocks are exact divisors of 120,
     * while forcing the OLED down to 60 reintroduced a physically measured
     * skipped scan in an otherwise exact 60 Hz GBA stream. OFF uses this only
     * as a physical display-mode vote; the emulator still owns the exact raw
     * Surface and no intermediate renderer exists.
     */
    public static float panelRefreshHz(double sourceHz) {
        return 120.0f;
    }

    /**
     * Selects the physical mode for strict direct presentation.  A native
     * 60 Hz scan avoids asking SurfaceFlinger to choose every second scan for
     * 60/30/20 Hz content; that choice produced an otherwise unexplained
     * third-scan hold on the Thor even when the buffer was ready on time.
     * Sources such as 40 and 24 Hz remain on 120 because 60 is not an integer
     * multiple of either rate.  Unknown and genuinely non-uniform clocks also
     * remain on 120 rather than being silently retimed.
     */
    public static float directPanelRefreshHz(double sourceHz) {
        double synchronizedHz = synchronizedSourceHz(sourceHz);
        if (!Double.isFinite(synchronizedHz) || synchronizedHz <= 0.0 ||
                synchronizedHz > 60.0) return 120.0f;
        double scansPerFrame = 60.0 / synchronizedHz;
        return Math.abs(scansPerFrame - Math.rint(scansPerFrame)) < 1.0e-9
                ? 60.0f : 120.0f;
    }

}
