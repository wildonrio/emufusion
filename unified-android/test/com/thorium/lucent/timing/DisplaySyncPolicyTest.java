package com.thorium.lucent.timing;

import com.thorium.lucent.TestSupport;

public final class DisplaySyncPolicyTest {
    public static void main(String[] args) {
        nearStandardConsoleClocksBecomeExactDivisors();
        everyCanonicalRateSelectsAnExactPanelMultiple();
        strictDirectModeUsesTheSmallestExactNativePanelRate();
        tenMinuteScanLatticesHaveOneAndOnlyOneHoldLength();
        automaticClockCorrectionsRemainSubPercent();
        loadTiersCannotChangeGameplaySpeed();
        correctionBoundIsRelativeToTheOriginalClock();
        genuinePalClockIsNeverSilentlySpedUp();
        invalidRatesRemainInvalid();
        physicalDivisorRespectsOriginalClock();
    }

    private static void physicalDivisorRespectsOriginalClock() {
        double panel = 119.945005;
        if (DisplaySyncPolicy.physicalSourceHz(60.0, panel) != panel / 2.0 ||
                DisplaySyncPolicy.physicalSourceHz(59.7275, panel) != panel / 2.0 ||
                DisplaySyncPolicy.physicalSourceHz(30.0, panel) != panel / 4.0 ||
                DisplaySyncPolicy.physicalSourceHz(60.0, 80.0) != 0.0 ||
                DisplaySyncPolicy.physicalSourceHz(50.0, panel) != 0.0 ||
                DisplaySyncPolicy.physicalSourceHz(60.0, Double.NaN) != 0.0)
            throw new AssertionError("physical clock correction budget/divisor");
    }

    private static void tenMinuteScanLatticesHaveOneAndOnlyOneHoldLength() {
        double[] declaredRates = {
                60.0988, 59.7275, 59.8261, 59.9227,
                40.0, 29.97, 24.0, 23.976, 20.03, 15.0, 12.0, 10.0
        };
        final int seconds = 10 * 60;
        for (double declared : declaredRates) {
            double source = DisplaySyncPolicy.synchronizedSourceHz(declared);
            float panel = DisplaySyncPolicy.panelRefreshHz(source);
            double ratio = panel / source;
            long scansPerFrame = Math.round(ratio);
            TestSupport.truth(Math.abs(ratio - scansPerFrame) < 1.0e-9,
                    declared + " Hz did not produce an integer scan hold");
            long frames = Math.round(source * seconds);
            long priorScan = 0L;
            for (long frame = 1L; frame <= frames; frame++) {
                long scan = frame * scansPerFrame;
                TestSupport.equal(scansPerFrame, scan - priorScan,
                        declared + " Hz acquired a long/short hold at frame " + frame);
                priorScan = scan;
            }
            TestSupport.equal(Math.round((double) panel * seconds), priorScan,
                    declared + " Hz drifted over the ten-minute scan proof");
        }
    }

    private static void automaticClockCorrectionsRemainSubPercent() {
        double[][] clocks = {
                {60.0988, 60.0}, {59.7275, 60.0}, {59.8261, 60.0},
                {59.9227, 60.0}, {29.97, 30.0}, {23.976, 24.0},
                {20.03, 20.0}
        };
        for (double[] clock : clocks) {
            double synchronizedHz = DisplaySyncPolicy.synchronizedSourceHz(clock[0]);
            TestSupport.equal(clock[1], synchronizedHz,
                    clock[0] + " Hz selected the wrong standard clock");
            double correction = Math.abs(synchronizedHz - clock[0]) / clock[0];
            TestSupport.truth(correction <= 0.0075,
                    clock[0] + " Hz exceeded the automatic correction safety bound");
        }
    }

    private static void loadTiersCannotChangeGameplaySpeed() {
        for (double requested : new double[] {20, 30, 40, 50, 59, 61, 120,
                -1, 0, 1, Double.NaN, Double.POSITIVE_INFINITY}) {
            TestSupport.truth(!DisplaySyncPolicy.permitsCoreClockCorrection(60, requested),
                    "60 Hz guest must reject load tier or invalid clock " + requested);
        }
        for (double declared : new double[] {60.0988, 59.7275, 59.8261, 59.9227, 59.94})
            TestSupport.truth(DisplaySyncPolicy.permitsCoreClockCorrection(declared, 60),
                    "near-native correction rejected for " + declared);
        TestSupport.truth(!DisplaySyncPolicy.permitsCoreClockCorrection(0, 60),
                "unknown native adapter clock cannot authorize a correction");
        TestSupport.truth(!DisplaySyncPolicy.permitsCoreClockCorrection(Double.NaN, 60),
                "invalid native clock cannot authorize a correction");
        // A native 20 FPS title may still run a 60 Hz simulation: content FPS
        // is not permission to run one third as many simulation ticks.
        TestSupport.truth(!DisplaySyncPolicy.permitsCoreClockCorrection(60, 20),
                "content frame rate must not replace the simulation clock");
    }

