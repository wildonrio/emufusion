package com.thorium.lucent.video;

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
        if (!validRate(sourceHz) || !validRate(panelHz))
            return new UniformFrameRatePlan(sourceHz, panelHz, 0.0, 0, false);
        if (Double.isFinite(maxGenerationFactor)) {
            int divisor = maxGenerationFactor >= MAX_GENERATION_FACTOR
                    ? panelDivisor(sourceHz * 2.0, panelHz) : 0;
            if (divisor == 0) divisor = panelDivisor(sourceHz, panelHz);
            if (divisor > 0)
                return new UniformFrameRatePlan(sourceHz, panelHz,
                        panelHz / divisor, divisor, true);
        }

        // This is not a cadence qualification.  It is only the honest rate a
        // direct renderer can request while reporting the panel limitation.
        return new UniformFrameRatePlan(sourceHz, panelHz,
                Math.min(sourceHz, panelHz), 0, false);
    }

    private static int panelDivisor(double outputHz, double panelHz) {
        long divisor = Math.round(panelHz / outputHz);
        if (divisor < 1L || divisor > MAX_PANEL_DIVISOR) return 0;
        // Return the physical panel clock, admitting only the existing
        // nanosecond representation tolerance around exact 1x or 2x.
        return Math.abs(panelHz / divisor - outputHz) <= COMPARISON_EPSILON_HZ
                ? (int) divisor : 0;
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
