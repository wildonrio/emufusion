package com.thorium.lucent.video;

import java.util.HashMap;
import java.util.Map;

/** Covers remembered panel rates ({@link PanelClockMemory}) and the clock seed. */
public final class PanelClockMemoryTest {
    public static void main(String[] args) {
        rememberedPerModeAndBounded();
        durableStoreRoundTrips();
        seedNeedsLiveAgreement();
        System.out.println("PanelClockMemoryTest passed");
    }

    private static void rememberedPerModeAndBounded() {
        PanelClockMemory.clearForTest();
        PanelClockMemory.remember(0, 120.00001, 119.929292);
        check(Math.abs(PanelClockMemory.lookup(0, 120.00001) - 119.929292) < 1e-9, "mode remembered");
        check(PanelClockMemory.lookup(0, 60.000004) == 0.0, "other modes are separate");
        check(PanelClockMemory.lookup(1, 120.00001) == 0.0, "other displays are separate");
        PanelClockMemory.remember(0, 60.000004, 75.0);
        check(PanelClockMemory.lookup(0, 60.000004) == 0.0, "implausible rates are refused");
    }

    private static void durableStoreRoundTrips() {
        PanelClockMemory.clearForTest();
        Map<String, Double> disk = new HashMap<>();
        PanelClockMemory.Store store = new PanelClockMemory.Store() {
            @Override public double get(String key) { return disk.getOrDefault(key, 0.0); }
            @Override public void put(String key, double hz) { disk.put(key, hz); }
        };
        PanelClockMemory.setStore(store);
        PanelClockMemory.remember(0, 144.0, 143.98);
        PanelClockMemory.clearForTest();       // a new process
        PanelClockMemory.setStore(store);
        check(Math.abs(PanelClockMemory.lookup(0, 144.0) - 143.98) < 1e-9, "survives a restart");
    }

    private static void seedNeedsLiveAgreement() {
        long period = Math.round(1e9 / 119.929292);
        PhysicalPresentationClock clock = new PhysicalPresentationClock();
        clock.seedFrequencyHz(119.929292);
        long t = 1_000_000_000L;
        for (int i = 0; i < 360; ++i) { clock.record(t, period); t += period; }  // 3 s
        double early = clock.sustainedFrequencyHz(t - period);
        check(Math.abs(early - 119.929292) < 1e-6,
                "a confirmed seed stands in before the 20 s baseline: " + early);
        check(!clock.hasSustainedBaseline(), "no own baseline yet");
        PhysicalPresentationClock wrong = new PhysicalPresentationClock();
        wrong.seedFrequencyHz(119.5);
        t = 1_000_000_000L;
        for (int i = 0; i < 360; ++i) { wrong.record(t, period); t += period; }
        check(wrong.sustainedFrequencyHz(t - period) == 0.0, "a seed live presents disagree with is ignored");
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
