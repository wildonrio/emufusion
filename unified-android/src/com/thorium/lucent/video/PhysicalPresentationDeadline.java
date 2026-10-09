package com.thorium.lucent.video;

/**
 * Immutable timing contract for one buffer submitted from a display callback.
 *
 * <p>The image must be rendered for {@link #contentPresentationTimeNs()}, the
 * physical scan at which the buffer is intended to become visible.  The
 * completion deadline is deliberately a different value: Thor's compositor
 * path was physically measured to require the buffer to be submitted 2 ms
 * before that scan. {@code VK_GOOGLE_display_timing} defines its desired time
 * as an earliest-display bound, so the Vulkan timestamp and hard submission
 * cutoff are that proven earlier instant while content retains the exact
 * intended physical scan.</p>
 *
 * <p>If work has already crossed the lead-time cutoff, planning advances by a
 * whole panel scan.  It never returns a stale deadline and never authorizes a
 * catch-up submission.</p>
 */
public final class PhysicalPresentationDeadline {
    /** r59's proven driver lead; queue isolation addresses the later miss. */
    public static final long THOR_DRIVER_LEAD_NS = 2_000_000L;
    /**
     * Generated-midpoint WSI release window before the hard driver cutoff.
     *
     * <p>Thor r117 put generated rows one scan early with a six-millisecond
     * window, while r118 put the first active generated row one scan late with
     * four milliseconds. Five milliseconds is the only integer-millisecond
     * boundary inside that physically measured bracket. Endpoint timing is a
     * separate measured class and must not inherit this value.</p>
     */
    public static final long THOR_WSI_GENERATED_RELEASE_WINDOW_NS = 5_000_000L;
    /**
     * Exact-endpoint WSI release window before the hard driver cutoff.
     *
     * <p>Thor r118 landed the active endpoint exactly with four milliseconds;
     * r119 moved the same class to five milliseconds and landed it one scan
     * early. After the later release-worker and queue-ownership fixes, r145
     * proved four milliseconds over a full 20-to-40 qualification, while r146
     * at the tighter 30-to-60 cadence put 537 of 538 endpoint rows on their
     * exact scan and one row exactly one scan late. Use the measured interior
     * midpoint, 4.5 ms, as a qualification arm. The desired scan, two-ms
     * driver bound, exact-slot verifier, and fail-closed miss handling remain
     * unchanged.</p>
     */
    public static final long THOR_WSI_ENDPOINT_RELEASE_WINDOW_NS = 4_500_000L;
    /**
     * Minimum time reserved for Java/JNI to prequeue the visible Vulkan request
     * before its immutable WSI release window opens.
     *
     * <p>Thor r122 proved that treating the release-window opening itself as
     * the planning boundary is too late: one request began prequeue about
     * 0.45 ms after that boundary and landed one complete panel scan late.
     * Thor r124 then proved that two milliseconds makes total admission nine
     * milliseconds—longer than a 120-Hz scan—and necessarily abandons valid
     * 20-to-40 midpoint slots. One millisecond is the bounded interior of the
     * physical bracket. It is admission time only and does not move or widen
     * either content-type-specific native release window.</p>
     */
    public static final long THOR_DIRECT_PREQUEUE_RESERVE_NS = 1_000_000L;
    /**
     * Minimum lead for an already-prepared direct Vulkan visible request.
     *
     * <p>The direct swapchain does not consume a SurfaceControl predecessor
     * token, so carrying that path's 30.3-ms refresh-derived reserve made a
     * single-pending transport own two future 20-to-40 output slots at once.
     * r115 consequently proved exact endpoint scan placement but produced no
     * generated frames: every prepared midpoint expired behind the preceding
     * endpoint. Direct WSI needs only the largest immutable prequeue window
     * plus the two-millisecond earliest-display lead and the bounded prequeue
     * reserve above. The unchanged release window, hard cutoff, and exact
     * physical-slot verifier still fail closed; an unsafe imminent divisor
     * slot is abandoned rather than armed late.</p>
     */
    public static final long THOR_DIRECT_OUTPUT_SUBMISSION_LEAD_NS =
            THOR_WSI_GENERATED_RELEASE_WINDOW_NS + THOR_DRIVER_LEAD_NS +
                    THOR_DIRECT_PREQUEUE_RESERVE_NS;
    /**
     * Minimum wall lead for one already-prepared external output submission.
     *
     * <p>This includes the five-millisecond native WSI hold, the two-millisecond
     * driver lead, the measured sub-four-millisecond enqueue path, and the
     * additional compositor-latch reserve required by physical r103. The
     * predecessor-token bracket must reach the preceding row's deadline, which
     * is about 18.67 ms before the visible target on Thor. Physical r108 then
     * proved that handing the transaction to the native worker with only the
     * old two-millisecond reserve is insufficient: the worker must still own a
     * complete measured refresh plus that reserve before the predecessor
     * deadline. Planning therefore adds {@code panelPeriodNs} to this bounded
     * base lead. A missed lattice slot is still abandoned rather than caught
     * up.</p>
     */
    public static final long THOR_OUTPUT_SUBMISSION_LEAD_NS = 22_000_000L;
    /**
     * Minimum time between SurfaceControl handoff and the selected
     * SurfaceFlinger frame-timeline deadline.
     *
     * <p>Physical r98 submitted a cheap endpoint row with 0.776 ms of Java/JNI
     * enqueue work, but SurfaceFlinger latched it 0.139 ms after the selected
     * composition deadline and displayed it one scan late. A timeline whose
     * deadline is merely positive is therefore not still safely meetable.
     * Keep two milliseconds for the transaction handoff itself; an unsafe
     * slot is abandoned before controller selection and is never caught up.</p>
     */
    public static final long THOR_COMPOSITOR_SUBMISSION_RESERVE_NS =
            2_000_000L;

