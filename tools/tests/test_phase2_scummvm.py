import hashlib
import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
LOCK = ROOT / "engines" / "scummvm-source-lock.json"
BUILD = ROOT / "engines" / "build_scummvm_core.sh"
LIFECYCLE_PATCH = ROOT / "engines" / "patches" / "scummvm-emufusion-exit-autosave.patch"
CONTENT_LOCK = ROOT / "engines" / "scummvm-test-content-lock.json"
HOST = ROOT / "unified-android" / "native" / "emufusion_libretro_host.c"
JNI = ROOT / "unified-android" / "native" / "emufusion_libretro_jni.c"
JAVA_HOST = ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" / "LibretroHost.java"
SESSION = ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" / "game" / "LibretroEngineSession.java"
HOST_TEST = ROOT / "unified-android" / "native" / "tests" / "host_test.c"
AUDIT = ROOT / "engines" / "scummvm-dependency-audit.json"
COMPLIANCE = ROOT / "tools" / "generate_scummvm_compliance_bundle.py"
UNIFIED_BUILD = ROOT / "unified-android" / "build.sh"
PHASE2_REGISTRY = ROOT / "engines" / "phase2-registry.json"
PHASE2_OPT_IN = ROOT / "engines" / "phase2-qualification-opt-in.json"
PHASE2_VERIFY = ROOT / "unified-android" / "tools" / "verify_phase2_apk.py"
BOOTSTRAP = ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" / "game" / "InternalEngineBootstrap.java"
ACTIVITY_QA = ROOT / "unified-android" / "tools" / "run_phase2_activity_qa.py"


