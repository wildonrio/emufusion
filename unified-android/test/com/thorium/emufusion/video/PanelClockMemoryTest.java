package com.thorium.emufusion.video;

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
        // Without a usable seed, 8 s of steady presents stand in (Thor sessions
        // measured 119.76-119.93 Hz; a stale seed meant 20 s on the nominal clock).
        for (int i = 0; i < 640; ++i) { wrong.record(t, period); t += period; }   // 8.3 s in all
        double provisional = wrong.sustainedFrequencyHz(t - period);
        check(Math.abs(provisional - 1e9 / period) < 1e-6, "8 s of live presents stand in: " + provisional);
        check(!wrong.hasSustainedBaseline(), "a provisional rate is not a baseline (never remembered)");
        // Halves that disagree (the oscillator moved, or noisy feedback) are not a rate.
        PhysicalPresentationClock moving = new PhysicalPresentationClock();
        t = 1_000_000_000L;
        long nominal = Math.round(1e9 / 120.0);
        for (int i = 0; i < 480; ++i) { moving.record(t, nominal); t += 8_337_000L; }
        for (int i = 0; i < 520; ++i) { moving.record(t, nominal); t += 8_331_000L; }
        check(moving.sustainedFrequencyHz(t - 8_331_000L) == 0.0, "a drifting window is not a provisional rate");
        // The panel settles after waking (Thor: 119.83 -> 119.90 Hz over ~6 s):
        // a good seed is confirmed on the recent span, not refused for the start.
        PhysicalPresentationClock settling = new PhysicalPresentationClock();
        settling.seedFrequencyHz(119.91);
        t = 1_000_000_000L;
        long slow = Math.round(1e9 / 119.80), steady = Math.round(1e9 / 119.90);
        for (int i = 0; i < 480; ++i) { settling.record(t, nominal); t += slow; }    // 4 s settling
        for (int i = 0; i < 300; ++i) { settling.record(t, nominal); t += steady; }  // 2.5 s steady
        double confirmed = settling.sustainedFrequencyHz(t - steady);
        check(Math.abs(confirmed - 119.91) < 1e-9, "a seed agreeing with the recent span stands in: " + confirmed);
        // Without a seed, the recent 8 s stand in once they are steady.
        PhysicalPresentationClock fresh = new PhysicalPresentationClock();
        t = 1_000_000_000L;
        for (int i = 0; i < 480; ++i) { fresh.record(t, nominal); t += slow; }
        for (int i = 0; i < 1000; ++i) { fresh.record(t, nominal); t += steady; }    // 8.3 s steady
        double recent = fresh.sustainedFrequencyHz(t - steady);
        check(Math.abs(recent - 1e9 / steady) < 0.002, "the recent steady span stands in: " + recent);
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