    private final long contentPresentationTimeNs;
    private final long driverDesiredPresentTimeNs;
    private final long hardCompletionDeadlineNs;
    private final int skippedPanelScans;
    private final int presentationPipelineScans;

    private PhysicalPresentationDeadline(long contentPresentationTimeNs,
                                         long driverDesiredPresentTimeNs,
                                         long hardCompletionDeadlineNs,
                                         int skippedPanelScans,
                                         int presentationPipelineScans) {
        this.contentPresentationTimeNs = contentPresentationTimeNs;
        this.driverDesiredPresentTimeNs = driverDesiredPresentTimeNs;
        this.hardCompletionDeadlineNs = hardCompletionDeadlineNs;
        this.skippedPanelScans = skippedPanelScans;
        this.presentationPipelineScans = presentationPipelineScans;
    }

    /**
     * Adopts one live API-33 compositor timeline as the physical bootstrap
     * target.
     *
     * <p>The compositor's expected-present time owns content phase. The proven
     * Thor desired-present bound remains the visibility authority. Request
     * binding replaces the hard completion cutoff with the immediately
     * preceding row's earlier deadline; that predecessor may initiate
     * compositor work, while the later desired timestamp forbids its scan from
     * becoming visible.</p>
     */
    public static PhysicalPresentationDeadline fromCompositorTimeline(
            long expectedPresentationTimeNs, long compositorDeadlineNs,
            long nowNs) {
        if (expectedPresentationTimeNs <= 0L ||
                compositorDeadlineNs <= nowNs || nowNs < 0L ||
                compositorDeadlineNs >= expectedPresentationTimeNs)
            return invalid();
        long driverDesiredNs = expectedPresentationTimeNs -
                THOR_DRIVER_LEAD_NS;
        if (driverDesiredNs <= nowNs ||
                compositorDeadlineNs > driverDesiredNs)
            return invalid();
        return new PhysicalPresentationDeadline(
                expectedPresentationTimeNs, driverDesiredNs,
                driverDesiredNs, 0, 0);
    }

    /**
     * Plans the first scan whose early driver deadline is still in the future.
     * Invalid or overflowing inputs return an invalid zero-valued plan.
     */
    public static PhysicalPresentationDeadline next(
            long callbackFrameTimeNs, long panelPeriodNs, long nowNs) {
        return next(callbackFrameTimeNs, panelPeriodNs, nowNs,
                THOR_DRIVER_LEAD_NS);
    }

