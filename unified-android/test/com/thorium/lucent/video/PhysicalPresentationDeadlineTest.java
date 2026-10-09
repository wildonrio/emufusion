package com.thorium.lucent.video;

public final class PhysicalPresentationDeadlineTest {
    public static void main(String[] ignored) {
        appOwnedGeneratedRetainsPredecessorLead();
        eglProspectiveQueueDeadlineOwnsAdmission();
        eglPhaseSweepSelectsFirstAdmissibleScan();
        contentAndDriverTimesRemainDistinct();
        externalBootstrapReservesItsPreparationLead();
        compositorTimelineOwnsBootstrapTargetAndCutoff();
        releaseWindowCannotReachThePreviousThorScan();
        directPlanningReservesPrequeueBeforeTheReleaseWindow();
        directEndpointAdmissionReleasesBeforeTheNextThirtyHertzInput();
        directDivisorPhaseBootstrapsOnASafelyPrequeueableScan();
        missedCutoffSkipsOneWholeScanWithoutCatchup();
        multipleMissedCutoffsRemainPanelAligned();
        externalAnchorOwnsPhysicalPhaseAndMonotonicTargets();
        externalDirectReservesRefreshDerivedLeadWithoutChangingItsLattice();
        directOutputUsesTheNextExactDivisorSlot();
        retunedPhysicalPeriodCannotReuseTheSameScanOrdinal();
        modeAlignedSixtyHertzOutputOwnsOnePredecessorScan();
        externalOutputDivisorUsesTheNextSafeLatticeSlot();
        r108RefreshReserveDeficitAdvancesByOneWholeScan();
        delayedExternalFeedbackCannotReuseAPlannedScan();
        invalidAndOverflowingInputsFailClosed();
        System.out.println("PhysicalPresentationDeadlineTest passed");
    }

    private static void appOwnedGeneratedRetainsPredecessorLead() {
        long anchor = 80_000_000_000L, period = 8_337_000L;
        for (int divisor = 1; divisor <= 4; ++divisor) {
            long previous = 0L;
            for (int frame = 0; frame < 100; ++frame) {
                long now = anchor + frame * period * divisor + 123_456L;
                PhysicalPresentationDeadline plan = PhysicalPresentationDeadline.nextAlignedAppOwnedGenerated(
                        now, anchor, period, divisor, now, previous);
                check(plan.valid(), "app-owned plan remains valid");
                check(plan.contentPresentationTimeNs() - now >= period +
                        PhysicalPresentationDeadline.THOR_DIRECT_OUTPUT_SUBMISSION_LEAD_NS,
                        "every generated-path frame retains predecessor lead");
                eq(0L, (plan.contentPresentationTimeNs() - anchor) % (period * divisor),
                        "preserves exact output divisor");
                if (previous != 0L) eq(period * divisor,
                        plan.contentPresentationTimeNs() - previous,
                        "steady callbacks retain every consecutive output slot");
                eq(PhysicalPresentationDeadline.THOR_DRIVER_LEAD_NS,
                        plan.contentPresentationTimeNs() - plan.driverDesiredPresentTimeNs(),
                        "no driver timestamp offset change");
                previous = plan.contentPresentationTimeNs();
            }
        }
        check(!PhysicalPresentationDeadline.nextAlignedAppOwnedGenerated(
                anchor, anchor, period, 0, anchor, 0).valid(), "reject invalid divisor");
        check(!PhysicalPresentationDeadline.nextAlignedAppOwnedGenerated(
                anchor, anchor, Long.MAX_VALUE, 2, anchor, 0).valid(), "reject overflow");
    }

