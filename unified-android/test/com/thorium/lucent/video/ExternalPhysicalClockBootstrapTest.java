package com.thorium.lucent.video;

public final class ExternalPhysicalClockBootstrapTest {
    public static void main(String[] args) {
        calibrationContinuesUntilTheDriverReturnsTiming();
        anchoredClockCommitsWithAnEpochIsolatedTail();
        generatedCalibrationAndQueueMismatchFailClosed();
        System.out.println("ExternalPhysicalClockBootstrapTest passed");
    }

    private static void calibrationContinuesUntilTheDriverReturnsTiming() {
        ExternalPhysicalClockBootstrap bootstrap =
                new ExternalPhysicalClockBootstrap();
        check(bootstrap.calibrationRow(7L), "startup row is calibration");
        bootstrap.recordCalibrationPresent(false, 7L);
        check(bootstrap.calibrationPresents() == 1L,
                "physical calibration present counted exactly");
        check(!bootstrap.ready(false, 0, 0),
                "no actual clock cannot commit the boundary");
    }

    private static void anchoredClockCommitsWithAnEpochIsolatedTail() {
        ExternalPhysicalClockBootstrap bootstrap =
                new ExternalPhysicalClockBootstrap();
        bootstrap.recordCalibrationPresent(false, 11L);
        check(bootstrap.ready(true, 1, 1),
                "first actual row establishes a boundary despite old tail");
        bootstrap.commit(true, 1, 1);
        check(bootstrap.complete(), "bootstrap commits once into aligned mode");
        check(bootstrap.calibrationRow(11L),
                "late old-epoch row remains calibration-only");
        check(!bootstrap.calibrationRow(12L),
                "fresh epoch row is eligible for aligned evidence");
        bootstrap.recordCalibrationPresent(false, 11L);
        check(bootstrap.calibrationPresents() == 2L,
                "late old-epoch calibration is accounted exactly");
        expectFailure(() -> bootstrap.recordCalibrationPresent(false, 12L));
        expectFailure(() -> bootstrap.commit(true, 0, 0));
    }

    private static void generatedCalibrationAndQueueMismatchFailClosed() {
        ExternalPhysicalClockBootstrap bootstrap =
                new ExternalPhysicalClockBootstrap();
        expectFailure(() -> bootstrap.recordCalibrationPresent(true, 1L));
        expectFailure(() -> bootstrap.recordCalibrationPresent(false, 0L));
        expectFailure(() -> bootstrap.calibrationRow(0L));
        expectFailure(() -> bootstrap.ready(true, -1, -1));
        expectFailure(() -> bootstrap.ready(true, 1, 0));
        expectFailure(() -> bootstrap.commit(true, 0, 0));
    }

    private static void expectFailure(Runnable action) {
        try {
            action.run();
            throw new AssertionError("expected failure");
        } catch (RuntimeException expected) {
            // expected
        }
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