    /** EGL's prospective queue deadline and display latency are separate clocks.
     * Reserve is caller-owned preparation/queue margin, never a display offset.
     * Old or invalid query data cannot authorize a submission. */
    public static PhysicalPresentationDeadline nextEgl(
            long compositeDeadlineNs, long intervalNs, long latencyNs,
            long nowNs, long minimumTargetExclusiveNs, long reserveNs) {
        if (compositeDeadlineNs <= 0L || intervalNs <= THOR_DRIVER_LEAD_NS ||
                latencyNs < THOR_DRIVER_LEAD_NS || nowNs < 0L || reserveNs < 0L ||
                minimumTargetExclusiveNs < 0L ||
                (nowNs > compositeDeadlineNs && nowNs - compositeDeadlineNs > intervalNs))
            return invalid();
        long target = saturatingAdd(compositeDeadlineNs, latencyNs);
        long earliest = saturatingAdd(saturatingAdd(nowNs, reserveNs), latencyNs);
        if (target == Long.MAX_VALUE || earliest == Long.MAX_VALUE) return invalid();
        if (minimumTargetExclusiveNs > 0L) {
            long distinct = saturatingAdd(minimumTargetExclusiveNs, intervalNs / 2L);
            if (distinct == Long.MAX_VALUE) return invalid();
            earliest = Math.max(earliest, distinct - 1L);
        }
        long scans = target > earliest ? 0L : (earliest - target) / intervalNs + 1L;
        if (scans > Integer.MAX_VALUE) return invalid();
        long advance = saturatingMultiply(intervalNs, scans);
        // saturatingMultiply treats zero as zero, as required for the first slot.
        target = saturatingAdd(target, advance);
        long queueDeadline = saturatingAdd(compositeDeadlineNs, advance);
        if (target == Long.MAX_VALUE || queueDeadline == Long.MAX_VALUE ||
                queueDeadline <= reserveNs || queueDeadline - reserveNs <= nowNs)
            return invalid();
        return new PhysicalPresentationDeadline(target, target - THOR_DRIVER_LEAD_NS,
                queueDeadline - reserveNs, (int) scans, 0);
    }

    /**
     * Plans a preprepared external endpoint before a measured physical anchor
     * exists.
     *
     * <p>The callback phase is the only available bootstrap lattice, but the
     * external path still needs the same refresh-derived preparation lead as
     * its calibrated endpoint path. Thor r123 proved that falling back to
     * {@link #next(long, long, long)} admitted an endpoint after its four-ms
     * WSI gate had opened. This method abandons those imminent bootstrap scans
     * without inventing a catch-up submission.</p>
     */
    public static PhysicalPresentationDeadline nextExternal(
            long callbackFrameTimeNs, long panelPeriodNs, long nowNs) {
        long firstTargetNs = saturatingAdd(
                callbackFrameTimeNs, panelPeriodNs);
        long preparationLeadNs = refreshDerivedSubmissionLead(panelPeriodNs);
        long earliestTargetNs = saturatingAdd(nowNs, preparationLeadNs);
        if (firstTargetNs == Long.MAX_VALUE || firstTargetNs <= 0L ||
                preparationLeadNs == Long.MAX_VALUE ||
                preparationLeadNs <= 0L ||
                earliestTargetNs == Long.MAX_VALUE || earliestTargetNs <= 0L)
            return invalid();
        return nextAlignedAtOrAfter(
                callbackFrameTimeNs, firstTargetNs,
                panelPeriodNs, panelPeriodNs, nowNs,
                0L, earliestTargetNs, THOR_DRIVER_LEAD_NS);
    }

    /**
     * Plans on an externally measured physical-present lattice.
     *
     * <p>{@code physicalAnchorNs} is a completed Vulkan/EGL physical-present
     * timestamp, not a Java callback timestamp. The selected target is the
     * first anchor-aligned scan whose completion cutoff is still in the future
     * and which follows every target already handed to the driver. This keeps
     * delayed timing feedback from selecting the same future scan twice.</p>
     */
    public static PhysicalPresentationDeadline nextAligned(
            long callbackFrameTimeNs, long physicalAnchorNs,
            long panelPeriodNs, long nowNs, long minimumTargetExclusiveNs) {
        return nextAligned(callbackFrameTimeNs, physicalAnchorNs,
                panelPeriodNs, nowNs, minimumTargetExclusiveNs,
                THOR_DRIVER_LEAD_NS);
    }

