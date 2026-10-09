import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


class DirectCadenceNormalizationTest(unittest.TestCase):
    def read(self, relative):
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_unqualified_native_panel_selection_remains_disabled(self):
        native = self.read(
            "unified-android/src/com/thorium/preview/game/NativeAdapterEngineSession.java")
        declaration = native.split("@Override public double declaredVideoHz()", 1)[1].split(
            "@Override", 1)[0]
        self.assertIn("!started", declaration)
        self.assertIn("active == null", declaration)
        self.assertIn("active.declaredVideoHz()", declaration)
        host = self.read("unified-android/src/com/thorium/preview/game/InWindowGameHost.java")
        ready = host.split("@Override public void onSessionReady()", 1)[1].split(
            "if (declaredVideoHz >", 1)[0]
        self.assertNotIn("((NativeAdapterEngineSession) session).declaredVideoHz()", ready)

    def test_software_and_hardware_libretro_paths_apply_the_same_clock_policy(self):
        software = self.read(
            "unified-android/src/com/thorium/preview/game/LibretroEngineSession.java")
        hardware = self.read(
            "unified-android/src/com/thorium/preview/ExperimentalGlesRenderLoop.java")
        for source in (software, hardware):
            self.assertIn("DisplaySyncPolicy.synchronizedSourceHz", source)
            self.assertIn("setSynchronizedVideoRate", source)
        self.assertIn("framePeriodNs = Math.max", software)
        self.assertIn("frameDelayNanos = frameDelayNanos(synchronizedHz)", hardware)

    def test_off_selects_exact_native_panel_mode_without_constructing_a_renderer(self):
        host = self.read(
            "unified-android/src/com/thorium/preview/game/InWindowGameHost.java")
        texture = self.read(
            "unified-android/src/com/thorium/preview/game/GameSurface.java")
        surface = self.read(
            "unified-android/src/com/thorium/preview/game/GameSurfaceView.java")
        self.assertIn("declaredVideoHz = ((LibretroEngineSession) session)", host)
        self.assertIn("declaredVideoHz = ((PpssppGlesEngineSession) session)", host)
        self.assertGreaterEqual(host.count("setDirectPresentationHz(directPanelHz)"), 2)
        self.assertIn("directSurfaceCadenceHz(declaredVideoHz)", host)
        self.assertIn("directSurfaceCadenceHz(authoritativeHz)", host)
        self.assertIn("DisplaySyncPolicy.isUniformOnThor(synchronizedHz)", host)
        self.assertIn("requestNativePanelMode();", host)
        self.assertIn("requestNativePanelMode(\n                            DisplaySyncPolicy.directPanelRefreshHz", host)
        self.assertIn("preferredDisplayModeId = selectedModeId", host)
        self.assertIn("preferredRefreshRate = refreshHz", host)
        self.assertIn("mode.getRefreshRate() - refreshHz", host)
        for source in (texture, surface):
            self.assertIn("outputSurface != null && outputSurface.isValid()", source)
            self.assertIn("requestDirectFrameRate(outputSurface)", source)
            off_branch = source.split(
                "if (launchMode == FrameGenerationSettings.Mode.OFF)", 1
            )[1].split("return;", 1)[0]
            self.assertIn("requestDirectFrameRate", off_branch)
            self.assertIn("uses the selected native panel mode", off_branch)
            self.assertIn("Surface.FRAME_RATE_COMPATIBILITY_DEFAULT", source)
            self.assertIn("Surface.FRAME_RATE_COMPATIBILITY_FIXED_SOURCE", source)
            self.assertIn("directPresentationHz >= 119.5f", source)

    def test_steady_state_video_transfer_uses_three_owned_buffers_without_jni_alloc(self):
        java = self.read("unified-android/src/com/thorium/preview/LibretroHost.java")
        jni = self.read("unified-android/native/lucent_libretro_jni.c")
        session = self.read(
            "unified-android/src/com/thorium/preview/game/LibretroEngineSession.java")
        self.assertIn("VIDEO_BUFFER_POOL_SIZE = 3", java)
        self.assertIn("reusableVideoCapacity(byteSize)", java)
        self.assertIn("pixels.length < byteSize", java)
        self.assertIn("nativeCopyVideoFrameInto(handle, frame.pixels)", java)
        self.assertIn("GetPrimitiveArrayCritical", jni)
        copy_body = jni.split(
            "Java_com_thorium_preview_LibretroHost_nativeCopyVideoFrameInto", 1
        )[1].split("JNIEXPORT", 1)[0]
        self.assertNotIn("malloc(", copy_body)
        self.assertNotIn("NewByteArray", copy_body)
        self.assertIn("videoMailbox.close(LibretroHost.VideoFrame::release)", session)
        self.assertIn("newest, LibretroHost.VideoFrame::release", session)
        self.assertIn("finally {\n                        frame.release();", session)
        self.assertIn("videoBufferAllocations=%d videoPoolExhaustions=%d", session)

    def test_native_audio_proof_uses_exact_snes_and_gba_clocks(self):
        native_test = self.read("unified-android/native/tests/host_test.c")
        self.assertIn("host, 60.0988, 60.0", native_test)
        self.assertIn("host, 59.7275, 60.0", native_test)
        self.assertIn("== 701", native_test)
        self.assertIn("== 696", native_test)


if __name__ == "__main__":
    unittest.main()
