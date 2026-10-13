package com.thorium.emufusion.video;

public final class UniformFrameRatePlanTest {
    public static void main(String[] args) {
        commonPanelMappings();
        fractionalClocksRequireMatchingPanels();
        noFractionalOrTripleGeneration();
        timestampQuantizationOnly();
        measuredThorMismatchRequiresClockCorrection();
        invalidInputsFailClosed();
        everyIntegerClockObeysBothLattices();
        timelineTripleAndTolerance();
        System.out.println("UniformFrameRatePlanTest passed");
    }

    private static void measuredThorMismatchRequiresClockCorrection() {
        UniformFrameRatePlan mismatch = UniformFrameRatePlan.select(60.0, 119.945005);
        check(!mismatch.qualified() && !mismatch.generatesIntermediateFrames(),
                "observed DS mismatch cannot authorize estimator output");
        UniformFrameRatePlan corrected = UniformFrameRatePlan.select(119.945005 / 2.0, 119.945005);
        check(corrected.qualified() && corrected.generatesIntermediateFrames(),
                "actual matching source clock permits exact doubling");
    }

    private static void commonPanelMappings() {
        plan(120.0, 10.0, 20.0, 6);
        plan(120.0, 12.0, 24.0, 5);
        plan(120.0, 15.0, 30.0, 4);
        plan(120.0, 20.0, 40.0, 3);
        plan(120.0, 24.0, 24.0, 5);
        plan(120.0, 30.0, 60.0, 2);
        plan(120.0, 40.0, 40.0, 3);
        plan(120.0, 60.0, 120.0, 1);
        plan(120.0, 120.0, 120.0, 1);
        plan(60.0, 10.0, 20.0, 3);
        plan(60.0, 12.0, 12.0, 5);
        plan(60.0, 15.0, 30.0, 2);
        plan(60.0, 20.0, 20.0, 3);
        plan(60.0, 30.0, 60.0, 1);
        plan(60.0, 60.0, 60.0, 1);
        plan(80.0, 40.0, 80.0, 1);
        plan(80.0, 20.0, 40.0, 2);
        plan(80.0, 80.0, 80.0, 1);
        unqualified(30.0, 80.0);
        unqualified(60.0, 80.0);
        unqualified(24.0, 60.0);
        unqualified(40.0, 60.0);
        for (double source : new double[] {25.0, 50.0, 80.0, 75.0, 1000.0}) {
            unqualified(source, 60.0);
            unqualified(source, 120.0);
        }
        UniformFrameRatePlan boundary = UniformFrameRatePlan.select(0.12, 120.0, 1.0);
        check(boundary.qualified(), "1000 scan Direct hold remains supported");
        eq(1000, boundary.panelScansPerOutput(), "maximum scan hold");
        unqualified(0.01, 120.0);
    }

    private static void fractionalClocksRequireMatchingPanels() {
        double ntsc60 = 60000.0 / 1001.0;
        double ntsc120 = 120000.0 / 1001.0;
        plan(ntsc120, ntsc60, ntsc120, 1);
        plan(ntsc120, ntsc60 / 2.0, ntsc60, 2);
        plan(ntsc120, ntsc60 / 3.0, ntsc120 / 3.0, 3);
        plan(ntsc120, 24000.0 / 1001.0, 24000.0 / 1001.0, 5);
        plan(ntsc60, ntsc60, ntsc60, 1);
        plan(ntsc60, ntsc60 / 2.0, ntsc60, 1);
        plan(ntsc60, ntsc60 / 3.0, ntsc60 / 3.0, 3);
        plan(119.88, 59.94, 119.88, 1);
        plan(59.94, 29.97, 59.94, 1);
        unqualified(ntsc60, 120.0);
        unqualified(ntsc60 / 2.0, 120.0);
        unqualified(60.0, ntsc120);
        unqualified(30.0, ntsc120);
        unqualified(59.94, ntsc120);
        plan(119.99, 119.99 / 4.0, 119.99 / 2.0, 2);
        unqualified(30.0, 119.99);
        for (double source : new double[] {19.9, 29.8, 37.25, 57.4, 58.0, 60.1}) {
            unqualified(source, 120.0);
            unqualified(source, 60.0);
        }
    }