    private static void correctionBoundIsRelativeToTheOriginalClock() {
        double bound = DisplaySyncPolicy.MAX_RELATIVE_CORRECTION;
        for (double declared : new double[] {20, 29.97, 40, 59.7275, 60, 120}) {
            for (double sign : new double[] {-1, 1}) {
                TestSupport.truth(DisplaySyncPolicy.permitsCoreClockCorrection(
                                declared, declared * (1 + sign * bound)),
                        "inclusive safety boundary rejected");
                TestSupport.truth(!DisplaySyncPolicy.permitsCoreClockCorrection(
                                declared, declared * (1 + sign * (bound + 0.00001))),
                        "correction beyond the original clock boundary accepted");
            }
        }
        // Measuring against the destination instead of the original clock
        // previously admitted an actual >0.75% speedup at this edge.
        double declared = 60 * (1 - bound);
        TestSupport.equal(declared, DisplaySyncPolicy.synchronizedSourceHz(declared),
                "nominal selection must respect actual gameplay speed ratio");
        TestSupport.truth(!DisplaySyncPolicy.permitsCoreClockCorrection(60, 60.8),
                "multiple individually small trims cannot accumulate against a moving baseline");
    }

    private static void everyCanonicalRateSelectsAnExactPanelMultiple() {
        assertPanel(20.0, 120.0f);
        assertPanel(24.0, 120.0f);
        assertPanel(30.0, 120.0f);
        assertPanel(40.0, 120.0f);
        assertPanel(60.0, 120.0f);
        assertPanel(120.0, 120.0f);
    }

    private static void assertPanel(double sourceHz, float expectedPanelHz) {
        TestSupport.truth(Float.compare(expectedPanelHz,
                        DisplaySyncPolicy.panelRefreshHz(sourceHz)) == 0,
                sourceHz + " Hz must select the exact " + expectedPanelHz + " Hz mode");
        TestSupport.truth(DisplaySyncPolicy.isUniformOnThor(sourceHz),
                sourceHz + " Hz must be uniform on Thor");
    }

    private static void strictDirectModeUsesTheSmallestExactNativePanelRate() {
        double[] nativeSixty = {60.0988, 59.7275, 30.0, 29.97, 20.03, 15.0, 12.0, 10.0};
        for (double source : nativeSixty)
            TestSupport.truth(Float.compare(60.0f,
                            DisplaySyncPolicy.directPanelRefreshHz(source)) == 0,
                    source + " Hz must use the native 60 Hz direct mode");
        double[] nativeOneTwenty = {120.0, 40.0, 24.0, 23.976, 50.0, 0.0};
        for (double source : nativeOneTwenty)
            TestSupport.truth(Float.compare(120.0f,
                            DisplaySyncPolicy.directPanelRefreshHz(source)) == 0,
                    source + " Hz must retain the native 120 Hz direct mode");
    }

    private static void nearStandardConsoleClocksBecomeExactDivisors() {
        TestSupport.equal(60.0, DisplaySyncPolicy.synchronizedSourceHz(60.0988),
                "SNES clock must synchronize to 60");
        TestSupport.equal(60.0, DisplaySyncPolicy.synchronizedSourceHz(59.7275),
                "GB/GBA clock must synchronize to 60");
        TestSupport.equal(60.0, DisplaySyncPolicy.synchronizedSourceHz(59.9227),
                "Genesis clock must synchronize to 60");
        TestSupport.equal(60.0, DisplaySyncPolicy.synchronizedSourceHz(59.8261),
                "handheld NTSC-family clock must synchronize to 60");
        TestSupport.equal(30.0, DisplaySyncPolicy.synchronizedSourceHz(29.97),
                "30 Hz content must synchronize to 30");
        TestSupport.equal(24.0, DisplaySyncPolicy.synchronizedSourceHz(23.976),
                "film-rate content must synchronize to 24");
        TestSupport.equal(20.0, DisplaySyncPolicy.synchronizedSourceHz(20.03),
                "20 Hz content must synchronize to 20");
        TestSupport.truth(DisplaySyncPolicy.isUniformOnThor(59.7275),
                "canonical GBA cadence must divide the panel");
    }

    private static void genuinePalClockIsNeverSilentlySpedUp() {
        TestSupport.equal(50.0, DisplaySyncPolicy.synchronizedSourceHz(50.0),
                "50 Hz must remain authentic without a proved converter");
        TestSupport.truth(!DisplaySyncPolicy.isUniformOnThor(50.0),
                "50 Hz cannot be called uniform on a 60/120-only panel");
    }

    private static void invalidRatesRemainInvalid() {
        TestSupport.equal(0.0, DisplaySyncPolicy.synchronizedSourceHz(0.0),
                "zero must remain invalid");
        TestSupport.truth(Float.compare(120.0f,
                        DisplaySyncPolicy.panelRefreshHz(59.7275)) == 0,
                "sub-60 console clock preserves the native 120 Hz panel mode");
        TestSupport.truth(Float.compare(120.0f,
                        DisplaySyncPolicy.panelRefreshHz(119.88)) == 0,
                "120 Hz content uses the 120 Hz panel mode");
    }
}
