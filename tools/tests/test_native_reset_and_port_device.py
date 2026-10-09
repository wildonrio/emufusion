"""retro_reset and the controller port device on both engine paths.

Two device bugs share one root cause: EmuFusion's native host resolved
``retro_reset`` but never called it, and the hardware (GLES) session never
selected a controller port device. Wii and GameCube run on the hardware path,
so Super Mario Galaxy 2 took no input until the Nunchuk device was attached
there, and no session could power-cycle a game through libretro's own reset.

These tests pin the whole chain -- native host, JNI, the two Java hosts, the
render loop, and both sessions -- because every link is separately loseable.
"""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "unified-android" / "native"
HOST_C = NATIVE / "lucent_libretro_host.c"
HOST_H = NATIVE / "include" / "lucent_libretro_host.h"
JNI_C = NATIVE / "lucent_libretro_jni.c"
NATIVE_TESTS = NATIVE / "tests"
PREVIEW = ROOT / "unified-android" / "src" / "com" / "thorium" / "preview"
LIBRETRO_HOST = PREVIEW / "LibretroHost.java"
GLES_HOST = PREVIEW / "ExperimentalGlesLibretroHost.java"
RENDER_LOOP = PREVIEW / "ExperimentalGlesRenderLoop.java"
LIBRETRO_SESSION = PREVIEW / "game" / "LibretroEngineSession.java"
PPSSPP_SESSION = PREVIEW / "game" / "PpssppGlesEngineSession.java"


def body_after(source: str, signature: str) -> str:
    """Returns the braced body of the first declaration containing it."""
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[opening:index + 1]
    raise AssertionError(f"unbalanced braces after {signature!r}")


class NativeResetTest(unittest.TestCase):
    def setUp(self):
        self.host = HOST_C.read_text(encoding="utf-8")
        self.header = HOST_H.read_text(encoding="utf-8")
        self.jni = JNI_C.read_text(encoding="utf-8")

    def test_the_host_exposes_the_reset_it_already_resolves(self):
        # The symbol was resolved long before anything could call it.
        self.assertIn('RESOLVE(host, reset, "retro_reset");', self.host)
        self.assertIn(
            "bool lucent_retro_reset(lucent_retro_host *host, char *error,",
            self.header,
        )
        self.assertIn(
            "bool lucent_retro_reset(lucent_retro_host *host, char *error,",
            self.host,
        )

    def test_reset_fails_closed_and_holds_the_host_lock(self):
        body = body_after(self.host, "bool lucent_retro_reset(lucent_retro_host")
        self.assertIn("lock_host();", body)
        # No host, no loaded game, and no resolved function pointer are all
        # rejected before the core is touched.
        self.assertIn("!host || !host->game_loaded || !host->reset", body)
        self.assertIn("RETURN_UNLOCKED(false);", body)
        # Cores may emit video/audio from inside retro_reset, so the callback
        # owner has to be this host first, exactly as run_frame does.
        self.assertLess(body.index("active_host = host;"), body.index("host->reset();"))
        self.assertIn("__android_log_print(ANDROID_LOG_INFO, \"LucentNativeHost\"", body)

    def test_the_jni_boundary_binds_reset_on_both_hosts(self):
        self.assertIn(
            "Java_com_thorium_preview_LibretroHost_nativeReset", self.jni
        )
        self.assertIn(
            "Java_com_thorium_preview_ExperimentalGlesLibretroHost_nativeResetGles",
            self.jni,
        )
        software = body_after(
            self.jni, "Java_com_thorium_preview_LibretroHost_nativeReset")
        self.assertIn("lucent_retro_reset(from_handle(handle)", software)
        self.assertIn("throw_state(env, error);", software)
        # The GLES session wraps the host in a session struct; the reset has
        # to reach the same underlying host the game was loaded into.
        hardware = body_after(
            self.jni,
            "Java_com_thorium_preview_ExperimentalGlesLibretroHost_nativeResetGles",
        )
        self.assertIn("from_gles_handle(handle)", hardware)
        self.assertIn("session && session->host", hardware)
        self.assertIn("lucent_retro_reset(session->host", hardware)

    def test_the_jni_boundary_binds_the_port_device_on_the_hardware_host(self):
        name = ("Java_com_thorium_preview_ExperimentalGlesLibretroHost_"
                "nativeSetControllerPortDeviceGles")
        self.assertIn(name, self.jni)
        body = body_after(self.jni, name)
        self.assertIn("from_gles_handle(handle)", body)
        self.assertIn("lucent_retro_set_controller_port_device(session->host", body)
        self.assertIn("(unsigned)port, (unsigned)device", body)
        self.assertIn("throw_state(env, error);", body)


