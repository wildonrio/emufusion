import json
import hashlib
import importlib.util
import re
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "engines" / "phase2-registry.json"
LOCK = ROOT / "engines" / "dolphin-source-lock.json"
RECIPE = ROOT / "engines" / "build_core.sh"
ACTIVITY_QA = ROOT / "unified-android" / "tools" / "run_phase2_activity_qa.py"
LIBRETRO_INPUT = ROOT / "unified-android" / "src" / "com" / "thorium" / "lucent" / "input" / "LibretroJoypadLayout.java"
SYSTEM_LAYOUTS = ROOT / "unified-android" / "src" / "com" / "thorium" / "lucent" / "input" / "SystemControlLayouts.java"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_controller_mapping import layout_blocks  # noqa: E402
LIBRETRO_HOST = ROOT / "unified-android" / "native" / "lucent_libretro_host.c"
RENDERED_DUPLICATE_PATCH = (
    ROOT / "engines" / "patches" /
    "dolphin-libretro-submit-rendered-duplicate-xfb.patch"
)
PHASE2_SESSION = ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" / "game" / "PpssppGlesEngineSession.java"
GLES_HOST = ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" / "ExperimentalGlesLibretroHost.java"
GLES_LOOP = ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" / "ExperimentalGlesRenderLoop.java"
GLES_JNI = ROOT / "unified-android" / "native" / "lucent_libretro_jni.c"
WII_POINTER = ROOT / "unified-android" / "src" / "com" / "thorium" / "lucent" / "input" / "WiiIrPointer.java"
DISC_PREFLIGHT = ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" / "game" / "DiscImagePreflight.java"
CORRUPT_FBO_FIXTURE = (
    ROOT / "unified-android" / "test" / "fixtures" / "dolphin-corrupt-fbo.png"
)


class DolphinCompilerProofTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        cls.engine = next(row for row in registry["engines"] if row["id"] == "dolphin")
        cls.lock = json.loads(LOCK.read_text(encoding="utf-8"))
        cls.recipe = RECIPE.read_text(encoding="utf-8")

    def test_disc_images_are_validated_before_native_core_load(self):
        session = PHASE2_SESSION.read_text(encoding="utf-8")
        preflight = DISC_PREFLIGHT.read_text(encoding="utf-8")
        self.assertLess(
            session.index("DiscImagePreflight.validate(request.systemId, game)"),
            session.index("entry.installRuntime(appContext, request.systemId)"),
        )
        self.assertIn("declaredSize != file.length()", preflight)
        self.assertIn("container header checksum is invalid", preflight)
        self.assertIn("secondary header checksum is invalid", preflight)
        self.assertIn('"gamecube".equals(systemId)', preflight)
        self.assertIn('"wii".equals(systemId)', preflight)

    def test_quick_resume_recreates_dolphin_presentation(self):
        session = PHASE2_SESSION.read_text(encoding="utf-8")
        restore = session.split(
            "private void restoreQuickResume", 1)[1].split(
                "private Throwable saveQuickResume", 1)[0]
        self.assertIn('"dolphin".equals(entry.id)', restore)
        self.assertIn("applyRuntimeState(active, state);", restore)
        self.assertIn("active.unserialize(state, migrateRenderer);", restore)
        self.assertNotIn("active.recreateSurface(current);", restore)
        self.assertIn("stale cyan/blank", restore)
        manual = session.split("private void restore(StateSnapshot snapshot)", 1)[1].split(
            "private synchronized void refreshDevices", 1)[0]
        self.assertIn("applyRuntimeState(active, loaded.state);", manual)
        self.assertNotIn("active.unserialize(loaded.state);", manual)

    def test_core_and_dependency_closure_are_exact(self):
        source = self.engine["source"]
        self.assertEqual(source["dependencyLock"], "engines/dolphin-source-lock.json")
        self.assertEqual(self.lock["core"]["repository"], source["repository"])
        self.assertEqual(self.lock["core"]["commit"], source["commit"])
        self.assertEqual(self.lock["core"]["archiveSha256"], source["archiveSha256"])
        dependencies = self.lock["dependencies"]
        self.assertEqual(len(dependencies), 30)
        self.assertEqual(len({row["path"] for row in dependencies}), 30)
        for row in dependencies:
            self.assertTrue(row["repository"].startswith("https://"))
            self.assertRegex(row["commit"], r"^[0-9a-f]{40}$")
            self.assertRegex(row["archiveSha256"], r"^[0-9a-f]{64}$")

    def test_recipe_contains_every_locked_identity(self):
        self.assertIn("dolphin)", self.recipe)
        for row in self.lock["dependencies"]:
            self.assertIn(row["path"], self.recipe)
            self.assertIn(row["repository"], self.recipe)
            self.assertIn(row["commit"], self.recipe)
            self.assertIn(row["archiveSha256"], self.recipe)
        self.assertTrue(self.lock["cmakeOptions"]["LIBRETRO"])
        self.assertEqual(
            self.lock["cmakeOptions"]["normalizedByRemovingSection"],
            ".note.gnu.build-id",
        )
        self.assertEqual(
            self.engine["build"]["proofArtifactSha256"],
            self.lock["cmakeOptions"]["normalizedArtifactSha256"],
        )

    def test_compiler_proof_does_not_claim_runtime_qualification(self):
        engine = self.engine
        self.assertEqual(engine["route"], "libretro-core")
        self.assertFalse(engine["shipped"])
        self.assertTrue(engine["gates"]["androidArm64"])
        for gate in ("license", "dependencies", "legalContent", "renderer",
                     "state", "performance", "device"):
            self.assertFalse(engine["gates"][gate])
        self.assertEqual(engine["build"]["recipe"], "engines/build_core.sh dolphin")
        self.assertRegex(engine["build"]["proofArtifactSha256"], r"^[0-9a-f]{64}$")

    def test_recipe_builds_the_in_process_core_not_android_jni(self):
        dolphin_recipe = self.recipe.split("    dolphin)", 1)[1].split(
            "    ppsspp)", 1
        )[0]
        self.assertIn("https://github.com/libretro/dolphin", dolphin_recipe)
        self.assertIn("-DLIBRETRO=ON", dolphin_recipe)
        self.assertIn("--target dolphin_libretro", dolphin_recipe)
        self.assertIn("dolphin_libretro_android.so", dolphin_recipe)
        self.assertIn("max-page-size=16384", dolphin_recipe)
        self.assertIn("--remove-section=.note.gnu.build-id", dolphin_recipe)
        self.assertIn(
            self.lock["cmakeOptions"]["normalizedArtifactSha256"],
            dolphin_recipe,
        )
        self.assertNotIn("Source/Android/jni/libmain.so", dolphin_recipe)
        self.assertNotIn("dolphin_native.so", dolphin_recipe)

    def test_failed_checksum_cannot_replace_qualified_core(self):
        dolphin_recipe = self.recipe.split("    dolphin)", 1)[1].split(
            "    ppsspp)", 1
        )[0]
        self.assertIn("candidate_dir=$(mktemp -d", dolphin_recipe)
        self.assertIn(
            'normalized_core="$candidate_dir/dolphin_libretro.so"',
            dolphin_recipe,
        )
        checksum_check = dolphin_recipe.index(
            "Normalized Dolphin core checksum mismatch"
        )
        publish = dolphin_recipe.index(
            'mv "$normalized_core" "$OUTPUT_DIR/dolphin_libretro.so"'
        )
        self.assertLess(checksum_check, publish)

    def test_recipe_pins_nested_scm_and_lucent_frontend_patch(self):
        dolphin_recipe = self.recipe.split("    dolphin)", 1)[1].split(
            "    ppsspp)", 1
        )[0]
        path = "engines/tools/dolphin-git-shim/git"
        expected_sha = (
            "7f0591b727b7961b72092778de867b3c4498b1fe3eb935fa38bb47a9cf6a462c"
        )
        self.assertIn(path, dolphin_recipe)
        self.assertIn(expected_sha, dolphin_recipe)
        self.assertTrue((ROOT / path).is_file())
        self.assertEqual(hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), expected_sha)
        self.assertIn('PATH="$dolphin_git_path:$PATH"', dolphin_recipe)
        self.assertEqual(len(self.lock["patches"]), 3)
        for row in self.lock["patches"]:
            self.assertEqual(hashlib.sha256((ROOT / row["path"]).read_bytes()).hexdigest(), row["sha256"])
            self.assertIn(row["path"], dolphin_recipe)
            self.assertIn(row["sha256"], dolphin_recipe)
        locked_patch = self.lock["patches"][0]
        self.assertEqual(
            locked_patch["path"],
            "engines/patches/dolphin-libretro-submit-rendered-duplicate-xfb.patch",
        )
        patch_sha = hashlib.sha256(RENDERED_DUPLICATE_PATCH.read_bytes()).hexdigest()
        self.assertEqual(locked_patch["sha256"], patch_sha)
        self.assertIn(locked_patch["path"], dolphin_recipe)
        self.assertIn(patch_sha, dolphin_recipe)

    def test_rendered_duplicate_xfb_is_submitted_to_lucent(self):
        patch = RENDERED_DUPLICATE_PATCH.read_text(encoding="utf-8")
        self.assertIn("void GLContextLR::Swap()", patch)
        self.assertIn(
            "Libretro::Video::video_cb(RETRO_HW_FRAME_BUFFER_VALID,",
            patch,
        )
        self.assertNotIn(
            "+  Libretro::Video::video_cb(VideoCommon::g_is_duplicate_frame ? nullptr",
            patch,
        )

    def test_dolphin_is_qualification_packaged_and_library_routed(self):
        opt_in = json.loads((ROOT / "engines" /
            "phase2-qualification-opt-in.json").read_text(encoding="utf-8"))
        row = next(value for value in opt_in["engines"] if value["id"] == "dolphin")
        self.assertEqual(row["libraryRouteSystems"], ["gamecube", "wii"])
        self.assertEqual(row["runtime"], "vulkan-libretro")
        self.assertEqual(row["systemAssetDestination"], "dolphin-emu")

    def test_activity_qa_accepts_android_logcat_pid_tag_format(self):
        harness = ACTIVITY_QA.read_text(encoding="utf-8")
        self.assertIn(r"LucentGlesBackend(?:\(\s*\d+\))?: ", harness)
        self.assertIn(r"presentation geometry.*sourcePadding=0", harness)
        self.assertNotIn(
            '"LucentGlesBackend: presentation geometry"', harness
        )

    def test_dolphin_controller_geometry_and_semantic_qa_are_explicit(self):
        mapping = LIBRETRO_INPUT.read_text(encoding="utf-8")
        phase2_session = PHASE2_SESSION.read_text(encoding="utf-8")
        harness = ACTIVITY_QA.read_text(encoding="utf-8")
        # Dolphin (GameCube/Wii) keeps A under the thumb and each console gets
        # its own table in SystemControlLayouts, taken from the pinned core's
        # own input descriptors rather than the generic RetroPad convention.
        # Every entry carries the console's name and the RetroPad ID together,
        # so the remap editor and the running game cannot disagree.
        tables = layout_blocks(SYSTEM_LAYOUTS.read_text(encoding="utf-8"))
        gamecube = tables["gamecube"]
        # descGC: A=8, B=0, X=9, Y=1, L/R are the analog triggers and Z=R(11).
        # A GameCube pad is not a diamond — A sits in the middle with B to its
        # lower left, X to its right and Y above it — so B takes the left face
        # button and X the right.
        self.assertEqual(("A", 8), gamecube["SOUTH"])
        self.assertEqual(("B", 0), gamecube["WEST"])
        self.assertEqual(("X", 9), gamecube["EAST"])
        self.assertEqual(("Y", 1), gamecube["NORTH"])
        self.assertEqual(("L", 12), gamecube["L2"])
        self.assertEqual(("R", 13), gamecube["R2"])
        self.assertEqual(("Z", 11), gamecube["R1"])
        # RetroPad L(10) is descGC's "Triforce - Test" and SELECT(2) its
        # "Triforce - Coin". Neither is a GameCube control, so neither binds.
        self.assertNotIn("L1", gamecube)
        self.assertNotIn("SELECT", gamecube)
        # descWiimote/descWiimoteNunchuk: X(9) is "1"/Nunchuk C, Y(1) is
        # "2"/Nunchuk Z, L(10)/R(11) are -/+ and L2(12) shakes the Nunchuk.
        wii = tables["wii"]
        self.assertEqual(8, wii["SOUTH"][1])
        self.assertEqual(0, wii["EAST"][1])
        self.assertEqual(9, wii["WEST"][1])
        self.assertEqual(1, wii["NORTH"][1])
        self.assertEqual(10, wii["L1"][1])
        self.assertEqual(11, wii["R1"][1])
        self.assertEqual(12, wii["L2"][1])
        self.assertEqual(13, wii["R2"][1])
        # The semantic table still names the right stick as IR; the session
        # mirrors it to a real pointer while preserving analog index 1.
        self.assertEqual(("C_STICK", -1), gamecube["RIGHT_X_POSITIVE"])
        self.assertEqual(("IR_POINTER", -1), wii["RIGHT_X_POSITIVE"])
        # Nunchuk-only titles need Dolphin's RETRO_DEVICE_WIIMOTE_NC device.
        self.assertIn(
            'WIIMOTE_NUNCHUK = (3 << 8) | RETRO_DEVICE_JOYPAD', mapping
        )
        self.assertIn('portDeviceFor(String systemId)', mapping)
        # The right stick never becomes a digital button, and the left stick
        # never doubles as the D-pad on a console whose core reads it as its
        # own analog control.
        self.assertIn('case RIGHT_X_NEGATIVE: case RIGHT_X_POSITIVE:', mapping)
        analog = mapping.split("public static boolean hasAnalogStick(", 1)[1].split(
            "\n    }", 1
        )[0]
        for system in ('"gamecube"', '"wii"', '"n64"'):
            self.assertIn(system, analog)
        self.assertIn(
            'LibretroJoypadLayout.idFor(request.systemId, control)',
            phase2_session,
        )
        self.assertIn("GameCube physical A did not leave the initial prompt", harness)
        self.assertIn("Dolphin submitted incomplete frames after navigation", harness)
        self.assertIn('if visible_burst_frames != 16:', harness)

    def test_wii_ir_is_a_real_gles_pointer_without_sacrificing_tilt(self):
        session = PHASE2_SESSION.read_text(encoding="utf-8")
        host = GLES_HOST.read_text(encoding="utf-8")
        loop = GLES_LOOP.read_text(encoding="utf-8")
        jni = GLES_JNI.read_text(encoding="utf-8")
        pointer = WII_POINTER.read_text(encoding="utf-8")
        self.assertIn("WiiIrPointer", session)
        self.assertIn("active.setPointer(0, pointer.x, pointer.y, pointer.pressed)",
                      session)
        motion = session.split("dispatchGenericMotionEvent", 1)[1].split(
            "openControls", 1)[0]
        self.assertIn("active.setAnalogAxis(0, 1, 0, normalizedRightX)", motion)
        self.assertIn("wiiIrPointer.move(normalizedRightX, normalizedRightY)", motion)
        keys = session.split("dispatchKeyEvent", 1)[1].split(
            "dispatchGenericMotionEvent", 1)[0]
        self.assertIn("control == CanonicalControl.SOUTH", keys)
        self.assertIn("wiiIrPointer.setPressed(pressed)", keys)
        self.assertIn("nativeHost.setPointer(port, x, y, pressed)", loop)
        self.assertIn("nativeSetPointerGles", host)
        self.assertIn("nativeSetPointerGles", jni)
        self.assertIn("lucent_retro_set_pointer", jni)
        self.assertIn("Short.MIN_VALUE", pointer)
        self.assertIn("Short.MAX_VALUE", pointer)

    def test_dolphin_uses_pointer_backed_ir_mode(self):
        host = LIBRETRO_HOST.read_text(encoding="utf-8")
        profile = host.split('"dolphin_ir_mode"', 1)[1].split(
            "} else if", 1
        )[0]
        self.assertIn('find_option_token(options, "2", &value_size)', profile)

    def test_dolphin_runs_single_core_to_avoid_the_frame_pump_deadlock(self):
        # Dolphin's dual-core libretro pump calls Core::DoFrameStep() before
        # FifoManager::RunGpuLoop() on the same thread. Its Running branch
        # enters CPUManager::SetStepping(true), which blocks until the separate
        # CPU thread idles, while that CPU thread can only idle once this
        # thread drains the FIFO. Both threads then sleep forever, which is the
        # observed GameCube/Wii freeze. Single core keeps emulation on the one
        # render thread, so no cross-thread handoff can deadlock.
        host = LIBRETRO_HOST.read_text(encoding="utf-8")
        self.assertIn('strcmp(variable->key, "dolphin_main_cpu_thread") == 0', host)
        profile = host.split('"dolphin_main_cpu_thread"', 1)[1].split(
            "} else if", 1
        )[0]
        self.assertIn('options, "disabled", &value_size', profile)
        self.assertNotIn('options, "enabled", &value_size', profile)

    def test_dolphin_shader_profile_uses_the_actual_synchronous_token(self):
        host = LIBRETRO_HOST.read_text(encoding="utf-8")
        profile = host.split('"dolphin_shader_compilation_mode"', 1)[1].split(
            '"dolphin_wait_for_shaders"', 1
        )[0]
        self.assertIn('options, "0", &value_size', profile)
        self.assertNotIn('options, "Synchronous", &value_size', profile)

    def test_wii_uses_vulkan_without_changing_gamecube_api(self):
        session = PHASE2_SESSION.read_text(encoding="utf-8")
        selection = session.split("final boolean useVulkanRuntime", 1)[1].split(
            "final ExperimentalGlesRenderLoop loop", 1
        )[0]
        self.assertIn('"vulkan-libretro".equals(entry.runtime)', selection)
        self.assertIn('"dolphin".equals(entry.id)', selection)
        self.assertIn("isWiiSystem(request.systemId)", selection)
        self.assertNotIn("isGameCubeSystem", selection)
        self.assertIn("useVulkanRuntime ?", session)

        vulkan = (ROOT / "unified-android" / "src" / "com" / "thorium" /
                  "preview" / "ExperimentalVulkanLibretroHost.java").read_text(
                      encoding="utf-8")
        jni = (ROOT / "unified-android" / "native" /
               "lucent_libretro_vulkan_jni.c").read_text(encoding="utf-8")
        self.assertIn("nativeSetControllerPortDeviceVulkan(handle, port, device)",
                      vulkan)
        self.assertIn("nativeSetControllerPortDeviceVulkan", jni)
        self.assertIn("lucent_retro_set_controller_port_device", jni)

    def test_rejected_dolphin_dso_is_quarantined_before_dlclose(self):
        # Exact Thor tombstones showed rejected/partial Dolphin globals crashing
        # from DSO finalizers beneath dlclose. Keep only those failed mappings
        # process-resident; completed sessions retain their existing unload.
        host = LIBRETRO_HOST.read_text(encoding="utf-8")
        self.assertIn('strcmp(name, "liblucent_core_dolphin.so") == 0', host)
        self.assertIn("!is_dolphin_core_path(host->core_path)", host)
        self.assertIn("!host->completed_game_load", host)
        self.assertIn("host->completed_game_load = false;", host)
        self.assertIn("host->completed_game_load = true;", host)
        self.assertIn("dolphin_mapping_quarantined = true;", host)
        self.assertIn(
            "quarantined rejected/partial Dolphin linker image without dlclose",
            host,
        )
        self.assertIn("ANDROID_DLEXT_FORCE_LOAD", host)
        self.assertIn("forcing fresh Dolphin linker image after quarantine", host)
        self.assertIn("} else if (host->library) {", host)
        self.assertIn("dlclose(host->library);", host)

    def test_activity_qa_rejects_exact_corrupt_dolphin_frame(self):
        self.assertEqual(
            hashlib.sha256(CORRUPT_FBO_FIXTURE.read_bytes()).hexdigest(),
            "f1feff4cb668fd6d5c89745185b93e212362478d32af7e786946396c94600ba7",
        )
        spec = importlib.util.spec_from_file_location(
            "lucent_phase2_activity_qa", ACTIVITY_QA
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        metrics = module.image_metrics(CORRUPT_FBO_FIXTURE)
        self.assertTrue(metrics["edgeCorruptionDetected"])
        self.assertTrue(metrics["sideEdgeCorruptionDetected"])
        self.assertTrue(metrics["horizontalEdgeCorruptionDetected"])
        self.assertFalse(metrics["visualIntegrity"])
        self.assertFalse(metrics["visible"])

    def test_process_restore_reference_match_is_strict(self):
        spec = importlib.util.spec_from_file_location(
            "lucent_phase2_activity_qa_match", ACTIVITY_QA
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "reference.png"
            exact = Path(directory) / "exact.png"
            changed = Path(directory) / "changed.png"
            Image.new("RGB", (100, 100), (12, 18, 24)).save(reference)
            Image.new("RGB", (100, 100), (12, 18, 24)).save(exact)
            altered = Image.new("RGB", (100, 100), (12, 18, 24))
            for x in range(100):
                altered.putpixel((x, 0), (255, 255, 255))
            altered.save(changed)
            self.assertTrue(module.strict_frame_match(reference, exact)["matches"])
            mismatch = module.strict_frame_match(reference, changed)
            self.assertFalse(mismatch["matches"])
            self.assertGreater(mismatch["changedPixelFraction"], 0.005)



if __name__ == "__main__":
    unittest.main()