    private static void eglProspectiveQueueDeadlineOwnsAdmission() {
        long deadline = 191101134694229L, period = 8337285L, latency = 10337285L;
        long now = 191101129350067L, reserve = 1_000_000L;
        PhysicalPresentationDeadline first = PhysicalPresentationDeadline.nextEgl(
                deadline, period, latency, now, 0, reserve);
        check(first.valid(), "captured EGL timing produces valid admission");
        eq(deadline + latency, first.contentPresentationTimeNs(), "uses next reachable display");
        eq(deadline - reserve, first.hardCompletionDeadlineNs(), "queue cutoff is not display minus2ms");
        PhysicalPresentationDeadline late = PhysicalPresentationDeadline.nextEgl(
                deadline, period, latency, deadline - reserve, 0, reserve);
        eq(first.contentPresentationTimeNs() + period, late.contentPresentationTimeNs(), "missed cutoff advances a scan");
        PhysicalPresentationDeadline next = PhysicalPresentationDeadline.nextEgl(
                deadline, period, latency, now, first.contentPresentationTimeNs(), reserve);
        eq(first.contentPresentationTimeNs() + period, next.contentPresentationTimeNs(), "never reuse target");
        check(!PhysicalPresentationDeadline.nextEgl(deadline, period, latency,
                deadline + period + 1, 0, reserve).valid(), "stale timing rejected");
        check(!PhysicalPresentationDeadline.nextEgl(deadline, period, Long.MAX_VALUE,
                now, 0, reserve).valid(), "overflow rejected");
        check(!PhysicalPresentationDeadline.nextEgl(deadline, 0, latency,
                now, 0, reserve).valid(), "invalid interval rejected");
    }

    private static void eglPhaseSweepSelectsFirstAdmissibleScan() {
        // Sweep arrival phase across the measured Thor scan, including both
        // sides of the queue-reserve boundary and a drifting previous target.
        // An independent bounded scan enumeration is the oracle: the planner
        // must not skip a scan that is still admissible under its contract.
        long deadline = 194484255402549L;
        long period = 8_337_664L;
        long latency = period + 2_000_000L;
        long reserve = 1_000_000L;
        for (long phase = -period; phase <= period; phase += 10_001L) {
            long now = deadline + phase;
            for (long shift = -period; shift <= period; shift += 100_003L) {
                long prior = deadline + latency + shift;
                long expected = 0L;
                for (int scan = 0; scan < 5; ++scan) {
                    long queue = deadline + scan * period;
                    long target = queue + latency;
                    if (queue - reserve > now && target - prior >= period / 2L) {
                        expected = target;
                        break;
                    }
                }
                check(expected != 0L, "bounded oracle finds a safe future scan");
                PhysicalPresentationDeadline plan = PhysicalPresentationDeadline.nextEgl(
                        deadline, period, latency, now, prior, reserve);
                check(plan.valid(), "fresh phase-sweep query remains valid");
                eq(expected, plan.contentPresentationTimeNs(),
                        "EGL planner cannot skip an admissible scan");
            }
        }
    }

    private static void compositorTimelineOwnsBootstrapTargetAndCutoff() {
        long now = 9_000_000_000L;
        PhysicalPresentationDeadline value =
                PhysicalPresentationDeadline.fromCompositorTimeline(
                        9_016_666_666L, 9_006_000_000L, now);
        check(value.valid(), "live compositor bootstrap deadline is valid");
        eq(9_016_666_666L, value.contentPresentationTimeNs(),
                "compositor expected time owns bootstrap content phase");
        eq(9_014_666_666L, value.driverDesiredPresentTimeNs(),
                "bootstrap retains Thor's two-millisecond latch bound");
        eq(9_014_666_666L, value.hardCompletionDeadlineNs(),
                "plain bootstrap plan retains its owned cutoff until binding");
        check(!PhysicalPresentationDeadline.fromCompositorTimeline(
                9_016_666_666L, now, now).valid(),
                "expired compositor deadline fails closed");
        check(!PhysicalPresentationDeadline.fromCompositorTimeline(
                9_016_666_666L, 9_016_666_666L, now).valid(),
                "deadline at expected scan fails closed");
        check(!PhysicalPresentationDeadline.fromCompositorTimeline(
                9_016_666_666L, 9_015_000_000L, now).valid(),
                "deadline after the proven latch bound fails closed");
    }

