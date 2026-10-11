package com.thorium.lucent.video;

import java.util.ArrayDeque;
import java.util.Map;
import java.util.TreeMap;

/**
 * Direct-equal fallback, AUTO's lock-to-30 tier policy and physical-lattice
 * held-frame qualification (2026-10-11).
 *
 * <p>The presentation simulator mirrors DisplayFrameGenerator's buffered
 * owner: classified endpoint admission (including held-frame retention and
 * the AUTO locked-tick gate), the endpoint FIFO and active pair, epoch
 * synchronization, and commit-then-advance. Gaps are measured in physical
 * panel scans between committed presentations, exactly as the Thor cadence
 * ledger reports them.</p>
 */
public final class FrameGenerationAutoPolicyTest {
    private static final double THOR_PANEL_HZ = 119.95;
    private static final double PACED_HZ = THOR_PANEL_HZ / 2.0;

    public static void main(String[] args) {
        unqualifiedHeldSourcePresentsOnlyOnProducerLattice();
        unqualifiedHeldSourceWithLateArrivalsStaysOnLattice();
        disabledGenerationHeldSourcePresentsOnlyOnProducerLattice();
        directLatticeRetainsHeldFramesLikeFgOff();
        directTargetIsPacedClockNotMeasuredMean();
        directLatticeNeedsAPacedProducerTimeline();
        lockToThirtySettlesFiftyEightPointFiveAtThirtyToSixty();
        adaptivePolicyKeepsFortyTierAndDirect();
        lockToThirtyKeepsStableSixtyAtSixtyTo120();
        lockToThirtyLocksTwentyFiveUniqueAtTwentyToForty();
        lockToThirtyClimbsBackOnlyWithSustainedSixty();
        lockToThirtyDemotesAnUnfundedHeldSixty();
        autoWithoutGenerationIsDirectEqualNotLocked();
        lockGateAdmitsOneTickPerLockedPeriod();
        tierPolicyChangeRebucketsForty();
        physicalHeldFramesQualifyPanelLatticeForSixtyTo120();
        unpacedHeldFramesNeverClaimPanelLattice();
        excessiveHeldFramesStayUnqualifiedAndLockUnderAuto();
        lockedThirtyUpgradesWhenHeldLatticeIsProven();
        System.out.println("FrameGenerationAutoPolicyTest passed");
    }

    // ------------------------------------------------------------------
    // Task 1: Direct-equal fallback.

    private static void unqualifiedHeldSourcePresentsOnlyOnProducerLattice() {
        // GameCube on the Thor: paced 59.975 stamps, ~2.5 percent held frames
        // (58.5 unique), generation available but the source unqualified.
        // Held frames are dropped here (no duplicate retention) so the
        // controller alone must keep every gap on the two-scan lattice.
        Sim sim = Sim.thor(heldPattern(2400, 41, 25), true);
        sim.retainHeldFrames = false;
        sim.run(20.0);
        check(!sim.value.generatesIntermediateFrames(),
                "held 58.5 source is not generation-qualified within 20 s");
        check(sim.value.directLatticeActive(), "Direct-equal lattice active");
        assertOnlyLatticeGaps(sim, "unqualified held source");
        check(sim.gapCount(4) > 0, "held frames show as doubled 4-scan holds");
        // Every non-held producer frame is still shown.
        check(sim.real >= sim.uniqueDelivered - 3,
                "every unique image presented: real=" + sim.real +
                        " unique=" + sim.uniqueDelivered);
        eq(0, sim.synthetic, "unqualified Direct never generates");
    }

    private static void unqualifiedHeldSourceWithLateArrivalsStaysOnLattice() {
        // Frames that arrive after their stamp (±6 ms jitter around +2 ms)
        // previously re-primed the timeline on whichever scan was next.
        Sim sim = Sim.thor(heldPattern(2400, 7, 25), true);
        sim.retainHeldFrames = false;
        sim.arrivalOffsetNs = 2_000_000L;
        sim.arrivalJitterNs = 6_000_000L;
        sim.run(20.0);
        assertOnlyLatticeGaps(sim, "late-arrival held source");
        eq(0, sim.synthetic, "late-arrival Direct never generates");
    }

    private static void disabledGenerationHeldSourcePresentsOnlyOnProducerLattice() {
        // Generation disabled (budget, rejected, backend unavailable) for a
        // full minute: the held-lattice proof may qualify the clock at ~31 s,
        // but presentation must stay exactly Direct on the lattice.
        Sim sim = Sim.thor(heldPattern(7200, 13, 25), false);
        sim.retainHeldFrames = false;
        sim.run(60.0);
        check(!sim.value.generatesIntermediateFrames(), "generation disabled");
        assertOnlyLatticeGaps(sim, "disabled generation");
        eq(0, sim.synthetic, "disabled generation never generates");
    }

