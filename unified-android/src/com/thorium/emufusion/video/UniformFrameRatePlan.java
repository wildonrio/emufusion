package com.thorium.emufusion.video;

/**
 * Selects a presentation cadence that occupies an integer number of panel
 * scans without changing the measured emulator clock.
 *
 * <p>The source and panel clocks deliberately remain doubles.  Rounding a
 * proven 23.976/29.97/59.94 clock before this decision can select an output
 * that is slightly faster than 2x source or that does not actually divide the
 * measured panel.  A caller may give this class a canonical rational clock,
 * but only after timestamp evidence has established that identity.</p>
 */
public final class UniformFrameRatePlan {
    private static final int MAX_PANEL_DIVISOR = 1000;
    public static final double MAX_GENERATION_FACTOR = 2.0;
    /** Frame generation On fills the panel up to 3x (timeline scheduler only). */
    public static final double TRIPLE_GENERATION_FACTOR = 3.0;
    /** The owner's "Allow 4x" ceiling: 30 fps games reach 120 Hz (timeline only). */
    public static final double QUAD_GENERATION_FACTOR = 4.0;
    // Nanosecond timestamp quantization turns an exact nominal60 period into
    // 59.9999988 Hz.  Ten microhertz admits that representation error while
    // remaining four orders of magnitude below the 29.97-vs-30 distinction.
    private static final double COMPARISON_EPSILON_HZ = 1.0e-5;

    private final double sourceHz;
    private final double panelHz;
    private final double outputHz;
    private final int panelScansPerOutput;
    private final boolean qualified;

    private UniformFrameRatePlan(double sourceHz, double panelHz,
                                 double outputHz, int panelScansPerOutput,
                                 boolean qualified) {
        this.sourceHz = sourceHz;
        this.panelHz = panelHz;
        this.outputHz = outputHz;
        this.panelScansPerOutput = panelScansPerOutput;
        this.qualified = qualified;
    }

    /**
     * Selects exact doubling when it fits the panel, otherwise exact Direct.
     *
     * <p>Every generated pair has one midpoint. Both doubled and Direct
     * output must occupy an integer number of panel scans. On a 120-Hz panel
     * this gives 20->40, 30->60 and 60->120, while 40 and 24 remain Direct.
     * On a 60-Hz panel 30 doubles to 60; 20 and 60 remain Direct. This
     * selector never drops source frames, changes their clock, or substitutes
     * a fractional conversion such as 40->60.</p>
     *
     * <p>If the panel is slower than the source or no divisor exists, the
     * result is an explicitly unqualified direct/panel-limited fallback.</p>
     */
    public static UniformFrameRatePlan select(double sourceHz, double panelHz) {
        return select(sourceHz, panelHz, MAX_GENERATION_FACTOR);
    }

    /**
     * Same protocol with a backend generation ceiling. A finite ceiling below
     * two permits Direct only; one above two cannot authorize extra frames.
     * A nonfinite ceiling leaves the fallback explicitly unqualified.
     */
    public static UniformFrameRatePlan select(double sourceHz, double panelHz,
                                              double maxGenerationFactor) {
        return select(sourceHz, panelHz, maxGenerationFactor, 0.0);
    }

    /**
     * Same protocol, optionally tripling and optionally accepting a source a
     * small relative distance from an exact divisor. Only the timeline
     * scheduler, which samples each output at its own source time, may pass
     * either: the exact one-midpoint lattice needs both exact. The highest
     * output wins (40 fps on 120 Hz triples to 120; 30 doubles to 60, or
     * quadruples to 120 when 4x is allowed).
     */
    public static UniformFrameRatePlan select(double sourceHz, double panelHz,
                                              double maxGenerationFactor,
                                              double relativeTolerance) {
        if (!validRate(sourceHz) || !validRate(panelHz))
            return new UniformFrameRatePlan(sourceHz, panelHz, 0.0, 0, false);
        double tolerance = Double.isFinite(relativeTolerance) && relativeTolerance > 0.0
                ? Math.min(0.02, relativeTolerance) : 0.0;
        if (Double.isFinite(maxGenerationFactor)) {
            int divisor = maxGenerationFactor >= QUAD_GENERATION_FACTOR
                    ? panelDivisor(sourceHz * 4.0, panelHz, tolerance) : 0;
            if (divisor == 0 && maxGenerationFactor >= TRIPLE_GENERATION_FACTOR)
                divisor = panelDivisor(sourceHz * 3.0, panelHz, tolerance);
            if (divisor == 0 && maxGenerationFactor >= MAX_GENERATION_FACTOR)
                divisor = panelDivisor(sourceHz * 2.0, panelHz, tolerance);
            if (divisor == 0) divisor = panelDivisor(sourceHz, panelHz, tolerance);
            if (divisor > 0)
                return new UniformFrameRatePlan(sourceHz, panelHz,
                        panelHz / divisor, divisor, true);
        }

        // This is not a cadence qualification.  It is only the honest rate a
        // direct renderer can request while reporting the panel limitation.
        return new UniformFrameRatePlan(sourceHz, panelHz,
                Math.min(sourceHz, panelHz), 0, false);
    }

    private static int panelDivisor(double outputHz, double panelHz, double relativeTolerance) {
        long divisor = Math.round(panelHz / outputHz);
        if (divisor < 1L || divisor > MAX_PANEL_DIVISOR) return 0;
        // Return the physical panel clock, admitting only the existing
        // nanosecond representation tolerance around the exact multiple
        // unless the caller's scheduler absorbs a small relative offset.
        double allowed = Math.max(COMPARISON_EPSILON_HZ, outputHz * relativeTolerance);
        return Math.abs(panelHz / divisor - outputHz) <= allowed ? (int) divisor : 0;
    }

    private static boolean validRate(double value) {
        return Double.isFinite(value) && value > 0.0 && value <= 1000.0;
    }

    public double sourceHz() { return sourceHz; }
    public double panelHz() { return panelHz; }
    public double outputHz() { return outputHz; }
    public int panelScansPerOutput() { return panelScansPerOutput; }
    public boolean qualified() { return qualified; }
    public boolean generatesIntermediateFrames() {
        return qualified && outputHz > sourceHz + COMPARISON_EPSILON_HZ;
    }
}