    private static void contentAndDriverTimesRemainDistinct() {
        long callback = 10_000_000_000L;
        long period = 8_448_000L;
        PhysicalPresentationDeadline value =
                PhysicalPresentationDeadline.next(
                        callback, period, callback + 1_000_000L);
        check(value.valid(), "ordinary next-scan plan is valid");
        eq(callback + period, value.contentPresentationTimeNs(),
                "phase owns the exact next scan");
        eq(callback + period -
                        PhysicalPresentationDeadline.THOR_DRIVER_LEAD_NS,
                value.driverDesiredPresentTimeNs(),
                "driver desired-present time is the earliest-display bound");
        eq(callback + period -
                        PhysicalPresentationDeadline.THOR_DRIVER_LEAD_NS,
                value.hardCompletionDeadlineNs(),
                "hard completion cutoff carries the proven Thor lead");
        eq(0L, value.skippedPanelScans(), "no scan skipped on time");
    }

    private static void externalBootstrapReservesItsPreparationLead() {
        long callback = 12_000_000_000L;
        long period = 8_333_333L;
        long now = callback + 200_000L;
        PhysicalPresentationDeadline value =
                PhysicalPresentationDeadline.nextExternal(
                        callback, period, now);
        check(value.valid(), "external bootstrap plan is valid");
        eq(callback + period * 4L, value.contentPresentationTimeNs(),
                "external bootstrap abandons the three unsafe imminent scans");
        check(value.contentPresentationTimeNs() - now >=
                        PhysicalPresentationDeadline.
                                THOR_OUTPUT_SUBMISSION_LEAD_NS + period,
                "external bootstrap retains refresh-derived preparation lead");
        long gateNotBeforeNs = value.contentPresentationTimeNs() -
                PhysicalPresentationDeadline.THOR_DRIVER_LEAD_NS -
                PhysicalPresentationDeadline.
                        THOR_WSI_ENDPOINT_RELEASE_WINDOW_NS;
        check(gateNotBeforeNs > now,
                "external bootstrap endpoint is planned before its WSI gate");
    }

    private static void releaseWindowCannotReachThePreviousThorScan() {
        long fastestThorPanelPeriodNs = 8_333_333L;
        check(PhysicalPresentationDeadline.THOR_DRIVER_LEAD_NS +
                        PhysicalPresentationDeadline.THOR_WSI_GENERATED_RELEASE_WINDOW_NS <
                        fastestThorPanelPeriodNs,
                "generated WSI opening remains after the preceding 120-Hz scan");
        eq(7_000_000L,
                PhysicalPresentationDeadline.THOR_DRIVER_LEAD_NS +
                        PhysicalPresentationDeadline.THOR_WSI_GENERATED_RELEASE_WINDOW_NS,
                "generated r117/r118 bracket stays within one scan");
        check(PhysicalPresentationDeadline.THOR_DRIVER_LEAD_NS +
                        PhysicalPresentationDeadline.THOR_WSI_ENDPOINT_RELEASE_WINDOW_NS <
                        fastestThorPanelPeriodNs,
                "endpoint WSI opening remains after the preceding 120-Hz scan");
        eq(6_500_000L,
                PhysicalPresentationDeadline.THOR_DRIVER_LEAD_NS +
                        PhysicalPresentationDeadline.THOR_WSI_ENDPOINT_RELEASE_WINDOW_NS,
                "endpoint r145/r146 midpoint remains within one scan");
    }

    private static void directPlanningReservesPrequeueBeforeTheReleaseWindow() {
        eq(8_000_000L,
                PhysicalPresentationDeadline.
                        THOR_DIRECT_OUTPUT_SUBMISSION_LEAD_NS,
                "direct admission includes window, driver, and prequeue lead");
        eq(1_000_000L,
                PhysicalPresentationDeadline.THOR_DIRECT_PREQUEUE_RESERVE_NS,
                "r122/r124 prequeue bracket remains explicit and bounded");
        long anchor = 19_000_000_000L;
        long period = 8_335_000L;
        long now = anchor + period * 13L + 200_000L;
        PhysicalPresentationDeadline value =
                PhysicalPresentationDeadline.nextAlignedOutputDirect(
                        anchor + period * 13L, anchor, period, 3,
                        now, 0L);
        long gateNotBeforeNs = value.contentPresentationTimeNs() -
                PhysicalPresentationDeadline.THOR_DRIVER_LEAD_NS -
                PhysicalPresentationDeadline.
                        THOR_WSI_GENERATED_RELEASE_WINDOW_NS;
        check(gateNotBeforeNs - now >=
                        PhysicalPresentationDeadline.
                                THOR_DIRECT_PREQUEUE_RESERVE_NS,
                "planned direct slot leaves prequeue time before gate opening");
    }

