import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = (ROOT / "unified-android" / "build.sh").read_text(encoding="utf-8")
CORE_BUILD = (ROOT / "engines" / "build_core.sh").read_text(encoding="utf-8")
CATALOG = (ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" /
           "game" / "InternalEngineCatalog.java").read_text(encoding="utf-8")
BOOTSTRAP = (ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" /
             "game" / "InternalEngineBootstrap.java").read_text(encoding="utf-8")
ENGINE_SPEC = (ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" /
               "game" / "LibretroEngineSpec.java").read_text(encoding="utf-8")
NATIVE_HOST = (ROOT / "unified-android" / "native" /
               "lucent_libretro_host.c").read_text(encoding="utf-8")
REGISTRY = json.loads((ROOT / "engines" / "registry.json").read_text(encoding="utf-8"))
OPT_IN = json.loads((ROOT / "engines" / "qualification-opt-in.json").read_text(encoding="utf-8"))

SPEC = importlib.util.spec_from_file_location(
    "engine_artifacts",
    ROOT / "unified-android" / "tools" / "generate_engine_artifact_manifest.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class PhaseOneReleaseGateTest(unittest.TestCase):
    def test_release_defaults_exclude_qualification_cores(self):
        self.assertIn("INCLUDE_EXPERIMENTAL_CORES=${LUCENT_INCLUDE_EXPERIMENTAL_CORES:-0}", BUILD)
        self.assertIn("AUTOSELECT_EXPERIMENTAL_CORES=${LUCENT_AUTOSELECT_EXPERIMENTAL_CORES:-0}", BUILD)
        qualified = {
            "mesen", "mesen-s", "sameboy", "mgba", "gearsystem",
            "swanstation", "melonds-ds", "fuse", "mame", "dosbox-pure",
            "prosystem", "beetle-pce-fast", "beetle-neopop", "beetle-cygne",
            "blastem", "mupen64plus-next",
        }
        self.assertEqual(qualified, {row["id"] for row in OPT_IN["engines"]})
        self.assertIn(
            "for qualification_core in mesen mesen-s sameboy mgba gearsystem "
            "swanstation melonds-ds fuse mame dosbox-pure prosystem "
            "beetle-pce-fast beetle-neopop beetle-cygne blastem "
            "mupen64plus-next; do",
            BUILD,
        )
        self.assertIn(
            '"$DECODED/lib/arm64-v8a/liblucent_core_${normalized_core}.so"', BUILD
        )
        self.assertIn('"$DECODED/assets/engine-qualification-opt-in.json"', BUILD)
        self.assertFalse(any(row.get("shipped") for row in REGISTRY["engines"]))

    def test_auto_selection_cannot_be_enabled_without_explicit_core_mode(self):
        gate = (
            'if [ "$AUTOSELECT_EXPERIMENTAL_CORES" = 1 ] &&\n'
            '        [ "$INCLUDE_EXPERIMENTAL_CORES" != 1 ]; then'
        )
        self.assertIn(gate, BUILD)
        self.assertTrue(OPT_IN["qualificationOnly"])
        self.assertFalse(OPT_IN["autoSelect"])

    def test_registry_validation_precedes_native_or_core_builds(self):
        validation = BUILD.index("validate_engine_registry.py")
        native = BUILD.index('"$PROJECT_DIR/native/build.sh"')
        experimental = BUILD.index('"$ROOT_DIR/engines/build_core.sh"')
        self.assertLess(validation, native)
        self.assertLess(validation, experimental)

    def test_release_runtime_fails_closed_on_license_and_artifact_identity(self):
        self.assertIn('"compatible-candidate".equals(', CATALOG)
        self.assertIn("artifact.matches(id, source, core)", CATALOG)
        self.assertIn("firmwareRequired && acceptedFirmwareHashes.isEmpty()", CATALOG)
        self.assertIn('readAsset(context, "engine-artifacts.json")', CATALOG)

    def test_phase_one_opengl_cores_use_the_in_window_gles_host(self):
        self.assertIn('"opengl".equals(entry.renderer)', BOOTSTRAP)
        self.assertIn("new PpssppGlesEngineSession(sessionContext, entry)", BOOTSTRAP)
        self.assertIn(
            '"opengl".equals(entry.renderer) ? "gles-libretro" : "software"',
            ENGINE_SPEC,
        )

    def test_n64_defaults_select_single_context_gliden64_route(self):
        self.assertIn('strcmp(variable->key, "mupen64plus-43screensize")', NATIVE_HOST)
        self.assertIn('strcmp(variable->key, "mupen64plus-rdp-plugin")', NATIVE_HOST)
        self.assertIn('strcmp(variable->key, "mupen64plus-rsp-plugin")', NATIVE_HOST)
        self.assertIn('strcmp(variable->key, "mupen64plus-ThreadedRenderer")', NATIVE_HOST)
        self.assertIn('strcmp(variable->key, "mupen64plus-EnableOverscan")', NATIVE_HOST)
        self.assertIn('strcmp(variable->key, "mupen64plus-OverscanTop")', NATIVE_HOST)
        self.assertIn('strcmp(variable->key, "mupen64plus-OverscanBottom")', NATIVE_HOST)
        self.assertRegex(
            NATIVE_HOST,
            r'(?s)mupen64plus-rdp-plugin"\) == 0\).*?'
            r'find_option_token\(\s*options, "gliden64"',
        )
        self.assertRegex(
            NATIVE_HOST,
            r'(?s)mupen64plus-rsp-plugin"\) == 0\).*?'
            r'find_option_token\(options, "hle"',
        )
        self.assertRegex(
            NATIVE_HOST,
            r'(?s)mupen64plus-ThreadedRenderer"\) == 0\).*?'
            r'find_option_token\(options, "False"',
        )
        self.assertRegex(
            NATIVE_HOST,
            r'(?s)mupen64plus-EnableOverscan"\) == 0\).*?'
            r'find_option_token\(\s*options, "Disabled"',
        )

    def test_genesis_and_n64_recipes_are_pinned_and_16k_aligned(self):
        for engine in ("blastem", "mupen64plus-next"):
            row = next(item for item in REGISTRY["engines"] if item["id"] == engine)
            self.assertEqual("compatible-candidate", row["license"]["distributionGate"])
            self.assertIsInstance(row["build"]["reproducible"], bool)
            self.assertFalse(row["shipped"])
            self.assertIn(f"{engine})", CORE_BUILD)
            audit = json.loads(
                (ROOT / "engines" / "audits" / f"{engine}-license.json")
                .read_text(encoding="utf-8")
            )
            self.assertEqual(engine, audit["engineId"])
            self.assertEqual(row["source"]["commit"], audit["sourceCommit"])
            self.assertEqual(
                row["source"]["archiveSha256"], audit["sourceArchiveSha256"]
            )
        blastem_recipe = CORE_BUILD.split("    blastem)", 1)[1].split(
            "    mupen64plus-next)", 1
        )[0]
        mupen_recipe = CORE_BUILD.split("    mupen64plus-next)", 1)[1].split(
            "    armsx2)", 1
        )[0]
        self.assertIn("-Wl,-z,max-page-size=16384", blastem_recipe)
        self.assertIn("PYTHONHASHSEED=0", blastem_recipe)
        blastem_patch = (
            ROOT / "engines" / "patches" / "blastem-libretro-android-portability.patch"
        ).read_text(encoding="utf-8")
        self.assertIn("$(LIBOBJDIR)/z80.o: LIBCFLAGS += -O1", blastem_patch)
        self.assertIn("-Wl,-z,max-page-size=16384", mupen_recipe)
        self.assertIn("-static-libstdc++", mupen_recipe)
        self.assertIn("ANDROID_GRAPHIC_BUFFER=0", mupen_recipe)
        self.assertIn('cat "$NDK_DIR/NOTICE.toolchain"', mupen_recipe)
        mupen_audit = json.loads(
            (ROOT / "engines" / "audits" / "mupen64plus-next-license.json")
            .read_text(encoding="utf-8")
        )
        self.assertNotIn("libc++_shared.so", mupen_audit["runtimeDependencies"])
        self.assertTrue(any(
            component.get("license") == "Apache-2.0 WITH LLVM-exception"
            for component in mupen_audit["components"]
        ))

    def test_gameplay_uses_only_single_task_main_activity(self):
        self.assertIn(
            'android:launchMode="singleTask" android:name="org.pegasus_frontend.android.MainActivity"',
            BUILD,
        )
        self.assertNotIn('android:name="com.thorium.preview.game.LucentGameActivity"', BUILD)
        self.assertNotIn('android:name="com.thorium.preview.game.InternalGameLaunchActivity"', BUILD)
        self.assertNotIn('android:name="com.thorium.preview.GameLaunchRouter"', BUILD)

    def test_no_qualification_activity_trampoline_is_packaged(self):
        self.assertNotIn(
            'android:name="com.thorium.preview.game.QualificationLaunchActivity"',
            BUILD,
        )
        source = (ROOT / "unified-android" / "tools" /
                  "run_phase1a_activity_qa.py").read_text(encoding="utf-8")
        self.assertIn("org.pegasus_frontend.android.MainActivity", source)
        self.assertIn("com.thorium.preview.LAUNCH_INTERNAL_GAME", source)

    def test_activity_harness_covers_every_runnable_qualification_system(self):
        module_spec = importlib.util.spec_from_file_location(
            "phase1_activity_qa",
            ROOT / "unified-android" / "tools" / "run_phase1a_activity_qa.py",
        )
        module = importlib.util.module_from_spec(module_spec)
        assert module_spec.loader is not None
        import sys
        sys.modules[module_spec.name] = module
        module_spec.loader.exec_module(module)
        self.assertEqual(
            {
                "nes", "snes", "gb", "gbc", "gba", "sg1000",
                "mastersystem", "gamegear", "psx", "nds",
                "zxspectrum", "arcade", "neogeo", "dos", "windows", "pcengine", "ngp",
                "wonderswancolor",
            },
            {case.system for case in module.CASES},
        )
        registry_systems = {
            system for engine in REGISTRY["engines"] for system in engine["systems"]
        }
        self.assertEqual(
            registry_systems,
            {case.system for case in module.CASES} |
            {case.system for case in module.BLOCKED_CASES},
        )
        self.assertFalse(
            {case.system for case in module.CASES} &
            {case.system for case in module.BLOCKED_CASES}
        )
        source = (ROOT / "unified-android" / "tools" /
                  "run_phase1a_activity_qa.py").read_text(encoding="utf-8")
        self.assertIn("In-window route accepted", source)
        self.assertIn("oneActivityWindow", source)
        self.assertIn("Quick Resume committed", source)
        self.assertIn("Quick Resume restored", source)
        self.assertIn("centralVisibleFraction", source)
        self.assertIn("Core frame presented", source)
        self.assertIn('"apkSha256": sha256_file(apk)', source)
        self.assertTrue(module.screenshot_is_visible(43_601, 83))
        self.assertTrue(module.screenshot_is_visible(100, 1))
        self.assertFalse(module.screenshot_is_visible(99, 83))
        self.assertFalse(module.screenshot_is_visible(43_601, 0))
        self.assertEqual([], module.app_crash_markers(
            "F libc: Fatal signal 11 in tid 3801, pid 1746 (mediaserver64)\n"
            "F DEBUG: Cmdline: /system/bin/mediaserver\n"
            "F DEBUG: pid: 1746, tid: 3801 >>> /system/bin/mediaserver <<<\n"
        ))
        self.assertEqual(["Fatal signal"], module.app_crash_markers(
            "F libc: Fatal signal 11 in tid 41, pid 42 (m.thorium.preview)\n"
            "F DEBUG: Cmdline: com.thorium.preview\n"
            "F DEBUG: pid: 42, tid: 41 >>> com.thorium.preview <<<\n"
        ))
        self.assertEqual(["FATAL EXCEPTION"], module.app_crash_markers(
            "E AndroidRuntime: FATAL EXCEPTION: main\n"
            "E AndroidRuntime: Process: com.thorium.preview, PID: 42\n"
        ))
        telemetry = module.runtime_telemetry(
            "I/LucentEngine: Runtime telemetry engine=mesen system=nes "
            "frames=180 elapsedMs=3000 measuredFps=60.000 targetFps=60.000 "
            "audioFrames=12345 audioStarted=true\n",
            module.Case("nes", "QA", "mesen", "opaque-case"),
        )
        self.assertIsNotNone(telemetry)
        self.assertTrue(telemetry["pacingWithinTolerance"])
        self.assertTrue(telemetry["audioStarted"])
        self.assertEqual(12345, telemetry["audioFrames"])
        telemetry = module.runtime_telemetry(
            "I/LucentEngine: Runtime telemetry engine=mesen system=nes "
            "frames=300 elapsedMs=6000 measuredFps=50.000 targetFps=60.000 "
            "audioFrames=100 audioStarted=true\n"
            "I/LucentEngine: Runtime telemetry engine=mesen system=nes "
            "frames=300 elapsedMs=5000 measuredFps=60.000 targetFps=60.000 "
            "audioFrames=200 audioStarted=true\n",
            module.Case("nes", "QA", "mesen", "opaque-case"),
        )
        self.assertEqual(60.0, telemetry["measuredFps"])
        self.assertTrue(telemetry["pacingWithinTolerance"])
        slow = module.runtime_telemetry(
            "I/LucentEngine: Runtime telemetry engine=mesen system=nes "
            "frames=300 elapsedMs=5100 measuredFps=58.000 targetFps=60.000 "
            "audioFrames=200 audioStarted=true\n",
            module.Case("nes", "QA", "mesen", "opaque-case"),
        )
        self.assertFalse(slow["pacingWithinTolerance"])
        self.assertIn("Runtime telemetry engine=", source)
        self.assertIn("Input consumed engine=", source)
        self.assertIn("sendevent", source)
        self.assertIn(
            'legacy_in_recents = f"{LEGACY_PACKAGE}/" in recent_state',
            source,
        )
        self.assertNotIn("legacy_in_recents = LEGACY_PACKAGE in recent_state", source)
        recents = """  Recent tasks:
  * Recent #0:
    mActivityComponent=com.thorium.preview/.PreviewActivity
  Visible recent tasks (most recent first):
  * RecentTaskInfo #0:
    realActivity={com.thorium.preview/org.pegasus_frontend.android.MainActivity}
    isExcluded=false
"""
        self.assertEqual(
            {"com.thorium.preview/org.pegasus_frontend.android.MainActivity"},
            module.package_recents_tasks(recents),
        )
        windows = """Window #0 Window{abc u0 com.thorium.preview/org.pegasus_frontend.android.MainActivity}:
    mDisplayId=0
Window #1 Window{def u0 com.thorium.preview/com.thorium.preview.PreviewActivity}:
    mDisplayId=4
"""
        self.assertEqual(
            {
                "com.thorium.preview/org.pegasus_frontend.android.MainActivity": [0],
                "com.thorium.preview/com.thorium.preview.PreviewActivity": [4],
            },
            module.package_window_displays(windows),
        )
        self.assertNotIn("MAIN_ACTIVITY not in display_zero", source)
        self.assertNotIn("PreviewActivity\" not in display_four", source)
        module.validate_runner_coverage()

        aosp_activity = (
            "    * Hist  #0: ActivityRecord{a8facd1 u0 "
            "com.thorium.preview/org.pegasus_frontend.android.MainActivity t188}\n"
        )
        original_dump = module.activity_dump
        try:
            module.activity_dump = lambda _adb, _serial: aosp_activity
            self.assertEqual(
                {
                    "activityToken": "a8facd1",
                    "taskId": "188",
                    "component": module.GAME_ACTIVITY,
                },
                module.main_activity_identity(Path("adb"), "emulator-5554"),
            )
        finally:
            module.activity_dump = original_dump

    def test_physical_library_matrix_is_private_and_non_destructive(self):
        source = (ROOT / "unified-android" / "tools" /
                  "run_phase1_physical_library_qa.py").read_text(encoding="utf-8")
        self.assertIn("up to three", source)
        self.assertIn("selected-content-private.json", source)
        self.assertIn('"userContentModified": False', source)
        self.assertIn("require_runtime_telemetry=True", source)
        self.assertIn("require_stop_hold=True", source)
        self.assertIn('"megadrive": ("blastem"', source)
        self.assertIn('"n64": ("mupen64plus-next"', source)
        self.assertIn('bytes.fromhex("80 37 12 40")', source)
        self.assertIn('read_range(adb_path, serial, path, 0x100, 4) == b"SEGA"', source)
        self.assertNotIn('"pm", "clear"', source)
        self.assertNotRegex(source, r'\b(?:rm|mv)\b')

    def test_artifact_modes_are_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            libraries = Path(directory)
            (libraries / "liblucent_libretro_host.so").write_bytes(b"host")
            release = MODULE.generate(ROOT / "engines" / "registry.json", libraries)
            self.assertEqual([], release["artifacts"])

            (libraries / "liblucent_core_mesen.so").write_bytes(b"qualification core")
            qualification = MODULE.generate(ROOT / "engines" / "registry.json", libraries)
            self.assertEqual(["mesen"], [row["engineId"] for row in qualification["artifacts"]])
            self.assertRegex(qualification["artifacts"][0]["sha256"], r"^[0-9a-f]{64}$")

    def test_unprefixed_build_flags_are_rejected_before_any_default(self):
        # The zero-core-APK incident: unprefixed flags silently defaulted every
        # gate to 0. The guard must run BEFORE the first LUCENT_ assignment.
        guard = BUILD.index("for stray_flag in INCLUDE_EXPERIMENTAL_CORES")
        first_default = BUILD.index(
            "INCLUDE_EXPERIMENTAL_CORES=${LUCENT_INCLUDE_EXPERIMENTAL_CORES:-0}"
        )
        self.assertLess(guard, first_default)
        for name in (
            "INCLUDE_EXPERIMENTAL_CORES", "AUTOSELECT_EXPERIMENTAL_CORES",
            "REUSE_QUALIFICATION_CORES", "INCLUDE_PHASE2_PPSSPP",
            "REUSE_PHASE2_PPSSPP", "KEYSTORE", "STORE_PASS", "KEY_PASS",
            "KEY_ALIAS",
        ):
            self.assertRegex(
                BUILD,
                r"for stray_flag in [^\n]*(?:\\\n[^\n]*)*\b" + name + r"\b",
            )
        self.assertIn(
            'this build only reads LUCENT_%s', BUILD,
        )

    def test_misspelled_lucent_flags_are_rejected(self):
        unknown_guard = BUILD.index(
            "LUCENT_INCLUDE_*|LUCENT_REUSE_*|LUCENT_AUTOSELECT_*)"
        )
        first_default = BUILD.index(
            "INCLUDE_EXPERIMENTAL_CORES=${LUCENT_INCLUDE_EXPERIMENTAL_CORES:-0}"
        )
        self.assertLess(unknown_guard, first_default)
        self.assertIn("unknown build flag", BUILD)
        for known in (
            "LUCENT_INCLUDE_EXPERIMENTAL_CORES)",
            "LUCENT_AUTOSELECT_EXPERIMENTAL_CORES)",
            "LUCENT_REUSE_QUALIFICATION_CORES)",
            "LUCENT_INCLUDE_PHASE2_PPSSPP)",
            "LUCENT_REUSE_PHASE2_PPSSPP)",
        ):
            self.assertIn(known, BUILD)

    def test_signing_profile_is_explicit_and_debug_builds_are_loud(self):
        self.assertIn('SIGNING_PROFILE=${LUCENT_SIGNING_PROFILE:-debug}', BUILD)
        self.assertIn(
            'KEYSTORE=${LUCENT_KEYSTORE:?LUCENT_SIGNING_PROFILE=release '
            'requires LUCENT_KEYSTORE}', BUILD,
        )
        self.assertIn(
            'STORE_PASS=${LUCENT_STORE_PASS:?LUCENT_SIGNING_PROFILE=release '
            'requires LUCENT_STORE_PASS}', BUILD,
        )
        self.assertIn(
            'KEY_ALIAS=${LUCENT_KEY_ALIAS:?LUCENT_SIGNING_PROFILE=release '
            'requires LUCENT_KEY_ALIAS}', BUILD,
        )
        self.assertIn("DEBUG-SIGNED (qualification only)", BUILD)
        self.assertIn(
            'LUCENT_SIGNING_PROFILE must be debug or release', BUILD,
        )

    def test_alignment_verifier_gates_every_apk_after_one_app_check(self):
        one_app = BUILD.index("verify_one_app_apk.py")
        alignment = BUILD.index("verify_elf_alignment.py")
        self.assertLess(one_app, alignment)
        # No warn-only escape hatch: outside the strict release mode the
        # verifier still gates with the explicit allowlist.
        self.assertNotIn("16 KiB policy not met", BUILD)
        self.assertIn('--allow-4k-lib "$allowed_4k_lib"', BUILD)

    def test_base_apk_and_dependencies_are_sha256_pinned(self):
        self.assertRegex(BUILD, r"BASE_SHA256=[0-9a-f]{64}")
        dependency_hashes = re.findall(r'^\s*"([0-9a-f]{64})"\s*$', BUILD, re.M)
        self.assertGreaterEqual(len(dependency_hashes), 2)
        self.assertIn('if [ "$ACTUAL_BASE_SHA" != "$BASE_SHA256" ]; then', BUILD)


if __name__ == "__main__":
    unittest.main()
