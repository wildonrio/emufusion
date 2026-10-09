package com.thorium.lucent.video;

/** Synthetic oscillator scenarios, not device acceptance or timestamp replay. */
public final class PhysicalPlanningPhaseTest {
    public static void main(String[] args) {
        for (long nominal : new long[] {8_333_333L, 16_666_667L})
            for (int divisor = 1; divisor <= 6; ++divisor)
                for (int sign : new int[] {-1, 1})
                    for (boolean generated : new boolean[] {false, true})
                        stableSlotsAfterOscillatorStep(nominal, divisor, sign, generated);
        phaseIsNotAcceptanceEvidence();
        System.out.println("PhysicalPlanningPhaseTest passed");
    }

    private static void stableSlotsAfterOscillatorStep(long nominal, int divisor,
                                                       int sign, boolean generated) {
        PhysicalPresentationClock clock = new PhysicalPresentationClock();
        long oldPeriod = nominal + sign * Math.round(nominal * 0.00047);
        long newPeriod = nominal + sign * Math.round(nominal * 0.00019);
        long actual = 1_000_000_000L;
        check(clock.record(actual, nominal), "initial row");
        for (int i = 0; i < 7200; ++i) {
            actual += oldPeriod;
            check(clock.record(actual, nominal), "warmup row");
        }
        clock.beginPresentationEpoch();
        check(clock.trackedPlanningAnchorNs() == 0L, "epoch requires a new real row");
        actual += newPeriod;
        check(clock.record(actual, nominal), "new epoch row");
        long epochActual = actual;
        long previousTarget = 0L, previousOrdinal = -1L;
        PhysicalPresentationDeadline committed = null;
        long committedTime = 0L;
        for (int i = divisor; i <= 1800; i += divisor) {
            actual = epochActual + i * newPeriod;
            // Sparse physical results and alternating timestamp noise. The
            // source rows are separated by an exact number of panel scans.
            long noise = ((i / divisor) % 2 == 0 ? 20_000L : -20_000L);
            check(clock.record(actual + noise, nominal), "noisy sparse row");
            check(clock.observedScans() == i, "physical scan ordinals retained");
            long now = actual + newPeriod * 2 + newPeriod / 2;
            PhysicalPresentationDeadline plan = generated ?
                    PhysicalPresentationDeadline.nextAlignedAppOwnedGenerated(now,
                            clock.trackedPlanningAnchorNs(), clock.planningPeriodNs(),
                            divisor, now, previousTarget) :
                    PhysicalPresentationDeadline.nextAlignedOutputDirect(now,
                            clock.trackedPlanningAnchorNs(), clock.planningPeriodNs(),
                            divisor, now, previousTarget);
            check(plan.valid(), "future plan valid");
            long target = plan.contentPresentationTimeNs();
            long ordinal = Math.round((target - epochActual) / (double) newPeriod);
            check(ordinal % divisor == 0L, "no even/odd or divisor phase flip");
            if (previousOrdinal >= 0L)
                check(ordinal - previousOrdinal == divisor, "no repeated or skipped output slot");
            long error = Math.abs(target - (epochActual + ordinal * newPeriod));
            check(error <= Math.max(150_000L, Math.round(newPeriod * 0.02)),
                    "prospective phase error " + error + " divisor=" + divisor);
            check(plan.driverDesiredPresentTimeNs() == target - 2_000_000L,
                    "driver margin unchanged");
            if (committed != null)
                check(committed.contentPresentationTimeNs() == committedTime,
                        "feedback cannot rewrite an already committed deadline");
            committed = plan;
            committedTime = target;
            previousTarget = target;
            previousOrdinal = ordinal;
        }
    }

    private static void phaseIsNotAcceptanceEvidence() {
        PhysicalPresentationClock clock = new PhysicalPresentationClock();
        long period = 8_333_333L, now = 1_000_000_000L;
        clock.record(now, period);
        for (int i = 1; i <= 120; ++i) clock.record(now + i * period, period);
        long origin = clock.trackedPlanningAnchorNs();
        long last = clock.lastActualNs();
        check(!clock.record(last, period), "duplicate physical row rejected");
        check(!clock.record(last + period / 2, period), "ambiguous half-scan rejected");
        check(clock.trackedPlanningAnchorNs() == origin, "rejected rows cannot move phase");
        check(clock.lastActualNs() == last, "phase tracking preserves actual evidence");
        clock.beginPresentationEpoch();
        check(clock.trackedPlanningAnchorNs() == 0L, "old phase unavailable across epochs");
        long newPhase = last + period;
        check(clock.record(newPhase, period), "fresh epoch row accepted");
        check(clock.trackedPlanningAnchorNs() == newPhase, "fresh epoch starts at measured phase");
        check(clock.record(newPhase + 16_666_667L, 16_666_667L), "refresh switch");
        check(clock.observedScans() == 0L, "new mode resets divisor identity");
        check(clock.trackedPlanningAnchorNs() == newPhase + 16_666_667L, "new mode phase");
        clock.reset();
        check(clock.trackedPlanningAnchorNs() == 0L, "reset unavailable");
    }

    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
}