    private static void
            modeAlignedSixtyHertzOutputOwnsOnePredecessorScan() {
        long anchor = 60_000_000_000L;
        long period = 16_666_667L;
        long callback = anchor + period * 10L;
        long now = callback + 200_000L;
        PhysicalPresentationDeadline value =
                PhysicalPresentationDeadline.
                        nextAlignedOneScanOutputDirectAfterPredecessor(
                                callback, anchor, period, now, 0L);
        check(value.valid(), "mode-aligned predecessor plan is valid");
        check(value.contentPresentationTimeNs() - now >= period +
                        PhysicalPresentationDeadline.
                                THOR_DIRECT_OUTPUT_SUBMISSION_LEAD_NS,
                "mode-aligned plan retains predecessor scan and Direct lead");
        eq(0L, (value.contentPresentationTimeNs() - anchor) % period,
                "mode-aligned plan remains on measured physical lattice");

        PhysicalPresentationDeadline next =
                PhysicalPresentationDeadline.
                        nextAlignedOneScanOutputDirectAfterPredecessor(
                                callback + period, anchor, period,
                                now + period,
                                value.contentPresentationTimeNs());
        check(next.valid(), "next mode-aligned slot is valid");
        eq(period, next.contentPresentationTimeNs() -
                        value.contentPresentationTimeNs(),
                "steady mode-aligned output advances exactly one scan");

        long queuedDirectTarget = anchor + period * 20L;
        PhysicalPresentationDeadline handoff =
                PhysicalPresentationDeadline.
                        nextAlignedOneScanOutputDirectAfterPredecessor(
                                anchor + period * 18L, anchor, period,
                                anchor + period * 18L + 200_000L,
                                queuedDirectTarget + period);
        eq(queuedDirectTarget + period * 2L,
                handoff.contentPresentationTimeNs(),
                "first generated target follows the queued Direct actual scan");
    }

    /** Physical r170: a 60-Hz panel carrying Direct30 must not retain the
     * transport's single native request across the next 33.3-ms endpoint. */
    private static void directEndpointAdmissionReleasesBeforeTheNextThirtyHertzInput() {
        long anchor = 50_000_000_000L;
        long panelPeriod = 16_666_667L;
        long callback = anchor + panelPeriod * 10L + 200_000L;
        PhysicalPresentationDeadline value =
                PhysicalPresentationDeadline.nextAlignedOutputDirect(
                        callback, anchor, panelPeriod, 1,
                        callback, 0L);
        check(value.valid(), "r170 direct endpoint plan is valid");
        long releaseNotBefore = value.contentPresentationTimeNs() -
                PhysicalPresentationDeadline.THOR_DRIVER_LEAD_NS -
                PhysicalPresentationDeadline.
                        THOR_WSI_ENDPOINT_RELEASE_WINDOW_NS;
        long nextThirtyHertzEndpoint = callback + 33_333_333L;
        check(releaseNotBefore < nextThirtyHertzEndpoint,
                "r170 direct WSI gate opens before the next 30-Hz endpoint");
        check(value.contentPresentationTimeNs() - callback < panelPeriod * 2L,
                "direct endpoint no longer inherits the refresh-derived hold");
    }

