from pathlib import Path
import hashlib
import importlib.util
import json
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


def _load_stager():
    path = ROOT / "unified-android/tools/stage_lsfg_private_qualification.py"
    spec = importlib.util.spec_from_file_location("lsfg_private_stager", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class LsfgQualificationPackagingTest(unittest.TestCase):
    def test_app_build_disables_cached_pixel_probe_flag(self):
        build = (ROOT / "unified-android/build.sh").read_text()
        self.assertIn("-DEMUFUSION_LSFG_PIXEL_PROBE=OFF", build)

    def test_private_stager_renames_exact_shader_set_without_copying_dll(self):
        stager = _load_stager()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dll = root / "Lossless.dll"
            dll.write_bytes(b"owned-test-dll")
            shaders = root / "extracted"
            shaders.mkdir()
            shader_bytes = b"\x03\x02\x23\x07" + bytes(16)
            for resource in range(255, 303):
                (shaders / f"{resource}.spv").write_bytes(shader_bytes)
            output = root / "private-payload"
            manifest_path = stager.stage_private_payload(
                dll,
                shaders,
                output,
                expected_dll_sha256=hashlib.sha256(dll.read_bytes()).hexdigest(),
            )

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(48, len(manifest["shaders"]))
            self.assertEqual("353.spv", manifest["shaders"][0]["name"])
            self.assertEqual("400.spv", manifest["shaders"][-1]["name"])
            self.assertFalse(manifest["dllPackaged"])
            self.assertFalse(manifest["dllExecuted"])
            self.assertFalse((output / "Lossless.dll").exists())
            self.assertEqual(
                {f"{resource}.spv" for resource in range(353, 401)},
                {path.name for path in (output / "shaders").iterdir()},
            )

    def test_private_stager_rejects_incomplete_shader_set(self):
        stager = _load_stager()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dll = root / "Lossless.dll"
            dll.write_bytes(b"owned-test-dll")
            shaders = root / "extracted"
            shaders.mkdir()
            shader_bytes = b"\x03\x02\x23\x07" + bytes(16)
            for resource in range(255, 302):
                (shaders / f"{resource}.spv").write_bytes(shader_bytes)
            with self.assertRaisesRegex(stager.StageError, "shader set mismatch"):
                stager.stage_private_payload(
                    dll,
                    shaders,
                    root / "private-payload",
                    expected_dll_sha256=hashlib.sha256(dll.read_bytes()).hexdigest(),
                )

    def test_internal_arm_is_top_only_explicitly_selected_and_reflected(self):
        settings = (ROOT / "unified-android/src/com/thorium/preview/game/"
                    "FrameGenerationSettings.java").read_text(encoding="utf-8")
        loader = (ROOT / "unified-android/src/com/thorium/preview/game/"
                  "ExternalFrameGenerationTransportLoader.java").read_text(
                      encoding="utf-8")

        self.assertIn('LSFG("lsfg")', settings)
        self.assertIn("launchMode != Mode.LSFG", settings)
        self.assertIn("displayId != Display.DEFAULT_DISPLAY", settings)
        self.assertNotIn("emufusion_framegen_lsfg_qualification", settings)
        # RIFE's explicit Alpha-only qualification switch cannot activate LSFG
        # or override Off. Its existence is not an LSFG routing regression.
        rife_flag = settings.index("emufusion_framegen_rife_qualification")
        self.assertLess(settings.index("launchMode == Mode.OFF"), rife_flag)
        self.assertLess(settings.index("if (launchMode == Mode.BUILT_IN_ALPHA)"), rife_flag)
        self.assertLess(rife_flag, settings.index("if (launchMode != Mode.LSFG)"))
        self.assertIn('"LSFG private beta"', settings)
        self.assertIn("ExternalFrameGenerationTransportLoader.lsfgQualification", settings)
        self.assertIn("FrameGenerationBackendPolicy.Backend.LSFG", settings)
        self.assertIn(
            '"com.thorium.preview.game.LsfgQualificationTransportFactory"', loader)
        self.assertIn("catch (Throwable absentOrRejected)", loader)

    def test_game_surface_uses_one_generic_qualification_boundary(self):
        surface = (ROOT / "unified-android/src/com/thorium/preview/game/"
                   "GameSurfaceView.java").read_text(encoding="utf-8")
        factory = (ROOT / "unified-android/src/com/thorium/preview/game/"
                   "FrameGenerationRendererFactory.java").read_text(
                       encoding="utf-8")

        self.assertIn("FrameGenerationSettings.qualificationTransport", surface)
        self.assertIn("activeBackend = qualification.backend", surface)
        self.assertIn("createExternalQualification", surface)
        self.assertIn("product backend assessment remains unqualified", surface)
        self.assertIn("static FrameGenerationRenderer createExternalQualification", factory)

    def test_default_off_build_has_conditional_source_gate_without_private_payload(self):
        build = (ROOT / "unified-android/build.sh").read_text(encoding="utf-8")
        qualification = ROOT / "unified-android/qualification-src/com/thorium/preview/game"

        self.assertIn("INCLUDE_LSFG_FRAMEGEN=${LUCENT_INCLUDE_LSFG_FRAMEGEN:-0}", build)
        self.assertIn("LUCENT_INCLUDE_LSFG_FRAMEGEN must be 0 or 1", build)
        self.assertIn("verify_patched_checkout.py", build)
        self.assertIn("verify_nonblocking_patch.py", build)
        self.assertIn("verify_owned_wsi_setup_source.py", build)
        self.assertIn("liblucent_lsfg_qualification.so", build)
        self.assertIn("lsfg-framegen-qualification.apk", build)
        self.assertIn("Lossless.dll and all", build)
        self.assertIn("LSFG is in-process", build)
        lsfg_notice = build.index(
            "liblucent_lsfg_qualification.so) notice_heading=")
        own_library_skip = build.index("liblucent_*|libpegasus-fe_*) continue")
        self.assertLess(lsfg_notice, own_library_skip)
        self.assertTrue((qualification / "LsfgQualificationTransportFactory.java").exists())
        self.assertTrue((qualification / "LsfgPresentationTransport.java").exists())
        self.assertTrue(
            (qualification / "LsfgQualificationSelfTestActivity.java").exists())
        self.assertIn("LsfgQualificationTransportFactory.java", build)
        self.assertIn("LsfgPresentationTransport.java", build)
        self.assertIn("LsfgQualificationSelfTestActivity.java", build)
        self.assertIn(
            'android:name="com.thorium.preview.game.'
            'LsfgQualificationSelfTestActivity"', build)
        self.assertIn('android:debuggable="true"', build)
        self.assertIn('if [ "$INCLUDE_LSFG_FRAMEGEN" = 1 ]; then', build)

    def test_internal_plus_build_has_distinct_label_icon_and_requires_lsfg(self):
        build = (ROOT / "unified-android/build.sh").read_text(encoding="utf-8")
        plus_icon = ROOT / "unified-android/res/drawable/lucent_plus_icon.png"

        self.assertTrue(plus_icon.is_file())
        self.assertIn("LUCENT_INTERNAL_LSFG_PLUS", build)
        self.assertIn("LUCENT_INCLUDE_LSFG_FRAMEGEN=1", build)
        self.assertIn('android:label="EmuFusion+"', build)
        self.assertIn("lucent_plus_icon.png", build)
        self.assertIn("emufusion-plus-lsfg-internal.apk", build)

    def test_self_test_activity_is_black_bounded_and_gameplay_free(self):
        source = (ROOT / "unified-android/qualification-src/com/thorium/preview/game/"
                  "LsfgQualificationSelfTestActivity.java").read_text(
                      encoding="utf-8")

        self.assertIn("attributes.screenBrightness = 0.0f", source)
        self.assertIn("setBackgroundColor(Color.BLACK)", source)
        self.assertIn("LsfgQualificationRuntime.open(this)", source)
        self.assertIn("NativeLsfgBridge.open(surface", source)
        self.assertIn("new Thread(", source)
        self.assertIn('"EmuFusion-LSFG-SelfTest"', source)
        self.assertIn("private synchronized void closeNative()", source)
        self.assertIn('Log.i(TAG, "RESULT PASS capabilities="', source)
        self.assertIn('Log.e(TAG, "RESULT FAIL capabilities="', source)
        self.assertIn("finishAndRemoveTask", source)
        self.assertNotIn("GameLaunch", source)
        self.assertNotIn("Rom", source)

    def test_conditional_transport_is_fixed_midpoint_and_private_asset_only(self):
        qualification = ROOT / "unified-android/qualification-src/com/thorium/preview/game"
        runtime = (qualification / "LsfgQualificationRuntime.java").read_text(
            encoding="utf-8")
        transport = (qualification / "LsfgPresentationTransport.java").read_text(
            encoding="utf-8")
        bridge = (qualification / "NativeLsfgBridge.java").read_text(
            encoding="utf-8")
        native = (ROOT / "unified-android/lsfg-qualification-native/"
                  "lsfg_qualification_jni.cpp").read_text(encoding="utf-8")
        owned = (ROOT / "unified-android/lsfg-qualification-native/"
                 "owned_vulkan_host.cpp").read_text(encoding="utf-8")
        cmake = (ROOT / "unified-android/lsfg-qualification-native/"
                 "CMakeLists.txt").read_text(encoding="utf-8")

        self.assertIn('getDir("lsfg-private-qualification"', runtime)
        self.assertIn('new File(root, "Lossless.dll").exists()', runtime)
        self.assertIn('manifest.getBoolean("dllPackaged")', runtime)
        self.assertIn('manifest.getBoolean("dllExecuted")', runtime)
        self.assertIn('manifest.getInt("generationCount") != 1', runtime)
        self.assertIn('manifest.getDouble("fixedPhase")', runtime)
        self.assertIn("NATIVE_BUILD_ID.equals(buildId)", runtime)
        self.assertIn("files.length() != SHADER_COUNT", runtime)
        self.assertIn("isExactMidpoint(request)", transport)
        self.assertIn("supportsEndpointOnlyPresentation()", transport)
        self.assertIn('backendLabel() { return "LSFG"; }', transport)
        self.assertIn("request.hardCompletionDeadlineNs()", transport)
        self.assertIn("request.desiredPhysicalPresentTimeNs()", transport)
        self.assertIn("request.driverDesiredPresentTimeNs()", transport)
        self.assertIn("request.sessionEpoch()", transport)
        self.assertIn("request.presentationEpoch()", transport)
        self.assertIn("endpoint.image.getFence()", transport)
        self.assertIn("if (!fence.isValid()) return true;", transport)
        self.assertIn("fence.getSignalTime() != SyncFence.SIGNAL_TIME_PENDING", transport)
        self.assertNotIn("fence.await(", transport)
        self.assertIn("left.buffer, right.buffer", transport)
        self.assertIn("HardwareBuffer left, HardwareBuffer right", bridge)
        self.assertIn("SUBMIT_NOT_READY", bridge)
        self.assertIn("three prewarmed fixed-AHB LSFG", bridge)
        self.assertIn("kSlotCount = emufusion::lsfg::OwnedVulkanHost::kFixedSlotCount", native)
        self.assertIn("AHardwareBuffer_allocate", native)
        self.assertIn("createContextFromAHB", native)
        self.assertIn("tryPresentContextSyncFd", native)
        self.assertIn("kSetupFenceTimeoutMs", native)
        self.assertIn("runBoundedSurfaceControlSelfTest(host.get())", native)
        self.assertIn("setupOnlyCpuContentCheck", native)
        self.assertIn("OwnedSurfaceControlPresenter", native)
        self.assertIn("AHARDWAREBUFFER_USAGE_COMPOSER_OVERLAY", native)
        self.assertIn("selfTestGenerationCompleteNs", native)
        self.assertIn("selfTestPhysicalIntervalNs", native)
        self.assertIn(
            "constexpr uint64_t timingFeedbackTimeoutNs = 3'000'000'000ULL;",
            native)
        self.assertIn("self-test timing deadline overflow", native)
        self.assertIn("host->ownedVulkan->diagnosticJson()", native)
        self.assertIn("selfTestEndpoint", native)
        self.assertIn("selfTestGenerated", native)
        self.assertIn("selfTestDeadline", native)
        self.assertIn("selfTestPhysicalTiming", native)
        self.assertIn("selfTestContent", native)
        self.assertIn('"ownedWsiImplemented\\":false', native)
        self.assertIn('"surfaceControlLiveImplemented\\":true', native)
        self.assertIn('"surfaceControlReleaseFenceReuse\\":true', native)
        enqueue = native.split(
            "Java_com_thorium_preview_game_NativeLsfgBridge_enqueue", 1
        )[1].split("Java_com_thorium_preview_game_NativeLsfgBridge_poll", 1)[0]
        self.assertIn("return 0", enqueue)
        self.assertNotIn("vkDeviceWaitIdle", enqueue)
        self.assertIn("ownedWsiSetupPassed", native)
        self.assertIn("liveResourcesReady", native)
        self.assertIn("fixedBuffersImported", transport)
        self.assertIn("setupOwnershipReleased", transport)
        self.assertIn("ownedWsiImplemented", transport)
        self.assertIn("surfaceControlLiveImplemented", transport)
        self.assertIn("surfaceControlReleaseFenceReuse", transport)
        self.assertIn("VK_PRESENT_MODE_FIFO_KHR", owned)
        self.assertIn(
            "const VkQueueFlags required = VK_QUEUE_GRAPHICS_BIT;", owned)
        self.assertNotIn(
            "VK_QUEUE_GRAPHICS_BIT | VK_QUEUE_TRANSFER_BIT", owned)
        self.assertIn("vkGetRefreshCycleDurationGOOGLE", owned)
        self.assertIn("vkGetAndroidHardwareBufferPropertiesANDROID", owned)
        self.assertNotIn("formatProperties.externalFormat != 0", owned)
        self.assertIn(
            "does not chain\n        // VkExternalFormatANDROID", owned)
        self.assertIn(
            '"owned Vulkan device entry points unavailable:" + missing.str()',
            owned)
        self.assertIn("VK_QUEUE_FAMILY_EXTERNAL", owned)
        self.assertIn("vkAcquireNextImageKHR", owned)
        self.assertIn("vkQueuePresentKHR", owned)
        self.assertIn("VkPresentTimeGOOGLE", owned)
        self.assertIn("::poll(&descriptor, 1, 0)", owned)
        self.assertIn(
            "LSFG output missed its immutable completion deadline", owned)
        self.assertIn("vkCmdCopyImageToBuffer", owned)
        self.assertIn("vkInvalidateMappedMemoryRanges", owned)
        self.assertIn("collectPastPresentationTimings", owned)
        self.assertIn("pollSurfaceSubmission", owned)
        self.assertIn("pollSurfaceCompletion", owned)
        self.assertIn("retireSurfacePresentation", owned)
        self.assertIn("recordSurfaceProof", owned)
        self.assertIn("vkImportSemaphoreFdKHR", owned)
        poll = native.split("progressLiveSurfacePipeline(Host* host,", 1)[1].split(
            "void runBoundedSurfaceControlSelfTest", 1
        )[0]
        self.assertIn("dispatchReadySurfaceSubmission(host)", poll)
        dispatch = native.split("void dispatchReadySurfaceSubmission(Host*", 1)[1].split(
            "void logSurfaceTimingDiagnostic", 1)[0]
        self.assertIn("pollSurfaceSubmission", dispatch)
        self.assertIn("surfacePresenter->present", dispatch)
        self.assertIn("surfacePresenter->pollCompletion", poll)
        self.assertIn("pollSurfaceCompletion", poll)
        self.assertIn("isReleased", poll)
        self.assertIn("retireSurfacePresentation", poll)
        self.assertNotIn("ownedVulkan->pollCompletion()", poll)
        self.assertIn("progressLiveSurfacePipeline(host)", native.split(
            "Java_com_thorium_preview_game_NativeLsfgBridge_poll", 1
        )[1])
        self.assertIn("runBoundedLiveSurfaceControlSelfTest(host.get())", native)
        self.assertIn("selfTestLiveSurfaceControl", native)
        self.assertIn('" expectedFirstId="', native)
        self.assertIn('" secondOutput="', native)
        self.assertIn('" secondDesired="', native)
        self.assertIn('" secondPair="', native)
        self.assertIn("runBoundedLiveCadenceSoak(host.get())", native)
        self.assertIn("selfTestLiveCadencePresents", native)
        self.assertIn("selfTestLiveCadenceMaxErrorNs", native)
        self.assertIn("pastTimingQueries_", owned)
        self.assertIn("presentFenceReady", owned)
        self.assertNotIn("ANativeWindow_lock", owned)
        # The diagnostic pixel probe has its own initialization. Check the
        # app's open path, not unrelated earlier function text.
        app_open = native[native.index("Java_com_thorium_preview_game_NativeLsfgBridge_open("):]
        import_pos = app_open.index("ownedVulkan->importAndPrepareFixedBuffers")
        fill_pos = app_open.index("fillSetupPattern(host->slots[index].left")
        initialize_pos = app_open.index("LSFG_3_1::initialize")
        self.assertLess(import_pos, fill_pos)
        self.assertLess(fill_pos, initialize_pos)
        self.assertIn("lsfg-vk-framegen", cmake)
        self.assertIn(
            "target_compile_definitions(volk PUBLIC "
            "VK_USE_PLATFORM_ANDROID_KHR=1)", cmake)
        self.assertIn("VK_USE_PLATFORM_ANDROID_KHR", cmake)
        self.assertIn("max-page-size=16384", cmake)


if __name__ == "__main__":
    unittest.main()
