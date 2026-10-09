package com.thorium.lucent.video;

public final class EndpointFrameSelectorTest {
    public static void main(String[] args) {
        sixtyCallbacksSelectEverySupportedTierExactly();
        longPauseNeverCatchesUp();
        tierChangeStartsOneFreshEndpoint();
        selectedTimestampsRemainTheImmutableCandidateTimes();
        oneMissedCallbackRemainsAnExplicitEndpointGap();
        nonMonotonicTimestampFailsClosed();
        System.out.println("EndpointFrameSelectorTest passed");
    }

    private static void sixtyCallbacksSelectEverySupportedTierExactly() {
        eq(120, selected(60, 60, 120), "60 of 60 callbacks");
        eq(100, selected(60, 50, 120), "50 of 60 callbacks");
        eq(80, selected(60, 40, 120), "40 of 60 callbacks");
        eq(60, selected(60, 30, 120), "30 of 60 callbacks");
        eq(40, selected(60, 20, 120), "20 of 60 callbacks");
    }

    private static int selected(int callbackFps, int sourceFps, int callbacks) {
        EndpointFrameSelector value = new EndpointFrameSelector();
        long now = 1_000_000_000L;
        long step = Math.round(1_000_000_000.0 / callbackFps);
        int selected = 0;
        for (int index = 0; index < callbacks; ++index) {
            if (value.select(now, sourceFps)) ++selected;
            now += step;
        }
        return selected;
    }

    private static void longPauseNeverCatchesUp() {
        EndpointFrameSelector value = new EndpointFrameSelector();
        check(value.select(1_000_000_000L, 60), "first endpoint");
        check(value.select(1_016_666_667L, 60), "second endpoint");
        check(value.select(2_000_000_000L, 60), "one endpoint after pause");
        check(value.select(2_016_666_667L, 60), "normal cadence resumes");
    }

    private static void tierChangeStartsOneFreshEndpoint() {
        EndpointFrameSelector value = new EndpointFrameSelector();
        check(value.select(3_000_000_000L, 60), "60 tier starts");
        check(value.select(3_016_666_667L, 50), "50 tier starts once");
        check(value.select(3_033_333_334L, 50),
                "nearest 50-Hz deadline may use an early callback");
        check(value.select(3_050_000_001L, 50),
                "second nearest 50-Hz deadline remains monotonic");
        check(!value.select(3_066_666_668L, 50),
                "50-Hz selector compensates without a catch-up burst");
    }

    private static void nonMonotonicTimestampFailsClosed() {
        EndpointFrameSelector value = new EndpointFrameSelector();
        check(value.select(4_000_000_000L, 60), "first monotonic endpoint");
        check(value.select(3_999_999_999L, 60),
                "clock reset starts exactly one new endpoint");
    }

    private static void selectedTimestampsRemainTheImmutableCandidateTimes() {
        EndpointFrameSelector value = new EndpointFrameSelector();
        long now = 5_000_000_000L;
        long callback = 16_666_667L;
        int selected = 0;
        for (int index = 0; index < 60; ++index) {
            long candidateTimestamp = now;
            if (value.select(now, 50)) {
                eqLong(candidateTimestamp, value.selectedTimestampNs(),
                        "selected endpoint keeps its producer timestamp");
                ++selected;
            }
            now += callback;
        }
        check(selected >= 49 && selected <= 51,
                "50-Hz endpoint selection count: " + selected);
    }

    private static void oneMissedCallbackRemainsAnExplicitEndpointGap() {
        EndpointFrameSelector value = new EndpointFrameSelector();
        long period = 16_666_667L;
        long[] callbacks = {
                6_000_000_000L,
                6_000_000_000L + period,
                // One delayed/missing handler callback. The selector may
                // retain the later candidate, but it must keep the 33.3-ms
                // timestamp gap so the renderer rejects interpolation across
                // it rather than relabelling it as one 16.7-ms interval.
                6_000_000_000L + period * 3L,
                6_000_000_000L + period * 4L,
                6_000_000_000L + period * 5L
        };
        long previous = 0L;
        boolean sawExplicitGap = false;
        for (long callback : callbacks) {
            check(value.select(callback, 60),
                    "one delayed callback still supplies one buffered slot");
            long selected = value.selectedTimestampNs();
            if (previous > 0L) {
                long delta = selected - previous;
                if (delta == period * 2L) sawExplicitGap = true;
                else eqLong(period, delta,
                        "ordinary candidates retain their exact spacing");
            }
            previous = selected;
        }
        check(sawExplicitGap,
                "missed callback remains visible in immutable timestamps");
        check(!AdaptiveFrameRateController.endpointSpanContinuous(
                        callbacks[1], callbacks[2], 60),
                "renderer continuity rejects the missed-callback interval");
    }

    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    private static void eq(int expected, int actual, String message) {
        if (expected != actual)
            throw new AssertionError(message + ": expected=" + expected +
                    " actual=" + actual);
    }


    private static void eqLong(long expected, long actual, String message) {
        if (expected != actual)
            throw new AssertionError(message + ": expected=" + expected +
                    " actual=" + actual);
    }
}