    private static void directDivisorPhaseBootstrapsOnASafelyPrequeueableScan() {
        long anchor = 19_500_000_000L;
        long period = 8_339_426L;
        // Model r127's failing phase: the current 40-Hz divisor target is only
        // seven milliseconds away. Eight-millisecond Direct admission must
        // reject it, but the replacement is then about 32 ms away and still
        // owns its gate at the following 25-ms output callback.
        long callback = anchor + period * 12L - 7_000_000L;
        PhysicalPresentationDeadline oldPhase =
                PhysicalPresentationDeadline.nextAlignedOutputDirect(
                        callback, anchor, period, 3, callback, 0L);
        eq(anchor + period * 15L, oldPhase.contentPresentationTimeNs(),
                "unsafe calibration-row divisor phase skips a whole output slot");
        check(oldPhase.contentPresentationTimeNs() - callback > 31_000_000L,
                "r127 phase retains the preceding request into the next callback");

        // Bootstrap on the first safely prequeueable physical scan. That scan
        // becomes the immutable 40-Hz phase anchor only after submission.
        PhysicalPresentationDeadline bootstrap =
                PhysicalPresentationDeadline.nextAlignedOutputDirect(
                        callback, anchor, period, 1, callback, 0L);
        eq(anchor + period * 13L, bootstrap.contentPresentationTimeNs(),
                "Direct bootstrap chooses the first safe panel scan");
        check(bootstrap.contentPresentationTimeNs() - callback >=
                        PhysicalPresentationDeadline.
                                THOR_DIRECT_OUTPUT_SUBMISSION_LEAD_NS,
                "bootstrap retains the complete Direct admission lead");

        long nextCallback = callback + period * 3L;
        PhysicalPresentationDeadline next =
                PhysicalPresentationDeadline.nextAlignedOutputDirect(
                        nextCallback, bootstrap.contentPresentationTimeNs(),
                        period, 3, nextCallback,
                        bootstrap.contentPresentationTimeNs());
        eq(bootstrap.contentPresentationTimeNs() + period * 3L,
                next.contentPresentationTimeNs(),
                "committed bootstrap phase remains exact 40 Hz");
        long priorEndpointGateNs = bootstrap.contentPresentationTimeNs() -
                PhysicalPresentationDeadline.THOR_DRIVER_LEAD_NS -
                PhysicalPresentationDeadline.
                        THOR_WSI_ENDPOINT_RELEASE_WINDOW_NS;
        check(priorEndpointGateNs < nextCallback,
                "prior endpoint release gate opens before the next output callback");
        long priorGeneratedGateNs = bootstrap.contentPresentationTimeNs() -
                PhysicalPresentationDeadline.THOR_DRIVER_LEAD_NS -
                PhysicalPresentationDeadline.
                        THOR_WSI_GENERATED_RELEASE_WINDOW_NS;
        check(priorGeneratedGateNs < nextCallback,
                "prior midpoint release gate opens before the next output callback");
    }

    private static void missedCutoffSkipsOneWholeScanWithoutCatchup() {
        long callback = 20_000_000_000L;
        long period = 8_448_000L;
        long firstCutoff = callback + period -
                PhysicalPresentationDeadline.THOR_DRIVER_LEAD_NS;
        PhysicalPresentationDeadline value =
                PhysicalPresentationDeadline.next(
                        callback, period, firstCutoff);
        eq(callback + period * 2L, value.contentPresentationTimeNs(),
                "crossed cutoff abandons exactly one scan");
        eq(callback + period * 2L -
                        PhysicalPresentationDeadline.THOR_DRIVER_LEAD_NS,
                value.driverDesiredPresentTimeNs(),
                "replacement desired time remains the earlier driver bound");
        eq(callback + period * 2L -
                        PhysicalPresentationDeadline.THOR_DRIVER_LEAD_NS,
                value.hardCompletionDeadlineNs(),
                "replacement cutoff remains early");
        eq(1L, value.skippedPanelScans(), "one skipped scan reported");
    }

    private static void multipleMissedCutoffsRemainPanelAligned() {
        long callback = 30_000_000_000L;
        long period = 8_333_333L;
        long now = callback + period * 4L;
        PhysicalPresentationDeadline value =
                PhysicalPresentationDeadline.next(callback, period, now);
        check(value.valid(), "late plan still finds a future scan");
        check(value.hardCompletionDeadlineNs() > now,
                "returned hard cutoff is strictly future");
        eq(0L, (value.contentPresentationTimeNs() - callback) % period,
                "late plan remains on the original panel lattice");
        check(value.skippedPanelScans() >= 4,
                "every stale scan is abandoned, not caught up");
    }

