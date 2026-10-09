import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
STAGER_PATH = ROOT / "unified-android/tools/stage_rife_framegen_qualification.py"
SPEC = importlib.util.spec_from_file_location("rife_qualification_stager", STAGER_PATH)
STAGER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(STAGER)


class RifeQualificationPackagingTest(unittest.TestCase):
    def test_visible_context_priority_is_scoped_and_has_fallback(self):
        source = (ROOT / "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java").read_text()
        context = source.split("private void initializeEgl()", 1)[1].split("int[] surfaceAttributes", 1)[0]
        self.assertIn('externalTransport != null &&\n                appOwnedPresentation', context)
        self.assertIn('contains(" EGL_IMG_context_priority ")', context)
        self.assertIn('eglContext == EGL14.EGL_NO_CONTEXT && prioritizeExternalPresentation', context)
        self.assertIn('EGL14.eglQueryContext(eglDisplay, eglContext,', context)
        self.assertEqual(context.count('EGL14.eglCreateContext('), 2)

    def test_app_owned_poll_enables_optional_driver_timestamps(self):
        source = (ROOT / "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java").read_text()
        poll = source.split("private void pollAppOwnedPhysicalPresentations()", 1)[1]
        poll = poll.split("PhysicalPresentationTracker.Event event;", 1)[0]
        self.assertLess(poll.index("tracker.setReadyTimingEnabled(true);"),
                        poll.index("tracker.poll();"))

    def test_spatial_qualification_build_selects_matching_manifest(self):
        source=(ROOT / "unified-android/build.sh").read_text()
        self.assertIn('RIFE_SPATIAL_DISPATCH=${LUCENT_RIFE_SPATIAL_DISPATCH:-0}',source)
        self.assertIn('upstream-prepared-v22-spatial/prepared-manifest.json',source)
        self.assertIn('then set -- -PspatialDispatch; else set --; fi',source)
        self.assertIn('"$RIFE_GRADLE" --no-daemon "$@"',source)
        self.assertIn('--prepared-manifest "$RIFE_PREPARED_MANIFEST"',source)

    def test_worker_affinity_is_stack_scoped_without_native_context_lock(self):
        base = ROOT / "experiments/rife-ncnn-vulkan-android/android-benchmark/app/src/main"
        native = (base / "cpp/rife_benchmark_jni.cpp").read_text()
        wrapper = native.split("Java_com_emufusion_rifebenchmark_NativeRifeBridge_nativeRunPreparationWorker(", 1)[1].split('extern "C"', 1)[0]
        self.assertIn("ScopedRecordingCpu worker_cpu_scope(true)", wrapper)
        self.assertIn("env->CallVoidMethod(worker, run)", wrapper)
        self.assertNotIn("global_lock", wrapper)
        self.assertNotIn("context_lock", wrapper)
        self.assertNotIn("ExceptionClear", wrapper)
        transport = (ROOT / "unified-android/qualification-src/com/thorium/preview/game/RifePresentationTransport.java").read_text()
        self.assertIn("() -> NativeRifeBridge.runPreparationWorker(runnable)", transport)

    def test_displayed_output_retains_ownership_until_owner_release(self):
        source = (ROOT / "unified-android/qualification-src/com/thorium/preview/game/RifePresentationTransport.java").read_text()
        release = source.split("@Override public void releaseAppOwnedOutput(", 1)[1].split(
            "private void releaseAppOwnedOutputNow(", 1)[0]
        deferred = release.split("if (preparationInFlight) {", 1)[1].split("return;", 1)[0]
        self.assertIn("deferredOutputReleases.put", deferred)
        self.assertNotIn(".remove(", deferred)
        self.assertNotIn("releaseBoundHardwareBufferRifeOutput", deferred)
        drain = source.split("private void drainDeferredOutputReleases()", 1)[1].split(
            "private long takeProofSequence()", 1)[0]
        self.assertLess(drain.index("requireOwner();"), drain.index("releaseAppOwnedOutputNow("))
        self.assertLess(drain.index("if (preparationInFlight) return;"), drain.index("releaseAppOwnedOutputNow("))
        self.assertLess(drain.index("releaseAppOwnedOutputNow("), drain.index("releases.remove();"))
        take = source.split("private AppOwnedOutput takeReadyOutput(", 1)[1].split(
            "private static ExternalGeneratedContentProof", 1)[0]
        self.assertIn("if (cachedOutputDiscardPending) return null;", take)

    def test_bound_output_poll_never_waits_for_recording_locks(self):
        native = (ROOT / "experiments/rife-ncnn-vulkan-android/android-benchmark/app/src/main/cpp/rife_benchmark_jni.cpp").read_text()
        poll = native.split("Java_com_emufusion_rifebenchmark_NativeRifeBridge_nativePollBoundHardwareBufferRifeOutputs(", 1)[1].split('extern "C"', 1)[0]
        self.assertEqual(poll.count("std::try_to_lock"), 2)
        self.assertIn("if (!global_lock.owns_lock()) return 0;", poll)
        self.assertIn("if (!context_lock.owns_lock()) return 0;", poll)
        self.assertNotIn("std::lock_guard", poll)
        self.assertLess(poll.index("if (!context_lock.owns_lock()) return 0;"),
                        poll.index("poll_app_owned_output_releases("))

    def test_output_worker_publishes_image_ownership_and_teardown_joins_first(self):
        source = (ROOT / "unified-android/qualification-src/com/thorium/preview/game/RifePresentationTransport.java").read_text()
        start = source.split("private PreparationResult startPreparation(", 1)[1].split(
            "private void finishOutputPreparation(", 1)[0]
        dispatch = start.index("preparationWorker.execute(")
        self.assertLess(start.index("preparedPresentation = pending;"), dispatch)
        self.assertLess(start.index("preparationInFlight = true;"), dispatch)
        self.assertGreater(start.index("jobBridge.prepareHardwareBufferRifeOutput("), dispatch)
        self.assertIn("owner.post(() -> finishOutputPreparation(", start)
        finish = source.split("private void finishOutputPreparation(", 1)[1].split(
            "@Override public PreparationReadiness", 1)[0]
        self.assertIn("pending.timelineEpoch != timelineEpoch || pending.discardRequested", finish)
        self.assertIn("if (closed) return;", finish)
        close = source.split("@Override public void close()", 1)[1]
        self.assertLess(close.index("preparationWorker.awaitTermination("), close.index("discardCachedOutputs();"))
        self.assertLess(close.index("if (!preparationStopped)"), close.index("bridge.closePresentationSurface()"))

    def test_prepare_busy_gate_precedes_native_pool_poll(self):
        source = (ROOT / "unified-android/qualification-src/com/thorium/preview/game/RifePresentationTransport.java").read_text()
        prepare = source.split("@Override public PreparationResult prepare(", 1)[1].split(
            "private PreparationResult startPreparation(", 1)[0]
        gate = prepare.index("return PreparationResult.NOT_READY;")
        self.assertIn("preparationInFlight", prepare[:gate])
        self.assertLess(gate, prepare.index("bridge.pollBoundHardwareBufferRifeOutputs()"))
        self.assertLess(gate, prepare.index("secondaryBridge.pollBoundHardwareBufferRifeOutputs()"))

    def test_rife_route_requires_alpha_and_explicit_flag_after_off_guard(self):
        source = (ROOT / "unified-android/src/com/thorium/preview/game/FrameGenerationSettings.java").read_text()
        route = source.split("Context context, int displayId, Mode launchMode) {", 1)[1]
        self.assertLess(route.index("launchMode == Mode.OFF) return null;"),
                        route.index("Settings.Global.getInt"))
        self.assertLess(route.index("launchMode == Mode.BUILT_IN_ALPHA"),
                        route.index('"emufusion_framegen_rife_qualification", 0) != 1'))
        self.assertIn("ExternalFrameGenerationTransportLoader.rifeQualification(context)", route)
        self.assertIn("if (launchMode != Mode.LSFG) return null;", route)

    def setUp(self):
        self.lock_path = ROOT / "experiments/rife-ncnn-vulkan-android/upstream-lock.json"
        self.lock = json.loads(self.lock_path.read_text(encoding="utf-8"))

    def test_twine_physical_harness_detects_system_server_failure_without_screencap(self):
        harness = (ROOT / ".evidence-rife-twine-r146-30to60" /
                   "run-device-test.sh").read_text(encoding="utf-8")
        navigator = (ROOT / ".evidence-rife-twine-r146-30to60" /
                     "navigate-twine-owned-replay.py").read_text(
                         encoding="utf-8")

        self.assertIn("system_services_healthy()", harness)
        self.assertIn("require_test_display_mode()", harness)
        self.assertIn("require_test_display_mode pre-launch", harness)
        self.assertIn("require_test_display_awake()", harness)
        self.assertIn("ensure_test_display_awake()", harness)
        self.assertIn("stabilize_usb_chooser_and_test_display post-usb-chooser", harness)
        self.assertIn("stabilize_usb_chooser_and_test_display twine-navigation-usb", harness)
        self.assertIn("THOR_TOP_120_RATE", harness)
        self.assertIn("120.00001", harness)
        self.assertIn('[[ "$QA_SESSION" =~ ^qa-[0-9a-f]{32}$ ]]', harness)
        self.assertLess(
            harness.index("RIFE_QA_SESSION must match"),
            harness.index("device wait-for-device"),
        )
        self.assertIn("REFRESH_RATE_GLOBALS_MUTATED=0", harness)
        self.assertIn(
            'if [ "$REFRESH_RATE_GLOBALS_MUTATED" = 1 ]; then', harness
        )
        self.assertIn(
            'if [ "$FORCE_TOP_MODE_60" = 1 ] || '
            '[ "$FORCE_TOP_MODE_120" = 1 ]; then\n'
            '    # With unset min/peak settings',
            harness,
        )
        pre_wake_policy = harness.split(
            'device shell settings put system screen_off_timeout 600000', 1
        )[1].split(
            'device shell settings put system screen_brightness 8', 1
        )[0]
        self.assertIn(
            'settings put system min_refresh_rate \\\n'
            '        "$THOR_TOP_120_RATE"',
            pre_wake_policy,
        )
        self.assertIn(
            'settings put system peak_refresh_rate \\\n'
            '        "$THOR_TOP_120_RATE"',
            pre_wake_policy,
        )
        self.assertNotIn("settings put system min_refresh_rate 120 >/dev/null", harness)
        self.assertNotIn('1080 1920 "$THOR_TOP_120_RATE"', harness)
        self.assertIn("ORIGINAL_USB_NOTICE_SETTING", harness)
        self.assertIn("notice_me_when_usb_connected 0", harness)
        self.assertIn("restore_vendor_usb_notice", harness)
        self.assertIn("vendor_usb_chooser_safe_geometry", harness)
        self.assertIn(r"frame=\[336,267\]\[1584,812\]", harness)
        self.assertIn("shell input tap 1450 755", harness)
        self.assertNotIn("shell input keyevent 4", harness)
        self.assertLess(
            harness.index("blacken_and_verify_oleds", harness.index("cleanup()")),
            harness.index("restore_top_display_mode", harness.index("cleanup()")),
        )
        for stage in (
            "engine-verification", "in-window-route", "twine-navigation",
            "pre-proof", "post-active-window",
        ):
            self.assertIn(f"require_test_display_mode {stage}", harness)
        preactivation = harness.split(
            "for second in $(seq 1 120); do", 1)[1].split(
                "if [ \"$activated\" != 1 ]", 1)[0]
        self.assertNotIn("require_test_display_mode", preactivation)
        self.assertNotIn("pidof com.thorium.preview", preactivation)
        active_window = harness.split(
            "for second in $(seq 1 60); do", 1)[1].split(
                "printf 'completionHostNs=%s", 1)[0]
        self.assertNotIn("require_test_display_mode", active_window)
        self.assertNotIn("pidof com.thorium.preview", active_window)
        for service_name in ("settings", "input", "activity", "window"):
            self.assertIn(service_name, harness)
            self.assertIn(f'"{service_name}"', navigator)
        self.assertIn("WATCHDOG KILLING SYSTEM PROCESS", harness)
        self.assertIn("Watchdog: *** GOODBYE", navigator)
        self.assertIn("DEAD_OBJECT", harness)
        self.assertIn("DEAD_OBJECT", navigator)
        self.assertIn("RIFE swapchain acquire interruption", harness)
        self.assertIn("External presentation transport interrupted", harness)
        self.assertEqual(2, harness.count("App-owned external timing failed closed"))
        self.assertEqual(
            1, harness.count("App-owned physical presentation failed closed")
        )
        failure_function = harness.split(
            "log_has_failure_from_line() {", 1
        )[1].split("\n}\n\nlog_has_preactivation_failure()", 1)[0]
        with tempfile.TemporaryDirectory() as temp_dir:
            live_log = Path(temp_dir) / "live-logcat.txt"
            live_log.write_text(
                "before activation\n"
                "still healthy\n"
                "App-owned physical presentation failed closed "
                "generator=1 result=UNAVAILABLE\n",
                encoding="utf-8",
            )
            probe = subprocess.run(
                [
                    "/bin/bash", "-c",
                    "set -euo pipefail\n"
                    f"EVIDENCE={json.dumps(temp_dir)}\n"
                    "log_has_failure_from_line() {"
                    f"{failure_function}\n"
                    "}\n"
                    "log_has_failure_from_line 2",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, probe.returncode, probe.stderr)
        self.assertNotIn("exec-out", navigator)
        self.assertNotIn("androidctl", navigator)
        self.assertIn('"screenCaptures": 0', navigator)
        self.assertIn("suppress-ambient-display emufusion true", harness)
        self.assertIn("blacken_and_verify_oleds()", harness)
        self.assertIn("cmd display set-brightness 0.0", harness)
        self.assertIn("settings put system screen_brightness 0", harness)
        self.assertIn("/sys/class/backlight/panel0-backlight/brightness", harness)
        self.assertIn("/sys/class/backlight/panel1-backlight/brightness", harness)
        self.assertIn(
            "/sys/class/backlight/panel0-backlight/actual_brightness", harness
        )
        self.assertIn(
            "/sys/class/backlight/panel1-backlight/actual_brightness", harness
        )
        self.assertIn(
            'if [ "$panel0_actual" = 0 ] && [ "$panel1_actual" = 0 ]',
            harness,
        )
        self.assertIn('echo "panel0_actual_backlight=', harness)
        self.assertIn('echo "panel1_actual_backlight=', harness)
        self.assertNotIn("shell input keyevent 223", harness)
        self.assertIn(r"mBrightness=0\.0", harness)

    def test_lock_allows_only_notice_bound_qualification_redistribution(self):
        STAGER.validate_lock(self.lock)
        self.assertFalse(self.lock["productIntegrationAllowed"])
        gate = self.lock["provenanceGate"]
        self.assertTrue(gate["redistributeModelInApk"])
        self.assertTrue(gate["qualificationApkRedistributionApproved"])
        self.assertFalse(gate["routeProductFramesToProvider"])

        for mutation in ("route", "model", "notice"):
            with self.subTest(mutation=mutation):
                damaged = copy.deepcopy(self.lock)
                if mutation == "route":
                    damaged["provenanceGate"]["routeProductFramesToProvider"] = True
                elif mutation == "model":
                    damaged["components"]["rifeV46Model"]["files"][1]["sha256"] = "0" * 64
                else:
                    damaged["components"]["ncnnAndroidBenchmark"]["license"]["sha256"] = "0" * 64
                with self.assertRaises(RuntimeError):
                    STAGER.validate_lock(damaged)

    def test_build_flag_is_default_off_verified_and_named_qualification(self):
        build = (ROOT / "unified-android/build.sh").read_text(encoding="utf-8")
        self.assertIn("INCLUDE_RIFE_FRAMEGEN=${LUCENT_INCLUDE_RIFE_FRAMEGEN:-0}", build)
        self.assertIn("LUCENT_INCLUDE_RIFE_FRAMEGEN must be 0 or 1", build)
        self.assertIn(":app:assembleRelease :app:assembleDebugAndroidTest", build)
        self.assertIn('RIFE_APP_APK="$RIFE_BENCHMARK_DIR/app/build/outputs/apk/release/app-release-unsigned.apk"', build)
        self.assertIn("RIFE_GRADLE=${RIFE_GRADLE:-/opt/homebrew/bin/gradle}", build)
        self.assertIn("build/upstream-prepared-v12/prepared-manifest.json", build)
        self.assertIn('--llvm-readelf "$RIFE_LLVM_READELF"', build)
        self.assertIn("verify_host_artifacts.py", build)
        self.assertIn("stage_rife_framegen_qualification.py", build)
        self.assertIn("lucent-$VERSION_NAME-rife-framegen-qualification.apk", build)
        self.assertIn("librife_benchmark.so) notice_heading=", build)
        self.assertLess(
            build.index("stage_rife_framegen_qualification.py"),
            build.index("UNDOCUMENTED_LIBS="),
        )
        self.assertIn("NativeRifeBridge.java", build)
        self.assertIn("ModelIntegrity.java", build)
        self.assertIn("RifeQualificationRuntime.java", build)
        self.assertIn("RifePresentationTransport.java", build)
        self.assertIn("RifeQualificationTransportFactory.java", build)
        factory = (ROOT / "unified-android/qualification-src/"
                   "com/thorium/preview/game/"
                   "RifeQualificationTransportFactory.java").read_text(
                       encoding="utf-8")
        self.assertIn("suggestedWidth, suggestedHeight,\n"
                      "                suggestedWidth, suggestedHeight);", factory)
        self.assertNotIn("private static final int ENDPOINT_WIDTH", factory)
        self.assertNotIn("private static final int ANALYSIS_WIDTH", factory)
        runtime = (ROOT / "unified-android/qualification-src/"
                   "com/thorium/preview/game/"
                   "RifeQualificationRuntime.java").read_text(encoding="utf-8")
        self.assertIn("ModelIntegrity.verify(modelDirectory)", runtime)
        self.assertIn("NativeRifeBridge.libraryBuildId()", runtime)
        self.assertIn("highDetailPresentedImageProofCompiled", runtime)
        self.assertIn("nonBlockingSubmissionSupported", runtime)
        bridge = (ROOT / "experiments/rife-ncnn-vulkan-android/android-benchmark/"
                  "app/src/main/java/com/emufusion/rifebenchmark/"
                  "NativeRifeBridge.java").read_text(encoding="utf-8")
        native = (ROOT / "experiments/rife-ncnn-vulkan-android/android-benchmark/"
                  "app/src/main/cpp/rife_benchmark_jni.cpp").read_text(encoding="utf-8")
        self.assertIn("pollPresentationTiming()", bridge)
        self.assertIn("takeCompletedPresentationGpuWorkNs()", bridge)
        self.assertIn("takeCompletedPresentationContentProof()", bridge)
        self.assertIn("actualPresentTimeNs", bridge)
        self.assertIn("nativePollPresentationTiming", native)
        self.assertIn(
            "nativeScheduleHardwareBufferRifePresentationRelease", native
        )
        self.assertIn("nativePollHardwareBufferRifePresentationRelease", native)
        self.assertIn("timed_release_worker_main", native)
        self.assertIn("pending_present_queued", native)
        self.assertIn("pending_release_gate_semaphore", native)
        self.assertIn("signal_pending_surface_present_locked", native)
        self.assertIn('"dedicatedReleaseQueue\\\":true', native)
        self.assertIn('"prequeuedPresentGate\\\":true', native)
        self.assertIn("Do not expose this finished image to FIFO yet", native)
        self.assertIn("nativeTakeCompletedPresentationGpuWorkNs", native)
        self.assertIn("nativeTakeCompletedPresentationContentProof", native)
        self.assertIn("kRifeContentProofShader", native)
        self.assertIn("kRifeHighDetailContentProofShader", native)
        self.assertIn('"highDetailPresentedImageProofCompiled\\\":true', native)
        self.assertIn("high_detail_content_proof_pipeline.get()", native)
        self.assertIn("proof_images[0] = proof_slot.image_mat", native)
        self.assertLess(
            native.index("high_detail_content_proof_pipeline.get()"),
            native.index("release_output.srcQueueFamilyIndex",
                         native.index("high_detail_content_proof_pipeline.get()")),
        )
        self.assertIn("kContentProofTileCount =", native)
        self.assertIn("kCurrentContentProofTileCount + kLookaheadContentProofTileCount", native)
        self.assertIn(
            "fnv_offset, fnv_offset, fnv_offset, fnv_offset, fnv_offset",
            native,
        )
        self.assertIn("if (checksums[3] != checksums[1]) return false", native)
        self.assertIn("pending_content_proof_sequence", native)
        self.assertIn("kLookaheadContentProofBytes", native)
        self.assertIn("VK_PIPELINE_STAGE_HOST_BIT", native)
        # Both the legacy combined job and the split private-preparation job
        # must decode their own retained proof buffer.  The split path no
        # longer aliases proof storage through SurfaceTransport's old pending
        # field, so bind this packaging check to the shared decoder and its
        # exact mapped allocation instead of the removed monolithic name.
        self.assertIn("decode_content_proof(", native)
        self.assertIn("content_proof_gpu.mapped_ptr()", native)
        self.assertIn("prepared.content_proof_gpu", native)
        self.assertNotIn("record_clone(content_proof_gpu", native)
        self.assertIn("consumed_gpu_work_count", native)
        self.assertIn("kMaximumRetainedGpuTimings = 1024", native)
        self.assertIn("kMaximumPendingPastTimings = 1024", native)
        self.assertIn("past_presentation_timing_count", native)
        self.assertIn("past_presentation_timings.pop_front()", native)
        self.assertIn("struct DirectPresentationLifecycle", native)
        self.assertIn("direct_presentation_lifecycles", native)
        self.assertIn("gate_signal_start_ns", native)
        self.assertIn("gate_signal_end_ns", native)
        self.assertIn(
            "direct presentation lifecycle did not match physical row", native
        )
        self.assertNotIn("past_presentation_timing_read_index", native)
        self.assertIn("never a fence wait", native)
        transport = (ROOT / "unified-android/qualification-src/"
                     "com/thorium/preview/game/RifePresentationTransport.java"
                     ).read_text(encoding="utf-8")
        self.assertIn("ImageReader.newInstance", transport)
        self.assertIn("USAGE_GPU_SAMPLED_IMAGE", transport)
        self.assertIn("FrameGenerationPresentationRequest", transport)
        self.assertIn("request.presentationTimestampNs()", transport)
        self.assertIn("request.driverDesiredPresentTimeNs()", transport)
        enqueue = transport.split(
            "@Override public EnqueueResult enqueue(", 1
        )[1].split("private void scheduleNativeRelease", 1)[0]
        native_desired = enqueue.split(
            "long nativeDesiredPresentTimeNs =", 1
        )[1].split("long nativeFrameTimelineVsyncId", 1)[0]
        self.assertIn("request.driverDesiredPresentTimeNs()", native_desired)
        self.assertNotIn("request.desiredPhysicalPresentTimeNs()", native_desired)
        native_enqueue = transport.split("int result =", 1)[1].split(
            "long enqueueWallNs", 1
        )[0]
        self.assertIn("nativeDesiredPresentTimeNs", native_enqueue)
        self.assertIn(
            "pending.nativeDesiredPresentTimeNs", transport
        )
        self.assertIn("request.hardCompletionDeadlineNs()", transport)
        self.assertIn("request.queueReleaseNotBeforeNs()", transport)
        self.assertIn(
            "scheduleHardwareBufferRifePresentationRelease(", transport
        )
        self.assertIn("pollHardwareBufferRifePresentationRelease()", transport)
        self.assertNotIn("owner.postDelayed(nativeReleaseCheck", transport)
        self.assertIn("kTimedReleaseSpinLeadNs = 5'000'000", native)
        self.assertNotIn("LockSupport.parkNanos", transport)
        self.assertIn("native timed WSI release crossed its hard cutoff", native)
        release_worker = native.split(
            "void* timed_release_worker_main", 1
        )[1].split("bool start_timed_release_worker", 1)[0]
        release_tail = release_worker.split(
            "state_lock.unlock();", 1
        )[1].split("state_lock.lock();", 1)[0]
        self.assertIn("signal_pending_surface_present_locked(", release_tail)
        self.assertNotIn("context_lock(context->mutex)", release_tail)
        self.assertIn(
            "only this\n        // worker mutates the prequeued gate/lifecycle",
            release_tail,
        )
        self.assertIn("request.sessionEpoch()", transport)
        self.assertIn("request.presentationEpoch()", transport)
        rate_gate = transport.split(
            "@Override public boolean supportsRatePath", 1
        )[1].split("@Override public boolean supportsEndpointOnlyPresentation", 1)[0]
        self.assertIn("sourceFps == 20 && outputFps == 40", rate_gate)
        self.assertIn("sourceFps == 30 && outputFps == 60", rate_gate)
        self.assertIn("sourceFps == 60 && outputFps == 120", rate_gate)
        for unsupported in (
            "sourceFps == 40 && outputFps == 60",
            "sourceFps == 50 && outputFps == 60",
        ):
            self.assertNotIn(unsupported, rate_gate)
        self.assertIn("supportsEndpointOnlyPresentation()", transport)
        self.assertIn("consecutiveCachedEndpointCount", transport)
        self.assertIn("endpointImportCacheWarm", transport)
        self.assertIn(
            "privateGenerationPipelineWarm && endpointImportCacheWarm",
            transport,
        )
        self.assertIn("RIFE endpoint import cache proven warm", transport)
        self.assertIn("if (active && !generatedRatePathActive)", transport)
        self.assertIn("if (generatedRatePathActive &&", transport)
        self.assertIn("setGeneratedRatePathActive(boolean active)", transport)
        self.assertIn("hasPreparedLookahead(long rightSequence)", transport)
        self.assertIn('backendLabel() { return "RIFE"; }', transport)
        self.assertIn("request.outputWidth() != width", transport)
        self.assertIn("pollPresentationTiming()", transport)
        self.assertIn("RIFE direct presentation lifecycle", transport)
        self.assertIn("timing.directGateSignalStartNs", transport)
        self.assertIn("actualBeforeGate", transport)
        self.assertIn("takeCompletedPresentationGpuWorkNs()", transport)
        self.assertIn("takeCompletedPresentationContentProof()", transport)
        readiness = transport.split(
            "@Override public GenerationReadiness generationReadiness(", 1
        )[1].split(
            "@Override public boolean hasPreparedLookahead", 1
        )[0]
        self.assertIn("current.request.leftSequence() == leftSequence", readiness)
        self.assertIn("current.request.rightSequence() == rightSequence", readiness)
        self.assertIn("pollPreparedPresentation();", readiness)
        self.assertLess(
            readiness.index("current.request.leftSequence() == leftSequence"),
            readiness.index("pollPreparedPresentation();"),
        )
        self.assertLess(
            readiness.index("pollPreparedPresentation();"),
            readiness.index("pairReadiness.get(rightSequence)"),
        )
        self.assertIn("nativeProof.sequence != nativeInFlight.proofSequence", transport)
        self.assertIn("FrameGenerationPreparationRequest", transport)
        self.assertIn("jobBridge.prepareHardwareBufferRifeOutput(", transport)
        self.assertIn("current.jobBridge.pollPreparedHardwareBufferRifeOutput(", transport)
        self.assertIn("private boolean privateGenerationPipelineWarm", transport)
        self.assertIn(
            "@Override public boolean privateGenerationPipelineWarm()",
            transport,
        )
        self.assertIn(
            "@Override public boolean visibleSubmissionReady()",
            transport,
        )
        submission_ready = transport.split(
            "@Override public boolean visibleSubmissionReady()", 1
        )[1].split("private void validatePreparationIdentity", 1)[0]
        self.assertIn("requireOwner();", submission_ready)
        self.assertIn("requireOpen();", submission_ready)
        self.assertIn(
            "return appOwnedPresentation ||\n"
            "                (startupSurfaceProbeComplete &&\n"
            "                        !nativePending && !preparationInFlight);",
            submission_ready,
        )
        private_poll = transport.split(
            "private void pollPreparedPresentation()", 1
        )[1].split("private long takeProofSequence()", 1)[0]
        self.assertIn("privateGenerationPipelineWarm = true;", private_poll)
        self.assertLess(
            private_poll.index("current.jobBridge.pollPreparedHardwareBufferRifeOutput("),
            private_poll.index("privateGenerationPipelineWarm = true;"),
        )
        self.assertIn("current.jobBridge.discardPreparedHardwareBufferRifeOutput(", transport)
        self.assertIn("bridge.enqueuePreparedHardwareBufferRifePresentation(", transport)
        self.assertIn("LinkedHashMap<Long, GenerationReadiness> pairReadiness", transport)
        self.assertIn("RIFE generated request lacks a completed safe-pair assessment", transport)
        self.assertIn("if (generatedRatePathActive &&", transport)
        self.assertIn("!pairReadiness.containsKey(lookaheadSequence)", transport)
        self.assertIn(
            "candidate != null && candidate.prepared && !candidate.preparing",
            transport,
        )
        self.assertIn("RIFE private look-ahead proof pipeline started", transport)
        self.assertIn("RIFE private look-ahead proof completed", transport)
        self.assertNotIn(
            "if (request.isGenerated() &&\n"
            "                !pairReadiness.containsKey(lookaheadSequence))",
            transport,
        )
        self.assertIn("nativeProof.lookaheadAvailable != expectedLookahead", transport)
        self.assertIn("RIFE look-ahead proof identity mismatch", transport)
        self.assertIn("recordPairAssessment(", transport)
        self.assertIn("nativeInFlight.timelineEpoch == timelineEpoch", transport)
        self.assertIn("enqueueWallNs", transport)
        self.assertIn("gpuWorkNs", transport)
        self.assertIn("findSubmitted(timing.presentId)", transport)
        self.assertNotIn(
            "if (!surfaceControlPresentation) {\n"
            "                for (SubmittedPresentation candidate : submitted)",
            transport,
        )
        self.assertIn(
            "OnComplete callback that explicitly omitted its present fence",
            transport,
        )
        self.assertNotIn(
            "surfaceControlPresentation ?\n"
            "                    pending.request.desiredPhysicalPresentTimeNs()",
            transport,
        )
        self.assertIn("if (candidate.timing == null)", transport)
        self.assertIn("candidate.physicallyDropped = true", transport)
        self.assertNotIn(
            '"RIFE physical presentation ordering mismatch"', transport
        )
        self.assertIn("actual delivered FPS", transport)
        self.assertIn("resetEndpointTimeline", transport)
        self.assertIn("nativeInFlight", transport)
        self.assertIn("MAX_PENDING_PRESENTATIONS", transport)
        self.assertIn("expectedTimestampNs=", transport)
        self.assertIn("actualTimestampNs=", transport)
        self.assertIn("expectedDepth=", transport)
        self.assertIn("RIFE endpoint carrier discontinuity", transport)
        self.assertIn("candidate.timestampNs == timestampNs", transport)
        self.assertIn("endpointDiscontinuities += skipped", transport)
        self.assertIn("consumeEndpointDiscontinuities()", transport)
        self.assertIn("EmuFusion-RIFE-prepare", transport)
        self.assertIn("bridge.prepareHardwareBufferEndpoint", transport)
        self.assertIn("bridge.isHardwareBufferEndpointPrepared", transport)
        self.assertIn("if (preparationInFlight) return", transport)
        self.assertIn("left.prepared && right.prepared", transport)
        self.assertIn("nativePending || preparationInFlight", transport)
        self.assertIn("hasPreparedPresentationWindow()", transport)
        preparation_scheduler = transport.split(
            "private void scheduleEndpointPreparation()", 1
        )[1].split("private boolean hasPreparedPresentationWindow()", 1)[0]
        self.assertNotIn("!submitted.isEmpty()", preparation_scheduler)
        self.assertIn("hasPreparedPresentationWindow()) return", preparation_scheduler)
        preparation_window = transport.split(
            "private boolean hasPreparedPresentationWindow()", 1
        )[1].split("private void finishEndpointPreparation", 1)[0]
        self.assertIn("generatedRatePathActive ? 3 : 2", preparation_window)
        self.assertIn("consecutivePrepared >= requiredPrepared", preparation_window)
        self.assertIn(
            "endpoint.sequence == previousSequence + 1L",
            transport,
        )
        self.assertLess(
            transport.index("bridge.prepareHardwareBufferEndpoint"),
            transport.index("private void finishEndpointPreparation"),
        )
        self.assertNotIn("await(", transport)
        self.assertIn("prepareHardwareBufferEndpoint(", bridge)
        self.assertIn("nativePrepareHardwareBufferEndpoint(", bridge)
        self.assertIn("nativeIsHardwareBufferEndpointPrepared(", bridge)
        self.assertIn(
            "nativePrepareHardwareBufferEndpoint", native
        )
        query = native.split(
            "nativeIsHardwareBufferEndpointPrepared", 1
        )[1].split("nativePrepareHardwareBufferEndpoint", 1)[0]
        self.assertIn("context->ahb_endpoint_cache", query)
        self.assertNotIn("cached_hardware_buffer_endpoint(", query)
        self.assertNotIn("create(", query)
        preparation = native.split(
            "nativePrepareHardwareBufferEndpoint", 1
        )[1].split("nativeProbeHardwareBuffer", 1)[0]
        self.assertIn("cached_hardware_buffer_endpoint(", preparation)
        self.assertIn("ensure_hardware_buffer_pack_pipeline(context)", preparation)
        self.assertNotIn("submit", preparation)
        self.assertNotIn("wait", preparation)
        self.assertIn("selfTestPassed=false", (ROOT /
            "unified-android/src/com/thorium/preview/game/FrameGenerationSettings.java"
        ).read_text(encoding="utf-8"))
        cmake = (ROOT / "experiments/rife-ncnn-vulkan-android/android-benchmark/"
                 "app/src/main/cpp/CMakeLists.txt").read_text(encoding="utf-8")
        self.assertIn('set(NCNN_OPENMP OFF CACHE BOOL "" FORCE)', cmake)
        self.assertLess(
            cmake.index('set(NCNN_OPENMP OFF CACHE BOOL "" FORCE)'),
            cmake.index('add_subdirectory("${NCNN_SOURCE_DIR}"'),
        )
        self.assertIn("max-page-size=16384", cmake)
        self.assertIn("common-page-size=16384", cmake)

    def test_live_transport_owns_output_and_counts_only_physical_rows(self):
        generator = (ROOT / "unified-android/src/com/thorium/preview/game/"
                     "DisplayFrameGenerator.java").read_text(encoding="utf-8")
        settings = (ROOT / "unified-android/src/com/thorium/preview/game/"
                    "FrameGenerationSettings.java").read_text(encoding="utf-8")
        surface = (ROOT / "unified-android/src/com/thorium/preview/game/"
                   "GameSurfaceView.java").read_text(encoding="utf-8")
        interface = (ROOT / "unified-android/src/com/thorium/preview/game/"
                     "ExternalFrameGenerationTransport.java").read_text(
                         encoding="utf-8")

        self.assertIn('"emufusion_framegen_rife_qualification", 0) != 1', settings)
        self.assertIn('BUILT_IN_ALPHA("built-in-alpha")', settings)
        self.assertIn("launchMode != Mode.LSFG", settings)
        self.assertIn("displayId != Display.DEFAULT_DISPLAY", settings)
        self.assertIn("createExternalQualification", surface)
        self.assertIn("qualification.label", surface)
        self.assertIn("product backend assessment remains unqualified", surface)
        self.assertIn("EGL14.eglCreatePbufferSurface", generator)
        self.assertIn("externalTransport.endpointSurface()", generator)
        self.assertIn("publishExternalEndpoint", generator)
        self.assertIn("eglPresentationTimeANDROID(\n                            eglDisplay, eglEndpointSurface, timestampNs)",
                      generator)
        self.assertIn("presentExternalBuffered", generator)
        self.assertIn("consumeExternalEndpointDiscontinuities();", generator)
        self.assertIn("consumeExternalPresentationDiscontinuities();", generator)
        self.assertIn("frameRate.resetPresentation();", generator.split(
            "private void consumeExternalEndpointDiscontinuities()", 1
        )[1].split("private ", 1)[0])
        self.assertIn("resetEndpointTimelineForSchedulerEpoch();", generator.split(
            "private void consumeExternalEndpointDiscontinuities()", 1
        )[1].split("private ", 1)[0])
        self.assertIn("row.actualPresentTimeNs", generator)
        self.assertIn("externalPresentationEvidence.record(commit", generator)
        self.assertIn("externalGeneratedContentEvidence.record(commit", generator)
        self.assertIn("externalPhysicalCadence.reset()", generator)
        self.assertIn("externalPresentationEvidence.timingQualified()", generator)
        self.assertIn("externalDeadlineMisses=", generator)
        self.assertIn("externalDesiredSlotMisses=", generator)
        self.assertIn("externalCombinedP95Ns=", generator)
        self.assertIn("externalTimingScans=", generator)
        self.assertIn("externalTimingPipelineScans=", generator)
        self.assertIn("externalTimingRefreshNs=", generator)
        self.assertIn("externalContentNumericPassed=", generator)
        self.assertIn("External rate-path transition", generator)
        self.assertIn("externalLockedSourceFps=", generator)
        self.assertIn("externalPresentationSourceHz=", generator)
        self.assertIn("externalCandidateOutput=", generator)
        self.assertIn("externalCandidateSource=", generator)
        self.assertIn("externalCandidateScans=", generator)
        self.assertIn("externalCandidateSupported=", generator)
        self.assertIn("externalRatePathActive=", generator)
        self.assertIn("externalGenerationAvailable=", generator)
        self.assertIn("externalUnsafePairs=", generator)
        self.assertIn("private boolean externalPresentationFailed;", generator)
        self.assertIn(
            "if (closed.get() || externalPresentationFailed) return;", generator
        )
        self.assertIn(
            '? "External presentation session failed closed"',
            generator,
        )
        failure_handler = generator.split(
            "private void failRuntimePresentation(", 1
        )[1].split("private void consumeExternalEndpointDiscontinuities()", 1)[0]
        self.assertIn("externalPresentationFailed = true;", failure_handler)
        self.assertIn("Log.e(TAG, diagnostic, failure);", failure_handler)
        self.assertIn("runtimeFailure.report(", failure_handler)
        self.assertIn("if (externalPresentationFailed) {", generator)
        self.assertIn("externalContentManualPassed=", generator)
        self.assertIn("externalPathManuallyCertified()", generator)
        poll = generator.split("private void pollPhysicalPresentations()", 1)[1]
        self.assertLess(poll.index("row.actualPresentTimeNs"),
                        poll.index("++presents"))
        external_present = generator.split(
            "private void presentExternalBuffered(", 1
        )[1].split("private void reportStats()", 1)[0]
        self.assertNotIn("++presents", external_present)
        self.assertNotIn("++generatedPresents", external_present)
        self.assertIn("interface Factory", interface)
        self.assertIn("enum GenerationReadiness { PENDING, READY, UNSAFE }", interface)
        self.assertIn("GenerationReadiness generationReadiness(", interface)
        default_readiness = interface.split(
            "default GenerationReadiness generationReadiness(", 1
        )[1].split("void releaseBefore", 1)[0]
        self.assertIn("return GenerationReadiness.PENDING", default_readiness)
        self.assertNotIn("GenerationReadiness.READY", default_readiness)
        self.assertIn("void resetEndpointTimeline()", interface)
        self.assertIn(
            "readiness ==\n                        ExternalFrameGenerationTransport.GenerationReadiness.READY",
            generator,
        )

    def test_rife_not_ready_is_reasoned_and_never_retried(self):
        transport = (ROOT /
            "unified-android/qualification-src/com/thorium/preview/game/"
            "RifePresentationTransport.java").read_text(encoding="utf-8")
        generator = (ROOT /
            "unified-android/src/com/thorium/preview/game/"
            "DisplayFrameGenerator.java").read_text(encoding="utf-8")
        enqueue = transport.split(
            "@Override public EnqueueResult enqueue(", 1
        )[1].split("@Override public", 1)[0]
        self.assertIn("reason=compositor-reserve", enqueue)
        self.assertIn("THOR_COMPOSITOR_SUBMISSION_RESERVE_NS", enqueue)
        self.assertGreaterEqual(
            enqueue.count("request.compositorFrameTimelineDeadlineNs()"), 2
        )
        self.assertGreaterEqual(
            enqueue.count(
                "request.compositorTokenExpectedPresentationTimeNs()"
            ),
            1,
        )
        self.assertIn('"compositor-reserve-post-work"', enqueue)
        self.assertIn("release-window-expired-post-work", enqueue)
        self.assertIn(
            "if (!physicalPresentationSkipped && !scheduleNativeRelease(request))",
            enqueue,
        )
        self.assertLess(
            enqueue.index("scheduleNativeRelease(request)"),
            enqueue.index("submitted.addLast(pending)"),
        )
        self.assertIn("boolean physicalPresentationSkipped = result == 2", enqueue)
        self.assertIn(
            "if (!physicalPresentationSkipped) submitted.addLast(pending)",
            enqueue,
        )
        self.assertLess(
            enqueue.index("nativeInFlight = pending"),
            enqueue.index("return EnqueueResult.NOT_READY", enqueue.index(
                '"compositor-reserve-post-work"'
            )),
        )
        self.assertIn("reason=transport-busy", enqueue)
        self.assertIn("reason=prior-release-not-before", enqueue)
        self.assertIn("priorOperationReadyNs", enqueue)
        self.assertNotIn("request.isGenerated() && nativePending", enqueue)
        self.assertIn("reason=private-output-pending", enqueue)
        self.assertIn(
            "nativePending && nativeReleaseScheduled && pollNativeRelease()",
            enqueue,
        )
        self.assertLess(
            enqueue.index("pollNativePresentationCompletion();"),
            enqueue.index("if (nativePending || preparationInFlight)"),
        )
        self.assertIn("return EnqueueResult.DEFERRED", enqueue)
        self.assertLess(
            enqueue.index("return EnqueueResult.DEFERRED"),
            enqueue.index("reason=transport-busy"),
        )
        self.assertIn("reason=retained-pair-missing", enqueue)
        self.assertIn('"surface-control-output" : "swapchain-acquire"', enqueue)
        self.assertIn("recordWsiAcquireNotReady()", enqueue)
        self.assertIn("resetWsiAcquireStarvation()", enqueue)
        starvation = transport.split(
            "private void recordWsiAcquireNotReady()", 1
        )[1].split("private void resetWsiAcquireStarvation()", 1)[0]
        self.assertIn("WSI_ACQUIRE_STARVATION_MIN_ATTEMPTS", starvation)
        self.assertIn("WSI_ACQUIRE_STARVATION_MIN_NS", starvation)
        self.assertIn("refreshDurationNs * 4L", starvation)
        self.assertIn('"RIFE swapchain acquire interruption"', starvation)
        self.assertIn("++presentationDiscontinuities", starvation)
        self.assertNotIn("throw new IllegalStateException", starvation)
        self.assertIn("wsiAcquireStarvationActive", enqueue)
        self.assertIn("STARTUP_SURFACE_DRAIN_SLOW_NS = 2_000_000_000L", transport)
        self.assertIn("STARTUP_SURFACE_DRAIN_TIMEOUT_NS = 8_000_000_000L", transport)
        self.assertIn("RIFE startup Surface drain delayed", transport)
        self.assertLess(
            transport.index("RIFE startup Surface drain delayed"),
            transport.index("RIFE startup Surface did not recycle one swapchain image"),
        )
        self.assertIn("reason=swapchain-recovery-cooldown", enqueue)
        recovery = transport.split(
            "private void resetWsiAcquireStarvation()", 1
        )[1].split("private boolean scheduleNativeRelease", 1)[0]
        self.assertIn('"RIFE swapchain acquire recovered"', recovery)
        self.assertIn("nextWsiAcquireProbeNs = 0L", recovery)
        discontinuity = generator.split(
            "private void consumeExternalPresentationDiscontinuities()", 1
        )[1].split("@Override public void close()", 1)[0]
        self.assertIn("markExternalTimingRejected();", discontinuity)
        rejection = generator.split("private void markExternalTimingRejected()", 1)[1].split("/**", 1)[0]
        self.assertIn("externalTimingRejected = true;", rejection)
        self.assertIn("externalTimingRejectedAtNs = System.nanoTime();", rejection)
        self.assertIn("externalRatePathActive = false", discontinuity)
        self.assertIn("transport.setGeneratedRatePathActive(false)", discontinuity)
        self.assertIn("frameRate.setGenerationAvailable(false)", discontinuity)
        self.assertIn("frameRate.resetPresentation()", discontinuity)
        self.assertIn("resetEndpointTimelineForSchedulerEpoch()", discontinuity)
        self.assertEqual(
            enqueue.count("bridge.enqueueHardwareBufferRifePresentation("), 1
        )

    def test_rife_endpoint_hardware_buffer_wrappers_are_closed_explicitly(self):
        transport = (ROOT /
            "unified-android/qualification-src/com/thorium/preview/game/"
            "RifePresentationTransport.java").read_text(encoding="utf-8")
        listener = transport.split(
            "@Override public void onImageAvailable(ImageReader source)", 1
        )[1].split("@Override public boolean hasAdjacentPair", 1)[0]
        preparation = transport.split(
            "private void scheduleEndpointPreparation()", 1
        )[1].split("private boolean hasPreparedPresentationWindow", 1)[0]
        self.assertEqual(listener.count("image.getHardwareBuffer()"), 1)
        self.assertIn("if (buffer != null) buffer.close();", listener)
        self.assertEqual(
            preparation.count("selected.image.getHardwareBuffer()"), 1
        )
        self.assertIn(
            "if (!handedToWorker) selectedBuffer.close();", preparation
        )
        self.assertIn("buffer.close();", preparation)

        bridge = (ROOT /
            "experiments/rife-ncnn-vulkan-android/android-benchmark/app/src/"
            "main/java/com/emufusion/rifebenchmark/NativeRifeBridge.java"
        ).read_text(encoding="utf-8")
        enqueue = bridge.split(
            "public int enqueueHardwareBufferRifePresentation(\n"
            "            Image previous,", 1
        )[1].split("public int prepareHardwareBufferRifeOutput", 1)[0]
        prepare = bridge.split(
            "public int prepareHardwareBufferRifeOutput", 1
        )[1].split("public PreparedOutput pollPrepared", 1)[0]
        for method in (enqueue, prepare):
            self.assertEqual(method.count("previous.getHardwareBuffer()"), 1)
            self.assertEqual(method.count("current.getHardwareBuffer()"), 1)
            self.assertIn("if (lookaheadBuffer != null) lookaheadBuffer.close();", method)
            self.assertIn("if (currentBuffer != null) currentBuffer.close();", method)
            self.assertIn("if (previousBuffer != null) previousBuffer.close();", method)

    def test_notices_and_source_map_name_every_payload_component(self):
        notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        section = notices.split(
            "## RIFE v4.6 frame-generation qualification payload", 1
        )[1].split("\n## ", 1)[0]
        for value in (
            "Practical-RIFE", "rife-ncnn-vulkan", "ncnn", "glslang",
            "MIT License", "BSD-3-Clause", "qualification-manifest.json",
            "productIntegrationAllowed", "routeProductFramesToProvider",
        ):
            self.assertIn(value, section)
        licensing = (ROOT / "LICENSING.md").read_text(encoding="utf-8")
        source_offer = (ROOT / "SOURCE_OFFER.md").read_text(encoding="utf-8")
        self.assertIn("RIFE frame-generation qualification APK", licensing)
        self.assertIn("stage_rife_framegen_qualification.py", source_offer)

    def test_current_host_verified_artifact_stages_exact_payload_when_present(self):
        benchmark = ROOT / "experiments/rife-ncnn-vulkan-android/android-benchmark"
        app_apk = benchmark / "app/build/outputs/apk/release/app-release-unsigned.apk"
        records = [
            ROOT / "unified-android/build/rife-framegen-host-artifacts.json",
            ROOT / "experiments/rife-ncnn-vulkan-android/evidence/"
                   "ahardwarebuffer-surface-2026-08-24/host-artifacts.json",
        ]
        record = next((candidate for candidate in records
                       if candidate.is_file() and
                       json.loads(candidate.read_text(encoding="utf-8"))
                           .get("appApk", {}).get("sha256") == STAGER.sha256(app_apk) and
                       json.loads(candidate.read_text(encoding="utf-8"))
                           .get("nativeLibrary", {}).get("buildId")),
                      None)
        cache = benchmark / "build/upstream-cache"
        required = [
            app_apk,
            cache / "source/rife-ncnn-vulkan/models/rife-v4.6/flownet.param",
            cache / "source/rife-ncnn-vulkan/models/rife-v4.6/flownet.bin",
        ]
        if record is None or not all(path.is_file() for path in required):
            self.skipTest("matching locked local RIFE build/cache is absent")
        with tempfile.TemporaryDirectory() as directory:
            args = type("Args", (), {
                "lock": self.lock_path,
                "cache_dir": cache,
                "app_apk": app_apk,
                "host_record": record,
                "decoded_apk": Path(directory),
            })()
            manifest = STAGER.stage(args)
            self.assertFalse(manifest["productIntegrationAllowed"])
            self.assertFalse(manifest["routeProductFramesToProvider"])
            self.assertEqual(STAGER.EXPECTED_MODEL_IDENTITIES, {
                name: (entry["bytes"], entry["sha256"])
                for name, entry in manifest["models"].items()
            })
            native = Path(directory) / STAGER.NATIVE_ENTRY
            self.assertEqual(
                manifest["nativeLibrary"]["sha256"], STAGER.sha256(native))
            emitted = Path(directory) / (
                "assets/framegen/rife-v4.6/qualification-manifest.json")
            self.assertEqual(manifest, json.loads(emitted.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
