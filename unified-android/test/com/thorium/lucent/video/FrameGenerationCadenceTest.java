package com.thorium.lucent.video;

public final class FrameGenerationCadenceTest {
    public static void main(String[] args) {
        sixtyToOneTwentyGeneratesOneIntermediate();
        thirtyToOneTwentyGeneratesThreeIntermediates();
        matchedRefreshBypassesGeneration();
        invalidRefreshFallsBackSafely();
        outlierDoesNotCorruptCadence();
        presentationTimestampTargetsOneFutureScan();
        cadenceFailureRequiresConsecutiveWindows();
        generationCannotUndercutDirectSourceCadence();
        generatedModeMustSustainItsAdvertisedTarget();
        System.out.println("FrameGenerationCadenceTest passed");
    }

    private static void sixtyToOneTwentyGeneratesOneIntermediate() {
        FrameGenerationCadence cadence = new FrameGenerationCadence(120.0);
        cadence.onSourceFrame(1_000_000_000L);
        cadence.onSourceFrame(1_016_666_667L);
        check(cadence.generatesIntermediateFrames(), "60 to 120 must generate");
        near(0.5f, cadence.interpolation(1_025_000_000L), 0.02f,
                "halfway panel refresh");
        near(1f, cadence.interpolation(1_033_333_334L), 0.001f,
                "source endpoint");
    }

    private static void thirtyToOneTwentyGeneratesThreeIntermediates() {
        FrameGenerationCadence cadence = new FrameGenerationCadence(120.0);
        cadence.onSourceFrame(2_000_000_000L);
        cadence.onSourceFrame(2_033_333_333L);
        near(0.25f, cadence.interpolation(2_041_666_666L), 0.02f, "quarter");
        near(0.5f, cadence.interpolation(2_050_000_000L), 0.02f, "half");
        near(0.75f, cadence.interpolation(2_058_333_333L), 0.02f, "three quarters");
    }

    private static void matchedRefreshBypassesGeneration() {
        FrameGenerationCadence cadence = new FrameGenerationCadence(60.0);
        cadence.onSourceFrame(3_000_000_000L);
        cadence.onSourceFrame(3_016_666_667L);
        check(!cadence.generatesIntermediateFrames(), "matched cadence must bypass");
        near(1f, cadence.interpolation(3_020_000_000L), 0f, "current frame direct");
    }

    private static void invalidRefreshFallsBackSafely() {
        FrameGenerationCadence cadence = new FrameGenerationCadence(Double.NaN);
        near(60f, (float) cadence.displayRefreshHz(), 0.01f, "safe fallback");
    }

    private static void outlierDoesNotCorruptCadence() {
        FrameGenerationCadence cadence = new FrameGenerationCadence(120.0);
        cadence.onSourceFrame(4_000_000_000L);
        cadence.onSourceFrame(4_016_666_667L);
        double before = cadence.estimatedSourceHz();
        cadence.onSourceFrame(5_000_000_000L);
        near((float) before, (float) cadence.estimatedSourceHz(), 0.01f,
                "long pause is not source cadence");
    }

    private static void presentationTimestampTargetsOneFutureScan() {
        long period = 8_333_333L;
        long callback = 10_000_000_000L;
        eq(callback + period, FrameGenerationCadence.nextPresentationTimeNs(
                callback, period, callback + 2_000_000L),
                "on-time render targets the following scan");
        eq(callback + period * 2L,
                FrameGenerationCadence.nextPresentationTimeNs(
                        callback, period, callback + period + 1L),
                "late render skips to the first future scan");
        eq(0L, FrameGenerationCadence.nextPresentationTimeNs(
                0L, period, callback), "invalid callback fails closed");
    }

    private static void cadenceFailureRequiresConsecutiveWindows() {
        int failures = 0;
        failures = FrameGenerationCadence.advanceCadenceFailureWindows(
                failures, true, true);
        eq(1L, failures, "first bad window is an outlier");
        failures = FrameGenerationCadence.advanceCadenceFailureWindows(
                failures, true, true);
        eq(2L, failures, "second bad window remains recoverable");
        failures = FrameGenerationCadence.advanceCadenceFailureWindows(
                failures, true, false);
        eq(0L, failures, "one healthy window clears the streak");
        failures = FrameGenerationCadence.advanceCadenceFailureWindows(
                2, false, true);
        eq(0L, failures, "source-ineligible window cannot blame renderer");
    }

    private static void generationCannotUndercutDirectSourceCadence() {
        check(FrameGenerationCadence.generationFallsBelowSourceFloor(
                        2_326L, 126L, 60, 120),
                "physical 54-Hz generated output fails below direct60 floor");
        check(!FrameGenerationCadence.generationFallsBelowSourceFloor(
                        1_050L, 120L, 60, 120),
                "healthy generated output stays enabled");
        check(!FrameGenerationCadence.generationFallsBelowSourceFloor(
                        2_100L, 120L, 60, 60),
                "direct presentation is not recursively rejected");
        check(!FrameGenerationCadence.generationFallsBelowSourceFloor(
                        400L, 20L, 60, 120),
                "startup fragment cannot reject generation");
    }

    private static void generatedModeMustSustainItsAdvertisedTarget() {
        check(FrameGenerationCadence.generationMissesTargetCadence(
                        2_800L, 126L, 30, 60),
                "physical 30-to-45 outcome must reject the claimed 60 target");
        check(FrameGenerationCadence.generationMissesTargetCadence(
                        2_326L, 126L, 60, 120),
                "physical 60-to-54 outcome must reject the claimed 120 target");
        check(!FrameGenerationCadence.generationMissesTargetCadence(
                        1_040L, 120L, 60, 120),
                "a healthy generated target remains enabled");
        check(!FrameGenerationCadence.generationMissesTargetCadence(
                        1_000L, 60L, 60, 60),
                "direct presentation is outside generated-target rejection");
    }

    private static void eq(long expected, long actual, String message) {
        if (expected != actual)
            throw new AssertionError(message + ": expected=" + expected +
                    " actual=" + actual);
    }

    private static void near(float expected, float actual, float epsilon, String message) {
        if (Math.abs(expected - actual) > epsilon)
            throw new AssertionError(message + ": expected=" + expected + " actual=" + actual);
    }

    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
}