class NativeCoverageTest(unittest.TestCase):
    def test_the_mock_cores_record_reset_and_the_port_device(self):
        for name in ("mock_core.c", "hw_mock_core.c"):
            mock = (NATIVE_TESTS / name).read_text(encoding="utf-8")
            reset = body_after(mock, "void retro_reset(void)")
            self.assertRegex(reset, r"reset_count\+\+;",
                             f"{name} does not record retro_reset")
            port = body_after(mock, "void retro_set_controller_port_device(")
            self.assertIn("port_device_count++;", port)
            self.assertIn("last_port = port;", port)
            self.assertIn("last_device = device;", port)

    def test_the_software_host_test_proves_reset_and_the_port_device(self):
        test = (NATIVE_TESTS / "host_test.c").read_text(encoding="utf-8")
        self.assertIn("lucent_mock_reset_count", test)
        self.assertIn("lucent_mock_port_device_count", test)
        self.assertIn('CHECK(lucent_retro_reset(host, error, sizeof(error)), "reset failed");',
                      test)
        self.assertIn('"retro_reset was not invoked"', test)
        self.assertIn('"reset did not power-cycle core state"', test)
        # A soft reset must not erase battery-backed save RAM.
        self.assertIn('"reset erased battery-backed save RAM"', test)
        # Fail-closed gates: before a load, after an unload, and on NULL.
        self.assertIn('"reset was accepted before a game was loaded"', test)
        self.assertIn('"unloaded game accepted a reset"', test)
        self.assertIn('"null host accepted a reset"', test)
        # And the port device itself reaches the core unchanged.
        self.assertIn('"Wii Nunchuk port device was rejected"', test)
        self.assertIn('"out-of-range controller port was accepted"', test)

    def test_the_hardware_host_test_covers_the_wii_path(self):
        test = (NATIVE_TESTS / "hw_host_test.c").read_text(encoding="utf-8")
        self.assertIn("lucent_hw_mock_game_reset_count", test)
        self.assertIn("lucent_hw_mock_port_device_count", test)
        self.assertIn('"hardware host rejected the Wii Nunchuk port device"', test)
        self.assertIn('"hardware port device did not reach the core unchanged"', test)
        self.assertIn('"retro_reset was not invoked on the hardware host"', test)
        # A game reset is not a hardware-context reset; the GL context must
        # survive it untouched or the next frame has nowhere to draw.
        self.assertIn('"game reset disturbed the hardware context lifecycle"', test)
        self.assertIn('"hardware frame failed after a game reset"', test)


class JavaHostBindingTest(unittest.TestCase):
    def test_the_software_host_exposes_reset(self):
        source = LIBRETRO_HOST.read_text(encoding="utf-8")
        self.assertIn("public synchronized void reset() {", source)
        self.assertIn("nativeReset(handle);", source)
        self.assertIn("private static native void nativeReset(long handle);", source)
        body = body_after(source, "public synchronized void reset()")
        self.assertIn("checkOpen();", body)

    def test_the_hardware_host_exposes_reset_and_the_port_device(self):
        source = GLES_HOST.read_text(encoding="utf-8")
        # Both go through the Bindings seam so the lifecycle probe can fake
        # them; a direct native call would be untestable off-device.
        self.assertIn("void setControllerPortDevice(long handle, int port, int device);",
                      source)
        self.assertIn("void reset(long handle);", source)
        self.assertIn("nativeSetControllerPortDeviceGles(handle, port, device);", source)
        self.assertIn("nativeResetGles(handle);", source)
        self.assertIn("public synchronized void setControllerPortDevice(int port, int device) {",
                      source)
        self.assertIn("public synchronized void reset() {", source)
        self.assertIn("private static native void nativeResetGles(long handle);", source)
        self.assertIn("nativeSetControllerPortDeviceGles(long handle, int port,", source)
        for signature in ("public synchronized void reset()",
                          "public synchronized void setControllerPortDevice(int port"):
            self.assertIn("checkOpen();", body_after(source, signature))


