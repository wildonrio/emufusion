package com.thorium.lucent.video;

/** Real source timestamp proof after a small physical-clock correction. */
public final class PhysicalClockSourceIntegrationTest {
    public static void main(String[] args) {
        transitionWindowMustNotLatchForever();
        for (double panel : new double[] {119.945005, 120.006, 120.052}) {
            AdaptiveFrameRateController rate = new AdaptiveFrameRateController(120);
            long now = 1_000_000_000L;
            for (int i = 0; i < 1200; ++i) {
                rate.onProducerFrame(now);
                now += 16_666_667L;
            }
            rate.setPhysicalDisplayRefreshHz(panel);
            long correctedPeriod = Math.round(2e9 / panel);
            for (int i = 0; i < 2400; ++i) {
                rate.onProducerFrame(now);
                now += correctedPeriod;
            }
            double actualSource = 1e9 / correctedPeriod;
            if (Math.abs(rate.presentationSourceHz() - actualSource) > 1e-5 ||
                    !rate.generatesIntermediateFrames())
                throw new AssertionError("panel=" + panel + " source=" + rate.presentationSourceHz() +
                        " expected=" + actualSource + " output=" + rate.targetOutputHz());
        }
        System.out.println("PhysicalClockSourceIntegrationTest passed");
    }

    private static void transitionWindowMustNotLatchForever() {
        double panel = 119.972749;
        AdaptiveFrameRateController rate = new AdaptiveFrameRateController(120);
        rate.setPhysicalDisplayRefreshHz(panel);
        long now = 1_000_000_000L;
        long period = Math.round(2e9 / panel);
        for (int i = 0; i < 3600; ++i) {
            rate.onProducerFrame(now);
            // First qualification sees the old clock before correction settles.
            // Deterministic transition model, not an invented device trace.
            now += i < 660 ? Math.round(1e9 / 59.975) : period;
        }
        if (Math.abs(rate.presentationSourceHz() - 1e9 / period) > 1e-5 ||
                !rate.generatesIntermediateFrames())
            throw new AssertionError("transition retained source=" + rate.presentationSourceHz() +
                    " actual=" + 1e9 / period + " output=" + rate.targetOutputHz());
    }
}