    private static void externalAnchorOwnsPhysicalPhaseAndMonotonicTargets() {
        long anchor = 40_000_000_000L;
        long period = 8_448_000L;
        long callback = anchor + period * 10L + 1_000_000L;
        long now = callback + 1_000_000L;
        PhysicalPresentationDeadline value =
                PhysicalPresentationDeadline.nextAligned(
                        callback, anchor, period, now, 0L);
        eq(anchor + period * 11L, value.contentPresentationTimeNs(),
                "external target follows the measured Vulkan phase");
        eq(value.contentPresentationTimeNs() -
                        PhysicalPresentationDeadline.THOR_DRIVER_LEAD_NS,
                value.driverDesiredPresentTimeNs(),
                "external driver target precedes the physical scan");
        eq(value.contentPresentationTimeNs() -
                        PhysicalPresentationDeadline.THOR_DRIVER_LEAD_NS,
                value.hardCompletionDeadlineNs(),
                "external completion cutoff remains early");
    }

    private static void delayedExternalFeedbackCannotReuseAPlannedScan() {
        long anchor = 50_000_000_000L;
        long period = 8_333_333L;
        long callback = anchor + 500_000L;
        long now = callback + 500_000L;
        PhysicalPresentationDeadline first =
                PhysicalPresentationDeadline.nextAligned(
                        callback, anchor, period, now, 0L);
        PhysicalPresentationDeadline second =
                PhysicalPresentationDeadline.nextAligned(
                        callback + 100_000L, anchor, period,
                        now + 100_000L, first.contentPresentationTimeNs());
        eq(first.contentPresentationTimeNs() + period,
                second.contentPresentationTimeNs(),
                "unretired target cannot be selected twice");
    }

    private static void externalDirectReservesRefreshDerivedLeadWithoutChangingItsLattice() {
        long anchor = 44_000_000_000L;
        long period = 8_333_333L;
        long callback = anchor + period * 10L;
        long now = callback + 200_000L;
        PhysicalPresentationDeadline first =
                PhysicalPresentationDeadline.nextAlignedDirect(
                        callback, anchor, period, now, 0L);
        eq(anchor + period * 14L, first.contentPresentationTimeNs(),
                "Direct target reserves the first refresh-safe aligned scan");
        eq(0L, first.presentationPipelineScans(),
                "Direct presentation has no measured generated-output pipeline");
        check(first.contentPresentationTimeNs() - now >=
                        PhysicalPresentationDeadline.THOR_OUTPUT_SUBMISSION_LEAD_NS +
                                period,
                "Direct planning includes one measured refresh beyond the base lead");
        check(first.contentPresentationTimeNs() - now <
                        PhysicalPresentationDeadline.THOR_OUTPUT_SUBMISSION_LEAD_NS +
                                period * 2L,
                "Direct planning uses the first refresh-safe panel scan");
        eq(3L, first.skippedPanelScans(),
                "three intervening physical scans are deliberately left untouched");

        PhysicalPresentationDeadline second =
                PhysicalPresentationDeadline.nextAlignedDirect(
                        callback + period, anchor, period,
                        now + period, first.contentPresentationTimeNs());
        eq(first.contentPresentationTimeNs() + period,
                second.contentPresentationTimeNs(),
                "Direct targets remain on every panel scan after pipelining");
    }

