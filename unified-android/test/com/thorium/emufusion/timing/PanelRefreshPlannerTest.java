package com.thorium.emufusion.timing;

/** Covers the panel-mode choice for each kind of display ({@link PanelRefreshPlanner}). */
public final class PanelRefreshPlannerTest {
    private static final double[] THOR = {60.000004, 120.00001};
    private static final double[] PHONE_144 = {60, 90, 120, 144};
    private static final double[] PHONE_90 = {60, 90};
    private static final double[] PAL_FRIENDLY = {48, 50, 60, 90, 100, 120};

    public static void main(String[] args) {
        thorKeepsItsQualifiedModes();
        highRefreshPhonesDoubleOnAnExactLattice();
        noMultipleFitsMeansDirectNotJudder();
        tripleOnlyWhenAllowed();
        palAndVariableRefresh();
        inputsAreSanitized();
        variableSourcesTakeTheFastestMode();
        fourTimesWhenAllowed();
        bestModeForAMeasuredVariableSource();
        replannerSwitchesOnlyForASteadyClearGain();
        replannerMovesASteady60ToTrueDoubling();
        System.out.println("PanelRefreshPlannerTest passed");
    }

    private static void thorKeepsItsQualifiedModes() {
        plan(PanelRefreshPlanner.direct(60, THOR), 60, 1, 1);
        plan(PanelRefreshPlanner.direct(30, THOR), 60, 1, 2);
        plan(PanelRefreshPlanner.direct(20, THOR), 60, 1, 3);
        plan(PanelRefreshPlanner.direct(40, THOR), 120, 1, 3);
        plan(PanelRefreshPlanner.direct(24, THOR), 120, 1, 5);
        plan(PanelRefreshPlanner.generated(60, THOR, 2, 0), 120, 2, 1);
        PanelRefreshPlanner.Plan pal = PanelRefreshPlanner.direct(50, THOR);
        check(!pal.uniform() && Math.abs(pal.panelHz - 120.00001) < 1e-3,
                "a clock no mode divides keeps the fastest mode and says so");
    }

    private static void highRefreshPhonesDoubleOnAnExactLattice() {
        // 60 x 2 = 120; 144 would need the game to run 20% fast.
        plan(PanelRefreshPlanner.generated(60, PHONE_144, 2, 0), 120, 2, 1);
        plan(PanelRefreshPlanner.direct(60, PHONE_144), 60, 1, 1);
        plan(PanelRefreshPlanner.generated(72, PHONE_144, 2, 0), 144, 2, 1);
        // 48 x 2 = 96 fits no mode, so 48 is held for three 144 Hz scans.
        plan(PanelRefreshPlanner.generated(48, PHONE_144, 2, 0), 144, 1, 3);
        plan(PanelRefreshPlanner.generated(48, PHONE_144, 3, 0), 144, 3, 1);
        plan(PanelRefreshPlanner.generated(59.94, PHONE_144, 2, 0), 120, 2, 1);
    }

    private static void noMultipleFitsMeansDirectNotJudder() {
        plan(PanelRefreshPlanner.generated(60, PHONE_90, 2, 0), 60, 1, 1);
        plan(PanelRefreshPlanner.generated(30, PHONE_90, 2, 0), 60, 2, 1);
    }

    private static void tripleOnlyWhenAllowed() {
        plan(PanelRefreshPlanner.generated(30, PHONE_90, 3, 0), 90, 3, 1);
        plan(PanelRefreshPlanner.generated(40, PHONE_144, 3, 0), 120, 3, 1);
        // 40 x 2 = 80 is on no lattice; 40 itself is held for three 120 Hz scans.
        plan(PanelRefreshPlanner.generated(40, PHONE_144, 2, 0), 120, 1, 3);
        plan(PanelRefreshPlanner.generated(60, PHONE_144, 3, 0), 120, 2, 1);
    }

