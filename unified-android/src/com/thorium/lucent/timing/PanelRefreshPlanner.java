package com.thorium.lucent.timing;

/**
 * Chooses the physical panel mode for a launch from every fixed refresh rate
 * the display offers, instead of assuming the Thor's 60/120 Hz pair.
 *
 * <p>An emulated game's frame rate is its speed, so the source clock is never
 * changed here. The question is only which panel rate shows that clock -- or,
 * with frame generation, a multiple of it -- on an exact scan lattice: every
 * output frame held for the same whole number of panel scans. A mode that is
 * not an exact multiple (60 fps on a 90 or 144 Hz panel) produces a recurring
 * long/short hold, the judder the owner sees as choppiness.</p>
 *
 * <p>Generation plans for the game's natural clock and its lock tiers at once:
 * a mode that is a multiple of twice the natural rate also holds 2x of every
 * integer division of it (60 -> 30 -> 20), so the frame-rate controller can
 * change tiers without a mid-game mode switch. The multiplier is capped by the
 * owner's setting -- double by default, triple only when asked.</p>
 *
 * <p>Pure Java: the caller supplies the display's mode list.</p>
 */
public final class PanelRefreshPlanner {
    /** A rate assumed for a source whose clock is unknown at launch. */
    public static final double DEFAULT_SOURCE_HZ = 60.0;
    // Panel and console rates are reported as floats (60.000004, 119.88).
    private static final double RELATIVE_TOLERANCE = 0.002;
    private static final int MAX_SCANS_PER_OUTPUT = 8;

    /** The selected mode and how the source occupies it. */
    public static final class Plan {
        public final double panelHz;
        public final double sourceHz;
        /** Output frames per source frame: 1 = direct, 2 = doubled, 3 = tripled. */
        public final int multiplier;
        /** Panel scans each output frame is held for; 0 when not uniform. */
        public final int scansPerOutput;
        public final boolean variableRefresh;

        Plan(double panelHz, double sourceHz, int multiplier, int scansPerOutput,
             boolean variableRefresh) {
            this.panelHz = panelHz;
            this.sourceHz = sourceHz;
            this.multiplier = multiplier;
            this.scansPerOutput = scansPerOutput;
            this.variableRefresh = variableRefresh;
        }

        public double outputHz() { return sourceHz * multiplier; }
        public boolean uniform() { return scansPerOutput > 0; }

        @Override public String toString() {
            return String.format(java.util.Locale.ROOT,
                    "panel=%.3f source=%.3f x%d scans=%d%s", panelHz, sourceHz,
                    multiplier, scansPerOutput, variableRefresh ? " vrr" : "");
        }
    }

    private PanelRefreshPlanner() {}

    /**
     * Direct presentation (no generated frames): the lowest offered rate that
     * holds every source frame for a whole number of scans. On the Thor this
     * is 60 Hz for 60/30/20 and 120 Hz for 40/24, as before. A clock no mode
     * divides (50 Hz PAL on a 60/120 panel) falls back to the fastest mode,
     * which keeps the uneven hold shortest; the plan reports it non-uniform.
     */
    public static Plan direct(double sourceHz, double[] panelRates) {
        double source = sourceOrDefault(sourceHz);
        double[] rates = validRates(panelRates);
        if (rates.length == 0) return new Plan(source, source, 1, 0, false);
        Plan best = lowestLattice(source, 1, rates);
        if (best != null) return best;
        return new Plan(rates[rates.length - 1], source, 1, 0, false);
    }

    /**
     * Presentation with up to {@code maxMultiplier} output frames per source
     * frame. The highest output rate wins; for the same output, fewer
     * generated frames, then the lowest panel rate. When no mode holds a
     * multiple, the plan is direct (a 60/90 Hz phone shows a 60 fps game at
     * 60 Hz rather than judder at 90).
     *
     * @param variableRefreshMaxHz above zero when the panel adapts its rate
     *        continuously (Android ARR); outputs up to it need no fixed mode.
     */
    public static Plan generated(double sourceHz, double[] panelRates, int maxMultiplier,
                                 double variableRefreshMaxHz) {
        double source = sourceOrDefault(sourceHz);
        double[] rates = validRates(panelRates);
        int ceiling = Math.max(1, Math.min(3, maxMultiplier));
        Plan best = null;
        for (int multiplier = ceiling; multiplier >= 1; --multiplier) {
            Plan candidate = null;
            if (variableRefreshMaxHz > 0.0 &&
                    source * multiplier <= variableRefreshMaxHz * (1.0 + RELATIVE_TOLERANCE))
                candidate = new Plan(source * multiplier, source, multiplier, 1, true);
            if (candidate == null && rates.length > 0)
                candidate = lowestLattice(source, multiplier, rates);
            if (candidate != null && (best == null || candidate.outputHz() >
                    best.outputHz() * (1.0 + RELATIVE_TOLERANCE)))
                best = candidate;
        }
        if (best != null) return best;
        return direct(source, rates);
    }

    /** Lowest rate whose scans divide evenly into source * multiplier outputs. */
    private static Plan lowestLattice(double source, int multiplier, double[] ascending) {
        double output = source * multiplier;
        for (double panel : ascending) {
            long scans = Math.round(panel / output);
            if (scans < 1 || scans > MAX_SCANS_PER_OUTPUT) continue;
            if (Math.abs(panel / scans - output) <= output * RELATIVE_TOLERANCE)
                return new Plan(panel, source, multiplier, (int) scans, false);
        }
        return null;
    }

    private static double sourceOrDefault(double sourceHz) {
        return Double.isFinite(sourceHz) && sourceHz >= 10.0 && sourceHz <= 240.0
                ? sourceHz : DEFAULT_SOURCE_HZ;
    }

    /** Finite, positive, de-duplicated, ascending. */
    static double[] validRates(double[] rates) {
        if (rates == null) return new double[0];
        double[] sorted = new double[rates.length];
        int count = 0;
        for (double rate : rates)
            if (Double.isFinite(rate) && rate >= 20.0 && rate <= 1000.0) sorted[count++] = rate;
        sorted = java.util.Arrays.copyOf(sorted, count);
        java.util.Arrays.sort(sorted);
        int unique = 0;
        for (int i = 0; i < sorted.length; ++i)
            if (unique == 0 || Math.abs(sorted[i] - sorted[unique - 1]) >
                    sorted[i] * RELATIVE_TOLERANCE)
                sorted[unique++] = sorted[i];
        return java.util.Arrays.copyOf(sorted, unique);
    }
}