    private static void noFractionalOrTripleGeneration() {
        for (double ceiling : new double[] {-1.0, 0.0, 1.0, 1.5, Math.nextDown(2.0)}) {
            UniformFrameRatePlan plan = UniformFrameRatePlan.select(30.0, 120.0, ceiling);
            check(plan.qualified(), "finite ceiling permits uniform Direct");
            near(30.0, plan.outputHz(), 1.0e-9, "ceiling below two is Direct only");
            eq(4, plan.panelScansPerOutput(), "Direct panel hold");
            check(!plan.generatesIntermediateFrames(), "Direct is not generated");
        }
        for (double ceiling : new double[] {2.0, Math.nextDown(3.0)}) {
            near(40.0, UniformFrameRatePlan.select(20.0, 120.0, ceiling).outputHz(),
                    1.0e-9, "a doubling ceiling never permits 20->60");
            near(40.0, UniformFrameRatePlan.select(40.0, 120.0, ceiling).outputHz(),
                    1.0e-9, "a doubling ceiling never permits 40->60 or 40->120");
        }
        // AUTO (TRIPLE) is the only way to a ceiling of three; never fractional.
        for (double ceiling : new double[] {3.0, 100.0, Double.MAX_VALUE}) {
            near(60.0, UniformFrameRatePlan.select(20.0, 120.0, ceiling).outputHz(),
                    1.0e-9, "the triple ceiling permits exact 20->60");
            near(120.0, UniformFrameRatePlan.select(40.0, 120.0, ceiling).outputHz(),
                    1.0e-9, "the triple ceiling permits exact 40->120, never 40->60");
        }
    }

    private static void timestampQuantizationOnly() {
        double rounded60 = 1_000_000_000.0 / 16_666_667L;
        double rounded30 = 1_000_000_000.0 / 33_333_333L;
        plan(120.0, rounded60, 120.0, 1);
        plan(120.0, rounded30, 60.0, 2);
        plan(60.0, rounded60, 60.0, 1);
        plan(120.0 + 0.000005, 60.0, 120.0 + 0.000005, 1);
        unqualified(60.0, 120.0 + 0.0001);
        unqualified(60.0 + 0.0001, 120.0);
    }

    private static void invalidInputsFailClosed() {
        for (double value : new double[] {Double.NaN, Double.POSITIVE_INFINITY,
                Double.NEGATIVE_INFINITY, -1.0, 0.0, 1000.1}) {
            rejectedClock(UniformFrameRatePlan.select(value, 120.0));
            rejectedClock(UniformFrameRatePlan.select(30.0, value));
        }
        for (double ceiling : new double[] {Double.NaN, Double.POSITIVE_INFINITY,
                Double.NEGATIVE_INFINITY}) {
            UniformFrameRatePlan plan = UniformFrameRatePlan.select(30.0, 120.0, ceiling);
            check(!plan.qualified(), "nonfinite ceiling cannot qualify output");
            eq(0, plan.panelScansPerOutput(), "nonfinite ceiling has no scan claim");
            near(30.0, plan.outputHz(), 0.0, "valid clocks retain honest Direct fallback");
            check(!plan.generatesIntermediateFrames(), "nonfinite ceiling cannot generate");
        }
    }

    private static void everyIntegerClockObeysBothLattices() {
        for (int panel = 20; panel <= 240; ++panel) {
            for (int source = 1; source <= 240; ++source) {
                UniformFrameRatePlan plan = UniformFrameRatePlan.select(source, panel);
                int expectedFactor = panel % (2 * source) == 0 ? 2 :
                        panel % source == 0 ? 1 : 0;
                check(plan.qualified() == (expectedFactor > 0),
                        "qualification matches both integer clocks: " + source + "/" + panel);
                if (expectedFactor == 0) {
                    check(!plan.generatesIntermediateFrames(), "unqualified never generates");
                    eq(0, plan.panelScansPerOutput(), "unqualified has no scan hold");
                } else {
                    near(source * expectedFactor, plan.outputHz(), 1.0e-9,
                            "output is only exact 1x or 2x");
                    eq(panel / (source * expectedFactor), plan.panelScansPerOutput(),
                            "same whole hold for every output");
                    check(plan.generatesIntermediateFrames() == (expectedFactor == 2),
                            "only midpoint output counts as generated");
                }
            }
        }
    }