class RenderLoopMarshallingTest(unittest.TestCase):
    def setUp(self):
        self.source = RENDER_LOOP.read_text(encoding="utf-8")

    def test_both_calls_are_part_of_the_render_thread_host_contract(self):
        interface = body_after(self.source, "interface Host extends Closeable")
        self.assertIn("void setControllerPortDevice(int port, int device);", interface)
        self.assertIn("void reset();", interface)

    def test_the_gles_host_delegates_to_the_native_session(self):
        self.assertIn("nativeHost.setControllerPortDevice(port, device);", self.source)
        self.assertIn("@Override public void reset() { nativeHost.reset(); }", self.source)

    def test_the_vulkan_host_delegates_port_device_and_reset(self):
        vulkan = self.source.split("public static ExperimentalGlesRenderLoop createVulkan", 1)[1]
        self.assertIn("nativeHost.setControllerPortDevice(port, device);", vulkan)
        self.assertIn("@Override public void reset() { nativeHost.reset(); }", vulkan)
        self.assertNotIn("Vulkan session exposes no reset", vulkan)

    def test_both_calls_are_marshalled_onto_the_render_owner_thread(self):
        # call() runs on the render thread and waits (bounded), unlike post()
        # which returns before the work happens. A caller that must report
        # success, or must finish before the first frame, needs call().
        reset = body_after(self.source, "\n    public void reset()")
        self.assertIn("call(() -> { host.reset(); return null; });", reset)
        port = body_after(self.source, "public void setControllerPortDevice(final int port")
        self.assertIn("host.setControllerPortDevice(port, device); return null;", port)
        self.assertIn("call(", port)


class HardwareSessionWiringTest(unittest.TestCase):
    """Wii and GameCube run on the hardware path, not the software one."""

    def setUp(self):
        self.source = PPSSPP_SESSION.read_text(encoding="utf-8")
        self.ready = body_after(self.source, "private void handleReady(Listener callback)")
        self.reset = body_after(self.source, "@Override public boolean reset()")

    def test_the_port_device_is_selected_right_after_the_game_load(self):
        self.assertIn("LibretroJoypadLayout.portDeviceFor(request.systemId)", self.ready)
        # Guarded exactly like the software session: a plain RetroPad needs no
        # call, and loading already selected one.
        self.assertIn("portDevice != LibretroJoypadLayout.RETRO_DEVICE_JOYPAD",
                      self.ready)
        self.assertIn("active.setControllerPortDevice(0, portDevice);", self.ready)
        self.assertIn('"Controller port device engine="', self.ready)
        self.assertIn('" device=0x" + Integer.toHexString(portDevice)', self.ready)
        # It must land before the surface attaches and before save RAM is
        # restored, so no frame runs against a plain RetroPad.
        self.assertLess(self.ready.index("setControllerPortDevice"),
                        self.ready.index("restoreSaveRam(active)"))
        self.assertLess(self.ready.index("setControllerPortDevice"),
                        self.ready.index("active.attachSurface(current)"))

    def test_reset_runs_through_the_render_loop_and_reports_honestly(self):
        self.assertIn("active.reset();", self.reset)
        self.assertIn("return true;", self.reset)
        self.assertIn("return false;", self.reset)
        # Success is only claimed after the synchronous render-thread call
        # returns; a throw is reported, never swallowed.
        self.assertLess(self.reset.index("active.reset();"),
                        self.reset.index("marker=reset\""))
        failure = self.reset.split("catch (Throwable failure)", 1)[1]
        self.assertIn("marker=reset-failure", failure)
        self.assertIn("return false;", failure.split("}", 1)[0] + "}")
        self.assertIn("flushAudioAfterRestore();", self.reset)

    def test_a_soft_reset_leaves_battery_save_ram_alone(self):
        # retro_reset is the console's reset button; the core keeps its SRAM.
        self.assertNotIn("restoreSaveRam", self.reset)
        self.assertNotIn("writeSaveRam", self.reset)


class SoftwareSessionWiringTest(unittest.TestCase):
    def test_the_software_session_still_attaches_the_port_device_on_load(self):
        source = LIBRETRO_SESSION.read_text(encoding="utf-8")
        self.assertIn("LibretroJoypadLayout.portDeviceFor(launch.systemId)", source)
        self.assertIn("opened.setControllerPortDevice(0, portDevice);", source)


if __name__ == "__main__":
    unittest.main()
