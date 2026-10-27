package com.thorium.emufusion.video;

/**
 * Holds an engine's images a short wait before the panel callback by trimming
 * its video clock: the rate form of {@link SourcePhaseLock}, for engines
 * (Dolphin, Cemu, Eden, aPS3e) whose frames we cannot delay one by one but
 * whose emulated vsync rate the adapter sets (setPacedVideoHz).
 *
 * <p>Once a second it turns the phase lock's smoothed wait error into a trim
 * of the paced rate: proportional plus integral (the measured panel clock is
 * a few hundred ppm off, a steady drift a proportional term alone would
 * leave as a standing error), within {@link #MAX_TRIM}. A positive error
 * (images early, waiting too long) slows the clock. An engine whose arrivals
 * do not follow its clock (they are set by its own rendering) is left alone
 * once the error stays above {@link #LARGE_ERROR_NS} for
 * {@link #MAX_INEFFECTIVE_UPDATES} updates with the trim at its limit.</p>
 */
public final class SourceRateLock {
    /** At most 0.1%: far inside the clock budget, inaudible in the audio. */
    public static final double MAX_TRIM = 1.0e-3;
    /** Trim per millisecond of error (proportional). */
    public static final double KP_PER_MS = 1.5e-4;
    /** Trim added per millisecond of error each update (integral). */
    public static final double KI_PER_MS = 3.0e-5;
    public static final long DEADBAND_NS = 200_000L;
    public static final long LARGE_ERROR_NS = 1_000_000L;
    public static final int MAX_INEFFECTIVE_UPDATES = 30;

    private double integral;
    private double trim;
    private int saturatedLarge;
    private boolean abandoned;
    private long updates;

    /**
     * One update (about a second apart) with the phase lock's smoothed error;
     * returns the fraction to scale the paced rate by (1 - trim).
     */
    public synchronized double update(double errorNs) {
        if (abandoned || Double.isNaN(errorNs)) return 1.0 - (abandoned ? 0.0 : trim);
        ++updates;
        double errorMs = Math.abs(errorNs) < DEADBAND_NS ? 0.0 : errorNs / 1e6;
        integral = clamp(integral + KI_PER_MS * errorMs);
        trim = clamp(KP_PER_MS * errorMs + integral);
        if (Math.abs(errorNs) > LARGE_ERROR_NS && Math.abs(trim) >= MAX_TRIM) {
            if (++saturatedLarge >= MAX_INEFFECTIVE_UPDATES) {
                abandoned = true;
                trim = 0.0;
                integral = 0.0;
            }
        } else {
            saturatedLarge = 0;
        }
        return 1.0 - trim;
    }

    /** A new stream or clock: start from no trim. */
    public synchronized void reset() {
        integral = 0.0;
        trim = 0.0;
        saturatedLarge = 0;
    }

    private static double clamp(double value) {
        return Math.max(-MAX_TRIM, Math.min(MAX_TRIM, value));
    }

    public synchronized double trim() { return trim; }
    public synchronized boolean abandoned() { return abandoned; }
    public synchronized long updates() { return updates; }
}