    /**
     * Plans a bounded preparation window on an exact output-divisor lattice.
     *
     * <p>The target remains on the exact output-divisor lattice and strictly
     * follows every prior target. It is the first such target with the bounded
     * external-submission lead above. A callback too close to the next target
     * abandons that target and selects the following one; it is never retried
     * or caught up.</p>
     */
    public static PhysicalPresentationDeadline nextAlignedOutput(
            long callbackFrameTimeNs, long physicalAnchorNs,
            long panelPeriodNs, int panelScansPerOutput,
            long nowNs, long minimumTargetExclusiveNs) {
        return nextAlignedOutput(callbackFrameTimeNs, physicalAnchorNs,
                panelPeriodNs, panelScansPerOutput, nowNs,
                minimumTargetExclusiveNs, THOR_DRIVER_LEAD_NS);
    }

    /**
     * Plans the first exact output-divisor slot for a preprepared direct WSI
     * image without inheriting SurfaceControl's predecessor-token reserve.
     */
    public static PhysicalPresentationDeadline nextAlignedOutputDirect(
            long callbackFrameTimeNs, long physicalAnchorNs,
            long panelPeriodNs, int panelScansPerOutput,
            long nowNs, long minimumTargetExclusiveNs) {
        if (panelScansPerOutput < 1) return invalid();
        long outputPeriodNs = saturatingMultiply(
                panelPeriodNs, panelScansPerOutput);
        if (outputPeriodNs == Long.MAX_VALUE || outputPeriodNs <= 0L)
            return invalid();
        long earliestOutputNs = saturatingAdd(
                nowNs, THOR_DIRECT_OUTPUT_SUBMISSION_LEAD_NS);
        if (earliestOutputNs == Long.MAX_VALUE || earliestOutputNs <= 0L)
            return invalid();
        return nextAlignedAtOrAfter(
                callbackFrameTimeNs, physicalAnchorNs,
                panelPeriodNs, outputPeriodNs, nowNs,
                minimumTargetExclusiveNs, earliestOutputNs,
                THOR_DRIVER_LEAD_NS);
    }

    /**
     * App-owned generated EGL output retains a predecessor scan of queue lead.
     * Thor fence-test frames 2222/8014 rendered before scanout but were latched
     * only about 1.8ms before it and appeared one scan late. The shorter WSI
     * admission window is therefore not sufficient evidence of EGL readiness.
     * This is preparation lead, not a timestamp offset: preserve the divisor
     * lattice, driver timestamp and physical verification. Device qualification
     * must still establish throughput and GPU completion under inference load.
     */
    public static PhysicalPresentationDeadline nextAlignedAppOwnedGenerated(
            long callbackFrameTimeNs, long physicalAnchorNs,
            long panelPeriodNs, int panelScansPerOutput, long nowNs,
            long minimumTargetExclusiveNs) {
        if (panelPeriodNs <= 0L || panelScansPerOutput <= 0) return invalid();
        long outputPeriodNs = saturatingMultiply(panelPeriodNs, panelScansPerOutput);
        long leadNs = saturatingAdd(panelPeriodNs, THOR_DIRECT_OUTPUT_SUBMISSION_LEAD_NS);
        long earliestNs = saturatingAdd(nowNs, leadNs);
        if (outputPeriodNs <= 0L || outputPeriodNs == Long.MAX_VALUE ||
                leadNs == Long.MAX_VALUE || earliestNs == Long.MAX_VALUE)
            return invalid();
        return nextAlignedAtOrAfter(callbackFrameTimeNs, physicalAnchorNs,
                panelPeriodNs, outputPeriodNs, nowNs, minimumTargetExclusiveNs,
                earliestNs, THOR_DRIVER_LEAD_NS);
    }

    /**
     * Preserve the planner's conservative EGL queue reserve during retries.
     * The driver cutoff alone is not an admission deadline: Thor frame 1340
     * swapped 6.18ms before its target yet appeared one scan late. This guard
     * rejects insufficient lead; passing it is NOT proof of on-time scanout.
     */
    public static boolean appOwnedSubmissionHasQueueLead(
            long desiredPhysicalNs, long panelPeriodNs, long nowNs) {
        if (desiredPhysicalNs <= 0L || panelPeriodNs <= 0L || nowNs <= 0L ||
                nowNs >= desiredPhysicalNs) return false;
        long leadNs = saturatingAdd(panelPeriodNs, THOR_DIRECT_OUTPUT_SUBMISSION_LEAD_NS);
        return leadNs != Long.MAX_VALUE && desiredPhysicalNs - nowNs >= leadNs;
    }

