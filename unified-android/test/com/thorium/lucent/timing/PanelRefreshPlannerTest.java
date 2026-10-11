package com.thorium.lucent.timing;

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
