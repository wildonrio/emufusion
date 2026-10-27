package com.thorium.emufusion.timing;

/**
 * Re-picks the panel mode for a variable source once its rate is known.
 *
 * <p>A game with no fixed clock launches on the fastest mode
 * ({@link PanelRefreshPlanner#variable}). Which mode serves it best depends on
 * the rate it actually runs at: with Allow 4x a 30 fps game reaches 120 Hz on
 * a 120 Hz mode but only 72 on 144. After the measured rate has held steady
 * this re-plans with {@link PanelRefreshPlanner#bestForVariable}, and only
 * for a clear gain or a true doubling, rarely, so the panel does not hop
 * between modes. On the
 * Thor (60/120) the best mode is always 120 and nothing ever changes.</p>
 *
 * <p>Pure Java; the host feeds the generator's sustained source rate.</p>
 */
public final class PanelModeReplanner {
    /** A rate must hold within this fraction for {@link #STEADY_MS}. */
    static final double STEADY_FRACTION = 0.10;
    static final long STEADY_MS = 8_000L;
    /** The new mode must give at least this much more generated output. */
    static final double MIN_OUTPUT_GAIN = 1.15;
    static final long COOLDOWN_MS = 30_000L;
    static final int MAX_SWITCHES = 2;

    private final double[] rates;
    private final int maxMultiplier;
    private double currentPanelHz;
    private double steadyHz;
    private long steadySinceMs = -1L;
    private long lastSwitchMs = Long.MIN_VALUE / 2;
    private int switches;

    public PanelModeReplanner(double[] panelRates, int maxMultiplier, double currentPanelHz) {
        this.rates = PanelRefreshPlanner.validRates(panelRates);
        this.maxMultiplier = maxMultiplier;
        this.currentPanelHz = currentPanelHz;
    }

    /**
     * @return the mode to request now, or 0 to keep the current one
     */
    public double observe(double sourceHz, long nowMs) {
        if (!(sourceHz >= 19.5) || rates.length < 2 || switches >= MAX_SWITCHES) {
            steadySinceMs = -1L;
            return 0.0;
        }
        if (steadySinceMs < 0L || Math.abs(sourceHz - steadyHz) > steadyHz * STEADY_FRACTION) {
            steadyHz = sourceHz;
            steadySinceMs = nowMs;
            return 0.0;
        }
        if (nowMs - steadySinceMs < STEADY_MS || nowMs - lastSwitchMs < COOLDOWN_MS) return 0.0;
        double best = PanelRefreshPlanner.bestForVariable(steadyHz, rates, maxMultiplier);
        if (!(best > 0.0) || Math.abs(best - currentPanelHz) <= currentPanelHz * 0.002) return 0.0;
        double now = output(currentPanelHz, steadyHz);
        double then = output(best, steadyHz);
        // A clear gain, or a mode that doubles the source where the current
        // one only reaches the 1.3 x fallback (60 fps on 144 Hz -> 120 Hz).
        int multiplier = Math.max(1, Math.min(4, maxMultiplier));
        boolean fitsDoubling = PanelRefreshPlanner.doubles(best, steadyHz, multiplier) &&
                !PanelRefreshPlanner.doubles(currentPanelHz, steadyHz, multiplier);
        if (!(then >= now * MIN_OUTPUT_GAIN) && !fitsDoubling) return 0.0;
        currentPanelHz = best;
        lastSwitchMs = nowMs;
        ++switches;
        steadySinceMs = -1L;
        return best;
    }

    private double output(double panelHz, double sourceHz) {
        int scans = PanelRefreshPlanner.variableScans(panelHz, sourceHz,
                Math.max(1, Math.min(4, maxMultiplier)));
        return scans > 0 ? panelHz / scans : sourceHz;
    }

    public int switches() { return switches; }
}