    private static void directLatticeRetainsHeldFramesLikeFgOff() {
        // With the renderer retaining a held producer frame on its own slot,
        // Direct shows every producer frame: FG-off's exact two scans each.
        Sim sim = Sim.thor(heldPattern(2400, 41, 25), true);
        sim.retainHeldFrames = true;
        sim.run(20.0);
        check(!sim.value.generatesIntermediateFrames(), "still unqualified");
        check(sim.heldRetained > 0, "held frames were retained as endpoints");
        // Startup only: the first late frame re-anchors the stamp-to-slot
        // mapping with one period of margin, and the 90-period bootstrap tier
        // publishes an epoch that clears the renderer FIFO.
        Map<Integer, Integer> gaps = sim.gapsSince(3.0);
        check(gaps.size() == 1 && gaps.containsKey(2),
                "every producer frame occupies exactly two scans: " + gaps);
        assertOnlyLatticeGaps(sim, "retained held frames");
        eq(0, sim.synthetic, "Direct-equal never generates");
    }

    private static void directTargetIsPacedClockNotMeasuredMean() {
        Sim sim = Sim.thor(heldPattern(1200, 41, 25), true);
        sim.run(12.0);
        AdaptiveFrameRateController value = sim.value;
        check(value.sustainedMeasuredSourceHz() < 59.0,
                "fixture measures a held mean: " + value.sustainedMeasuredSourceHz());
        near(PACED_HZ, value.targetOutputHz(), 1.0e-9,
                "unqualified target is the paced producer clock, not the mean");
        eq(60, value.outputFps(), "integer target label");
        near(value.sustainedMeasuredSourceHz(), value.reportedSourceHz(), 0.0,
                "Direct reports the measured unique rate");
        eq(0, value.panelScansPerOutput(),
                "Direct remains unqualified for cadence evidence");
        check(!value.uniformOutputQualified(), "not claimed as generated output");
    }

    private static void directLatticeNeedsAPacedProducerTimeline() {
        // Without a stamped timeline (or 417 ppm off the panel divisor) the
        // former behaviour is unchanged: target = measured, no lattice.
        AdaptiveFrameRateController none = new AdaptiveFrameRateController(120.0);
        none.setPhysicalDisplayRefreshHz(THOR_PANEL_HZ);
        feedLattice(none, PACED_HZ, heldPattern(900, 41, 25), true, 900);
        check(!none.directLatticeActive(), "no timeline: no Direct lattice");
        near(Math.min(THOR_PANEL_HZ, none.presentationSourceHz()),
                none.targetOutputHz(), 1.0e-9, "no timeline keeps measured target");

        AdaptiveFrameRateController unpaced = new AdaptiveFrameRateController(120.0);
        unpaced.setPhysicalDisplayRefreshHz(THOR_PANEL_HZ);
        unpaced.setProducerTimelineHz(60.0);
        check(unpaced.directLatticeHz() == 0.0,
                "unpaced 60.000 is not the 119.95 divisor");
        unpaced.retimeProducerTimeline(PACED_HZ);
        near(PACED_HZ, unpaced.directLatticeHz(), 1.0e-9,
                "the host retime to the panel divisor engages the lattice");

        // Thor 3DS: the paced clock (59.9604) and the controller's panel
        // estimate (119.9358 -> 59.9679 lattice) disagree by ~125 ppm. The
        // Direct passthrough must still engage, or a permanent rejection takes
        // the context-destroying Direct recovery.
        AdaptiveFrameRateController skewed = new AdaptiveFrameRateController(120.0);
        skewed.setPhysicalDisplayRefreshHz(119.935774);
        skewed.setProducerTimelineHz(60.0);
        skewed.retimeProducerTimeline(59.960403880855566);
        near(119.935774 / 2.0, skewed.directLatticeHz(), 1.0e-9, "125 ppm estimate skew keeps the lattice");
    }

    // ------------------------------------------------------------------
    // Task 2: AUTO lock-to-30 tier policy.

    private static void lockToThirtySettlesFiftyEightPointFiveAtThirtyToSixty() {
        // A 58.5-unique source whose holds are not ordinal-proven (so the
        // 60 lattice can never be funded) settles at the locked 30 clock.
        Sim sim = Sim.thor(heldPattern(2400, 41, 25), true);
        sim.value.setTierPolicy(AdaptiveFrameRateController.TierPolicy.LOCK_TO_THIRTY);
        sim.controllerOrdinals = false;
        sim.pairReady = true;
        sim.run(20.0);
        AdaptiveFrameRateController value = sim.value;
        eq(30, value.lockedSourceFps(), "58.5 locks to 30");
        check(value.lockedTierActive(), "locked tier active");
        near(THOR_PANEL_HZ / 4.0, value.presentationSourceHz(), 1.0e-9,
                "locked clock is the 119.95/4 panel divisor");
        near(THOR_PANEL_HZ / 4.0, value.reportedSourceHz(), 1.0e-9,
                "the badge reports the locked 30, not the delivered 58.5");
        near(PACED_HZ, value.targetOutputHz(), 1.0e-9, "30 -> 60, never 30 -> 120");
        eq(60, value.outputFps(), "integer output label");
        eq(2, value.panelScansPerOutput(), "each output spans two scans");
        check(value.generatesIntermediateFrames(), "30 -> 60 generates");
        check(value.uniformOutputQualified(), "exact doubled divisor plan");
        Map<Integer, Integer> gaps = sim.gapsSince(8.0);
        check(gaps.size() == 1 && gaps.containsKey(2),
                "locked 30->60 presents every two scans: " + gaps);
        check(sim.syntheticSince(8.0) > 0, "midpoints were generated");
        check(sim.syntheticSince(8.0) <= sim.realSince(8.0) + 1,
                "generated never exceed half of presented: real=" +
                        sim.realSince(8.0) + " synthetic=" + sim.syntheticSince(8.0));
        check(sim.synthetic <= sim.real + 1,
                "lifetime generated never exceed half of presented");
    }

