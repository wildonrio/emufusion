import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "unified-android" / "build.sh"
OPT_IN = ROOT / "engines" / "phase2-qualification-opt-in.json"
ACTIVITY_QA = ROOT / "unified-android" / "tools" / "run_phase2_activity_qa.py"
SESSION = (ROOT / "unified-android" / "src" / "com" / "thorium" /
           "preview" / "game" / "PpssppGlesEngineSession.java")
CATALOG = (ROOT / "unified-android" / "src" / "com" / "thorium" /
           "preview" / "game" / "Phase2QualificationCatalog.java")
INTERNAL_CATALOG = (ROOT / "unified-android" / "src" / "com" / "thorium" /
                    "preview" / "game" / "InternalEngineCatalog.java")
PHASE1_SESSION = (ROOT / "unified-android" / "src" / "com" / "thorium" /
                  "preview" / "game" / "LibretroEngineSession.java")
PREVIEW_ACTIVITY = (ROOT / "android-companion" / "src" / "com" / "thorium" /
                    "preview" / "PreviewActivity.java")
PREVIEW_SERVICE = (ROOT / "android-companion" / "src" / "com" / "thorium" /
                   "preview" / "PreviewService.java")
LUCENT_APPLICATION = (ROOT / "unified-android" / "src" / "com" / "thorium" /
                      "preview" / "LucentApplication.java")
BROWSER_ACTIVITY = (ROOT / "android-companion" / "src" / "com" / "thorium" /
                    "preview" / "BrowserActivity.java")
BRANDING_PATCH = (ROOT / "unified-android" / "tools" /
                  "patch_emufusion_branding.py")
VULKAN_BACKEND = (ROOT / "unified-android" / "native" /
                  "lucent_android_vulkan_backend.c")


