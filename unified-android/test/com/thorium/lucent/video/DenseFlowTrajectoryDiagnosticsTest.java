package com.thorium.lucent.video;

public final class DenseFlowTrajectoryDiagnosticsTest {
    public static void main(String[] args) {
        separatesConfidenceFromChangedMotionOwnership();
        rejectsMalformedPayloads();
    }

    private static void separatesConfidenceFromChangedMotionOwnership() {
        byte[] previous = rgba(4);
        byte[] current = rgba(4);
        byte[] backward = flow(4);
        byte[] forward = flow(4);

        setRgb(current, 1, 20, 20, 20); // changed, but both flows remain zero
        setFlow(backward, 1, 128, 128, 64);
        setFlow(forward, 1, 128, 128, 64);

        setRgb(current, 2, 40, 0, 0); // moving in backward only
        setFlow(backward, 2, 134, 128, 64);
        setFlow(forward, 2, 140, 128, 20); // invalid confidence

        setRgb(current, 3, 0, 40, 0); // strong moving support in both
        setFlow(backward, 3, 140, 128, 64);
        setFlow(forward, 3, 116, 128, 64);

        // Unchanged but moving-valid flow is diagnosed separately.
        setFlow(backward, 0, 132, 128, 64);

        DenseFlowTrajectoryDiagnostics.Sample sample =
                DenseFlowTrajectoryDiagnostics.analyze(previous, current,
                        backward, forward, 4, 1);
        equal(4, sample.cells, "cells");
        equal(3, sample.changedCells, "changed");
        equal(3, sample.changedAnyValidCells, "changed any valid");
        equal(2, sample.changedAnyMovingValidCells, "changed motion owned");
        equal(1, sample.changedBothMovingValidCells, "both directions moving");
        equal(3, sample.changedTiles, "changed tiles");
        equal(2, sample.changedMovingOwnedTiles, "owned tiles");
        equal(4, sample.validCells[0], "backward valid");
        equal(2, sample.validCells[1], "forward valid");
        equal(3, sample.movingValidCells[0], "backward moving");
        equal(1, sample.movingValidCells[1], "forward moving");
        equal(1, sample.strongMovingValidCells[0], "backward strong");
        equal(1, sample.strongMovingValidCells[1], "forward strong");
        equal(2, sample.changedMovingValidCells[0], "backward changed moving");
        equal(1, sample.changedMovingValidCells[1], "forward changed moving");
        equal(1, sample.unchangedMovingValidCells[0], "backward false ownership");
    }

    private static void rejectsMalformedPayloads() {
        boolean rejected = false;
        try {
            DenseFlowTrajectoryDiagnostics.analyze(new byte[4], new byte[4],
                    new byte[4], new byte[3], 1, 1);
        } catch (IllegalArgumentException expected) {
            rejected = true;
        }
        check(rejected, "mismatched field rejected");
    }

    private static byte[] rgba(int pixels) { return new byte[pixels * 4]; }

    private static byte[] flow(int pixels) {
        byte[] result = new byte[pixels * 4];
        for (int pixel = 0; pixel < pixels; ++pixel) {
            result[pixel * 4] = (byte) 128;
            result[pixel * 4 + 1] = (byte) 128;
        }
        return result;
    }

    private static void setRgb(byte[] pixels, int pixel, int r, int g, int b) {
        int offset = pixel * 4;
        pixels[offset] = (byte) r;
        pixels[offset + 1] = (byte) g;
        pixels[offset + 2] = (byte) b;
    }

    private static void setFlow(byte[] field, int pixel, int r, int g, int b) {
        int offset = pixel * 4;
        field[offset] = (byte) r;
        field[offset + 1] = (byte) g;
        field[offset + 2] = (byte) b;
    }

    private static void equal(long expected, long actual, String message) {
        if (expected != actual)
            throw new AssertionError(message + " expected=" + expected +
                    " actual=" + actual);
    }

    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
}