    private static void adaptivePolicyKeepsFortyTierAndDirect() {
        // Policy off (Built-in (Alpha) / LSFG): the identical source keeps the
        // existing 40 label and stays unqualified Direct.
        Sim sim = Sim.thor(heldPattern(2400, 41, 25), true);
        sim.controllerOrdinals = false;
        sim.pairReady = true;
        sim.run(20.0);
        AdaptiveFrameRateController value = sim.value;
        eq(40, value.lockedSourceFps(), "ADAPTIVE keeps the 40 bucket");
        check(!value.lockedTierActive(), "no lock without the policy");
        check(!value.generatesIntermediateFrames(), "ADAPTIVE stays Direct");
        int[] tiers = value.protocolTiers();
        eq(4, tiers.length, "ADAPTIVE 120-Hz protocol has four tiers");
        eq(40, tiers[1], "ADAPTIVE keeps 40");
    }

    private static void lockToThirtyKeepsStableSixtyAtSixtyTo120() {
        Sim sim = Sim.thor(new boolean[0], true);
        sim.value.setTierPolicy(AdaptiveFrameRateController.TierPolicy.LOCK_TO_THIRTY);
        sim.pairReady = true;
        sim.run(15.0);
        AdaptiveFrameRateController value = sim.value;
        eq(60, value.lockedSourceFps(), "stable 60 stays 60 under AUTO");
        check(!value.lockedTierActive(), "no lock at 60");
        near(PACED_HZ, value.presentationSourceHz(), 1.0e-9, "paced 60 lattice");
        eq(120, value.outputFps(), "60 -> 120");
        eq(1, value.panelScansPerOutput(), "one scan per output");
        check(value.generatesIntermediateFrames(), "60 -> 120 generates");
        Map<Integer, Integer> gaps = sim.gapsSince(6.0);
        check(gaps.size() == 1 && gaps.containsKey(1),
                "60->120 presents every scan: " + gaps);
        int real = sim.realSince(6.0);
        int synthetic = sim.syntheticSince(6.0);
        check(synthetic > 0 && synthetic <= real + 1,
                "half generated at most: real=" + real + " synthetic=" + synthetic);
        int[] tiers = value.protocolTiers();
        eq(3, tiers.length, "AUTO protocol is 60/30/20");
        check(tiers[0] == 60 && tiers[1] == 30 && tiers[2] == 20, "AUTO tiers");
    }

    private static void lockToThirtyLocksTwentyFiveUniqueAtTwentyToForty() {
        // 25 unique images/s on a paced producer (images every 2 or 3 ticks).
        Sim sim = Sim.thor(new boolean[0], true);
        sim.value.setTierPolicy(AdaptiveFrameRateController.TierPolicy.LOCK_TO_THIRTY);
        sim.imageTicks = new int[] {2, 3, 2, 3, 2};
        sim.pairReady = true;
        sim.run(20.0);
        AdaptiveFrameRateController value = sim.value;
        eq(20, value.lockedSourceFps(), "25 unique locks to 20");
        check(value.lockedTierActive(), "locked 20 active");
        near(THOR_PANEL_HZ / 6.0, value.presentationSourceHz(), 1.0e-9,
                "locked 20 clock is the 119.95/6 divisor");
        eq(40, value.outputFps(), "20 -> 40");
        eq(3, value.panelScansPerOutput(), "three scans per output");
        check(value.generatesIntermediateFrames(), "20 -> 40 generates");
        Map<Integer, Integer> gaps = sim.gapsSince(8.0);
        check(gaps.size() == 1 && gaps.containsKey(3),
                "locked 20->40 presents every three scans: " + gaps);
        check(sim.syntheticSince(8.0) <= sim.realSince(8.0) + 1,
                "20->40 generated never exceed half");

        // Policy off: the same stream stays unqualified Direct at its 20 label.
        Sim adaptive = Sim.thor(new boolean[0], true);
        adaptive.imageTicks = new int[] {2, 3, 2, 3, 2};
        adaptive.pairReady = true;
        adaptive.run(20.0);
        eq(20, adaptive.value.lockedSourceFps(), "ADAPTIVE label 20");
        check(!adaptive.value.generatesIntermediateFrames(),
                "ADAPTIVE leaves 25 unique Direct");
    }

