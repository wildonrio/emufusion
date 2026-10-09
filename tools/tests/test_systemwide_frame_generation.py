import pathlib
import math
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


class SystemwideFrameGenerationTest(unittest.TestCase):
    def test_app_owned_direct_warmup_uses_a_positive_physical_divisor(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/"
            "DisplayFrameGenerator.java"
        )
        present = generator.split(
            "private void presentAppOwnedExternalBuffered(", 1
        )[1].split(
            "/** Submits exactly one EmuFusion-selected request", 1
        )[0]
        self.assertIn(
            "int physicalScansPerOutput = appOwnedPhysicalScansPerOutput();",
            present,
        )
        self.assertIn(
            "long physicalPanelPeriodNs = frameRate.panelPeriodNs();", present
        )
        self.assertEqual(present.count(
            "physicalScansPerOutput, physicalPanelPeriodNs"), 2)
        self.assertNotIn(
            "frameRate.panelScansPerOutput(), frameRate.panelPeriodNs()",
            present,
        )
        fallback = present.split(
            "private int appOwnedPhysicalScansPerOutput()", 1
        )[1]
        self.assertIn("frameRate.panelScansPerOutput()", fallback)
        self.assertIn("frameRate.presentationSourceHz()", fallback)
        self.assertIn("frameRate.panelHz()", fallback)
        self.assertIn("Math.round(ratio)", fallback)

    def test_app_owned_egl_uses_calibrated_lattice_and_safe_submission_lead(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/"
            "DisplayFrameGenerator.java"
        )
        planning = generator.split(
            "PhysicalPresentationDeadline deadline =", 1
        )[1].split("if (!deadline.valid())", 1)[0]
        app_owned = planning.split("appOwnedExternal ?", 1)[1].split(
            ") : externalClockAvailable ?", 1
        )[0]
        self.assertIn("appOwnedClockAvailable ?", app_owned)
        self.assertIn(
            "PhysicalPresentationDeadline.nextAlignedOutputDirect(", app_owned
        )
        self.assertIn("externalPhysicalClock.anchorNs()", app_owned)
        self.assertIn("externalPhysicalClock.planningPeriodNs()", app_owned)
        self.assertIn("externalLastPlannedPhysicalNs", app_owned)
        self.assertIn("externalRatePathActive ?", app_owned)
        self.assertIn("frameRate.panelScansPerOutput()", app_owned)
        self.assertIn("appOwnedPhysicalScansPerOutput()", app_owned)
        self.assertIn("PhysicalPresentationDeadline.next(", app_owned)

    def test_app_owned_direct_pause_reanchors_without_weakening_generated_path(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/"
            "DisplayFrameGenerator.java"
        )
        poll = generator.split(
            "private void pollAppOwnedPhysicalPresentations()", 1
        )[1].split("private boolean externalPathManuallyCertified", 1)[0]
        reanchor = poll.split(
            "if (!clockConsistent && !externalRatePathActive", 1
        )[1].split("if (!cadenceConsistent || !clockConsistent)", 1)[0]
        self.assertIn("!pending.request.isGenerated()", reanchor)
        self.assertIn(
            "event.actualPresentTimeNs > priorPhysicalActualNs", reanchor
        )
        self.assertIn(
            "externalPhysicalClock.nominalPeriodNs() ==", reanchor
        )
        self.assertIn(
            "externalPhysicalClock.beginPresentationEpoch();", reanchor
        )
        self.assertIn("externalPhysicalClock.record(", reanchor)
        self.assertIn(
            'Log.i(TAG, "App-owned Direct physical clock re-anchored"',
            reanchor,
        )

        recovery = generator.split(
            "private void maybeRecoverAppOwnedDirectPhysicalTiming()", 1
        )[1].split("private ", 1)[0]
        self.assertIn("externalTimingRejected", recovery)
        self.assertIn("externalRatePathActive ||", recovery)
        self.assertIn("externalRatePathPriming ||", recovery)
        self.assertIn("!appOwnedPhysicalPending.isEmpty()", recovery)
        self.assertIn("tracker.pendingCount() != 0", recovery)
        self.assertIn("externalPhysicalClock.available()", recovery)
        self.assertIn("externalPhysicalCadence.qualified(", recovery)
        self.assertLess(
            recovery.index("externalPhysicalCadence.qualified("),
            recovery.index("externalTimingRejected = false"),
        )
        self.assertIn("frameRate.resetPresentation();", recovery)
        self.assertIn("resetEndpointTimelineForSchedulerEpoch();", recovery)
        self.assertIn("refreshProofEvidencePresentationEpoch();", recovery)
        self.assertIn("resetHealthWindowAfterStreamChange();", recovery)
        self.assertIn(
            'Log.i(TAG, "App-owned Direct physical timing recovered"',
            recovery,
        )

    def test_external_generated_work_gets_the_next_safe_divisor_slot(self):
        deadline = self.read(
            "unified-android/src/com/thorium/lucent/video/"
            "PhysicalPresentationDeadline.java"
        )
        planner = deadline.split(
            "static PhysicalPresentationDeadline nextAlignedOutput(", 1
        )[1].split(
            "static PhysicalPresentationDeadline nextAligned(", 1
        )[0]
        self.assertIn("THOR_OUTPUT_SUBMISSION_LEAD_NS", planner)
        self.assertIn("refreshDerivedSubmissionLead(panelPeriodNs)", planner)
        self.assertIn(
            "saturatingAdd(THOR_OUTPUT_SUBMISSION_LEAD_NS, panelPeriodNs)",
            planner,
        )
        self.assertNotIn("long preparationScans = panelScansPerOutput;", planner)
        self.assertIn(
            "minimumTargetExclusiveNs, earliestOutputNs", planner
        )
        self.assertIn("callbackFrameTimeNs, physicalAnchorNs", planner)
        self.assertNotIn("driverSlot", planner)
        self.assertIn("presentationPipelineScans", deadline)
        self.assertIn("THOR_WSI_GENERATED_RELEASE_WINDOW_NS", deadline)
        self.assertIn("THOR_WSI_ENDPOINT_RELEASE_WINDOW_NS", deadline)
        self.assertIn(
            "public static PhysicalPresentationDeadline nextExternal(",
            deadline,
        )

        direct = deadline.split(
            "public static PhysicalPresentationDeadline nextAlignedOutputDirect(", 1
        )[1].split(
            "public static PhysicalPresentationDeadline nextAlignedDirect(", 1
        )[0]
        self.assertIn("THOR_DIRECT_OUTPUT_SUBMISSION_LEAD_NS", direct)
        self.assertIn("THOR_DIRECT_PREQUEUE_RESERVE_NS", deadline)
        self.assertIn(
            "THOR_WSI_GENERATED_RELEASE_WINDOW_NS + THOR_DRIVER_LEAD_NS +",
            deadline,
        )
        self.assertIn("panelScansPerOutput", direct)
        self.assertIn("minimumTargetExclusiveNs, earliestOutputNs", direct)
        self.assertNotIn("refreshDerivedSubmissionLead", direct)

        generator = self.read(
            "unified-android/src/com/thorium/preview/game/"
            "DisplayFrameGenerator.java"
        )
        planning = generator.split(
            "PhysicalPresentationDeadline deadline =", 1
        )[1].split("if (!deadline.valid())", 1)[0]
        self.assertIn("externalTransport != null ?", planning)
        self.assertIn("PhysicalPresentationDeadline.nextExternal(", planning)

    def test_external_physical_slot_slip_permanently_falls_back_to_direct(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        self.assertIn("private boolean externalTimingRejected;", generator)
        transition = generator.split(
            "// Backend certification is rate-path specific.", 1
        )[1].split("if (beginPriming || activateWarmPath || disablePath)", 1)[0]
        self.assertIn("qualificationProofEnabled", transition)
        self.assertIn("!externalTimingRejected", transition)
        poll = generator.split(
            "private void pollPhysicalPresentations()", 1
        )[1].split("private boolean externalPathManuallyCertified", 1)[0]
        self.assertIn(
            "commit.presentationEpoch == schedulerPresentationEpoch()", poll
        )
        reject = poll.split(
            "if (externalRatePathActive && currentRatePathEpoch &&", 1
        )[1].split("externalPhysicalScansPerOutput", 1)[0]
        self.assertIn("markExternalTimingRejected();", reject)
        self.assertIn("externalRatePathActive = false;", reject)
        self.assertIn("transport.setGeneratedRatePathActive(false);", reject)
        self.assertIn("frameRate.setGenerationAvailable(false);", reject)
        self.assertIn("invalidateBufferedPairForReprime(false);", reject)
        self.assertIn("commit.request.compositorExpectedPresentationTimeNs()", reject)
        self.assertIn("commit.request.compositorFrameTimelineDeadlineNs()", reject)
        self.assertIn('" latchNs=" + row.earliestPresentTimeNs', reject)
        self.assertIn('" enqueueWallNs=" + row.enqueueWallNs', reject)
        self.assertIn('" gpuWorkNs=" + row.gpuWorkNs', reject)

    def test_scheduler_epoch_reanchors_phase_without_forgetting_panel_period(self):
        clock = self.read(
            "unified-android/src/com/thorium/lucent/video/"
            "PhysicalPresentationClock.java"
        )
        self.assertIn("public void beginPresentationEpoch()", clock)
        reanchor = clock.split(
            "public void beginPresentationEpoch()", 1
        )[1].split("public void reset()", 1)[0]
        self.assertIn("anchorNs = 0L;", reanchor)
        self.assertIn("lastActualNs = 0L;", reanchor)
        self.assertIn("observedScans = 0L;", reanchor)
        self.assertNotIn("estimatedPeriodNs = 0L;", reanchor)
        self.assertNotIn("nominalPeriodNs = 0L;", reanchor)

        generator = self.read(
            "unified-android/src/com/thorium/preview/game/"
            "DisplayFrameGenerator.java"
        )
        epoch_change = generator.split(
            "if (externalPhysicalAccountingEpoch != eventEpoch)", 1
        )[1].split("externalPhysicalAccountingEpoch = eventEpoch;", 1)[0]
        self.assertIn(
            "externalPhysicalClock.beginPresentationEpoch();", epoch_change
        )
        self.assertNotIn("externalPhysicalClock.reset();", epoch_change)

    def test_shell_external_backend_cannot_generate_before_proof_is_armed(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        transition = generator.split(
            "// Backend certification is rate-path specific.", 1
        )[1].split(
            "if (beginPriming || activateWarmPath || disablePath)", 1
        )[0]
        self.assertLess(transition.index("boolean physicalAuthorityReady"),
                        transition.index("boolean supported"))
        authority = transition.split(
            "boolean physicalAuthorityReady", 1
        )[1].split("boolean supported", 1)[0]
        self.assertIn("physicalPresentationTracker.available()", authority)
        self.assertIn("externalPhysicalClockBootstrap.complete()", authority)
        supported = transition.split("boolean supported", 1)[1]
        self.assertLess(
            supported.index("physicalAuthorityReady"),
            supported.index("qualificationProofEnabled"),
        )
        self.assertLess(
            supported.index("qualificationProofEnabled"),
            supported.index("!externalTimingRejected"),
        )

    def test_external_vulkan_path_polls_proof_on_shared_callback_cadence(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        callback = generator.split(
            "++bufferedPresentationCallbackCount;", 1
        )[1].split("// Backend certification is rate-path specific", 1)[0]
        self.assertIn("externalTransport != null", callback)
        self.assertIn(
            "bufferedPresentationCallbackCount % HEALTH_INTERVAL == 0L",
            callback,
        )
        self.assertIn("refreshQualificationProofState();", callback)

    def test_external_physical_lattice_uses_long_baseline_actual_clock(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        poll = generator.split(
            "private void pollPhysicalPresentations()", 1
        )[1].split("private boolean externalPathManuallyCertified", 1)[0]
        self.assertIn("externalPhysicalClock.record(", poll)
        self.assertIn("boolean physicalEpochChanged", poll)
        self.assertIn("externalPhysicalClock.beginPresentationEpoch();", poll)
        self.assertIn("externalPhysicalClock.reset();", poll)
        self.assertLess(
            poll.index("externalPhysicalClock.beginPresentationEpoch();"),
            poll.index("externalPhysicalClock.record("),
        )
        self.assertGreater(
            poll.index("externalPhysicalClock.reset();"),
            poll.index("externalPhysicalClock.record("),
        )
        self.assertIn("commit.actualPresentTimeNs", poll)
        self.assertIn("commit.refreshDurationNs", poll)
        self.assertIn("externalPhysicalClockBootstrap.calibrationRow(", poll)
        self.assertIn("recordCalibrationPresent(", poll)
        calibration = poll.split(
            "externalPhysicalClockBootstrap.calibrationRow(", 1
        )[1].split("continue;", 1)[0]
        self.assertIn("externalPhysicalCadence.recordPresented(", calibration)
        self.assertIn("++presents;", calibration)
        self.assertIn("externalPhysicalClockBootstrap.ready(", poll)
        self.assertIn("externalPhysicalClockBootstrap.commit(", poll)
        self.assertLess(
            poll.index("externalPhysicalClockBootstrap.calibrationRow("),
            poll.index("externalPresentationEvidence.record(commit"),
        )
        epoch_anchor = poll.split(
            "if (physicalEpochChanged) {", 1
        )[1].split("long timingMissesBefore", 1)[0]
        self.assertIn("if (commit.generated)", epoch_anchor)
        self.assertIn("externalPresentationEvidence.beginEpoch(", epoch_anchor)
        self.assertIn("externalGeneratedContentEvidence.beginEpoch(", epoch_anchor)
        # aa09: a new phase is not permission to reuse an already submitted
        # scan. Actual-method coverage lives in test_external_physical_slot_reservation.
        self.assertNotRegex(epoch_anchor, r"externalLastPlannedPhysicalNs\s*=")
        self.assertNotRegex(epoch_anchor, r"externalLastSubmittedCompositorExpectedNs\s*=")
        self.assertIn("externalPhysicalCadence.recordPresented(", epoch_anchor)
        self.assertIn(
            "externalPresentationLedger.pendingCount()", epoch_anchor
        )
        self.assertIn("externalPhysicalAnchorTailRows", poll)
        tail = poll.split(
            "if (externalPhysicalAnchorTailRows > 0) {", 1
        )[1].split("long timingMissesBefore", 1)[0]
        self.assertIn("--externalPhysicalAnchorTailRows", tail)
        self.assertIn(
            "externalDirectOutputPhaseAnchorNs =\n"
            "                            commit.actualPresentTimeNs",
            tail,
        )
        self.assertIn("externalPhysicalCadence.reset()", tail)
        self.assertIn("++presents", tail)
        self.assertIn("continue;", tail)
        self.assertNotIn("externalPresentationEvidence.record(commit", tail)
        self.assertIn("++presents;", epoch_anchor)
        self.assertIn("continue;", epoch_anchor)
        self.assertNotIn("externalPresentationEvidence.record(commit", epoch_anchor)
        self.assertNotRegex(poll, r"externalLastPlannedPhysicalNs\s*=")
        self.assertNotRegex(poll, r"externalLastSubmittedCompositorExpectedNs\s*=")
        self.assertIn("frameRate.resetPresentation();", poll)
        self.assertIn("resetEndpointTimelineForSchedulerEpoch();", poll)
        planner = generator.split(
            "PhysicalPresentationDeadline deadline =", 1
        )[1].split("if (!deadline.valid())", 1)[0]
        self.assertIn("externalClockAvailable ?", planner)
        self.assertIn(
            "externalPhysicalClock.available()", generator.split(
                "boolean externalClockAvailable", 1
            )[1].split("PhysicalPresentationDeadline deadline =", 1)[0]
        )
        self.assertIn("externalPhysicalClock.anchorNs()", planner)
        self.assertIn("externalPhysicalClock.planningPeriodNs()", planner)
        self.assertIn("externalRatePathActive ?", planner)
        self.assertIn("PhysicalPresentationDeadline.nextAlignedOutput(", planner)
        self.assertIn("nextAlignedOutputDirect(", planner)
        self.assertIn(
            "nextAlignedOneScanOutputDirectAfterPredecessor(", planner
        )
        transition = generator.split(
            'Log.i(TAG, "External rate-path transition"', 1
        )[1].split(
            "// Endpoint buffers reach an external ImageReader", 1
        )[0]
        self.assertIn("if (beginOutputPriming)", transition)
        self.assertIn("privatePipelineWarm", transition)
        self.assertIn("frameRate.setGenerationAvailable(true)", transition)
        self.assertIn("externalRatePathOutputPriming = true", transition)
        self.assertNotIn("externalRatePathActive = true", transition)
        self.assertIn("externalTransport.requiresCompositorFrameTimeline()", planner)
        self.assertNotIn("PhysicalPresentationDeadline.nextAlignedDirect(", planner)
        self.assertGreaterEqual(planner.count("nextAlignedOutputDirect("), 2)
        no_clock = planner.split(
            ") :\n                    (externalTransport != null ?", 1
        )[1]
        self.assertIn("PhysicalPresentationDeadline.nextExternal(", no_clock)
        self.assertNotIn("nextAlignedOutputDirect(", no_clock)
        direct_fallback = planner.split(
            "// Endpoint-only Direct has no private inference", 1
        )[1]
        self.assertRegex(direct_fallback,
                         r"externalPhysicalClock\.planningPeriodNs\(\),\s+1,")
        self.assertIn("frameRate.panelScansPerOutput()", planner)
        self.assertIn("externalDirectOutputPhaseAnchorNs", planner)
        self.assertIn(
            "externalDirectOutputPhaseAnchorNs > 0L ?",
            planner,
        )
        self.assertIn(
            "frameRate.panelScansPerOutput() : 1",
            planner,
        )
        self.assertIn(
            "externalDirectOutputPhaseAnchorNs =\n"
            "                            commit.actualPresentTimeNs",
            poll,
        )
        report = generator.split(
            'Log.i(TAG, "App swap cadence"', 1
        )[1].split("publishReportedFrameRate", 1)[0]
        self.assertIn("externalSlotErrorSignedMinNs", report)
        self.assertIn("externalSlotErrorSignedMaxNs", report)
        self.assertIn("externalSlotErrorSignedLastNs", report)
        self.assertIn("externalPresentMarginMinNs", report)
        self.assertIn("externalPresentMarginP05Ns", report)
        self.assertIn("externalPresentMarginP50Ns", report)
        self.assertIn("externalPresentMarginP95Ns", report)
        self.assertIn("externalPresentMarginMaxNs", report)
        self.assertIn("externalPresentMarginLastNs", report)
        self.assertIn("externalTimingPipelineScans", report)
        self.assertIn("externalLateSlotMarginMinNs", report)
        self.assertIn("externalLateSlotMarginMaxNs", report)
        self.assertIn("externalPhysicalClockCalibrated", report)
        self.assertIn("externalPhysicalClockCalibrationPresents", report)
        bootstrap = self.read(
            "unified-android/src/com/thorium/lucent/video/"
            "ExternalPhysicalClockBootstrap.java"
        )
        self.assertIn("presentationEpoch == calibrationPresentationEpoch",
                      bootstrap)
        self.assertIn("excludedTailPending=", poll)

    def test_external_transport_stays_visible_direct_until_exact_rate_is_authorized(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        guard = generator.split(
            "++bufferedPresentationCallbackCount;", 1
        )[1].split("long underrunsBefore", 1)[0]
        self.assertIn("externalTransport != null", guard)
        self.assertIn("frameRate.candidateGeneratedOutputFps()", guard)
        self.assertIn("frameRate.candidateGeneratedSourceFps()", guard)
        self.assertIn(
            "frameRate.candidateGeneratedPanelScansPerOutput()", guard
        )
        self.assertIn("frameRate.panelClockMeasured()", guard)
        self.assertIn("externalPhysicalClockBootstrap.complete()", guard)
        self.assertIn("externalTransport.supportsRatePath(", guard)
        self.assertIn("candidateSource, candidateOutput", guard)
        self.assertIn("candidateOutput", guard)
        self.assertIn("boolean beginPriming = supported", guard)
        self.assertIn("boolean beginOutputPriming = supported", guard)
        self.assertIn("boolean disablePath = !supported", guard)
        self.assertIn(
            "externalTransport.privateGenerationPipelineWarm()", guard
        )
        self.assertIn(
            "externalTransport.setGeneratedRatePathActive(true)", guard
        )
        self.assertIn("if (beginPriming)", guard)
        self.assertIn("externalRatePathPriming = true", guard)
        self.assertIn("if (beginOutputPriming)", guard)
        self.assertIn("externalRatePathOutputPriming = true", guard)
        self.assertIn(
            "frameRate.setGenerationAvailable(true)", guard
        )
        self.assertIn("invalidateBufferedPairForReprime(", guard)
        self.assertLess(
            guard.index("externalTransport.setGeneratedRatePathActive(true)"),
            guard.index("frameRate.setGenerationAvailable(true)"),
        )
        priming = guard.split("if (beginPriming)", 1)[1].split(
            "if (beginOutputPriming)", 1
        )[0]
        self.assertNotIn("invalidateBufferedPairForReprime", priming)
        self.assertNotIn("if (!supported) return;", guard)
        self.assertIn("activeLeftSequence <= 0L", guard)
        self.assertIn(
            "activeRightSequence != activeLeftSequence + 1L", guard
        )
        self.assertIn("!externalTransport.hasAdjacentPair(", guard)
        self.assertIn("externalTransport.hasPreparedLookahead(", guard)
        self.assertIn("!activePairReady", guard)
        self.assertIn("GenerationReadiness.PENDING", guard)
        self.assertIn("externalTransport.visibleSubmissionReady()", guard)
        first_output = guard.split(
            "if (externalRatePathOutputPriming)", 1
        )[1].split(
            "// A newly activated generated path", 1
        )[0]
        self.assertIn("primeFirstExternalGeneratedOutput()", first_output)
        self.assertIn("externalRatePathActive = true", first_output)
        self.assertIn(
            "externalAppOwnedActivationFirstSwapPending =", first_output
        )
        self.assertIn("motionEstimateReady = true", first_output)
        self.assertIn("activePairReady = true", first_output)
        self.assertIn("!appOwnedPhysicalPending.isEmpty()", first_output)
        self.assertIn(
            "physicalPresentationTracker.pendingCount() != 0", first_output
        )
        self.assertLess(
            first_output.index("primeFirstExternalGeneratedOutput()"),
            first_output.index("externalRatePathActive = true"),
        )
        self.assertLess(
            first_output.index("physicalPresentationTracker.pendingCount() != 0"),
            first_output.index("externalRatePathActive = true"),
        )
        first_swap_planner = generator.split(
            "PhysicalPresentationDeadline deadline = appOwnedExternal ?", 1
        )[1].split("CompositorFrameTimeline.Selection", 1)[0]
        self.assertNotIn(
            "externalAppOwnedActivationFirstSwapPending", first_swap_planner
        )
        self.assertIn(
            "nextAlignedAppOwnedGenerated(",
            first_swap_planner,
        )
        self.assertLess(
            first_swap_planner.index(
                "nextAlignedAppOwnedGenerated("
            ),
            first_swap_planner.index("nextAlignedOutputDirect("),
        )
        prime = generator.split(
            "private boolean primeFirstExternalGeneratedOutput()", 1
        )[1].split(
            "private FrameGenerationPreparationRequest ", 1
        )[0]
        self.assertIn("hasPreparedLookahead(activeRightSequence)", prime)
        self.assertIn(
            "AdaptiveFrameRateController.exactMidpointTimestampNs(", prime
        )
        self.assertIn("submitExternalGeneratedPreparation(request)", prime)
        self.assertIn("PreparationReadiness.READY", prime)
        self.assertIn("GenerationReadiness.READY", prime)
        self.assertIn("invalidateBufferedPairForReprime();", prime)
        self.assertIn("External output-prime pair rejected", prime)
        bootstrap_admission = guard.split(
            "!externalPhysicalClockBootstrap.complete()", 1
        )[1].split("long underrunsBefore", 1)[0]
        self.assertIn("!externalTransport.visibleSubmissionReady()", bootstrap_admission)
        self.assertIn("return;", guard)

        physical_poll = generator.split(
            "private void pollPhysicalPresentations()", 1
        )[1].split("private boolean externalPathManuallyCertified", 1)[0]
        stale_reanchor = physical_poll.split(
            "boolean endedDirectEpoch", 1
        )[1].split("externalPhysicalCadence.recordPresented", 1)[0]
        self.assertIn("!externalRatePathActive", stale_reanchor)
        self.assertIn("!commit.generated", stale_reanchor)
        self.assertIn(
            "commit.presentationEpoch !=\n"
            "                                    schedulerPresentationEpoch()",
            stale_reanchor,
        )
        self.assertIn("externalPhysicalClock.reset();", stale_reanchor)
        self.assertIn("External stale Direct clock re-anchored", stale_reanchor)
        do_frame = generator.split(
            "@Override public void doFrame(long frameTimeNanos)", 1
        )[1].split("private void initializeEgl()", 1)[0]
        self.assertLess(
            do_frame.index("!externalTransport.hasAdjacentPair("),
            do_frame.index("frameRate.selectBufferedPresentation("),
        )
        endpoint = generator.split(
            "private void acceptPresentationEndpoint(", 1
        )[1].split("private void publishExternalEndpoint(", 1)[0]
        self.assertIn(
            "if (externalTransport != null)\n"
            "            publishExternalEndpoint", endpoint
        )
        self.assertNotIn("externalRatePathActive)\n"
                         "            publishExternalEndpoint", endpoint)

        external = self.read(
            "unified-android/src/com/thorium/preview/game/"
            "ExternalFrameGenerationTransport.java"
        )
        self.assertIn("supportsEndpointOnlyPresentation()", external)
        self.assertIn("return false;", external)
        self.assertIn("physical earliest-present time is invalid", external)
        self.assertIn("PhysicalPresentMargin.normalize(", external)
        margin = self.read(
            "unified-android/src/com/thorium/lucent/video/"
            "PhysicalPresentMargin.java"
        )
        self.assertIn("if (rawSignedNs >= -refreshDurationNs) return 0L;",
                      margin)
        self.assertIn(
            "physical present margin exceeds bounded unsigned-wrap range",
            margin
        )
        self.assertIn("Long.toUnsignedString(rawSignedNs)", margin)
        initialize = generator.split("private void initialize()", 1)[1].split(
            "private void initializeEgl()", 1
        )[0]
        self.assertIn("!externalTransport.supportsEndpointOnlyPresentation()",
                      initialize)
        self.assertIn("frameRate.setGenerationAvailable(false)", initialize)
        self.assertIn(
            "frameRate.setExactDoubleEndpointLatticeRequired(true)", initialize
        )
        present = generator.split("private void presentExternalBuffered(", 1)[1]
        self.assertIn("request.isGenerated() && !externalRatePathActive", present)
        self.assertIn('externalRatePathActive ?\n'
                      '                frameRate.panelScansPerOutput() : 1', present)
        self.assertIn(
            "result == ExternalFrameGenerationTransport.EnqueueResult.NOT_READY",
            present,
        )
        deferred = present.split(
            "result == ExternalFrameGenerationTransport.EnqueueResult.DEFERRED", 1
        )[1].split(
            "result == ExternalFrameGenerationTransport.EnqueueResult.NOT_READY", 1
        )[0]
        self.assertIn("frameRate.deferBufferedPresentationSlot()", deferred)
        self.assertNotIn("++bufferedSyntheticNotReadyCount", deferred)
        self.assertNotIn("frameRate.dropBufferedPresentationSlot()", deferred)
        not_ready = present.split(
            "result == ExternalFrameGenerationTransport.EnqueueResult.NOT_READY", 1
        )[1].split(
            "result != ExternalFrameGenerationTransport.EnqueueResult.SUBMITTED", 1
        )[0]
        self.assertIn("++bufferedSyntheticNotReadyCount", not_ready)
        self.assertIn("frameRate.dropBufferedPresentationSlot()", not_ready)
        self.assertNotIn("invalidateBufferedPairForReprime(false)", not_ready)
        self.assertIn("return;", not_ready)
        self.assertNotIn(
            "external presentation missed its one physical deadline", present
        )

    def test_rife_cold_model_cost_is_paid_before_visible_surface_ownership(self):
        transport = self.read(
            "unified-android/qualification-src/com/thorium/preview/game/"
            "RifePresentationTransport.java"
        )
        constructor = transport.split(
            "private RifePresentationTransport(", 1
        )[1].split("@Override public Surface endpointSurface()", 1)[0]
        warm = constructor.index(
            "warmPresentationModelBeforeSurface(analysisWidth, analysisHeight)"
        )
        reader = constructor.index("ImageReader.newInstance(")
        private_output = constructor.index("bridge.createPrivateOutputTransport")
        self.assertLess(warm, reader)
        self.assertLess(reader, private_output)
        self.assertIn("bridge.interpolate(", constructor)
        self.assertIn("timing.processV4CompositeNs <= 0L", constructor)
        self.assertNotIn("bridge.createPresentationSurface", constructor)
        self.assertIn('privateOutput.getBoolean("appOwnedPresentation")',
                      constructor)
        self.assertIn('privateOutput.getBoolean("visibleSurface")', constructor)
        self.assertIn('privateOutput.getBoolean("vulkanSwapchain")', constructor)
        self.assertIn('privateOutput.getBoolean("surfaceControl")', constructor)
        self.assertIn('privateOutput.getBoolean("zeroWaitReadyPoll")', constructor)
        self.assertIn('privateOutput.getBoolean("eglFenceRecycle")', constructor)

    def test_rife_startup_proves_surface_drain_before_live_submission(self):
        transport = self.read(
            "unified-android/qualification-src/com/thorium/preview/game/"
            "RifePresentationTransport.java"
        )
        constructor = transport.split(
            "private RifePresentationTransport(", 1
        )[1].split("private void advanceStartupSurfaceDrainProbe()", 1)[0]
        visible = transport.split(
            "@Override public boolean visibleSubmissionReady()", 1
        )[1].split("private void validatePreparationIdentity", 1)[0]
        poll = transport.split(
            "@Override public List<PresentationEvent> poll()", 1
        )[1].split("private SubmittedPresentation findSubmitted", 1)[0]
        # The private-output arm has no visible backend Surface or swapchain to
        # drain. Its entire startup gate is the fixed AHardwareBuffer pool and
        # zero-wait completion/recycle contract.
        self.assertIn("startupSurfaceProbeTarget = 0;", constructor)
        self.assertIn("startupSurfaceProbeComplete = true;", constructor)
        self.assertNotIn("advanceStartupSurfaceDrainProbe();", constructor)
        self.assertIn("return appOwnedPresentation ||", visible)
        app_poll = poll.split("if (appOwnedPresentation)", 1)[1].split(
            "if (!startupSurfaceProbeComplete)", 1
        )[0]
        self.assertIn("bridge.pollBoundHardwareBufferRifeOutputs();", app_poll)
        self.assertIn("return java.util.Collections.emptyList();", app_poll)

    def test_rife_finished_image_is_released_to_wsi_only_inside_bounded_window(self):
        request = self.read(
            "unified-android/src/com/thorium/lucent/video/"
            "FrameGenerationPresentationRequest.java"
        )
        preparation = self.read(
            "unified-android/src/com/thorium/lucent/video/"
            "FrameGenerationPreparationRequest.java"
        )
        transport_contract = self.read(
            "unified-android/src/com/thorium/preview/game/"
            "ExternalFrameGenerationTransport.java"
        )
        transport = self.read(
            "unified-android/qualification-src/com/thorium/preview/game/"
            "RifePresentationTransport.java"
        )
        native = self.read(
            "experiments/rife-ncnn-vulkan-android/android-benchmark/"
            "app/src/main/cpp/rife_benchmark_jni.cpp"
        )
        self.assertIn("THOR_WSI_GENERATED_RELEASE_WINDOW_NS", request)
        self.assertIn("THOR_WSI_ENDPOINT_RELEASE_WINDOW_NS", request)
        self.assertIn("queueReleaseNotBeforeNs", request)
        self.assertIn(
            "withReleaseAfterImmediatePriorPhysicalScan", request
        )
        self.assertIn(
            "releaseNotBeforeNs = priorActualPresentTimeNs + 1L", request
        )
        self.assertIn(
            "absoluteDifference(targetDeltaNs, panelPeriodNs) > toleranceNs",
            request,
        )
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/"
            "DisplayFrameGenerator.java"
        )
        self.assertIn("frameRate.panelScansPerOutput() == 1", generator)
        self.assertIn("externalPhysicalClock.lastActualNs()", generator)
        self.assertIn(
            "withReleaseAfterImmediatePriorPhysicalScan(", generator
        )
        self.assertIn(
            "nextAlignedOneScanOutputDirectAfterPredecessor(", generator
        )
        self.assertIn(
            "withReleaseAfterModeAlignedPredecessorScan(", generator
        )
        self.assertNotIn(
            "externalPhysicalAnchorTailRows > 0)\n                return;",
            generator,
        )
        self.assertIn(
            "excludes every physical-presentation deadline", preparation
        )
        self.assertIn(
            "boolean matches(FrameGenerationPresentationRequest", preparation
        )
        self.assertIn("Starts private GPU preparation", transport_contract)
        self.assertIn("PreparationReadiness", transport_contract)
        self.assertIn(
            "scheduleHardwareBufferRifePresentationRelease(", transport
        )
        self.assertIn("pollHardwareBufferRifePresentationRelease()", transport)
        self.assertNotIn("owner.postDelayed(nativeReleaseCheck", transport)
        bridge = self.read(
            "experiments/rife-ncnn-vulkan-android/android-benchmark/"
            "app/src/main/java/com/emufusion/rifebenchmark/NativeRifeBridge.java"
        )
        self.assertIn("releaseWindowNs == 4_500_000L", bridge)
        self.assertIn("releaseWindowNs == 5_000_000L", bridge)
        self.assertIn("immediateAfterPriorPhysicalScan", bridge)
        self.assertIn("release_window_ns == 4'500'000", native)
        self.assertIn("release_window_ns == 5'000'000", native)
        self.assertIn("immediate_after_prior_physical_scan", native)
        self.assertIn("immediate_expected_window_ns", native)
        self.assertIn("immediate_window_error_ns", native)
        self.assertIn(
            "(!immediate_release && schedule_now_ns >= not_before_ns)",
            native,
        )
        self.assertIn('" untilNotBeforeNs="', native)
        self.assertIn("kTimedReleaseSpinLeadNs = 5'000'000", native)
        self.assertIn("setpriority(PRIO_PROCESS, 0, kTimedReleaseNice)", native)
        self.assertIn("sched_setaffinity(", native)
        release_worker = native.split(
            "void* timed_release_worker_main", 1
        )[1].split("bool start_timed_release_worker", 1)[0]
        release_tail = release_worker.split(
            "state_lock.unlock();", 1
        )[1].split("state_lock.lock();", 1)[0]
        self.assertIn("signal_pending_surface_present_locked(", release_tail)
        self.assertNotIn("context_lock(context->mutex)", release_tail)
        self.assertIn("pthread_t timed_release_thread", native)
        self.assertIn("stop_timed_release_worker(context);", native)
        self.assertNotIn("LockSupport.parkNanos", transport)
        self.assertLess(
            native.index("Do not expose this finished image to FIFO yet"),
            native.index("nativeScheduleHardwareBufferRifePresentationRelease"),
        )
        hardware = native.split(
            "nativeEnqueueHardwareBufferRifePresentation", 1
        )[1].split("nativeScheduleHardwareBufferRifePresentationRelease", 1)[0]
        self.assertNotIn("vkQueuePresentKHR", hardware)
        release = native.split("queue_pending_surface_present_locked", 1)[1]
        self.assertIn("vkQueuePresentKHR", release)
        self.assertIn("pending_present_queued = true", release)
        self.assertIn("VkQueue presentation_queue = VK_NULL_HANDLE", native)
        self.assertIn("VkQueue release_queue = VK_NULL_HANDLE", native)
        self.assertIn("pending_release_gate_semaphore", native)
        self.assertIn("signal_pending_surface_present_locked", native)
        self.assertIn("struct DirectPresentationLifecycle", native)
        self.assertIn("pending_release_present_id", native)
        self.assertIn("gate_signal_start_ns", native)
        self.assertIn("gate_signal_end_ns", native)
        self.assertIn("direct presentation lifecycle payload is invalid", native)
        self.assertIn("new long[15]", bridge)
        self.assertIn("Native direct presentation lifecycle is invalid", bridge)
        self.assertIn("RIFE direct presentation lifecycle", transport)
        self.assertIn("info.compute_queue_count() < 3", native)
        self.assertIn('"dedicatedPresentationQueue\\\":true', native)
        self.assertIn('"dedicatedReleaseQueue\\\":true', native)
        self.assertIn('"prequeuedPresentGate\\\":true', native)
        self.assertIn("wait_release_queue_idle", native)
        self.assertIn("wait_presentation_queue_idle", native)
        self.assertIn("wait_compute_queue_idle", native)

    def test_rife_product_transport_returns_private_images_to_app_owned_egl(self):
        transport = self.read(
            "unified-android/qualification-src/com/thorium/preview/game/"
            "RifePresentationTransport.java"
        )
        bridge = self.read(
            "experiments/rife-ncnn-vulkan-android/android-benchmark/"
            "app/src/main/java/com/emufusion/rifebenchmark/NativeRifeBridge.java"
        )
        native = self.read(
            "experiments/rife-ncnn-vulkan-android/android-benchmark/"
            "app/src/main/cpp/rife_benchmark_jni.cpp"
        )
        constructor = transport.split(
            "private RifePresentationTransport(", 1
        )[1].split("@Override public Surface endpointSurface()", 1)[0]
        self.assertIn("bridge.createPrivateOutputTransport(", constructor)
        self.assertNotIn("bridge.createPresentationSurface(", constructor)
        self.assertIn("appOwnedPresentation = true;", constructor)
        self.assertIn("bindPreparedHardwareBufferRifeOutput", bridge)
        self.assertIn("releaseBoundHardwareBufferRifeOutput", bridge)
        self.assertIn("pollBoundHardwareBufferRifeOutputs", bridge)
        enqueue = transport.split(
            "@Override public EnqueueResult enqueue(", 1
        )[1].split("private void scheduleNativeRelease", 1)[0]
        self.assertIn("if (appOwnedPresentation)", enqueue)
        self.assertIn(
            "app-owned RIFE output cannot submit a visible backend presentation",
            enqueue,
        )
        private_create = native.split(
            "nativeCreatePrivateOutputTransport(", 1
        )[1].split("extern \"C\" JNIEXPORT", 1)[0]
        self.assertIn("app_owned_output_mode = true", private_create)
        self.assertIn('"visibleSurface\\\":false', private_create)
        self.assertIn('"vulkanSwapchain\\\":false', private_create)
        self.assertIn('"surfaceControl\\\":false', private_create)
        self.assertNotIn("vkQueuePresentKHR", private_create)

    def test_app_owned_rife_swap_accounting_and_teardown_are_fail_closed(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/"
            "DisplayFrameGenerator.java"
        )
        native = self.read(
            "experiments/rife-ncnn-vulkan-android/android-benchmark/"
            "app/src/main/cpp/rife_benchmark_jni.cpp"
        )
        start = generator.index("private void presentAppOwnedExternalBuffered(")
        end = generator.index("    private void presentExternalBuffered(", start)
        present = generator[start:end]
        bind = present.index("transport.bindAppOwnedOutput(")
        prepare = present.index("physicalPresentationTracker.prepareFrame()")
        swap = present.index("EGL14.eglSwapBuffers(eglDisplay, eglSurface)")
        tracker_commit = present.index(
            "physicalPresentationTracker.commitPrepared("
        )
        pending = present.index("appOwnedPhysicalPending.addLast(")
        submitted = present.index("++appOwnedExternalSubmittedCount;")
        first_swap_consumed = present.index(
            "externalAppOwnedActivationFirstSwapPending = false;"
        )
        controller_commit = present.index(
            "frameRate.commitBufferedPresentation(true)"
        )
        self.assertLess(bind, prepare)
        self.assertLess(prepare, swap)
        self.assertLess(swap, tracker_commit)
        self.assertLess(tracker_commit, pending)
        self.assertLess(pending, submitted)
        self.assertLess(submitted, first_swap_consumed)
        self.assertLess(first_swap_consumed, controller_commit)
        self.assertLess(submitted, controller_commit)
        finally_block = present.split("} finally {", 1)[1].split(
            "if (!outputFrameRateReassertedAfterSwap)", 1
        )[0]
        self.assertIn("physicalPresentationTracker.cancelPrepared()",
                      finally_block)
        self.assertIn(
            "transport.releaseAppOwnedOutput(generatedOutput, swapSucceeded)",
            finally_block,
        )

        dispatcher = generator.split(
            "private void pollPhysicalPresentations()", 1
        )[1].split("private void pollAppOwnedPhysicalPresentations()", 1)[0]
        self.assertIn("transport.poll()", dispatcher)
        self.assertIn("!backendEvents.isEmpty()", dispatcher)
        self.assertIn("transport.pendingPhysicalPresentationCount() != 0",
                      dispatcher)
        physical = generator.split(
            "private void pollAppOwnedPhysicalPresentations()", 1
        )[1].split("private boolean externalPathManuallyCertified()", 1)[0]
        self.assertIn("pending.frameId != event.frameId", physical)
        self.assertIn("Event.Kind.UNAVAILABLE", physical)
        self.assertIn("recordUnavailable", physical)
        self.assertIn("restartAppOwnedExternalTimingWindow(", physical)
        self.assertIn(
            "App-owned physical timestamp history expired; ", physical
        )
        unavailable_branch = physical.split(
            "Event.Kind.UNAVAILABLE) {", 1
        )[1].split(
            "if (event.kind != PhysicalPresentationTracker.Event.Kind.PRESENTED)",
            1,
        )[0]
        self.assertIn("restartAppOwnedExternalTimingWindow(",
                      unavailable_branch)
        self.assertIn("continue;", unavailable_branch)
        self.assertNotIn("externalRatePathActive = false",
                         unavailable_branch)
        self.assertNotIn("setGenerationAvailable(false)",
                         unavailable_branch)
        self.assertNotIn("invalidateBufferedPairForReprime",
                         unavailable_branch)
        rejected = physical.index(
            "event.kind != PhysicalPresentationTracker.Event.Kind.PRESENTED"
        )
        endpoint_count = physical.index(
            "++appOwnedExternalPhysicalEndpointCount"
        )
        generated_count = physical.index(
            "++appOwnedExternalPhysicalGeneratedCount"
        )
        evidence = physical.index("appOwnedExternalPresentationEvidence.record(")
        self.assertLess(rejected, endpoint_count)
        self.assertLess(rejected, generated_count)
        self.assertLess(endpoint_count, evidence)
        self.assertLess(generated_count, evidence)
        self.assertIn("recordAppOwnedGenerated(", physical)
        # A physical one-scan miss must be attributable without another
        # device run.  Preserve the immutable request times and the complete
        # app-owned submission/swap interval in the fail-closed diagnostic.
        for field in (
            "driverDesiredNs=", "hardDeadlineNs=", "actualMinusDesiredNs=",
            "submissionStartedNs=", "swapStartedNs=", "swapCompletedNs=",
            "submissionLeadToDesiredNs=", "swapLeadToDesiredNs=",
            "completionReserveNs=", "resultAgeNs=", "targetSourceNs=",
            "phaseBits=",
        ):
            self.assertIn(field, physical)
        pending_row = generator.split(
            "private static final class AppOwnedPhysicalPending", 1
        )[1].split("private static void checkGl", 1)[0]
        self.assertIn("final long submissionStartedNs;", pending_row)
        self.assertIn("final long swapStartedNs;", pending_row)
        self.assertIn("final long swapCompletedNs;", pending_row)
        self.assertIn("swapStartedNs < submissionStartedNs", pending_row)
        self.assertIn("swapCompletedNs < swapStartedNs", pending_row)

        release = generator.split("private void releaseGl()", 1)[1].split(
            "private static void bindTexture", 1
        )[0]
        make_current = release.index(
            "EGL14.eglMakeCurrent(eglDisplay, workingSurface, workingSurface, eglContext)"
        )
        private_close = release.index("transport.close();")
        tracker_close = release.index("physicalPresentationTracker.close();")
        texture_delete = release.index(
            "new int[]{externalGeneratedTexture}"
        )
        no_context = release.index(
            "EGL14.eglMakeCurrent(eglDisplay, EGL14.EGL_NO_SURFACE"
        )
        self.assertLess(make_current, private_close)
        self.assertLess(private_close, tracker_close)
        self.assertLess(private_close, texture_delete)
        self.assertLess(texture_delete, no_context)
        self.assertIn("catch (RuntimeException failure)", release)
        self.assertIn("if (transportCloseFailure != null) throw", release)

        native_release = native.split(
            "nativeReleaseBoundHardwareBufferRifeOutput(", 1
        )[1].split("nativePollBoundHardwareBufferRifeOutputs(", 1)[0]
        self.assertNotIn("if (!swap_succeeded)", native_release)
        self.assertIn("(void)swap_succeeded;", native_release)
        self.assertIn("g_app_owned_egl.create_sync(", native_release)
        self.assertIn("EGL_SYNC_FENCE_KHR", native_release)
        self.assertIn("glFlush();", native_release)
        self.assertIn(
            "selected->state = SurfaceControlOutputSlot::APP_RELEASE_PENDING",
            native_release,
        )

        initialize_egl = generator.split(
            "private void initializeEgl()", 1
        )[1].split("private void initializeGl()", 1)[0]
        self.assertIn("if (externalTransport != null) {", initialize_egl)
        self.assertIn("externalTransport.endpointSurface()", initialize_egl)
        self.assertLess(
            initialize_egl.index("if (externalTransport != null) {"),
            initialize_egl.index(
                "eglMakeCurrent(eglDisplay, eglEndpointSurface"
            ),
        )

    def test_rife_private_work_follows_real_selection_and_wsi_is_lightweight(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/"
            "DisplayFrameGenerator.java"
        )
        transport = self.read(
            "unified-android/qualification-src/com/thorium/preview/game/"
            "RifePresentationTransport.java"
        )
        native = self.read(
            "experiments/rife-ncnn-vulkan-android/android-benchmark/"
            "app/src/main/cpp/rife_benchmark_jni.cpp"
        )
        callback = generator.split(
            "PhysicalPresentationDeadline deadline =", 1
        )[1].split(
            "private void consumeExternalEndpointDiscontinuities", 1
        )[0]
        self.assertLess(
            callback.index("frameRate.selectBufferedPresentation("),
            callback.index(
                "buildExternalGeneratedPreparation("
            ),
        )
        self.assertLess(
            callback.index("presentBuffered(deadline,"),
            callback.index("submitExternalGeneratedPreparation("),
        )
        prepare = generator.split(
            "private FrameGenerationPreparationRequest "
            "buildExternalGeneratedPreparation(", 1
        )[1].split("private void presentExternalBuffered(", 1)[0]
        self.assertIn(
            "previewBufferedGeneratedTargetSourceNsAfterPendingCommit(", prepare
        )
        self.assertIn("externalRatePathPriming", prepare)
        self.assertIn(
            "frameRate.candidateGeneratedPanelScansPerOutput()", prepare
        )
        self.assertIn(
            "AdaptiveFrameRateController.exactMidpointTimestampNs(", prepare
        )
        self.assertIn(
            "prepareSuccessorAfterExactDoubleSynthetic", prepare
        )
        self.assertIn(
            "frameRate.bufferedPendingExactDoubleSchedule()", prepare
        )
        self.assertIn(
            "prepareSuccessorAfterExactDoubleSynthetic && advance != 0", prepare
        )
        self.assertIn(
            "advance == 1 || prepareSuccessorAfterExactDoubleSynthetic", prepare
        )
        self.assertIn(
            "prepareSuccessorAfterExactDoubleSynthetic ? 2L : 1L", prepare
        )
        self.assertIn(
            "successorSequence != activeRightSequence + 1L", prepare
        )
        self.assertIn("endpointFifoTimestampNs[successorSlot]", prepare)
        self.assertIn("Math.multiplyExact(", prepare)
        self.assertIn("FrameGenerationPreparationRequest.between(", prepare)
        self.assertIn("transport.prepare(request)", prepare)
        self.assertIn("targetSourceNs <= leftTimestampNs", prepare)
        self.assertIn("targetSourceNs >= rightTimestampNs", prepare)
        self.assertIn("bufferedPresentsBefore + 1L", callback)
        self.assertLess(
            callback.index("presentBuffered(deadline,"),
            callback.index("transport.prepare(request)")
            if "transport.prepare(request)" in callback else
            callback.index("submitExternalGeneratedPreparation("),
        )

        private_prepare_java = transport.split(
            "@Override public PreparationResult prepare(", 1
        )[1].split("@Override public PreparationReadiness", 1)[0]
        self.assertIn(
            "if (pairState == GenerationReadiness.UNSAFE)",
            private_prepare_java,
        )
        self.assertNotIn(
            "pairState != GenerationReadiness.READY", private_prepare_java
        )
        self.assertNotIn("nativePending || preparationInFlight",
                         private_prepare_java)
        self.assertIn("!nativePending || nativeInFlight == null ||",
                      private_prepare_java)
        self.assertIn("!nativeReleaseScheduled", private_prepare_java)
        self.assertIn(
            '"RIFE private preparation lacks a prequeued visible request"',
            private_prepare_java,
        )
        self.assertIn("return startPreparation(request);", private_prepare_java)
        self.assertNotIn("deferredPreparation", private_prepare_java)
        transport_poll = transport.split(
            "@Override public List<PresentationEvent> poll()", 1
        )[1].split("private SubmittedPresentation findSubmitted", 1)[0]
        self.assertIn("if (!pollNativeRelease())", transport_poll)
        self.assertNotIn("startDeferredPreparationAfterWsiRelease", transport)
        self.assertNotIn("deferredPreparation", transport)
        schedule_release = native.split(
            "nativeScheduleHardwareBufferRifePresentationRelease", 1
        )[1].split(
            "nativePollHardwareBufferRifePresentationRelease", 1
        )[0]
        self.assertLess(
            schedule_release.index("queue_pending_surface_present_locked("),
            schedule_release.index("context->timed_release_status = 1"),
        )
        self.assertIn("transport->presentation_queue", schedule_release)
        private_poll = transport.split(
            "private void pollPreparedPresentation()", 1
        )[1].split("private long takeProofSequence()", 1)[0]
        self.assertIn("if (proof.sceneCutRisk) {", private_poll)
        self.assertIn("current.discardRequested = true", private_poll)
        self.assertIn("discardPreparedPresentation()", private_poll)
        self.assertNotIn(
            'throw new IllegalStateException(\n'
            '                    "RIFE private generated output crossed',
            private_poll,
        )

        enqueue = transport.split(
            "@Override public EnqueueResult enqueue(", 1
        )[1].split("private void scheduleNativeRelease", 1)[0]
        self.assertIn("FrameGenerationPreparationRequest.from(request)", enqueue)
        self.assertIn("reason=private-output", enqueue)
        self.assertIn("enqueuePreparedHardwareBufferRifePresentation(", enqueue)
        self.assertIn("enqueueHardwareBufferRifePresentation(", enqueue)
        self.assertIn("proofSequence = consumedPreparation.proofSequence", enqueue)
        self.assertIn("preparedPresentation = null", enqueue)

        private_prepare = native.split(
            "nativePrepareHardwareBufferRifeOutput", 1
        )[1].split("nativePollPreparedHardwareBufferRifeOutput", 1)[0]
        self.assertIn("benchmark_submit_async(", private_prepare)
        self.assertIn("content_proof_pipeline", private_prepare)
        self.assertNotIn("vkAcquireNextImageKHR", private_prepare)
        self.assertNotIn("vkQueuePresentKHR", private_prepare)
        prepared_enqueue = native.split(
            "nativeEnqueuePreparedHardwareBufferRifePresentation", 1
        )[1].split("nativeEnqueueHardwareBufferRifePresentation", 1)[0]
        self.assertIn("vkAcquireNextImageKHR", prepared_enqueue)
        self.assertIn("transport->rife_to_surface_pipeline", prepared_enqueue)
        self.assertNotIn("context->rife->process_v4_gpu", prepared_enqueue)
        self.assertNotIn("transport->content_proof_pipeline", prepared_enqueue)
        self.assertNotIn("vkQueuePresentKHR", prepared_enqueue)
        self.assertIn("prepared = PreparedSurfaceOutput()", prepared_enqueue)

        discard = transport.split(
            "private boolean retireStalePreparation(", 1
        )[1].split("private void pollPreparedPresentation(", 1)[0]
        self.assertIn("current.request.matches(requested)", discard)
        self.assertIn("discardPreparedHardwareBufferRifeOutput(", discard)
        references = transport.split(
            "private boolean nativeReferences(", 1
        )[1].split("private void recordPairAssessment(", 1)[0]
        self.assertIn("privateOutput.request.leftSequence()", references)
        self.assertIn("privateOutput.lookaheadSequence", references)

    def test_external_lsfg_startup_and_cleanup_are_bounded_without_changing_default(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        self.assertIn("private static final long START_TIMEOUT_MS = 2500L;", generator)
        self.assertIn("private static final long STOP_TIMEOUT_MS = 1500L;", generator)
        self.assertIn(
            "private static final long EXTERNAL_START_TIMEOUT_MS = 15000L;",
            generator,
        )
        self.assertIn(
            "private static final long EXTERNAL_STOP_TIMEOUT_MS = 15000L;",
            generator,
        )
        self.assertIn(
            "externalTransportFactory == null ?\n"
            "                    START_TIMEOUT_MS : EXTERNAL_START_TIMEOUT_MS",
            generator,
        )
        self.assertIn(
            "externalTransportFactory == null ?\n"
            "                STOP_TIMEOUT_MS : EXTERNAL_STOP_TIMEOUT_MS",
            generator,
        )

    def test_lsfg_timeline_reset_waits_for_a_positive_renderer_epoch(self):
        transport = self.read(
            "unified-android/qualification-src/com/thorium/preview/game/"
            "LsfgPresentationTransport.java"
        )
        reset = transport.split(
            "@Override public void resetEndpointTimeline()", 1
        )[1].split("@Override public PreparationResult prepare", 1)[0]
        enqueue = transport.split(
            "@Override public EnqueueResult enqueue", 1
        )[1].split("@Override public PollResult poll", 1)[0]
        self.assertNotIn("NativeLsfgBridge.resetTimeline", reset)
        self.assertIn("requestPresentationEpoch = 0L;", reset)
        self.assertIn(
            "NativeLsfgBridge.resetTimeline(nativeHandle, requestPresentationEpoch);",
            enqueue,
        )
        self.assertIn("selfTestPresentFenceOffsetNs", transport)
        self.assertIn("selfTestPresentFenceOffsetNs < 0L", transport)
        self.assertIn(
            "selfTestPresentFenceOffsetNs > selfTestRefreshDurationNs * 2L",
            transport,
        )

    def test_lsfg_physical_self_test_uses_bounded_symmetric_measurement_tolerance(self):
        native = self.read(
            "unified-android/lsfg-qualification-native/lsfg_qualification_jni.cpp"
        )
        helper = native.split(
            "bool physicalTargetWithinTolerance", 1
        )[1].split("std::string jstringValue", 1)[0]
        self.assertIn("actualPresentTimeNs - desiredPresentTimeNs <= maximumLateNs", helper)
        self.assertIn("desiredPresentTimeNs - actualPresentTimeNs <= earlyToleranceNs", helper)
        self_test = native.split(
            "void runBoundedSurfaceControlSelfTest", 1
        )[1].split("void runBoundedLiveSurfaceControlSelfTest", 1)[0]
        self.assertIn("intervalError <= intervalTolerance", self_test)
        self.assertIn("firstPhysicalTargetMatched && secondPhysicalTargetMatched", self_test)
        self.assertIn("refresh * 2ULL", self_test)
        self.assertNotIn("firstNormalizedActual >= firstPhysical &&", self_test)

    def test_lsfg_retries_only_fenceless_startup_evidence_once(self):
        native = self.read(
            "unified-android/lsfg-qualification-native/lsfg_qualification_jni.cpp"
        )
        presenter = self.read(
            "unified-android/lsfg-qualification-native/"
            "owned_surface_control_presenter.cpp"
        )
        self.assertIn("kSurfaceControlSelfTestAttempts = 2U", native)
        self.assertIn(
            "catch (const emufusion::lsfg::PresentFenceUnavailable&)", native
        )
        self.assertIn("if (attempt + 1U == kSurfaceControlSelfTestAttempts) throw;", native)
        self.assertIn("takeUnavailablePresentFences()", presenter)
        self.assertIn(
            "throw emufusion::lsfg::PresentFenceUnavailable(", native
        )
        self.assertIn("omitted its present fence", native)
        self.assertIn("emufusion-lsfg-live-surface-control-v8-", native)
        runtime = self.read(
            "unified-android/qualification-src/com/thorium/preview/game/"
            "LsfgQualificationRuntime.java"
        )
        self.assertIn("emufusion-lsfg-live-surface-control-v8-", runtime)

    def test_fixed_rate_legacy_systems_use_core_cadence_not_image_uniqueness(self):
        controller = (ROOT / pathlib.Path(
            "unified-android/src/com/thorium/lucent/video/AdaptiveFrameRateController.java"
        )).read_text(encoding="utf-8")
        generator = (ROOT / pathlib.Path(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )).read_text(encoding="utf-8")
        host = (ROOT / pathlib.Path(
            "unified-android/src/com/thorium/preview/game/InWindowGameHost.java"
        )).read_text(encoding="utf-8")
        surface = (ROOT / pathlib.Path(
            "unified-android/src/com/thorium/preview/game/GameSurfaceView.java"
        )).read_text(encoding="utf-8")
        self.assertIn("setAuthoritativeSourceHz", controller)
        self.assertIn("if (frameRate.usesAuthoritativeSourceRate())", generator)
        self.assertIn("classifiedUniqueTimestampNs = producerTimestampNs", generator)
        # Authoritative callbacks remain exact endpoints. Adaptive source-rate
        # acquisition still observes only distinct images. Once that clock is
        # proven, the exact full candidate from a classified repeat may enter
        # presentation only when its immutable timestamp occupies precisely
        # the next source slot.
        self.assertIn("consumeClassifiedFrame(classifiedUnique)", generator)
        classified = generator[
            generator.index("private void consumeClassifiedFrame"):
            generator.index("private void uploadBitmap")
        ]
        self.assertIn("if (!unique) {", classified)
        self.assertIn("frameRate.hasSustainableGenerationRate()", classified)
        self.assertIn("duplicateOccupiesNextSourceSlot(", classified)
        self.assertIn("lastPresentationEndpointSubmission", classified)
        self.assertIn("if (!observeUniqueFrame(classifiedUniqueTimestampNs,",
                      classified)
        self.assertIn("acceptPresentationEndpoint(classifiedUniqueTexture,",
                      generator)
        self.assertIn("classifiedUniqueTimestampNs, classifiedUniqueSubmission",
                      classified)
        self.assertIn("classifiedUniqueSubmission);", generator)
        self.assertNotIn("presentationEndpointSelector", generator)
        self.assertIn("softwareImageIsUnique", generator)
        for system in ("nes", "snes", "gb", "gba", "megadrive"):
            self.assertIn('case "{}":'.format(system), host)
        for adaptive in ("gamecube", "ps2", "wii", "switch", "ps3"):
            self.assertNotIn('case "{}":'.format(adaptive), host)
        self.assertIn("layer.setAuthoritativeSourceHz", host)
        self.assertIn("declaredVideoHz()", host)
        self.assertIn("frameGenerator.setAuthoritativeSourceHz", surface)
        self.assertIn("setProducerTimelineHz", controller)
        self.assertIn("hardware.usesStampedProducerTimeline()", host)
        self.assertIn("hardware.declaredVideoHz()", host)
        self.assertIn("frameGenerator.setProducerTimelineHz", surface)
        self.assertIn('"gles-libretro".equals(entry.runtime)', self.read(
            "unified-android/src/com/thorium/preview/game/PpssppGlesEngineSession.java"
        ))

    def read(self, relative):
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_generator_is_surface_boundary_not_core_specific(self):
        source = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        self.assertIn("SurfaceTexture.OnFrameAvailableListener", source)
        self.assertIn("Choreographer.FrameCallback", source)
        self.assertIn("AdaptiveFrameRateController", source)
        self.assertIn("inputSurface()", source)
        self.assertNotIn("runFrame()", source)
        self.assertIn("eglSwapBuffers", source)

    def test_n64_frame_generation_uses_vi_origin_source_timeline_only_when_on(self):
        host = self.read(
            "unified-android/src/com/thorium/preview/ExperimentalGlesLibretroHost.java"
        )
        session = self.read(
            "unified-android/src/com/thorium/preview/game/PpssppGlesEngineSession.java"
        )
        native = self.read("unified-android/native/lucent_libretro_host.c")
        patch = self.read("engines/patches/mupen64plus-next-android-arm64.patch")

        self.assertIn("SOURCE_TIMELINE_DEFAULT = 0", host)
        self.assertIn("SOURCE_TIMELINE_MUPEN_VI_ORIGIN = 1", host)
        self.assertIn('"mupen64plus-next".equals(entry.id) &&', session)
        self.assertIn("request.frameGenerationMode !=", session)
        self.assertIn("FrameGenerationSettings.Mode.OFF", session)
        self.assertIn("SOURCE_TIMELINE_MUPEN_VI_ORIGIN", session)
        # 2026-09-06: content-bounds cropping (the N64 "blue edges" fix) is a
        # separate bit that must apply regardless of frame-generation mode,
        # so filteredSourceTimeline -- which gates whether the native host is
        # dropping unmarked/duplicate callbacks -- is masked to the
        # VI-origin bit specifically rather than "any policy at all".
        self.assertIn("SOURCE_TIMELINE_MUPEN_CONTENT_BOUNDS", session)
        self.assertIn(
            "filteredSourceTimeline = (sourceTimelinePolicy &", session
        )
        self.assertIn(
            ".SOURCE_TIMELINE_MUPEN_VI_ORIGIN) != 0;", session
        )
        # 2026-09-01: both hardware runtimes stamp presents on the ideal
        # paced lattice (GLES via eglPresentationTimeANDROID, Vulkan via
        # VK_GOOGLE_display_timing), so both are stamped producers.
        self.assertIn('("gles-libretro".equals(entry.runtime) ||', session)
        self.assertIn('"vulkan-libretro".equals(entry.runtime)) &&', session)
        self.assertIn("!filteredSourceTimeline", session)
        self.assertIn("SOURCE_TIMELINE_DEFAULT", session)
        self.assertIn("mupen_vi_origin_boundary", native)
        self.assertIn(
            '"retro_lucent_mupen_current_run_has_vi_origin_change"', native
        )
        self.assertIn("!active_host->mupen_vi_origin_boundary()", native)
        self.assertNotIn('"mupen64plus-BufferSwapMode"', native)
        self.assertIn("lucent_mupen_note_vi_origin_change", patch)
        self.assertIn(
            "retro_lucent_mupen_current_run_has_vi_origin_change", patch
        )
        self.assertIn("lucent_mupen_vi_origin_changed = false", patch)
        self.assertNotIn('CORE_NAME "-BufferSwapMode"', patch)
        self.assertNotIn("Config::bsOnVIOriginChange", patch)

    def test_game_surface_votes_for_panel_cadence_across_relaunch_and_resize(self):
        source = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        request = source.split(
            "private void requestOutputFrameRate(String reason)", 1
        )[1].split("private void initializeEgl()", 1)[0]
        self.assertIn("Surface.FRAME_RATE_COMPATIBILITY_DEFAULT", request)
        self.assertIn("Surface.CHANGE_FRAME_RATE_ONLY_IF_SEAMLESS", request)
        self.assertNotIn("FRAME_RATE_COMPATIBILITY_FIXED_SOURCE", request)
        self.assertIn('Log.e(TAG, "Unable to request game display cadence', request)

        initialize = source.split("private void initialize()", 1)[1].split(
            "private void requestOutputFrameRate", 1
        )[0]
        self.assertIn('requestOutputFrameRate("initialize")', initialize)
        self.assertLess(initialize.index('requestOutputFrameRate("initialize")'),
                        initialize.index("Choreographer.getInstance()"))

        resize = source.split("public void resize(", 1)[1].split(
            "@Override public void onFrameAvailable", 1
        )[0]
        self.assertIn('requestOutputFrameRate("resize")', resize)
        self.assertIn("outputFrameRateReassertedAfterSwap = false", resize)

        present = source.split("private void presentBuffered(", 1)[1].split(
            "private void reportStats()", 1
        )[0]
        self.assertLess(present.index("eglSwapBuffers"),
                        present.index('requestOutputFrameRate("first-successful-swap")'))
        self.assertIn("if (!outputFrameRateReassertedAfterSwap)", present)

    def test_both_primary_surface_kinds_use_the_same_generator(self):
        texture = self.read(
            "unified-android/src/com/thorium/preview/game/GameSurface.java"
        )
        layer = self.read(
            "unified-android/src/com/thorium/preview/game/GameSurfaceView.java"
        )
        for source in (texture, layer):
            self.assertIn("FrameGenerationRendererFactory.create", source)
            self.assertIn("frameGenerator.inputSurface()", source)
            self.assertIn("frameGenerator.resize", source)
            self.assertIn("generator.close()", source)
        factory = self.read(
            "unified-android/src/com/thorium/preview/game/"
            "FrameGenerationRendererFactory.java"
        )
        self.assertIn("new DisplayFrameGenerator", factory)
        self.assertIn("Direct presentation has no renderer", factory)
        self.assertIn("LSFG selected without an integrated renderer", factory)

    def test_n64_frontend_fbo_uses_title_dynamic_written_bounds(self):
        backend = self.read(
            "unified-android/native/lucent_android_gles_backend.c"
        )
        probe = backend.split(
            "static int probe_frontend_content_bounds(", 1
        )[1].split(
            "/* Bounded qualification telemetry", 1
        )[0]
        self.assertIn("is_framebuffer_sentinel", probe)
        self.assertIn("glReadPixels(0", probe)
        self.assertIn("backend->content_width * numerator / 4u", probe)
        self.assertIn("for (sample = 0; sample < 3u; ++sample)", probe)
        self.assertIn("*source_width = right - left", probe)
        self.assertIn("*source_height = top - bottom", probe)
        self.assertNotIn("near_black_edge_run", backend)
        self.assertNotIn("bottom_trim", probe)
        self.assertNotIn("top_trim", probe)
        self.assertIn("(top - bottom) * 3u < backend->content_height * 2u", probe)
        # 2026-09-06: the swap-restore fix for Dolphin's cached FBO binding
        # split the body that used to live directly in present_if_ready out
        # into present_current_frame (present_if_ready is now a thin
        # save/restore wrapper around it).
        present = backend.split(
            "static bool present_current_frame(", 1
        )[1].split(
            "bool lucent_android_gles_present_if_ready(", 1
        )[0]
        self.assertIn("content_bounds_probe_count < 600u", present)
        self.assertIn("content_bounds_stable_count < 4u", present)
        self.assertIn("content_bounds_stable_count = changed ? 1u", present)
        self.assertIn("title-dynamic source bounds=", present)
        self.assertIn("source_x = (GLint)backend->content_source_x", present)
        self.assertIn("source_y = (GLint)backend->content_source_y", present)
        self.assertIn("source_width = backend->content_source_width", present)
        self.assertIn("source_height = backend->content_source_height", present)
        self.assertIn("backend->presented_sequence = info.frame_sequence", present)
        self.assertNotIn(
            "!core_viewport_valid) {\n        if (!backend->content_bounds_valid",
            present,
        )

    def test_private_lsfg_requires_explicit_mode_and_packaged_transport(self):
        settings = self.read(
            "unified-android/src/com/thorium/preview/game/FrameGenerationSettings.java"
        )
        setter = settings.split(
            "public static synchronized void setMode(Context context, Mode mode)", 1
        )[1].split(
            "private static void persistMode", 1
        )[0]
        # The owner now explicitly permits LSFG beta through the ordinary
        # menu. Preserve that choice, but Off/Alpha/package presence alone
        # still cannot activate its optional transport.
        self.assertIn("Mode safe = mode == null ? Mode.OFF : mode;", setter)
        self.assertIn("persistMode(preferences(context), safe);", setter)
        transport = settings.split(
            "Context context, int displayId, Mode launchMode)", 1
        )[1].split("static final class QualificationTransport", 1)[0]
        self.assertIn("displayId != Display.DEFAULT_DISPLAY", transport)
        self.assertIn("launchMode != Mode.LSFG) return null;", transport)
        self.assertIn("ExternalFrameGenerationTransportLoader.lsfgQualification(context)",
                      transport)
        self.assertIn("if (factory == null) return null;", transport)
        host = self.read(
            "unified-android/src/com/thorium/preview/game/InWindowGameHost.java"
        )
        request = host.split(
            "private static GameLaunchRequest requestFrom", 1
        )[1].split(
            "private static String clean", 1
        )[0]
        self.assertIn("FrameGenerationSettings.mode(activity)", request)
        self.assertIn("qualificationSession,\n                launchMode", request)
        self.assertNotIn("launchMode = FrameGenerationSettings.Mode.LSFG", request)

    def test_failed_lsfg_does_not_authorize_a_different_generator(self):
        settings = self.read(
            "unified-android/src/com/thorium/preview/game/FrameGenerationSettings.java"
        )
        lsfg_selection = settings.split("if (selected == Mode.LSFG)", 1)[1].split(
            "return FrameGenerationBackendPolicy.select(false,", 2
        )
        # The first return after the LSFG branch must disable generation;
        # neither unavailable LSFG nor the unselected Alpha arm can be ready.
        self.assertEqual(len(lsfg_selection), 3)
        branch = lsfg_selection[1]
        self.assertIn('"LSFG transport unavailable"', branch)
        self.assertIn('"Built-in (Alpha) was not selected"', branch)
        self.assertNotIn("Assessment.ready()", branch)
        surface = self.read(
            "unified-android/src/com/thorium/preview/game/GameSurfaceView.java"
        )
        startup = surface.split("private void createGenerator(", 1)[1].split(
            "private void useDirectAfterUnavailableLsfg(", 1
        )[0]
        failure_paths = startup.split(
            '" qualification unavailable after bounded retry;', 1
        )[1].split("FrameGenerationBackendPolicy.Selection selection", 1)[0]
        self.assertEqual(failure_paths.count("useDirectAfterUnavailableLsfg(output);"), 2)
        self.assertEqual(failure_paths.count("return;"), 2)
        self.assertIn("launchMode == FrameGenerationSettings.Mode.LSFG", failure_paths)
        direct = surface.split("private void useDirectAfterUnavailableLsfg(", 1)[1].split(
            "private void requestDirectFrameRate(", 1
        )[0]
        self.assertIn("frameGenerator = null;", direct)
        self.assertIn("activeBackend = FrameGenerationBackendPolicy.Backend.DIRECT;", direct)
        self.assertIn("engineSurface = output;", direct)
        self.assertNotIn("FrameGenerationRendererFactory.create", direct)
        self.assertIn("LSFG could not start. Using direct playback", direct)

    def test_owner_setting_is_explicit_three_way_and_off_is_a_hard_bypass(self):
        setting = self.read(
            "unified-android/src/com/thorium/preview/game/FrameGenerationSettings.java"
        )
        self.assertIn('enum Mode', setting)
        self.assertIn('OFF("off")', setting)
        self.assertIn('BUILT_IN_ALPHA("built-in-alpha")', setting)
        self.assertIn('LSFG("lsfg")', setting)
        self.assertIn('return Mode.OFF;', setting)
        self.assertIn('prefs.getInt(MODE_VERSION, 0) != CURRENT_MODE_VERSION', setting)
        self.assertNotIn('LOSSLESS_SCALING', setting)
        self.assertNotIn('ensureExternalBackend', setting)
        self.assertNotIn('sendBroadcast', setting)
        self.assertIn('FrameGenerationBackendPolicy.Assessment.ready()', setting)
        self.assertIn('launchMode != Mode.LSFG', setting)
        self.assertNotIn('Lossless.dll', setting)
        self.assertIn('RifeQualificationRuntime', setting)
        self.assertIn('selfTestPassed=false/deadlineQualified=false', setting)
        self.assertIn('builtInAssessment', setting)
        build = self.read("unified-android/build.sh")
        self.assertIn('copy the exact <queries> block here', build)
        self.assertIn('android-companion/AndroidManifest.xml', build)
        manifest = self.read("android-companion/AndroidManifest.xml")
        self.assertNotIn('com.lsfg.android', manifest)

        for relative in (
            "unified-android/src/com/thorium/preview/game/GameSurface.java",
            "unified-android/src/com/thorium/preview/game/GameSurfaceView.java",
            "android-companion/src/com/thorium/preview/PreviewActivity.java",
        ):
            source = self.read(relative)
            self.assertIn("FrameGenerationSettings.selectBackendForSession(", source,
                          relative)
            self.assertIn("FrameGenerationBackendPolicy.Backend.DIRECT",
                          source, relative)
            self.assertIn("using direct presentation", source, relative)
            if relative.endswith(("GameSurface.java", "GameSurfaceView.java")):
                self.assertIn("renderer.activeBackendLabel()", source, relative)
                self.assertIn("FrameGenerationSettings.Mode.OFF", source, relative)

        policy = self.read(
            "unified-android/src/com/thorium/lucent/video/FrameGenerationBackendPolicy.java"
        )
        self.assertIn("legallyUsable", policy)
        self.assertIn("abiCompatible", policy)
        self.assertIn("capabilitiesReady", policy)
        self.assertIn("selfTestPassed", policy)
        self.assertIn("deadlineQualified", policy)
        self.assertIn("safeLsfg.usable() ? Backend.LSFG", policy)
        self.assertIn("safeBuiltIn.usable() ? Backend.BUILT_IN : Backend.DIRECT",
                      policy)

        service = self.read("android-companion/src/com/thorium/preview/PreviewService.java")
        self.assertGreaterEqual(service.count('"/settings/frame-generation"'), 3)
        self.assertIn('mode must be off, built-in-alpha, or lsfg', service)
        self.assertIn("FrameGenerationSettings.Mode", service)
        self.assertIn("FrameGenerationSettings.setMode(this, parsed)", service)
        self.assertIn("legacy frame-generation enable is disabled", service)
        self.assertNotIn("FrameGenerationSettings.setEnabled(this, enabled)", service)

        theme = self.read("theme/theme.qml")
        self.assertIn('property string frameGenerationMode: "off"', theme)
        self.assertIn('"FRAME GENERATION"', theme)
        self.assertIn('return "BUILT-IN (ALPHA)"', theme)
        self.assertIn('return "LSFG"', theme)
        self.assertIn('return "OFF"', theme)
        self.assertIn('lucentFrameGenerationThreeModeV3', theme)
        self.assertIn('property bool frameGenerationModeConfirmed: false', theme)
        self.assertIn('if (frameGenerationModePending || !frameGenerationModeConfirmed)', theme)
        self.assertIn('if (pendingGame) root.launchConfirmed(pendingGame)', theme)
        self.assertIn("cycleFrameGenerationMode", theme)
        self.assertNotIn('losslessScalingAvailable', theme)

        host = self.read(
            "unified-android/src/com/thorium/preview/game/InWindowGameHost.java"
        )
        self.assertNotIn('"S-- T-- A-- Backend=" +', host)
        self.assertIn("frameRateBadge", host)
        self.assertIn("observeReportedOutput(actual)", host)

    def test_authoritative_framegen_document_uses_only_uniform_thor_divisors(self):
        historical = self.read("docs/systemwide-frame-generation.md")
        self.assertIn("FRAME-GENERATION-GOAL-2026-09-04.md", historical)
        self.assertIn("historical lab notebook", historical)
        current = self.read("docs/FRAME-GENERATION-GOAL-2026-09-04.md")

        controller_test = self.read(
            "unified-android/test/com/thorium/lucent/video/"
            "AdaptiveFrameRateControllerTest.java"
        )

        # The current owner-directed max2 goal supersedes September1's x3
        # notebook. Do not make historical acceptance labels executable policy.
        self.assertIn("**1 or 2 only**", current)
        self.assertIn("R  = n × O", current)
        self.assertIn("|r - 1| ≤ 0.0075", current)
        for mapping in (
            "| 60 | 120 | 2 | 1 |",
            "| 40 | 40 direct | 1 | 3 |",
            "| 30 | 60 | 2 | 2 |",
            "| 24 | 24 direct | 1 | 5 |",
            "| 20 | 40 | 2 | 3 |",
        ):
            self.assertIn(mapping, current)
        self.assertIn("40→80 on 120 Hz", current)
        self.assertIn("old 3× paths 20→60 / 40→120", current)
        self.assertIn("not accelerated to 60", current)
        self.assertIn("retired guest ticks", current)
        self.assertIn("Off remains the default", current)
        self.assertIn("Direct fallback is not a generation PASS", current)
        self.assertIn("int[] output = {40, 60, 40, 50, 120};", controller_test)
        self.assertIn("int[] output = {20, 60, 40, 50, 60};", controller_test)
        self.assertNotIn("int[] output = {60, 60, 120, 120, 120};", controller_test)

    def test_off_is_direct_on_an_independently_latched_surface_layer(self):
        host = self.read(
            "unified-android/src/com/thorium/preview/game/InWindowGameHost.java"
        )
        self.assertIn("request.frameGenerationMode ==", host)
        self.assertIn("activity, request.frameGenerationMode", host)
        self.assertIn("if (strictOff)", host)
        self.assertIn("Strict Off: direct isolated SurfaceView path", host)
        self.assertIn("GameSurfaceView layer = new GameSurfaceView(", host)
        request = self.read(
            "unified-android/src/com/thorium/preview/game/GameLaunchRequest.java"
        )
        self.assertIn("final FrameGenerationSettings.Mode frameGenerationMode", request)
        self.assertIn("EXTRA_FRAME_GENERATION_MODE", request)
        for relative in (
            "unified-android/src/com/thorium/preview/game/GameSurface.java",
            "unified-android/src/com/thorium/preview/game/GameSurfaceView.java",
        ):
            surface = self.read(relative)
            self.assertIn("final FrameGenerationSettings.Mode launchMode", surface)
            self.assertIn("if (launchMode == FrameGenerationSettings.Mode.OFF)", surface)
            self.assertIn("surfaceIdentity=true rendererCreated=", surface)
            self.assertIn("FrameGenerationRendererRegistry.liveCount()", surface)
        ppsspp = self.read(
            "unified-android/src/com/thorium/preview/game/PpssppGlesEngineSession.java"
        )
        self.assertIn("request.frameGenerationMode !=", ppsspp)
        self.assertNotIn("FrameGenerationSettings.isEnabled(appContext)", ppsspp)
        harness = self.read("unified-android/tools/run_runtime_acceptance_qa.py")
        self.assertIn("candidateLayers", harness)
        # Exactly-one-passing was strengthened to a uniquely strongest
        # primary display-0 candidate; ambiguity still fails the gate.
        self.assertIn(
            '_unique_strongest_framegen_candidate(\n        passing, "primary", 0)',
            harness)
        self.assertIn("if primary_selected is None", harness)
        self.assertIn("actual-present", harness)

    def test_dual_screen_proof_is_bound_to_secondary_display(self):
        harness = self.read("unified-android/tools/run_runtime_acceptance_qa.py")
        self.assertIn("secondary_gameplay_layers", harness)
        self.assertIn("role=role, display_id=display_id", harness)
        # Exactly-one-passing was strengthened to a uniquely strongest
        # secondary display-4 candidate; ambiguity still fails the gate.
        self.assertIn(
            '_unique_strongest_framegen_candidate(\n            passing, "secondary", 4)',
            harness)
        self.assertIn("if secondary_selected is None", harness)
        self.assertIn('item[2].get("displayId") == 4', harness)

    def test_thor_lower_normal_and_rotated_paths_use_generator(self):
        preview = self.read("android-companion/src/com/thorium/preview/PreviewActivity.java")
        self.assertIn("ensureGameplayGenerator(holder.getSurface()", preview)
        self.assertIn("private void showClockwiseGameplaySurface()", preview)
        clockwise = preview.split("private void showClockwiseGameplaySurface()", 1)[1].split(
            "private void ensureGameplayGenerator(", 1
        )[0]
        self.assertIn("ensureGameplayGenerator(holder.getSurface(), width, height)", clockwise)
        self.assertIn("gameplayEngineSurface", preview)
        self.assertIn("releaseGameplayGenerator()", preview)
        self.assertIn("this::qualificationProofEnabled", preview)
        self.assertIn('"emufusion_framegen_proof", 0', preview)
        # SurfaceView View transforms do not rotate its independently composed
        # buffer on Thor.  The producer buffer is portrait and SurfaceFlinger
        # performs the actual quarter-turn.
        self.assertIn("int portraitWidth = Math.min(panelWidth, panelHeight);", clockwise)
        self.assertIn("int portraitHeight = Math.max(panelWidth, panelHeight);", clockwise)
        self.assertIn("setFixedSize(portraitWidth, portraitHeight)", clockwise)
        self.assertIn("SurfaceControl.BUFFER_TRANSFORM_ROTATE_90", clockwise)
        self.assertIn("setBufferTransform(gameplaySurface.getSurfaceControl()",
                      clockwise)
        self.assertNotIn("gameplaySurface.setRotation(90f)", clockwise)

    def test_interpolation_never_advances_emulation_or_audio(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        self.assertNotIn("LibretroHost", generator)
        self.assertNotIn("NativeAdapterHost", generator)
        self.assertNotIn("AudioTrack", generator)
        self.assertNotIn("nativeRunFrame", generator)
        self.assertIn("uPrevious", generator)
        self.assertIn("uCurrent", generator)
        self.assertIn("uPhase", generator)

    def test_starved_source_holds_real_endpoint_instead_of_extrapolating(self):
        controller = self.read(
            "unified-android/src/com/thorium/lucent/video/AdaptiveFrameRateController.java"
        )
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        self.assertIn("MIN_GENERATION_SOURCE_HZ = 20.0", controller)
        self.assertIn("public boolean hasSustainableGenerationRate()", controller)
        # The starvation guard gained an availability pre-condition; the
        # sustainable-rate check itself must remain in the disjunction.
        self.assertIn("if (!generationAvailable || !hasSustainableGenerationRate())",
                      controller)
        self.assertIn("Math.min(displayRefreshHz, source)", controller)
        self.assertIn("return Math.min(1f,", controller)
        self.assertNotIn("return Math.min(1.5f", controller)
        self.assertIn("boolean sustainable = frameRate.hasSustainableGenerationRate()",
                      generator)
        self.assertIn("else drawTexture2d(historyTextures[previousIndex])", generator)
        self.assertIn("phase > 0f && phase < 1f", generator)
        self.assertIn("selectBufferedPresentation(", generator)
        self.assertIn("PRESENT_NONE", generator)
        self.assertIn("PRESENT_REAL", generator)
        self.assertIn("if (midpointPending)", controller)
        self.assertIn("++syntheticQuotaSkippedCount", controller)
        self.assertNotIn("if (frameRate.presentationDue(frameTimeNanos))", generator)

    def test_buffered_scheduler_commits_swaps_and_exact_fifo_pairs(self):
        controller = self.read(
            "unified-android/src/com/thorium/lucent/video/AdaptiveFrameRateController.java"
        )
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        endpoint_selector = self.read(
            "unified-android/src/com/thorium/lucent/video/EndpointFrameSelector.java"
        )
        decision = controller[controller.index("public int selectBufferedPresentation"):
                              controller.index("public float selectedInterpolation")]
        self.assertIn("bufferedPendingPresentation", decision)
        self.assertIn("commitBufferedPresentation", decision)
        self.assertIn("bufferedEndpointAdvanceAfterPresentation", decision)
        self.assertIn("PRESENT_REAL", decision)
        self.assertIn("PRESENT_SYNTHETIC", decision)
        self.assertIn("rightSequence == leftSequence + 1L", decision)
        self.assertIn("bufferedMinimumReprimeSequence", decision)
        self.assertIn(
            "boolean wantsGeneratedOutput = generationAvailable &&\n"
            "                hasSustainableGenerationRate() &&\n"
            "                exactOutputHz > exactSourceHz + 1.0e-5;",
            decision,
        )
        self.assertIn(
            "boolean directOnly = !wantsGeneratedOutput || !validPair;",
            decision,
        )
        self.assertIn(
            "boolean primeReady = wantsGeneratedOutput ?\n"
            "                    (structuralPair || knownUnsafeSuccessor) : endpointReady;",
            decision,
        )
        self.assertIn("presentationSourceHz()", decision)
        self.assertIn("targetOutputHz()", decision)
        self.assertIn("Motion readiness may disappear independently", decision)
        self.assertIn("exactDoubleEndpointLatticeRequired", decision)
        exact_double = decision.split(
            "if (exactDoubleSchedule)", 1
        )[1].split("else if (directOnly)", 1)[0]
        self.assertIn("presentation = PRESENT_SYNTHETIC", exact_double)
        self.assertIn("phase = 1f", exact_double)
        self.assertIn("pendingAdvance = 0", exact_double)
        self.assertIn("pendingAdvance = 1", exact_double)
        self.assertLess(decision.index("bufferedPendingPresentation = presentation"),
                        decision.index("public void commitBufferedPresentation"))
        callback = generator[generator.index("@Override public void doFrame"):
                             generator.index("private boolean latestImageIsUnique")]
        self.assertLess(callback.index("choreographer.postFrameCallback(this)"),
                        callback.index(
                            "presentBuffered(deadline,"
                        ))
        self.assertIn("eglPresentationTimeANDROID", generator)
        self.assertIn("PhysicalPresentationDeadline.next", generator)
        self.assertIn("deadline.contentPresentationTimeNs()", callback)
        self.assertIn("presentBuffered(deadline,", callback)
        self.assertLess(callback.index("prepareBufferedPairIfPossible()"),
                        callback.index("selectBufferedPresentation("))
        self.assertLess(callback.index("synchronizeBufferedPresentationEpoch()"),
                        callback.index("prepareBufferedPairIfPossible()"))
        self.assertIn(
            "if (schedulerPresentationEpoch() != presentationEpochBeforePrepare)",
            callback,
        )
        self.assertIn(
            "presentBuffered(deadline,",
            callback,
        )
        self.assertIn("FrameGenerationPresentationRequest.between(", generator)
        self.assertIn("deadline.contentPresentationTimeNs()", generator)
        self.assertIn("deadline.driverDesiredPresentTimeNs()", generator)
        self.assertIn("request.hardCompletionDeadlineNs()", generator)
        self.assertIn("abortBufferedPresentation()", callback)
        present_start = generator.index("private void presentBuffered(")
        present_end = generator.index(
            "    private boolean primeFirstExternalGeneratedOutput(",
            present_start,
        )
        present = generator[present_start:present_end]
        self.assertLess(present.index("eglPresentationTimeANDROID"),
                        present.index("eglSwapBuffers"))
        self.assertLess(present.index("eglSwapBuffers"),
                        present.index("commitBufferedPresentation(true)"))
        self.assertLess(present.index("commitBufferedPresentation(true)"),
                        present.index("commitBufferedEndpointAdvance"))
        self.assertLess(present.index("bufferedAdvanceWouldCrossGap(endpointAdvance)"),
                        present.index("enqueueProofAtlas(proofPhase)"))
        self.assertLess(present.index("if (advanceCrossesGap) captureProof = false"),
                        present.index("enqueueProofAtlas(proofPhase)"))
        self.assertLess(present.index("commitBufferedEndpointAdvance"),
                        present.rindex("refreshProofEvidencePresentationEpoch()"))
        self.assertLess(present.rindex("refreshProofEvidencePresentationEpoch()"),
                        present.index("if (presents % HEALTH_INTERVAL == 0L)"))
        self.assertIn(
            "if (presentationEpochAfterAdvance != presentationEpochBeforeAdvance)",
            present,
        )
        epoch_boundary = present[
            present.index(
                "if (presentationEpochAfterAdvance != presentationEpochBeforeAdvance)"
            ):present.index("if (presents % HEALTH_INTERVAL == 0L)")
        ]
        self.assertIn("resetHealthWindowAfterStreamChange()", epoch_boundary)
        self.assertIn("return;", epoch_boundary)
        self.assertIn("drawTexture2d(historyTextures[previousIndex])", present)
        fifo = generator[generator.index("private boolean observeUniqueFrame"):
                         generator.index("private void promoteLatestTexture")]
        # 2026-09-02: six retained endpoints so slot-lattice (adapter)
        # producers can prime three deeper than the libretro path; every
        # other prime depth is unchanged.
        self.assertIn("ENDPOINT_FIFO_CAPACITY = 6", generator)
        self.assertIn("ENDPOINT_FIFO_PRIME_DEPTH = 3", generator)
        self.assertIn("ENDPOINT_FIFO_EXTERNAL_PRIME_DEPTH = 4", generator)
        self.assertNotIn("ENDPOINT_FIFO_JITTER_RESERVE", generator)
        self.assertIn("endpointFifoTextures", fifo)
        self.assertIn("endpointFifoSubmission", fifo)
        self.assertIn("endpointFifoUniqueSequence", fifo)
        self.assertIn("endpointFifoCandidateLoss", fifo)
        self.assertIn("acceptPresentationEndpoint", fifo)
        observation = fifo[fifo.index("private boolean observeUniqueFrame"):
                           fifo.index("private void acceptPresentationEndpoint")]
        self.assertIn("frameRate.onProducerFrame", observation)
        self.assertNotIn("endpointFifoTextures", observation)
        self.assertIn("consumeEndpointIntoHistory", fifo)
        self.assertIn("activeRightSequence != activeLeftSequence + 1L", fifo)
        overflow = fifo[fifo.index("if (endpointFifoCount < ENDPOINT_FIFO_CAPACITY)"):
                        fifo.index("copyTexture(sourceTexture")]
        self.assertIn("endpointFifoHead = 0", overflow)
        self.assertIn("endpointFifoCount = 1", overflow)
        self.assertIn("Arrays.fill(endpointFifoSequence, 0L)", overflow)
        prepare = fifo[fifo.index("private void prepareBufferedPairIfPossible"):
                       fifo.index("private void copyBufferedEndpoints")]
        self.assertIn(
            "boolean generatedTimeline = frameRate.generatesIntermediateFrames()",
            prepare,
        )
        self.assertIn(
            "int requiredPrimeDepth = generatedTimeline ?",
            prepare,
        )
        self.assertIn(
            "externalTransport != null ?\n" +
            "                            ENDPOINT_FIFO_EXTERNAL_PRIME_DEPTH :",
            prepare,
        )
        self.assertIn("endpointFifoCount < requiredPrimeDepth", prepare)
        self.assertIn("right == left + 1L", prepare)
        self.assertIn("consumeEndpointIntoHistory(previousIndex, true)", prepare)
        self.assertIn(
            "if (!generatedTimeline && endpointFifoCount == 1)",
            prepare,
        )
        self.assertNotIn("discardEndpointFifoHead()", prepare)
        self.assertIn("boolean sequenceContinuous =", prepare)
        self.assertIn("boolean timestampContinuous =", prepare)
        self.assertIn("activeLeftSubmission, nextSubmission", prepare)
        self.assertIn("activeLeftUniqueSequence, nextUniqueSequence", prepare)
        self.assertIn("activeLeftCandidateLoss, nextCandidateLoss", prepare)
        self.assertIn("if (!sequenceContinuous || !timestampContinuous)", prepare)
        self.assertLess(prepare.index("if (!sequenceContinuous || !timestampContinuous)"),
                        prepare.index("copyBufferedEndpoints(false)"))
        discontinuity = prepare[prepare.index(
                                "if (!sequenceContinuous || !timestampContinuous)"):
                                prepare.index("copyBufferedEndpoints(false)")]
        self.assertIn("invalidateBufferedPairForReprime()", discontinuity)
        self.assertIn("prepareBufferedPairIfPossible()", discontinuity)
        epoch_reset = fifo[
            fifo.index("private void resetEndpointTimelineForSchedulerEpoch"):
            fifo.index("private void copyBufferedEndpoints")
        ]
        self.assertNotIn("presentationEndpointSelector", epoch_reset)
        self.assertIn("Arrays.fill(endpointFifoSequence, 0L)", epoch_reset)
        self.assertNotIn("clearSignatureCandidates()", epoch_reset)
        atlas = generator[generator.index("private void enqueueProofAtlas"):
                          generator.index("private void pollProofAtlas")]
        self.assertIn("activeRightSequence != activeLeftSequence + 1L", atlas)
        self.assertIn("proofAtlasHeader.putInt((int) activeLeftSequence)", atlas)
        self.assertIn("proofAtlasHeader.putInt((int) activeRightSequence)", atlas)
        self.assertNotIn("proofAtlasHeader.putInt(promotedFrameCount", atlas)
        teardown = generator[
            generator.index("private void teardownDenseEpoch(String reason)"):
            generator.index("private void clearAllMotionFieldsAfterDenseReject")
        ]
        self.assertLess(teardown.index("clearSignatureCandidates()"),
                        teardown.index("timer.discardPending()"))
        self.assertIn("denseSignatureBaselineReady = false", teardown)
        self.assertIn("denseSignatureSequence = 0L", teardown)
        self.assertIn("denseSignatureReady = 0", teardown)
        self.assertNotIn("presentationDue(frameTimeNanos)", callback)
        self.assertIn("targetScheduleEligible", generator)
        self.assertIn("denseCadenceTargetEligible(", generator)
        self.assertIn("DENSE_CADENCE_REJECT_CONSECUTIVE_WINDOWS = 3", generator)
        self.assertIn("denseCadenceFailureWindows >=\n" +
                      "                            DENSE_CADENCE_REJECT_CONSECUTIVE_WINDOWS",
                      generator)
        self.assertIn("advanceCadenceFailureWindows", generator)
        target_eligibility = generator.index(
            "boolean targetScheduleEligible = denseCadenceTargetEligible(")
        target_failure = generator.index(
            "generationTargetFailureWindows =\n" +
            "                    FrameGenerationCadence.advanceCadenceFailureWindows(")
        self.assertLess(target_eligibility, target_failure)
        target_failure_block = generator[
            target_failure:generator.index(
                "boolean generationTargetReject =", target_failure)
        ]
        self.assertIn("targetScheduleEligible", target_failure_block)
        self.assertNotIn("frameRate.generatesIntermediateFrames()",
                         target_failure_block)
        self.assertIn('PRESENTATION_TIMING_MODE =\n' +
                      '            "egl-android-next-vsync"', generator)
        self.assertIn('" presentationTimingMode=" + PRESENTATION_TIMING_MODE',
                      generator)
        self.assertIn('" cadenceRejectConsecutiveWindows=" +', generator)
        self.assertIn("promotedHz >= lockedFps * .92", generator)
        self.assertIn("dueNoEndpoint == 0L", generator)
        self.assertIn("syntheticQuotaSkipped != 0L", generator)
        self.assertNotIn("windowDueSelected >=", generator)
        eligibility_call = generator[
            generator.index("boolean targetScheduleEligible ="):
            generator.index("boolean cadenceUnderTarget =", generator.index(
                "boolean targetScheduleEligible ="))
        ]
        self.assertIn("windowPresentationEpoch, lastHealthPresentationEpoch",
                      eligibility_call)
        self.assertIn("windowSyntheticQuotaSkipped", eligibility_call)
        self.assertNotIn("windowPresents", eligibility_call)
        self.assertNotIn("windowDueSelected", eligibility_call)
        self.assertIn("observePromotionWindow", generator)

    def test_async_proof_poll_isolates_stale_gl_errors_and_logs_exact_row(self):
        native = self.read(
            "unified-android/native/lucent_framegen_timer_jni.c"
        )
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        poll = native[native.index("int lucent_framegen_proof_atlas_poll_raw"):
                      native.index("JNIEXPORT jlongArray JNICALL",
                                   native.index("int lucent_framegen_proof_atlas_poll_raw"))]
        self.assertLess(poll.index("drain_gl_errors()"),
                        poll.index("proof_client_wait_sync"))
        for stage in ("PROOF_ATLAS_POLL_STAGE_DRAIN",
                      "PROOF_ATLAS_POLL_STAGE_GET_BINDING",
                      "PROOF_ATLAS_POLL_STAGE_BIND",
                      "PROOF_ATLAS_POLL_STAGE_MAP",
                      "PROOF_ATLAS_POLL_STAGE_UNMAP",
                      "PROOF_ATLAS_POLL_STAGE_RESTORE_BINDING"):
            self.assertIn(stage, poll)
        self.assertIn('java.util.Arrays.toString(row)', generator)
        self.assertIn('bufferCapacity=', generator)
        self.assertIn('nativePending=', generator)
        self.assertIn('capability=', generator)
        self.assertIn('oldest->fence = NULL', poll)
        self.assertIn('oldest->pending = 0', poll)
        self.assertNotIn('memset(oldest', poll)

    def test_source_rate_counts_unique_images_not_buffer_callbacks(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        callback = generator[generator.index("onFrameAvailable"):
                             generator.index("@Override public void doFrame")]
        self.assertIn("producerArrivalNs = System.nanoTime()", callback)
        self.assertIn("producerBufferTimestampNs = inputTexture.getTimestamp()", callback)
        self.assertIn("producerTimestampNs = producerBufferTimestampNs > 0L", callback)
        self.assertIn("latestImageIsUnique(producerTimestampNs)", callback)
        self.assertIn("consumeClassifiedFrame(classifiedUnique)", callback)
        self.assertLess(callback.index("latestImageIsUnique(producerTimestampNs)"),
                        callback.index(
                            "consumeClassifiedFrame(classifiedUnique)"))
        self.assertNotIn("selectPresentationEndpoint(producerArrivalNs)", callback)
        classified = generator[
            generator.index("private void consumeClassifiedFrame"):
            generator.index("private void uploadBitmap")
        ]
        self.assertIn("if (!unique) {", classified)
        self.assertIn("frameRate.hasSustainableGenerationRate()", classified)
        self.assertIn("duplicateOccupiesNextSourceSlot(", classified)
        self.assertIn("if (!observeUniqueFrame(classifiedUniqueTimestampNs,",
                      classified)
        self.assertIn("acceptPresentationEndpoint(classifiedUniqueTexture",
                      classified)
        # A classified repeat can preserve a real source slot, but it never
        # enters the source-rate observer. Distinct-image evidence remains the
        # sole authority that can acquire or change the sustainable clock.
        duplicate_branch = classified[
            classified.index("if (!unique) {"):
            classified.index("if (!observeUniqueFrame(")
        ]
        self.assertNotIn("observeUniqueFrame", duplicate_branch)
        self.assertIn("acceptPresentationEndpoint", duplicate_branch)
        self.assertIn("return;", duplicate_branch)
        self.assertIn(
            "endpointFifoUniqueSequence[slot] = endpointSequence;", generator
        )

        accepted = generator[
            generator.index("private void acceptPresentationEndpoint"):
            generator.index("private void publishExternalEndpoint")
        ]
        self.assertIn(
            "!AdaptiveFrameRateController.endpointSpanContinuous(", accepted
        )
        source_gap = accepted[
            accepted.index(
                "if (lastPresentationEndpointTimestampNs > 0L &&"
            ):
            accepted.index(
                "if (externalTransport != null &&\n"
                "                endpointFifoCount >= ENDPOINT_FIFO_CAPACITY)"
            )
        ]
        self.assertLess(
            source_gap.index("frameRate.resetPresentation()"),
            source_gap.index("resetEndpointTimelineForSchedulerEpoch()"),
        )
        self.assertLess(
            source_gap.index(
                "observedBufferedPresentationEpoch = "
                "schedulerPresentationEpoch()"
            ),
            source_gap.index("resetEndpointTimelineForSchedulerEpoch()"),
        )
        self.assertLess(
            source_gap.index("resetEndpointTimelineForSchedulerEpoch()"),
            source_gap.index("refreshProofEvidencePresentationEpoch()"),
        )
        self.assertNotIn("publishExternalEndpoint", source_gap)
        self.assertLess(
            accepted.index("endpointFifoCount >= ENDPOINT_FIFO_CAPACITY"),
            accepted.index("lastPresentationEndpointTimestampNs = timestampNs"),
        )
        self.assertLess(
            accepted.index("Presentation endpoint timestamp discontinuity"),
            accepted.index("publishExternalEndpoint"),
        )
        self.assertLess(
            accepted.index("resetEndpointTimelineForSchedulerEpoch()"),
            accepted.index("lastPresentationEndpointSubmission = submissionOrdinal"),
        )
        observation = generator[generator.index("private boolean observeUniqueFrame"):
                                generator.index("private void acceptPresentationEndpoint")]
        self.assertIn("frameRate.onProducerFrame", observation)
        self.assertIn("frameRate.onProducerFrame(timestampNs, submissionOrdinal)",
                      observation)
        self.assertIn("if (!frameRate.onProducerFrame(timestampNs, submissionOrdinal))",
                      observation)
        coalesced = observation[
            observation.index(
                "if (!frameRate.onProducerFrame(timestampNs, submissionOrdinal))"
            ):
            observation.index("return true;", observation.index(
                "if (!frameRate.onProducerFrame(timestampNs, submissionOrdinal))"))
        ]
        self.assertIn("synchronizeBufferedPresentationEpoch()", coalesced)
        self.assertNotIn("teardownDenseEpoch", coalesced)
        self.assertNotIn("resetEndpointFifo()", coalesced)
        self.assertNotIn("clearSignatureCandidates", coalesced)
        self.assertNotIn("System.nanoTime()", observation)
        self.assertIn("return false", observation)
        discontinuity = observation[
            observation.index("if (timestampNs <= 0L"):
            observation.index("lastProducerTimestampNs = timestampNs")
        ]

        self.assertLess(
            discontinuity.index(
                'teardownDenseEpoch("producer-timestamp-discontinuity")'
            ),
            discontinuity.index("resetEndpointFifo()"),
        )
        self.assertNotIn("endpointFifoTextures", observation)
        self.assertIn("SIGNATURE_WIDTH = 16", generator)
        self.assertIn("SIGNATURE_HEIGHT = 9", generator)
        self.assertIn("SIGNATURE_CANDIDATE_SLOTS = 5", generator)
        self.assertIn("sourceSignatureIsUnique()", generator)
        self.assertIn("submitted=", generator)
        classifier = generator[
            generator.index("private boolean latestImageIsUnique"):
            generator.index("private void copyCurrentSignatureToPrevious")
        ]
        self.assertIn(
            "classifiedUniqueTexture =\n"
            "                            signatureCandidateTextures[completedCandidate]",
            classifier,
        )
        self.assertIn(
            "classifiedUniqueTimestampNs =\n"
            "                            signatureCandidateTimestampNs[completedCandidate]",
            classifier,
        )
        self.assertIn(
            "classifiedUniqueSubmission =\n"
            "                            signatureCandidateSubmission[completedCandidate]",
            classifier,
        )
        self.assertIn("return unique;", classifier)
        self.assertNotIn("observeUniqueFrame(ready", classifier)
        self.assertNotIn("presentationEndpointSelector", generator)
        self.assertNotIn("private boolean selectPresentationEndpoint", generator)

        frame_loop = generator[
            generator.index("@Override public void doFrame"):
            generator.index("private void presentBuffered")
        ]
        self.assertIn("presentationEpochBeforePrepare", frame_loop)
        self.assertLess(frame_loop.index("prepareBufferedPairIfPossible()"),
                        frame_loop.index("resetHealthWindowAfterStreamChange()"))

    def test_qualified_source_clock_owns_public_scheduler_identity(self):
        controller = self.read(
            "unified-android/src/com/thorium/lucent/video/"
            "AdaptiveFrameRateController.java"
        )
        method = controller[
            controller.index("public int lockedSourceFps()"):
            controller.index("public int outputFps()")
        ]
        qualified = method.index(
            "generationAvailable && qualifiedUniqueTimestampSourceHz > 0.0"
        )
        direct_fallback = method.index("directFallbackSourceFps > 0")
        volatile_short_window = method.index("measuredProducerHz()")
        self.assertLess(qualified, direct_fallback)
        self.assertLess(qualified, volatile_short_window)
        self.assertIn(
            "return downgradeTierFor(qualifiedUniqueTimestampSourceHz,",
            method,
        )

    def test_hardware_surface_uses_core_sequence_timestamp_not_swap_jitter(self):
        backend = self.read(
            "unified-android/native/lucent_android_gles_backend.c"
        )
        fake_egl = self.read(
            "unified-android/native/tests/fake_android_egl.c"
        )
        native_test = self.read(
            "unified-android/native/tests/android_gles_backend_test.c"
        )
        stamp = backend[
            backend.index("static bool stamp_core_frame_timestamp"):
            backend.index("lucent_android_gles_create", backend.index(
                "static bool stamp_core_frame_timestamp"))
        ]
        self.assertIn('resolve_egl_symbol("eglPresentationTimeANDROID")', stamp)
        self.assertIn("lucent_retro_get_av_info", stamp)
        self.assertIn("frame_sequence -", stamp)
        self.assertIn("1000000000.0L", stamp)
        self.assertIn("backend->timestamp_source_hz", stamp)
        # 2026-09-06: see test_n64_frontend_fbo_uses_title_dynamic_written_bounds
        # for why this now reads present_current_frame rather than the thin
        # present_if_ready wrapper that calls it.
        present = backend[
            backend.index("static bool present_current_frame("):
            backend.index("bool lucent_android_gles_present_if_ready")
        ]
        self.assertLess(
            present.index("stamp_core_frame_timestamp(backend, info.frame_sequence)"),
            present.index("eglSwapBuffers"),
        )
        self.assertIn("fake_presentation_time", fake_egl)
        self.assertIn("lucent_fake_egl_presentation_time_delta", native_test)
        self.assertIn("== 16666667", native_test)

    def test_dense_proof_reservoir_survives_late_clean_baseline(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        self.assertIn("MAX_QUALIFICATION_PROOF_SAMPLES = 120", generator)
        self.assertIn("proofEvidenceEnqueuedInEpoch", generator)
        self.assertIn("MAX_QUALIFICATION_PROOF_SAMPLES", generator)

    def test_source_signature_uses_dedicated_exact_sampler2d_copy_shader(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        copy_shader = generator[generator.index("TEXTURE_COPY_SHADER"):
                                generator.index("FLOW_PROOF_SHADER")]
        self.assertIn("uniform sampler2D uTexture", copy_shader)
        self.assertIn("gl_FragColor=texture2D(uTexture,vTexCoord)", copy_shader)
        self.assertNotIn("uFlow", copy_shader)
        self.assertNotIn("decodeFlow", copy_shader)
        signature = generator[generator.index("private boolean latestImageIsUnique("):
                              generator.index("private boolean softwareImageIsUnique")]
        self.assertIn("signatureTexture", signature)
        self.assertIn("SIGNATURE_WIDTH, SIGNATURE_HEIGHT", signature)
        self.assertIn("drawTexture2d(latestTexture)", signature)
        self.assertNotIn("flowProofProgram", signature)
        self.assertNotIn('"uFlow"', signature)
        self.assertIn("int completedCandidate = -1", signature)
        self.assertIn("classifiedFrameReady = true", signature)
        self.assertIn("retainSignatureCandidate(sequence, currentTimestampNs,\n"
                      "                        completedCandidate)", signature)
        self.assertLess(signature.index(
                            "retainSignatureCandidate(sequence, currentTimestampNs,"),
                        signature.index(
                            "signatureCandidateSequence[completedCandidate] = 0L"))
        retained = generator[
            generator.index("private void retainSignatureCandidate"):
            generator.index("private void clearSignatureCandidates")
        ]
        self.assertIn("index != reservedSlot", retained)

    def test_app_owned_rife_generated_texture_has_explicit_y_origin_conversion(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        generated_shader = generator[
            generator.index("EXTERNAL_GENERATED_TEXTURE_COPY_SHADER"):
            generator.index("SIGNATURE_COMPARE_SHADER")
        ]
        self.assertIn("vec2(vTexCoord.x,1.0-vTexCoord.y)", generated_shader)
        self.assertNotIn("vec2(1.0-vTexCoord.x", generated_shader)
        app_owned_present = generator[
            generator.index("private void presentAppOwnedExternalBuffered("):
            generator.index("private int appOwnedPhysicalScansPerOutput()")
        ]
        self.assertIn(
            "drawExternalGeneratedTexture(externalGeneratedTexture)",
            app_owned_present,
        )
        self.assertNotIn(
            "drawTexture2d(externalGeneratedTexture)", app_owned_present
        )
        self.assertIn(
            "drawTexture2d(historyTextures[selectedPhase >= 1f ?",
            app_owned_present,
        )

    def test_signature_fbo_is_restored_and_fallback_copy_preserves_aspect(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        signature = generator[generator.index("private boolean latestImageIsUnique("):
                              generator.index("private boolean softwareImageIsUnique")]
        self.assertLess(signature.index("signatureTexture"),
                        signature.index("drawTexture2d(latestTexture)"))
        # v31's core occlusion query owns its comparison. Every Java return
        # restores the default framebuffer; the synchronous fallback retains
        # the original draw/read/restore ordering.
        sync_read = signature.rindex("GLES20.glReadPixels")
        self.assertLess(sync_read,
                        signature.index("glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0)",
                                        sync_read))
        self.assertIn("glViewport(0, 0, outputWidth, outputHeight)", signature)

        present = generator[generator.index("private void presentBuffered("):
                            generator.index("private void reportStats", generator.index(
                                "private void presentBuffered("))]
        self.assertIn("drawTexture2d(historyTextures[previousIndex])", present)
        self.assertNotIn("drawTexture2d(latestTexture)", present)
        viewport = generator[generator.index("private void setPresentationViewport()"):
                             generator.index("private void copyExternalTo")]
        self.assertIn("Math.round(outputHeight * aspect)", viewport)
        self.assertIn("(outputWidth - contentWidth) / 2", viewport)
        self.assertNotIn("outputWidth / aspect", viewport)

    def test_qualification_readback_requires_an_actual_generated_present(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        present = generator[generator.index("private void presentBuffered("):
                            generator.index("private void reportStats", generator.index(
                                "private void presentBuffered("))]
        self.assertIn("boolean synthetic = renderedSynthetic &&", present)
        self.assertIn("presentation == AdaptiveFrameRateController.PRESENT_SYNTHETIC",
                      present)
        self.assertIn("if (realThisTick)", present)
        self.assertIn("drawTexture2d(historyTextures[previousIndex])", present)
        self.assertIn("captureProof = synthetic && qualificationProofEnabled", present)

    def test_interpolation_uses_measured_motion_not_fixed_pixel_crossfade(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        self.assertIn("COARSE_MOTION_SHADER", generator)
        self.assertIn("REFINE_MOTION_SHADER", generator)
        self.assertIn("MOTION_INTERPOLATE_SHADER", generator)
        self.assertIn("estimateMotion()", generator)
        self.assertIn("uBackwardMotion", generator)
        self.assertIn("uForwardMotion", generator)
        self.assertIn("previousUv=clamp(vTexCoord-forward*uPhase*previousGate",
                      generator)
        self.assertIn("currentUv=clamp(vTexCoord-backward*(1.0-uPhase)*currentGate",
                      generator)
        self.assertGreaterEqual(generator.count(
            "previousGate=step(0.02,previousReliability)"), 2)
        self.assertGreaterEqual(generator.count(
            "currentGate=step(0.02,currentReliability)"), 2)
        self.assertIn("activeMotionVectors", generator)
        self.assertIn("sampleFrameProof", generator)
        self.assertIn("syntheticDistinctFromEndpoints", generator)
        self.assertIn("uPixelStep", generator)
        self.assertIn("for(int y=-2;y<=2;y++)", generator)
        self.assertIn("nonCrossfadeSyntheticPixels", generator)
        self.assertIn("motionCorrelatedProofSamples", generator)
        self.assertIn("MOTION_PREDICTION_PROOF_SHADER", generator)
        self.assertIn("drawPredictionProof(phase, false)", generator)
        self.assertIn("drawPredictionProof(phase, true)", generator)
        self.assertIn("predictionSeparation < 9", generator)
        self.assertIn("vectorPredictionError * 4 <= inverseVectorError",
                      generator)
        self.assertIn("outputHash != previousHash && outputHash != currentHash", generator)
        self.assertIn("previousCycle=length((forward+backwardAtForward)", generator)
        self.assertIn("currentCycle=length((backward+forwardAtBackward)", generator)
        self.assertIn("previousWeight=(1.0-uPhase)*(0.02+previousReliability)",
                      generator)
        self.assertIn("currentWeight=uPhase*(0.02+currentReliability)", generator)
        self.assertGreaterEqual(generator.count(
            "previousSupported=step(0.02,previousReliability)"), 2)
        self.assertGreaterEqual(generator.count(
            "currentSupported=step(0.02,currentReliability)"), 2)
        self.assertGreaterEqual(generator.count(
            "ownedPrediction=mix(a"), 2)
        self.assertGreaterEqual(generator.count(
            "ownerByPhase=step(0.5,uPhase)"), 2)
        self.assertNotIn("ownerByWeight", generator)
        self.assertGreaterEqual(generator.count(
            "mutuallyVisiblePrediction=mix(ownedPrediction,alignedPrediction,appearanceAdmission)"), 2)
        self.assertGreaterEqual(generator.count(
            "predictionAdmission=mix(1.0,anySupported,uDenseEncoding)"), 2)
        self.assertGreaterEqual(generator.count(
            "staticHud=1.0-smoothstep(6.0/255.0,20.0/255.0,endpointDelta)"), 2)
        self.assertGreaterEqual(generator.count(
            "predictionAdmission*(1.0-staticHud)"), 2)
        self.assertIn(
            "alignmentError=max(max(abs(a.r-b.r),abs(a.g-b.g)),abs(a.b-b.b))",
            generator,
        )
        self.assertIn(
            "appearanceAdmission=1.0-smoothstep(24.0/255.0,96.0/255.0,alignmentError)",
            generator,
        )
        self.assertIn("rawPrevious=texture2D(uPrevious,vTexCoord)", generator)
        self.assertIn("rawCurrent=texture2D(uCurrent,vTexCoord)", generator)
        self.assertIn("exactEndpoint=mix(rawPrevious,rawCurrent,nearestEndpoint)",
                      generator)
        self.assertNotIn("flow*=sqrt(clamp(field.b,0.0,1.0))", generator)
        self.assertNotIn("mix(a.rgb,b.rgb,uPhase)", generator)
        self.assertNotIn('" vec4 a=texture2D(uPrevious,vTexCoord);', generator)
        self.assertNotIn('" vec4 b=texture2D(uCurrent,vTexCoord);', generator)

    def test_motion_is_measured_in_both_directions_not_faked_by_negation(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        estimate = generator[generator.index("private void estimateMotion()"):
                             generator.index("private void copyTexture", generator.index(
                                 "private void estimateMotion()"))]
        self.assertIn(
            "estimateMotionPass(historyTextures[previousIndex],\n"
            "                historyTextures[currentIndex], flowTextures,\n"
            "                globalCandidateTextures[0], globalCandidateWinnerTextures[0],\n"
            "                globalFlowTextures[0])", estimate)
        self.assertIn(
            "estimateMotionPass(historyTextures[currentIndex],\n"
            "                historyTextures[previousIndex], reverseFlowTextures,\n"
            "                globalCandidateTextures[1], globalCandidateWinnerTextures[1],\n"
            "                globalFlowTextures[1])", estimate)
        self.assertEqual(estimate.count("estimateMotionPass("), 3)
        self.assertNotIn("=-flow", estimate)
        self.assertNotIn("=-motion", estimate)

    def test_matcher_uses_patch_support_ambiguity_and_zero_motion_prior(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        coarse = generator[generator.index("COARSE_MOTION_SHADER"):
                           generator.index("REFINE_MOTION_SHADER")]
        refine = generator[generator.index("REFINE_MOTION_SHADER"):
                           generator.index("MOTION_INTERPOLATE_SHADER")]
        for shader in (coarse, refine):
            self.assertIn("uTexel.x*6.0", shader)
            self.assertIn("vTexCoord+dx+dy", shader)
            self.assertIn("0.035*dot(normalized,normalized)", shader)
            self.assertIn("4.0*length((vTexCoord+motion)-p)", shader)
        self.assertIn("float second=1000.0", coarse)
        self.assertIn("(second-score)/(second+", coarse)
        self.assertNotIn("float second=1000.0", refine)
        self.assertNotIn("(second-score)/(second+", refine)
        self.assertIn("sqrt(gain)*(0.55+0.45*coarse.b)", refine)
        self.assertNotIn("max(coarse.b*0.7,gain)", refine)
        regularize = generator[generator.index("REGULARIZE_MOTION_SHADER"):
                               generator.index("MOTION_INTERPOLATE_SHADER")]
        self.assertIn("uFlowTexel.x*2.0", regularize)
        self.assertIn("seedCount=step(0.10,l.b)", regularize)
        self.assertIn("distance(mean,vectorOf(l))", regularize)
        self.assertIn("1.0-2.5*deviation", regularize)
        self.assertIn("smoothstep(2.0,3.0,seedCount)", regularize)
        self.assertIn("max(c.b,neighborConfidence*0.90)", regularize)
        self.assertIn("sqrt(sourceConfidence)*coherence*clamp(1.35*sqrt(support)",
                      regularize)
        estimate = generator[generator.index("private void estimateMotionPass"):
                             generator.index("private void copyTexture")]
        self.assertIn("destinationFlow[2]", estimate)
        self.assertIn("regularizeMotionProgram", estimate)
        self.assertIn('"uFlow", destinationFlow[1]', estimate)

    def test_regional_fallback_is_source_backed_overlapping_and_bidirectional(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        reduction = generator[generator.index("GLOBAL_MOTION_REDUCTION_SHADER"):
                              generator.index("MOTION_INTERPOLATE_SHADER")]
        self.assertIn("vec2(12.0,8.0)", reduction)
        self.assertIn("uniform sampler2D uWinners", reduction)
        self.assertIn("for(int y=0;y<4;y++)", reduction)
        self.assertIn("for(int x=0;x<4;x++)", reduction)
        self.assertIn("uniform sampler2D uPrevious", reduction)
        self.assertIn("uniform sampler2D uCurrent", reduction)
        winner = generator[generator.index("REGIONAL_CANDIDATE_WINNER_SHADER"):
                           generator.index("GLOBAL_MOTION_REDUCTION_SHADER")]
        self.assertIn("vec2(60.0,40.0)", winner)
        self.assertIn("for(int y=0;y<5;y++)", winner)
        self.assertIn("for(int x=0;x<5;x++)", winner)
        self.assertIn("smoothstep(9.0,11.0,support)", reduction)
        self.assertIn("smoothstep(3.5,4.0,quadrants)", reduction)
        self.assertIn("constantNeighborGate=step(min(2.0,available)-0.5,neighbors)",
                      reduction)
        self.assertIn("horizontalGradient=leftOk*rightOk", reduction)
        self.assertIn("verticalGradient=downOk*upOk", reduction)
        self.assertIn("distance(vectorOf(left),vectorOf(right)),0.45", reduction)
        self.assertIn("neighborGate=max(constantNeighborGate,gradientNeighborGate)",
                      reduction)
        self.assertIn("(zeroMotionCost-bestCost)/(zeroMotionCost+0.02)", reduction)
        coarse_lattice = generator[
            generator.index("REGIONAL_COARSE_CANDIDATE_SHADER"):
            generator.index("REGIONAL_FINE_CANDIDATE_SHADER")]
        fine_lattice = generator[
            generator.index("REGIONAL_FINE_CANDIDATE_SHADER"):
            generator.index("REGIONAL_CANDIDATE_WINNER_SHADER")]
        self.assertNotIn("uniform sampler2D uFlow", coarse_lattice)
        aligned_samples = (
            "vec2 center=(region+0.5)/vec2(12.0,8.0)",
            "vec2 local=(vec2(x,y)+0.5)/4.0-0.5",
            "local*vec2(1.5/12.0,1.5/8.0)",
            "for(int y=0;y<4;y++){for(int x=0;x<4;x++)",
        )
        for shader in (coarse_lattice, fine_lattice, reduction):
            for source in aligned_samples:
                self.assertIn(source, shader)
        for shader in (coarse_lattice, fine_lattice):
            self.assertIn("cost/16.0", shader)
            self.assertIn("support/16.0", shader)
        self.assertIn("float coherent=step(9.5/16.0,candidate.a)", winner)
        self.assertIn("coherent>bestCoherent", winner)
        self.assertIn("bestCost/=16.0; zeroMotionCost/=16.0", reduction)
        self.assertIn("step(9.5/16.0,left.a)", reduction)
        self.assertIn("support/16.0", reduction)
        self.assertIn("candidateCell-vec2(2.0)", coarse_lattice)
        self.assertIn("uniform vec2 uCoarseStep", coarse_lattice)
        self.assertIn("uniform sampler2D uCoarseWinner", fine_lattice)
        self.assertIn("uniform vec2 uFineStep", fine_lattice)
        estimate = generator[generator.index("private void estimateMotionPass"):
                             generator.index("private void copyTexture")]
        self.assertIn('"uFlow", destinationFlow[1]', estimate)
        self.assertIn('"uPrevious", previousTexture', estimate)
        self.assertIn('"uCurrent", currentTexture', estimate)
        self.assertIn("destinationGlobalFlow", estimate)
        regional_estimate = estimate[estimate.index("// Coarse fixed lattice"):
                                     estimate.index("GLES20.glBindFramebuffer(",
                                                    estimate.index("// Apply the unchanged"))]
        self.assertNotIn('"uFlow", destinationFlow[1]', regional_estimate)
        interpolation = generator[generator.index("MOTION_INTERPOLATE_SHADER"):
                                  generator.index("MOTION_PREDICTION_PROOF_SHADER")]
        self.assertIn("globalBackwardPeer", interpolation)
        self.assertIn("globalForwardPeer", interpolation)
        self.assertIn("1.0-5.0*previousGlobalCycle", interpolation)
        self.assertIn("1.0-5.0*currentGlobalCycle", interpolation)
        self.assertIn("1.0-smoothstep(0.04,0.18,previousReliability)", interpolation)
        self.assertIn("mix(forward,globalForward,previousGlobalUse)", interpolation)
        self.assertIn("mix(backward,globalBackward,currentGlobalUse)", interpolation)

    def test_quad_binding_tolerates_global_reducer_optimized_texcoord(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        reduction = generator[generator.index("GLOBAL_MOTION_REDUCTION_SHADER"):
                              generator.index("MOTION_INTERPOLATE_SHADER")]
        # The reducer intentionally samples a fixed grid and may therefore
        # have aTexCoord removed by a production GLES linker.
        self.assertNotIn("vTexCoord+", reduction)
        self.assertNotIn("texture2D(uFlow,vTexCoord)", reduction)
        binder = generator[generator.index("private void bindQuad(int program)"):
                           generator.index("private void releaseGl()")]
        self.assertIn('glGetAttribLocation(program, "aPosition")', binder)
        self.assertIn('glGetAttribLocation(program, "aTexCoord")', binder)
        self.assertIn("if (position < 0)", binder)
        self.assertIn("if (texture >= 0)", binder)
        optional = binder[binder.index("if (texture >= 0)"):]
        self.assertIn("glEnableVertexAttribArray(texture)", optional)
        self.assertIn("glVertexAttribPointer(texture", optional)
        self.assertNotIn("glEnableVertexAttribArray(texture)",
                         binder[:binder.index("if (texture >= 0)")])
        self.assertNotIn("glVertexAttribPointer(texture",
                         binder[:binder.index("if (texture >= 0)")])

    @staticmethod
    def _smoothstep(edge0, edge1, value):
        t = max(0.0, min(1.0, (value - edge0) / (edge1 - edge0)))
        return t * t * (3.0 - 2.0 * t)

    @staticmethod
    def _coarse_fine_lattice_winner(previous, current, region_x, region_y,
                                    flow_range=(0.20, 0.20),
                                    coarse_step=(0.04, 0.04),
                                    fine_step=(0.01, 0.01),
                                    native_step=None):
        """CPU mirror of v21's support-aware regional candidates."""
        def clamp(value):
            return max(0.0, min(1.0, value))

        center_u = (region_x + 0.5) / 12.0
        center_v = (region_y + 0.5) / 8.0
        points = [(
            clamp(center_u + (((x + 0.5) / 4.0) - 0.5) * 1.5 / 12.0),
            clamp(center_v + (((y + 0.5) / 4.0) - 0.5) * 1.5 / 8.0),
        ) for y in range(4) for x in range(4)]

        def evaluate(motion):
            total = 0.0
            support = 0
            for u, v in points:
                peer_u, peer_v = clamp(u + motion[0]), clamp(v + motion[1])
                base = abs(current(u, v) - previous(u, v))
                error = abs(current(u, v) - previous(peer_u, peer_v)) + \
                    3.0 * math.hypot((u + motion[0]) - peer_u,
                                     (v + motion[1]) - peer_v)
                total += min(error, 0.30)
                support += error <= 0.18 and base - error >= 0.008
            return total / 16.0, support

        def choose(candidates):
            return min(candidates, key=lambda motion: (
                0 if evaluate(motion)[1] >= 10 else 1,
                evaluate(motion)[0],
            ))

        coarse = [(x * coarse_step[0], y * coarse_step[1])
                  for y in range(-2, 3) for x in range(-2, 3)]
        coarse_best = choose(coarse)
        fine = [(
            max(-flow_range[0], min(flow_range[0],
                coarse_best[0] + x * fine_step[0])),
            max(-flow_range[1], min(flow_range[1],
                coarse_best[1] + y * fine_step[1])),
        ) for y in range(-2, 3) for x in range(-2, 3)]
        best = choose(fine)
        if native_step is not None:
            native = [(
                max(-flow_range[0], min(flow_range[0],
                    best[0] + x * native_step[0])),
                max(-flow_range[1], min(flow_range[1],
                    best[1] + y * native_step[1])),
            ) for y in range(-2, 3) for x in range(-2, 3)]
            best = choose(native)
        return (best[0] / flow_range[0], best[1] / flow_range[1]), \
            evaluate(best)[0], evaluate((0.0, 0.0))[0], evaluate(best)[1]

    def test_fixed_coarse_fine_lattice_finds_motion_without_raw_flow_seed(self):
        pattern = lambda u, v: 0.5 + 0.24 * math.sin(19.0 * u + 7.0 * v) + \
            0.18 * math.sin(11.0 * v - 3.0 * u)
        current = lambda u, v: pattern(max(0.0, min(1.0, u + 0.05)),
                                       max(0.0, min(1.0, v - 0.03)))
        winners = [self._coarse_fine_lattice_winner(
            pattern, current, x, y) for y in range(8) for x in range(12)]
        interior = [winners[y * 12 + x]
                    for y in range(1, 7) for x in range(1, 11)]
        close = 0
        for vector, best_cost, zero_cost, support in interior:
            close += (abs(vector[0] - 0.25) <= 0.051 and
                      abs(vector[1] + 0.15) <= 0.051)
            self.assertLess(best_cost, zero_cost)
            self.assertGreaterEqual(support, 10)
        self.assertGreaterEqual(close, len(interior) * 0.90)
        static_vector, static_cost, static_zero, static_support = \
            self._coarse_fine_lattice_winner(pattern, pattern, 2, 2)
        self.assertEqual(static_vector, (0.0, 0.0))
        self.assertEqual(static_cost, static_zero)
        self.assertEqual(static_support, 0)

    def test_v19_wide_range_is_reverted_to_bounded_v18_span(self):
        pattern = lambda u, v: 0.5 + 0.21 * math.sin(13.0 * u + 5.0 * v) + \
            0.17 * math.sin(7.0 * v - 4.0 * u)
        current = lambda u, v: pattern(max(0.0, min(1.0, u + 0.18)), v)
        vector, best_cost, zero_cost, support = \
            self._coarse_fine_lattice_winner(pattern, current, 6, 4)
        self.assertLessEqual(abs(vector[0]), 0.51)
        self.assertGreater(best_cost, 0.0)
        # Five coarse and five fine candidates remain exactly fixed; v21 adds
        # precision only after the bounded winner on low-resolution sources.
        self.assertEqual(5 * 5, 25)

    def test_native_pixel_refinement_reaches_odd_nes_scroll_displacements(self):
        # At 256x240 the production regional steps are 8, 2, then 1 source
        # pixels. The v20 two-stage lattice contains only even displacements;
        # v21's final stage contains every integer within two pixels of its
        # selected even winner, including both fixture motions (+1 and -7).
        def reachable(coarse, fine, native=None):
            first = {coarse * value for value in range(-2, 3)}
            second = {center + fine * value
                      for center in first for value in range(-2, 3)}
            if native is None:
                return second
            return {center + native * value
                    for center in second for value in range(-2, 3)}

        even_only = reachable(8, 2)
        native_pixel = reachable(8, 2, 1)
        for displacement in (1, -7):
            self.assertNotIn(displacement, even_only)
            self.assertIn(displacement, native_pixel)

    def test_native_pixel_refinement_finds_bidirectional_nes_scale_motion(self):
        width, height = 256, 240
        flow_pixels = 24.0
        flow_range = flow_pixels / width, flow_pixels / height
        coarse_step = 8.0 / width, 8.0 / height
        fine_step = 2.0 / width, 2.0 / height
        native_step = 1.0 / width, 1.0 / height

        def clamp(value):
            return max(0.0, min(1.0, value))

        # Structured pixel-scale content with independent horizontal and
        # vertical frequencies. It is deterministic and deliberately avoids
        # the fixture's repeated eight-tile ambiguity.
        def pattern(u, v):
            return (0.50 + 0.22 * math.sin(91.0 * u + 13.0 * v) +
                    0.19 * math.sin(47.0 * v - 17.0 * u))

        for pixels in (1.0, -7.0):
            shift = pixels / width
            current = lambda u, v, amount=shift: pattern(clamp(u + amount), v)
            backward = self._coarse_fine_lattice_winner(
                pattern, current, 6, 4, flow_range, coarse_step, fine_step,
                native_step)
            forward = self._coarse_fine_lattice_winner(
                current, pattern, 6, 4, flow_range, coarse_step, fine_step,
                native_step)
            expected = pixels / flow_pixels
            self.assertAlmostEqual(backward[0][0], expected, places=6)
            self.assertAlmostEqual(forward[0][0], -expected, places=6)
            self.assertAlmostEqual(backward[0][0] + forward[0][0], 0.0,
                                   places=6)
            self.assertGreaterEqual(backward[3], 10)
            self.assertGreaterEqual(forward[3], 10)

    def test_native_pixel_refinement_is_low_resolution_only_and_ping_ponged(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        estimate = generator[generator.index("private void estimateMotionPass"):
                             generator.index("private void copyTexture")]
        native = estimate[estimate.index("// Native-resolution consoles"):
                          estimate.index("// Apply the unchanged", estimate.index(
                              "// Native-resolution consoles"))]
        self.assertIn(
            "Math.min(historyWidth, historyHeight) < HIGH_RES_FLOW_THRESHOLD",
            native)
        self.assertIn("destinationGlobalCandidates", native)
        self.assertIn('"uCoarseWinner",\n                    destinationGlobalWinner',
                      native)
        self.assertIn("1f / Math.max(1f, historyWidth)", native)
        self.assertIn("1f / Math.max(1f, historyHeight)", native)
        self.assertIn("destinationGlobalWinner", native)
        self.assertEqual(native.count("GLES20.glDrawArrays("), 2)
        self.assertTrue(min(256, 240) < 720)
        self.assertFalse(min(1920, 1080) < 720)

    def test_candidate_objective_rejects_sparse_aggregate_cost_winner(self):
        # This is the exact ordering embedded in the winner shader. v17 picked
        # the lowest aggregate cost even when only four sites improved; v18
        # first requires coherent 10/16 support, then compares cost.
        candidates = [
            {"name": "sparse", "support": 4, "cost": 0.010},
            {"name": "coherent", "support": 10, "cost": 0.030},
            {"name": "coherent-worse", "support": 12, "cost": 0.045},
        ]
        winner = min(candidates, key=lambda item: (
            0 if item["support"] >= 10 else 1,
            item["cost"],
        ))
        self.assertEqual(winner["name"], "coherent")
        self.assertEqual(min(candidates, key=lambda item: item["cost"])["name"],
                         "sparse")

    @staticmethod
    def _candidate_neighbor_class_rgba8(winners, region):
        """Exact CPU mirror: bit 0 constant, bit 1 affine-gradient."""
        width, height = 12, 8

        def vector(cell):
            return cell[0] / 255.0 * 2.0 - 1.0, \
                cell[1] / 255.0 * 2.0 - 1.0

        x, y = region % width, region // width
        peers = ((region - 1, x > 0), (region + 1, x + 1 < width),
                 (region - width, y > 0),
                 (region + width, y + 1 < height))
        center = vector(winners[region])
        available = compatible = 0
        coherent = [False] * 4
        vectors = [(0.0, 0.0)] * 4
        for index, (peer, valid) in enumerate(peers):
            if not valid:
                continue
            available += 1
            coherent[index] = winners[peer][3] >= 159
            vectors[index] = vector(winners[peer])
            if coherent[index] and math.dist(center, vectors[index]) <= 0.18:
                compatible += 1
        constant = compatible >= min(2, available)

        def gradient(left, right):
            midpoint = ((left[0] + right[0]) * 0.5,
                        (left[1] + right[1]) * 0.5)
            return (math.dist(center, midpoint) <= 0.18 and
                    math.dist(left, right) <= 0.45)

        varying = ((coherent[0] and coherent[1] and
                    gradient(vectors[0], vectors[1])) or
                   (coherent[2] and coherent[3] and
                    gradient(vectors[2], vectors[3])))
        return (1 if constant else 0) | (2 if varying else 0)

    def test_rgba8_neighbor_gate_accepts_coherence_and_rejects_fragmentation(self):
        # A encodes exact candidate support/16. The vectors are deliberately
        # quantized before comparison, exactly as bounded proof observes them.
        coherent = [(153, 121, 80, 191) for _ in range(96)]
        self.assertEqual(self._candidate_neighbor_class_rgba8(coherent, 40) & 1, 1)

        fragmented = []
        for y in range(8):
            for x in range(12):
                fragmented.append(
                    (217 if (x + y) % 2 else 38, 128, 80, 191))
        self.assertEqual(self._candidate_neighbor_class_rgba8(fragmented, 40), 0)

        low_support = list(coherent)
        for peer in (39, 41, 28, 52):
            low_support[peer] = (153, 121, 80, 143)
        self.assertEqual(self._candidate_neighbor_class_rgba8(low_support, 40), 0)

    def test_rgba8_affine_neighbor_accepts_slope_but_rejects_curvature(self):
        def encoded(x, support=191):
            return (round((x * 0.5 + 0.5) * 255), 128, 80, support)

        center = 40
        affine = [encoded(0.0, 0) for _ in range(96)]
        affine[center] = encoded(0.0)
        affine[center - 1] = encoded(-0.20)
        affine[center + 1] = encoded(0.20)
        self.assertEqual(self._candidate_neighbor_class_rgba8(affine, center), 2)

        curved = list(affine)
        curved[center - 1] = encoded(0.20)
        self.assertEqual(self._candidate_neighbor_class_rgba8(curved, center), 0)

    @classmethod
    def _regional_consensus_mirror(cls, previous, current, fields,
                                   flow_range=(0.20, 0.20)):
        """CPU mirror of v18's aligned 12x8 overlapping reducer."""
        def clamp(value):
            return max(0.0, min(1.0, value))

        def points(region_x, region_y):
            center_u = (region_x + 0.5) / 12.0
            center_v = (region_y + 0.5) / 8.0
            return [(
                clamp(center_u + (((x + 0.5) / 4.0) - 0.5) * 1.5 / 12.0),
                clamp(center_v + (((y + 0.5) / 4.0) - 0.5) * 1.5 / 8.0),
                x, y,
            ) for y in range(4) for x in range(4)]

        def cost(region_x, region_y, candidate):
            dx = candidate[0] * flow_range[0]
            dy = candidate[1] * flow_range[1]
            total = 0.0
            for u, v, _x, _y in points(region_x, region_y):
                pu, pv = clamp(u + dx), clamp(v + dy)
                error = abs(current(u, v) - previous(pu, pv))
                error += 3.0 * math.hypot((u + dx) - pu, (v + dy) - pv)
                total += min(error, 0.30)
            return total / 16.0

        selected = [[None for _x in range(12)] for _y in range(8)]
        for region_y in range(8):
            for region_x in range(12):
                candidates = [(0.0, 0.0)] + fields[region_y][region_x]
                def support(value):
                    dx, dy = value[0] * flow_range[0], value[1] * flow_range[1]
                    count = 0
                    for u, v, _x, _y in points(region_x, region_y):
                        base = abs(current(u, v) - previous(u, v))
                        moved = abs(current(u, v) - previous(
                            clamp(u + dx), clamp(v + dy)))
                        count += base - moved >= 0.008 and moved <= 0.18
                    return count
                best = min(candidates, key=lambda value: (
                    0 if support(value) >= 10 else 1,
                    cost(region_x, region_y, value),
                ))
                selected[region_y][region_x] = (
                    best,
                    cost(region_x, region_y, best),
                    cost(region_x, region_y, (0.0, 0.0)),
                    support(best),
                )

        result = [[None for _x in range(12)] for _y in range(8)]
        for region_y in range(8):
            for region_x in range(12):
                best, best_cost, zero_cost, _candidate_support = \
                    selected[region_y][region_x]
                dx, dy = best[0] * flow_range[0], best[1] * flow_range[1]
                support = 0
                quadrants = set()
                for u, v, x, y in points(region_x, region_y):
                    base = abs(current(u, v) - previous(u, v))
                    moved = abs(current(u, v) - previous(
                        clamp(u + dx), clamp(v + dy)))
                    if base - moved >= 0.008 and moved <= 0.18:
                        support += 1
                        quadrants.add((x >= 2, y >= 2))
                neighbors = 0
                peer_vectors = {}
                for peer_x, peer_y in ((region_x - 1, region_y),
                                       (region_x + 1, region_y),
                                       (region_x, region_y - 1),
                                       (region_x, region_y + 1)):
                    if not (0 <= peer_x < 12 and 0 <= peer_y < 8):
                        continue
                    peer, _peer_cost, _peer_zero, peer_support = \
                        selected[peer_y][peer_x]
                    peer_vectors[(peer_x, peer_y)] = (peer, peer_support)
                    if (peer_support >= 10 and
                            math.dist(best, peer) <= 0.18):
                        neighbors += 1
                gradient = False
                for first, second in (
                        ((region_x - 1, region_y), (region_x + 1, region_y)),
                        ((region_x, region_y - 1), (region_x, region_y + 1))):
                    if first not in peer_vectors or second not in peer_vectors:
                        continue
                    left, left_support = peer_vectors[first]
                    right, right_support = peer_vectors[second]
                    midpoint = ((left[0] + right[0]) * 0.5,
                                (left[1] + right[1]) * 0.5)
                    gradient |= (left_support >= 10 and right_support >= 10 and
                                 math.dist(best, midpoint) <= 0.18 and
                                 math.dist(left, right) <= 0.45)
                gain = max(0.0, min(1.0,
                                    (zero_cost - best_cost) /
                                    (zero_cost + 0.02)))
                confidence = (
                    math.sqrt(gain) * cls._smoothstep(9.0, 11.0, support) *
                    cls._smoothstep(3.5, 4.0, len(quadrants)) *
                    (1.0 if neighbors >= 2 or gradient else 0.0) *
                    (1.0 - cls._smoothstep(0.10, 0.20, best_cost)) *
                    cls._smoothstep(0.006, 0.018, math.hypot(*best))
                )
                result[region_y][region_x] = best, confidence, support
        return result

    def test_perspective_regional_motion_passes_without_one_global_vector(self):
        pattern = lambda u, v: 0.5 + 0.24 * math.sin(19.0 * u + 7.0 * v) + \
            0.18 * math.sin(11.0 * v - 3.0 * u)

        def motion_at(u):
            return 0.13 + 0.08 * (u - 0.5), -0.05

        current = lambda u, v: pattern(
            max(0.0, min(1.0, u + motion_at(u)[0] * 0.20)),
            max(0.0, min(1.0, v + motion_at(u)[1] * 0.20)),
        )
        fields = []
        for region_y in range(8):
            row = []
            for region_x in range(12):
                motion = motion_at((region_x + 0.5) / 12.0)
                candidates = [motion for _ in range(16)]
                candidates[(region_x + region_y) % 16] = (-0.55, 0.35)
                row.append(candidates)
            fields.append(row)
        result = self._regional_consensus_mirror(pattern, current, fields)
        accepted = [cell for row in result for cell in row if cell[1] > 0.15]
        self.assertGreaterEqual(len(accepted), 64)
        self.assertLess(result[1][0][0][0], result[1][11][0][0])

    def test_static_and_cardinally_conflicting_regional_flow_is_rejected(self):
        pattern = lambda u, v: 0.5 + 0.3 * math.sin(17.0 * u + 9.0 * v)
        sparse = [[[((0.30, -0.05) if index == 0 else (0.0, 0.0))
                    for index in range(16)] for _x in range(12)] for _y in range(8)]
        static_result = self._regional_consensus_mirror(
            pattern, pattern, sparse)
        self.assertTrue(all(cell[1] == 0.0 for row in static_result for cell in row))

        # Every cardinal neighbor proposes the opposite vector. Even when a
        # local patch prefers motion, the shared-consistency gate rejects it.
        conflict = []
        for region_y in range(8):
            row = []
            for region_x in range(12):
                motion = (0.24 if (region_x + region_y) % 2 == 0 else -0.24, 0.0)
                row.append([motion for _ in range(16)])
            conflict.append(row)
        split = lambda u, v: pattern(max(0.0, min(1.0,
            u + (0.048 if (int(u * 12) + int(v * 8)) % 2 == 0 else -0.048))), v)
        conflict_result = self._regional_consensus_mirror(pattern, split, conflict)
        self.assertTrue(all(cell[1] == 0.0 for row in conflict_result for cell in row))

    def test_regional_fallback_requires_reverse_consistency_and_yields_to_local(self):
        def reliability(backward, forward, backward_conf, forward_conf):
            cycle = math.hypot(backward[0] + forward[0],
                               backward[1] + forward[1])
            return math.sqrt(backward_conf * forward_conf) * max(0.0, 1.0 - 5.0 * cycle)

        coherent = reliability((0.20, -0.04), (-0.20, 0.04), 0.5, 0.5)
        conflicting = reliability((0.20, -0.04), (0.20, -0.04), 0.5, 0.5)
        self.assertGreater(coherent, 0.24)
        self.assertEqual(conflicting, 0.0)
        global_gate = self._smoothstep(0.10, 0.24, coherent)
        low_local_use = global_gate * (1.0 - self._smoothstep(0.04, 0.18, 0.01))
        trusted_local_use = global_gate * (1.0 - self._smoothstep(0.04, 0.18, 0.30))
        self.assertGreater(low_local_use, 0.95)
        self.assertEqual(trusted_local_use, 0.0)

    def test_regional_flow_telemetry_is_bounded_to_proof_callbacks(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        proof = generator[generator.index("private void sampleFrameProof"):
                          generator.index("private void drawPredictionProof")]
        self.assertIn("sampleRegionalFlowTelemetry()", proof)
        telemetry = generator[generator.index(
            "private void sampleRegionalFlowTelemetry"):
            generator.index("private void drawPredictionProof")]
        self.assertIn("globalFlowTextures[0]", telemetry)
        self.assertIn("globalFlowTextures[1]", telemetry)
        self.assertIn("globalCandidateWinnerTextures[0]", telemetry)
        self.assertIn("globalCandidateWinnerTextures[1]", telemetry)
        self.assertIn("backwardCandidateSupport >= 159", telemetry)
        self.assertIn("candidateTouchesBoundary(", telemetry)
        self.assertIn("backwardIsCoherent && backwardIsBoundary", telemetry)
        self.assertIn("backwardIsBoundary) ++backwardAcceptedBoundary", telemetry)
        self.assertIn("candidateNeighborClass(", telemetry)
        self.assertIn("backwardConstantNeighbor", telemetry)
        self.assertIn("backwardGradientNeighbor", telemetry)
        self.assertIn("forwardCycleAccepted", telemetry)
        self.assertIn("backwardConfidence >= 26 && reliability > 0.10", telemetry)
        self.assertIn("forwardConfidence >= 26 && forwardReliability > 0.10",
                      telemetry)
        self.assertIn("latticeRegionSamples += REGIONAL_FLOW_CELLS", telemetry)
        self.assertIn("REGIONAL_FLOW_WIDTH, REGIONAL_FLOW_HEIGHT", telemetry)
        self.assertIn("regionalFlowRegionSamples += REGIONAL_FLOW_CELLS", telemetry)
        self.assertIn("regionalBackwardSupportedRegions += backwardSupported",
                      telemetry)
        self.assertIn("backwardSupport >= 159", telemetry)
        self.assertIn("sampleRegionalChannel(forward, peerU, peerV, 2)", telemetry)
        estimate = generator[generator.index("private void estimateMotionPass"):
                             generator.index("private void copyTexture")]
        self.assertNotIn("glReadPixels", estimate)
        self.assertIn('" regionalFlowRegionSamples="', generator)
        self.assertIn('" regionalBackwardCycleAcceptedRegions="', generator)
        self.assertIn('" regionalForwardCycleAcceptedRegions="', generator)
        self.assertIn('" latticeBackwardCoherentRegions="', generator)
        self.assertIn('" latticeBackwardBoundaryRegions="', generator)
        self.assertIn('" latticeBackwardCoherentBoundaryRegions="', generator)
        self.assertIn('" regionalBackwardNeighborRegions="', generator)
        self.assertIn('" regionalBackwardConstantNeighborRegions="', generator)
        self.assertIn('" regionalBackwardGradientNeighborRegions="', generator)
        self.assertIn('" regionalBackwardAcceptedBoundaryRegions="', generator)

    def test_full_hd_matcher_work_is_reduced_without_weakening_patch_cost(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        self.assertIn("LOW_RES_FINE_FLOW_DIVISOR = 16", generator)
        self.assertIn("HIGH_RES_FINE_FLOW_DIVISOR = 36", generator)
        self.assertIn("HIGH_RES_COARSE_FLOW_DIVISOR = 54", generator)
        self.assertIn("HIGH_RES_FLOW_THRESHOLD = 720", generator)
        self.assertIn("shorterSide >= HIGH_RES_FLOW_THRESHOLD", generator)
        coarse = generator[generator.index("COARSE_MOTION_SHADER"):
                           generator.index("REFINE_MOTION_SHADER")]
        self.assertIn("for(int y=-3;y<=3;y++)", coarse)
        self.assertIn("for(int x=-3;x<=3;x++)", coarse)
        estimate = generator[generator.index("private void estimateMotionPass"):
                             generator.index("private void copyTexture")]
        self.assertIn("flowLimit / 3f", estimate)
        self.assertIn("flowLimit / 12f", estimate)
        self.assertIn("Math.min(8f, Math.max(2f, flowLimit / 2f))", estimate)
        self.assertIn("Math.min(2f,", estimate)

        # Fragment-cost estimate for one direction at 1920x1080. Patch taps
        # remain nine; only field density and coarse candidate count change.
        old = (80 * 45 * 80 * 9) + (120 * 67 * 49 * 9)
        optimized = (35 * 20 * 48 * 9) + (53 * 30 * 49 * 9)
        self.assertGreater(old / optimized, 3.0)

        # High-resolution sources retain v20's two fixed 5x5 stages exactly.
        # Low-resolution sources add one equally bounded candidate+winner
        # stage. Both costs are independent of output resolution, and the
        # extra native-pixel work is absent from the GameCube path.
        high_resolution_regional = 2 * ((2 * 96 * 25 * 16 * 3) +
                                        (2 * 96 * 25) +
                                        (96 * (5 + 16 * 4)))
        low_resolution_regional = high_resolution_regional + \
            2 * ((96 * 25 * 16 * 3) + (96 * 25))
        self.assertLess(high_resolution_regional / optimized, 0.50)
        self.assertLess(low_resolution_regional / optimized, 0.75)

        # A native 256x192 handheld source must retain its former /16 field.
        self.assertEqual((256 // 16, 192 // 16), (16, 12))

    def test_supported_patch_rejects_a_single_feature_false_match(self):
        # A deliberately adversarial pair: the center and the old +/-2 cross
        # are copied at a false displacement, but the surrounding 13x13 patch
        # is stationary. Point/cross matching selects the false cell-wide
        # warp; the production patch weights correctly retain zero motion.
        old_zero = 1.0 + 4 * 0.45
        old_false = 0.0
        robust_zero = 1.4
        robust_false = 4 * 0.55 + 4 * 0.4 + 0.035 * (8 / 80) ** 2
        self.assertLess(old_false, old_zero)
        self.assertLess(robust_zero, robust_false)

    def test_spatial_fallback_zeroes_fragmented_cell_confidence(self):
        def filtered_confidence(center_confidence, center_vector, neighbors):
            trusted = [(vector, confidence) for vector, confidence in neighbors
                       if confidence >= 0.10]
            seed_count = len(trusted)
            seed_gate = 1.0 if seed_count >= 3 else 0.0
            seed_weight = sum(confidence for _vector, confidence in trusted)
            mean = (sum(vector * confidence for vector, confidence in trusted) /
                    seed_weight) if seed_weight else 0.0
            deviations = [abs(mean - vector) for vector, _confidence in trusted]
            if center_confidence >= 0.10:
                deviations.append(abs(center_vector - mean))
            deviation = max(deviations, default=0.0)
            coherence = max(0.0, min(1.0, 1.0 - 2.5 * deviation))
            neighbor_confidence = ((seed_weight / max(seed_count, 1)) * seed_gate)
            source_confidence = max(center_confidence,
                                    neighbor_confidence * 0.90)
            support = min(1.0, seed_weight * 0.25) * seed_gate
            confidence = (source_confidence ** 0.5 * coherence *
                          min(1.0, 1.35 * support ** 0.5))
            return confidence, mean

        coherent = [(0.20, 0.8), (0.22, 0.8), (0.19, 0.8), (0.21, 0.8)] * 2
        fragmented = [(-0.60, 0.8), (0.75, 0.8), (-0.45, 0.8), (0.62, 0.8)] * 2
        unsupported = [(0.20, 0.0)] * 8
        self.assertGreater(filtered_confidence(0.8, 0.2, coherent)[0], 0.70)
        self.assertEqual(filtered_confidence(0.8, 0.2, fragmented)[0], 0.0)
        self.assertEqual(filtered_confidence(0.8, 0.2, unsupported)[0], 0.0)

        # A textureless center may inherit only a three-or-more-seed coherent
        # field. Two matching seeds are deliberately insufficient.
        propagated = [(0.30, 0.30)] * 4 + [(0.0, 0.0)] * 4
        insufficient = [(0.30, 0.30)] * 2 + [(0.0, 0.0)] * 6
        propagated_confidence, propagated_vector = filtered_confidence(
            0.0, -0.8, propagated)
        self.assertGreater(propagated_confidence, 48 / 255)
        self.assertAlmostEqual(propagated_vector, 0.30)
        self.assertEqual(filtered_confidence(0.0, -0.8, insufficient)[0], 0.0)

    def test_coherent_shallow_minimum_survives_fine_confidence(self):
        # Mirrors the production v10 equations for slow motion. Adjacent 1px
        # candidates can differ by only one percent without being a distant
        # ambiguity; coarse trust + spatial agreement must keep it measurable.
        gain = 0.05
        coarse_confidence = 0.0
        fine = gain ** 0.5 * (0.55 + 0.45 * coarse_confidence)
        support = min(1.0, 8 * fine * 0.25)
        regularized = fine ** 0.5 * min(1.0, 1.35 * support ** 0.5)
        self.assertGreater(regularized, 48 / 255)

        old_adjacent_uniqueness = 0.01
        old_fine = (gain * old_adjacent_uniqueness) ** 0.5 * 0.35
        old_support = min(1.0, 4 * old_fine * 0.5)
        old_regularized = old_fine * old_support
        self.assertLess(old_regularized, 48 / 255)

    def test_occlusion_weight_prevents_transparent_foreground_smear(self):
        # This is the exact production weighting equation at the midpoint.
        # The previous endpoint has no valid reverse correspondence because a
        # newly revealed background pixel existed only in the current frame.
        phase = 0.5
        previous_reliability = 0.0
        current_reliability = 1.0
        previous_weight = ((1.0 - phase) *
                           (0.02 + previous_reliability))
        current_weight = phase * (0.02 + current_reliability)
        current_mix = current_weight / (previous_weight + current_weight)
        old_crossfade = phase
        self.assertGreater(current_mix, 0.98)
        self.assertEqual(old_crossfade, 0.5)

    def test_confidence_admission_never_blends_unsupported_silhouettes(self):
        confidence_floor = 0.02

        def smoothstep(low, high, value):
            t = max(0.0, min(1.0, (value - low) / (high - low)))
            return t * t * (3.0 - 2.0 * t)

        def synthesize(previous, current, aligned, phase,
                       previous_reliability, current_reliability):
            alignment_error = max(abs(a - b)
                                  for a, b in zip(aligned[0], aligned[1])) / 255.0
            appearance = 1.0 - smoothstep(24.0 / 255.0, 96.0 / 255.0,
                                          alignment_error)
            admitted = (1.0 if min(previous_reliability, current_reliability) >=
                        confidence_floor else 0.0) * appearance
            exact_endpoint = current if phase >= 0.5 else previous
            return tuple(round(endpoint * (1.0 - admitted) + predicted * admitted)
                         for endpoint, predicted in zip(exact_endpoint, aligned[2]))

        previous = (240, 160, 32)
        current = (32, 64, 240)
        translucent_double = tuple((a + b) // 2
                                   for a, b in zip(previous, current))
        self.assertEqual(synthesize(previous, current,
                                    (previous, current, translucent_double),
                                    0.5, 1.0, 0.10), current)
        self.assertNotEqual(current, translucent_double)
        falsely_confident_double = (
            (220, 150, 30),
            (35, 70, 225),
            translucent_double,
        )
        self.assertEqual(synthesize(previous, current, falsely_confident_double,
                                    0.5, 1.0, 1.0), current)
        aligned_previous = (100, 120, 140)
        aligned_current = (108, 125, 147)
        aligned_prediction = (104, 123, 144)
        self.assertEqual(
            synthesize(previous, current,
                       (aligned_previous, aligned_current, aligned_prediction),
                       0.5, 0.50, 0.50),
            aligned_prediction,
        )
        medium_previous = (100, 120, 140)
        medium_current = (148, 150, 170)
        medium_prediction = (124, 135, 155)
        softened = synthesize(previous, current,
                              (medium_previous, medium_current,
                               medium_prediction),
                              0.5, 0.50, 0.50)
        self.assertNotEqual(softened, current)
        self.assertNotEqual(softened, medium_prediction)
        self.assertEqual(
            synthesize(previous, current,
                       (aligned_previous, aligned_current, aligned_prediction),
                       0.5, 0.019, 0.50),
            current,
        )

    def test_forward_backward_cycle_rejects_contradictory_block_match(self):
        def reliability(vector, opposite_at_endpoint, confidence=1.0):
            cycle = abs(vector + opposite_at_endpoint) / 20.0
            return confidence * max(0.0, min(1.0, 1.0 - 4.0 * cycle))

        self.assertEqual(reliability(8.0, -8.0), 1.0)
        self.assertEqual(reliability(8.0, 3.0), 0.0)

    def test_bidirectional_warp_tracks_translation_instead_of_crossfading(self):
        # Model the production inverse sampling for a four-pixel translation.
        # At t=.5 the independently measured forward/backward fields must land
        # on the same two-pixel midpoint, while fixed-coordinate blending
        # creates a visibly different double exposure on most signal pixels.
        import math
        width = 128
        previous = [round(127.5 + 95.0 * math.sin(x * 0.37) +
                          24.0 * math.sin(x * 1.19)) for x in range(width)]
        current = [previous[(x - 4) % width] for x in range(width)]
        generated = []
        fixed_crossfade = []
        for x in range(width):
            previous_sample = previous[(x - 2) % width]
            current_sample = current[(x + 2) % width]
            generated.append(round((previous_sample + current_sample) / 2))
            fixed_crossfade.append(round((previous[x] + current[x]) / 2))
        expected_midpoint = [previous[(x - 2) % width] for x in range(width)]
        self.assertEqual(generated, expected_midpoint)
        non_crossfade = sum(abs(a - b) >= 9 for a, b in
                            zip(generated, fixed_crossfade))
        self.assertGreater(non_crossfade / width, 0.70)

    def test_flow_readback_cannot_steal_the_proof_framebuffer_binding(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        start = generator.index("private void sampleFrameProof")
        end = generator.index("private long readProofHash", start)
        method = generator[start:end]
        first_proof_draw = method.index("drawMotionFrame(0f)")
        self.assertNotIn("sampleMotionEvidence()", method[:first_proof_draw])
        self.assertIn("drawProofFlow()", method)
        self.assertLess(
            method.index("glBindFramebuffer(GLES20.GL_FRAMEBUFFER, frameBuffer)"),
            first_proof_draw,
        )

    def test_proof_interval_does_not_phase_lock_to_supported_cadences(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        match = re.search(r"PROOF_SAMPLE_INTERVAL\s*=\s*(\d+)", generator)
        self.assertIsNotNone(match)
        interval = int(match.group(1))
        # 60/40/30 sources repeat after 2/3/4 120-Hz panel ticks. A 50-Hz
        # source repeats its complete phase sequence after 12 panel ticks.
        for cycle in (2, 3, 4, 12):
            self.assertEqual(
                math.gcd(interval, cycle),
                1,
                f"proof interval {interval} phase-locks to a {cycle}-tick cadence",
            )

    def test_qualification_samples_only_materially_synthetic_frames(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        self.assertIn("phase > 0.15f && phase < 0.85f", generator)
        self.assertIn("presents - lastProofPresent >= PROOF_SAMPLE_INTERVAL",
                      generator)
        self.assertIn("if (captureProof) lastProofPresent = presents", generator)

    def test_dense_pyramid_is_lazy_qualification_only_and_bounded(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        surface = self.read(
            "unified-android/src/com/thorium/preview/game/GameSurfaceView.java"
        )
        initialize = generator.split("private void initializeGl()", 1)[1].split(
            "private void allocateHistoryTextures", 1)[0]
        self.assertNotIn("DENSE_SOLVE_SHADER", initialize)
        # 2026-09-01: dense is the product generator; proof gates evidence only.
        self.assertIn("denseRequested = densePyramidSwitch.enabled();", generator)
        self.assertNotIn("requested && densePyramidSwitch.enabled()", generator)
        self.assertIn("DENSE_BASE_PASSES_PER_PROMOTION = 38", generator)
        self.assertIn("DENSE_RECIPROCAL_REFINEMENT_PASSES = 2", generator)
        self.assertIn("DENSE_V26_ANALYSIS_MAX_WIDTH = 256", generator)
        self.assertIn("DENSE_V26_ANALYSIS_MAX_HEIGHT = 144", generator)
        self.assertIn("DENSE_LEVEL_ITERATIONS = {4, 4, 8}", generator)
        # The coarsest step, the reach and the reciprocal tolerance scale
        # with the source period (2026-09-02, wiiu-b64 flow dumps): 4.5px
        # at 60, 6.75px at 40, 9px at 30, 13.5px at 20 -- same iteration
        # count and tap cost.
        self.assertIn("float coarsestStep = denseCoarsestStep();", generator)
        self.assertIn("flowLimitPixels(historyWidth, historyHeight)));", generator)
        self.assertIn("2f * Math.max(1f, activeFlowLimitPixels() / DENSE_MAX_FLOW_PIXELS));", generator)
        self.assertIn("level == 2 ? coarsestStep", generator)
        self.assertIn("GL_OES_rgb8_rgba8", generator)
        self.assertIn("glGetShaderPrecisionFormat", generator)
        self.assertIn("validateDenseByteContract", generator)
        self.assertIn("validateDenseQ8ShaderContract", generator)
        self.assertIn("DENSE_Q8_PROBE_SHADER", generator)
        self.assertIn("dense Q8.8 shader round-trip mismatch", generator)
        self.assertIn("128f / 255f, 128f / 255f", generator)
        probe = generator.split("private void validateDenseQ8ShaderContract()", 1)[1].split(
            "private void validateDenseByteContract()", 1)[0]
        self.assertIn("glDisable(GLES20.GL_DITHER)", probe)
        self.assertIn("finally {", probe)
        self.assertIn("glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0)", probe)
        self.assertIn("glViewport(0, 0, outputWidth, outputHeight)", probe)
        self.assertIn("primaryFailure.addSuppressed(cleanupFailure)", probe)
        self.assertIn("clearDenseFields();", probe.split("finally {", 1)[1])
        byte_probe = generator.split("private void validateDenseByteContract()", 1)[1].split(
            "private void clearTexture", 1)[0]
        self.assertIn("primaryFailure.addSuppressed(cleanupFailure)", byte_probe)
        self.assertIn("clearDenseFields();", byte_probe.split("finally {", 1)[1])
        clear_fields = generator.split("private void clearDenseFields()", 1)[1].split(
            "private void validateDenseQ8ShaderContract()", 1)[0]
        self.assertIn("glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0)", clear_fields)
        self.assertIn("glViewport(0, 0, outputWidth, outputHeight)", clear_fields)
        ensure_dense = generator.split("private void ensureDenseResources()", 1)[1].split(
            "private void allocateDenseResources()", 1)[0]
        self.assertIn("finally {", ensure_dense)
        self.assertIn("glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0)", ensure_dense)
        byte_try = byte_probe.split("try {", 1)[1].split("} catch", 1)[0]
        self.assertIn("attachDenseTarget", byte_try)
        self.assertIn("decLinear", generator)
        self.assertIn("denseGpuCompleteMaxUs", generator)
        self.assertIn("DenseGpuTimer.create()", generator)
        self.assertIn("DenseGpuTimer.nanosecondsToMicroseconds(rawElapsedNs)", generator)
        self.assertIn("rawElapsedNs <= 0L", generator)
        self.assertIn("Dense GPU timer diagnostic", generator)
        self.assertIn("status=", generator)
        timer = self.read(
            "unified-android/src/com/thorium/preview/game/DenseGpuTimer.java")
        self.assertIn("nanoseconds / 1000L +", timer)
        self.assertIn("nanoseconds % 1000L == 0L", timer)
        cadence_estimator = generator.split(
            "private void estimateDenseMotion()", 1)[1].split(
            "private void beginDenseStage", 1)[0]
        self.assertNotIn("GLES20.glFinish();", cadence_estimator)
        self.assertNotIn("measureEndpointDifference();", cadence_estimator)
        calibration = generator.split(
            "private void runDenseIntrusiveCalibration()", 1)[1].split(
            "private void endDenseStage", 1)[0]
        self.assertEqual(calibration.count("GLES20.glFinish();"), 2)
        self.assertIn("denseTimerDisjoint", generator)
        self.assertIn("denseTimerStale", generator)
        self.assertIn("denseWarpSequence", generator)
        self.assertIn("denseWarpMaxCompletedSequence", generator)
        warp_accounting = generator.split(
            "if (stage == DenseGpuTimer.VISIBLE_WARP) {", 1)[1].split(
            "int pair =", 1)[0]
        self.assertIn("continue;", warp_accounting)
        self.assertNotIn("densePairTotalUs", warp_accounting)
        self.assertIn("motionEstimateReady = false", generator)
        self.assertIn("clearAllMotionFieldsAfterDenseReject();", generator)
        self.assertIn("gpu-warp-timer-failure", generator)
        self.assertIn("eglSwapBuffers", generator)
        lifecycle = generator.split(
            "private void teardownDenseEpoch(String reason)", 1)[1].split(
            "private void clearAllMotionFieldsAfterDenseReject", 1)[0]
        self.assertIn("motionEstimateReady = false", lifecycle)
        self.assertIn("clearAllMotionFieldsAfterDenseReject();", lifecycle)
        self.assertIn("finally {", lifecycle)
        self.assertLess(lifecycle.index("denseGpuTimer = null"),
                        lifecycle.index("timer.discardPending()"))
        self.assertIn("timer.close();", lifecycle)
        self.assertIn("denseCalibrationRuns = 0", lifecycle)
        refresh = generator.split(
            "private void refreshQualificationProofState()", 1)[1].split(
            "private String activeProofContract", 1)[0]
        self.assertLess(refresh.index("DenseGpuTimer.create()"),
                        refresh.index("ensureDenseResources()"))
        self.assertIn("boolean wasDense = densePyramidEnabled", refresh)
        self.assertIn("teardownDenseEpoch(\"settings-disabled\")", refresh)
        self.assertIn("denseGpuTimer = DenseGpuTimer.create()", refresh)
        atlas_epoch = generator.split(
            "private void ensureProofAtlasTimerConfigured()", 1)[1].split(
            "private void ensureDenseResources()", 1)[0]
        self.assertIn("denseGpuTimer.proofAtlasCapability()", atlas_epoch)
        self.assertIn("denseGpuTimer.configureProofAtlas(", atlas_epoch)
        self.assertIn("(capability & 15) == 15", atlas_epoch)
        dense_resources = generator.split(
            "private void ensureDenseResources()", 1)[1].split(
            "private void allocateDenseResources()", 1)[0]
        ready_branch = dense_resources.split(
            "if (denseResourcesReady)", 1)[1].split("try {", 1)[0]
        self.assertIn("ensureProofAtlasTimerConfigured();", ready_branch)
        self.assertLess(ready_branch.index("ensureProofAtlasTimerConfigured();"),
                        ready_branch.index("return;"))
        self.assertIn("ensureProofAtlasTimerConfigured();", dense_resources)
        self.assertIn("surface-cadence-below-reported-output", generator)
        health = generator.split(
            "if (presents % HEALTH_INTERVAL == 0L)", 1
        )[1].split("reportStats();", 1)[0]
        cadence = health.index("boolean cadenceReject")
        rejected = health.index("densePerformanceRejected = true", cadence)
        pending = health.index("pendingDenseCadenceReject = true", rejected)
        self.assertLess(cadence, rejected)
        self.assertLess(rejected, pending)
        for snapshot in (
            "pendingDenseHealthPresents = windowPresents",
            "pendingDenseHealthGenerated = windowGenerated",
            "pendingDenseHealthPromoted = windowPromoted",
        ):
            self.assertIn(snapshot, health)
        self.assertNotIn(
            'rejectDense("surface-cadence-below-reported-output", null)',
            health,
        )
        callback = generator.split(
            "@Override public void doFrame(long frameTimeNanos)", 1
        )[1].split("@Override public void close()", 1)[0]
        self.assertLess(
            callback.index("recordDenseWall(DENSE_WALL_PRESENT"),
            callback.index("finalizeDenseCadenceReject()"),
        )
        self.assertLess(
            callback.index("recordDenseWall(DENSE_WALL_PROMOTION"),
            callback.index("finalizeDenseCadenceReject()"),
        )
        finalizer = generator.split(
            "private void finalizeDenseCadenceReject()", 1
        )[1].split("private String healthKey", 1)[0]
        split = finalizer.index("logSplitHealth(")
        teardown = finalizer.index(
            'rejectDense("surface-cadence-below-reported-output", null)'
        )
        self.assertLess(split, teardown)
        self.assertIn("finally {", finalizer)
        self.assertIn("long now = System.nanoTime()", finalizer)
        self.assertIn("now - healthWindowStartNanos", finalizer)
        self.assertIn("densePerformanceRejected = true", health)
        refresh = generator.split(
            "private void refreshQualificationProofState()", 1
        )[1].split("private String activeProofContract", 1)[0]
        for counter in (
            "callbackDeltaSamples = 0", "densePresentWallSamples = 0",
            "denseSwapWallSamples = 0", "denseProofEnqueueWallSamples = 0",
            "denseProofPollWallSamples = 0",
            "lastCallbackFrameTimeNs = 0L",
        ):
            self.assertIn(counter, refresh)
        self.assertIn("async-gpu-pair-over-budget", generator)
        self.assertIn("ownedPrediction", generator)
        self.assertIn("predictionAdmission", generator)
        self.assertIn("DENSE_MAX_FLOW_PIXELS = 47f", generator)
        self.assertIn("uActiveRect", generator)
        self.assertIn("float coherentFlat=step(2.5,ns)", generator)
        self.assertIn("step(distance(f,fm),1.5+.03*length(fm))", generator)
        self.assertIn(
            "textureGate=max(smoothstep(.008,.030,textureEnergy),coherentFlat)",
            generator,
        )
        self.assertIn("floor(v*256.0+.5)", generator)
        self.assertIn("decReverse", generator)
        self.assertIn("uUseReciprocalGuide", generator)
        self.assertIn("decReciprocalLinear", generator)
        self.assertIn("vec2 q=vTexCoord-f/uSourceSize", generator)
        self.assertIn("vec2 g=clamp(-decReciprocalLinear(q)", generator)
        self.assertIn("gc+uReciprocalMargin<bc", generator)
        self.assertIn('"uReciprocalMargin"), 0.002f', generator)
        self.assertIn('"uReciprocalMargin"), 0.006f', generator)
        self.assertNotIn("refineDenseForwardFromReverse", generator)
        self.assertIn("boolean coarsestFirst = level == DENSE_LEVELS - 1", generator)
        self.assertIn("int iterations = DENSE_LEVEL_ITERATIONS[level]", generator)
        self.assertIn("vec2 chroma(vec3 c)", generator)
        self.assertIn(".18*cc(tv,rv)", generator)
        self.assertIn(".07*(cc(txpv,rxpv)", generator)
        self.assertIn("uBypassSearch", generator)
        self.assertIn(
            "if(uBypassSearch>.5&&uUseTemporalGuide<.5){gl_FragColor=enc(c);return;}",
            generator,
        )
        self.assertIn("uniform sampler2D uReference,uTarget,uPriorFlow,uTemporalFlow", generator)
        self.assertIn("vec2 decTemporal(vec4 f)", generator)
        self.assertIn("if(uUseTemporalGuide>.5)", generator)
        self.assertIn("float tc=objective(t)", generator)
        self.assertIn("tf.b>=48.0/255.0&&tc+.002<bc", generator)
        self.assertNotIn("tc<=bc+.008", generator)
        self.assertIn("boolean temporalGuide = temporalGuideReady && coarsestFirst", generator)
        self.assertIn("denseValidatedTextures[direction], 3", generator)
        self.assertIn("boolean reciprocalGuide = direction == 1 && iteration == 0", generator)
        self.assertIn("denseFlowTextures[0][level]", generator)
        self.assertIn("q=vTexCoord-decReciprocalLinear(q)/uSourceSize", generator)
        self.assertIn('"uReciprocalFlow",\n                        reciprocalTexture, 4', generator)
        self.assertIn('"uUseReciprocalGuide"), reciprocalGuide ? 1f : 0f', generator)
        self.assertIn("denseTemporalGuideReady = false", generator)
        self.assertIn("denseTemporalGuideReady = true", generator)
        fifo_reset = generator.split(
            "private void resetEndpointFifo()", 1
        )[1].split("private int endpointFifoSlot", 1)[0]
        self.assertIn("denseTemporalGuideReady = false", fifo_reset)
        fifo_reprime = generator.split(
            "private void invalidateBufferedPairForReprime(boolean resetController)", 1
        )[1].split("private void recordPromotedEndpoint", 1)[0]
        self.assertIn("denseTemporalGuideReady = false", fifo_reprime)
        self.assertIn("if(uBypassSearch>.5){gl_FragColor=enc(c);return;}", generator)
        self.assertIn(
            '"uBypassSearch"), level == 0 && iteration == 0', generator)
        self.assertIn("iteration == 0 ? 1f : 0f", generator)
        self.assertIn("8*4.5 + 4*2 + 3*1 = 47px", generator)
        self.assertIn("uUseWidePatch", generator)
        self.assertIn("float cs=abs(step(t,txp)-step(r,rxp))", generator)
        self.assertIn("z+=.22*(rb(td1-rd1)", generator)
        self.assertIn("uFinalConsensus", generator)
        self.assertIn("float med4(float a,float b,float c,float d)", generator)
        self.assertIn("float support=step(distance(l,m),2.5)", generator)
        self.assertIn("w=max(w,.65*g)", generator)
        self.assertIn(
            '"uUseWidePatch"), level == DENSE_LEVELS - 1 ? 1f : 0f',
            generator,
        )
        self.assertIn(
            '"uFinalConsensus"), level == 0 &&', generator)
        self.assertIn(
            "iteration == iterations - 1", generator)
        self.assertIn("level == DENSE_LEVELS - 1 &&", generator)
        self.assertIn("level == 0 &&", generator)
        self.assertIn("denseSceneCut", generator)
        self.assertIn("drawTexture2d(historyTextures[currentIndex])", generator)
        self.assertIn("(field.rg*255.0-128.0)/127.0", generator)
        self.assertIn("finally {", generator)
        self.assertIn("emufusion_framegen_dense_pyramid", surface)
        self.assertIn("emufusion_framegen_dense_v27_192", surface)
        self.assertIn('"emufusion_framegen_dense_pyramid", 1) == 0', surface)
        self.assertIn("displayId() != Display.DEFAULT_DISPLAY) return false", surface)
        self.assertIn("if (!rawDensePyramidRequested()) return false", surface)
        v27_switch = surface.split(
            "private boolean denseV27ReducedAnalysisEnabled()", 1)[1].split(
            "private void releaseGenerator()", 1)[0]
        self.assertNotIn("qualificationProofEnabled()", v27_switch)
        # v27 preselection stays a raw shell arm; v28 (the product variant)
        # legitimately derives from densePyramidEnabled(), so only inspect v27.
        v27_only = v27_switch.split("private boolean denseV28ReducedAnalysisEnabled()", 1)[0]
        self.assertNotIn("densePyramidEnabled()", v27_only)
        self.assertIn("DENSE_V27_ANALYSIS_MAX_WIDTH = 192", generator)
        self.assertIn("DENSE_V27_ANALYSIS_MAX_HEIGHT = 108", generator)
        self.assertIn("DENSE_V28_ANALYSIS_MAX_WIDTH = 128", generator)
        self.assertIn("DENSE_V28_ANALYSIS_MAX_HEIGHT = 72", generator)
        self.assertIn("emufusion_framegen_dense_v28_160", surface)
        self.assertIn("combined-pair-warp-over-budget", generator)
        self.assertIn("denseTimedPairMaxUs +", generator)
        self.assertIn("denseStageP95(DenseGpuTimer.VISIBLE_WARP)", generator)
        self.assertIn("densePromotionWallSamples", generator)
        self.assertIn("denseSignatureWallSamples", generator)
        self.assertIn("denseProofWallSamples", generator)
        self.assertIn("denseSolveTexelsPerPromotion()", generator)
        self.assertIn("denseTotalTexelsPerPromotion()", generator)
        self.assertIn("variant change requires a new generator", generator)
        self.assertIn("setAuthoritativeSourceHz(authoritativeSourceHz)", surface)

    def test_v27_preselection_is_independent_of_delayed_proof_activation(self):
        surface = self.read(
            "unified-android/src/com/thorium/preview/game/GameSurfaceView.java"
        )
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        dense = surface.split("private boolean densePyramidEnabled()", 1)[1].split(
            "/** Raw shell preselection", 1)[0]
        raw = surface.split("private boolean rawDensePyramidRequested()", 1)[1].split(
            "/** Pre-launch-only v27", 1)[0]
        v27 = surface.split("private boolean denseV27ReducedAnalysisEnabled()", 1)[1].split(
            "private void releaseGenerator()", 1)[0]
        self.assertNotIn("qualificationProofEnabled()", dense)
        self.assertIn('"emufusion_framegen_dense_pyramid", 1) == 0', dense)
        self.assertIn('"emufusion_framegen_dense_pyramid"', raw)
        self.assertIn("displayId() != Display.DEFAULT_DISPLAY", raw)
        self.assertIn("if (!rawDensePyramidRequested()) return false", v27)
        self.assertIn('"emufusion_framegen_dense_v27_192"', v27)
        self.assertNotIn("qualificationProofEnabled()", v27)
        constructor = generator.split(
            "DenseV27ReducedAnalysisSwitch denseV27ReducedAnalysisSwitch)", 1)[1].split(
            "/** The only Surface", 1)[0]
        self.assertIn("denseV27ReducedAnalysisSwitch.enabled()", constructor)
        refresh = generator.split(
            "private void refreshQualificationProofState()", 1)[1].split(
            "private String activeProofContract", 1)[0]
        self.assertIn("denseRequested = densePyramidSwitch.enabled()", refresh)
        self.assertNotIn("requested && densePyramidSwitch.enabled()", refresh)
        self.assertIn("if (displayId > 0)", refresh)
        self.assertIn("frameRate.setGenerationAvailable(false)", refresh)
        self.assertIn("if (denseRequested)", refresh)
        self.assertIn("v27Requested = denseV27ReducedAnalysisSwitch.enabled()", refresh)

    def test_generated_target_rejection_requires_three_complete_bad_windows(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        health = generator.split(
            "if (presents % HEALTH_INTERVAL == 0L)", 1
        )[1].split("private void updateSchedulerHealthBaseline", 1)[0]
        self.assertIn("generationTargetFailureWindows =", health)
        self.assertIn("advanceCadenceFailureWindows(", health)
        self.assertIn(
            "generationTargetFailureWindows >=\n" +
            "                            DENSE_CADENCE_REJECT_CONSECUTIVE_WINDOWS",
            health,
        )
        self.assertIn("if (generationTargetReject)", health)

    def test_v28_preselection_is_triple_gated_and_incompatible_with_v27(self):
        surface = self.read(
            "unified-android/src/com/thorium/preview/game/GameSurfaceView.java"
        )
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        verifier = self.read(
            "unified-android/tools/verify_frame_generation_evidence.py"
        )
        v28 = surface.split("private boolean denseV28ReducedAnalysisEnabled()", 1)[1].split(
            "private void releaseGenerator()", 1)[0]
        self.assertIn("if (!densePyramidEnabled()) return false", v28)
        self.assertIn("if (denseV27ReducedAnalysisEnabled()) return false", v28)
        self.assertIn('"emufusion_framegen_dense_v28_160", 1) == 1', v28)
        self.assertNotIn("qualificationProofEnabled()", v28)
        refresh = generator.split(
            "private void refreshQualificationProofState()", 1)[1].split(
            "private String activeProofContract", 1)[0]
        self.assertIn("if (denseRequested)", refresh)
        self.assertIn("v28Requested = denseV28ReducedAnalysisSwitch.enabled()", refresh)
        self.assertIn("(v27Requested && v28Requested)", refresh)
        self.assertIn("dense-v63-exact-midpoint-max2x-pair-owned-gpu-presented", generator)
        self.assertIn(
            '"fragment-v62-parallel-global-seed"',
            generator)
        self.assertNotIn(
            'return denseV28ReducedAnalysisRequested ?\n'
            '                "fragment-128x72-v40-temporal-flow-guidance-',
            generator)
        self.assertIn("DENSE_V28_PROOF_SCHEMA_VERSION = 63", generator)
        self.assertIn('"uUseNeighborProposal"), 1f', generator)
        self.assertIn('"if(uUseNeighborProposal>.5&&support>=3.0&&edge>=.55)',
                      generator)
        self.assertIn('if(mc+uNeighborMargin<bc)', generator)
        self.assertIn("DENSE_BASE_PASSES_PER_PROMOTION = 38", generator)
        self.assertIn("DENSE_RECIPROCAL_REFINEMENT_PASSES = 2", generator)
        self.assertIn("DENSE_GLOBAL_SEED_PASSES = 8", generator)
        self.assertIn("DENSE_GLOBAL_COST_SHADER", generator)
        self.assertIn("DENSE_GLOBAL_REDUCE_SHADER", generator)
        self.assertIn("denseGlobalCoarseCostTextures", generator)
        self.assertIn("denseGlobalFineCostTextures", generator)
        self.assertIn("buildDenseGlobalSeed(0", generator)
        self.assertIn("buildDenseGlobalSeed(1", generator)
        self.assertIn(
            'denseV28ReducedAnalysisRequested && coarsestFirst ? 1f : 0f',
            generator,
        )
        self.assertIn("gain<.008||length(best)<.25", generator)
        self.assertIn("refineDenseReciprocalDirection(0", generator)
        self.assertIn("refineDenseReciprocalDirection(1", generator)
        self.assertIn('"uReciprocalMargin"), 0.006f', generator)
        self.assertIn("uCycleObjectiveWeight", generator)
        self.assertIn('"uCycleObjectiveWeight"), 0f', generator)
        self.assertIn('"uCycleObjectiveWeight"), 0.006f', generator)
        self.assertIn("min(length(f+decReciprocalLinear(q)),4.0)", generator)
        self.assertIn("private int densePassesPerPromotion()", generator)
        self.assertIn(
            'DENSE_V37_PROOF_CONTRACT = "dense-fragment-128x72-v37-timestamp-resample-qualification-x2-presented"',
            verifier)
        self.assertIn("DENSE_V37_PROOF_SCHEMA_VERSION = 37", verifier)
        self.assertIn("HEALTH_BASE_V37 = re.compile", verifier)
        self.assertIn("HEALTH_DENSE_EXTENSION_V37 = re.compile", verifier)
        self.assertIn(
            'DENSE_V38_PROOF_CONTRACT = "dense-fragment-128x72-v38-vector-trajectory-qualification-x2-presented"',
            verifier)
        self.assertIn("DENSE_V38_PROOF_SCHEMA_VERSION = 38", verifier)
        self.assertIn("HEALTH_BASE_V38 = re.compile", verifier)
        self.assertIn("HEALTH_DENSE_EXTENSION_V38 = re.compile", verifier)
        self.assertIn(
            'DENSE_V39_PROOF_CONTRACT = "dense-fragment-128x72-v39-present-timed-vector-trajectory-qualification-x2-presented"',
            verifier)
        self.assertIn("DENSE_V39_PROOF_SCHEMA_VERSION = 39", verifier)
        self.assertIn("HEALTH_BASE_V39 = re.compile", verifier)
        self.assertIn("HEALTH_DENSE_EXTENSION_V39 = re.compile", verifier)
        self.assertIn(
            'DENSE_V40_PROOF_CONTRACT = "dense-fragment-128x72-v40-temporal-flow-guidance-present-timed-vector-trajectory-qualification-x2-presented"',
            verifier)
        self.assertIn("DENSE_V40_PROOF_SCHEMA_VERSION = 40", verifier)
        self.assertIn("HEALTH_BASE_V40 = re.compile", verifier)
        self.assertIn("HEALTH_DENSE_EXTENSION_V40 = re.compile", verifier)
        self.assertIn(
            'DENSE_V41_PROOF_CONTRACT = "dense-fragment-128x72-v41-strict-temporal-flow-guidance-present-timed-vector-trajectory-qualification-x2-presented"',
            verifier)
        self.assertIn("DENSE_V41_PROOF_SCHEMA_VERSION = 41", verifier)
        self.assertIn("HEALTH_BASE_V41 = re.compile", verifier)
        self.assertIn("HEALTH_DENSE_EXTENSION_V41 = re.compile", verifier)
        self.assertIn(
            'DENSE_V44_PROOF_CONTRACT = "dense-fragment-128x72-v44-unique-endpoint-rational-clock-strict-flow-qualification-max2x-presented"',
            verifier)
        self.assertIn("DENSE_V44_PROOF_SCHEMA_VERSION = 44", verifier)
        self.assertIn("HEALTH_RATIONAL_CLOCK_V44 = re.compile", verifier)
        self.assertIn(
            'DENSE_V45_PROOF_CONTRACT = "dense-fragment-128x72-v45-spatial-consensus-rational-clock-strict-flow-qualification-max2x-presented"',
            verifier)
        self.assertIn("DENSE_V45_PROOF_SCHEMA_VERSION = 45", verifier)
        self.assertIn("HEALTH_RATIONAL_CLOCK_V45 = re.compile", verifier)
        self.assertIn(
            'DENSE_V46_PROOF_CONTRACT = "dense-fragment-128x72-v46-independent-bidirectional-spatial-consensus-rational-clock-strict-flow-qualification-max2x-presented"',
            verifier)
        self.assertIn("DENSE_V46_PROOF_SCHEMA_VERSION = 46", verifier)
        self.assertIn("HEALTH_RATIONAL_CLOCK_V46 = re.compile", verifier)
        self.assertIn(
            'DENSE_V47_PROOF_CONTRACT = "dense-fragment-128x72-v47-stamped-pts-loss-bound-independent-bidirectional-spatial-consensus-rational-clock-strict-flow-qualification-max2x-presented"',
            verifier)
        self.assertIn("DENSE_V47_PROOF_SCHEMA_VERSION = 47", verifier)
        self.assertIn("HEALTH_RATIONAL_CLOCK_V47 = re.compile", verifier)
        self.assertIn(
            'DENSE_V48_PROOF_CONTRACT = "dense-fragment-128x72-v48-reciprocal-proposal-stamped-pts-loss-bound-bidirectional-spatial-consensus-rational-clock-strict-flow-qualification-max2x-presented"',
            verifier)
        self.assertIn("DENSE_V48_PROOF_SCHEMA_VERSION = 48", verifier)
        self.assertIn("HEALTH_RATIONAL_CLOCK_V48 = re.compile", verifier)
        self.assertIn(
            'DENSE_V49_PROOF_CONTRACT = "dense-fragment-128x72-v49-multilevel-reciprocal-proposal-stamped-pts-loss-bound-bidirectional-spatial-consensus-rational-clock-strict-flow-qualification-max2x-presented"',
            verifier)
        self.assertIn("DENSE_V49_PROOF_SCHEMA_VERSION = 49", verifier)
        self.assertIn("HEALTH_RATIONAL_CLOCK_V49 = re.compile", verifier)
        self.assertIn(
            'DENSE_V50_PROOF_CONTRACT = "dense-fragment-128x72-v50-iterated-multilevel-reciprocal-proposal-stamped-pts-loss-bound-bidirectional-spatial-consensus-rational-clock-strict-flow-qualification-max2x-presented"',
            verifier)
        self.assertIn("DENSE_V50_PROOF_SCHEMA_VERSION = 50", verifier)
        self.assertIn("HEALTH_RATIONAL_CLOCK_V50 = re.compile", verifier)
        self.assertIn(
            'DENSE_V51_PROOF_CONTRACT = "dense-fragment-128x72-v51-cost-tested-bidirectional-refinement-stamped-pts-loss-bound-spatial-consensus-rational-clock-strict-flow-qualification-max2x-presented"',
            verifier)
        self.assertIn("DENSE_V51_PROOF_SCHEMA_VERSION = 51", verifier)
        self.assertIn("HEALTH_RATIONAL_CLOCK_V51 = re.compile", verifier)
        self.assertIn(
            'DENSE_V54_PROOF_CONTRACT = "dense-fragment-128x72-v54-cycle-aware-cost-tested-bidirectional-refinement-stamped-pts-loss-bound-spatial-consensus-rational-clock-strict-flow-qualification-max2x-presented"',
            verifier)
        self.assertIn("DENSE_V54_PROOF_SCHEMA_VERSION = 54", verifier)
        self.assertIn("HEALTH_RATIONAL_CLOCK_V54 = re.compile", verifier)
        self.assertIn(
            'DENSE_V55_PROOF_CONTRACT = "dense-fragment-128x72-v55-cycle-regularized-cost-tested-bidirectional-refinement-stamped-pts-loss-bound-spatial-consensus-rational-clock-strict-flow-qualification-max2x-presented"',
            verifier)
        self.assertIn("DENSE_V55_PROOF_SCHEMA_VERSION = 55", verifier)
        self.assertIn("HEALTH_RATIONAL_CLOCK_V55 = re.compile", verifier)
        self.assertIn(
            'DENSE_V56_PROOF_CONTRACT = "dense-fragment-128x72-v56-strong-cycle-regularized-cost-tested-bidirectional-refinement-stamped-pts-loss-bound-spatial-consensus-rational-clock-strict-flow-qualification-max2x-presented"',
            verifier)
        self.assertIn("DENSE_V56_PROOF_SCHEMA_VERSION = 56", verifier)
        self.assertIn("HEALTH_RATIONAL_CLOCK_V56 = re.compile", verifier)
        self.assertIn(
            'DENSE_V57_PROOF_CONTRACT = "dense-v57-joint-cycle-rational-max2x-presented"',
            verifier)
        self.assertIn("DENSE_V57_PROOF_SCHEMA_VERSION = 57", verifier)
        self.assertIn("HEALTH_RATIONAL_CLOCK_V57 = re.compile", verifier)
        self.assertIn(
            'DENSE_V58_PROOF_CONTRACT = "dense-v58-joint-cycle-rational-max2x-presented"',
            verifier)
        self.assertIn("DENSE_V58_PROOF_SCHEMA_VERSION = 58", verifier)
        self.assertIn("HEALTH_RATIONAL_CLOCK_V58 = re.compile", verifier)
        self.assertIn(
            'DENSE_V59_PROOF_CONTRACT = "dense-v59-edge-aware-neighbor-rational-max2x-presented"',
            verifier)
        self.assertIn("DENSE_V59_PROOF_SCHEMA_VERSION = 59", verifier)
        self.assertIn("HEALTH_BASE_V59 = re.compile", verifier)
        self.assertIn("HEALTH_DENSE_EXTENSION_V59 = re.compile", verifier)
        self.assertIn("HEALTH_RATIONAL_CLOCK_V59 = re.compile", verifier)
        self.assertIn(
            'DENSE_V60_PROOF_CONTRACT = "dense-v60-independent-global-seed-rational-max2x-presented"',
            verifier)
        self.assertIn("DENSE_V60_PROOF_SCHEMA_VERSION = 60", verifier)
        self.assertIn("HEALTH_BASE_V60 = re.compile", verifier)
        self.assertIn("HEALTH_DENSE_EXTENSION_V60 = re.compile", verifier)
        self.assertIn("HEALTH_RATIONAL_CLOCK_V60 = re.compile", verifier)
        self.assertIn(
            'DENSE_V61_PROOF_CONTRACT = "dense-v61-parallel-global-seed-rational-max2x-presented"',
            verifier)
        self.assertIn("DENSE_V61_PROOF_SCHEMA_VERSION = 61", verifier)
        self.assertIn("HEALTH_BASE_V61 = re.compile", verifier)
        self.assertIn("HEALTH_DENSE_EXTENSION_V61 = re.compile", verifier)
        self.assertIn("HEALTH_RATIONAL_CLOCK_V61 = re.compile", verifier)
        self.assertIn(
            'DENSE_V62_PROOF_CONTRACT = "dense-v62-parallel-global-seed-rational-tiered-max3x-presented"',
            verifier)
        self.assertIn("DENSE_V62_PROOF_SCHEMA_VERSION = 62", verifier)
        self.assertIn("MAX_GENERATION_FACTOR_V62 = 3", verifier)
        self.assertIn("HEALTH_BASE_V62 = re.compile", verifier)
        self.assertIn("HEALTH_DENSE_EXTENSION_V62 = re.compile", verifier)
        self.assertIn("HEALTH_RATIONAL_CLOCK_V62 = re.compile", verifier)
        self.assertIn('" rClock="', generator)
        for field in (
            "source_millihz", "target_millihz", "panel_millihz",
            "panel_scans_per_output", "uniform_output_qualified",
            "window_swap_millihz", "source_clock_kind",
        ):
            self.assertIn(field, verifier)
        self.assertIn("HEALTH_BASE_V42 = re.compile", verifier)
        self.assertIn("HEALTH_DENSE_EXTENSION_V42 = re.compile", verifier)
        # Schema36 remains immutable and parseable as historical evidence.
        self.assertIn(
            'DENSE_V36_PROOF_CONTRACT = "dense-fragment-160x90-v36-epoch-bound-packed-mask-qualification-x2-presented"',
            verifier)
        self.assertIn("DENSE_V36_PROOF_SCHEMA_VERSION = 36", verifier)
        self.assertIn("HEALTH_BASE_V36 = re.compile", verifier)
        self.assertIn("HEALTH_DENSE_EXTENSION_V36 = re.compile", verifier)
        # Schema35 remains immutable and parseable as historical evidence.
        self.assertIn(
            'DENSE_V35_PROOF_CONTRACT = "dense-fragment-160x90-v35-packed-mask-qualification-x2-presented"',
            verifier)
        self.assertIn("DENSE_V35_PROOF_SCHEMA_VERSION = 35", verifier)
        self.assertIn("HEALTH_BASE_V35 = re.compile", verifier)
        self.assertIn("HEALTH_DENSE_EXTENSION_V35 = re.compile", verifier)
        self.assertIn("window_presentation_callbacks", verifier)
        for field in (
            "dense_diagnostic_cells", "dense_diagnostic_tiles",
            "dense_diagnostic_mask_errors",
            "dense_diagnostic_last_atlas_sequence",
            "dense_diagnostic_last_pair_sequence",
            "dense_diagnostic_last_previous_endpoint",
            "dense_diagnostic_last_current_endpoint",
            "dense_backward_active", "dense_backward_in_bounds",
            "dense_backward_cycle_valid", "dense_backward_photometric_valid",
            "dense_backward_texture_valid", "dense_backward_saturated",
            "dense_backward_out_of_bounds", "dense_backward_covered_tiles",
            "dense_backward_covered_tile_mask",
            "dense_forward_active", "dense_forward_in_bounds",
            "dense_forward_cycle_valid", "dense_forward_photometric_valid",
            "dense_forward_texture_valid", "dense_forward_saturated",
            "dense_forward_out_of_bounds", "dense_forward_covered_tiles",
            "dense_forward_covered_tile_mask",
        ):
            self.assertIn(field, verifier)

    def test_v38_trajectory_proof_does_not_misclassify_translated_hard_edges(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        verifier = self.read(
            "unified-android/tools/verify_frame_generation_evidence.py"
        )
        sample_gate = generator.split(
            "if (eligible >= 24 && motionEligible >= 12)", 1
        )[1].split("motionCorrelatedProofSamples", 1)[0]
        self.assertIn("nonCrossfade * 2 >= eligible", sample_gate)
        self.assertIn("motionSynthesized * 5 >= motionEligible * 4", sample_gate)
        self.assertNotIn("substantive * 2 >= eligible", sample_gate)
        self.assertIn("if not vector_trajectory_contract:", verifier)
        self.assertIn("_motion_content_failures(", verifier)
        self.assertIn("vectorTrajectoryContract", verifier)
        self.assertIn("_v35_diagnostic_hierarchy", verifier)
        self.assertIn('bin(mask).count("1")', verifier)
        self.assertNotIn(".bit_count()", verifier)
        self.assertIn("V35_RESET_COUNTER_FIELDS", verifier)
        self.assertIn("PROOF_ATLAS_LAYOUT_VERSION = 5", generator)
        self.assertIn("HEALTH_LOG_MAX_UTF8_BYTES = 4000", generator)
        # Extra independently bounded admission/GPU records are permitted;
        # the original three joined records still use this checked transport.
        self.assertGreaterEqual(generator.count("logBoundedHealth("), 4)
        bounded = generator.split("private static void validateBoundedHealth", 1)[1].split(
            "private String wallTelemetry", 1)[0]
        self.assertIn("StandardCharsets.UTF_8", bounded)
        self.assertIn("split health record exceeds", bounded)
        self.assertIn(
            'Log.e(TAG, "Presentation health transport failed after " +',
            generator,
        )
        split_health = generator.split(
            "private void logSplitHealth", 1
        )[1].split("private static void validateBoundedHealth", 1)[0]
        self.assertLess(
            split_health.index("validateBoundedHealth(base)"),
            split_health.index("logBoundedHealth(base)"),
        )

        self.assertLess(
            split_health.index("validateBoundedHealth(extension)"),
            split_health.index("logBoundedHealth(base)"),
        )
        self.assertLess(
            split_health.index("validateBoundedHealth(rationalClock)"),
            split_health.index("logBoundedHealth(base)"),
        )
        cycle = generator.split("DENSE_CYCLE_SHADER", 1)[1].split(
            "DENSE_Q8_PROBE_SHADER", 1)[0]
        self.assertIn(
            "float conf=activeGate*inb*cg*photoGate*textureGate*spatialGate",
            cycle)
        self.assertIn("float spatialSupport=step(2.5,ns)", cycle)
        self.assertIn(
            "spatialAgreement=1.0-smoothstep(1.0+.03*length(fm),2.5+.06*length(fm),distance(f,fm))",
            cycle)
        self.assertIn(
            "outv=mix(vec2(128.0/255.0),outv,step(40.0/255.0,conf))",
            cycle)
        self.assertIn("prerequisiteThreshold=47.0/255.0", cycle)
        self.assertNotIn("threshold=48.0/255.0", cycle)
        self.assertNotIn("128.0*step(threshold,conf)", cycle)
        self.assertIn("gl_FragColor=vec4(outv,conf,mask/255.0)", cycle)
        self.assertNotIn("vec2 delta=clamp(-.5*(f+b)", cycle)
        self.assertNotIn("robustPhoto", cycle)
        self.assertIn("float pe=abs(lum(texture2D(uTarget,vTexCoord).rgb)", cycle)
        diagnostics_accumulator = generator.split(
            "private void accumulateDenseDiagnostic", 1)[1].split(
            "private static double sampleRegionalChannel", 1)[0]
        self.assertIn("packedMasks[pixel * 4 + packedChannel]", diagnostics_accumulator)
        self.assertIn("byteValid", diagnostics_accumulator)
        self.assertIn("if (byteValid) ++validByTile[tile]", diagnostics_accumulator)
        self.assertIn("if ((mask & 128) != 0)", diagnostics_accumulator)
        packed_draw = generator.split(
            "private void renderDenseDiagnosticMaskTile", 1)[1].split(
            "private void renderProofAtlasTile", 1)[0]
        self.assertIn("DENSE_DIAGNOSTIC_PACK_WIDTH", packed_draw)
        self.assertIn("DENSE_DIAGNOSTIC_PACK_HEIGHT", packed_draw)
        self.assertIn("GLES20.GL_NEAREST", packed_draw)
        finally_block = packed_draw.split("finally", 1)[1]
        self.assertGreaterEqual(finally_block.count("GLES20.GL_LINEAR"), 2)
        self.assertIn("renderDenseDiagnosticMaskTile();", generator)
        self.assertIn("DENSE_DIAGNOSTIC_PACK_X = 48", generator)
        self.assertIn("DENSE_DIAGNOSTIC_PACK_Y = 55", generator)
        self.assertIn("DENSE_DIAGNOSTIC_PACK_WIDTH = 144", generator)
        self.assertIn("DENSE_DIAGNOSTIC_PACK_HEIGHT = 9", generator)
        self.assertIn("DENSE_BASE_PASSES_PER_PROMOTION = 38", generator)
        self.assertIn("densePassesPerPromotion()", generator)
        for field in (
            "denseDiagnosticCells", "denseDiagnosticTiles",
            "denseDiagnosticMaskErrors", "denseDiagnosticLastAtlasSequence",
            "denseDiagnosticLastPairSequence",
            "denseDiagnosticLastPreviousEndpoint",
            "denseDiagnosticLastCurrentEndpoint",
        ):
            self.assertIn(field + "=", generator)
        self.assertIn('denseDiagnosticDirectionTelemetry("Backward", 0)', generator)
        self.assertIn('denseDiagnosticDirectionTelemetry("Forward", 1)', generator)
        direction = generator.split(
            "private String denseDiagnosticDirectionTelemetry", 1)[1].split(
            "private void refreshQualificationProofState", 1)[0]
        for suffix in (
            "ActiveCells=", "InBoundsCells=", "CycleValidCells=",
            "PhotometricValidCells=", "TextureValidCells=",
            "SaturatedCells=", "OutOfBoundsCells=", "CoveredTiles=",
            "CoveredTileMask=",
        ):
            self.assertIn(suffix, direction)
        self.assertIn("EGL_OPENGL_ES3_BIT_KHR = 0x40", generator)
        self.assertIn("requestedEglContextMajor = denseV28ReducedAnalysisRequested ||",
                      generator)
        self.assertIn("externalTransportFactory != null ? 3 : 2", generator)
        egl = generator.split("private void initializeEgl()", 1)[1].split(
            "private void initializeGl()", 1)[0]
        self.assertIn("requestedEglContextMajor >= 3 ?", egl)
        self.assertIn("EGL_OPENGL_ES3_BIT_KHR : EGL_OPENGL_ES2_BIT", egl)
        self.assertIn("EGL14.EGL_CONTEXT_CLIENT_VERSION,", egl)
        self.assertIn("requestedEglContextMajor, EGL14.EGL_NONE", egl)
        self.assertIn("actualEglContextMajor < 3", egl)
        signature = generator.split("private boolean latestImageIsUnique(", 1)[1].split(
            "private boolean softwareImageIsUnique", 1)[0]
        self.assertIn("pollSignature", signature)
        self.assertIn("beginSignature", signature)
        self.assertIn("endSignature", signature)
        self.assertLess(signature.index("pollSignature"), signature.index("beginSignature"))
        self.assertIn("SIGNATURE_COMPARE_SHADER", generator)
        self.assertIn("if(all(equal(a,b)))discard", generator)
        sampling = generator.split("private void setSignatureTextureSampling", 1)[1].split(
            "private void clearMotionField", 1)[0]
        self.assertEqual(sampling.count("GLES20.GL_NEAREST"), 2)
        qualified = generator.split("private void allocateSignatureQualificationTexture", 1)[1].split(
            "private int denseSignatureCapability", 1)[0]
        self.assertIn("GL_RGBA8_OES", qualified)
        self.assertEqual(qualified.count("GLES20.GL_NEAREST"), 2)
        self.assertIn("GLES20.GL_UNSIGNED_BYTE", qualified)
        self.assertIn("precision highp float", generator.split(
            "SIGNATURE_COMPARE_SHADER", 1)[1].split("FLOW_PROOF_SHADER", 1)[0])
        self.assertIn("DENSE_SIGNATURE_CAP_RGBA8 = 32", generator)
        self.assertIn('teardownDenseEpoch("software-stream-resize")', generator)
        atlas = generator.split("private void enqueueProofAtlas", 1)[1].split(
            "private void pollProofAtlas", 1)[0]
        for state in ("GL_BLEND", "GL_DITHER", "GL_SCISSOR_TEST",
                      "GL_DEPTH_TEST", "GL_STENCIL_TEST", "GL_CULL_FACE",
                      "GL_COLOR_WRITEMASK"):
            self.assertIn(state, atlas)
        self.assertIn("PROOF_ATLAS_HEADER_SHADER", generator)
        self.assertIn("GLES20.glUniform4fv(words, 26, headerWords, 0)", atlas)
        self.assertIn("GLES20.glViewport(PROOF_ATLAS_HEADER_X, PROOF_ATLAS_HEADER_Y, 26, 1)", atlas)
        self.assertIn("proofAtlasHeader.putLong(targetSourceNs)", atlas)
        self.assertIn("proofAtlasPixels.getLong(header + 92)", generator)
        self.assertIn('checkGl("render proof atlas header")', atlas)
        header_reattach = atlas.index(
            "proofAtlasTexture, 0);",
            atlas.index("float[] headerWords"),
        )
        header_complete = atlas.index(
            'throw new IllegalStateException("proof atlas header framebuffer incomplete")'
        )
        header_draw = atlas.index("GLES20.glUseProgram(proofAtlasHeaderProgram)")
        self.assertLess(header_reattach, header_complete)
        self.assertLess(header_complete, header_draw)
        self.assertNotIn("glTexSubImage2D", atlas)
        self.assertIn("finally", atlas)
        # Header is uploaded at one exact 24-RGBA-pixel row. Since both
        # glTexSubImage2D and glReadPixels use bottom-left row zero, its byte
        # offset in the returned 192x64 atlas is invariant under orientation.
        self.assertEqual((54 * 192 + 48) * 4, 41664)
        self.assertEqual(24 * 4, 96)
        diagnostics = generator.split("long[] expectedTag", 1)[1].split(
            "byte[] crcBytes", 1)[0]
        self.assertIn("firstTagMismatch", diagnostics)
        self.assertIn("nativeSeq", diagnostics)
        self.assertIn("nativePresent", diagnostics)
        self.assertIn("words=", diagnostics)
        delayed = generator.split("private void pollProofAtlas()", 1)[1].split(
            "private static double sampleRegionalChannel", 1)[0]
        for offset in ("header + 60", "header + 64", "header + 68"):
            self.assertIn(offset, delayed)
        self.assertIn("taggedWidth", delayed)
        self.assertIn("taggedHeight", delayed)
        self.assertIn("taggedFlowLimit", delayed)
        self.assertIn('" denseSignatureRequestedGles="', generator)
        self.assertIn('" denseSignatureActualGlesMajor="', generator)
        self.assertIn('" denseSignatureSelfTests="', generator)
        resize = generator.split("public void resize(", 1)[1].split(
            "@Override public void onFrameAvailable", 1)[0]
        self.assertIn('teardownDenseEpoch("stream-resize")', resize)
        for lifetime_counter in (
                "realFrameCount = 0", "submittedFrameCount = 0",
                "promotedFrameCount = 0"):
            self.assertNotIn(lifetime_counter, resize)
        self.assertIn("frameRate.resetPresentation()", resize)
        self.assertIn("resetHealthWindowAfterStreamChange()", resize)
        authoritative = generator.split(
            "public void setAuthoritativeSourceHz", 1)[1].split(
            "public void setFirstSubmittedFrameListener", 1)[0]
        self.assertIn('teardownDenseEpoch("authoritative-source-change")',
                      authoritative)
        self.assertLess(
            authoritative.index('teardownDenseEpoch("authoritative-source-change")'),
            authoritative.index("resetEndpointFifo()"),
        )
        self.assertIn("resetEndpointFifo()", authoritative)
        self.assertIn("resetHealthWindowAfterStreamChange()", authoritative)
        self.assertNotIn("realFrameCount = 0", authoritative)
        self.assertNotIn("promotedFrameCount = 0", authoritative)
        software_resize = generator.split(
            "private void uploadSoftwareFrame", 1)[1].split(
            "private void uploadBitmap", 1)[0]
        for lifetime_counter in (
                "realFrameCount = 0", "submittedFrameCount = 0",
                "promotedFrameCount = 0"):
            self.assertNotIn(lifetime_counter, software_resize)
        self.assertIn("frameRate.resetPresentation()", software_resize)
        self.assertIn("resetHealthWindowAfterStreamChange()", software_resize)
        allocation = generator.split("private void allocateHistoryTextures", 1)[1].split(
            "private void allocateTexture", 1)[0]
        self.assertIn("if (!denseResourcesReady)", allocation)
        for field in ("denseSignatureBaselineReady = false",
                      "denseSignatureSequence = 0", "denseSignatureReady = 0"):
            self.assertIn(field, allocation)
        proof_reset = generator.split(
            "if (requested) {", 1
        )[1].split("java.util.Arrays.fill(densePromotionWallObservedUs", 1)[0]
        self.assertIn("if (externalSignatureTimer == null)", proof_reset)
        preserved_external = proof_reset.split(
            "if (externalSignatureTimer == null)", 1
        )[1].split("}", 1)[0]
        self.assertIn("denseSignatureSequence = 0L", preserved_external)
        self.assertIn("denseSignatureBaselineReady = false", preserved_external)
        compare = generator.split("private void drawSignatureDifferenceQuery", 1)[1].split(
            "private boolean softwareImageIsUnique", 1)[0]
        for state in ("GL_SCISSOR_TEST", "GL_DEPTH_TEST", "GL_STENCIL_TEST", "GL_CULL_FACE"):
            self.assertIn("glDisable(GLES20." + state + ")", compare)
            self.assertIn("glEnable(GLES20." + state + ")", compare)
        self.assertIn("if (begun) signatureTimer.endSignature()", compare)
        self.assertIn("external asynchronous signature failed closed", signature)
        self.assertIn("rejectDense(\"async-signature-failure\"", signature)
        self.assertIn("signaturePixels.position(0)", signature)
        fallback = signature.split("rejectDense(\"async-signature-failure\"", 1)[1]
        self.assertIn("signatureTexture", fallback)
        self.assertIn("glViewport(0, 0, SIGNATURE_WIDTH, SIGNATURE_HEIGHT)", fallback)
        self.assertIn("drawTexture2d(latestTexture)", fallback)
        self.assertLess(fallback.index("drawTexture2d(latestTexture)"),
                        fallback.index("GLES20.glReadPixels"))
        self.assertIn("denseSignaturePending", generator)
        self.assertIn("denseSignatureCapability", generator)

    def test_dense_trajectory_diagnosis_reuses_async_atlas_only(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        helper = self.read(
            "unified-android/src/com/thorium/lucent/video/"
            "DenseFlowTrajectoryDiagnostics.java"
        )
        poll = generator.split(
            "private void pollProofAtlas", 1
        )[1].split(
            "/** Decodes schema36", 1
        )[0]
        self.assertIn("copyAtlasTile(denseBackward", poll)
        self.assertIn("accumulateDenseTrajectoryDiagnosis", poll)
        self.assertNotIn("glReadPixels", poll)
        self.assertIn("catch (RuntimeException diagnosticFailure)", poll)
        self.assertIn("Dense flow trajectory diagnostic", generator)
        self.assertIn("VALID_CONFIDENCE_BYTE = 48", helper)
        self.assertIn("ACTIVE_FLOW_BYTE_DELTA = 2", helper)
        self.assertIn("CHANGED_ENDPOINT_RGB_SUM = 36", helper)

    def test_software_cores_upload_source_frames_without_full_panel_canvas_copy(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        session = self.read(
            "unified-android/src/com/thorium/preview/game/LibretroEngineSession.java"
        )
        self.assertIn("submitSoftwareFrame", generator)
        self.assertIn("GLUtils.texSubImage2D", generator)
        self.assertIn("FrameGenerationRendererRegistry.find(target)", session)
        self.assertIn("primaryGenerator.submitSoftwareFrame", session)
        self.assertIn("lowerGenerator.submitSoftwareFrame", session)

    def test_software_upload_reverses_rows_inside_each_requested_crop(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        session = self.read(
            "unified-android/src/com/thorium/preview/game/LibretroEngineSession.java"
        )
        method = generator.split("public boolean submitSoftwareFrame", 1)[1].split(
            "/** Resizes without replacing", 1
        )[0]
        self.assertIn("final int[] snapshot = new int[width * height]", method)
        self.assertIn("(bottom - 1 - row) * frameWidth + left", method)
        self.assertIn("snapshot, row * width, width", method)
        self.assertNotIn("(top + row) * frameWidth + left", method)
        self.assertNotIn("generatorFrameColors", session)
        self.assertNotIn("DualScreenLayout.forGeneratorUpload", session)
        self.assertIn("primaryGenerator.submitSoftwareFrame(frameColors", session)
        self.assertIn("lowerGenerator.submitSoftwareFrame(frameColors", session)

    def test_proof_rearm_resets_lattice_and_regional_telemetry(self):
        # switch-b59 (2026-09-02): a proof re-arm after a pacing lift reset
        # proofSamples but not the lattice/regional counters, so every later
        # health record failed lattice == proof * cells.
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        block = generator.split("            proofSamples = 0;", 1)[1].split(
            "            syntheticProofSamples = 0;", 1)[0]
        self.assertIn("latticeRegionSamples = 0;", block)
        self.assertIn("regionalFlowRegionSamples = 0;", block)
        self.assertIn("latticeForwardPeakSupport = 0;", block)

    def test_software_frames_lift_the_curtain_and_carry_the_pacer_stamp(self):
        # nds-b51 (2026-09-02): melonDS ran behind the launch curtain because
        # only the SurfaceTexture path notified the first submitted frame, and
        # its exact 2:1 stream never proved a clock because software frames
        # were stamped with upload-thread arrival time.
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        upload = generator.split("private void uploadSoftwareFrame(", 1)[1].split(
            "private void consumeClassifiedFrame(", 1)[0]
        self.assertIn("notifyFirstSubmittedFrame();", upload)
        self.assertIn("float contentAspect, long scheduledTimestampNs)", generator)
        self.assertIn("scheduledTimestampNs > 0L ?", generator)
        session = self.read(
            "unified-android/src/com/thorium/preview/game/LibretroEngineSession.java"
        )
        self.assertIn("long scheduledNs = pacer.deadlineNanos();", session)
        self.assertIn("newest.producerTimestampNs = scheduledNs;", session)
        self.assertIn("frame.producerTimestampNs)", session)
        pacer = self.read(
            "unified-android/src/com/thorium/lucent/timing/AbsoluteFramePacer.java"
        )
        self.assertIn("public long deadlineNanos() { return deadlineNanos; }", pacer)

        def upload_crop(pixels, frame_width, left, top, right, bottom):
            width = right - left
            return [
                pixels[source_row * frame_width + x]
                for row in range(bottom - top)
                for source_row in (bottom - 1 - row,)
                for x in range(left, left + width)
            ]

        pixels = [
            10, 11, 12,
            20, 21, 22,
            30, 31, 32,
            40, 41, 42,
        ]
        self.assertEqual(upload_crop(pixels, 3, 0, 0, 3, 4), [
            40, 41, 42, 30, 31, 32, 20, 21, 22, 10, 11, 12,
        ])
        # A stacked DS composite must flip within top and bottom, never swap.
        self.assertEqual(upload_crop(pixels, 3, 0, 0, 3, 2),
                         [20, 21, 22, 10, 11, 12])
        self.assertEqual(upload_crop(pixels, 3, 0, 2, 3, 4),
                         [40, 41, 42, 30, 31, 32])
        self.assertEqual(upload_crop(pixels, 3, 1, 0, 3, 2),
                         [21, 22, 11, 12])

    def test_matched_refresh_bypass_and_pause_endpoint_are_explicit(self):
        cadence = self.read(
            "unified-android/src/com/thorium/lucent/video/FrameGenerationCadence.java"
        )
        self.assertIn("GENERATION_MARGIN", cadence)
        self.assertIn("if (!generatesIntermediateFrames()) return 1f", cadence)
        self.assertIn("elapsed >= estimatedSourcePeriodNs", cadence)

    def test_adaptive_visual_lock_has_only_requested_tiers_and_hysteresis(self):
        controller = self.read(
            "unified-android/src/com/thorium/lucent/video/AdaptiveFrameRateController.java"
        )
        # Tier protocol 2026-09-01: no 50 tier; a separate 60-Hz protocol.
        self.assertIn("int[] TIERS_120 = {60, 40, 30, 20}", controller)
        self.assertIn("int[] TIERS_60 = {60, 30, 20}", controller)
        self.assertIn("UniformFrameRatePlan.MAX_GENERATION_FACTOR", controller)
        self.assertNotIn("MAX_GENERATION_FACTOR = 3.0", controller)
        self.assertNotIn("int[] TIERS = {60, 50, 40, 30, 20}", controller)
        self.assertIn("INITIAL_TIER_PERIODS = 90", controller)
        self.assertIn("TIER_DECISION_WINDOW_NS = 10_000_000_000L", controller)
        self.assertIn("decisionPeriodsForElapsed(TIER_DECISION_WINDOW_NS)", controller)
        self.assertIn("SIXTY_TIER_SCHEDULER_HOLD_HZ = 1.0", controller)
        self.assertIn("Renderer consumption is not source-rate evidence", controller)
        self.assertIn("promoteIfDue", controller)
        self.assertIn("latestSequence == promotedSequence", controller)
        self.assertIn("bufferedOutputCredits", controller)
        self.assertIn("bufferedCreditedRightSequence", controller)
        # 2026-09-01: a bridged held/dropped span is credited per source
        # period it covers (span-proportional), capped at one extra period.
        self.assertIn("bufferedOutputCredits = Math.min((1 + spanPeriods) * perEndpoint",
                      controller)
        self.assertIn("private int outputCreditsPerEndpoint()", controller)
        self.assertIn("bufferedOutputCredits <= 0", controller)
        self.assertIn("--bufferedOutputCredits", controller)
        planner = self.read(
            "unified-android/src/com/thorium/lucent/video/UniformFrameRatePlan.java"
        )
        self.assertIn("MAX_GENERATION_FACTOR = 2.0", planner)
        self.assertIn("panelDivisor(sourceHz * 2.0, panelHz)", planner)
        self.assertIn("panelDivisor(sourceHz, panelHz)", planner)
        self.assertIn("Math.abs(panelHz / divisor - outputHz) <= COMPARISON_EPSILON_HZ",
                      planner)
        self.assertIn("currentUniformOutputPlan()", controller)
        self.assertIn(
            "selectedSixtyTierCannotOutrunSlowerPhysicalSource",
            self.read(
                "unified-android/test/com/thorium/lucent/video/"
                "AdaptiveFrameRateControllerTest.java"
            ),
        )

    def test_frame_generation_badge_reports_only_delivered_output(self):
        # 2026-09-01 owner directive: the corner badge is the product's
        # visible confirmation that generation is running. It must report the
        # physically delivered rate, claim a generated target only once
        # cadence is qualified, and never exist for an Off session.
        host = self.read(
            "unified-android/src/com/thorium/preview/game/InWindowGameHost.java"
        )
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        self.assertIn("private TextView frameRateBadge;", host)
        self.assertIn("updateFrameRateBadge(source, target, actual, qualified)", host)
        badge = host.split("private void updateFrameRateBadge(", 1)[1].split(
            "private void observeReportedOutput(", 1)[0]
        self.assertIn("request.frameGenerationMode == FrameGenerationSettings.Mode.OFF", badge)
        self.assertIn("boolean generating = qualified && target > source + 0.5", badge)
        self.assertIn("activeFrameGenerationBackend()", badge)
        self.assertNotIn('"S-- T-- A-- Backend="', host)
        self.assertIn("setFrameRateListener", host)
        self.assertIn("observeReportedOutput(actual)", host)
        report = generator[generator.index("private void reportStats()"):
                           generator.index("private void reportPresentationStall")]
        self.assertIn("long committed = presents - statsWindowStartPresents", report)
        self.assertNotIn("Math.floor(", report)
        self.assertNotIn("Math.min(targetOutput", report)
        self.assertIn("committed * 1_000_000_000.0 / elapsedNs", report)
        self.assertIn('Log.i(TAG, "App swap cadence"', report)
        self.assertIn("reportSourceAdmissionDiagnostic(now)", report)
        self.assertIn('Log.i(TAG, "Source admission diagnostic"', report)
        self.assertIn('" hwSubmits=" + hardware', report)
        self.assertIn('" uniqueVerdicts=" + unique', report)
        self.assertIn('" duplicateVerdicts=" + duplicate', report)
        self.assertIn('" acceptedEndpoints=" + endpoints', report)
        self.assertIn('" timestampProof=" +', report)
        self.assertIn('" canonical=" +', report)
        self.assertIn('" canonicalCandidate=" +', report)
        self.assertIn('" canonicalEvidenceMs=" +', report)
        self.assertIn('" canonicalProof=" +', report)
        self.assertIn('" physicalAvailable=" +', report)
        self.assertIn("physicalTracker.actualHz(scansPerOutput, panelPeriodNs)",
                      report)
        self.assertIn("externalPhysical ?\n" +
                      "                externalPhysicalCadence.actualHz(",
                      report)
        self.assertIn("externalPhysicalCadence.qualified(", report)
        self.assertIn("scansPerOutput, panelPeriodNs)", report)
        self.assertIn('" physicalSamples=" + (externalPhysical ?\n' +
                      "                        externalPhysicalCadence.sampleCount()",
                      report)
        self.assertIn('" physicalPresented=" + (externalPhysical ?\n' +
                      "                        externalPhysicalCadence.successfulPresents()",
                      report)
        self.assertIn("publishReportedFrameRate(source, physicalOutput, targetOutput,",
                      report)
        self.assertNotIn("publishReportedFrameRate(source, swapOutput", report)
        publish = generator[
            generator.index("private void publishReportedFrameRate"):
            generator.index("private void bindQuad")
        ]
        self.assertIn("String backendLabel = activeBackendLabel()", publish)
        self.assertIn("backendLabel.equals(reportedBackendLabel)", publish)
        self.assertIn("reportedBackendLabel = backendLabel", publish)
        self.assertIn('" backend=" + backendLabel', publish)
        tracker = self.read(
            "unified-android/src/com/thorium/preview/game/PhysicalPresentationTracker.java"
        )
        native = self.read(
            "unified-android/native/lucent_framegen_timer_jni.c"
        )
        self.assertIn("EGL_DISPLAY_PRESENT_TIME_ANDROID", native)
        self.assertIn("eglGetNextFrameIdANDROID", native)
        self.assertIn("eglGetFrameTimestampsANDROID", native)
        self.assertIn("commitPrepared", tracker)
        self.assertIn("recordDropped", tracker)
        self.assertIn('"Frame rate committed source="', generator)
        self.assertIn('callback.onFrameRate(source, targetOutput, output,', generator)

    def test_transient_timer_anomalies_rearm_bounded_instead_of_latching(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        timer = self.read(
            "unified-android/src/com/thorium/preview/game/DenseGpuTimer.java"
        )
        # Only the two named measurement anomalies are transient, and both
        # names come from the shared native status contract, not literals.
        self.assertIn("static final int STATUS_DISJOINT = 2;", timer)
        self.assertIn("static final int STATUS_ELAPSED_OVERFLOW = 5;", timer)
        classifier = generator.split(
            "private static boolean isTransientDenseRejection", 1
        )[1].split("private void rejectDense", 1)[0]
        self.assertIn('"gpu-timer-disjoint".equals(reason)', classifier)
        self.assertIn("DenseGpuTimer.STATUS_DISJOINT", classifier)
        self.assertIn("DenseGpuTimer.STATUS_ELAPSED_OVERFLOW", classifier)
        reject = generator.split("private void rejectDense", 1)[1].split(
            "private void teardownDenseEpoch", 1
        )[0]
        # A recoverable rejection still ends the epoch and collapses to
        # endpoint-only output; only the permanent latch is conditional.
        self.assertIn("if (!recoverable) densePyramidUnavailable = true;", reject)
        self.assertIn("DENSE_TRANSIENT_REJECT_REARM_LIMIT", reject)
        self.assertIn("frameRate.setGenerationAvailable(false)", reject)
        self.assertIn('teardownDenseEpoch("runtime-reject")', reject)
        self.assertIn('" recoverable="', reject)

    def test_external_transport_selects_surfacecontrol_timeline_only_when_required(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        request = self.read(
            "unified-android/src/com/thorium/lucent/video/"
            "FrameGenerationPresentationRequest.java"
        )
        transport = self.read(
            "unified-android/qualification-src/com/thorium/preview/game/"
            "RifePresentationTransport.java"
        )
        bridge = self.read(
            "experiments/rife-ncnn-vulkan-android/android-benchmark/app/src/"
            "main/java/com/emufusion/rifebenchmark/NativeRifeBridge.java"
        )
        presenter = self.read(
            "unified-android/lsfg-qualification-native/"
            "owned_surface_control_presenter.cpp"
        )
        native = self.read(
            "experiments/rife-ncnn-vulkan-android/android-benchmark/"
            "app/src/main/cpp/rife_benchmark_jni.cpp"
        )
        self.assertIn("implements Choreographer.VsyncCallback", generator)
        self.assertIn("frameData.getFrameTimelines()", generator)
        java_timeline_copy = generator.split(
            "private void onVsyncFrame(Choreographer.FrameData frameData)", 1
        )[1].split("private void postNextFrameCallback()", 1)[0]
        self.assertIn("externalTransport == null", java_timeline_copy)
        self.assertIn("copyCompositorFrameTimelines(", generator)
        self.assertIn("externalTransport.requiresCompositorFrameTimeline()",
                      generator)
        self.assertIn("compositorFrameTimelineNativeCallbackSequence", generator)
        self.assertIn("compositorFrameTimelineNativeFrameTimeNs", generator)
        selection = generator.split(
            "CompositorFrameTimeline.selectRefreshSafeTarget(", 1
        )[1].split("frameRate.selectBufferedPresentation(", 1)[0]
        self.assertIn("if (compositorTimeline == null)", selection)
        self.assertIn("return;", selection)
        self.assertIn("withTargetCompositorFrameTimeline(", generator)
        self.assertIn("expectedPresentationTimeNs()", generator)
        self.assertIn("hasCompositorFrameTimeline()", request)
        self.assertIn("MAX_COMPOSITOR_TIMELINE_DIAGNOSTIC_LOGS = 12", generator)
        self.assertIn("CompositorFrameTimeline.probe(", generator)
        self.assertIn(
            "CompositorFrameTimeline.selectEarliestRefreshSafeTarget(", generator
        )
        bootstrap_selector = self.read(
            "unified-android/src/com/thorium/lucent/video/"
            "CompositorFrameTimeline.java"
        ).split(
            "public static Selection selectEarliestRefreshSafeTarget(", 1
        )[1].split(
            "public static Selection select(", 1
        )[0]
        self.assertIn(
            "hasRefreshDerivedSubmissionReserve(", bootstrap_selector
        )
        self.assertIn("deadlinesNs[index]", bootstrap_selector)
        self.assertIn("fromCompositorTimeline(", generator)
        self.assertIn("Compositor frame-timeline miss", generator)
        self.assertIn("compositorFrameTimelineSuppliedCount", generator)
        self.assertIn('" copied=" + probe.suppliedCount()', generator)
        self.assertIn("recordCompositorFrameTimelineProbe(probe)", generator)
        self.assertIn("externalFrameTimelineProbeLive=", generator)
        self.assertIn("externalFrameTimelineProbeNoLive=", generator)
        self.assertIn(
            "surfaceControlPresentation != request.hasCompositorFrameTimeline()",
            transport,
        )
        self.assertIn(
            "RIFE presentation timing contract does not match its output path",
            transport,
        )
        self.assertIn("request.compositorFrameTimelineVsyncId()", transport)
        self.assertIn(
            "request.compositorTokenExpectedPresentationTimeNs()", transport
        )
        self.assertIn("request.compositorFrameTimelineDeadlineNs()", transport)
        self.assertIn("compositorFrameTimelineVsyncId", bridge)
        self.assertIn("compositorFrameTimelineExpectedNs", bridge)
        self.assertIn("compositorFrameTimelineDeadlineNs", bridge)
        self.assertIn('"ASurfaceTransaction_setFrameTimeline"', presenter)
        self.assertIn('"AChoreographer_postVsyncCallback"', presenter)
        self.assertIn("enableNativeFrameTimelineSource()", presenter)
        self.assertIn("nativeFrameTimeline(", presenter)
        self.assertIn("nativeCopySurfaceControlFrameTimelines", native)
        self.assertIn("enableNativeFrameTimelineSource();", native)
        self.assertIn('"nativeFrameTimelineSource\\\":', native)
        self.assertIn("requiresCompositorFrameTimeline()", transport)
        timeline_method = transport.split(
            "@Override public boolean requiresCompositorFrameTimeline()", 1
        )[1].split("@Override public boolean usesAppOwnedPresentation()", 1)[0]
        self.assertIn("return false;", timeline_method)
        self.assertIn("takeUnavailablePresentFences", presenter)
        self.assertIn("markDropped", presenter)
        live_present = presenter.split(
            "bool present(AHardwareBuffer* buffer", 1
        )[1].split("std::optional<Completion> pollCompletion", 1)[0]
        transaction_configuration = live_present.split(
            "ASurfaceTransaction_setBuffer(", 1
        )[1].split("ASurfaceTransaction_setOnComplete", 1)[0]
        self.assertEqual(
            transaction_configuration.count("setFrameTimeline_(transaction"), 1
        )
        self.assertEqual(
            transaction_configuration.count(
                "ASurfaceTransaction_setDesiredPresentTime"
            ),
            1,
        )
        self.assertIn("exact visible-target token validated",
                      transaction_configuration)
        self.assertIn("never identifies another panel scan",
                      transaction_configuration)
        self.assertLess(
            live_present.index("setFrameTimeline_(transaction"),
            live_present.index("ASurfaceTransaction_setDesiredPresentTime"),
        )
        self.assertLess(
            live_present.index("ASurfaceTransaction_setDesiredPresentTime"),
            live_present.index("ASurfaceTransaction_apply(transaction)"),
        )
        self.assertIn("kMinFrameTimelineSubmissionReserveNs", live_present)
        self.assertIn("kMaxFrameTimelineTargetErrorNs", live_present)
        self.assertIn("absoluteDifference(", live_present)
        self.assertIn("nativeFrameTimeline(", live_present)
        self.assertIn(
            "timeline->deadlineNs != compositorFrameTimelineDeadlineNs",
            live_present,
        )
        transaction_create = live_present.index(
            "transactionOwner(ASurfaceTransaction_create(), &ASurfaceTransaction_delete)"
        )
        self.assertLess(
            live_present.index(
                "timeline->deadlineNs != compositorFrameTimelineDeadlineNs"
            ),
            transaction_create,
        )
        self.assertLess(
            live_present.index("kMinFrameTimelineSubmissionReserveNs"),
            transaction_create,
        )
        # Rejections now preserve present identity/reason through the ledger
        # helper, rather than returning an unreported false.
        for reason in ("frame-timeline-api-missing", "timeline-revised",
                       "submission-window-missed"):
            self.assertIn('return rejectImmediate(presentId, "' + reason + '"',
                          live_present[:transaction_create])
        self.assertIn("transactionApplyStartNs", live_present)
        self.assertIn("transactionApplyEndNs", live_present)
        self.assertIn("std::lock_guard<std::mutex> applyLock(applyMutex_)",
                      live_present)
        timed_worker = presenter.split(
            "void timedApplyWorkerMain()", 1
        )[1].split("void rejectScheduled", 1)[0]
        self.assertNotIn("kTimedApplyOpeningReserveNs", presenter)
        self.assertIn("kMinFrameTimelineSubmissionReserveNs =\n"
                      "            2'000'000ULL", presenter)
        # Ready FIFO output is submitted promptly to its unchanged target.
        # The old deliberate deadline-minus-reserve sleep/spin consumed the
        # hardware margin. Actual worker/FD/deadline behavior is exercised by
        # test_lsfg_surface_early_submission, not certified by these strings.
        self.assertNotIn("kTimedApplySpinLeadNs", presenter)
        self.assertNotIn("scheduledCondition.wait_until", timed_worker)
        self.assertIn("state_->scheduled.front()", timed_worker)
        self.assertIn("state_->scheduled.pop_front()", timed_worker)
        self.assertIn('"deadline-expired-at-handoff"', live_present)
        self.assertIn(
            "if (state_->closing || state_->dispatchFailurePresentId != 0) return;",
            timed_worker,
        )
        self.assertIn("latestTimeline = nativeFrameTimeline(vsyncId)", timed_worker)
        self.assertIn("Absence is therefore", timed_worker)
        self.assertNotIn('"timeline-missing"', timed_worker)
        self.assertIn(
            "latestTimeline->expectedPresentationTimeNs != expectedNs",
            timed_worker,
        )
        self.assertIn("latestTimeline->deadlineNs != deadlineNs", timed_worker)
        self.assertLess(
            timed_worker.index("latestTimeline = nativeFrameTimeline(vsyncId)"),
            timed_worker.index("applyScheduled(presentId)"),
        )
        self.assertIn("if (deadlineNs <= applyNowNs)", timed_worker)
        self.assertLess(timed_worker.index("if (deadlineNs <= applyNowNs)"),
                        timed_worker.index("applyScheduled(presentId)"))
        self.assertIn("rejectScheduled(presentId,", timed_worker)
        for reason in (
            '"refresh-invalid"',
            '"expected-revised"',
            '"deadline-revised"',
            '"deadline-expired"',
            '"apply-exception"',
        ):
            self.assertIn(reason, timed_worker)
        self.assertNotIn("sync_wait", timed_worker)
        self.assertNotIn("vkWait", timed_worker)
        self.assertIn("canSubmitFrameTimeline(", presenter)
        self.assertGreaterEqual(native.count("transport->refresh_duration_ns"), 6)
        bridge_endpoint = bridge.split(
            "public int enqueueHardwareBufferRifePresentation(\n"
            "            Image previous,\n"
            "            Image current,\n"
            "            Image lookahead,\n"
            "            int width,\n"
            "            int height,\n"
            "            long interpolationTimestampNs,\n"
            "            long desiredPresentTimeNs,\n"
            "            long proofSequence,\n"
            "            long compositorFrameTimelineVsyncId,\n"
            "            long compositorFrameTimelineExpectedNs,", 1
        )[1].split("public int prepareHardwareBufferRifeOutput", 1)[0]
        self.assertIn(
            "(compositorFrameTimelineExpectedNs == 0L)", bridge_endpoint
        )
        self.assertIn(
            "compositorFrameTimelineExpectedNs,\n"
            "                    compositorFrameTimelineDeadlineNs",
            bridge_endpoint,
        )
        bridge_prepared = bridge.split(
            "public int enqueuePreparedHardwareBufferRifePresentation(\n"
            "            long proofSequence, long desiredPresentTimeNs,\n"
            "            long compositorFrameTimelineVsyncId,\n"
            "            long compositorFrameTimelineExpectedNs,", 1
        )[1].split("public void scheduleHardwareBufferRifePresentationRelease", 1)[0]
        self.assertIn(
            "(compositorFrameTimelineExpectedNs == 0L)", bridge_prepared
        )
        self.assertIn(
            "compositorFrameTimelineExpectedNs,\n"
            "                compositorFrameTimelineDeadlineNs",
            bridge_prepared,
        )
        endpoint_native = native.split(
            "NativeRifeBridge_nativeEnqueueHardwareBufferRifePresentation(", 1
        )[1].split(
            "NativeRifeBridge_nativeScheduleHardwareBufferRifePresentationRelease(",
            1,
        )[0]
        self.assertLess(
            endpoint_native.index("canSubmitFrameTimeline("),
            endpoint_native.index("AHardwareBuffer_fromHardwareBuffer"),
        )
        self.assertIn("compositor_frame_timeline_deadline_ns", endpoint_native)
        self.assertIn("compositor_frame_timeline_expected_ns", endpoint_native)
        self.assertIn(
            "(compositor_frame_timeline_expected_ns == 0)", endpoint_native
        )
        self.assertIn("if (!presented)", endpoint_native)
        nonvisible = endpoint_native.split("if (!presented)", 1)[1].split(
            "transport->surface_control_rows.push_back", 1
        )[0]
        self.assertIn("return 2;", nonvisible)
        self.assertNotIn("++transport->next_present_id", nonvisible)
        self.assertNotIn("++transport->present_calls", nonvisible)
        prepared_native = native.split(
            "NativeRifeBridge_nativeEnqueuePreparedHardwareBufferRifePresentation(",
            1,
        )[1].split(
            "NativeRifeBridge_nativeEnqueueHardwareBufferRifePresentation(", 1
        )[0]
        self.assertIn(
            "if (!transport->surface_control_presenter->present(",
            prepared_native,
        )
        self.assertIn("compositor_frame_timeline_expected_ns", prepared_native)
        self.assertIn(
            "(compositor_frame_timeline_expected_ns == 0)", prepared_native
        )
        self.assertIn("return 0;", prepared_native)
        enqueue_java = transport.split(
            "@Override public EnqueueResult enqueue(", 1
        )[1].split("@Override public", 1)[0]
        self.assertIn("boolean physicalPresentationSkipped = result == 2", enqueue_java)
        self.assertIn(
            "physicalPresentationSkipped ? 0L :\n                                nextPresentId++",
            enqueue_java,
        )
        self.assertIn(
            "if (!physicalPresentationSkipped) submitted.addLast(pending)",
            enqueue_java,
        )
        self.assertLess(
            enqueue_java.index("nativeInFlight = pending"),
            enqueue_java.index('"compositor-reserve-post-work"'),
        )
        self.assertLess(
            enqueue_java.index("nativePending = true"),
            enqueue_java.index('"compositor-reserve-post-work"'),
        )
        self.assertIn("return EnqueueResult.NOT_READY", enqueue_java)
        self.assertIn("long[] values = new long[15]", bridge)
        self.assertIn("frameTimelineDeadlineNs", bridge)
        self.assertIn("transactionApplyStartNs", bridge)
        self.assertIn("transactionApplyEndNs", bridge)
        self.assertIn("RIFE compositor deadline miss evidence", transport)
        vulkan_timing = native.split(
            "struct BenchmarkPastPresentationTimingGoogle", 1
        )[1].split("};", 1)[0]
        self.assertNotIn("frame_timeline_deadline", vulkan_timing)
        surface_timing = native.split(
            "struct SurfaceControlPresentationTiming", 1
        )[1].split("};", 1)[0]
        self.assertIn("frame_timeline_deadline", surface_timing)
        self.assertIn("transaction_apply_start", surface_timing)
        self.assertIn("transaction_apply_end", surface_timing)
        self.assertIn("bool physical_dropped = false", native)
        self.assertIn("bool event_queued = false", native)
        self.assertIn("takeUnavailablePresentFences()", native)
        self.assertIn("markDropped(present_id)", native)
        rejected = presenter.split("void rejectScheduled", 1)[1].split(
            "static void postNativeFrameTimelineCallback", 1
        )[0]
        self.assertIn("::close(row.acquireFenceFd)", rejected)
        self.assertIn("row.submissionRejected = true", rejected)
        self.assertIn("row.released = true", rejected)
        teardown = presenter.split("~Impl()", 1)[1].split(
            "bool present(AHardwareBuffer* buffer", 1
        )[0]
        self.assertLess(
            teardown.index("timedApplyStop_.store"),
            teardown.index("timedApplyWorker_.join"),
        )
        self.assertLess(
            teardown.index("timedApplyWorker_.join"),
            teardown.index("ASurfaceControl_release(surface_)"),
        )
        dropped = native.split(
            "takeUnavailablePresentFences();", 1
        )[1].split(
            "surface_control_presenter->pollCompletion()", 1
        )[0]
        self.assertIn("found->physical_dropped = true", dropped)
        self.assertIn("dropped_timing.physical_dropped = true", native)
        self.assertIn("return 2;", native.split(
            "nativePollPresentationTiming", 1
        )[1].split("nativeClosePresentationSurface", 1)[0])
        self.assertIn("if (result == 2)", bridge)
        self.assertIn("PresentationTiming.dropped(values[0])", bridge)
        self.assertIn("if (timing.dropped)", transport)
        self.assertIn("PresentationEvent.dropped(", transport)
        generator_poll = generator.split(
            "private void pollPhysicalPresentations()", 1
        )[1].split("private boolean externalPathManuallyCertified", 1)[0]
        self.assertIn("event.kind ==", generator_poll)
        self.assertIn("externalPresentationLedger.physicallyDropped(",
                      generator_poll)
        self.assertIn("externalPhysicalCadence.recordDropped(", generator_poll)
        self.assertLess(
            generator_poll.index("externalPresentationLedger.physicallyDropped("),
            generator_poll.index("ExternalPresentationLedger.Commit commit"),
        )
        retirement = native.split(
            "for (auto iterator = transport->surface_control_rows.begin();", 1
        )[1].split("return 0;", 1)[0]
        self.assertIn("!iterator->physical_dropped", retirement)
        self.assertIn("!iterator->event_queued", retirement)
        self.assertIn("kMaximumRejectionLogs = 12", presenter)
        self.assertIn("Timed apply rejected presentId=%llu reason=%s", presenter)
        self.assertIn('scheduledRejected', presenter)

    def test_in_poll_rejection_degrades_selected_synthetic_to_endpoint_hold(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        present = generator.split(
            "private void presentBuffered(PhysicalPresentationDeadline deadline", 1
        )[1].split("private void setPresentationViewport", 1)[0]
        # The poll can reject dense after this callback's synthetic selection;
        # that swap must hold the retained left endpoint, not throw.
        self.assertIn("boolean denseEnabledAtSelection = densePyramidEnabled;",
                      present)
        self.assertIn("rejectedAfterSelection", present)
        self.assertLess(
            present.index("} else if (rejectedAfterSelection) {"),
            present.index("buffered synthetic selected without an adjacent"),
        )
        degrade = present.split("} else if (rejectedAfterSelection) {", 1)[1] \
            .split("} else if (!activePairReady", 1)[0]
        self.assertIn("drawTexture2d(historyTextures[previousIndex])", degrade)

    def test_native_adapter_motion_dispatch_forwards_hat_dpad(self):
        session = self.read(
            "unified-android/src/com/thorium/preview/game/"
            "NativeAdapterEngineSession.java"
        )
        motion = session.split(
            "public boolean dispatchGenericMotionEvent", 1
        )[1].split("public boolean shouldShowOnScreenControls", 1)[0]
        # The Thor's physical d-pad reports HAT axes, not DPAD key events;
        # sticks-only forwarding left the d-pad dead in every native-adapter
        # game.
        self.assertIn("MotionEvent.AXIS_HAT_X", motion)
        self.assertIn("MotionEvent.AXIS_HAT_Y", motion)
        for ordinal in ("PAD_DPAD_LEFT", "PAD_DPAD_RIGHT",
                        "PAD_DPAD_UP", "PAD_DPAD_DOWN"):
            self.assertIn("active.setControl(" + ordinal, motion)

    def test_launch_never_blocks_qt_and_spinner_is_delayed_until_needed(self):
        theme = self.read("theme/theme.qml")
        stop = theme.split("function stopBottomPreviewForLaunch(game)", 1)[1] \
            .split("function wrappedSystemIndex", 1)[0]
        self.assertIn('request.open("GET", "http://127.0.0.1:43821/" + endpoint, true)',
                      stop)
        self.assertNotIn(", false)", stop)

        host = self.read(
            "unified-android/src/com/thorium/preview/game/InWindowGameHost.java"
        )
        build = host.split("private void buildUi()", 1)[1] \
            .split("private FrameLayout.LayoutParams match()", 1)[0]
        self.assertIn("new ProgressBar(activity)", build)
        self.assertIn("launchSpinner.setVisibility(View.GONE)", build)
        self.assertIn("postDelayed(revealLaunchSpinner, 500L)", build)
        self.assertIn("setFirstSubmittedFrameListener(this::dismissLaunchCurtain)",
                      build)
        dismiss = host.split("private void dismissLaunchCurtain()", 1)[1] \
            .split("private FrameLayout createPauseOverlay", 1)[0]
        self.assertIn("removeCallbacks(revealLaunchSpinner)", dismiss)
        self.assertIn("root.removeView(spinner)", dismiss)

        texture = self.read(
            "unified-android/src/com/thorium/preview/game/GameSurface.java"
        )
        updated = texture.split("onSurfaceTextureUpdated", 1)[1] \
            .split("private void ensureSurface", 1)[0]
        self.assertIn("firstFrameSubmitted = true", updated)
        self.assertIn("callback.run()", updated)

    def test_exact_game_hashes_are_persistently_cached_off_the_hot_path(self):
        cache = self.read(
            "unified-android/src/com/thorium/preview/game/"
            "GameContentIdentityCache.java"
        )
        self.assertIn('PREFS = "game-content-identities-v1"', cache)
        self.assertIn("file.getCanonicalPath()", cache)
        self.assertIn("file.length()", cache)
        self.assertIn("file.lastModified()", cache)
        self.assertIn("sample(digest, file, 0L)", cache)
        self.assertIn("file.length() - SAMPLE_BYTES", cache)
        self.assertIn("preferences.edit().putString(key, computed).apply()", cache)

        for relative in (
            "unified-android/src/com/thorium/preview/game/LibretroEngineSession.java",
            "unified-android/src/com/thorium/preview/game/PpssppGlesEngineSession.java",
        ):
            source = self.read(relative)
            self.assertIn("GameContentIdentityCache.sha256(appContext, game)", source)


if __name__ == "__main__":
    unittest.main()


class ProofMarkTest(unittest.TestCase):
    """Synthetic frames carry a marker-gated corner tag so a panel recording
    can label real/generated frames without trusting the logs."""

    def test_synthetic_frames_carry_marker_gated_proof_tag(self):
        source = (ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" /
                  "game" / "DisplayFrameGenerator.java").read_text()
        self.assertIn('new java.io.File("/data/local/tmp/lucent-proofmark")', source)
        self.assertIn("if (renderedSynthetic) drawProofMark();", source)
        self.assertIn("GLES20.glScissor(0, Math.max(0, outputHeight - PROOF_MARK_PX)", source)
        self.assertIn("GLES20.glClearColor(1f, 0f, 1f, 1f);", source)


class HardCutHoldTest(unittest.TestCase):
    """A hard cut holds the exact left endpoint from a measured 1x1 cut
    signal instead of warping surviving photometric matches."""

    def test_cut_signal_pass_and_left_endpoint_hold(self):
        source = (ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" /
                  "game" / "DisplayFrameGenerator.java").read_text()
        self.assertIn("DENSE_GLOBAL_CUT_SHADER", source)
        self.assertIn("float m=min(mismatch(vec2(0.0)),mismatch(seed));", source)
        self.assertIn("drawDenseGlobalCut(reference, target, denseGlobalSeedTextures[direction],", source)
        self.assertIn("float hardCut=uDenseCutEnabled*step(0.25,cutFraction);", source)
        self.assertIn("gl_FragColor=vec4(mix(finalColor,rawPrevious,hardCut),1.0);", source)


class DenseModeLegacyGlobalBranchTest(unittest.TestCase):
    """The production interpolate shader skips the dead legacy global-flow
    block in dense mode; the advected temporal prior itself was reverted
    (no gain on the Mario box metric, worse frame-wide result)."""

    def test_legacy_global_block_is_branched_out_in_dense_mode(self):
        source = (ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" /
                  "game" / "DisplayFrameGenerator.java").read_text()
        interpolate = source.split("MOTION_INTERPOLATE_SHADER =", 1)[1].split(
            "MOTION_PREDICTION_PROOF_SHADER", 1)[0]
        self.assertIn('" if(uDenseEncoding<0.5){\\n" +', interpolate)
        self.assertIn("mix(backward,globalBackward,currentGlobalUse)", interpolate)
        self.assertNotIn("DENSE_TEMPORAL_ADVECT_SHADER", source)


class BoxPyramidTest(unittest.TestCase):
    """The dense pyramid is a box-filter ladder (history -> /4 -> /16 -> 64x36
    -> 32x18), not a direct 2x2 point sample of every 30x30 block."""

    def test_pyramid_is_box_filtered(self):
        source = (ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" /
                  "game" / "DisplayFrameGenerator.java").read_text()
        self.assertIn("uniform float uTapScale;", source)
        self.assertIn("denseBoxWidths[stage] < denseLevelWidths[1]", source)
        self.assertIn("denseBoxHeights[stage] < denseLevelHeights[1]", source)
        self.assertIn("denseBoxWidths[stage], denseBoxHeights[stage], 1f);", source)
        self.assertIn("densePyramidTextures[endpoint][0], denseLevelWidths[1], denseLevelHeights[1], 0.5f);", source)
        self.assertIn("if(uExhaustiveRadius>.5){for(int y=-4;y<=4;y++){for(int x=-4;x<=4;x++){", source)
        self.assertIn('"uExhaustiveRadius"), coarsestFirst ? 4f : 0f);', source)
        self.assertIn("predictionAdmission*=1.0-popIn*weakOnly;", source)

    def test_dense_gpu_budget_scales_with_the_output_lattice(self):
        """Exact20->40 and30->60 have three/two panel scans per output;
        the GPU budget includes the completed pair's actual midpoint warp."""
        source = (ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" /
                  "game" / "DisplayFrameGenerator.java").read_text()
        self.assertIn("private long denseGpuBudgetUs() {", source)
        self.assertIn("int scans = frameRate.panelScansPerOutput();", source)
        self.assertIn("if (scans < 2 || panelPeriodUs <= 0L) return DENSE_GPU_BUDGET_US;", source)
        self.assertIn("periodUs * 4L / 5L - DENSE_GPU_BUDGET_WARP_RESERVE_US", source)
        self.assertRegex(source, r'if \(total > denseGpuBudgetUs\(\)\)\s*\{\s*'
                         r'failDenseGpuPairOnce\(sequence, "async-gpu-pair-over-budget"\);')
        self.assertRegex(source, r'if \(elapsedUs > denseGpuBudgetUs\(\)\)\s*\{\s*'
                         r'failDenseGpuPairOnce\(pairSequence, "async-gpu-stage-over-budget"\);')
        complete = source.split("private boolean consumeCompletedDenseGpuPairs()", 1)[1].split(
            "private long denseStageP95", 1)[0]
        self.assertIn("denseGpuPairLedger.completedTotalUs(pairSequence)", complete)
        self.assertIn("denseGpuHeadroom.recordShader(denseGpuHeadroom.evidenceEpoch(),", complete)
        self.assertIn("pairSequence, totalUs, denseGpuBudgetUs()", complete)
        self.assertIn("result.presentationEpoch != schedulerPresentationEpoch()", complete)
        self.assertIn("GpuPhysicalHeadroomLedger.Outcome.VERIFIED_HEADROOM", complete)
        self.assertIn("if (!result.generated()) continue;", complete)
        self.assertIn("result.shaderBudgetUs, verified", complete)
        self.assertIn("denseGpuAdaptation.invalidateRecoveryEvidence()", complete)
        self.assertNotIn("System.nanoTime()", complete)
        self.assertNotIn("total > DENSE_GPU_BUDGET_US", source)

    def test_solver_breaks_aperture_ties_toward_the_neighbourhood(self):
        """Equal-cost candidates (a yard line under any horizontal shift) must
        resolve toward the neighbourhood median rather than scan order."""
        source = (ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" /
                  "game" / "DisplayFrameGenerator.java").read_text()
        self.assertIn("float reg(vec2 f,vec2 m){return .0025*min(length(f-m),12.0);}", source)
        self.assertIn("bc+=reg(c,m);", source)
        self.assertEqual(source.count("float z=objective(f)+reg(f,m);"), 2)
