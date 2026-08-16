import pathlib
import math
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


class SystemwideFrameGenerationTest(unittest.TestCase):
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
        self.assertIn("observeUniqueFrame(producerTimestampNs", generator)
        # Endpoint acceptance is still keyed to producer timestamps, but the
        # timestamp now flows through the endpoint selector rather than being
        # passed raw alongside the texture.
        self.assertIn("selectPresentationEndpoint(producerTimestampNs)", generator)
        self.assertIn("acceptPresentationEndpoint(latestTexture,", generator)
        self.assertIn("presentationEndpointSelector.selectedTimestampNs())",
                      generator)
        self.assertIn("softwareImageIsUnique", generator)
        for system in ("nes", "snes", "gb", "gba", "megadrive"):
            self.assertIn('case "{}":'.format(system), host)
        for adaptive in ("gamecube", "ps2", "wii", "switch", "ps3"):
            self.assertNotIn('case "{}":'.format(adaptive), host)
        self.assertIn("layer.setAuthoritativeSourceHz", host)
        self.assertIn("declaredVideoHz()", host)
        self.assertIn("frameGenerator.setAuthoritativeSourceHz", surface)

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
            self.assertIn("new DisplayFrameGenerator", source)
            self.assertIn("frameGenerator.inputSurface()", source)
            self.assertIn("frameGenerator.resize", source)
            self.assertIn("generator.close()", source)

    def test_owner_setting_is_on_by_default_and_guards_every_surface(self):
        setting = self.read(
            "unified-android/src/com/thorium/preview/game/FrameGenerationSettings.java"
        )
        self.assertIn('getBoolean(ENABLED, true)', setting)
        self.assertIn('putBoolean(ENABLED, enabled).commit()', setting)

        for relative in (
            "unified-android/src/com/thorium/preview/game/GameSurface.java",
            "unified-android/src/com/thorium/preview/game/GameSurfaceView.java",
            "android-companion/src/com/thorium/preview/PreviewActivity.java",
        ):
            source = self.read(relative)
            self.assertIn("if (!FrameGenerationSettings.isEnabled(", source, relative)
            self.assertIn("using direct presentation", source, relative)

        service = self.read("android-companion/src/com/thorium/preview/PreviewService.java")
        self.assertGreaterEqual(service.count('"/settings/frame-generation"'), 3)
        self.assertIn('if (!values.containsKey("enabled"))', service)
        self.assertIn("FrameGenerationSettings.isEnabled(this)", service)
        self.assertIn("FrameGenerationSettings.setEnabled(this, enabled)", service)

        theme = self.read("theme/theme.qml")
        self.assertIn("property bool frameGenerationEnabled: true", theme)
        self.assertIn('"FRAME GENERATION"', theme)
        self.assertIn('if (index === 21) return frameGenerationEnabled ? "ON" : "OFF"',
                      theme)
        self.assertIn('api.memory.has("lucentFrameGenerationEnabled")', theme)
        self.assertIn('requestPreviewEndpoint("settings/frame-generation?enabled=" +', theme)
        self.assertIn("setFrameGenerationEnabled(!frameGenerationEnabled)", theme)

    def test_every_primary_engine_uses_a_distinct_gameplay_surface_layer(self):
        host = self.read(
            "unified-android/src/com/thorium/preview/game/InWindowGameHost.java"
        )
        self.assertIn("GameSurfaceView layer = new GameSurfaceView(activity)", host)
        self.assertNotIn("new GameSurface(activity)", host)
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
        # Rotation remains a presentation transform after generation. The
        # SurfaceView itself is measured portrait and its layer turns +90°.
        self.assertIn("new ClockwiseGameplaySurfaceView(this)", clockwise)
        self.assertIn("gameplaySurface.setRotation(90f)", clockwise)
        self.assertIn("setMeasuredDimension(parentHeight, parentWidth)", preview)

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
        self.assertIn("return Math.min(panel, source)", controller)
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
        self.assertLess(decision.index("bufferedPendingPresentation = presentation"),
                        decision.index("public void commitBufferedPresentation"))
        callback = generator[generator.index("@Override public void doFrame"):
                             generator.index("private boolean latestImageIsUnique")]
        self.assertLess(callback.index("choreographer.postFrameCallback(this)"),
                        callback.index("presentBuffered(frameTimeNanos, presentation"))
        self.assertIn("eglPresentationTimeANDROID", generator)
        self.assertIn("nextPresentationTimeNs", generator)
        self.assertLess(callback.index("prepareBufferedPairIfPossible()"),
                        callback.index("selectBufferedPresentation("))
        self.assertIn("presentBuffered(frameTimeNanos, presentation", callback)
        self.assertIn("abortBufferedPresentation()", callback)
        present = generator[generator.index("private void presentBuffered("):
                            generator.index("private void reportStats")]
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
        fifo = generator[generator.index("private void observeUniqueFrame"):
                         generator.index("private void promoteLatestTexture")]
        self.assertIn("ENDPOINT_FIFO_CAPACITY = 4", generator)
        self.assertIn("ENDPOINT_FIFO_PRIME_DEPTH = ENDPOINT_FIFO_CAPACITY", generator)
        self.assertIn("ENDPOINT_FIFO_JITTER_RESERVE = 2", generator)
        self.assertIn("endpointFifoTextures", fifo)
        self.assertIn("selectPresentationEndpoint", fifo)
        self.assertIn("acceptPresentationEndpoint", fifo)
        observation = fifo[fifo.index("private void observeUniqueFrame"):
                           fifo.index("private boolean selectPresentationEndpoint")]
        self.assertIn("frameRate.onProducerFrame", observation)
        self.assertNotIn("endpointFifoTextures", observation)
        selection = fifo[fifo.index("private boolean selectPresentationEndpoint"):
                         fifo.index("private void acceptPresentationEndpoint")]
        self.assertIn("frameRate.presentationSourceFps()", selection)
        self.assertIn("presentationEndpointSelector.select", selection)
        self.assertIn("rawDeltaNs / 2L", endpoint_selector)
        self.assertIn("at most one", endpoint_selector)
        self.assertIn("consumeEndpointIntoHistory", fifo)
        self.assertIn("activeRightSequence != activeLeftSequence + 1L", fifo)
        overflow = fifo[fifo.index("if (endpointFifoCount < ENDPOINT_FIFO_CAPACITY)"):
                        fifo.index("copyTexture(sourceTexture")]
        self.assertIn("endpointFifoHead = 0", overflow)
        self.assertIn("endpointFifoCount = 1", overflow)
        self.assertIn("Arrays.fill(endpointFifoSequence, 0L)", overflow)
        prepare = fifo[fifo.index("private void prepareBufferedPairIfPossible"):
                       fifo.index("private void copyBufferedEndpoints")]
        self.assertIn("endpointFifoCount < ENDPOINT_FIFO_PRIME_DEPTH", prepare)
        self.assertIn("three complete source intervals", prepare)
        self.assertIn("right == left + 1L", prepare)
        self.assertIn("discardEndpointFifoHead()", prepare)
        self.assertIn("next != activeLeftSequence + 1L", prepare)
        self.assertLess(prepare.index("next != activeLeftSequence + 1L"),
                        prepare.index("copyBufferedEndpoints(false)"))
        discontinuity = prepare[prepare.index("next != activeLeftSequence + 1L"):
                                prepare.index("copyBufferedEndpoints(false)")]
        self.assertIn("invalidateBufferedPairForReprime()", discontinuity)
        self.assertIn("prepareBufferedPairIfPossible()", discontinuity)
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
        self.assertIn("latestImageIsUnique(producerArrivalNs)", callback)
        self.assertIn("observeUniqueFrame", callback)
        self.assertIn("selectPresentationEndpoint(producerArrivalNs)", callback)
        self.assertIn("acceptPresentationEndpoint(latestTexture", callback)
        self.assertNotIn("inputTexture.getTimestamp()", callback)
        self.assertLess(callback.index("latestImageIsUnique(producerArrivalNs)"),
                        callback.index("selectPresentationEndpoint(producerArrivalNs)"))
        observation = generator[generator.index("private void observeUniqueFrame"):
                                generator.index("private boolean selectPresentationEndpoint")]
        self.assertIn("frameRate.onProducerFrame", observation)
        self.assertIn("normalizedTimestamp, submissionOrdinal", observation)
        self.assertNotIn("endpointFifoTextures", observation)
        self.assertIn("SIGNATURE_WIDTH = 16", generator)
        self.assertIn("SIGNATURE_HEIGHT = 9", generator)
        self.assertIn("sourceSignatureIsUnique()", generator)
        self.assertIn("submitted=", generator)
        selector = generator[generator.index("private boolean selectPresentationEndpoint"):
                             generator.index("private void acceptPresentationEndpoint")]
        self.assertNotIn("endpointFifoCount >= ENDPOINT_FIFO_CAPACITY", selector)
        self.assertIn("sourceFps == 60", selector)
        self.assertIn("endpointFifoCount < ENDPOINT_FIFO_JITTER_RESERVE", selector)

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
        self.assertIn("requested && densePyramidSwitch.enabled()", generator)
        self.assertIn("DENSE_PASSES_PER_PROMOTION = 38", generator)
        self.assertIn("DENSE_V26_ANALYSIS_MAX_WIDTH = 256", generator)
        self.assertIn("DENSE_V26_ANALYSIS_MAX_HEIGHT = 144", generator)
        self.assertIn("DENSE_LEVEL_ITERATIONS = {4, 4, 8}", generator)
        # The coarsest step is tier-adaptive: 47px reach for 40+ FPS
        # sources, 83px for <=30 FPS sources whose per-frame
        # displacement doubles (physically measured 72px on the Thor,
        # 2026-08-15) — same iteration count and tap cost.
        self.assertIn("lockedSourceFps() <= 30 ? 9.0f : 4.5f", generator)
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
        self.assertIn("step(distance(f,fm),1.5)", generator)
        self.assertIn(
            "textureGate=max(smoothstep(.008,.030,textureEnergy),coherentFlat)",
            generator,
        )
        self.assertIn("floor(v*256.0+.5)", generator)
        self.assertIn("decReverse", generator)
        self.assertIn("uUseReciprocalGuide", generator)
        self.assertIn("decGuideLinear", generator)
        self.assertIn("q1=clamp(vTexCoord-first/uSourceSize", generator)
        self.assertIn("q2=clamp(vTexCoord-second/uSourceSize", generator)
        self.assertIn("q3=clamp(vTexCoord-third/uSourceSize", generator)
        self.assertIn("-decGuideLinear(q3)", generator)
        self.assertIn("boolean coarsestFirst = level == DENSE_LEVELS - 1", generator)
        self.assertIn("boolean finestBootstrap = level == 0", generator)
        self.assertIn("boolean finestLast = level == 0", generator)
        self.assertIn(
            "(coarsestFirst || finestBootstrap || finestLast)", generator)
        self.assertIn("refineDenseForwardFromReverse", generator)
        self.assertIn(
            "(direction == 0 && level == 0 ? 1 : 0)", generator)
        self.assertIn('"uUpdateStep", 0f, 0f', generator)
        self.assertIn("vec2 chroma(vec3 c)", generator)
        self.assertIn(".18*cc(tv,rv)", generator)
        self.assertIn(".07*(cc(txpv,rxpv)", generator)
        self.assertIn("uBypassSearch", generator)
        self.assertIn(
            "if(uBypassSearch>.5&&uUseReciprocalGuide<.5){gl_FragColor=enc(c);return;}",
            generator,
        )
        self.assertIn("if(uBypassSearch>.5){gl_FragColor=enc(c);return;}", generator)
        self.assertIn(
            '"uBypassSearch"), direction == 1 && level == 0 &&', generator)
        self.assertIn("iteration == 0 ? 1f : 0f", generator)
        self.assertIn("8*4.5 + 4*2 + 3*1 = 47px", generator)
        self.assertIn("uUseWidePatch", generator)
        self.assertIn("float cs=abs(step(t,txp)-step(r,rxp))", generator)
        self.assertIn("z+=.22*(rb(td1-rd1)", generator)
        self.assertIn("uFinalConsensus", generator)
        self.assertIn("float med4(float a,float b,float c,float d)", generator)
        self.assertIn("float s=step(distance(l,m),2.5)", generator)
        self.assertIn("w=max(w,.65*g)", generator)
        self.assertIn(
            '"uUseWidePatch"), level == DENSE_LEVELS - 1 ? 1f : 0f',
            generator,
        )
        self.assertIn(
            '"uFinalConsensus"), level == 0 &&', generator)
        self.assertIn(
            "iteration == iterations - 1", generator)
        self.assertIn("vec2 q1=clamp(vTexCoord-first/uSourceSize", generator)
        self.assertIn("float gc=cost(g);if(gc<bc)", generator)
        self.assertIn("direction == 1 &&", generator)
        self.assertIn("level == DENSE_LEVELS - 1 &&", generator)
        self.assertIn("level == 0 &&", generator)
        self.assertIn("denseFinalTextures[0] : denseFlowTextures[0][0][0]", generator)
        self.assertIn("denseSceneCut", generator)
        self.assertIn("drawTexture2d(historyTextures[currentIndex])", generator)
        self.assertIn("(field.rg*255.0-128.0)/127.0", generator)
        self.assertIn("finally {", generator)
        self.assertIn("emufusion_framegen_dense_pyramid", surface)
        self.assertIn("emufusion_framegen_dense_v27_192", surface)
        self.assertIn("if (!qualificationProofEnabled()) return false", surface)
        self.assertIn("return rawDensePyramidRequested();", surface)
        self.assertIn("if (!rawDensePyramidRequested()) return false", surface)
        v27_switch = surface.split(
            "private boolean denseV27ReducedAnalysisEnabled()", 1)[1].split(
            "private void releaseGenerator()", 1)[0]
        self.assertNotIn("qualificationProofEnabled()", v27_switch)
        self.assertNotIn("densePyramidEnabled()", v27_switch)
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
        self.assertIn("if (!qualificationProofEnabled()) return false", dense)
        self.assertIn("return rawDensePyramidRequested();", dense)
        self.assertIn('"emufusion_framegen_dense_pyramid"', raw)
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
        self.assertIn("denseRequested = requested && densePyramidSwitch.enabled()", refresh)
        self.assertIn("if (denseRequested)", refresh)
        self.assertIn("v27Requested = denseV27ReducedAnalysisSwitch.enabled()", refresh)

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
        self.assertIn("if (!rawDensePyramidRequested()) return false", v28)
        self.assertIn('"emufusion_framegen_dense_v28_160"', v28)
        self.assertNotIn("qualificationProofEnabled()", v28)
        refresh = generator.split(
            "private void refreshQualificationProofState()", 1)[1].split(
            "private String activeProofContract", 1)[0]
        self.assertIn("if (denseRequested)", refresh)
        self.assertIn("v28Requested = denseV28ReducedAnalysisSwitch.enabled()", refresh)
        self.assertIn("(v27Requested && v28Requested)", refresh)
        self.assertIn("dense-fragment-128x72-v39-present-timed-vector-trajectory-qualification-x2-presented", generator)
        self.assertIn("DENSE_V28_PROOF_SCHEMA_VERSION = 39", generator)
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
        self.assertIn("HEALTH_LOG_MAX_UTF8_BYTES = 3900", generator)
        self.assertEqual(generator.count("logBoundedHealth("), 3)
        bounded = generator.split("private static void logBoundedHealth", 1)[1].split(
            "private String wallTelemetry", 1)[0]
        self.assertIn("StandardCharsets.UTF_8", bounded)
        self.assertIn("split health record exceeds", bounded)
        cycle = generator.split("DENSE_CYCLE_SHADER", 1)[1].split(
            "DENSE_Q8_PROBE_SHADER", 1)[0]
        self.assertIn(
            "float conf=activeGate*inb*cg*photoGate*textureGate", cycle)
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
        self.assertIn("DENSE_PASSES_PER_PROMOTION = 38", generator)
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
        self.assertIn("requestedEglContextMajor = denseV28ReducedAnalysisRequested ? 3 : 2", generator)
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
        compare = generator.split("private void drawSignatureDifferenceQuery", 1)[1].split(
            "private boolean softwareImageIsUnique", 1)[0]
        for state in ("GL_SCISSOR_TEST", "GL_DEPTH_TEST", "GL_STENCIL_TEST", "GL_CULL_FACE"):
            self.assertIn("glDisable(GLES20." + state + ")", compare)
            self.assertIn("glEnable(GLES20." + state + ")", compare)
        self.assertIn("if (begun) denseGpuTimer.endSignature()", compare)
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

    def test_software_cores_upload_source_frames_without_full_panel_canvas_copy(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        session = self.read(
            "unified-android/src/com/thorium/preview/game/LibretroEngineSession.java"
        )
        self.assertIn("submitSoftwareFrame", generator)
        self.assertIn("GLUtils.texSubImage2D", generator)
        self.assertIn("DisplayFrameGenerator.forInputSurface(target)", session)
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
        self.assertIn("int[] TIERS = {60, 50, 40, 30, 20}", controller)
        self.assertIn("INITIAL_TIER_PERIODS = 90", controller)
        self.assertIn("TIER_DECISION_WINDOW_NS = 10_000_000_000L", controller)
        self.assertIn("decisionPeriodsForElapsed(TIER_DECISION_WINDOW_NS)", controller)
        self.assertIn("SIXTY_TIER_SCHEDULER_HOLD_HZ = 4.0", controller)
        self.assertIn("Renderer consumption is not source-rate evidence", controller)
        self.assertIn("promoteIfDue", controller)
        self.assertIn("latestSequence == promotedSequence", controller)
        self.assertIn("bufferedSyntheticCredits", controller)
        self.assertIn("bufferedCreditedRightSequence", controller)
        self.assertIn("bufferedSyntheticCredits = Math.min(2", controller)
        self.assertIn("bufferedSyntheticCredits <= 0", controller)
        self.assertIn("--bufferedSyntheticCredits", controller)
        self.assertIn(
            "selectedSixtyTierCannotOutrunSlowerPhysicalSource",
            self.read(
                "unified-android/test/com/thorium/lucent/video/"
                "AdaptiveFrameRateControllerTest.java"
            ),
        )

    def test_upper_left_badge_reports_only_committed_output_rates(self):
        host = self.read(
            "unified-android/src/com/thorium/preview/game/InWindowGameHost.java"
        )
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        self.assertIn("Gravity.TOP | Gravity.START", host)
        self.assertIn('frameRateBadge.setText("--/--")', host)
        self.assertIn('(output > 0 ? Integer.toString(output) : "--")', host)
        self.assertIn("frameRateBadge.setTextSize(10f)", host)
        self.assertIn("Color.argb(165, 255, 255, 255)", host)
        self.assertIn("Color.argb(62, 0, 0, 0)", host)
        self.assertNotIn('source + " / " + output + " FPS"', host)
        self.assertIn("setFrameRateListener", host)
        report = generator[generator.index("private void reportStats()"):
                           generator.index("private void bindQuad")]
        self.assertIn("long committed = presents - statsWindowStartPresents", report)
        self.assertIn("Math.floor(", report)
        self.assertIn("publishReportedFrameRate(source, 0, targetOutput)", report)
        self.assertIn('"Frame rate committed "', report)
        self.assertNotIn('callback.onFrameRate(source, targetOutput)', report)

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

    def test_in_poll_rejection_degrades_selected_synthetic_to_endpoint_hold(self):
        generator = self.read(
            "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
        )
        present = generator.split(
            "private void presentBuffered(long frameTimeNanos", 1
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


if __name__ == "__main__":
    unittest.main()