    private static void palAndVariableRefresh() {
        plan(PanelRefreshPlanner.generated(50, PAL_FRIENDLY, 2, 0), 100, 2, 1);
        plan(PanelRefreshPlanner.direct(50, PAL_FRIENDLY), 50, 1, 1);
        PanelRefreshPlanner.Plan vrr = PanelRefreshPlanner.generated(55, THOR, 2, 120);
        check(vrr.variableRefresh && vrr.multiplier == 2 && Math.abs(vrr.panelHz - 110) < 1e-6,
                "a variable-refresh panel shows 2x any clock up to its maximum");
        PanelRefreshPlanner.Plan capped = PanelRefreshPlanner.generated(70, THOR, 2, 120);
        check(!capped.variableRefresh || capped.multiplier == 1,
                "variable refresh never exceeds the panel maximum");
    }

    private static void inputsAreSanitized() {
        plan(PanelRefreshPlanner.generated(0, THOR, 2, 0), 120, 2, 1);
        plan(PanelRefreshPlanner.direct(Double.NaN, new double[] {120, 60, 60.0001, -5}), 60, 1, 1);
        check(PanelRefreshPlanner.validRates(new double[] {60, 60.0001, 120}).length == 2,
                "duplicate modes collapse");
        PanelRefreshPlanner.Plan none = PanelRefreshPlanner.generated(60, new double[0], 2, 0);
        check(!none.uniform(), "no modes cannot claim a lattice");
    }

    private static void variableSourcesTakeTheFastestMode() {
        // Switch/Wii U/PS3 and the 3D cores have no fixed clock: the timeline
        // fills whichever lattice the measured rate allows, so give it the most.
        PanelRefreshPlanner.Plan thor = PanelRefreshPlanner.variable(THOR, 0);
        check(Math.abs(thor.panelHz - 120.00001) < 1e-3 && !thor.uniform() && thor.multiplier == 0,
                "the Thor keeps its 120 Hz mode for variable sources");
        check(Math.abs(PanelRefreshPlanner.variable(PHONE_144, 0).panelHz - 144) < 1e-6,
                "a 60/90/120/144 phone gives variable sources 144 Hz");
        check(Math.abs(PanelRefreshPlanner.variable(PHONE_90, 0).panelHz - 90) < 1e-6,
                "a 60/90 phone gives them 90 Hz");
        check(Math.abs(PanelRefreshPlanner.variable(new double[] {60, 120, 165}, 0).panelHz - 165) < 1e-6,
                "165 Hz panels too");
        PanelRefreshPlanner.Plan arr = PanelRefreshPlanner.variable(PHONE_144, 144);
        check(arr.variableRefresh && Math.abs(arr.panelHz - 144) < 1e-6,
                "an adaptive panel offers its maximum");
        check(Math.abs(PanelRefreshPlanner.variable(new double[0], 0).panelHz - 120) < 1e-6,
                "no mode list falls back to 2 x 60");
    }

    private static void fourTimesWhenAllowed() {
        plan(PanelRefreshPlanner.generated(30, THOR, 4, 0), 120, 4, 1);
        plan(PanelRefreshPlanner.generated(30, THOR, 3, 0), 60, 2, 1);
        plan(PanelRefreshPlanner.generated(36, PHONE_144, 4, 0), 144, 4, 1);
        plan(PanelRefreshPlanner.generated(60, PHONE_144, 4, 0), 120, 2, 1);
        plan(PanelRefreshPlanner.generated(30, PHONE_144, 9, 0), 120, 4, 1);
    }