    private static void lockToThirtyClimbsBackOnlyWithSustainedSixty() {
        boolean[] held = heldPattern(1500, 41, 25);
        Sim sim = Sim.thor(held, true);
        sim.value.setTierPolicy(AdaptiveFrameRateController.TierPolicy.LOCK_TO_THIRTY);
        sim.controllerOrdinals = false;
        sim.pairReady = true;
        sim.run(20.0);
        eq(30, sim.value.lockedSourceFps(), "held phase is locked to 30");
        // The pattern ends after 1500 ticks (25 s): a clean 60 follows.
        sim.run(30.0);
        eq(30, sim.value.lockedSourceFps(),
                "five clean seconds are not sustained headroom");
        sim.run(42.0);
        eq(60, sim.value.lockedSourceFps(),
                "a sustained clean 60 climbs back to 60");
        check(!sim.value.lockedTierActive(), "lock released");
        sim.run(60.0);
        check(sim.value.generatesIntermediateFrames() && sim.value.outputFps() == 120,
                "recovered 60 re-qualifies 60 -> 120");
        Map<Integer, Integer> gaps = sim.gapsSince(50.0);
        check(gaps.size() == 1 && gaps.containsKey(1),
                "recovered 60->120 every scan: " + gaps);
    }

    private static void lockToThirtyDemotesAnUnfundedHeldSixty() {
        // An acquired, unqualified 60 whose game starts holding frames: the
        // submission clock may no longer vouch for the 60 tier under AUTO.
        boolean[] held = new boolean[3600];
        for (int tick = 1200; tick < held.length; ++tick)
            held[tick] = (tick * 2654435761L >>> 7) % 1000 < 30;
        AdaptiveFrameRateController auto = new AdaptiveFrameRateController(120.0);
        auto.setPhysicalDisplayRefreshHz(THOR_PANEL_HZ);
        auto.setProducerTimelineHz(PACED_HZ);
        auto.setTierPolicy(AdaptiveFrameRateController.TierPolicy.LOCK_TO_THIRTY);
        // Ordinals present for the first 20 s (clean), then a source whose
        // holds are not provable: the qualified 60 clock is revoked.
        feedLattice(auto, PACED_HZ, held, true, 1200);
        eq(60, auto.lockedSourceFps(), "clean start acquires 60");
        feedLatticeFrom(auto, PACED_HZ, held, false, 1200, 3600);
        eq(30, auto.lockedSourceFps(), "unfunded held 60 locks to 30 under AUTO");
        check(auto.lockedTierActive() && auto.generatesIntermediateFrames(),
                "locked 30 -> 60 generates");

        AdaptiveFrameRateController adaptive = new AdaptiveFrameRateController(120.0);
        adaptive.setPhysicalDisplayRefreshHz(THOR_PANEL_HZ);
        adaptive.setProducerTimelineHz(PACED_HZ);
        feedLattice(adaptive, PACED_HZ, held, true, 1200);
        feedLatticeFrom(adaptive, PACED_HZ, held, false, 1200, 3600);
        check(!adaptive.lockedTierActive(), "ADAPTIVE never locks");
    }

    private static void autoWithoutGenerationIsDirectEqualNotLocked() {
        // AUTO with generation unavailable (budget/rejected/panel unmeasured):
        // the 30 label must not decimate real frames; Direct-equal applies.
        Sim sim = Sim.thor(heldPattern(2400, 41, 25), false);
        sim.value.setTierPolicy(AdaptiveFrameRateController.TierPolicy.LOCK_TO_THIRTY);
        sim.controllerOrdinals = false;
        sim.run(20.0);
        AdaptiveFrameRateController value = sim.value;
        eq(30, value.lockedSourceFps(), "AUTO label for the held source");
        check(!value.lockedTierActive(), "no lock without generation");
        check(!value.generatesIntermediateFrames(), "Direct");
        check(value.directLatticeActive(), "Direct-equal lattice");
        near(PACED_HZ, value.targetOutputHz(), 1.0e-9, "Direct-equal target");
        Map<Integer, Integer> gaps = sim.gapsSince(3.0);
        check(gaps.size() == 1 && gaps.containsKey(2),
                "every producer frame shown for two scans: " + gaps);
        eq(0, sim.synthetic, "no generation");
        // Generation becoming available engages the lock at once.
        value.setGenerationAvailable(true);
        check(value.lockedTierActive() && value.generatesIntermediateFrames(),
                "lock engages with generation");
    }