    /**
     * Plans a one-scan Direct-WSI output only after its predecessor scan can
     * already own the completed image.
     *
     * <p>Thor's native 60-Hz mode needs the finished buffer in WSI across the
     * complete preceding scan.  The ordinary eight-millisecond Direct lead is
     * sufficient at 120 Hz, but r198 showed that it deterministically places
     * every 60-Hz-mode row on the following scan.  Merely pausing submissions
     * while old rows drain is not safe: VK_GOOGLE_display_timing may expose
     * the last row only after another present, and r199 proved that such a
     * pause deadlocks the presentation FIFO.  This planner keeps submissions
     * flowing while selecting a target at least one full measured scan plus
     * the unchanged Direct admission lead in the future.  Target, driver
     * cutoff, physical accounting, and no-catch-up behavior are unchanged.</p>
     */
    public static PhysicalPresentationDeadline
            nextAlignedOneScanOutputDirectAfterPredecessor(
            long callbackFrameTimeNs, long physicalAnchorNs,
            long panelPeriodNs, long nowNs,
            long minimumTargetExclusiveNs) {
        if (panelPeriodNs <= 0L) return invalid();
        long predecessorLeadNs = saturatingAdd(
                panelPeriodNs, THOR_DIRECT_OUTPUT_SUBMISSION_LEAD_NS);
        if (predecessorLeadNs == Long.MAX_VALUE || predecessorLeadNs <= 0L)
            return invalid();
        long earliestTargetNs = saturatingAdd(nowNs, predecessorLeadNs);
        if (earliestTargetNs == Long.MAX_VALUE || earliestTargetNs <= 0L)
            return invalid();
        return nextAlignedAtOrAfter(
                callbackFrameTimeNs, physicalAnchorNs,
                panelPeriodNs, panelPeriodNs, nowNs,
                minimumTargetExclusiveNs, earliestTargetNs,
                THOR_DRIVER_LEAD_NS);
    }

    /**
     * Plans a Direct endpoint on the physical panel lattice with the same
     * refresh-derived preparation lead as generated output.
     *
     * <p>Direct still targets an arbitrary panel scan rather than an output
     * divisor lattice. The extra scans are preparation margin only: the native
     * timed-release worker retains the completed image until the unchanged
     * bounded WSI window, so this cannot expose the image to the
     * preceding scan or authorize catch-up. Thor r45 proved that one scan can
     * leave less than the submission path needs before the immutable cutoff.</p>
     */
    public static PhysicalPresentationDeadline nextAlignedDirect(
            long callbackFrameTimeNs, long physicalAnchorNs,
            long panelPeriodNs, long nowNs, long minimumTargetExclusiveNs) {
        // A predecessor-token bracket needs the previous row's compositor
        // deadline to remain live, and r108 proved that the native worker must
        // still own one complete measured refresh plus the immutable handoff
        // reserve at enqueue. Derive the extra scan from the measured panel
        // period instead of hard-coding a nominal 120-Hz duration.
        long preparationLeadNs = refreshDerivedSubmissionLead(panelPeriodNs);
        if (preparationLeadNs == Long.MAX_VALUE || preparationLeadNs <= 0L)
            return invalid();
        long earliestTargetNs = saturatingAdd(
                nowNs, preparationLeadNs);
        if (earliestTargetNs == Long.MAX_VALUE || earliestTargetNs <= 0L)
            return invalid();
        return nextAlignedAtOrAfter(callbackFrameTimeNs, physicalAnchorNs,
                panelPeriodNs, panelPeriodNs, nowNs,
                minimumTargetExclusiveNs, earliestTargetNs,
                THOR_DRIVER_LEAD_NS);
    }

