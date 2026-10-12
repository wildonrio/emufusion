package com.thorium.emufusion.video;

import java.nio.ByteBuffer;

public final class GeneratedFrameVerdictTest {
    private static final int W = 64;

    public static void main(String[] args) {
        // A bar moving 8 cells right between A and B, rendered three ways.
        check(classify(frame(4)) == GeneratedFrameVerdict.GENERATED, "a true midpoint is generated");
        check(classify(frame(0)) == GeneratedFrameVerdict.DUPLICATE, "a copy of A is a duplicate");
        check(classify(frame(8)) == GeneratedFrameVerdict.DUPLICATE, "a copy of B is a duplicate");
        check(classify(crossFade()) == GeneratedFrameVerdict.BLEND, "a cross-fade is not generated");
        check(classify(bar(0), bar(0), bar(0)) == GeneratedFrameVerdict.STATIC,
                "no motion is no evidence");
        check(classify(frame(3)) == GeneratedFrameVerdict.GENERATED, "a one-third phase is generated");
        // A fade at phase 0.375 matches neither image nor the 50/50 blend, so it
        // passed as generated until the blend was taken at the frame's phase.
        check(classify(crossFade(0.375f), 0.5f) == GeneratedFrameVerdict.GENERATED,
                "the midpoint-only comparison missed off-centre fades");
        check(classify(crossFade(0.375f), 0.375f) == GeneratedFrameVerdict.BLEND,
                "an off-centre cross-fade is not generated");
        check(classify(frame(3), 0.375f) == GeneratedFrameVerdict.GENERATED,
                "an off-centre true frame is generated");
        System.out.println("GeneratedFrameVerdictTest passed");
    }

    private static int classify(float[][] g) { return classify(g, 0.5f); }

    private static int classify(float[][] g, float phase) { return classify(g, bar(0), bar(8), phase); }

    private static int classify(float[][] g, float[][] a, float[][] b) { return classify(g, a, b, 0.5f); }

    private static int classify(float[][] g, float[][] a, float[][] b, float phase) {
        ByteBuffer cells = ByteBuffer.allocate(W * W * 4);
        for (int y = 0; y < W; ++y)
            for (int x = 0; x < W; ++x) {
                float ga = Math.abs(g[y][x] - a[y][x]), gb = Math.abs(g[y][x] - b[y][x]);
                float gm = Math.abs(g[y][x] - ((1f - phase) * a[y][x] + phase * b[y][x]));
                float ab = Math.abs(a[y][x] - b[y][x]);
                cells.put(q(ga)).put(q(gb)).put(q(gm)).put(q(ab));
            }
        cells.flip();
        return GeneratedFrameVerdict.classify(cells, W * W, 31, 12, 48);
    }

    private static byte q(float v) { return (byte) Math.round(Math.min(1f, 4f * v) * 255f); }

    /** A bright 16-cell-wide bar on a dark background, offset by {@code shift}. */
    private static float[][] bar(int shift) {
        float[][] f = new float[W][W];
        for (int y = 0; y < W; ++y)
            for (int x = 0; x < W; ++x) f[y][x] = (x >= 20 + shift && x < 36 + shift) ? 0.8f : 0.1f;
        return f;
    }

    private static float[][] frame(int shift) { return bar(shift); }

    private static float[][] crossFade() { return crossFade(0.5f); }

    private static float[][] crossFade(float phase) {
        float[][] a = bar(0), b = bar(8), f = new float[W][W];
        for (int y = 0; y < W; ++y)
            for (int x = 0; x < W; ++x) f[y][x] = (1f - phase) * a[y][x] + phase * b[y][x];
        return f;
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