    private static void lockGateAdmitsOneTickPerLockedPeriod() {
        Sim sim = Sim.thor(heldPattern(2400, 41, 25), true);
        sim.value.setTierPolicy(AdaptiveFrameRateController.TierPolicy.LOCK_TO_THIRTY);
        sim.controllerOrdinals = false;
        sim.run(12.0);
        AdaptiveFrameRateController value = sim.value;
        check(value.lockedTierActive(), "locked for the gate test");
        long base = 900_000_000_000L;
        long previous = 0L;
        int admitted = 0;
        for (int tick = 0; tick < 600; ++tick) {
            long stamp = base + Math.round(tick * 1.0e9 / PACED_HZ);
            if (!value.admitLockedTierEndpoint(stamp)) continue;
            if (previous != 0L) {
                long ticks = Math.round((stamp - previous) * PACED_HZ / 1.0e9);
                eq(2L, ticks, "locked endpoints are exactly two producer ticks apart");
            }
            previous = stamp;
            ++admitted;
        }
        eq(300, admitted, "one admission per locked period");
        // A pause restarts the clock instead of admitting a catch-up pair.
        long resumed = previous + 2_000_000_000L;
        check(value.admitLockedTierEndpoint(resumed), "first image after a pause");
        check(!value.admitLockedTierEndpoint(resumed +
                        Math.round(1.0e9 / PACED_HZ)),
                "the following tick belongs to the generated midpoint");
        // ADAPTIVE: every callback is admitted.
        AdaptiveFrameRateController adaptive = new AdaptiveFrameRateController(120.0);
        for (int tick = 0; tick < 10; ++tick)
            check(adaptive.admitLockedTierEndpoint(base + tick * 16_000_000L),
                    "no lock admits every endpoint");
    }

    private static void tierPolicyChangeRebucketsForty() {
        Sim sim = Sim.thor(heldPattern(1200, 41, 25), true);
        sim.controllerOrdinals = false;
        sim.run(10.0);
        eq(40, sim.value.lockedSourceFps(), "ADAPTIVE 40");
        long epoch = sim.value.bufferedPresentationEpoch();
        sim.value.setTierPolicy(AdaptiveFrameRateController.TierPolicy.LOCK_TO_THIRTY);
        eq(30, sim.value.lockedSourceFps(), "AUTO has no 40: re-bucketed to 30");
        check(sim.value.bufferedPresentationEpoch() > epoch, "one epoch boundary");
        sim.value.setTierPolicy(AdaptiveFrameRateController.TierPolicy.ADAPTIVE);
        eq(30, sim.value.lockedSourceFps(), "30 exists in both protocols");
    }

    // ------------------------------------------------------------------
    // Task 3: physical-mode held-frame lattice qualification.

    private static void physicalHeldFramesQualifyPanelLatticeForSixtyTo120() {
        Sim sim = Sim.thor(heldPattern(4200, 41, 25), true);
        sim.pairReady = true;
        sim.run(25.0);
        check(sim.value.qualifiedUniqueTimestampSourceHzForDiagnostics() == 0.0,
                "no strict or held proof before thirty seconds");
        check(!sim.value.generatesIntermediateFrames(), "Direct until proven");
        assertOnlyLatticeGaps(sim, "pre-qualification Direct");
        sim.run(40.0);
        near(PACED_HZ, sim.value.qualifiedUniqueTimestampSourceHzForDiagnostics(),
                1.0e-9, "thirty-second held proof names the 119.95/2 lattice");
        eq(60, sim.value.lockedSourceFps(), "held lattice joins the 60 tier");
        eq(120, sim.value.outputFps(), "60 -> 120");
        check(sim.value.generatesIntermediateFrames(), "held lattice funds 60 -> 120");
        sim.run(70.0);
        near(PACED_HZ, sim.value.qualifiedUniqueTimestampSourceHzForDiagnostics(),
                1.0e-9, "retention keeps the held lattice");
        Map<Integer, Integer> gaps = sim.gapsSince(45.0);
        check(gaps.size() == 1 && gaps.containsKey(1),
                "held frames bridged: every scan presented: " + gaps);
        check(sim.syntheticSince(45.0) <= sim.realSince(45.0) + 1,
                "bridged holds never exceed half generated");
    }

    private static void unpacedHeldFramesNeverClaimPanelLattice() {
        // The same holds on a nominal 60.000 core (417 ppm off 119.95/2).
        AdaptiveFrameRateController value = new AdaptiveFrameRateController(120.0);
        value.setPhysicalDisplayRefreshHz(THOR_PANEL_HZ);
        value.setProducerTimelineHz(60.0);
        feedLattice(value, 60.0, heldPattern(4200, 41, 25), true, 4200);
        check(value.qualifiedUniqueTimestampSourceHzForDiagnostics() == 0.0,
                "unpaced held clock stays unqualified: " +
                        value.qualifiedUniqueTimestampSourceHzForDiagnostics());
        check(!value.generatesIntermediateFrames(), "unpaced 60.000 stays Direct");
    }

    private static void excessiveHeldFramesStayUnqualifiedAndLockUnderAuto() {
        // ~15 percent held frames exceed the 90-percent ordinary bound.
        boolean[] held = heldPattern(4200, 41, 150);
        AdaptiveFrameRateController adaptive = new AdaptiveFrameRateController(120.0);
        adaptive.setPhysicalDisplayRefreshHz(THOR_PANEL_HZ);
        adaptive.setProducerTimelineHz(PACED_HZ);
        feedLattice(adaptive, PACED_HZ, held, true, 4200);
        check(adaptive.qualifiedUniqueTimestampSourceHzForDiagnostics() == 0.0,
                "15 percent holds cannot qualify the lattice");
        check(!adaptive.generatesIntermediateFrames(), "ADAPTIVE stays Direct");

        AdaptiveFrameRateController auto = new AdaptiveFrameRateController(120.0);
        auto.setPhysicalDisplayRefreshHz(THOR_PANEL_HZ);
        auto.setProducerTimelineHz(PACED_HZ);
        auto.setTierPolicy(AdaptiveFrameRateController.TierPolicy.LOCK_TO_THIRTY);
        feedLattice(auto, PACED_HZ, held, true, 4200);
        eq(30, auto.lockedSourceFps(), "AUTO locks the unprovable source to 30");
        check(auto.lockedTierActive() && auto.generatesIntermediateFrames() &&
                        auto.outputFps() == 60,
                "AUTO presents locked 30 -> 60");
    }