    private static void bestModeForAMeasuredVariableSource() {
        near(PanelRefreshPlanner.bestForVariable(30, PHONE_144, 4), 120, "30 fps at 4x: 120 (4x), not 144 (72 Hz)");
        near(PanelRefreshPlanner.bestForVariable(30, PHONE_144, 3), 90, "30 fps at 3x: 90 (3x)");
        near(PanelRefreshPlanner.bestForVariable(50, PHONE_144, 3), 144, "50 fps at 3x: 144");
        near(PanelRefreshPlanner.bestForVariable(40, PHONE_144, 3), 120, "40 fps at 3x: 120 (3x)");
        near(PanelRefreshPlanner.bestForVariable(57, PHONE_90, 3), 90, "57 fps on a 60/90 phone: 90");
        near(PanelRefreshPlanner.bestForVariable(45, THOR, 3), 120.00001, "the Thor always 120");
        near(PanelRefreshPlanner.bestForVariable(24, THOR, 4), 120.00001, "the Thor always 120");
        near(PanelRefreshPlanner.bestForVariable(10, PHONE_144, 3), 120, "equal outputs keep the higher mode");
        check(PanelRefreshPlanner.variableScans(144, 30, 4) == 2, "30 fps on 144 at 4x is the 72 Hz lattice");
        check(PanelRefreshPlanner.variableScans(120, 30, 4) == 1, "and 120 on a 120 Hz panel");
        // Doubling (the product's 2x): the mode that doubles beats more output.
        near(PanelRefreshPlanner.bestForVariable(60, PHONE_144, 2), 120, "60 fps: 120 (2x), not 144 (2.4x)");
        near(PanelRefreshPlanner.bestForVariable(45, PHONE_144, 2), 90, "45 fps: 90 (2x)");
        near(PanelRefreshPlanner.bestForVariable(30, PHONE_144, 2), 120, "30 fps: 60 Hz output, the higher mode");
        near(PanelRefreshPlanner.bestForVariable(60, THOR, 2), 120.00001, "the Thor stays 120");
        check(PanelRefreshPlanner.doubles(120, 60, 2) && !PanelRefreshPlanner.doubles(144, 60, 2),
                "120 doubles 60; 144 is the 2.4x fallback");
    }

    private static void replannerMovesASteady60ToTrueDoubling() {
        PanelModeReplanner value = new PanelModeReplanner(PHONE_144, 2, 144);
        double switched = 0;
        long t = 0;
        for (int i = 0; i < 20 && switched == 0; ++i, t += 1000) switched = value.observe(59.9, t);
        near(switched, 120, "a steady 60 fps game moves from 144 to 120 although output falls");
        PanelModeReplanner settled = new PanelModeReplanner(PHONE_144, 2, 120);
        for (int i = 0; i < 60; ++i) check(settled.observe(60, i * 1000L) == 0, "120 already doubles 60");
    }

    private static void replannerSwitchesOnlyForASteadyClearGain() {
        PanelModeReplanner value = new PanelModeReplanner(PHONE_144, 4, 144);
        long t = 0;
        double switched = 0;
        for (int i = 0; i < 20 && switched == 0; ++i, t += 1000) switched = value.observe(30 + (i % 2) * 0.8, t);
        near(switched, 120, "a steady 30 fps game moves to 120");
        check(t >= PanelModeReplanner.STEADY_MS, "only after it held steady");
        for (int i = 0; i < 20; ++i, t += 1000)
            check(value.observe(50, t) == 0, "within the cooldown nothing moves");
        double back = 0;
        for (int i = 0; i < 60 && back == 0; ++i, t += 1000) back = value.observe(50, t);
        near(back, 144, "a sustained 50 fps later earns 144 again");
        for (int i = 0; i < 200; ++i, t += 1000) value.observe(i % 40 < 20 ? 30 : 50, t);
        check(value.switches() <= PanelModeReplanner.MAX_SWITCHES, "never more than two switches a session");
        PanelModeReplanner thor = new PanelModeReplanner(THOR, 4, 120.00001);
        for (int i = 0; i < 120; ++i) check(thor.observe(20 + i % 40, i * 1000L) == 0, "the Thor never re-plans");
        PanelModeReplanner wobbly = new PanelModeReplanner(PHONE_144, 4, 144);
        for (int i = 0; i < 60; ++i) check(wobbly.observe(i % 2 == 0 ? 30 : 45, i * 1000L) == 0,
                "a rate that never settles keeps the launch mode");
    }

    private static void near(double actual, double expected, String message) {
        check(Math.abs(actual - expected) < 0.01, message + ": " + actual);
    }

    private static void plan(PanelRefreshPlanner.Plan plan, double panelHz, int multiplier,
                             int scans) {
        check(Math.abs(plan.panelHz - panelHz) < 0.01, "panel " + plan + " expected " + panelHz);
        check(plan.multiplier == multiplier, "multiplier " + plan + " expected " + multiplier);
        check(plan.scansPerOutput == scans, "scans " + plan + " expected " + scans);
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