    private static void externalOutputDivisorUsesTheNextSafeLatticeSlot() {
        long anchor = 45_000_000_000L;
        long period = 8_335_000L;
        // The selection callback is one scan after the output-lattice phase.
        // The next 40-Hz target is only two scans away and cannot meet the
        // predecessor-token deadline. The following exact 40-Hz lattice target
        // is selected without relabelling or catch-up.
        long callback = anchor + period * 13L;
        long now = callback + 200_000L;
        PhysicalPresentationDeadline first =
                PhysicalPresentationDeadline.nextAlignedOutput(
                        callback, anchor, period, 3, now, 0L);
        eq(anchor + period * 18L, first.contentPresentationTimeNs(),
                "20-to-40 content targets the exact driver scan");
        eq(anchor + period * 18L -
                        PhysicalPresentationDeadline.THOR_DRIVER_LEAD_NS,
                first.driverDesiredPresentTimeNs(),
                "generated driver slot remains on the proven output lattice");
        eq(0L, first.presentationPipelineScans(),
                "generated output does not invent a presentation pipeline");
        check(first.contentPresentationTimeNs() - now >=
                        PhysicalPresentationDeadline.THOR_OUTPUT_SUBMISSION_LEAD_NS +
                                period,
                "off-phase generated work receives the refresh-derived submission lead");
        check(first.contentPresentationTimeNs() - now < 42_000_000L,
                "off-phase work uses the next safe output target");

        // r89/r90 proved that accepting the same target with only the old
        // fourteen-millisecond lead can miss SurfaceFlinger's latch cycle even
        // when endpoint GPU work is tiny. A marginal target is abandoned as a
        // whole output-lattice slot; it is never relabelled to the next scan.
        long marginalNow = anchor + period * 18L - 21_500_000L;
        PhysicalPresentationDeadline marginal =
                PhysicalPresentationDeadline.nextAlignedOutput(
                        marginalNow - 200_000L, anchor, period, 3,
                        marginalNow, 0L);
        eq(anchor + period * 21L, marginal.contentPresentationTimeNs(),
                "sub-bracket-reserve target is abandoned before submission");

        // Planning is intentionally ahead of physical completion; delayed
        // feedback cannot reuse the already-owned target.
        long postCompletionCallback = anchor + period * 16L;
        long postCompletionNow = postCompletionCallback + 200_000L;
        PhysicalPresentationDeadline postCompletion =
                PhysicalPresentationDeadline.nextAlignedOutput(
                        postCompletionCallback, anchor, period, 3,
                        postCompletionNow, anchor + period * 15L);
        eq(anchor + period * 21L,
                postCompletion.contentPresentationTimeNs(),
                "late callback advances to the next safe output slot");

        long alignedCallback = anchor + period * 15L;
        PhysicalPresentationDeadline aligned =
                PhysicalPresentationDeadline.nextAlignedOutput(
                        alignedCallback, anchor, period, 3,
                        alignedCallback + 200_000L, 0L);
        eq(anchor + period * 21L, aligned.contentPresentationTimeNs(),
                "aligned callback abandons an output slot lacking refresh reserve");
        eq(anchor + period * 21L -
                        PhysicalPresentationDeadline.THOR_DRIVER_LEAD_NS,
                aligned.driverDesiredPresentTimeNs(),
                "aligned driver slot preserves the earlier immutable cutoff");
        check(aligned.hardCompletionDeadlineNs() -
                        (alignedCallback + 200_000L) > 47_000_000L,
                "aligned generated work advances by a whole output slot");

        long tooLateCallback = anchor + period * 14L;
        PhysicalPresentationDeadline skipped =
                PhysicalPresentationDeadline.nextAlignedOutput(
                        tooLateCallback, anchor, period, 3,
                        tooLateCallback + 200_000L, 0L);
        eq(anchor + period * 18L, skipped.contentPresentationTimeNs(),
                "a callback inside the lead window abandons the imminent slot");

        PhysicalPresentationDeadline second =
                PhysicalPresentationDeadline.nextAlignedOutput(
                        callback + period * 3L, anchor, period, 3,
                        now + period * 3L,
                        first.contentPresentationTimeNs());
        eq(first.contentPresentationTimeNs() + period * 3L,
                second.contentPresentationTimeNs(),
                "successive generated targets stay exactly three scans apart");
    }

    private static void directOutputUsesTheNextExactDivisorSlot() {
        long anchor = 46_000_000_000L;
        long period = 8_335_000L;
        long callback = anchor + period * 13L;
        long now = callback + 200_000L;
        PhysicalPresentationDeadline first =
                PhysicalPresentationDeadline.nextAlignedOutputDirect(
                        callback, anchor, period, 3, now, 0L);
        eq(anchor + period * 15L, first.contentPresentationTimeNs(),
                "safe next 20-to-40 divisor slot retains its lattice");
        check(first.contentPresentationTimeNs() - now >=
                        PhysicalPresentationDeadline.
                                THOR_DIRECT_OUTPUT_SUBMISSION_LEAD_NS,
                "direct slot retains its complete prequeue lead");
        check(first.contentPresentationTimeNs() - now < period * 3L,
                "direct slot does not inherit SurfaceControl reserve");
        eq(first.contentPresentationTimeNs() -
                        PhysicalPresentationDeadline.THOR_DRIVER_LEAD_NS,
                first.driverDesiredPresentTimeNs(),
                "direct native request retains the two-time contract");

        PhysicalPresentationDeadline second =
                PhysicalPresentationDeadline.nextAlignedOutputDirect(
                        callback + period * 3L, anchor, period, 3,
                        now + period * 3L,
                        first.contentPresentationTimeNs());
        eq(first.contentPresentationTimeNs() + period * 3L,
                second.contentPresentationTimeNs(),
                "direct successive targets remain exactly three scans apart");

        PhysicalPresentationDeadline sixtyToOneTwenty =
                PhysicalPresentationDeadline.nextAlignedOutputDirect(
                        anchor + period * 20L, anchor, period, 1,
                        anchor + period * 20L + 200_000L, 0L);
        eq(anchor + period * 21L,
                sixtyToOneTwenty.contentPresentationTimeNs(),
                "bounded direct admission still fits one 120-Hz scan");
    }