    private static void lockedThirtyUpgradesWhenHeldLatticeIsProven() {
        // Under AUTO the ordinal-proven held source starts locked (it cannot
        // hold 60 by the delivery rules) and moves to 60 -> 120 once the
        // thirty-second held-lattice proof funds the 60 lattice.
        Sim sim = Sim.thor(heldPattern(4200, 41, 25), true);
        sim.value.setTierPolicy(AdaptiveFrameRateController.TierPolicy.LOCK_TO_THIRTY);
        sim.pairReady = true;
        sim.run(20.0);
        eq(30, sim.value.lockedSourceFps(), "starts locked to 30");
        check(sim.value.generatesIntermediateFrames() && sim.value.outputFps() == 60,
                "30 -> 60 while the lattice is unproven");
        sim.run(45.0);
        eq(60, sim.value.lockedSourceFps(), "proven held lattice joins 60");
        check(!sim.value.lockedTierActive(), "lock released");
        eq(120, sim.value.outputFps(), "60 -> 120");
        sim.run(60.0);
        eq(60, sim.value.lockedSourceFps(),
                "the funded lattice keeps the 60 tier through its holds");
        Map<Integer, Integer> late = sim.gapsSince(50.0);
        check(late.size() == 1 && late.containsKey(1),
                "proven held lattice presents every scan: " + late);
        Map<Integer, Integer> locked = sim.gapsBetween(8.0, 30.0);
        check(locked.size() == 1 && locked.containsKey(2),
                "locked phase presented every two scans: " + locked);
    }

    // ------------------------------------------------------------------
    // Fixtures.

    /** Deterministic held-tick pattern: about permille/1000 of ticks held. */
    private static boolean[] heldPattern(int ticks, int seed, int permille) {
        boolean[] held = new boolean[ticks];
        long state = seed * 2654435761L + 12345L;
        for (int tick = 1; tick < ticks; ++tick) {
            state = state * 6364136223846793005L + 1442695040888963407L;
            held[tick] = ((state >>> 33) % 1000L) < permille;
        }
        return held;
    }

    private static void feedLattice(AdaptiveFrameRateController value, double stampHz,
                                    boolean[] held, boolean ordinals, int ticks) {
        feedLatticeFrom(value, stampHz, held, ordinals, 0, ticks);
    }

    private static void feedLatticeFrom(AdaptiveFrameRateController value,
                                        double stampHz, boolean[] held,
                                        boolean ordinals, int from, int to) {
        long base = 700_000_000_000L;
        for (int tick = from; tick < to; ++tick) {
            if (tick < held.length && held[tick]) continue;
            value.onProducerFrame(base + Math.round(tick * 1.0e9 / stampHz),
                    ordinals ? tick + 1L : 0L);
        }
    }

    private static void assertOnlyLatticeGaps(Sim sim, String label) {
        check(sim.presents > 100, label + ": presented " + sim.presents);
        for (Map.Entry<Integer, Integer> entry : sim.gaps.entrySet()) {
            int gap = entry.getKey();
            check(gap % 2 == 0 && gap >= 2 && gap <= 2 * (sim.longestHeldRun + 1),
                    label + ": off-lattice gap " + gap + " in " + sim.gaps);
        }
        check(sim.gapCount(2) * 10 > sim.presents * 8,
                label + ": mostly two-scan frames " + sim.gaps);
    }

    /**
     * Renderer-faithful buffered presentation: producer ticks on a stamped
     * lattice, classified admission, endpoint FIFO/active pair, Choreographer
     * callbacks on the physical panel, commit-then-advance.
     */
    private static final class Sim {
        final AdaptiveFrameRateController value;
        final boolean[] held;
        final double panelHz;
        final double stampHz;
        final long panelPeriodNs;
        final long callbackBaseNs = 800_000_000_000L;
        // Stamps sit 3.1 ms after a scan, as a paced core's PTS do.
        final long stampBaseNs = callbackBaseNs + 3_100_000L;
        boolean retainHeldFrames = true;
        boolean controllerOrdinals = true;
        boolean pairReady;
        long arrivalOffsetNs = -6_000_000L;
        long arrivalJitterNs = 3_000_000L;
        int leadScans = 2;
        int[] imageTicks;  // unique image every N ticks (cycled); null = every tick

