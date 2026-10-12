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
        System.out.println("GeneratedFrameVerdictTest passed");
    }

    private static int classify(float[][] g) { return classify(g, bar(0), bar(8)); }

    private static int classify(float[][] g, float[][] a, float[][] b) {
        ByteBuffer cells = ByteBuffer.allocate(W * W * 4);
        for (int y = 0; y < W; ++y)
            for (int x = 0; x < W; ++x) {
                float ga = Math.abs(g[y][x] - a[y][x]), gb = Math.abs(g[y][x] - b[y][x]);
                float gm = Math.abs(g[y][x] - 0.5f * (a[y][x] + b[y][x]));
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

    private static float[][] crossFade() {
        float[][] a = bar(0), b = bar(8), f = new float[W][W];
        for (int y = 0; y < W; ++y)
            for (int x = 0; x < W; ++x) f[y][x] = 0.5f * (a[y][x] + b[y][x]);
        return f;
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