    private static void retunedPhysicalPeriodCannotReuseTheSameScanOrdinal() {
        long anchor = 50_000_000_000L;
        long oldPeriod = 8_338_574L;
        long newPeriod = oldPeriod + 10_000L;
        long previousTarget = anchor + oldPeriod * 100L;
        long callback = previousTarget - oldPeriod;
        long now = previousTarget - oldPeriod / 2L;

        PhysicalPresentationDeadline value =
                PhysicalPresentationDeadline.nextAlignedOutputDirect(
                        callback, anchor, newPeriod, 1, now, previousTarget);
        check(value.valid(), "retuned physical lattice remains plannable");
        eq(anchor + newPeriod * 101L,
                value.contentPresentationTimeNs(),
                "retuned lattice skips the shifted copy of the prior scan ordinal");
        check(value.contentPresentationTimeNs() - previousTarget >=
                        newPeriod / 2L,
                "successive targets are separated by an unambiguous half scan");
    }

    private static void r108RefreshReserveDeficitAdvancesByOneWholeScan() {
        long period = 8_333_333L;
        long now = 252_607_063_609_365L;
        // r108's selected visible target was this scan (driver desired time
        // plus the immutable two-millisecond visibility lead). Its preceding
        // token deadline had only 2.798 ms left, so the refresh-derived native
        // admission correctly rejected it.
        long unsafeTarget = 252_607_087_078_454L;
        long unsafePredecessorDeadline = 252_607_066_406_950L;
        check(unsafePredecessorDeadline - now < period +
                        PhysicalPresentationDeadline.
                                THOR_COMPOSITOR_SUBMISSION_RESERVE_NS,
                "r108 target is below the refresh-derived admission reserve");

        PhysicalPresentationDeadline replanned =
                PhysicalPresentationDeadline.nextAlignedOutput(
                        now - 500_000L, unsafeTarget, period, 1,
                        now, 0L);
        eq(unsafeTarget + period,
                replanned.contentPresentationTimeNs(),
                "r108 target is abandoned by exactly one whole panel scan");
        long modeledNextDeadline = unsafePredecessorDeadline + period;
        check(modeledNextDeadline - now >= period +
                        PhysicalPresentationDeadline.
                                THOR_COMPOSITOR_SUBMISSION_RESERVE_NS,
                "replacement token retains one refresh plus handoff reserve");
    }

    private static void invalidAndOverflowingInputsFailClosed() {
        check(!PhysicalPresentationDeadline.next(0L, 8_448_000L, 1L).valid(),
                "zero callback rejected");
        check(!PhysicalPresentationDeadline.next(1L, 0L, 1L).valid(),
                "zero period rejected");
        check(!PhysicalPresentationDeadline.next(1L, 1_000_000L, 1L).valid(),
                "lead larger than period rejected");
        check(!PhysicalPresentationDeadline.next(
                Long.MAX_VALUE - 4L, 8L, Long.MAX_VALUE - 4L, 1L).valid(),
                "overflow rejected");
        check(!PhysicalPresentationDeadline.nextAligned(
                1L, Long.MAX_VALUE - 10L, 8L,
                1L, Long.MAX_VALUE - 1L, 1L).valid(),
                "aligned target overflow rejected");
    }

    private static void eq(long expected, long actual, String message) {
        if (expected != actual)
            throw new AssertionError(message + ": expected=" + expected +
                    " actual=" + actual);
    }

    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
}