        final ArrayDeque<long[]> fifo = new ArrayDeque<>();
        long[] left;
        long[] right;
        long lastAcceptedTs;
        long lastAcceptedSub;
        long sequence;
        long observedEpoch;
        long nextTick;
        int callback;
        long lastImageTick = -1L;
        int imageCycle;
        long lastUniqueTick = -1L;
        int longestHeldRun;
        int currentHeldRun;

        int presents;
        int real;
        int synthetic;
        int uniqueDelivered;
        int heldRetained;
        long lastPresentNs;
        final TreeMap<Integer, Integer> gaps = new TreeMap<>();
        final java.util.ArrayList<long[]> log = new java.util.ArrayList<>();

        private Sim(AdaptiveFrameRateController value, boolean[] held,
                    double panelHz, double stampHz) {
            this.value = value;
            this.held = held;
            this.panelHz = panelHz;
            this.stampHz = stampHz;
            this.panelPeriodNs = Math.round(1.0e9 / panelHz);
            observedEpoch = value.bufferedPresentationEpoch();
        }

        static Sim thor(boolean[] held, boolean generationAvailable) {
            AdaptiveFrameRateController value = new AdaptiveFrameRateController(120.0);
            value.setPhysicalDisplayRefreshHz(THOR_PANEL_HZ);
            // The session installs the synchronized 60.000 timeline and the
            // host then retimes it to the measured panel divisor.
            value.setProducerTimelineHz(60.0);
            value.retimeProducerTimeline(PACED_HZ);
            value.setGenerationAvailable(generationAvailable);
            return new Sim(value, held, THOR_PANEL_HZ, PACED_HZ);
        }

        long stamp(long tick) {
            return stampBaseNs + Math.round(tick * 1.0e9 / stampHz);
        }

        long arrival(long tick) {
            long jitter = 0L;
            if (arrivalJitterNs > 0L) {
                long hash = (tick * 0x9E3779B97F4A7C15L) >>> 40;
                jitter = hash % (2L * arrivalJitterNs + 1L) - arrivalJitterNs;
            }
            return stamp(tick) + arrivalOffsetNs + jitter;
        }

        boolean isHeld(long tick) {
            if (imageTicks != null) {
                if (lastImageTick < 0L) return false;
                long due = lastImageTick + imageTicks[imageCycle % imageTicks.length];
                return tick < due;
            }
            return tick < held.length && held[(int) tick];
        }

        long callbackNs(int index) {
            return callbackBaseNs + Math.round(index * 1.0e9 / panelHz);
        }

        void run(double untilSeconds) {
            int last = (int) Math.round(untilSeconds * panelHz);
            for (; callback < last; ++callback) step(callbackNs(callback));
        }

        void step(long callbackNs) {
            while (arrival(nextTick) <= callbackNs) deliver(nextTick++);
            synchronizeEpoch();
            long beforePrepare = value.bufferedPresentationEpoch();
            prepare();
            if (value.bufferedPresentationEpoch() != beforePrepare)
                observedEpoch = value.bufferedPresentationEpoch();
            long physicalNs = callbackNs + leadScans * panelPeriodNs;
            long epochBefore = value.bufferedPresentationEpoch();
            int decision = value.selectBufferedPresentation(callbackNs, physicalNs,
                    seq(left), ts(left), seq(left), sub(left), 0L,
                    seq(right), ts(right), seq(right), sub(right), 0L,
                    pairReady && left != null && right != null);
            if (value.bufferedPresentationEpoch() != epochBefore) {
                synchronizeEpoch();
                decision = AdaptiveFrameRateController.PRESENT_NONE;
            }
            if (decision == AdaptiveFrameRateController.PRESENT_NONE) return;
            int advance = value.bufferedEndpointAdvanceAfterPresentation();
            value.commitBufferedPresentation(true);
            record(physicalNs, decision);
            if (advance == 1) {
                left = right;
                right = null;
            }
        }

        void record(long physicalNs, int decision) {
            if (lastPresentNs > 0L) {
                int scans = (int) Math.round((double) (physicalNs - lastPresentNs) /
                        panelPeriodNs);
                gaps.merge(scans, 1, Integer::sum);
                log.add(new long[] {physicalNs - callbackBaseNs, scans, decision});
            }
            lastPresentNs = physicalNs;
            ++presents;
            if (decision == AdaptiveFrameRateController.PRESENT_SYNTHETIC) ++synthetic;
            else ++real;
        }

        void deliver(long tick) {
            long ts = stamp(tick);
            long submission = tick + 1L;
            if (isHeld(tick)) {
                ++currentHeldRun;
                longestHeldRun = Math.max(longestHeldRun, currentHeldRun);
                deliverHeld(ts, submission);
                return;
            }
            currentHeldRun = 0;
            if (imageTicks != null) {
                if (lastImageTick >= 0L) ++imageCycle;
                lastImageTick = tick;
            }
            ++uniqueDelivered;
            long epochBefore = value.bufferedPresentationEpoch();
            boolean continuous = value.onProducerFrame(ts,
                    controllerOrdinals ? submission : 0L);
            if (!continuous || value.bufferedPresentationEpoch() != epochBefore)
                synchronizeEpoch();
            if (!value.admitLockedTierEndpoint(ts)) return;
            accept(ts, submission);
        }

