package com.thorium.preview.game;

public final class DenseGpuTimerMathTest {
    public static void main(String[] args) {
        expect(0L, DenseGpuTimer.nanosecondsToMicroseconds(0L));
        expect(1L, DenseGpuTimer.nanosecondsToMicroseconds(1L));
        expect(1L, DenseGpuTimer.nanosecondsToMicroseconds(999L));
        expect(1L, DenseGpuTimer.nanosecondsToMicroseconds(1000L));
        expect(2L, DenseGpuTimer.nanosecondsToMicroseconds(1001L));
        expect(4_294_968L,
                DenseGpuTimer.nanosecondsToMicroseconds(4_294_967_297L));
        System.out.println("DenseGpuTimerMathTest passed");
    }

    private static void expect(long expected, long actual) {
        if (expected != actual)
            throw new AssertionError("expected=" + expected + " actual=" + actual);
    }
}