class ScummvmPhase2Test(unittest.TestCase):
    def setUp(self):
        self.lock = json.loads(LOCK.read_text())
        self.recipe = BUILD.read_text()
        self.lifecycle_patch = LIFECYCLE_PATCH.read_text()
        self.content_lock = json.loads(CONTENT_LOCK.read_text())
        self.audit = json.loads(AUDIT.read_text())

    def test_primary_source_and_dependencies_are_exactly_pinned(self):
        self.assertRegex(self.lock["core"]["commit"], r"^[0-9a-f]{40}$")
        self.assertRegex(self.lock["core"]["archiveSha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(2, len(self.lock["dependencies"]))
        for dependency in self.lock["dependencies"]:
            self.assertRegex(dependency["commit"], r"^[0-9a-f]{40}$")
            self.assertRegex(dependency["archiveSha256"], r"^[0-9a-f]{64}$")

    def test_recipe_is_offline_after_locked_archive_fetch(self):
        self.assertIn("EMUFUSION_OFFLINE_PINNED_DEPS=1", self.recipe)
        self.assertIn("configure_submodules.sh", self.recipe)
        self.assertIn("libmad/version", self.recipe)
        self.assertIn("APP_ABI=arm64-v8a", self.recipe)
        self.assertIn("APP_PLATFORM=android-21", self.recipe)
        self.assertIn("max-page-size=16384", self.recipe)
        self.assertIn("llvm-readelf", self.recipe)
        self.assertNotIn("git clone", self.recipe)
        self.assertNotIn("git fetch", self.recipe)

    def test_lifecycle_patch_is_locked_and_applied(self):
        locked_patch = self.lock["patches"][0]
        self.assertEqual("engines/patches/scummvm-emufusion-exit-autosave.patch",
                         locked_patch["path"])
        self.assertEqual(locked_patch["sha256"],
                         hashlib.sha256(LIFECYCLE_PATCH.read_bytes()).hexdigest())
        self.assertIn("patch -d \"$WORK/source\" -p1", self.recipe)
        self.assertIn("retro_emufusion_prepare_exit_autosave", self.lifecycle_patch)
        self.assertIn("saveEmuFusionExitAutosave", self.lifecycle_patch)
        self.assertIn("canSaveAutosaveCurrently", self.lifecycle_patch)
        self.assertIn("EMUFUSION_EXIT_AUTOSAVE_CANCELED", self.lifecycle_patch)
        self.assertIn("emufusion_write_resume_slot", self.lifecycle_patch)
        self.assertIn('" -x "', self.lifecycle_patch)

    def test_state_claim_is_fail_closed(self):
        configuration = self.lock["configuration"]
        self.assertFalse(configuration["genericSerialization"])
        self.assertEqual("engine-native-fail-closed-exit-autosave",
                         configuration["statePolicy"])
        self.assertEqual("retro_emufusion_prepare_exit_autosave",
                         configuration["hostPrepareExitSymbol"])
        self.assertEqual(120, configuration["prepareExitMaximumCoreFrames"])
        artifact = self.lock["artifact"]
        self.assertTrue(artifact["reproducible"])
        self.assertEqual(artifact["sha256"], artifact["firstCleanBuildSha256"])
        self.assertEqual(artifact["sha256"], artifact["secondCleanBuildSha256"])
        self.assertEqual("0x4000", artifact["ptLoadAlignment"])

    def test_artifact_matches_lock_when_present(self):
        artifact = self.lock["artifact"]
        path = ROOT / artifact["path"]
        if path.exists():
            self.assertEqual(artifact["size"], path.stat().st_size)
            self.assertEqual(artifact["sha256"],
                             hashlib.sha256(path.read_bytes()).hexdigest())

    def test_cached_archives_match_when_present(self):
        archives = [(self.lock["core"], "scummvm-")]
        archives.extend((dependency, "scummvm-libretro-deps-" if index == 0
                         else "scummvm-libretro-common-")
                        for index, dependency in enumerate(self.lock["dependencies"]))
        for entry, prefix in archives:
            path = ROOT / "engines" / "build" / "sources" / (
                prefix + entry["commit"] + ".tar.gz")
            if path.exists():
                self.assertEqual(entry["archiveSha256"],
                                 hashlib.sha256(path.read_bytes()).hexdigest())

    def test_exit_extension_is_wired_fail_closed_through_the_host(self):
        host = HOST.read_text()
        jni = JNI.read_text()
        java_host = JAVA_HOST.read_text()
        session = SESSION.read_text()
        native_test = HOST_TEST.read_text()
        self.assertIn('resolve_optional_symbol(host->library, "retro_emufusion_prepare_exit_autosave"',
                      host)
        self.assertIn("host->prepare_exit && !host->prepare_exit()", host)
        self.assertIn("Java_com_thorium_preview_LibretroHost_nativeUnloadGame", jni)
        self.assertIn("nativeUnloadGame(handle);", java_host)
        self.assertIn("active.unloadGame();", session)
        self.assertIn("callback.onSessionStopRejected", session)
        self.assertIn("unload_count() == 0", native_test)
        self.assertIn("emufusion_retro_run_frame(host, error, sizeof(error))", native_test)

    def test_official_freeware_device_fixture_is_pinned_but_not_bundled(self):
        fixture = self.content_lock["fixtures"][0]
        self.assertEqual("Flight of the Amazon Queen - Freeware Floppy Version",
                         fixture["title"])
        self.assertEqual("queen", fixture["engine"])
        self.assertEqual("official-download-only", fixture["distributionPolicy"])
        self.assertRegex(fixture["sha256"], r"^[0-9a-f]{64}$")
        self.assertTrue(fixture["url"].startswith("https://downloads.scummvm.org/"))
        self.assertFalse(fixture["bundleInApk"])

    def test_exact_dependency_compliance_gate_is_build_mandatory(self):
        self.assertEqual(self.lock["artifact"]["sha256"],
                         self.audit["coreArtifactSha256"])
        self.assertEqual(337, self.audit["externalObjectCount"])
        self.assertEqual(15, len(self.audit["components"]))
        self.assertEqual(4, len(self.audit["embeddedComponents"]))
        self.assertEqual(337, sum(entry["objectCount"]
                                  for entry in self.audit["components"]))
        self.assertEqual(94, sum(entry["objectCount"]
                                 for entry in self.audit["embeddedComponents"]))
        for component in self.audit["components"] + self.audit["embeddedComponents"]:
            self.assertNotEqual("NOASSERTION", component["spdx"])
            self.assertRegex(component["evidenceSha256"], r"^[0-9a-f]{64}$")
        self.assertIn("generate_scummvm_compliance_bundle.py", self.recipe)
        self.assertIn("scummvm-dependency-audit.json", self.recipe)
        compliance = COMPLIANCE.read_text()
        self.assertIn("unknown", self.audit["policy"].lower())
        self.assertIn("counts != expected", compliance)
        self.assertIn("core artifact does not match the audited binary", compliance)
        self.assertIn("license evidence changed", compliance)

    def test_phase2_qualification_package_wires_exact_core_runtime_and_notices(self):
        build = UNIFIED_BUILD.read_text()
        opt_in = json.loads(PHASE2_OPT_IN.read_text())
        registry = json.loads(PHASE2_REGISTRY.read_text())
        verify = PHASE2_VERIFY.read_text()
        bootstrap = BOOTSTRAP.read_text()
        enabled = {entry["id"]: entry for entry in opt_in["engines"]}["scummvm"]
        row = {entry["id"]: entry for entry in registry["engines"]}["scummvm"]
        self.assertEqual("libemufusion_core_scummvm.so", enabled["libraryName"])
        self.assertEqual("phase2-system/scummvm/scummvm", enabled["systemAssetRoot"])
        self.assertEqual(["scummvm"], enabled["libraryRouteSystems"])
        self.assertEqual("libretro-core", row["route"])
        self.assertTrue(row["license"]["dependencyAuditComplete"])
        self.assertTrue(row["gates"]["license"])
        self.assertTrue(row["gates"]["dependencies"])
        self.assertIn("build_scummvm_core.sh", build)
        self.assertIn("scummvm-compliance", build)
        self.assertIn("scummvm-system/scummvm", build)
        self.assertIn('"scummvm": ["scummvm"]', verify)
        self.assertIn('"scummvm".equals(entry.id)', bootstrap)
        self.assertIn("LibretroEngineSpec.phaseTwo(entry)", bootstrap)

    def test_physical_qa_understands_scummvm_native_save_and_telemetry(self):
        harness = ACTIVITY_QA.read_text()
        self.assertIn('parser.add_argument("--scummvm-rom"', harness)
        self.assertIn('Case("scummvm", "scummvm"', harness)
        self.assertIn("SCUMMVM_HEALTH = re.compile", harness)
        self.assertIn("engineNativeExitAutosaveCommitted", harness)
        self.assertIn("engineNativeResumePresentedAfterProcessDeath", harness)
        self.assertIn("ScummVM engine-native exit autosave commit", harness)


if __name__ == "__main__":
    unittest.main()