    static PhysicalPresentationDeadline nextAlignedOutput(
            long callbackFrameTimeNs, long physicalAnchorNs,
            long panelPeriodNs, int panelScansPerOutput,
            long nowNs, long minimumTargetExclusiveNs, long driverLeadNs) {
        if (panelScansPerOutput < 1) return invalid();
        long outputPeriodNs = saturatingMultiply(
                panelPeriodNs, panelScansPerOutput);
        if (outputPeriodNs == Long.MAX_VALUE || outputPeriodNs <= 0L)
            return invalid();
        long preparationLeadNs = refreshDerivedSubmissionLead(panelPeriodNs);
        if (preparationLeadNs == Long.MAX_VALUE || preparationLeadNs <= 0L)
            return invalid();
        long earliestOutputNs = saturatingAdd(nowNs, preparationLeadNs);
        if (earliestOutputNs == Long.MAX_VALUE || earliestOutputNs <= 0L)
            return invalid();
        // The physical r49 run returned 409 consecutive rows on this exact
        // driver/content slot.  A speculative extra content scan therefore
        // made every generated image one scan late in source-time even though
        // physical cadence itself remained uniform.  Keep preparation lead
        // and WSI release separate from content time: both driver and content
        // target the same independently modeled output-lattice scan.
        return nextAlignedAtOrAfter(
                callbackFrameTimeNs, physicalAnchorNs,
                panelPeriodNs, outputPeriodNs, nowNs,
                minimumTargetExclusiveNs, earliestOutputNs,
                driverLeadNs);
    }

    private static long refreshDerivedSubmissionLead(long panelPeriodNs) {
        if (panelPeriodNs <= 0L) return Long.MAX_VALUE;
        return saturatingAdd(THOR_OUTPUT_SUBMISSION_LEAD_NS, panelPeriodNs);
    }

    static PhysicalPresentationDeadline nextAligned(
            long callbackFrameTimeNs, long physicalAnchorNs,
            long panelPeriodNs, long nowNs, long minimumTargetExclusiveNs,
            long driverLeadNs) {
        return nextAlignedAtOrAfter(callbackFrameTimeNs, physicalAnchorNs,
                panelPeriodNs, panelPeriodNs, nowNs,
                minimumTargetExclusiveNs, 0L, driverLeadNs);
    }

    private static PhysicalPresentationDeadline nextAlignedAtOrAfter(
            long callbackFrameTimeNs, long physicalAnchorNs,
            long panelPeriodNs, long targetPeriodNs, long nowNs,
            long minimumTargetExclusiveNs, long minimumTargetInclusiveNs,
            long driverLeadNs) {
        if (callbackFrameTimeNs <= 0L || physicalAnchorNs <= 0L ||
                panelPeriodNs <= 0L || targetPeriodNs <= 0L || nowNs < 0L ||
                minimumTargetExclusiveNs < 0L || driverLeadNs < 0L ||
                driverLeadNs >= panelPeriodNs)
            return invalid();
        long afterCutoffNs = saturatingAdd(nowNs, driverLeadNs);
        if (afterCutoffNs == Long.MAX_VALUE) return invalid();
        long thresholdNs = Math.max(afterCutoffNs, minimumTargetExclusiveNs);
        if (minimumTargetExclusiveNs > 0L) {
            // The measured period is a long-baseline estimate and may move by
            // a few microseconds when a fresh physical row updates it.  A
            // target from the retuned lattice that is merely one nanosecond
            // newer can still be the same scan ordinal shifted forward, not a
            // new physical scan.  r242 hit that boundary immediately after
            // the first 30-scan estimate: the duplicate ordinal moved the
            // source playhead backwards and tore down an otherwise healthy
            // 60-to-120 epoch.  Require half a measured scan of separation so
            // only the nearest unambiguously newer scan can be selected.  If
            // recalibration makes that scan ambiguous, it is skipped once;
            // it is never retried or caught up.
            long distinctScanSeparationNs = Math.max(1L,
                    panelPeriodNs / 2L);
            long minimumDistinctTargetNs = saturatingAdd(
                    minimumTargetExclusiveNs, distinctScanSeparationNs);
            if (minimumDistinctTargetNs == Long.MAX_VALUE) return invalid();
            // thresholdNs is exclusive below; subtract one so an exact
            // half-scan separation remains admissible.
            thresholdNs = Math.max(thresholdNs,
                    minimumDistinctTargetNs - 1L);
        }
        if (minimumTargetInclusiveNs > 0L)
            thresholdNs = Math.max(thresholdNs,
                    minimumTargetInclusiveNs - 1L);
        if (thresholdNs == Long.MAX_VALUE) return invalid();
        ++thresholdNs;

        long targetNs;
        if (thresholdNs <= physicalAnchorNs) {
            targetNs = physicalAnchorNs;
        } else {
            long deltaNs = thresholdNs - physicalAnchorNs;
            long periods = deltaNs / targetPeriodNs;
            if (deltaNs % targetPeriodNs != 0L) ++periods;
            long advanceNs = saturatingMultiply(targetPeriodNs, periods);
            targetNs = saturatingAdd(physicalAnchorNs, advanceNs);
        }
        if (targetNs == Long.MAX_VALUE || targetNs <= nowNs ||
                targetNs <= minimumTargetExclusiveNs ||
                targetNs - driverLeadNs <= nowNs)
            return invalid();

        long firstAfterCallbackNs;
        if (callbackFrameTimeNs < physicalAnchorNs) {
            firstAfterCallbackNs = physicalAnchorNs;
        } else {
            long deltaNs = callbackFrameTimeNs - physicalAnchorNs;
            long periods = deltaNs / panelPeriodNs + 1L;
            firstAfterCallbackNs = saturatingAdd(physicalAnchorNs,
                    saturatingMultiply(panelPeriodNs, periods));
        }
        long skipped = firstAfterCallbackNs == Long.MAX_VALUE ||
                targetNs <= firstAfterCallbackNs ? 0L :
                (targetNs - firstAfterCallbackNs) / panelPeriodNs;
        if (skipped > Integer.MAX_VALUE) return invalid();
        return new PhysicalPresentationDeadline(targetNs,
                targetNs - driverLeadNs,
                targetNs - driverLeadNs, (int) skipped, 0);
    }