        /** DisplayFrameGenerator.consumeClassifiedFrame(false). */
        void deliverHeld(long ts, long submission) {
            if (lastAcceptedTs == 0L && !value.hasSustainableGenerationRate()) {
                accept(ts, submission);
                return;
            }
            if (value.lockedTierActive()) {
                if (value.admitLockedTierEndpoint(ts)) {
                    ++heldRetained;
                    accept(ts, submission);
                }
                return;
            }
            if (!retainHeldFrames) return;
            double slotHz = value.hasSustainableGenerationRate() ?
                    value.presentationSourceHz() : value.directLatticeSourceHz();
            if (!(slotHz > 0.0) ||
                    !AdaptiveFrameRateController.duplicateOccupiesNextSourceSlot(
                            lastAcceptedTs, ts, slotHz, lastAcceptedSub, submission))
                return;
            ++heldRetained;
            accept(ts, submission);
        }

        /** DisplayFrameGenerator.acceptPresentationEndpoint. */
        void accept(long ts, long submission) {
            if (lastAcceptedTs > 0L && !AdaptiveFrameRateController.endpointSpanContinuous(
                    lastAcceptedTs, ts, value.presentationSourceHz())) {
                value.resetPresentation();
                observedEpoch = value.bufferedPresentationEpoch();
                clearTimeline();
            }
            lastAcceptedTs = ts;
            lastAcceptedSub = submission;
            if (fifo.size() >= 6) {
                fifo.clear();
            }
            fifo.addLast(new long[] {++sequence, ts, submission});
        }

        void synchronizeEpoch() {
            long epoch = value.bufferedPresentationEpoch();
            if (epoch == observedEpoch) return;
            observedEpoch = epoch;
            clearTimeline();
        }

        void clearTimeline() {
            fifo.clear();
            left = null;
            right = null;
            lastAcceptedTs = 0L;
            lastAcceptedSub = 0L;
        }

        boolean continuous(long[] a, long[] b) {
            return AdaptiveFrameRateController.endpointSpanContinuous(a[1], b[1],
                    value.presentationSourceHz(), a[0], b[0], a[2], b[2], 0L, 0L,
                    false);
        }

        /** DisplayFrameGenerator.prepareBufferedPairIfPossible. */
        void prepare() {
            if (left == null) {
                while (fifo.size() >= 2) {
                    long[] a = fifo.peekFirst();
                    long[] b = fifo.toArray(new long[0][])[1];
                    if (b[0] == a[0] + 1L && continuous(a, b)) break;
                    left = fifo.pollFirst();
                    return;
                }
                boolean generated = value.generatesIntermediateFrames();
                if (!generated && fifo.size() == 1) {
                    left = fifo.pollFirst();
                    return;
                }
                if (fifo.size() < (generated ? 3 : 2)) return;
                left = fifo.pollFirst();
                right = fifo.pollFirst();
                return;
            }
            if (right == null && !fifo.isEmpty()) {
                long[] next = fifo.peekFirst();
                if (next[0] != left[0] + 1L || !continuous(left, next)) {
                    left = null;
                    right = null;
                    value.resetPresentation();
                    prepare();
                    return;
                }
                right = fifo.pollFirst();
            }
        }

        int gapCount(int scans) {
            Integer count = gaps.get(scans);
            return count == null ? 0 : count;
        }

        Map<Integer, Integer> gapsSince(double seconds) {
            return gapsBetween(seconds, Double.MAX_VALUE);
        }

        Map<Integer, Integer> gapsBetween(double from, double to) {
            TreeMap<Integer, Integer> result = new TreeMap<>();
            for (long[] row : log) {
                double at = row[0] / 1.0e9;
                if (at >= from && at < to)
                    result.merge((int) row[1], 1, Integer::sum);
            }
            return result;
        }

        int realSince(double seconds) { return countSince(seconds, false); }
        int syntheticSince(double seconds) { return countSince(seconds, true); }

        private int countSince(double seconds, boolean wantSynthetic) {
            int count = 0;
            for (long[] row : log) {
                if (row[0] / 1.0e9 < seconds) continue;
                boolean isSynthetic =
                        row[2] == AdaptiveFrameRateController.PRESENT_SYNTHETIC;
                if (isSynthetic == wantSynthetic) ++count;
            }
            return count;
        }

        private static long seq(long[] e) { return e == null ? 0L : e[0]; }
        private static long ts(long[] e) { return e == null ? 0L : e[1]; }
        private static long sub(long[] e) { return e == null ? 0L : e[2]; }
    }

    private static void eq(long expected, long actual, String message) {
        if (expected != actual)
            throw new AssertionError(message + ": expected=" + expected +
                    " actual=" + actual);
    }

    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    private static void near(double expected, double actual, double epsilon,
                             String message) {
        if (Math.abs(expected - actual) > epsilon)
            throw new AssertionError(message + ": expected=" + expected +
                    " actual=" + actual);
    }
}