    private static void timelineTripleAndTolerance() {
        // AUTO (TRIPLE): the highest exact output wins.
        UniformFrameRatePlan forty = UniformFrameRatePlan.select(40.0, 120.0, 3.0, 0.0);
        near(120.0, forty.outputHz(), 1e-9, "40 triples to 120");
        eq(1, forty.panelScansPerOutput(), "40x3 holds one scan");
        near(60.0, UniformFrameRatePlan.select(30.0, 120.0, 3.0, 0.0).outputHz(), 1e-9,
                "30 cannot triple to 90 on 120 Hz and doubles");
        near(60.0, UniformFrameRatePlan.select(20.0, 120.0, 3.0, 0.0).outputHz(), 1e-9,
                "20 triples to 60 rather than doubling to 40");
        near(120.0, UniformFrameRatePlan.select(60.0, 120.0, 3.0, 0.0).outputHz(), 1e-9,
                "60 cannot triple on 120 Hz and doubles");
        near(144.0, UniformFrameRatePlan.select(48.0, 144.0, 3.0, 0.0).outputHz(), 1e-9,
                "48 triples to 144");
        near(80.0, UniformFrameRatePlan.select(40.0, 120.0, 2.0, 0.0).outputHz() * 2.0, 1e-9,
                "a 2x ceiling never triples (40 stays Direct)");
        // "Allow 4x" (owner, 2026-10-12): 30 fps games reach 120 Hz.
        UniformFrameRatePlan thirty = UniformFrameRatePlan.select(30.0, 120.0,
                UniformFrameRatePlan.QUAD_GENERATION_FACTOR, 0.0);
        near(120.0, thirty.outputHz(), 1e-9, "30 quadruples to 120");
        eq(1, thirty.panelScansPerOutput(), "30x4 holds one scan");
        near(120.0, UniformFrameRatePlan.select(40.0, 120.0, 4.0, 0.0).outputHz(), 1e-9,
                "40 still triples to 120 under the 4x ceiling");
        near(60.0, UniformFrameRatePlan.select(15.0, 120.0, 4.0, 0.0).outputHz(), 1e-9,
                "15 quadruples to 60");
        near(120.0, UniformFrameRatePlan.select(60.0, 120.0, 4.0, 0.0).outputHz(), 1e-9,
                "60 still doubles to 120");
        check(UniformFrameRatePlan.select(29.983, 119.906, 4.0, 0.005).panelScansPerOutput() == 1,
                "the timeline quadruples a near-divisor 30 Hz clock");
        // Timeline tolerance: the Thor's 3DS clock against its measured panel.
        check(!UniformFrameRatePlan.select(29.983, 119.906, 2.0).generatesIntermediateFrames(),
                "the exact lattice refuses a clock just off the divisor");
        UniformFrameRatePlan near3ds = UniformFrameRatePlan.select(29.983, 119.906, 2.0, 0.005);
        check(near3ds.generatesIntermediateFrames(), "the timeline doubles a near-divisor clock");
        eq(2, near3ds.panelScansPerOutput(), "near-3DS doubles to two scans");
        check(!UniformFrameRatePlan.select(58.0, 120.0, 2.0, 0.005).qualified(),
                "a game below its tier is not a near-divisor clock");
    }

    private static void rejectedClock(UniformFrameRatePlan plan) {
        check(!plan.qualified(), "invalid clock rejected");
        near(0.0, plan.outputHz(), 0.0, "invalid clock has no output rate");
        eq(0, plan.panelScansPerOutput(), "invalid clock has no scan hold");
        check(!plan.generatesIntermediateFrames(), "invalid clock never generates");
    }

    private static void unqualified(double source, double panel) {
        UniformFrameRatePlan plan = UniformFrameRatePlan.select(source, panel);
        check(!plan.qualified(), source + " on " + panel + " must be unqualified");
        near(source, plan.sourceHz(), 0.0, "source clock remains unchanged");
        near(Math.min(source, panel), plan.outputHz(), 0.0, "honest Direct/panel fallback");
        eq(0, plan.panelScansPerOutput(), "fallback has no uniform scan claim");
        check(!plan.generatesIntermediateFrames(), "fallback never claims generation");
    }

    private static void plan(double panel, double source, double output, int divisor) {
        UniformFrameRatePlan plan = UniformFrameRatePlan.select(source, panel);
        check(plan.qualified(), source + " on " + panel + " must qualify");
        near(source, plan.sourceHz(), 0.0, "source clock remains unchanged");
        near(output, plan.outputHz(), 1.0e-9, source + " on " + panel + " output");
        eq(divisor, plan.panelScansPerOutput(), source + " on " + panel + " divisor");
        check(Math.abs(output - source) <= 1.0e-5 || Math.abs(output - 2.0 * source) <= 1.0e-5,
                "qualified output is Direct or doubling within timestamp quantization");
        near(panel, output * divisor, 1.0e-9, "output exactly divides physical panel");
        check(plan.generatesIntermediateFrames() == (output > source + 1.0e-5),
                "generated flag describes actual interpolation");
    }

    private static void eq(int expected, int actual, String message) {
        if (expected != actual)
            throw new AssertionError(message + ": expected=" + expected + " actual=" + actual);
    }

    private static void near(double expected, double actual, double epsilon, String message) {
        if (!Double.isFinite(actual) || Math.abs(expected - actual) > epsilon)
            throw new AssertionError(message + ": expected=" + expected + " actual=" + actual);
    }

    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
}