    static PhysicalPresentationDeadline next(
            long callbackFrameTimeNs, long panelPeriodNs, long nowNs,
            long driverLeadNs) {
        if (callbackFrameTimeNs <= 0L || panelPeriodNs <= 0L || nowNs < 0L ||
                driverLeadNs < 0L || driverLeadNs >= panelPeriodNs)
            return invalid();

        long targetNs = saturatingAdd(callbackFrameTimeNs, panelPeriodNs);
        if (targetNs == Long.MAX_VALUE) return invalid();

        int skipped = 0;
        long cutoffNs = targetNs - driverLeadNs;
        if (cutoffNs <= nowNs) {
            long lateNs = nowNs - cutoffNs;
            long extraScans = lateNs / panelPeriodNs + 1L;
            if (extraScans > Integer.MAX_VALUE) return invalid();
            long advanceNs = saturatingMultiply(panelPeriodNs, extraScans);
            targetNs = saturatingAdd(targetNs, advanceNs);
            if (targetNs == Long.MAX_VALUE) return invalid();
            skipped = (int) extraScans;
            cutoffNs = targetNs - driverLeadNs;
        }
        if (targetNs <= callbackFrameTimeNs || cutoffNs <= nowNs ||
                cutoffNs <= 0L)
            return invalid();
        return new PhysicalPresentationDeadline(
                targetNs, cutoffNs, cutoffNs, skipped, 0);
    }

    public boolean valid() {
        return contentPresentationTimeNs > 0L &&
                driverDesiredPresentTimeNs > 0L &&
                driverDesiredPresentTimeNs < contentPresentationTimeNs &&
                hardCompletionDeadlineNs > 0L &&
                hardCompletionDeadlineNs <= driverDesiredPresentTimeNs;
    }

    /** Exact physical time used for endpoint phase calculation. */
    public long contentPresentationTimeNs() {
        return contentPresentationTimeNs;
    }

    /** Proven earliest-display bound supplied to Vulkan presentation timing. */
    public long driverDesiredPresentTimeNs() {
        return driverDesiredPresentTimeNs;
    }

    /** Last safe completion/submission instant for the selected scan. */
    public long hardCompletionDeadlineNs() {
        return hardCompletionDeadlineNs;
    }

    /** Whole scans abandoned because their driver cutoff had already passed. */
    public int skippedPanelScans() { return skippedPanelScans; }

    /** Explicit physical scans between the driver slot and content visibility. */
    public int presentationPipelineScans() { return presentationPipelineScans; }

    private static PhysicalPresentationDeadline invalid() {
        return new PhysicalPresentationDeadline(0L, 0L, 0L, 0, 0);
    }

    private static long saturatingAdd(long left, long right) {
        if (right > 0L && left > Long.MAX_VALUE - right) return Long.MAX_VALUE;
        return left + right;
    }

    private static long saturatingMultiply(long value, long multiplier) {
        if (value <= 0L || multiplier <= 0L) return 0L;
        if (value > Long.MAX_VALUE / multiplier) return Long.MAX_VALUE;
        return value * multiplier;
    }
}