class PhaseTwoAndroidPackagingTest(unittest.TestCase):
    def setUp(self):
        self.build = BUILD.read_text(encoding="utf-8")
        self.harness = ACTIVITY_QA.read_text(encoding="utf-8")
        self.opt_in = json.loads(OPT_IN.read_text(encoding="utf-8"))

    def test_default_build_packages_internal_dolphin(self):
        self.assertIn(
            "INCLUDE_PHASE2_PPSSPP=${LUCENT_INCLUDE_PHASE2_PPSSPP:-1}",
            self.build,
        )
        self.assertIn('if [ "$INCLUDE_PHASE2_PPSSPP" = 1 ]; then', self.build)
        self.assertNotIn("LUCENT_AUTOSELECT_PHASE2_PPSSPP", self.build)
        self.assertFalse(self.opt_in["autoSelect"])

    def test_qualification_build_verifies_exact_phase2_artifact(self):
        self.assertIn("validate_phase2_registry.py", self.build)
        self.assertIn("--verify-artifacts", self.build)
        self.assertIn(
            "for phase2_core in applewin puae beetle-saturn dolphin ppsspp play armsx2 flycast azahar virtualjaguar",
            self.build,
        )
        self.assertIn("build_scummvm_core.sh", self.build)
        self.assertIn("liblucent_core_${normalized_core}.so", self.build)
        self.assertIn("phase2-engine-artifacts.json", self.build)
        self.assertIn("generate_phase2_sbom.py", self.build)
        self.assertIn("phase2-sbom.spdx.json", self.build)
        self.assertNotIn(
            'android:name="com.thorium.preview.game.QualificationLaunchActivity"',
            self.build,
        )
        self.assertNotIn(
            'android:name="com.thorium.launchbridge.StopButtonService"',
            self.build,
        )
        self.assertNotIn(
            'android:name="com.thorium.launchbridge.LaunchActivity"',
            self.build,
        )
        # RomLaunchActivity is now the external-route content-URI trampoline
        # (non-exported, no-history, excluded from recents) and IS packaged.
        self.assertIn(
            'android:name="com.thorium.preview.RomLaunchActivity"',
            self.build,
        )
        self.assertIn(
            "! -path '*/com/thorium/launchbridge/StopButtonService.java'",
            self.build,
        )
        self.assertIn('android:launchMode="singleTask" android:name="org.pegasus_frontend.android.MainActivity"', self.build)
        self.assertIn("com.thorium.preview.LAUNCH_INTERNAL_GAME", self.harness)
        self.assertIn("oneActivityWindow", self.harness)
        self.assertIn("phase2-qualification.apk", self.build)

    def test_runtime_assets_and_license_are_packaged_only_with_core(self):
        self.assertIn("phase2-system/ppsspp", self.build)
        self.assertIn("ppsspp-LICENSE.txt", self.build)
        self.assertIn("phase2-qualification-opt-in.json", self.build)
        row = next(item for item in self.opt_in["engines"]
                   if item["id"] == "ppsspp")
        self.assertEqual("ppsspp", row["id"])
        self.assertEqual(
            "fa50bb1976065c4f8b1b47af227d367fe9771555", row["commit"]
        )
        self.assertEqual("phase2-system/ppsspp/PPSSPP", row["systemAssetRoot"])
        self.assertRegex(row["systemAssetRevision"], r"^[0-9a-f]{64}$")
        self.assertEqual(["PPSSPP/compat.ini"], row["systemAssetRequiredFiles"])
        self.assertEqual(
            {"applewin", "puae", "beetle-saturn", "dolphin", "ppsspp", "play", "armsx2", "flycast",
             "azahar", "virtualjaguar", "scummvm"},
            {row["id"] for row in self.opt_in["engines"]},
        )
        runtimes = {row["id"]: row["runtime"] for row in self.opt_in["engines"]}
        self.assertEqual("vulkan-libretro", runtimes["armsx2"])
        self.assertEqual("vulkan-libretro", runtimes["azahar"])
        self.assertEqual("vulkan-libretro", runtimes["dolphin"])
        armsx2 = next(row for row in self.opt_in["engines"]
                      if row["id"] == "armsx2")
        self.assertIn("pcsx2/resources/patches.zip",
                      armsx2["systemAssetRequiredFiles"])
        self.assertTrue(all(runtime == "gles-libretro"
                            for engine_id, runtime in runtimes.items()
                            if engine_id not in {"armsx2", "azahar", "dolphin"}))
        applewin = next(row for row in self.opt_in["engines"]
                        if row["id"] == "applewin")
        self.assertEqual(["apple2"], applewin["libraryRouteSystems"])
        self.assertEqual("user-files", applewin["firmwareProfiles"][0]["mode"])
        self.assertEqual(6, len(applewin["firmwareProfiles"][0]["alternatives"][0]))
        self.assertIn("liblucent_core_${normalized_core}.so", self.build)
        self.assertIn("applewin-firmware-policy.json", self.build)
        puae = next(row for row in self.opt_in["engines"] if row["id"] == "puae")
        profiles = {row["system"]: row for row in puae["firmwareProfiles"]}
        self.assertEqual("builtin", profiles["amiga"]["mode"])
        self.assertEqual("user-files", profiles["amigacd32"]["mode"])
        self.assertEqual(["amiga", "amigacd32"], puae["libraryRouteSystems"])
        self.assertIn("puae-source-lock.json", self.build)
        self.assertIn("puae-firmware-policy.json", self.build)
        saturn = next(row for row in self.opt_in["engines"]
                      if row["id"] == "beetle-saturn")
        self.assertEqual("user-files", saturn["firmwareProfiles"][0]["mode"])

    def test_physical_input_proof_requires_mapped_down_and_up_telemetry(self):
        harness = ACTIVITY_QA.read_text(encoding="utf-8")
        session = SESSION.read_text(encoding="utf-8")
        self.assertIn("Physical input dispatched engine=", session)
        self.assertIn("mapped physical A-button down event", harness)
        self.assertIn("mapped physical A-button up event", harness)
        self.assertIn('"physicalAInputDownDispatched": True', harness)
        self.assertIn('"physicalAInputUpDispatched": input_up is not None', harness)
        self.assertIn("Input consumed engine={case.engine}", harness)

    def test_phase2_uses_shared_identity_lower_blank_and_stop_hold_gates(self):
        harness = ACTIVITY_QA.read_text(encoding="utf-8")
        self.assertIn(
            "return phase1_qa_module().strict_gameplay_identity(adb_path, serial)",
            harness,
        )
        self.assertIn("secondary_blank_metrics", harness)
        self.assertIn('"thorLowerDisplayBlankDuringGameplay": lower_blank', harness)
        self.assertIn("event_node, 314, hold_seconds=1.15", harness)
        self.assertIn('"recents": str(recents_evidence)', harness)

    def test_hardware_cores_use_pinned_frontend_fbo_path_in_main_activity(self):
        session = SESSION.read_text(encoding="utf-8")
        self.assertIn('final int presentationPolicy = ("flycast".equals(entry.id) ||',
                      session)
        self.assertIn('"ppsspp".equals(entry.id) ||', session)
        self.assertIn('"mupen64plus-next".equals(entry.id) ||', session)
        self.assertIn('"dolphin".equals(entry.id)) ?', session)
        self.assertIn(".PRESENT_FRONTEND_FBO", session)
        self.assertIn(".PRESENT_DIRECT_WINDOW", session)
        self.assertIn('"Renderer policy engine="', session)
        self.assertIn('" sourceTimeline=" + (filteredSourceTimeline ?', session)
        self.assertIn('"Producer clock engine="', session)
        self.assertIn('" stamp=core-run-sequence"', session)
        self.assertIn('"Surface available engine="', session)

    def test_both_sessions_emit_the_canonical_commit_marker(self):
        # Every acceptance harness waits for this exact phrasing; the phase 2
        # session silently diverging cost a real device run (36ef96d2 N64).
        marker = '"Quick Resume committed engine="'
        self.assertIn(marker, SESSION.read_text(encoding="utf-8"))
        self.assertIn(marker, PHASE1_SESSION.read_text(encoding="utf-8"))

    def test_state_identity_binds_exact_packaged_core_artifact(self):
        phase2_catalog = CATALOG.read_text(encoding="utf-8")
        phase2_session = SESSION.read_text(encoding="utf-8")
        phase1_catalog = INTERNAL_CATALOG.read_text(encoding="utf-8")
        phase1_session = PHASE1_SESSION.read_text(encoding="utf-8")
        self.assertIn("final String coreArtifactSha256", phase2_catalog)
        self.assertIn("new Entry(id, systems, commit, expectedHash", phase2_catalog)
        self.assertIn("entry.coreArtifactSha256", phase2_session)
        self.assertIn('entry.sourceCommit + ":sha256:"', phase2_session)
        self.assertIn("public final String coreArtifactSha256", phase1_catalog)
        self.assertIn("artifact.sha256", phase1_catalog)
        self.assertIn("entry.coreArtifactSha256", phase1_session)
        self.assertIn('entry.sourceCommit + ":sha256:"', phase1_session)

    def test_phase2_qa_state_namespace_is_strict_and_production_is_fail_closed(self):
        host = (ROOT / "unified-android" / "src" / "com" / "thorium" /
                "preview" / "game" / "InWindowGameHost.java").read_text(
                    encoding="utf-8")
        request = (ROOT / "unified-android" / "src" / "com" / "thorium" /
                   "preview" / "game" / "GameLaunchRequest.java").read_text(
                       encoding="utf-8")
        phase2_session = SESSION.read_text(encoding="utf-8")
        phase1_session = PHASE1_SESSION.read_text(encoding="utf-8")
        self.assertIn('Pattern.compile("qa-[0-9a-f]{32}")', host)
        self.assertIn('source.getBooleanExtra("qualification_only", false)', host)
        self.assertIn("boolean phaseTwoNamespace = phaseTwo != null", host)
        self.assertIn("boolean phaseOneNamespace = approvedPhaseOne;", host)
        namespace = host[host.index('String qualificationSession = "";'):]
        namespace = namespace[:namespace.index('FrameGenerationSettings.Mode launchMode')]
        self.assertNotIn("FrameGenerationSettings.qualificationTransport(", namespace)
        self.assertIn("!phaseTwoNamespace && !phaseOneNamespace", host)
        self.assertIn('qualification_session")).isEmpty()', host)
        self.assertIn("EXTRA_QUALIFICATION_SESSION", request)
        self.assertIn('":qa:" + request.qualificationSession', phase2_session)
        self.assertIn('"engine-saves-qa/" + request.qualificationSession',
                      phase2_session)
        self.assertIn("Isolated qualification runtime state engine=", phase2_session)
        self.assertNotIn(
            "entry.phaseTwoQualification &&\n                        "
            "!launch.qualificationSession.isEmpty()",
            phase1_session,
        )
        self.assertIn(
            'String saveRoot = !launch.qualificationSession.isEmpty() ?',
            phase1_session,
        )
        self.assertIn('\":qa:\" + launch.qualificationSession', phase1_session)
        self.assertIn("Isolated qualification runtime state engine=",
                      phase1_session)
        self.assertIn('"--ez", "qualification_only", "true"', self.harness)
        self.assertIn(
            "gameplay_identity = launch(adb_path, serial, case, qualification_session)",
            self.harness,
        )
        self.assertIn(
            "adb_path, serial, case, qualification_session\n    )",
            self.harness,
        )
        self.assertIn("--qualification-session", self.harness)

    def test_catalog_enforces_registry_minimum_api_and_3ds_is_in_qa_matrix(self):
        catalog = CATALOG.read_text(encoding="utf-8")
        harness = ACTIVITY_QA.read_text(encoding="utf-8")
        self.assertIn('android.optInt("minApi", Integer.MAX_VALUE)', catalog)
        self.assertIn("Build.VERSION.SDK_INT < minimumApi", catalog)
        self.assertIn('parser.add_argument("--3ds-rom", action="append"', harness)
        self.assertIn('Case("3ds", "azahar"', harness)

    def test_vulkan_sync_fence_stays_signalled_while_core_records(self):
        backend = VULKAN_BACKEND.read_text(encoding="utf-8")
        method = backend.split(
            "bool lucent_android_vulkan_run_and_present", 1
        )[1].split(
            "bool lucent_android_vulkan_detach", 1
        )[0]
        run_frame = method.index("lucent_retro_run_frame")
        reset_fence = method.index("vkResetFences")
        queue_submit = method.index("vkQueueSubmit")
        self.assertLess(run_frame, reset_fence)
        self.assertLess(reset_fence, queue_submit)
        self.assertIn("self-deadlock", method)

    def test_physical_matrix_covers_every_packaged_phase2_engine_and_system(self):
        harness = ACTIVITY_QA.read_text(encoding="utf-8")
        for argument in (
                "--apple2-rom", "--amiga-rom", "--amigacd32-rom", "--saturn-rom",
                "--gamecube-rom", "--wii-rom",
                "--play-ps2-rom", "--armsx2-ps2-rom", "--dreamcast-rom",
                "--naomi-rom", "--atomiswave-rom", "--3ds-rom",
                "--jaguar-rom"):
            self.assertIn(argument, harness)
        for case in (
                'Case("apple2", "applewin"',
                'Case("amiga", "puae"', 'Case("amigacd32", "puae"',
                'Case("saturn", "beetle-saturn"', 'Case("psp", "ppsspp"',
                'Case("gamecube", "dolphin"', 'Case("wii", "dolphin"',
                'Case("ps2", "play"',
                'Case("ps2", "armsx2"', 'Case("dreamcast", "flycast"',
                'Case("naomi", "flycast"',
                'Case("atomiswave", "flycast"',
                'Case("3ds", "azahar"',
                'Case("jaguar", "virtualjaguar"'):
            self.assertIn(case, harness)
        self.assertIn("def case_artifact_prefix(case: Case)", harness)
        self.assertIn('f"{artifact_prefix}-gameplay-activities.txt"', harness)
        self.assertNotIn('if record["status"] == "FAIL":\n            break', harness)
        self.assertIn('parser.add_argument(\n        "--require-three-titles"', harness)
        self.assertIn('"threeTitleReleaseGate": args.require_three_titles', harness)
        self.assertIn('if len(supplied[system]) < 3', harness)

    def test_heavy_jit_health_uses_rolling_rate_and_stable_underruns(self):
        harness = ACTIVITY_QA.read_text(encoding="utf-8")
        self.assertIn(
            'effective_fps = latest.get("intervalFps", latest["fps"])',
            harness,
        )
        self.assertIn(
            'Case("3ds", "azahar", Path(rom).stem, rom, 55.0, False, 32_728)',
            harness,
        )

    def test_only_exactly_qualified_phase2_systems_enter_normal_library_routes(self):
        catalog = CATALOG.read_text(encoding="utf-8")
        routes = {
            row["id"]: row.get("libraryRouteSystems", [])
            for row in self.opt_in["engines"]
        }
        self.assertEqual({
            "applewin": ["apple2"],
            "puae": ["amiga", "amigacd32"], "beetle-saturn": [],
            "dolphin": ["gamecube", "wii"], "ppsspp": ["psp"],
            "play": [], "armsx2": ["ps2"], "flycast": ["dreamcast"],
            "azahar": ["3ds"], "virtualjaguar": [], "scummvm": ["scummvm"],
        }, routes)
        self.assertIn("public static String libraryEngineIdForSystem", catalog)
        self.assertIn('if (!match.isEmpty()) return "";', catalog)

    def test_secondary_preview_is_private_and_primary_display_fails_closed(self):
        preview = PREVIEW_ACTIVITY.read_text(encoding="utf-8")
        service = PREVIEW_SERVICE.read_text(encoding="utf-8")
        self.assertIn('android:exported="false"', self.build)
        self.assertIn(
            '<service android:name="com.thorium.preview.PreviewService" android:exported="false"/>',
            self.build,
        )
        self.assertIn("display.getDisplayId() == Display.DEFAULT_DISPLAY", preview)
        self.assertIn("finishAndRemoveTask();", preview)
        self.assertIn("launchPlayerOnSecondary(new Intent(this, PreviewActivity.class)",
                      service)
        self.assertIn(".setAction(ACTION_BLANK)", service)
        self.assertGreaterEqual(
            preview.count("PreviewService.ACTION_BLANK.equals("), 2
        )

    def test_preview_service_enters_foreground_before_slow_initialization(self):
        service = PREVIEW_SERVICE.read_text(encoding="utf-8")
        preview = PREVIEW_ACTIVITY.read_text(encoding="utf-8")
        application = LUCENT_APPLICATION.read_text(encoding="utf-8")
        on_create = service.split("public void onCreate()", 1)[1].split(
            "public int onStartCommand", 1
        )[0]
        foreground = on_create.index("ensureForeground()")
        for slower_work in (
            "new ImportManager(this)",
            "new UpdateManager(this)",
            "LaunchMetadataRouter.normalize(this)",
            "ThemeInstaller.installBundledIfNeeded",
        ):
            self.assertLess(foreground, on_create.index(slower_work))
        on_start = service.split("public int onStartCommand", 1)[1].split(
            "public IBinder onBind", 1
        )[0]
        self.assertLess(on_start.index("ensureForeground()"),
                        on_start.index("ACTION_GAMEPLAY.equals"))
        self.assertNotIn(
            "startForegroundService(new Intent(this, PreviewService.class))",
            preview,
        )
        self.assertIn("startForegroundService(service)", application)
        self.assertIn("Build.VERSION.SDK_INT >= Build.VERSION_CODES.O", application)

    def test_in_app_browser_does_not_delegate_deep_links_to_other_apps(self):
        browser = BROWSER_ACTIVITY.read_text(encoding="utf-8")
        method = browser.split("private boolean openUrl", 1)[1].split(
            "private final class BrowserDownloadListener", 1
        )[0]
        self.assertNotIn("startActivity", method)
        self.assertIn("Only web links and downloads open inside EmuFusion", method)

    def test_theme_publication_invalidates_qml_cache(self):
        source = (ROOT / "android-companion" / "src" / "com" / "thorium" /
                  "preview" / "ThemeInstaller.java").read_text(encoding="utf-8")
        publish = source.split("private static void publishStagedFile", 1)[1].split(
            "static String installedVersion", 1
        )[0]
        self.assertIn('"theme.qml".equals(relative)', publish)
        self.assertIn("target.setLastModified(cacheBuster)", publish)
        self.assertIn("replacedTimestamp + 1L", publish)

    def test_visible_upstream_branding_is_rewritten_but_abi_names_are_not(self):
        branding = BRANDING_PATCH.read_text(encoding="utf-8")
        self.assertIn("patch_emufusion_branding.py", self.build)
        self.assertIn('"Exit Pegasus"', branding)
        self.assertIn('"Pegasus couldn\'t find any games on your device.', branding)
        self.assertIn('"Lucent Frontend - version"', branding)
        self.assertIn("Lucent has permission for", branding)
        self.assertNotIn('replace("Pegasus", "Lucent ")', branding)
        self.assertNotIn('"Pegasus.Model"', branding)
        self.assertNotIn('"PegasusProvider"', branding)

    def test_build_emits_content_addressed_immutable_qa_artifact(self):
        self.assertIn("OUTPUT_SHA=$(shasum -a 256", self.build)
        self.assertIn("phase2-qualification-$OUTPUT_SHA.apk", self.build)
        self.assertIn("Immutable Lucent artifact collision", self.build)
        self.assertIn("printf '%s\\n' \"$IMMUTABLE_OUTPUT\"", self.build)


if __name__ == "__main__":
    unittest.main()
